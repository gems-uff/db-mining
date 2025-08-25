import os
import re
import json
import sys
import argparse
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple, Dict

# === dependências do seu projeto ===
import database as db
from extract import (
    get_or_create_projects,
    read_args,
)
from util import REPOS_DIR, yellow

# opcional para gerar planilha
try:
    import pandas as pd
    HAS_PANDAS = True
except Exception:
    HAS_PANDAS = False

IGNORES = {
    ".git", "target", "build", "dist", "out", "node_modules", "venv",
    ".venv", "__pycache__", ".idea", ".vscode", ".mvn", ".gradle"
}

BUILD_MARKERS = {
    "maven": ["pom.xml"],
    "gradle": ["build.gradle", "build.gradle.kts"],
    "node": ["package.json"],
    "python": ["pyproject.toml", "setup.py"],
}

def is_maven_monorepo(root: Path) -> bool:
    pom = root / "pom.xml"
    if not pom.is_file():
        return False
    try:
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        tree = ET.parse(pom)
        root_xml = tree.getroot()
        modules = root_xml.find("m:modules", ns) or root_xml.find("modules")
        if modules is None:
            return False
        items = modules.findall("m:module", ns) or modules.findall("module")
        return len(items) > 0
    except ET.ParseError:
        return False

def has_gradle_multiproject(root: Path) -> bool:
    for fname in ("settings.gradle", "settings.gradle.kts"):
        f = root / fname
        if f.is_file():
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if re.search(r"\binclude\s*\(", txt) or re.search(r'^\s*include\s+["\':]', txt, re.M):
                return True
    return False

def has_node_workspaces(root: Path) -> bool:
    pkg = root / "package.json"
    if not pkg.is_file():
        return False
    try:
        data = json.loads(pkg.read_text(encoding="utf-8", errors="ignore"))
        return "workspaces" in data
    except Exception:
        return False

def find_project_roots(repo_root: Path) -> List[Path]:
    roots = []
    for cur, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in IGNORES]
        curpath = Path(cur)
        file_set = set(files)
        has_marker = any(any(m in file_set for m in markers) for markers in BUILD_MARKERS.values())
        if has_marker:
            roots.append(curpath)
            dirs[:] = []  # não desce mais dentro desta raiz
    return roots

def classify_repo(repo_path: Path) -> Tuple[str, Dict[str, bool]]:
    repo_path = repo_path.resolve()
    if not repo_path.is_dir():
        return ("DESCONHECIDO", {"erro": True, "gradle_multi": False, "node_workspaces": False})
    maven_monorepo = is_maven_monorepo(repo_path)
    gradle_multi = has_gradle_multiproject(repo_path)
    node_ws = has_node_workspaces(repo_path)
    project_roots = find_project_roots(repo_path)

    if maven_monorepo:
        return ("MONOREPO_MAVEN", {"gradle_multi": gradle_multi, "node_workspaces": node_ws})
    if len(project_roots) > 1:
        return ("MULTIPROJETOS", {"gradle_multi": gradle_multi, "node_workspaces": node_ws})
    if len(project_roots) == 1:
        return ("SINGLE_REPO", {"gradle_multi": gradle_multi, "node_workspaces": node_ws})
    return ("DESCONHECIDO", {"gradle_multi": gradle_multi, "node_workspaces": node_ws})

def build_repo_path(owner: str, name: str) -> Path:
    return Path(REPOS_DIR) / owner / name

# ---------- NOVO: contagens de POMs e commits ----------
def list_all_poms(repo_root: Path) -> List[Path]:
    poms = []
    for cur, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in IGNORES]
        if "pom.xml" in files:
            poms.append(Path(cur) / "pom.xml")
    return poms

def count_repo_poms(repo_root: Path) -> int:
    return len(list_all_poms(repo_root))

def _git(repo_root: Path, args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )

def is_git_repo(repo_root: Path) -> bool:
    r = _git(repo_root, ["rev-parse", "--is-inside-work-tree"])
    return r.returncode == 0 and r.stdout.strip() == "true"

