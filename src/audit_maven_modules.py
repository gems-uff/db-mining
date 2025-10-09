#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auditoria Maven (DB-mining) — v2 (recursivo + ancestral correto)

O que faz:
- Para cada projeto (owner/name) vindo do banco/lista (get_or_create_projects):
  1) Verifica se há pom.xml na raiz.
  2) Coleta <modules> de forma RECUSIVA e valida:
     - diretório existe
     - existe pom.xml no módulo
     - módulo declara <parent> apontando para o ancestral declarado mais próximo
       (e se não houver ancestral declarado, compara com o POM raiz).
  3) Lista pom.xml existentes fora da árvore de módulos declarados (POMs "não declarados") e informa:
     - caminho relativo e absoluto
     - profundidade (nº de barras)
     - ancestral declarado mais próximo (se existir)
     - se aponta parent correto para o ancestral esperado
Saídas:
- projetos.csv: resumo por repositório
- modulos.csv : status por módulo/subpom (inclui info detalhada de undeclared POMs)
- (opcional) XLSX consolidado se pandas estiver disponível
"""

import os, re, csv, argparse
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple, Optional

# === dependências do seu projeto ===
import database as db
from extract import get_or_create_projects, read_args
from util import REPOS_DIR, yellow

# opcional XLSX
try:
    import pandas as pd
    HAS_PANDAS = True
except Exception:
    HAS_PANDAS = False

IGNORES = {
    ".git", "target", "build", "dist", "out", "node_modules", "venv",
    ".venv", "__pycache__", ".idea", ".vscode", ".mvn", ".gradle"
}

# ---------------------------------------------------------------------------
# Helpers XML / Maven
# ---------------------------------------------------------------------------

def _read_xml_ns_aware(p: Path):
    """Retorna (root, txt, q) com helper q(tag) para lidar com namespace; root=None se parse falhar."""
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None, "", None
    try:
        root = ET.fromstring(txt)
    except ET.ParseError:
        return None, txt, None
    ns_uri = root.tag.split('}')[0].strip('{') if root.tag.startswith('{') else None
    def q(name: str):
        return f"{{{ns_uri}}}{name}" if ns_uri else name
    return root, txt, q

def _text_of(node):
    return (node.text or "").strip() if node is not None and node.text else None

def _extract_gav(pom_path: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Retorna (groupId, artifactId, version) do POM; herda gid/version do <parent> se ausentes."""
    root, txt, q = _read_xml_ns_aware(pom_path)
    if root is None:
        # fallback simples
        def rgx(tag):
            m = re.search(rf"<{tag}>([^<]+)</{tag}>", txt)
            return m.group(1).strip() if m else None
        gid, aid, ver = rgx("groupId"), rgx("artifactId"), rgx("version")
        if not gid or not ver:
            mg = re.search(r"<parent>.*?<groupId>([^<]+)</groupId>.*?</parent>", txt, re.S|re.I)
            mv = re.search(r"<parent>.*?<version>([^<]+)</version>.*?</parent>", txt, re.S|re.I)
            gid = gid or (mg.group(1).strip() if mg else None)
            ver = ver or (mv.group(1).strip() if mv else None)
        return gid, aid, ver

    gid = _text_of(root.find(q("groupId")))
    aid = _text_of(root.find(q("artifactId")))
    ver = _text_of(root.find(q("version")))
    par = root.find(q("parent"))
    if par is not None:
        pg = _text_of(par.find(q("groupId")))
        pv = _text_of(par.find(q("version")))
        gid = gid or pg
        ver = ver or pv
    return gid, aid, ver

def _list_declared_modules(pom_file: Path) -> List[str]:
    """Lê <modules><module>... relativos ao pom_file e retorna lista de caminhos relativos a ESTE POM."""
    root, txt, q = _read_xml_ns_aware(pom_file)
    mods: List[str] = []
    if root is None:
        for m in re.findall(r"<modules[^>]*>(.*?)</modules>", txt, flags=re.S|re.I):
            mods += [x.strip() for x in re.findall(r"<module>([^<]+)</module>", m, flags=re.I)]
    else:
        m_nodes = root.findall(".//{*}modules") or ([root.find(q("modules"))] if root.find(q("modules")) is not None else [])
        for mn in m_nodes:
            for item in (mn.findall(".//{*}module") or mn.findall("module")):
                val = _text_of(item)
                if val:
                    mods.append(val.strip())
    # normaliza (ordem preservada, sem duplicatas)
    seen, out = set(), []
    for m in mods:
        if m and m not in seen:
            out.append(m); seen.add(m)
    return out

