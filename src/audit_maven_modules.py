#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Auditoria Maven (DB-mining) — 1º nível (módulos do <modules> da raiz)

Objetivo:
- Verificar, por repositório, se os módulos listados em <modules> do pom.xml da raiz
  declaram o POM raiz como <parent> (comparando groupId/artifactId sempre, e version se
  presente em ambos).
- Encontrar POMs de 1º nível (diretórios imediatamente sob a raiz) que apontam o raiz
  como <parent>, mas não estão listados em <modules> (descompasso).

Entradas:
- Lista de projetos via DB-mining: `read_args(...)` + `get_or_create_projects(...)`
  (usa `args.input`, `args.filter`, etc. conforme seu padrão).

Saídas:
- CSV `--out-projects` (default: projetos_rootlevel.csv): resumo por repositório
- CSV `--out-modules`  (default: modulos_rootlevel.csv): detalhe por módulo/filho
- XLSX opcional `--out-xlsx` (default: auditoria_rootlevel.xlsx) se pandas disponível

Uso (exemplos):
  python audit_maven_modules_rootlevel_dbmining.py --input /caminho/projetos.csv
  python audit_maven_modules_rootlevel_dbmining.py --filter owner=apache --out-xlsx auditoria.xlsx
"""

import csv
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Set
import xml.etree.ElementTree as ET
import argparse

# ==== dependências do seu projeto (DB-mining) ====
import database as db
from extract import get_or_create_projects, read_args
from util import REPOS_DIR, yellow

# XLSX opcional
try:
    import pandas as pd
    HAS_PANDAS = True
except Exception:
    HAS_PANDAS = False

# ----------------- helpers XML ----------------- #

def _strip_ns(tag: str) -> str:
    return tag.split('}', 1)[1] if '}' in tag else tag

def _find_text(el: Optional[ET.Element], name: str) -> Optional[str]:
    if el is None:
        return None
    for child in el:
        if _strip_ns(child.tag) == name:
            val = (child.text or '').strip()
            return val or None
    return None

def parse_pom_gav(pom_path: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """(groupId, artifactId, version) do POM (herda gid/version do <parent> se ausentes)."""
    try:
        root = ET.parse(pom_path).getroot()
    except ET.ParseError as e:
        print(f"[WARN] XML inválido: {pom_path} ({e})", file=sys.stderr)
        return None, None, None

    gid = _find_text(root, "groupId")
    aid = _find_text(root, "artifactId")
    ver = _find_text(root, "version")

    parent = None
    for child in root:
        if _strip_ns(child.tag) == "parent":
            parent = child
            break

    if parent is not None:
        pg = _find_text(parent, "groupId")
        pv = _find_text(parent, "version")
        gid = gid or pg
        ver = ver or pv

    return gid, aid, ver

def parse_modules_from_root_pom(pom_path: Path) -> List[str]:
    """Extrai <modules>/<module> do POM raiz (valores exatamente como declarados)."""
    try:
        root = ET.parse(pom_path).getroot()
    except ET.ParseError:
        return []
    modules: List[str] = []
    for child in root:
        if _strip_ns(child.tag) == "modules":
            for m in child:
                if _strip_ns(m.tag) == "module":
                    name = (m.text or '').strip()
                    if name:
                        modules.append(name)
    # de-duplicado preservando ordem
    seen, out = set(), []
    for m in modules:
        if m not in seen:
            out.append(m); seen.add(m)
    return out

def parse_parent_gav(pom_path: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """(parent.groupId, parent.artifactId, parent.version) de um POM filho; None se sem <parent>."""
    try:
        root = ET.parse(pom_path).getroot()
    except ET.ParseError:
        return None, None, None
    parent = None
    for child in root:
        if _strip_ns(child.tag) == "parent":
            parent = child
            break
    if parent is None:
        return None, None, None
    return (
        _find_text(parent, "groupId"),
        _find_text(parent, "artifactId"),
        _find_text(parent, "version"),
    )

def gav_str(g: Optional[str], a: Optional[str], v: Optional[str]) -> str:
    return f"{g or '?'}:{a or '?'}:{v or '?'}"

def parent_matches_root(
    child_parent: Tuple[Optional[str], Optional[str], Optional[str]],
    root_gav: Tuple[Optional[str], Optional[str], Optional[str]],
) -> Tuple[bool, str]:
    """Compara parent(child) com GAV do raiz: GA devem bater; versão só se presente em ambos."""
    c_g, c_a, c_v = child_parent
    r_g, r_a, r_v = root_gav

    if not c_g or not c_a:
        return False, "child-without-parent-or-missing-ga"
    if not r_g or not r_a:
        return False, "root-missing-ga"
    if c_g != r_g or c_a != r_a:
        return False, "parent-ga-mismatch"
    if c_v and r_v and c_v != r_v:
        return False, "parent-version-mismatch"
    return True, ""

# ----------------- varredura (1º nível) ----------------- #

def scan_project_rootlevel(project_path: Path) -> Dict:
    """
    Lê pom.xml da raiz, avalia módulos listados (1º nível) e encontra filhos de 1º nível
    não listados que referenciam o raiz como <parent>.
    """
    project_path = project_path.resolve()
    root_pom = project_path / "pom.xml"
    if not root_pom.exists():
        return {
            "project": str(project_path),
            "error": "missing-root-pom",
            "root_gav": None,
            "module_rows": [],
            "summary": {
                "has_root_pom": False,
                "listed_modules": 0,
                "listed_modules_parent_ok": 0,
                "listed_modules_parent_bad": 0,
                "unlisted_children_parent_ok": 0,
                "coverage_listed_ok_over_listed": "0.000",
            },
        }

    root_gav = parse_pom_gav(root_pom)
    root_modules = parse_modules_from_root_pom(root_pom)

    module_rows: List[Dict] = []
    ok_count = 0

    # normaliza entradas do <modules>
    normalized: List[Tuple[str, Path, bool]] = []
    for m in root_modules:
        is_nested = ("/" in m) or ("\\" in m)  # só 1º nível interessa
        mod_dir = (project_path / m).resolve()
        normalized.append((m, mod_dir, is_nested))

    # Avalia listados
    for m_name, m_dir, is_nested in normalized:
        pom = m_dir / "pom.xml"
        if is_nested:
            status = "listed-nested-path"
            reason = "nested-module-path"
            match_parent = False
            child_parent_gav = (None, None, None)
            exists = False
        elif not pom.exists():
            status = "listed-missing-pom"
            reason = "missing-module-pom"
            match_parent = False
            child_parent_gav = (None, None, None)
            exists = False
        else:
            child_parent_gav = parse_parent_gav(pom)
            match_parent, reason = parent_matches_root(child_parent_gav, root_gav)
            status = "listed-ok" if match_parent else "listed-parent-mismatch"
            exists = True
            if match_parent:
                ok_count += 1

        module_rows.append({
            "project_path": str(project_path),
            "root_gav": gav_str(*root_gav),
            "module_listed": True,
            "module_name": m_name,
            "module_path": str(m_dir.relative_to(project_path) if m_dir.exists() else m_name),
            "module_pom_exists": exists,
            "child_parent_gav": gav_str(*child_parent_gav),
            "parent_matches_root": match_parent,
            "status": status,
            "reason": reason,
        })

    # Filhos de 1º nível não listados, mas com parent=root
    listed_set: Set[str] = {n for (n, _, _) in normalized}
    extra_children = 0
    for entry in project_path.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith(".") or entry.name in (".git", "target", "build", "dist", "out", "node_modules"):
            continue
        if entry.name in listed_set:
            continue
        pom = entry / "pom.xml"
        if not pom.exists():
            continue
        child_parent_gav = parse_parent_gav(pom)
        match_parent, _ = parent_matches_root(child_parent_gav, root_gav)
        if match_parent:
            extra_children += 1
            module_rows.append({
                "project_path": str(project_path),
                "root_gav": gav_str(*root_gav),
                "module_listed": False,
                "module_name": entry.name,
                "module_path": entry.name,
                "module_pom_exists": True,
                "child_parent_gav": gav_str(*child_parent_gav),
                "parent_matches_root": True,
                "status": "unlisted-child-with-root-parent",
                "reason": "unlisted-but-parent-matches-root",
            })

    total_listed = len(root_modules)
    coverage = (ok_count / total_listed) if total_listed else 0.0

    summary = {
        "has_root_pom": True,
        "listed_modules": total_listed,
        "listed_modules_parent_ok": ok_count,
        "listed_modules_parent_bad": total_listed - ok_count,
        "unlisted_children_parent_ok": extra_children,
        "coverage_listed_ok_over_listed": f"{coverage:.3f}",
    }

    return {
        "project": str(project_path),
        "error": None,
        "root_gav": root_gav,
        "module_rows": module_rows,
        "summary": summary,
    }

# ----------------- CLI (DB-mining style) ----------------- #

def parse_extra_cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--out-projects", default="projetos_rootlevel.csv")
    p.add_argument("--out-modules",  default="modulos_rootlevel.csv")
    p.add_argument("--out-xlsx",     default="auditoria_rootlevel.xlsx")
    return p.parse_known_args()[0]

def build_repo_path(owner: str, name: str) -> Path:
    return Path(REPOS_DIR) / owner / name

def main():
    # carrega lista de projetos com os mesmos parâmetros do seu pipeline
    args = read_args(
        'audit_maven_modules_rootlevel',
        'Audita módulos Maven (1º nível) e confere <parent> com o POM raiz.',
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

    print(f"\n[INFO] Projetos carregados: {len(projects)}\n")

    proj_rows, mod_rows = [], []

    for project in projects:
        repo_path = build_repo_path(project.owner, project.name)
        res = scan_project_rootlevel(repo_path)

        s = res["summary"]
        print(f"{project.owner}/{project.name} -> root_pom={s['has_root_pom']}, "
              f"listed={s['listed_modules']}, ok={s['listed_modules_parent_ok']}, "
              f"bad={s['listed_modules']-s['listed_modules_parent_ok']}, "
              f"unlisted_children={s['unlisted_children_parent_ok']}, "
              f"coverage={s['coverage_listed_ok_over_listed']}")

        proj_rows.append({
            "owner": project.owner,
            "name": project.name,
            "repo_path": str(repo_path),
            "has_root_pom": s["has_root_pom"],
            "listed_modules": s["listed_modules"],
            "listed_modules_parent_ok": s["listed_modules_parent_ok"],
            "listed_modules_parent_bad": s["listed_modules_parent_bad"],
            "unlisted_children_parent_ok": s["unlisted_children_parent_ok"],
            "coverage_listed_ok_over_listed": s["coverage_listed_ok_over_listed"],
        })

        for r in res["module_rows"]:
            mod_rows.append({
                "owner": project.owner,
                "name": project.name,
                "repo_path": r["project_path"],
                "root_gav": r["root_gav"],
                "module_listed": r["module_listed"],
                "module_name": r["module_name"],
                "module_path": r["module_path"],
                "module_pom_exists": r["module_pom_exists"],
                "child_parent_gav": r["child_parent_gav"],
                "parent_matches_root": r["parent_matches_root"],
                "status": r["status"],
                "reason": r["reason"],
            })

    # CSVs
    try:
        with open(extra.out_projects, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "owner","name","repo_path","has_root_pom","listed_modules",
                "listed_modules_parent_ok","listed_modules_parent_bad",
                "unlisted_children_parent_ok","coverage_listed_ok_over_listed"
            ])
            w.writeheader(); w.writerows(proj_rows)
        print(f"[OK] CSV (projetos): {extra.out_projects}")

        with open(extra.out_modules, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "owner","name","repo_path","root_gav","module_listed","module_name",
                "module_path","module_pom_exists","child_parent_gav",
                "parent_matches_root","status","reason"
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