def count_pom_commits(repo_root: Path, max_count: int = None) -> int:
    """
    Conta commits que tocaram QUALQUER pom.xml no repositório.
    Tenta pathspec glob (Git >= 2.13). Se falhar, faz fallback listando todos os poms.
    """
    if not is_git_repo(repo_root):
        return 0

    base_cmd = ["rev-list", "--all", "--no-merges"]
    if max_count is not None and max_count > 0:
        base_cmd = ["rev-list", f"--max-count={max_count}", "--all", "--no-merges"]

    # 1) Tenta glob pathspec:
    try_cmd = _git(repo_root, ["-c", "globpathspecs=true"] + base_cmd + ["--", ":(glob)**/pom.xml"])
    if try_cmd.returncode == 0 and try_cmd.stdout:
        # dedup não é necessário aqui; rev-list já entrega sem repetição para um pathspec
        return len(try_cmd.stdout.strip().splitlines())

    # 2) Fallback: lista todos os poms e passa cada um explicitamente.
    poms = list_all_poms(repo_root)
    if not poms:
        return 0

    # Para não ultrapassar limites de linha de comando, pode particionar se houver muitos poms.
    commits = set()
    chunk = 200  # razoável na prática
    pom_paths = [str(p.relative_to(repo_root)) for p in poms]
    for i in range(0, len(pom_paths), chunk):
        part = pom_paths[i:i+chunk]
        r = _git(repo_root, base_cmd + ["--"] + part)
        if r.returncode == 0 and r.stdout:
            for line in r.stdout.strip().splitlines():
                commits.add(line)
    return len(commits)

# ---------- CLI extra ----------
def parse_extra_cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--out-xlsx", default="classificacao.xlsx")
    p.add_argument("--out-csv", default="classificacao.csv")
    p.add_argument("--max-commit-scan", type=int, default=0,
                   help="Limita a contagem aos N commits mais recentes (0 = todo histórico).")
    return p.parse_known_args()[0]

def main():
    args = read_args(
        'classify_repos',
        'Classify repositories (DB-mining): monorepo vs multiprojetos vs single',
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

    rows = []
    print(f"\nFound {len(projects)} projects. Classifying...\n")
    print("owner,name,repo_path,classe,gradle_multi,node_workspaces,erro_no_caminho,total_poms,total_pom_commits")

    for project in projects:
        repo_path = build_repo_path(project.owner, project.name)
        classe, flags = classify_repo(repo_path)
        gradle_flag = bool(flags.get("gradle_multi", False))
        node_flag = bool(flags.get("node_workspaces", False))
        err_flag = bool(flags.get("erro", False))

        # NOVO: contagens
        total_poms = count_repo_poms(repo_path) if not err_flag else 0
        total_pom_commits = count_pom_commits(
            repo_path, max_count=extra.max_commit_scan if extra.max_commit_scan > 0 else None
        ) if not err_flag else 0

        print(f"{project.owner},{project.name},{repo_path},{classe},{gradle_flag},{node_flag},{err_flag},{total_poms},{total_pom_commits}")

        rows.append({
            "owner": project.owner,
            "name": project.name,
            "repo_path": str(repo_path),
            "classe": classe,
            "gradle_multi": gradle_flag,
            "node_workspaces": node_flag,
            "erro_no_caminho": err_flag,
            "total_poms": total_poms,
            "total_pom_commits": total_pom_commits
        })

    # Resumo no stdout
    from collections import Counter
    counts = Counter(r["classe"] for r in rows)
    print("\nResumo por classe:")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print("\nMétricas agregadas:")
    soma_poms = sum(r["total_poms"] for r in rows)
    soma_commits = sum(r["total_pom_commits"] for r in rows)
    print(f"  Total de pom.xml nos repos: {soma_poms}")
    print(f"  Total de commits que tocaram pom.xml: {soma_commits}")

    # Saídas em CSV/XLSX
    try:
        import csv
        fieldnames = ["owner","name","repo_path","classe","gradle_multi","node_workspaces",
                      "erro_no_caminho","total_poms","total_pom_commits"]
        with open(extra.out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        print(f"\n[OK] CSV salvo em: {extra.out_csv}")
    except Exception as e:
        print(yellow(f"[WARN] Falha ao salvar CSV: {e}"))

    if HAS_PANDAS:
        try:
            df = pd.DataFrame(rows)
            resumo = pd.DataFrame(
                [{"classe": k, "quantidade": v} for k, v in counts.items()]
            )
            resumo2 = pd.DataFrame([{
                "total_poms": soma_poms,
                "total_pom_commits": soma_commits
            }])
            with pd.ExcelWriter(extra.out_xlsx, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="classificacao")
                resumo.to_excel(writer, index=False, sheet_name="resumo_classe")
                resumo2.to_excel(writer, index=False, sheet_name="resumo_metrico")
            print(f"[OK] XLSX salvo em: {extra.out_xlsx}")
        except Exception as e:
            print(yellow(f"[WARN] Falha ao salvar XLSX: {e}"))
    else:
        print(yellow("[INFO] pandas não instalado; XLSX não gerado. Instale com: pip install pandas openpyxl"))

    db.close()

if __name__ == "__main__":
    main()
