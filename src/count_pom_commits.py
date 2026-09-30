import os
import re
import subprocess
from typing import Optional, Dict, List

import database as db
from extract import get_or_create_projects, read_args
from util import REPOS_DIR, red, green, yellow

GREP_COMMAND_LOG_COMMAND_POM = [
    "git", "log", "--first-parent", "-p", "--reverse",
    "--format=%H|%cI", "--",
    "pom.xml"
]

_SHA_LINE_RE = re.compile(r"^[0-9a-f]{40}\|")

import csv
from datetime import datetime

def export_pom_commit_counts_to_csv(results, out_dir="outputs"):
    """
    Gera um CSV com:
    project, pom_commits
    """
    os.makedirs(out_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, f"pom_commit_counts_{ts}.csv")

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["project", "pom_commits"]
        )
        writer.writeheader()
        for row in results:
            writer.writerow(row)

    print(green(f"CSV gerado em: {out_path}"))
    return out_path


def count_pom_commits(project, args) -> int:
    """
    Conta commits que alteraram **/pom.xml para um projeto já conhecido no banco.
    O repositório é sempre resolvido via REPOS_DIR/owner/name.
    """
    repo_path = os.path.join(REPOS_DIR, project.owner, project.name)

    if not os.path.isdir(repo_path):
        print(yellow(f"Repo não encontrado: {project.owner}/{project.name}"))
        return 0

    cmd = list(GREP_COMMAND_LOG_COMMAND_POM)

    if getattr(args, "latest_only", False):
        cmd[1:1] += ["-n", "1"]
    elif getattr(args, "max_commits", None):
        cmd[1:1] += ["-n", str(args.max_commits)]

    try:
        p = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            check=False,
            timeout=getattr(args, "timeout_sec", 600),
        )

        output = p.stdout.decode(errors="replace").replace("\x00", "\uFFFD")

        count = 0
        for line in output.splitlines():
            if _SHA_LINE_RE.match(line):
                count += 1

        return count

    except subprocess.TimeoutExpired:
        print(red(f"Git timeout: {project.owner}/{project.name}"))
        return 0
    except Exception as e:
        print(red(f"Erro em {project.owner}/{project.name}: {e}"))
        return 0

def process_projects(args):
    db.connect()

    projects = get_or_create_projects(
        create_version=False,
        filename=args.input,
        filters=args.filter,
        min_project=args.min_project,
        max_project=args.max_project,
        skip_remove=args.skip_remove
    )

    print(green(f"Processando {len(projects)} projetos."))

    results = []

    for project in projects:
        n_commits = count_pom_commits(project, args)

        results.append({
            "project": f"{project.owner}/{project.name}",
            "pom_commits": n_commits
        })

        print(green(f"{project.owner}/{project.name}: {n_commits} commits em pom.xml"))

    db.close()
    return results

def main():
    args = read_args(
        "count_pom_commits",
        "Count commits that changed pom.xml",
        default_skip_remove=True
    )

    # garante compatibilidade com scripts antigos
    if not hasattr(args, "max_commits"):
        args.max_commits = None
    if not hasattr(args, "latest_only"):
        args.latest_only = False
    if not hasattr(args, "timeout_sec"):
        args.timeout_sec = 600

    results = process_projects(args)

    export_pom_commit_counts_to_csv(results)


if __name__ == "__main__":
    main()
