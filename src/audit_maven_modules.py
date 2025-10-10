#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auditoria Maven — Primeiro Nível (root only)

Objetivo:
- Contar e validar SOMENTE os módulos listados no <modules> do POM da raiz:
  * diretório existe?
  * existe pom.xml?
  * <parent> (groupId/artifactId e, se presente, version) aponta para o POM raiz?

Saídas:
- root_projetos.csv  : resumo por repositório (apenas 1º nível)
- root_modulos.csv   : linhas detalhadas por módulo de 1º nível
- (opcional) root_auditoria.xlsx com as duas abas acima

Dependências internas (do seu projeto DB-mining):
- database as db
- extract.get_or_create_projects, extract.read_args
- util.REPOS_DIR, util.yellow
"""

import os, re, csv, argparse
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import List, Tuple, Optional, Dict

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
        # fallback simples via regex
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

def _list_declared_modules_root_only(root_pom: Path) -> List[str]:
    """Lê SOMENTE os módulos do POM raiz (não recursivo)."""
    root, txt, q = _read_xml_ns_aware(root_pom)
    mods: List[str] = []
    if root is None:
        for m in re.findall(r"<modules[^>]*>(.*?)</modules>", txt, flags=re.S|re.I):
            mods += [x.strip() for x in re.findall(r"<module>([^<]+)</module>", m, flags=re.I)]
    else:
        mn = root.find(q("modules"))
        if mn is not None:
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
        return False, f"parent-mismatch(child={cg}:{ca} vs root={pgid}:{paid})"
    if cv and pver and (cv != pver):
        return False, f"parent-version-diff(child={cv}, root={pver})"
    return True, "ok"

# ---------------------------------------------------------------------------
# Auditoria (apenas 1º nível)
# ---------------------------------------------------------------------------

def audit_repo_root_level(repo_root: Path) -> Dict[str, object]:
    """
    Audita somente os módulos listados no <modules> do POM raiz.
    Retorna resumo + linhas por módulo (1º nível).
    """
    repo_root = repo_root.resolve()
    root_pom = repo_root / "pom.xml"

    res = {
        "repo_path": str(repo_root),
        "has_root_pom": root_pom.is_file(),
        "first_level_declared": 0,
        "ok": 0,
        "parent_problem": 0,
        "missing_dir": 0,
        "missing_pom": 0,
        "rows": [],  # cada item: dict com info do módulo de 1º nível
        "notes": ""
    }

    if not root_pom.is_file():
        res["notes"] = "no-root-pom"
        return res

    # GAV do pai esperado (root)
    root_gav = _extract_gav(root_pom)  # (groupId, artifactId, version)

    # SOMENTE 1º nível (não recursivo)
    first_level = _list_declared_modules_root_only(root_pom)
    res["first_level_declared"] = len(first_level)

    for m in first_level:
        mdir = repo_root / m
        depth = m.count(os.sep)

        if not mdir.exists():
            res["missing_dir"] += 1
            res["rows"].append({
                "module": m, "level": 1, "status": "missing-dir",
                "detail": "Diretório não existe",
                "rel_path": "", "abs_path": "", "depth": depth
            })
            continue

        mpom = mdir / "pom.xml"
        if not mpom.is_file():
            res["missing_pom"] += 1
            res["rows"].append({
                "module": m, "level": 1, "status": "missing-pom",
                "detail": "pom.xml não encontrado",
                "rel_path": "", "abs_path": "", "depth": depth
            })
            continue

        ok, why = _child_has_parent(mpom, root_gav)
        if ok:
            res["ok"] += 1
            status, detail = "ok", "parent=root"
        else:
            res["parent_problem"] += 1
            status, detail = "parent-problem", why

        res["rows"].append({
            "module": m, "level": 1, "status": status, "detail": detail,
            "rel_path": f"{m}/pom.xml",
            "abs_path": str(mpom.resolve()),
            "depth": depth
        })

    return res

# ---------------------------------------------------------------------------
# CLI e execução
# ---------------------------------------------------------------------------

def parse_extra_cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--out-projects", default="root_projetos.csv",
                   help="CSV de resumo por repositório (1º nível)")
    p.add_argument("--out-modules", default="root_modulos.csv",
                   help="CSV de módulos do 1º nível")
    p.add_argument("--out-xlsx", default="root_auditoria.xlsx",
                   help="Arquivo XLSX consolidado (opcional, se pandas disponível)")
    return p.parse_known_args()[0]

def build_repo_path(owner: str, name: str) -> Path:
    return Path(REPOS_DIR) / owner / name

def main():
    # usa seu read_args padrão para carregar a lista de repositórios
    args = read_args(
        'audit_maven_root_modules',
        'Valida APENAS o primeiro nível: módulos listados no <modules> do POM raiz e seu <parent> apontando para o root.',
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

    print(f"\nFound {len(projects)} projects. Auditing ROOT level...\n")

    proj_rows, mod_rows = [], []

    for project in projects:
        repo_path = build_repo_path(project.owner, project.name)
        res = audit_repo_root_level(repo_path)

        print(f"{project.owner}/{project.name}: "
              f"root_pom={res['has_root_pom']}, "
              f"declared(1st)={res['first_level_declared']}, "
              f"ok={res['ok']}, "
              f"parent_problem={res['parent_problem']}, "
              f"missing_dir={res['missing_dir']}, "
              f"missing_pom={res['missing_pom']}")

        proj_rows.append({
            "owner": project.owner,
            "name": project.name,
            "repo_path": res["repo_path"],
            "has_root_pom": res["has_root_pom"],
            "first_level_declared": res["first_level_declared"],
            "ok": res["ok"],
            "parent_problem": res["parent_problem"],
            "missing_dir": res["missing_dir"],
            "missing_pom": res["missing_pom"],
            "notes": res["notes"]
        })

        for r in res["rows"]:
            mod_rows.append({
                "owner": project.owner,
                "name": project.name,
                **r
            })

    # CSVs
    try:
        with open(extra.out_projects, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "owner","name","repo_path","has_root_pom",
                "first_level_declared","ok","parent_problem",
                "missing_dir","missing_pom","notes"
            ])
            w.writeheader(); w.writerows(proj_rows)
        print(f"[OK] CSV (projetos 1º nível): {extra.out_projects}")

        with open(extra.out_modules, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "owner","name","module","level","status","detail",
                "rel_path","abs_path","depth"
            ])
            w.writeheader(); w.writerows(mod_rows)
        print(f"[OK] CSV (módulos 1º nível): {extra.out_modules}")
    except Exception as e:
        print(yellow(f"[WARN] Falha ao salvar CSVs: {e}"))

    # XLSX opcional
    if HAS_PANDAS:
        try:
            df_proj = pd.DataFrame(proj_rows)
            df_mods = pd.DataFrame(mod_rows)
            with pd.ExcelWriter(extra.out_xlsx, engine="openpyxl") as writer:
                df_proj.to_excel(writer, index=False, sheet_name="projetos_root")
                df_mods.to_excel(writer, index=False, sheet_name="modulos_root")
            print(f"[OK] XLSX salvo em: {extra.out_xlsx}")
        except Exception as e:
            print(yellow(f"[WARN] Falha ao salvar XLSX: {e}"))

    db.close()

if __name__ == "__main__":
    main()
