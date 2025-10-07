#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pré-processamento (DB-mining): módulos deployáveis em projetos Maven

Objetivo:
- Unidade de análise = módulo deployável (packaging != pom; jar/war/ear/rar/ejb/bundle) ou
  módulo com spring-boot-maven-plugin (repackage), mesmo que packaging seja jar/war.
- Excluir (ou rotular) módulos em paths típicos de sample/doc tooling: examples, quickstart, docs, tools (customizável).
Saídas:
- deployables.csv: um por POM encontrado com metadata e flag is_deployable / is_excluded
- (opcional) XLSX consolidado
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

try:
    import pandas as pd
    HAS_PANDAS = True
except Exception:
    HAS_PANDAS = False

IGNORES = {
    ".git", "target", "build", "dist", "out", "node_modules", "venv",
    ".venv", "__pycache__", ".idea", ".vscode", ".mvn", ".gradle"
}

DEFAULT_DEPLOYABLE_PACKAGINGS = {"jar", "war", "ear", "rar", "ejb", "bundle"}
DEFAULT_EXCLUDE_DIR_HINTS = {"examples", "example", "quickstart", "quick-start", "samples", "sample",
                             "docs", "documentation", "site", "tools", "tooling", "demo", "demos", "playground", "kitchen-sink"}

SPRING_BOOT_PLUGIN_ARTIFACT = "spring-boot-maven-plugin"

# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _read_xml_ns_aware(p: Path):
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

def _text(node: Optional[ET.Element]) -> Optional[str]:
    return (node.text or "").strip() if node is not None and node.text else None

def _local(tag: str) -> str:
    if not tag: return ""
    return tag.split("}",1)[-1].split(":",1)[-1]

# ---------------------------------------------------------------------------
# Maven parsing
# ---------------------------------------------------------------------------

def parse_pom_metadata(pom_path: Path) -> Dict[str, Optional[str]]:
    """
    Lê groupId, artifactId, version, packaging e flags de spring-boot (repackage).
    Aplica default packaging=jar quando ausente (regra Maven).
    """
    meta = {
        "groupId": None,
        "artifactId": None,
        "version": None,
        "packaging": None,
        "boot_repackage": False,
    }
    root, txt, q = _read_xml_ns_aware(pom_path)
    if root is None:
        # fallback rápido só para packaging
        m = re.search(r"<packaging>([^<]+)</packaging>", txt, re.I)
        meta["packaging"] = (m.group(1).strip() if m else None) or "jar"
        # spring-boot plugin (heurística textual)
        if re.search(r"<artifactId>\s*spring-boot-maven-plugin\s*</artifactId>", txt, re.I):
            # procurar goal repackage (opcional, mas vale marcar boot_repackage=True de qualquer forma)
            meta["boot_repackage"] = True
        # tentar pegar básica de GAV
        g = re.search(r"<groupId>([^<]+)</groupId>", txt)
        a = re.search(r"<artifactId>([^<]+)</artifactId>", txt)
        v = re.search(r"<version>([^<]+)</version>", txt)
        meta["groupId"] = g.group(1).strip() if g else None
        meta["artifactId"] = a.group(1).strip() if a else None
        meta["version"] = v.group(1).strip() if v else None
        return meta

    # GAV direto
    meta["groupId"] = _text(root.find(q("groupId")))
    meta["artifactId"] = _text(root.find(q("artifactId")))
    meta["version"] = _text(root.find(q("version")))
    # herança (se quiser resolver de fato, teria que buscar <parent>; aqui mantemos simples)
    if (not meta["groupId"]) or (not meta["version"]):
        par = root.find(q("parent"))
        if par is not None:
            pg = _text(par.find(q("groupId")))
            pv = _text(par.find(q("version")))
            meta["groupId"] = meta["groupId"] or pg
            meta["version"] = meta["version"] or pv

    # packaging com default jar
    pkg = _text(root.find(q("packaging")))
    meta["packaging"] = pkg or "jar"

    # spring-boot plugin detection
    plugins = root.findall(".//{*}plugin")
    for p in plugins:
        aid = _text(p.find(".//{*}artifactId"))
        if (aid or "").strip() == SPRING_BOOT_PLUGIN_ARTIFACT:
            # se quiser, procurar goals/repackage
            goals = p.findall(".//{*}goal")
            if any((_text(g) or "").strip() == "repackage" for g in goals) or True:
                meta["boot_repackage"] = True
            break

    return meta

# ---------------------------------------------------------------------------
# Repo scan
# ---------------------------------------------------------------------------

def list_all_poms(repo_root: Path) -> List[Path]:
    poms = []
    for cur, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in IGNORES]
        if "pom.xml" in files:
            poms.append(Path(cur) / "pom.xml")
    return poms

