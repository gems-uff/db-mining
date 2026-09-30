import os
import sys
import subprocess
from datetime import datetime
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor, as_completed

import database as db
from extract import (
    get_or_create_projects,
    do_commit,
    maybe_checkout,
    do_rev_parse,
    get_or_create_labels,
    read_args,
    prepare_version,
)
from util import REPOS_DIR, red, green, yellow, HEURISTICS_DIR_VULNERABILITIES

from typing import Optional, List, Dict, Tuple, Any
from sqlalchemy import func, text
from sqlalchemy.exc import OperationalError
from dataclasses import dataclass
from urllib.parse import quote


# =========================
# Configurações
# =========================
GREP_COMMAND_LOG_COMMAND_POM = [
    "git", "log", "--first-parent", "--reverse", "--format=%H|%cI", "--", "pom.xml", "**/pom.xml"
]

ROOT_ONLY = True
USE_ALL_DEPS = True
DEFAULT_PARALLEL_WORKERS = 2

_MODULE_HEADER_RE = re.compile(r"^\s*\[INFO\]\s+--- .* @ ([^ ]+) ---")
_DEP_LINE_RE = re.compile(
    r"^\s*(?:\[INFO\]\s*)?(?:[\|\+\-\\ ]*)\s*([^\s:]+):([^\s:]+):([^\s:]+):([^\s:]+)(?::([^\s:]+))?"
)
_POM_FROM_RE = re.compile(r"^\s*\[INFO\]\s+from\s+(.+?/pom\.xml)\s*$")


# =========================
# Reset
# =========================
def run_reset():
    subprocess.run(
        [sys.executable, "src/reset.py"],
        check=True
    )


# =========================
# SQLite helpers
# =========================
def configure_sqlite_for_parallel() -> None:
    """
    Ajustes best effort para reduzir contenção no SQLite.
    Não falha o processamento se algum PRAGMA não puder ser aplicado.
    """
    try:
        sess = db.db.session
        sess.execute(text("PRAGMA journal_mode=WAL"))
        sess.execute(text("PRAGMA synchronous=NORMAL"))
        sess.execute(text("PRAGMA busy_timeout=30000"))
        sess.commit()
    except Exception:
        safe_rollback()


# =========================
# Sessão / rollback
# =========================


def safe_rollback() -> None:
    """
    Faz rollback explícito da sessão atual, ignorando falhas secundárias.
    """
    try:
        db.db.session.rollback()
    except Exception:
        pass


def best_effort_analysis_event(**kwargs) -> None:
    """
    Tenta persistir um AnalysisEvent sem deixar a sessão contaminada caso falhe.
    """
    try:
        db.create(db.AnalysisEvent, **kwargs)
        do_commit()
    except Exception:
        safe_rollback()

# =========================
# Commits
# =========================
def list_pom_commits(
    latest_only: bool = False,
    max_commits: Optional[int] = None,
) -> List[Dict]:
    """
    Retorna commits que alteraram algum pom.xml.
    Usa committer date (%cI).
    """
    cmd = list(GREP_COMMAND_LOG_COMMAND_POM)

    if latest_only:
        cmd[1:1] += ["-n", "1"]
    elif max_commits:
        cmd[1:1] += ["-n", str(max_commits)]

    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False
        )

        output = (p.stdout or "").replace("\x00", "\uFFFD")
        commits: List[Dict] = []

        for line in output.splitlines():
            if "|" not in line:
                continue

            sha, dt = line.split("|", 1)
            sha = sha.strip()
            dt = dt.strip()

            try:
                commit_date = datetime.fromisoformat(dt).date()
            except ValueError:
                commit_date = None

            commits.append({"sha": sha, "date": commit_date})

        return commits

    except subprocess.TimeoutExpired:
        print(red("Git timeout during log."))
    except subprocess.CalledProcessError:
        print(red("Git error during log."))

    return []


