#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validação Heurística — Caso 3 (com todos os repositórios listados)

Agora lista **todos** os repositórios encontrados com pom.xml na raiz,
mesmo que não atendam aos critérios do Caso 3.

Colunas principais:
repo, root_packaging, sub_poms, toy_like, child_of_root, independent_like, classification, examples
"""

import os
import csv
import xml.etree.ElementTree as ET
from pathlib import Path
from util import REPOS_DIR

NAMESPACE = {'m': 'http://maven.apache.org/POM/4.0.0'}
TOY_KEYWORDS = ("sample", "samples", "example", "examples", "demo", "demos",
                "test", "tests", "it", "integration", "benchmark", "perf",
                "playground", "tutorial", "doc", "docs", "quickstart")
SKIP_DIRS = {".git", "target", ".mvn", ".idea", ".github"}

# ---------- Funções auxiliares (iguais às anteriores) ----------

def safe_parse_pom(pom_path):
    try:
        tree = ET.parse(pom_path)
        return tree.getroot()
    except Exception:
        return None

def get_text(node, tag):
    if node is None:
        return None
    el = node.find(f"m:{tag}", NAMESPACE)
    return el.text.strip() if el is not None and el.text else None

def read_pom_info(pom_path):
    root = safe_parse_pom(pom_path)
    if root is None:
        return None

    packaging = get_text(root, "packaging") or "jar"
    group_id = get_text(root, "groupId")
    artifact_id = get_text(root, "artifactId")
    version = get_text(root, "version")

    parent = root.find("m:parent", NAMESPACE)
    parent_gid = get_text(parent, "groupId")
    parent_aid = get_text(parent, "artifactId")
    parent_ver = get_text(parent, "version")

    modules = []
    modules_node = root.find("m:modules", NAMESPACE)
    if modules_node is not None:
        for m in modules_node.findall("m:module", NAMESPACE):
            if m.text:
                modules.append(m.text.strip())

    return {
        "packaging": packaging,
        "groupId": group_id,
        "artifactId": artifact_id,
        "version": version,
        "parent_groupId": parent_gid,
        "parent_artifactId": parent_aid,
        "parent_version": parent_ver,
        "modules": modules
    }

def path_looks_toy(p):
    return any(k in str(p).lower().split(os.sep) for k in TOY_KEYWORDS)

def has_src_main(project_dir: Path):
    for lang in ("java", "kotlin", "scala"):
        if (project_dir / "src" / "main" / lang).exists():
            return True
    return False

def classify_subpom(sub_pom_dir: Path, root_coords, root_modules):
    info = read_pom_info(sub_pom_dir / "pom.xml")
    if info is None:
        return "toy_like"
    rel = str(sub_pom_dir.relative_to(root_coords["root_dir"]))
    parent_matches_root = (
        info["parent_groupId"] == root_coords["groupId"] and
        info["parent_artifactId"] == root_coords["artifactId"]
    )
    if path_looks_toy(sub_pom_dir):
        return "toy_like"
    if info["packaging"] == "pom" and not has_src_main(sub_pom_dir):
        return "toy_like"
    if parent_matches_root:
        if has_src_main(sub_pom_dir) and (info["groupId"] != root_coords["groupId"] or info["version"]):
            return "independent_like"
        return "child_of_root"
    if has_src_main(sub_pom_dir) and info["packaging"] != "pom":
        return "independent_like"
    return "toy_like"

def extract_repo_name(abs_path: Path) -> str:
    base = Path(REPOS_DIR)
    rel = abs_path.relative_to(base)
    parts = rel.parts
    return "/".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else str(abs_path.name))

def find_all_root_poms():
    for root, dirs, files in os.walk(REPOS_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if "pom.xml" in files:
            yield Path(root)
            dirs[:] = []

def list_subpom_dirs(root_dir: Path):
    subdirs = []
    for r, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if "pom.xml" in files and Path(r) != root_dir:
            subdirs.append(Path(r))
    return subdirs

# ---------- Classificação principal (alterada) ----------

def classify_repo_case3(root_dir: Path):
    """Retorna dict com info, incluindo NOT_CASE3 para os que não se encaixam."""
    root_pom = root_dir / "pom.xml"
    root_info = read_pom_info(root_pom)
    repo_result = {
        "repo": extract_repo_name(root_dir),
        "root_packaging": None,
        "sub_poms": 0,
        "toy_like": 0,
        "child_of_root": 0,
        "independent_like": 0,
        "classification": "NOT_CASE3",
        "examples": ""
    }

    if root_info is None:
        return repo_result

    repo_result["root_packaging"] = root_info["packaging"]
    subdirs = list_subpom_dirs(root_dir)
    repo_result["sub_poms"] = len(subdirs)

    # caso 3 válido: packaging=jar + sem modules + tem sub-POMs
    if root_info["packaging"] == "jar" and not root_info["modules"] and subdirs:
        toy, child, indep = 0, 0, 0
        for sd in subdirs:
            label = classify_subpom(sd, {
                "root_dir": root_dir,
                "groupId": root_info["groupId"],
                "artifactId": root_info["artifactId"]
            }, root_info["modules"])
            if label == "toy_like": toy += 1
            elif label == "child_of_root": child += 1
            elif label == "independent_like": indep += 1
        repo_result.update({
            "toy_like": toy,
            "child_of_root": child,
            "independent_like": indep,
            "classification": (
                "CASE3_B_MONOREPO_LIKELY" if indep > 0
                else "CASE3_A_SINGLE_PROJECT_LIKELY"
            )
        })
    # caso não se enquadre → mantém "NOT_CASE3"
    return repo_result

# ---------- Execução principal ----------

def main():
    all_results = []
    for root_dir in find_all_root_poms():
        result = classify_repo_case3(root_dir)
        all_results.append(result)

    out_csv = "case3_classification_all.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "repo", "root_packaging", "sub_poms",
            "toy_like", "child_of_root", "independent_like",
            "classification", "examples"
        ])
        w.writeheader()
        w.writerows(all_results)

    total = len(all_results)
    case3 = sum(1 for r in all_results if r["classification"].startswith("CASE3"))
    print(f"[Resumo] Total de repositórios analisados: {total}")
    print(f" - Candidatos Caso 3: {case3}")
    print(f" - Outros (NOT_CASE3): {total - case3}")
    print(f"Relatório salvo em: {out_csv}")

if __name__ == "__main__":
    main()