def _list_subpom_paths(repo_root: Path) -> List[Path]:
    """Lista todos os pom.xml abaixo da raiz (exceto a raiz)."""
    poms = []
    for cur, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in IGNORES]
        curp = Path(cur)
        if curp == repo_root:
            continue
        if "pom.xml" in files:
            poms.append(curp / "pom.xml")
    return poms

def _child_has_parent(child_pom: Path, parent_gav: Tuple[Optional[str], Optional[str], Optional[str]]) -> Tuple[bool, str]:
    """Verifica se o child possui <parent> com gid/aid do pai; se version presente no child, compara também."""
    pgid, paid, pver = parent_gav
    root, txt, q = _read_xml_ns_aware(child_pom)
    if root is None:
        mg = re.search(r"<parent>.*?<groupId>([^<]+)</groupId>.*?</parent>", txt, re.S|re.I)
        ma = re.search(r"<parent>.*?<artifactId>([^<]+)</artifactId>.*?</parent>", txt, re.S|re.I)
        mv = re.search(r"<parent>.*?<version>([^<]+)</version>.*?</parent>", txt, re.S|re.I)
        cg, ca, cv = (mg.group(1).strip() if mg else None,
                      ma.group(1).strip() if ma else None,
                      mv.group(1).strip() if mv else None)
    else:
        par = root.find(q("parent"))
        if par is None:
            return False, "no-parent"
        cg = _text_of(par.find(q("groupId")))
        ca = _text_of(par.find(q("artifactId")))
        cv = _text_of(par.find(q("version")))
    if not (cg and ca):
        return False, "parent-incomplete"
    if (pgid and paid) and ((cg != pgid) or (ca != paid)):
        return False, f"parent-mismatch(child={cg}:{ca} vs expected={pgid}:{paid})"
    if cv and pver and (cv != pver):
        return False, f"parent-version-diff(child={cv}, expected={pver})"
    return True, "ok"

def _nearest_declared_ancestor_exclusive(rel_dir: str, declared_set: set) -> Optional[str]:
    """
    Retorna o módulo declarado mais próximo (ancestral) de rel_dir, EXCLUINDO ele próprio.
    Ex.: rel_dir='examples/foo/bar' e declared_set contém 'examples' e 'examples/foo'
         -> retorna 'examples/foo'
    """
    parts = Path(rel_dir).parts
    for i in range(len(parts)-1, 0, -1):  # começa um nível acima
        cand = str(Path(*parts[:i]))
        if cand in declared_set:
            return cand
    return None

def _collect_declared_modules_recursive(repo_root: Path, root_pom: Path) -> List[str]:
    """
    Coleta módulos declarados de forma recursiva.
    Para cada POM declarado, os módulos filhos são concatenados ao caminho do pai
    (respeitando paths relativos entre POMs).
    """
    queue = _list_declared_modules(root_pom)
    seen, out = set(), []
    while queue:
        rel = queue.pop(0)
        norm_rel = str(Path(rel))  # normaliza separadores
        if norm_rel in seen:
            continue
        seen.add(norm_rel)
        out.append(norm_rel)

        pom = (repo_root / norm_rel / "pom.xml")
        if pom.is_file():
            child_mods = _list_declared_modules(pom)
            for cm in child_mods:
                # cm é relativo ao pom atual -> concatenar
                combined = str(Path(norm_rel) / cm)
                if combined not in seen:
                    queue.append(combined)
    return out

def _extract_gav_map(repo_root: Path, declared: List[str]) -> Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]]:
    """Mapa módulo->GAV para todos os módulos declarados; inclui a chave '' para o root."""
    gav_by_module: Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]] = {}
    root_pom = repo_root / "pom.xml"
    gav_by_module[""] = _extract_gav(root_pom)
    for rel in declared:
        pom = repo_root / rel / "pom.xml"
        if pom.is_file():
            gav_by_module[rel] = _extract_gav(pom)
    return gav_by_module