def build_full_commit_index() -> Dict[str, int]:
    """
    Retorna um mapa {sha: posição_no_histórico} com base no histórico
    completo do branch atual, seguindo first parent e ordem cronológica crescente.
    """
    try:
        p = subprocess.run(
            ["git", "rev-list", "--first-parent", "--reverse", "HEAD"],
            capture_output=True,
            text=True,
            check=True
        )
        shas = [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
        return {sha: idx for idx, sha in enumerate(shas)}
    except subprocess.CalledProcessError as e:
        print(yellow(f"Falha ao montar índice completo de commits: {e}"))
        return {}


def resume_from_first_incomplete_for_dict_commits(project, labels, commits, session=None):
    """
    Reinicia a partir do primeiro commit ainda incompleto.

    Um commit é considerado completo quando count(Execution) da Version do seu SHA
    é maior ou igual a len(labels) deste run.

    Retorna:
        commits_aparados, start_idx
    Se todos completos, retorna [], None.
    """
    if not commits:
        return [], None

    total_heuristics = len(labels)
    if total_heuristics == 0:
        return [], None

    sha_list = [c["sha"] for c in commits]
    sess = session or db.db.session

    rows = (
        sess.query(db.Version.sha1, func.count(db.Execution.id))
        .join(db.Execution, db.Execution.version_id == db.Version.id)
        .filter(
            db.Version.project_id == project.id,
            db.Version.sha1.in_(sha_list)
        )
        .group_by(db.Version.sha1)
        .all()
    )

    count_by_sha = {sha: cnt for sha, cnt in rows}

    start_idx = None
    for i, sha in enumerate(sha_list):
        if count_by_sha.get(sha, 0) < total_heuristics:
            start_idx = i
            break

    if start_idx is None:
        return [], None

    return commits[start_idx:], start_idx


# =========================
# Utils de POM e arquivos externos
# =========================
def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _resolve_basedir(path_text: str, pom_dir: str) -> str:
    if not path_text:
        return path_text
    return (
        path_text
        .replace("${project.basedir}", pom_dir)
        .replace("${basedir}", pom_dir)
    )


def get_root_pom_path() -> Optional[str]:
    root_pom = os.path.abspath(os.path.join(os.getcwd(), "pom.xml"))
    return root_pom if os.path.isfile(root_pom) else None


def find_external_files_in_pom(file_path: str) -> List[str]:
    """
    Varre <configuration> e coleta caminhos de arquivo externos.
    Retorna caminhos absolutos existentes no filesystem.
    """
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    pom_dir = os.path.dirname(file_path)

    try:
        eff = os.path.join(pom_dir, "effective-pom.xml")
        tree = ET.parse(eff if os.path.isfile(eff) else file_path)
    except Exception:
        return []

    root = tree.getroot()
    found: List[str] = []

    for conf in root.findall(".//m:configuration", ns):
        for node in conf.iter():
            name = _strip_ns(node.tag).lower()
            if name in ("file", "configfile", "include"):
                if node.text and node.text.strip():
                    raw = node.text.strip()
                    resolved = _resolve_basedir(raw, pom_dir)
                    if not os.path.isabs(resolved):
                        resolved = os.path.normpath(os.path.join(pom_dir, resolved))
                    found.append(resolved)

    for n in root.findall(".//m:configuration//m:files//m:file", ns):
        if n.text and n.text.strip():
            raw = n.text.strip()
            resolved = _resolve_basedir(raw, pom_dir)
            if not os.path.isabs(resolved):
                resolved = os.path.normpath(os.path.join(pom_dir, resolved))
            found.append(resolved)

    uniq: List[str] = []
    seen = set()
    for p in found:
        if p not in seen and os.path.isfile(p):
            uniq.append(p)
            seen.add(p)

    return uniq


def list_commits_for_file(rel_path: str) -> List[Dict]:
    """
    Lista commits que alteraram rel_path, seguindo renome.
    Usa committer date (%cI), não author date.
    """
    try:
        p = subprocess.run(
            ["git", "log", "--follow", "--format=%H|%cI", "--", rel_path],
            capture_output=True,
            text=True,
            check=True
        )

        commits = []
        for ln in (p.stdout or "").splitlines():
            if "|" in ln:
                sha, dt = ln.split("|", 1)
                commits.append({"sha": sha.strip(), "date": dt.strip()})
        return commits

    except subprocess.CalledProcessError:
        return []


# =========================
# Maven dependency tree consolidado
# =========================
@dataclass
class MavenDepTreeResult:
    ok: bool
    stdout_text: str
    log_text: str
    returncode: int


def generate_all_dependencies(repo_root: str) -> MavenDepTreeResult:
    cmd = ["mvn", "dependency:tree", "-DoutputType=text"]

    try:
        p = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False
        )

        stdout = p.stdout or ""
        stderr = p.stderr or ""

        log_text = (
            "[DBMINING] mvn dependency:tree\n"
            f"[DBMINING] returncode={p.returncode}\n\n"
            "----- STDOUT -----\n"
            + stdout +
            "\n\n----- STDERR -----\n"
            + stderr
        )

        return MavenDepTreeResult(
            ok=(p.returncode == 0),
            stdout_text=stdout,
            log_text=log_text,
            returncode=p.returncode
        )

    except Exception as e:
        log_text = (
            "[DBMINING] mvn dependency:tree\n"
            "[DBMINING] exception\n\n"
            + repr(e)
        )
        return MavenDepTreeResult(
            ok=False,
            stdout_text="",
            log_text=log_text,
            returncode=999
        )