def is_excluded_path(rel_dir: str, exclude_hints: List[str]) -> bool:
    parts = set(Path(rel_dir).parts)
    # match por “palavra de diretório” (mais robusto que substring solta)
    hints = set(hint.strip().lower() for hint in exclude_hints if hint.strip())
    return any(h in (p.lower() for p in parts) for h in hints)

def decide_deployable(meta: Dict[str, Optional[str]],
                      deployable_packagings: set) -> Tuple[bool, str]:
    """
    Regras:
      - packaging in deployable_packagings => deployável
      - packaging == 'pom' => NÃO deployável
      - packaging ausente => tratamos como 'jar' (Maven default) => deployável
      - spring-boot plugin => reforça deployável (mas packaging ainda manda)
    """
    pkg = (meta.get("packaging") or "jar").lower()
    if pkg == "pom":
        return False, "packaging=pom"
    if pkg in deployable_packagings:
        # se for jar/war e tiver spring-boot, menciona
        if meta.get("boot_repackage", False):
            return True, f"packaging={pkg}+spring-boot"
        return True, f"packaging={pkg}"
    # packaging fora da lista → normalmente não-deployável
    if meta.get("boot_repackage", False):
        # ainda pode ser deployável (jar) — mas se chegou aqui, packaging não está na lista.
        return True, f"spring-boot (packaging={pkg})"
    return False, f"packaging={pkg}"

# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------

def parse_extra_cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--out-csv", default="deployables.csv")
    p.add_argument("--out-xlsx", default="deployables.xlsx")
    p.add_argument("--exclude", nargs="*", default=sorted(DEFAULT_EXCLUDE_DIR_HINTS),
                   help="Pistas de diretórios a excluir/classificar à parte (ex.: examples docs tools)")
    p.add_argument("--exclude-mode", choices=["drop", "tag"], default="tag",
                   help="drop=excluir do CSV principal; tag=marcar is_excluded=True e manter")
    p.add_argument("--deployable-packagings", nargs="*", default=sorted(DEFAULT_DEPLOYABLE_PACKAGINGS),
                   help="Lista de packagings considerados deployáveis")
    return p.parse_known_args()[0]

def build_repo_path(owner: str, name: str) -> Path:
    return Path(REPOS_DIR) / owner / name

def main():
    args = read_args(
        'preprocess_deployables',
        'Descobre módulos deployáveis (packaging != pom) e rotula exemplos/quickstarts/docs/tools.',
        default_label_type="vulnerabilities",
        default_skip_remove=True
    )
    extra = parse_extra_cli()

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

    rows = []
    print(f"\nFound {len(projects)} projects. Scanning for deployable modules...\n")

    for project in projects:
        repo_root = build_repo_path(project.owner, project.name)
        if not repo_root.is_dir():
            print(yellow(f"[WARN] Repo path not found: {repo_root}"))
            continue

        poms = list_all_poms(repo_root)
        for pom in poms:
            rel_dir = str(pom.parent.relative_to(repo_root)) if pom.parent != repo_root else "."
            meta = parse_pom_metadata(pom)
            is_deployable, reason = decide_deployable(meta, deployable_packagings)
            excluded = is_excluded_path(rel_dir, exclude_hints)

            if excluded and exclude_mode == "drop":
                continue

            rows.append({
                "owner": project.owner,
                "name": project.name,
                "repo_path": str(repo_root),
                "module_dir": rel_dir,
                "pom_path_rel": (("pom.xml" if rel_dir == "." else f"{rel_dir}/pom.xml")),
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

    # CSV
    try:
        with open(extra.out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "owner","name","repo_path","module_dir","pom_path_rel","pom_path_abs",
                "groupId","artifactId","version","packaging","spring_boot_plugin",
                "is_deployable","deployable_reason","is_excluded"
            ])
            w.writeheader(); w.writerows(rows)
        print(f"[OK] CSV salvo em: {extra.out_csv}")
    except Exception as e:
        print(yellow(f"[WARN] Falha ao salvar CSV: {e}"))

    # XLSX opcional
    if HAS_PANDAS:
        try:
            df = pd.DataFrame(rows)
            # um resuminho útil
            summary = (df
                       .assign(_repo=df["owner"] + "/" + df["name"])
                       .groupby("_repo")
                       .agg(total_poms=("pom_path_abs","count"),
                            deployables=("is_deployable","sum"),
                            excluded=("is_excluded","sum"))
                       .reset_index()
                      )
            with pd.ExcelWriter(extra.out_xlsx, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="deployables_raw")
                summary.to_excel(writer, index=False, sheet_name="summary_by_repo")
            print(f"[OK] XLSX salvo em: {extra.out_xlsx}")
        except Exception as e:
            print(yellow(f"[WARN] Falha ao salvar XLSX: {e}"))

    db.close()

if __name__ == "__main__":
    main()