def _expected_parent_gav_for(rel_dir: str, declared_set: set, gav_map: Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]]):
    """
    Para um diretório (rel_dir), retorna (gav_esperado, ancestral_usado):
    - ancestral é o módulo declarado mais próximo (excluindo o próprio), se houver;
    - caso não exista, espera o GAV do root (chave "").
    """
    anc = _nearest_declared_ancestor_exclusive(rel_dir, declared_set)
    gav = gav_map.get(anc or "", (None, None, None))
    return gav, (anc or "")

# ---------------------------------------------------------------------------
# Auditoria de um repositório
# ---------------------------------------------------------------------------

def audit_repo(repo_root: Path) -> Dict[str, object]:
    repo_root = repo_root.resolve()
    root_pom = repo_root / "pom.xml"
    res = {
        "repo_path": str(repo_root),
        "has_root_pom": root_pom.is_file(),
        "declared_modules_count": 0,
        "declared_missing_dir": 0,
        "declared_missing_pom": 0,
        "child_without_parent": 0,
        "undeclared_poms": 0,
        "notes": "",
        "module_rows": []  # cada item: {repo_path, module, status, detail, rel_path, abs_path, depth, nearest_declared_ancestor}
    }
    if not root_pom.is_file():
        res["notes"] = "no-root-pom"
        return res

    # 1) módulos declarados (RECUSIVO)
    declared = _collect_declared_modules_recursive(repo_root, root_pom)
    declared_set = set(declared)
    res["declared_modules_count"] = len(declared)

    # mapa GAV dos declarados + root
    gav_map = _extract_gav_map(repo_root, declared)

    # 1.a) validar cada módulo declarado
    for m in declared:
        mdir = repo_root / m
        if not mdir.exists():
            res["declared_missing_dir"] += 1
            res["module_rows"].append({
                "repo_path": str(repo_root),
                "module": m,
                "status": "missing-dir",
                "detail": "Diretório não existe",
                "rel_path": "",
                "abs_path": "",
                "depth": m.count(os.sep),
                "nearest_declared_ancestor": _nearest_declared_ancestor_exclusive(m, declared_set) or ""
            })
            continue

        mpom = mdir / "pom.xml"
        if not mpom.is_file():
            res["declared_missing_pom"] += 1
            res["module_rows"].append({
                "repo_path": str(repo_root),
                "module": m,
                "status": "missing-pom",
                "detail": "pom.xml não encontrado",
                "rel_path": "",
                "abs_path": "",
                "depth": m.count(os.sep),
                "nearest_declared_ancestor": _nearest_declared_ancestor_exclusive(m, declared_set) or ""
            })
            continue

        # parent esperado = ancestral declarado mais próximo (ou root)
        exp_gav, anc = _expected_parent_gav_for(m, declared_set, gav_map)
        ok, why = _child_has_parent(mpom, exp_gav)
        status = "ok" if ok else "parent-problem"
        detail = "ok" if ok else why
        res["child_without_parent"] += (0 if ok else 1)

        res["module_rows"].append({
            "repo_path": str(repo_root),
            "module": m,
            "status": status,
            "detail": detail,
            "rel_path": f"{m}/pom.xml",
            "abs_path": str(mpom.resolve()),
            "depth": m.count(os.sep),
            "nearest_declared_ancestor": anc
        })

    # 2) POMs que NÃO estão em <modules> (após recursão)
    subs = _list_subpom_paths(repo_root)
    seen_undeclared = set()
    for sp in subs:
        rel_dir = str(sp.parent.relative_to(repo_root))  # diretório do pom
        if rel_dir in declared_set:
            continue
        if rel_dir in seen_undeclared:
            continue
        seen_undeclared.add(rel_dir)

        exp_gav, anc = _expected_parent_gav_for(rel_dir, declared_set, gav_map)
        ok, why = _child_has_parent(sp, exp_gav)
        st = "undeclared-with-parent" if ok else f"undeclared-{why}"

        res["module_rows"].append({
            "repo_path": str(repo_root),
            "module": rel_dir,            # pasta do POM
            "status": st,
            "detail": "POM não listado em <modules> (após expansão recursiva)",
            "rel_path": f"{rel_dir}/pom.xml",
            "abs_path": str(sp.resolve()),
            "depth": rel_dir.count(os.sep),
            "nearest_declared_ancestor": anc
        })
    res["undeclared_poms"] = len(seen_undeclared)
    return res