def parse_consolidated_dependency_tree_text(dep_text: str) -> List[Dict]:
    """
    Faz parse da saída textual do dependency:tree consolidado e retorna:
    [
        {
            'group', 'artifact', 'version', 'scope', 'module', 'module_pom'
        }
    ]
    """
    results: List[Dict] = []
    if not dep_text:
        return results

    current_module = ""
    current_module_pom = ""

    for ln in dep_text.splitlines():
        m_hdr = _MODULE_HEADER_RE.match(ln)
        if m_hdr:
            current_module = m_hdr.group(1).strip()
            current_module_pom = ""
            continue

        m_from = _POM_FROM_RE.match(ln)
        if m_from:
            current_module_pom = os.path.abspath(m_from.group(1).strip())
            continue

        m = _DEP_LINE_RE.match(ln)
        if not m:
            continue

        group, artifact, _type, version, scope = m.groups()
        results.append({
            "group": group.strip(),
            "artifact": artifact.strip(),
            "version": (version or "").strip(),
            "scope": (scope or "").strip(),
            "module": current_module,
            "module_pom": current_module_pom,
        })

    return results


# =========================
# Heurísticas
# =========================
def compile_patterns_by_label(labels) -> Dict[int, List[re.Pattern]]:
    compiled: Dict[int, List[re.Pattern]] = {}

    for label in labels:
        raw_lines = [
            ln.strip()
            for ln in (label.heuristic.pattern or "").splitlines()
            if ln.strip()
        ]

        patterns = []
        for ln in raw_lines:
            try:
                patterns.append(re.compile(ln))
            except re.error as e:
                print(yellow(f"Heurística inválida em '{label.name}': {e}"))

        compiled[label.id] = patterns

    return compiled


def parse_and_extract_from_consolidated(
    dep_entries: List[Dict],
    compiled_patterns: List[re.Pattern],
    scopes_accept=None
) -> List[Dict]:
    results: List[Dict] = []

    if not compiled_patterns:
        return results

    for d in dep_entries:
        ga_norm = f"{d['group']}:{d['artifact']}".lower().replace(" ", "")

        if scopes_accept is not None:
            sc = (d.get("scope") or "").lower()
            if sc and sc not in scopes_accept:
                continue

        if any(rx.search(ga_norm) for rx in compiled_patterns):
            version_text = d.get("version") or "undefined"
            module_name = (d.get("module") or "").strip() or "?module"
            origin = f" {module_name}"

            results.append({
                "file": origin,
                "group_artifact": f"{d.get('group')}:{d.get('artifact')}",
                "version": version_text,
            })

    return results


def build_maven_purl(group: str, artifact: str, version: Optional[str]) -> str:
    g = (group or "").strip()
    a = (artifact or "").strip()
    v = (version or "").strip()

    base = f"pkg:maven/{quote(g, safe='')}/{quote(a, safe='')}"
    if v and v.lower() != "undefined":
        return base + f"@{quote(v, safe='')}"
    return base


# =========================
# Banco
# =========================
def preload_existing_vulns_for_version(version_id: int) -> set:
    rows = (
        db.query(
            db.VersionVulnerability.file,
            db.VersionVulnerability.versionNumber,
            db.Execution.heuristic_id
        )
        .join(db.Execution, db.Execution.id == db.VersionVulnerability.execution_id)
        .filter(db.VersionVulnerability.version_id == version_id)
        .all()
    )
    return {(file_path, version_num, heuristic_id) for file_path, version_num, heuristic_id in rows}


