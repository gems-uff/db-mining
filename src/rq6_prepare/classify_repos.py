#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Classificação de repositórios: SINGLE_REPO | MONOREPO_MAVEN | MULTIPROJETOS | DESCONHECIDO

Regras Maven:
1) POM na raiz com <modules> ....................... MONOREPO_MAVEN
2) POM na raiz sem <modules> e sem sub-POMs ........ SINGLE_REPO
3) POM na raiz sem <modules>, mas sub-POMs com <parent> = raiz ... MONOREPO_MAVEN
4) POM na raiz sem <modules>, sub-POMs sem vínculo .. MULTIPROJETOS
5) Sem POM na raiz:
   - se houver >1 "raiz de projeto" (Maven/Gradle/Node/Python) ... MULTIPROJETOS
   - se houver 1 .................................................. SINGLE_REPO
"""

import os, re, json, argparse, subprocess, xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple, Dict

# === dependências do seu projeto ===
import database as db
from extract import get_or_create_projects, read_args
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

# ---------------------------------------------------------------------------
# Helpers XML / Maven
# ---------------------------------------------------------------------------

def _read_xml_ns_aware(p: Path):
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None, "", None
    try:
        root = ET.fromstring(txt)
    except ET.ParseError:
        return None, txt, None  # fallback textual
    ns_uri = root.tag.split('}')[0].strip('{') if root.tag.startswith('{') else None
    def q(name):  # query com namespace dinâmico
        return f"{{{ns_uri}}}{name}" if ns_uri else name
    return root, txt, q

def _has_modules_in_pom(pom_path: Path) -> bool:
    root, txt, q = _read_xml_ns_aware(pom_path)
    if root is None:
        # fallback regex (pega até em perfis)
        return bool(re.search(r"<modules[^>]*>.*?<module>.+?</module>.*?</modules>", txt, re.S))
    # Procura modules em qualquer lugar (raiz, perfis, etc.)
    mods = root.findall(".//{*}modules")
    if not mods:
        m = root.find(q("modules")) if q else root.find("modules")
        mods = [m] if m is not None else []
    for m in mods:
        items = m.findall(".//{*}module") or m.findall("module")
        if items:
            return True
    return False

def _extract_gav(pom_path: Path):
    """Retorna (groupId, artifactId, version, packaging) do POM (best effort)."""
    root, txt, q = _read_xml_ns_aware(pom_path)
    if root is None:
        def _rgx(tag):
            m = re.search(rf"<{tag}>([^<]+)</{tag}>", txt)
            return m.group(1).strip() if m else None
        gid = _rgx("groupId")
        aid = _rgx("artifactId")
        ver = _rgx("version")
        pkg = _rgx("packaging")
    else:
        def _find_text(tag):
            n = root.find(q(tag)) if q else root.find(tag)
            return (n.text or "").strip() if n is not None and n.text else None
        gid = _find_text("groupId")
        aid = _find_text("artifactId")
        ver = _find_text("version")
        pkg = _find_text("packaging")
        # groupId/version podem vir do parent
        if not gid or not ver:
            par = root.find(".//{*}parent")
            if par is not None:
                g = par.find(".//{*}groupId") or par.find("groupId")
                v = par.find(".//{*}version") or par.find("version")
                gid = (g.text or "").strip() if (not gid and g is not None and g.text) else gid
                ver = (v.text or "").strip() if (not ver and v is not None and v.text) else ver
    return gid, aid, ver, pkg

def _pom_has_parent_gav(pom_path: Path, parent_gav: tuple) -> bool:
    """Verifica se pom_path declara <parent> correspondente a parent_gav (gid, aid)."""
    pgid, paid = parent_gav[:2]
    if not pgid or not paid:
        return False
    root, txt, q = _read_xml_ns_aware(pom_path)
    if root is None:
        mg = re.search(r"<parent>.*?<groupId>([^<]+)</groupId>.*?</parent>", txt, re.S)
        ma = re.search(r"<parent>.*?<artifactId>([^<]+)</artifactId>.*?</parent>", txt, re.S)
        g = mg.group(1).strip() if mg else None
        a = ma.group(1).strip() if ma else None
        return (g == pgid and a == paid)
    par = root.find(".//{*}parent")
    if par is None:
        return False
    g = par.find(".//{*}groupId") or par.find("groupId")
    a = par.find(".//{*}artifactId") or par.find("artifactId")
    g = (g.text or "").strip() if g is not None and g.text else None
    a = (a.text or "").strip() if a is not None and a.text else None
    return (g == pgid and a == paid)

def _list_subpom_paths(repo_root: Path) -> List[Path]:
    subpoms = []
    for cur, dirs, files in os.walk(repo_root):
        # não descer em diretórios ignorados
        dirs[:] = [d for d in dirs if d not in IGNORES]
        curp = Path(cur)
        if curp == repo_root:
            continue  # não adiciona o pom da raiz
        if "pom.xml" in files:
            subpoms.append(curp / "pom.xml")
    return subpoms

def _assess_maven_structure(repo_root: Path) -> Dict[str, object]:
    """
    Retorna diagnóstico do layout Maven:
      - has_root_pom
      - root_has_modules
      - root_gav (gid, aid, ver, pkg)
      - subpom_count
      - linked_to_root_count (via <parent>)
    """
    root_pom = repo_root / "pom.xml"
    has_root = root_pom.is_file()
    diag = {
        "has_root_pom": has_root,
        "root_has_modules": False,
        "root_gav": (None, None, None, None),
        "subpom_count": 0,
        "linked_to_root_count": 0,
    }
    if not has_root:
        return diag
    # raiz tem modules?
    root_has_modules = _has_modules_in_pom(root_pom)
    gid, aid, ver, pkg = _extract_gav(root_pom)
    diag["root_has_modules"] = root_has_modules
    diag["root_gav"] = (gid, aid, ver, pkg)
    # contar sub-POMs e quantos apontam parent para a raiz
    subpoms = _list_subpom_paths(repo_root)
    diag["subpom_count"] = len(subpoms)
    if (gid and aid):
        linked = 0
        for sp in subpoms:
            if _pom_has_parent_gav(sp, (gid, aid, ver, pkg)):
                linked += 1
        diag["linked_to_root_count"] = linked
    return diag

# ---------------------------------------------------------------------------
# Detectores auxiliares (Gradle / Node) - flags de contexto
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Scanner de "raízes de projeto" (Maven/Gradle/Node/Python)
# ---------------------------------------------------------------------------

def find_project_roots(repo_root: Path) -> List[Path]:
    roots = []
    for cur, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in IGNORES]
        curpath = Path(cur)
        file_set = set(files)
        has_marker = any(any(m in file_set for m in markers) for markers in BUILD_MARKERS.values())
        if has_marker:
            roots.append(curpath)
            # ao entrar num subprojeto, não descer mais
            if curpath != repo_root:
                dirs[:] = []
    return roots

# ---------------------------------------------------------------------------
# Classificação do repositório
# ---------------------------------------------------------------------------

def classify_repo(repo_path: Path) -> Tuple[str, Dict[str, object]]:
    repo_path = repo_path.resolve()
    if not repo_path.is_dir():
        return ("DESCONHECIDO", {"erro": True, "gradle_multi": False, "node_workspaces": False})

    gradle_multi = has_gradle_multiproject(repo_path)
    node_ws = has_node_workspaces(repo_path)
    project_roots = find_project_roots(repo_path)

    mdiag = _assess_maven_structure(repo_path)
    has_root_pom = mdiag["has_root_pom"]
    root_has_modules = mdiag["root_has_modules"]
    subpom_count = mdiag["subpom_count"]
    linked_to_root = mdiag["linked_to_root_count"]

    # --- Regras Maven ---
    if has_root_pom:
        if root_has_modules:
            return ("MONOREPO_MAVEN", {"gradle_multi": gradle_multi, "node_workspaces": node_ws, "maven_diag": mdiag})
        if subpom_count == 0:
            return ("SINGLE_REPO", {"gradle_multi": gradle_multi, "node_workspaces": node_ws, "maven_diag": mdiag})
        if linked_to_root > 0:
            return ("MONOREPO_MAVEN", {"gradle_multi": gradle_multi, "node_workspaces": node_ws, "maven_diag": mdiag})
        return ("MULTIPROJETOS", {"gradle_multi": gradle_multi, "node_workspaces": node_ws, "maven_diag": mdiag})

    # --- Sem POM na raiz: decide por “raízes de projeto” ---
    if len(project_roots) > 1:
        return ("MULTIPROJETOS", {"gradle_multi": gradle_multi, "node_workspaces": node_ws, "maven_diag": mdiag})
    if len(project_roots) == 1:
        return ("SINGLE_REPO", {"gradle_multi": gradle_multi, "node_workspaces": node_ws, "maven_diag": mdiag})
    return ("DESCONHECIDO", {"gradle_multi": gradle_multi, "node_workspaces": node_ws, "maven_diag": mdiag})

# ---------------------------------------------------------------------------
# Utilidades Git e contagens (opcionais)
# ---------------------------------------------------------------------------

def build_repo_path(owner: str, name: str) -> Path:
    return Path(REPOS_DIR) / owner / name

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
    return subprocess.run(["git"] + args, cwd=str(repo_root),
                          capture_output=True, text=True, check=False)

def is_git_repo(repo_root: Path) -> bool:
    r = _git(repo_root, ["rev-parse", "--is-inside-work-tree"])
    return r.returncode == 0 and r.stdout.strip() == "true"

def count_pom_commits(repo_root: Path, max_count: int = None) -> int:
    """Conta commits que tocaram QUALQUER pom.xml no repositório."""
    if not is_git_repo(repo_root):
        return 0
    base_cmd = ["rev-list", "--all", "--no-merges"]
    if max_count and max_count > 0:
        base_cmd = ["rev-list", f"--max-count={max_count}", "--all", "--no-merges"]
    # tenta glob pathspec
    r = _git(repo_root, ["-c", "globpathspecs=true"] + base_cmd + ["--", ":(glob)**/pom.xml"])
    if r.returncode == 0 and r.stdout:
        return len(r.stdout.strip().splitlines())
    # fallback listando poms explicitamente
    commits = set()
    poms = list_all_poms(repo_root)
    if not poms:
        return 0
    chunk = 200
    rels = [str(p.relative_to(repo_root)) for p in poms]
    for i in range(0, len(rels), chunk):
        rr = _git(repo_root, base_cmd + ["--"] + rels[i:i+chunk])
        if rr.returncode == 0 and rr.stdout:
            commits |= set(rr.stdout.strip().splitlines())
    return len(commits)

# ---------------------------------------------------------------------------
# CLI extra e main
# ---------------------------------------------------------------------------

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
            resumo = pd.DataFrame([{"classe": k, "quantidade": v} for k, v in counts.items()])
            resumo2 = pd.DataFrame([{"total_poms": soma_poms, "total_pom_commits": soma_commits}])
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