# ---------------------------------------------------------------------------
# CLI (DB-mining style) e execução
# ---------------------------------------------------------------------------

def parse_extra_cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--out-projects", default="projetos.csv")
    p.add_argument("--out-modules", default="modulos.csv")
    p.add_argument("--out-xlsx", default="auditoria_modulos.xlsx")
    return p.parse_known_args()[0]

def build_repo_path(owner: str, name: str) -> Path:
    return Path(REPOS_DIR) / owner / name

def main():
    # usa o mesmo read_args do seu projeto para carregar a lista de repositórios
    args = read_args(
        'audit_maven_modules_v2',
        'Audita módulos Maven de forma recursiva e valida <parent> contra o ancestral declarado mais próximo.',
        default_label_type="vulnerabilities",
        default_skip_remove=True
    )
    extra = parse_extra_cli()

    db.connect()
    projects = get_or_create_projects(
        create_version=False,
        filename=args.input,
        filters=args.filter,
        min_project=args.min_project,
        max_project=args.max_project,
        skip_remove=args.skip_remove
    )

    print(f"\nFound {len(projects)} projects. Auditing...\n")

    proj_rows, mod_rows = [], []
    for project in projects:
        repo_path = build_repo_path(project.owner, project.name)
        res = audit_repo(repo_path)

        print(f"{project.owner}/{project.name}: "
              f"root_pom={res['has_root_pom']}, decl={res['declared_modules_count']}, "
              f"missing_dir={res['declared_missing_dir']}, missing_pom={res['declared_missing_pom']}, "
              f"decl_parent_issues={res['child_without_parent']}, undeclared={res['undeclared_poms']}")

        proj_rows.append({
            "owner": project.owner,
            "name": project.name,
            "repo_path": str(repo_path),
            "has_root_pom": res["has_root_pom"],
            "declared_modules_count": res["declared_modules_count"],
            "declared_missing_dir": res["declared_missing_dir"],
            "declared_missing_pom": res["declared_missing_pom"],
            "child_without_parent": res["child_without_parent"],
            "undeclared_poms": res["undeclared_poms"],
            "notes": res["notes"],
        })
        for r in res["module_rows"]:
            mod_rows.append({
                "owner": project.owner,
                "name": project.name,
                "repo_path": r["repo_path"],
                "module": r["module"],
                "status": r["status"],
                "detail": r["detail"],
                "rel_path": r.get("rel_path",""),
                "abs_path": r.get("abs_path",""),
                "depth": r.get("depth",""),
                "nearest_declared_ancestor": r.get("nearest_declared_ancestor","")
            })

    # CSVs
    try:
        with open(extra.out_projects, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "owner","name","repo_path","has_root_pom","declared_modules_count",
                "declared_missing_dir","declared_missing_pom","child_without_parent",
                "undeclared_poms","notes"
            ])
            w.writeheader(); w.writerows(proj_rows)
        print(f"[OK] CSV (projetos): {extra.out_projects}")

        with open(extra.out_modules, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "owner","name","repo_path","module","status","detail",
                "rel_path","abs_path","depth","nearest_declared_ancestor"
            ])
            w.writeheader(); w.writerows(mod_rows)
        print(f"[OK] CSV (módulos): {extra.out_modules}")
    except Exception as e:
        print(yellow(f"[WARN] Falha ao salvar CSVs: {e}"))

    # XLSX opcional
    if HAS_PANDAS:
        try:
            df_proj = pd.DataFrame(proj_rows)
            df_mods = pd.DataFrame(mod_rows)
            with pd.ExcelWriter(extra.out_xlsx, engine="openpyxl") as writer:
                df_proj.to_excel(writer, index=False, sheet_name="projetos")
                df_mods.to_excel(writer, index=False, sheet_name="modulos")
            print(f"[OK] XLSX salvo em: {extra.out_xlsx}")
        except Exception as e:
            print(yellow(f"[WARN] Falha ao salvar XLSX: {e}"))

    db.close()

if __name__ == "__main__":
    main()