def preload_executions_for_version(version_id: int) -> Dict[int, Any]:
    rows = (
        db.query(db.Execution)
        .filter(db.Execution.version_id == version_id)
        .all()
    )
    return {row.heuristic_id: row for row in rows}


def preload_last_seen_vuln_sha(project_id: int) -> Dict[Tuple[str, int], str]:
    latest = (
        db.db.session.query(
            db.VersionVulnerability.file.label("file"),
            db.Execution.heuristic_id.label("heuristic_id"),
            func.max(db.Version.id).label("max_version_id")
        )
        .join(db.Execution, db.Execution.id == db.VersionVulnerability.execution_id)
        .join(db.Version, db.Version.id == db.VersionVulnerability.version_id)
        .filter(db.Version.project_id == project_id)
        .group_by(
            db.VersionVulnerability.file,
            db.Execution.heuristic_id
        )
        .subquery()
    )

    rows = (
        db.db.session.query(
            latest.c.file,
            latest.c.heuristic_id,
            db.Version.sha1
        )
        .join(db.Version, db.Version.id == latest.c.max_version_id)
        .all()
    )

    return {(file_path, heuristic_id): sha1 for file_path, heuristic_id, sha1 in rows}


# =========================
# Checkout com diagnóstico detalhado
# =========================
@dataclass
class CheckoutResult:
    ok: bool
    requested_sha: str
    head_sha: Optional[str]
    returncode: int
    stdout: str
    stderr: str


def maybe_checkout_with_result(commit_sha: str) -> CheckoutResult:
    """
    Tenta realizar checkout do commit e retorna diagnóstico completo.
    Deve ser usada apenas em cenários de falha, para descobrir o motivo real.
    """
    try:
        p = subprocess.run(
            ["git", "checkout", "-f", commit_sha],
            capture_output=True,
            text=True,
            check=False
        )
    except Exception as e:
        return CheckoutResult(
            ok=False,
            requested_sha=commit_sha,
            head_sha=None,
            returncode=999,
            stdout="",
            stderr=repr(e),
        )

    head_sha = None
    try:
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False
        )
        if rev.returncode == 0:
            head_sha = (rev.stdout or "").strip()
    except Exception:
        head_sha = None

    return CheckoutResult(
        ok=(p.returncode == 0 and head_sha == commit_sha),
        requested_sha=commit_sha,
        head_sha=head_sha,
        returncode=p.returncode,
        stdout=p.stdout or "",
        stderr=p.stderr or "",
    )


# =========================
# Paralelismo
# =========================
def determine_max_workers(args) -> int:
    explicit = getattr(args, "parallel_workers", None)
    if explicit is None:
        env_val = os.getenv("DBMINING_MAX_WORKERS")
        if env_val:
            try:
                explicit = int(env_val)
            except ValueError:
                explicit = None

    if explicit is not None:
        return max(1, explicit)

    cpu_count = os.cpu_count() or 2
    return max(1, min(DEFAULT_PARALLEL_WORKERS, cpu_count))


def build_project_payload(project) -> Dict[str, Any]:
    return {
        "id": project.id,
        "owner": project.owner,
        "name": project.name,
    }


def merge_status(base: Dict[str, int], inc: Dict[str, int]) -> None:
    for k, v in inc.items():
        base[k] = base.get(k, 0) + v


