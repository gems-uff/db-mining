#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DB-mining — Projeto x Deployáveis x Multi-Módulo (mesclado)

O que faz, por projeto:
1) Lê o POM raiz (se existir), extrai <packaging> e conta <modules>/<module> (1º nível).
   - Classifica: MULTI_MODULE | AGGREGATOR_EMPTY | SINGLE_MODULE | NO_ROOT_POM
2) Varre TODOS os pom.xml do repo e calcula:
   - Módulos deployáveis (packaging in {jar,war,ear,rar,ejb,bundle} ou com spring-boot plugin)
   - Marca caminhos "exemplo/docs/tools..." como excluídos (tag ou drop)
3) Exporta:
   - projects_summary.csv (por projeto)
   - deployables.csv (por POM)
   - auditoria.xlsx (opcional)

Uso típico:
  python merge_packaging_and_deployables.py --input /caminho/lista.csv \
      --out-projects projects_summary.csv \
      --out-deployables deployables.csv \
      --out-xlsx auditoria.xlsx
"""

import os
import re
import csv
import argparse
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Tuple

# === dependências do seu projeto ===
import database as db
from extract import get_or_create_projects, read_args
from util import REPOS_DIR, yellow

# XLSX opcional
try:
    import pandas as pd
    HAS_PANDAS = True
except Exception:
    HAS_PANDAS = False

# ----------------- configurações ----------------- #

IGNORES = {
    ".git", "target", "build", "dist", "out", "node_modules", "venv",
    ".venv", "__pycache__", ".idea", ".vscode", ".mvn", ".gradle"
}

DEFAULT_DEPLOYABLE_PACKAGINGS = {"jar", "war", "ear", "rar", "ejb", "bundle"}
DEFAULT_EXCLUDE_DIR_HINTS = {
    "examples","example","quickstart","quick-start","samples","sample",
    "docs","documentation","site","tools","tooling","demo","demos","playground","kitchen-sink"
}
SPRING_BOOT_PLUGIN_ARTIFACT = "spring-boot-maven-plugin"

# ----------------- helpers XML ----------------- #

def _read_xml_ns_aware(p: Path):
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None, "", (lambda t: t)
    try:
        root = ET.fromstring(txt)
        ns = root.tag.split('}')[0].strip('{') if root.tag.startswith('{') else None
        def q(tag: str):
            return f"{{{ns}}}{tag}" if ns else tag
        return root, txt, q
    except ET.ParseError:
        return None, txt, (lambda t: t)

def _text(node: Optional[ET.Element]) -> Optional[str]:
    return (node.text or "").strip() if node is not None and node.text else None

# ----------------- raiz: packaging + modules ----------------- #

def parse_packaging_from_root_pom(pom_path: Path) -> Optional[str]:
    root, txt, q = _read_xml_ns_aware(pom_path)
    if root is not None:
        v = _text(root.find(q("packaging")))
        if v: return v
    m = re.search(r"<packaging>([^<]+)</packaging>", txt, re.I)
    return m.group(1).strip() if m else None

def parse_modules_from_root_pom(pom_path: Path) -> List[str]:
    root, txt, q = _read_xml_ns_aware(pom_path)
    mods: List[str] = []
    if root is not None:
        mn = root.find(q("modules"))
        if mn is not None:
            for m in mn.findall(q("module")):
                v = _text(m)
                if v: mods.append(v)
    else:
        for block in re.findall(r"<modules[^>]*>(.*?)</modules>", txt, flags=re.S|re.I):
            for m in re.findall(r"<module>([^<]+)</module>", block, flags=re.I):
                v = m.strip()
                if v: mods.append(v)
    # de-dup preservando ordem
    seen, out = set(), []
    for m in mods:
        if m not in seen:
            seen.add(m); out.append(m)
    return out

def classify_by_root(repo_root: Path) -> Dict[str, object]:
    """
    Classifica projeto pela definição clássica:
      MULTI_MODULE      => root.packaging == "pom" and len(root.modules) > 0
      AGGREGATOR_EMPTY  => root.packaging == "pom" and len(root.modules) == 0
      SINGLE_MODULE     => root.packaging != "pom"
      NO_ROOT_POM       => sem pom.xml na raiz
    """
    root_pom = repo_root / "pom.xml"
    if not root_pom.is_file():
        return {
            "has_root_pom": False,
            "root_packaging": None,
            "root_modules_declared_count": 0,
            "classification": "NO_ROOT_POM"
        }
    packaging = (parse_packaging_from_root_pom(root_pom) or "jar").strip()
    modules = parse_modules_from_root_pom(root_pom)
    mcount = len(modules)
    if packaging == "pom":
        if mcount > 0:
            cls = "MULTI_MODULE"
        else:
            cls = "AGGREGATOR_EMPTY"
    else:
        cls = "SINGLE_MODULE"
    return {
        "has_root_pom": True,
        "root_packaging": packaging,
        "root_modules_declared_count": mcount,
        "classification": cls
    }

# ----------------- deployáveis (por POM) ----------------- #

def list_all_poms(repo_root: Path) -> List[Path]:
    poms = []
    for cur, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in IGNORES]
        if "pom.xml" in files:
            poms.append(Path(cur) / "pom.xml")
    return poms

def parse_pom_metadata(pom_path: Path) -> Dict[str, Optional[str]]:
    meta = {
        "groupId": None, "artifactId": None, "version": None,
        "packaging": None, "boot_repackage": False,
    }
    root, txt, q = _read_xml_ns_aware(pom_path)
    if root is None:
        m = re.search(r"<packaging>([^<]+)</packaging>", txt, re.I)
        meta["packaging"] = (m.group(1).strip() if m else None) or "jar"
        if re.search(r"<artifactId>\s*spring-boot-maven-plugin\s*</artifactId>", txt, re.I):
            meta["boot_repackage"] = True
        g = re.search(r"<groupId>([^<]+)</groupId>", txt)
        a = re.search(r"<artifactId>([^<]+)</artifactId>", txt)
        v = re.search(r"<version>([^<]+)</version>", txt)
        meta["groupId"] = g.group(1).strip() if g else None
        meta["artifactId"] = a.group(1).strip() if a else None
        meta["version"] = v.group(1).strip() if v else None
        return meta

    meta["groupId"] = _text(root.find(q("groupId")))
    meta["artifactId"] = _text(root.find(q("artifactId")))
    meta["version"] = _text(root.find(q("version")))
    # herança mínima
    if (not meta["groupId"]) or (not meta["version"]):
        par = root.find(q("parent"))
        if par is not None:
            pg = _text(par.find(q("groupId")))
            pv = _text(par.find(q("version")))
            meta["groupId"] = meta["groupId"] or pg
            meta["version"] = meta["version"] or pv

    pkg = _text(root.find(q("packaging")))
    meta["packaging"] = pkg or "jar"

    for p in root.findall(".//{*}plugin"):
        aid = _text(p.find(".//{*}artifactId"))
        if (aid or "").strip() == SPRING_BOOT_PLUGIN_ARTIFACT:
            # considerar como indicativo (mesmo sem checar goal)
            meta["boot_repackage"] = True
            break

    return meta

def is_excluded_path(rel_dir: str, exclude_hints: List[str]) -> bool:
    parts = set(Path(rel_dir).parts)
    hints = set(h.strip().lower() for h in exclude_hints if h.strip())
    return any(h in (p.lower() for p in parts) for h in hints)

def decide_deployable(meta: Dict[str, Optional[str]], deployable_packagings: set) -> Tuple[bool, str]:
    pkg = (meta.get("packaging") or "jar").lower()
    if pkg == "pom":
        return False, "packaging=pom"
    if pkg in deployable_packagings:
        if meta.get("boot_repackage", False):
            return True, f"packaging={pkg}+spring-boot"
        return True, f"packaging={pkg}"
    if meta.get("boot_repackage", False):
        return True, f"spring-boot (packaging={pkg})"
    return False, f"packaging={pkg}"

# ----------------- CLI / Execução ----------------- #

def parse_cli():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--out-projects", default="projects_summary.csv")
    p.add_argument("--out-deployables", default="deployables.csv")
    p.add_argument("--out-xlsx", default="auditoria.xlsx")
    p.add_argument("--exclude", nargs="*", default=sorted(DEFAULT_EXCLUDE_DIR_HINTS),
                   help="Pistas de diretórios a excluir/taggar (ex.: examples docs tools)")
    p.add_argument("--exclude-mode", choices=["drop", "tag"], default="tag",
                   help="drop=excluir do CSV de deployáveis; tag=manter com is_excluded=True")
    p.add_argument("--deployable-packagings", nargs="*", default=sorted(DEFAULT_DEPLOYABLE_PACKAGINGS),
                   help="Packagings considerados deployáveis")
    return p.parse_known_args()[0]

def build_repo_path(owner: str, name: str) -> Path:
    return Path(REPOS_DIR) / owner / name

def main():
    args = read_args(
        'merge_packaging_and_deployables',
        'Mescla classificação multi-módulo (packaging do POM raiz) com contagem de módulos deployáveis por projeto.',
        default_label_type="vulnerabilities",
        default_skip_remove=True
    )
    extra = parse_cli()

    deployable_packagings = set(x.lower() for x in extra.deployable_packagings)
    exclude_hints = list(extra.exclude)
    exclude_mode = extra.exclude_mode

    db.connect()
    projects = get_or_create_projects(
        create_version=False,
        filename=args.input,
        filters=args.filter,
        min_project=args.min_project,
        max_project=args.max_project,
        skip_remove=args.skip_remove
    )

    proj_rows, dep_rows = [], []
    print(f"[INFO] Projetos carregados: {len(projects)}")

    for prj in projects:
        repo_root = build_repo_path(prj.owner, prj.name)
        if not repo_root.is_dir():
            print(yellow(f"[WARN] Repo path not found: {repo_root}"))
            continue

        # (1) Classificação pelo POM raiz
        root_info = classify_by_root(repo_root)

        # (2) Varredura deployáveis por POM
        total_poms = 0
        deployables_count = 0
        excluded_count = 0

        for pom in list_all_poms(repo_root):
            total_poms += 1
            rel_dir = str(pom.parent.relative_to(repo_root)) if pom.parent != repo_root else "."
            meta = parse_pom_metadata(pom)
            is_deployable, reason = decide_deployable(meta, deployable_packagings)
            excluded = is_excluded_path(rel_dir, exclude_hints)
            if excluded:
                excluded_count += 1

            if excluded and exclude_mode == "drop":
                # não grava linha, mas conta exclusões
                continue

            dep_rows.append({
                "owner": prj.owner,
                "name": prj.name,
                "repo_path": str(repo_root),
                "module_dir": rel_dir,
                "pom_path_rel": ("pom.xml" if rel_dir == "." else f"{rel_dir}/pom.xml"),
                "pom_path_abs": str(pom.resolve()),
                "groupId": meta.get("groupId"),
                "artifactId": meta.get("artifactId"),
                "version": meta.get("version"),
                "packaging": meta.get("packaging"),
                "spring_boot_plugin": bool(meta.get("boot_repackage", False)),
                "is_deployable": bool(is_deployable),
                "deployable_reason": reason,
                "is_excluded": bool(excluded),
            })

            if is_deployable:
                deployables_count += 1

        # linha agregada por projeto
        proj_rows.append({
            "owner": prj.owner,
            "name": prj.name,
            "repo_path": str(repo_root),
            "has_root_pom": root_info["has_root_pom"],
            "root_packaging": root_info["root_packaging"],
            "root_modules_declared_count": root_info["root_modules_declared_count"],
            "classification": root_info["classification"],
            "total_poms": total_poms,
            "deployables_count": deployables_count,
            "excluded_count": excluded_count
        })

        print(f"{prj.owner}/{prj.name} -> {root_info['classification']} "
              f"(root packaging={root_info['root_packaging']}, modules={root_info['root_modules_declared_count']}) | "
              f"deployables={deployables_count}/{total_poms}, excluded={excluded_count}")

    # --- grava CSVs ---
    try:
        with open(extra.out_projects, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "owner","name","repo_path",
                "has_root_pom","root_packaging","root_modules_declared_count","classification",
                "total_poms","deployables_count","excluded_count"
            ])
            w.writeheader(); w.writerows(proj_rows)
        print(f"[OK] CSV (projetos): {extra.out_projects}")

        with open(extra.out_deployables, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "owner","name","repo_path","module_dir","pom_path_rel","pom_path_abs",
                "groupId","artifactId","version","packaging","spring_boot_plugin",
                "is_deployable","deployable_reason","is_excluded"
            ])
            w.writeheader(); w.writerows(dep_rows)
        print(f"[OK] CSV (deployáveis): {extra.out_deployables}")
    except Exception as e:
        print(yellow(f"[WARN] Falha ao salvar CSVs: {e}"))

    # --- XLSX opcional ---
    if HAS_PANDAS:
        try:
            df_dep = pd.DataFrame(dep_rows)
            df_proj = pd.DataFrame(proj_rows)
            by_repo = (df_dep.assign(_repo=df_dep["owner"]+"/"+df_dep["name"])
                              .groupby("_repo")
                              .agg(total_poms=("pom_path_abs","count"),
                                   deployables=("is_deployable","sum"),
                                   excluded=("is_excluded","sum"))
                              .reset_index())
            with pd.ExcelWriter(extra.out_xlsx, engine="openpyxl") as writer:
                df_proj.to_excel(writer, index=False, sheet_name="projects_summary")
                df_dep.to_excel(writer, index=False, sheet_name="deployables_raw")
                by_repo.to_excel(writer, index=False, sheet_name="summary_by_repo")
            print(f"[OK] XLSX salvo: {extra.out_xlsx}")
        except Exception as e:
            print(yellow(f"[WARN] Falha ao salvar XLSX: {e}"))

    db.close()

if __name__ == "__main__":
    main()