# =========================
# Pipeline por projeto
# =========================
def process_single_project(project_payload: Dict[str, Any], args) -> Dict[str, Any]:
    db.connect()
    configure_sqlite_for_parallel()

    local_status = {
        "Success": 0,
        "Skipped": 0,
        "Repository not found": 0,
        "Git error": 0,
        "Git timeout": 0,
    }

    project_id = project_payload["id"]
    project_owner = project_payload["owner"]
    project_name = project_payload["name"]
    project_path = os.path.join(REPOS_DIR, project_owner, project_name)

    total_commit = 0
    successful_checkouts = 0

    try:
        try:
            os.chdir(project_path)
        except NotADirectoryError:
            print(red(f"{project_owner}/{project_name}: repository not found."))
            local_status["Repository not found"] += 1
            return {"project": f"{project_owner}/{project_name}", "status": local_status}

        project = db.query(db.Project).filter(db.Project.id == project_id).first()
        if not project:
            print(red(f"{project_owner}/{project_name}: projeto não encontrado no banco."))
            local_status["Git error"] += 1
            return {"project": f"{project_owner}/{project_name}", "status": local_status}

        labels = get_or_create_labels(
            heuristics_dir=args.heuristics,
            label_type=args.label_type,
            skip_remove=args.skip_remove
        )
        compiled_patterns_by_label = compile_patterns_by_label(labels)

        full_sha_index = build_full_commit_index()

        all_commits = list_pom_commits(
            latest_only=getattr(args, "latest_only", False),
            max_commits=getattr(args, "max_commits", None)
        )

        total_commit = len(all_commits)

        if total_commit == 0:
            best_effort_analysis_event(
                project_id=project.id,
                version_id=None,
                event_type="NO_POM_COMMITS_FOUND",
                status="SKIPPED",
                commit_sha=None,
                message=(
                    f"Nenhum commit com alteração em pom.xml foi retornado por list_pom_commits "
                    f"para o projeto {project.owner}/{project.name}."
                )
            )
            print(yellow(f"{project.owner}/{project.name}: nenhum commit de pom.xml encontrado."))
            return {"project": f"{project_owner}/{project_name}", "status": local_status}

        print(f"\nProcessing {total_commit} commits of {project.name} project.")

        commits, start_idx = resume_from_first_incomplete_for_dict_commits(project, labels, all_commits)
        if start_idx is None:
            print(green(f"{project.owner}/{project.name}: janela já completa, nada a fazer."))
            return {"project": f"{project_owner}/{project_name}", "status": local_status}

        previous_sha_cache: Dict[Tuple[str, int], Optional[str]] = preload_last_seen_vuln_sha(project.id)

        for offset, c in enumerate(commits, start=1):
            commit_sha = c.get("sha")
            commit_date = c.get("date")
            commit_index = start_idx + offset

            try:
                if args.may_grep_workspace or (args.checkout and args.restore):
                    current_sha1 = do_rev_parse(args.verbose)
                else:
                    current_sha1 = None

                head_sha1 = current_sha1 if args.may_grep_workspace else None
                current_commit = maybe_checkout(args, commit_sha, head_sha1)

                if current_commit != commit_sha:
                    print(yellow(
                        f"Checkout falhou no commit {commit_sha[:7]}, "
                        f"HEAD ficou em {current_commit[:7] if current_commit else 'desconhecido'}, tentando reset"
                    ))

                    subprocess.run(
                        ["git", "reset", "--hard"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    subprocess.run(
                        ["git", "clean", "-ffd"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )

                    checkout_res = maybe_checkout_with_result(commit_sha)

                    if not checkout_res.ok:
                        print(red(f"Pulando commit {commit_sha[:7]}: checkout falhou mesmo após reset"))

                        db.create(
                            db.AnalysisEvent,
                            project_id=project.id,
                            version_id=None,
                            event_type="CHECKOUT_FAILED",
                            status="ERROR",
                            commit_sha=commit_sha,
                            message=(
                                f"Falha ao realizar checkout do commit {commit_sha} "
                                f"repo={project.owner}/{project.name}\n"
                                f"mesmo após reset --hard e clean -ffd.\n\n"
                                f"requested_sha={checkout_res.requested_sha}\n"
                                f"head_sha={checkout_res.head_sha}\n"
                                f"returncode={checkout_res.returncode}\n\n"
                                f"STDOUT:\n{checkout_res.stdout}\n\n"
                                f"STDERR:\n{checkout_res.stderr}"
                            )
                        )
                        do_commit()
                        local_status["Git error"] += 1
                        continue

                successful_checkouts += 1

            except subprocess.CalledProcessError as e:
                print(red(f"Falha no checkout do commit {commit_sha[:7]}, {e}"))
                local_status["Git error"] += 1
                continue

            try:
                version, _ = prepare_version(
                    project,
                    commit_sha,
                    total_commit,
                    commit_index,
                    commit_date,
                    all_commits[-1]["sha"] if all_commits else None
                )
                db.db.session.flush()

            except Exception as e:
                safe_rollback()
                best_effort_analysis_event(
                    project_id=project.id,
                    version_id=None,
                    event_type="PREPARE_VERSION_FAILED",
                    status="ERROR",
                    commit_sha=commit_sha,
                    message=f"Falha ao preparar Version para {commit_sha[:7]}: {e}"
                )
                print(red(f"{project.name}: erro ao preparar Version para {commit_sha[:7]}"))
                local_status["Git error"] += 1
                continue

            repo_root = os.getcwd()

            if ROOT_ONLY:
                root_pom = get_root_pom_path()
                if not root_pom:
                    print(yellow(f"{project.name}: sem pom.xml na raiz; nada a processar em ROOT_ONLY."))
                    continue
            else:
                root_pom = None

            if getattr(args, "inspect_external_files", False) and root_pom:
                external_files = find_external_files_in_pom(root_pom)
                for abs_path in external_files:
                    try:
                        rel_path = os.path.relpath(abs_path, repo_root)
                    except ValueError:
                        continue

                    file_commits = list_commits_for_file(rel_path)
                    if args.verbose:
                        print(yellow(
                            f"[ext] {rel_path} mudou em {len(file_commits)} commits "
                            f"(ex.: {[c['sha'][:7] for c in file_commits[:3]]})"
                        ))

            if USE_ALL_DEPS:
                mvn_res = generate_all_dependencies(repo_root=repo_root)

                if not mvn_res.ok:
                    print(yellow(
                        f"{project.name}: falhou mvn dependency:tree no commit {commit_sha[:7]}. "
                        f"Salvando log em Execution.output"
                    ))

                    fail_output = (
                        "[DBMINING] BUILD FAILED: dependency:tree\n"
                        f"[DBMINING] project={project.owner}/{project.name}\n"
                        f"[DBMINING] sha={commit_sha}\n"
                        f"[DBMINING] returncode={mvn_res.returncode}\n\n"
                        + mvn_res.log_text
                    )

                    executions_by_heuristic = preload_executions_for_version(version.id)
                    first_label_id = labels[0].id if labels else None

                    for label in labels:
                        heuristic_id = label.heuristic.id
                        output_to_store = fail_output if label.id == first_label_id else ""

                        existing = executions_by_heuristic.get(heuristic_id)

                        if existing:
                            new_output = (output_to_store or "").strip()
                            old_output = (existing.output or "").strip()

                            if new_output and new_output != old_output:
                                existing.output = new_output

                        else:
                            execution = db.create(
                                db.Execution,
                                output=output_to_store or "",
                                version=version,
                                heuristic=label.heuristic,
                                isValidated=False,
                                isAccepted=False
                            )
                            db.db.session.flush()
                            executions_by_heuristic[heuristic_id] = execution

                    do_commit()
                    continue

                all_deps_text = mvn_res.stdout_text
                dep_entries = parse_consolidated_dependency_tree_text(all_deps_text)

                if not dep_entries:
                    print(yellow(
                        f"{project.name}: dependency:tree sem dependências reconhecidas; "
                        f"pulando commit {commit_sha[:7]}."
                    ))
                    do_commit()
                    continue

                parsed_by_label: Dict[int, List[Dict]] = {}
                for label in labels:
                    parsed_by_label[label.id] = parse_and_extract_from_consolidated(
                        dep_entries=dep_entries,
                        compiled_patterns=compiled_patterns_by_label.get(label.id, []),
                        scopes_accept=None
                    )

                executions_by_heuristic = preload_executions_for_version(version.id)
                exec_id_by_label = {}

                first_label_id = labels[0].id if labels else None

                for label in labels:
                    heuristic_id = label.heuristic.id
                    output_to_store = all_deps_text if label.id == first_label_id else ""

                    existing = executions_by_heuristic.get(heuristic_id)

                    if existing:
                        new_output = (output_to_store or "").strip()
                        old_output = (existing.output or "").strip()

                        if new_output and new_output != old_output:
                            existing.output = new_output

                        eid = existing.id
                    else:
                        execution = db.create(
                            db.Execution,
                            output=output_to_store or "",
                            version=version,
                            heuristic=label.heuristic,
                            isValidated=False,
                            isAccepted=False
                        )
                        db.db.session.flush()
                        executions_by_heuristic[heuristic_id] = execution
                        eid = execution.id

                    exec_id_by_label[label.id] = (eid, heuristic_id)

                existing_vulns = preload_existing_vulns_for_version(version.id)

                for label in labels:
                    parsed = parsed_by_label[label.id]
                    eid, heuristic_id = exec_id_by_label[label.id]

                    for result in parsed:
                        file_path = result["file"]
                        new_version = result["version"]

                        dedup_key = (file_path, new_version, heuristic_id)
                        if dedup_key in existing_vulns:
                            local_status["Skipped"] += 1
                            continue

                        ga = (result.get("group_artifact") or "")
                        group, artifact = (ga.split(":", 1) + [""])[:2]
                        purl_value = build_maven_purl(group, artifact, new_version)

                        cache_key = (file_path, heuristic_id)
                        prev_sha = previous_sha_cache.get(cache_key)

                        if prev_sha and prev_sha in full_sha_index and commit_sha in full_sha_index:
                            commits_between = max(0, full_sha_index[commit_sha] - full_sha_index[prev_sha])
                        else:
                            commits_between = 0

                        db.create(
                            db.VersionVulnerability,
                            versionNumber=new_version,
                            file=file_path,
                            version_id=version.id,
                            commitsBetween=commits_between,
                            purl=purl_value,
                            execution_id=eid
                        )

                        existing_vulns.add(dedup_key)
                        previous_sha_cache[cache_key] = commit_sha
                        local_status["Success"] += 1

                do_commit()
                print(green(f"{project.name}: commit {commit_sha[:7]} processado com sucesso."))

            else:
                print(yellow("Fluxo por POM individual removido nesta versão otimizada."))
                do_commit()

        if total_commit > 0 and successful_checkouts == 0:
            best_effort_analysis_event(
                project_id=project.id,
                version_id=None,
                event_type="ALL_COMMITS_CHECKOUT_FAILED",
                status="ERROR",
                commit_sha=None,
                message=(
                    f"Todos os {total_commit} commits retornados por list_pom_commits "
                    f"falharam no checkout."
                )
            )

        return {"project": f"{project_owner}/{project_name}", "status": local_status}

    except subprocess.TimeoutExpired:
        local_status["Git timeout"] += 1
        safe_rollback()
        return {"project": f"{project_owner}/{project_name}", "status": local_status}

    except OperationalError as e:
        print(red(f"Database error in {project_owner}/{project_name}: {e}"))
        local_status["Git error"] += 1
        safe_rollback()
        return {"project": f"{project_owner}/{project_name}", "status": local_status}

    except Exception as e:
        print(red(f"Unexpected error in {project_owner}/{project_name}: {e}"))
        local_status["Git error"] += 1
        safe_rollback()
        return {"project": f"{project_owner}/{project_name}", "status": local_status}

    finally:
        try:
            db.close()
        except Exception:
            pass


# =========================
# Pipeline principal
# =========================
def process_projects(args, connect=True):
    if connect:
        db.connect()
        configure_sqlite_for_parallel()

    status = {
        "Success": 0,
        "Skipped": 0,
        "Repository not found": 0,
        "Git error": 0,
        "Git timeout": 0,
    }

    projects = get_or_create_projects(
        create_version=True,
        filename=args.input,
        filters=args.filter,
        min_project=args.min_project,
        max_project=args.max_project,
        skip_remove=args.skip_remove
    )

    labels = get_or_create_labels(
        heuristics_dir=args.heuristics,
        label_type=args.label_type,
        skip_remove=args.skip_remove
    )

    print(f"\nProcessing {len(labels)} heuristics over {len(projects)} projects commits.")

    project_payloads = [build_project_payload(project) for project in projects]
    max_workers = determine_max_workers(args)

    if connect:
        db.close()

    if max_workers == 1 or len(project_payloads) <= 1:
        for payload in project_payloads:
            result = process_single_project(payload, args)
            merge_status(status, result["status"])
    else:
        print(yellow(f"Executando em paralelo com {max_workers} workers, paralelismo por projeto."))
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_single_project, payload, args) for payload in project_payloads]

            for future in as_completed(futures):
                result = future.result()
                merge_status(status, result["status"])

    print("\nResumo final:")
    for k, v in status.items():
        print(f"{k}: {v}")


def main():
    run_reset()
    args = read_args(
        "extract_vulnerabilities",
        "Extract vulnerabilities heuristics from repository history",
        default_label_type="vulnerabilities",
        default_skip_remove=True,
        default_heuristics=HEURISTICS_DIR_VULNERABILITIES
    )
    args.checkout = True
    process_projects(args)


if __name__ == "__main__":
    main()
