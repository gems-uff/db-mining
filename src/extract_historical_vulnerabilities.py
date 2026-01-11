import os
import sys
import subprocess
from datetime import datetime, date
from sqlalchemy.sql.expression import null
from sqlalchemy import desc
import re
import xml.etree.ElementTree as ET
from io import StringIO
import database as db
from extract import (
    get_or_create_projects, do_commit, maybe_checkout, do_rev_parse,
    get_or_create_labels, read_args, find_heuristic, prepare_version
)
from util import REPOS_DIR, red, green, yellow, HEURISTICS_DIR_VULNERABILITIES
from typing import Optional, List, Dict
from sqlalchemy import func

# Configurações
GREP_COMMAND_LOG_COMMAND_POM = [ "git", "log", "--first-parent",  "--reverse", "--format=%H|%cI", "--", "pom.xml", "**/pom.xml" ]
ROOT_ONLY = True          # processar apenas o pom da raiz para tarefas auxiliares (arquivos externos etc.)
USE_ALL_DEPS = True       # usar o consolidado all-dependencies.txt para extrair versões de DBs
_MODULE_HEADER_RE = re.compile(r'^\s*\[INFO\]\s+--- .* @ ([^ ]+) ---')
_DEP_LINE_RE = re.compile(r'^\s*(?:\[INFO\]\s*)?(?:[\|\+\-\\ ]*)\s*([^\s:]+):([^\s:]+):([^\s:]+):([^\s:]+)(?::([^\s:]+))?')
_POM_FROM_RE = re.compile(r'^\s*\[INFO\]\s+from\s+(.+?/pom\.xml)\s*$')


# ---------------------------------
# Faz reset de todos os projetos
# ---------------------------------
def run_reset():
    subprocess.run(
        [sys.executable, "src/reset.py"],
        check=True
    )

def filter_commits_from_2024(commits: List[Dict]) -> List[Dict]:
    cutoff = date(2024, 1, 1)
    return [
        c for c in commits
        if c.get('date') and c['date'] >= cutoff
    ]

# ---------------------------------
# Geração e listagem de commits POM
# ---------------------------------
def list_pom_commits(latest_only: bool = False, max_commits: Optional[int] = None,) -> List[Dict]:

    """ Retorna commits que alteraram algum pom.xml. Usa committer date (%cI). """
    cmd = list(GREP_COMMAND_LOG_COMMAND_POM)

    #validação de parâmetros
    if latest_only:
        cmd[1:1] += ['-n', '1']
    elif max_commits:
        cmd[1:1] += ['-n', str(max_commits)]

    try:
        p = subprocess.run(cmd, capture_output=True, check=False)
        output = p.stdout.decode(errors='replace').replace('\x00', '\uFFFD')

        commits = []
        for line in output.splitlines():
            if '|' not in line:
                continue
            sha, dt = line.split('|', 1)
            sha = sha.strip()
            dt = dt.strip()

            commit_date = None
            try:
                # dt vem como 2010-06-18T12:34:56-03:00
                commit_date = datetime.fromisoformat(dt).date()
            except ValueError:
                commit_date = None

            commits.append({'sha': sha, 'date': commit_date})

        #commits_2024 = filter_commits_from_2024(commits)
        # assume “ordem cronológica crescente”
        return commits

    except subprocess.TimeoutExpired:
        print(red('Git timeout during log.'))
    except subprocess.CalledProcessError:
        print(red('Git error during log.'))
    return []



def find_all_pom_files(project):
    """Retorna todos os arquivos pom.xml presentes no projeto no estado atual (após checkout)."""
    project_path = os.path.join(REPOS_DIR, project.owner, project.name)
    try:
        os.chdir(project_path)
        pom_files = []
        for root, dirs, files in os.walk('.'):
            if 'pom.xml' in files:
                full_path = os.path.abspath(os.path.join(root, 'pom.xml'))
                pom_files.append(full_path)
        return pom_files
    except Exception as e:
        print(f"Erro ao buscar arquivos pom.xml no diretório '{project_path}': {e}")
        return []

def resume_from_first_incomplete_for_dict_commits(project, labels, commits, session=None):
    """
    Corta a lista para reiniciar no primeiro commit ainda incompleto.
    Um commit está completo quando count(Execution) da Version do seu SHA
    é maior ou igual a len(labels) deste run.
    Retorna: commits_aparados, start_idx  .  Se todos completos, retorna [], None.
    """
    if not commits:
        return [], None

    total_heuristics = len(labels)
    if total_heuristics == 0:
        return [], None

    sha_list = [c['sha'] for c in commits]

    sess = session or db.db.session
    rows = (
        sess.query(db.Version.sha1, func.count(db.Execution.id))
            .join(db.Execution, db.Execution.version_id == db.Version.id)
            .filter(db.Version.project_id == project.id,
                    db.Version.sha1.in_(sha_list))
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

def count_commits_between(start_sha, end_sha):
    """Conta quantos commits existem entre start_sha (exclusivo) e end_sha (inclusivo)."""
    try:
        cmd = ["git", "rev-list", "--count", f"{start_sha}..{end_sha}"]
        p = subprocess.run(cmd, capture_output=True, check=True)
        count = int(p.stdout.decode().strip())
        return count
    except Exception as e:
        print(yellow(f"Erro ao contar commits entre {start_sha} e {end_sha}: {e}"))
        return 0

# -----------------------------
# Utils de POM (arquivos externos)
# -----------------------------
def _strip_ns(tag: str) -> str:
    return tag.split('}', 1)[-1] if '}' in tag else tag

def _resolve_basedir(path_text: str, pom_dir: str) -> str:
    if not path_text:
        return path_text
    return (path_text
            .replace('${project.basedir}', pom_dir)
            .replace('${basedir}', pom_dir))

def find_external_files_in_pom(file_path: str) -> list[str]:
    """
    Varre <configuration> e coleta caminhos de arquivo externos.
    Retorna caminhos ABSOLUTOS existentes no filesystem (estado do commit).
    """
    ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
    pom_dir = os.path.dirname(file_path)
    try:
        eff = os.path.join(pom_dir, 'effective-pom.xml')
        tree = ET.parse(eff if os.path.isfile(eff) else file_path)
    except Exception:
        return []

    root = tree.getroot()
    found = []

    for conf in root.findall('.//m:configuration', ns):
        for node in conf.iter():
            name = _strip_ns(node.tag).lower()
            if name in ('file', 'configfile', 'include'):
                if node.text and node.text.strip():
                    raw = node.text.strip()
                    resolved = _resolve_basedir(raw, pom_dir)
                    if not os.path.isabs(resolved):
                        resolved = os.path.normpath(os.path.join(pom_dir, resolved))
                    found.append(resolved)

    for n in root.findall('.//m:configuration//m:files//m:file', ns):
        if n.text and n.text.strip():
            raw = n.text.strip()
            resolved = _resolve_basedir(raw, pom_dir)
            if not os.path.isabs(resolved):
                resolved = os.path.normpath(os.path.join(pom_dir, resolved))
            found.append(resolved)

    uniq = []
    seen = set()
    for p in found:
        if p not in seen and os.path.isfile(p):
            uniq.append(p)
            seen.add(p)
    return uniq

def list_commits_for_file(repo_root: str, rel_path: str) -> list[dict]:
    """ Lista commits que alteraram 'rel_path', seguindo renomes. Usa committer date (%cI), não author date.
    Retorna [{'sha':..., 'date':...}, ...] """
    try:
        p = subprocess.run(
            ['git', 'log', '--follow', '--format=%H|%cI', '--', rel_path],
            capture_output=True, check=True
        )
        commits = []
        for ln in p.stdout.decode(errors='replace').splitlines():
            if '|' in ln:
                sha, dt = ln.split('|', 1)
                commits.append({'sha': sha.strip(), 'date': dt.strip()})
        return commits
    except subprocess.CalledProcessError:
        return []

# -----------------------------------------------
# Geração do consolidado e parsers de dependências
# -----------------------------------------------
def generate_all_dependencies(repo_root: str) -> Optional[str]:
    """
    Executa 'mvn dependency:tree -DoutputType=text' na raiz do repositório
    e salva a saída completa em 'all-dependencies.txt'.
    Retorna o caminho do arquivo ou None se falhar.
    """
    out_path = os.path.join(repo_root, "all-dependencies.txt")
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            subprocess.run(
                ["mvn", "dependency:tree", "-DoutputType=text"],
                cwd=repo_root,
                check=True,
                stdout=fh,
                stderr=subprocess.DEVNULL
            )
        print(f"Dependency:tree (consolidado) gerado.")
        return out_path if os.path.isfile(out_path) else None
    except subprocess.CalledProcessError:
        print(yellow("Não foi possível gerar all-dependencies.txt na raiz."))
        return None

def parse_consolidated_dependency_tree(all_dep_path: str):
    """
    Lê o all-dependencies.txt e retorna uma lista de dicts:
    [{'group', 'artifact', 'version', 'scope', 'module', 'module_pom'}]
    """
    results = []
    if not all_dep_path or not os.path.isfile(all_dep_path):
        return results

    current_module = ''
    current_module_pom = ''
    try:
        with open(all_dep_path, 'r', encoding='utf-8', errors='replace') as f:
            for ln in f:
                m_hdr = _MODULE_HEADER_RE.match(ln)
                if m_hdr:
                    current_module = m_hdr.group(1).strip()
                    current_module_pom = ''  # reseta; virá numa linha "from .../pom.xml" logo abaixo (quando houver)
                    continue

                m_from = _POM_FROM_RE.match(ln)
                if m_from:
                    # caminho do pom.xml daquele módulo
                    current_module_pom = os.path.abspath(m_from.group(1).strip())
                    continue

                m = _DEP_LINE_RE.match(ln)
                if not m:
                    continue

                group, artifact, _type, version, scope = m.groups()
                results.append({
                    'group': group.strip(),
                    'artifact': artifact.strip(),
                    'version': (version or '').strip(),
                    'scope': (scope or '').strip(),
                    'module': current_module,
                    'module_pom': current_module_pom
                })
    except Exception as e:
        print(yellow(f"Falha ao parsear all-dependencies.txt: {e}"))
    return results

# Parser “por POM” (mantido como fallback opcional)
def generate_dependency_tree(file_path: str, non_recursive: bool = False):
    """
    Executa 'mvn dependency:tree' no diretório do pom.xml e grava em dep-tree.txt.
    Retorna o caminho do arquivo gerado ou None em caso de falha.
    """
    pom_dir = os.path.dirname(file_path)
    output_file = os.path.join(pom_dir, 'dep-tree.txt')
    try:
        if os.path.isfile(output_file):
            try:
                os.remove(output_file)
            except OSError:
                pass

        cmd = ["mvn", "dependency:tree", "-DoutputFile=dep-tree.txt", "-DoutputType=text"]
        if non_recursive:
            cmd.insert(1, "-N")  # mvn -N dependency:tree

        with open(os.devnull, "w") as devnull:
            subprocess.run(cmd, cwd=pom_dir, check=True, stdout=devnull, stderr=devnull)

        print(f"Dependency:tree gerado em: {output_file}.")
        return output_file if os.path.isfile(output_file) else None
    except subprocess.CalledProcessError:
        print(yellow(f"Não foi possível gerar dependency:tree para {file_path}."))
        return None

def parse_dependency_tree_file(dep_tree_path: str):
    """Parser de dep-tree.txt por POM."""
    results = []
    if not dep_tree_path or not os.path.isfile(dep_tree_path):
        return results

    try:
        with open(dep_tree_path, 'r', encoding='utf-8', errors='replace') as f:
            for ln in f:
                m = _DEP_LINE_RE.match(ln)
                if not m:
                    continue
                group, artifact, _type, version, scope = m.groups()
                results.append({
                    'group': group.strip(),
                    'artifact': artifact.strip(),
                    'version': (version or '').strip(),
                    'scope': (scope or '').strip()
                })
    except Exception as e:
        print(yellow(f"Falha ao parsear dependency:tree: {e}"))
    return results

# -----------------------------
# Aplicação das heurísticas
# -----------------------------
def parse_and_extract_from_consolidated(dep_entries, label, scopes_accept=None, source_path: Optional[str]=None):
    results = []

    # 1) lê linhas da heurística
    raw_lines = [ln.strip() for ln in (label.heuristic.pattern or "").splitlines() if ln.strip()]

    # 2) compila padrões
    patterns = []
    for ln in raw_lines:
        ln = re.sub(r"\s+", "", ln)  # remove espaços

        # se a linha parece regex (ex.: começa com (?i) ou tem ^ / $), compile como está
        looks_like_regex = ln.startswith("(?") or ln.startswith("^") or ln.endswith("$")

        if looks_like_regex:
            patterns.append(re.compile(ln))
        else:
            # caso contrário, trata como literal group:artifact e casa exato
            # re.IGNORECASE porque você normaliza ga_norm em lower, então tanto faz, mas ajuda se mudar depois
            patterns.append(re.compile(rf"^{re.escape(ln.lower())}$", re.IGNORECASE))

    if not patterns:
        return results

    # 3) percorre dependências
    for d in dep_entries:
        ga_norm = f"{d['group']}:{d['artifact']}".lower().replace(" ", "")

        if scopes_accept is not None:
            sc = (d.get('scope') or "").lower()
            if sc and sc not in scopes_accept:
                continue

        # 4) aplica regex
        if any(rx.search(ga_norm) for rx in patterns):
            version_text = d.get('version') or 'undefined'

            origin_parts = []
            if source_path:
                origin_parts.append(os.path.abspath(source_path))
            origin_parts.append((d.get('module') or '').strip() or '?module')

            origin = (f" {origin_parts[-1]}" if origin_parts else "")

            results.append({
                'file': origin,
                'group_artifact': f"{d.get('group')}:{d.get('artifact')}",
                'version': version_text
            })

    return results

def parse_and_extract_from_tree(dep_entries, label):
    """
    (Fallback) Aplica a heurística na lista de dependências de um único POM (dep-tree.txt).
    """
    results = []
    pattern_lines = [line.strip() for line in label.heuristic.pattern.strip().splitlines() if line.strip()]
    try:
        regex = re.compile(r'(' + '|'.join(map(re.escape, pattern_lines)) + r')', re.IGNORECASE)
    except re.error as regex_err:
        print(yellow(f"Regex inválido na heurística '{label.name}': {regex_err}"))
        return results

    for d in dep_entries:
        ga = f"{d['group']}:{d['artifact']}"
        if regex.search(ga):
            version_text = d['version'] if d['version'] else 'undefined'
            results.append({
                'file': '(dependency:tree)',
                'group_artifact': ga,
                'version': version_text
            })
    return results

# ---------------------------------
# DB helpers (inalterados do seu projeto)
# ---------------------------------

def vuln_exists(version_id, file_path, heuristic_id, version_num):
    q = (db.query(db.VersionVulnerability.id)
           .join(db.Execution, db.Execution.id == db.VersionVulnerability.execution_id)
           .filter(db.VersionVulnerability.version_id == version_id)
           .filter(db.VersionVulnerability.file == file_path)
           .filter(db.VersionVulnerability.versionNumber == version_num)
           .filter(db.Execution.heuristic_id == heuristic_id))
    return db.db.session.query(q.exists()).scalar()

def get_or_create_execution(project, label, version, commit_sha, all_deps_text, args):
    existing = (db.query(db.Execution.id)
                  .filter_by(version_id=version.id, heuristic_id=label.heuristic.id)
                  .first())
    if existing:
        return existing[0]

    execution = db.create(db.Execution,
                          output=all_deps_text,
                          version=version,
                          heuristic=label.heuristic,
                          isValidated=False,
                          isAccepted=False)
    do_commit()
    print("Execution criada.")
    return execution.id

def get_previous_vuln_sha(project_id, file_path, heuristic_id, current_version_id):
    row = (db.query(db.Version.sha1)
             .join(db.VersionVulnerability, db.Version.id == db.VersionVulnerability.version_id)
             .join(db.Execution, db.Execution.id == db.VersionVulnerability.execution_id)
             .filter(db.Version.project_id == project_id)
             .filter(db.Execution.heuristic_id == heuristic_id)
             .filter(db.VersionVulnerability.file == file_path)
             .filter(db.Version.id < current_version_id)
             .order_by(db.Version.id.desc())
             .first())
    return row[0] if row else None

def commit_exists(sha: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return False
    p = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True)
    return p.returncode == 0

def read_text_file(path: str, max_chars: int = 2_000_000) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    if max_chars and len(txt) > max_chars:
        txt = txt[:max_chars] + "\n\n[TRUNCATED]"
    return txt

# ---------------------------------
# Pipeline principal
# ---------------------------------
def get_root_pom_path() -> Optional[str]:
    """Retorna o caminho absoluto para o pom.xml da raiz do repositório atual (cwd), ou None."""
    root_pom = os.path.abspath(os.path.join(os.getcwd(), 'pom.xml'))
    return root_pom if os.path.isfile(root_pom) else None


def process_projects(args, connect=True):
    if connect:
        db.connect()
    status = {
        'Success': 0,
        'Skipped': 0,
        'Iguais': 0,
        'Repository not found': 0,
        'Git error': 0,
        'Git timeout': 0,
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
    
    for project in projects:
        name = project.name
        try:
            os.chdir(REPOS_DIR + os.sep + project.owner + os.sep + project.name)
        except NotADirectoryError:
            print(red('Repository not found.'))
            status['Repository not found'] += 1
            continue

        try:
            
            # Janela de commits com a sua função atual
            commits = list_pom_commits(
                latest_only=getattr(args, 'latest_only', False),
                max_commits=getattr(args, 'max_commits', None)
            )
            total_commit = len(commits)
            print(f"\nProcessing {total_commit} commits of {project.name} project.")

            # Retomada: começar no primeiro commit ainda incompleto
            commits, _start_idx = resume_from_first_incomplete_for_dict_commits(project, labels, commits)
            if _start_idx is None or total_commit == 0:
                print(green(f"{project.owner}/{project.name}: janela já completa, nada a fazer."))
                continue

            for i, c in enumerate(commits, start=1):
                if isinstance(c, dict):
                    commit_sha = c.get('sha')
                    commit_date = c.get('date')
                    commit_index = i
                elif isinstance(c, (list, tuple)):
                    commit_sha, commit_date = c[0], (c[1] if len(c) > 1 else None)
                else:
                    commit_sha, commit_date = c, None
                    
                # checkout do commit, agora sempre
                try:
                    #current_commit = do_checkout(commit_sha, getattr(args, "verbose", False))
                    if args.may_grep_workspace or (args.checkout and args.restore):
                        current_sha1 = do_rev_parse(args.verbose)
                    head_sha1 = current_sha1 if args.may_grep_workspace else None

                    if not commit_exists(commit_sha):
                        print(f"Pulando commit inválido ou inexistente: {commit_sha!r}")
                        status['Git error'] += 1
                        continue
                    
                    current_commit = maybe_checkout(args, commit_sha, head_sha1)
                    
                    if current_commit != commit_sha:
                        print(yellow(f"Checkout falhou no commit {commit_sha[:7]}, " f"HEAD ficou em {current_commit[:7] if current_commit else 'desconhecido'}, tentando reset"))

                        # limpeza forçada
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

                        # 2ª tentativa de checkout
                        current_commit = maybe_checkout(args, commit_sha, head_sha1)

                        if current_commit != commit_sha:
                            print(red(f"Pulando commit {commit_sha[:7]}: " f"checkout falhou mesmo após reset"))
                            status['Git error'] += 1
                            continue
                        
                except subprocess.CalledProcessError as e:
                    print(red(f"Falha no checkout do commit {commit_sha[:7]}, {e}"))
                    status['Git error'] += 1
                    continue

                try:
                    version, is_new = prepare_version(
                    project, commit_sha, total_commit,
                    commit_index,
                    commit_date, commits[-1]['sha'] if commits else None
                )
                    do_commit() 
                    print("Version criada.")
                except Exception as e:
                    print(red(f"{name}: erro ao preparar Version para {commit_sha[:7]}"))
                    status['Git error'] += 1
                    continue

                repo_root = os.getcwd()

                # Manter análise de arquivos externos referenciados em POM
                if ROOT_ONLY:
                    root_pom = get_root_pom_path()
                    if not root_pom:
                        print(yellow(f"{name}: sem pom.xml na raiz; nada a processar em ROOT_ONLY."))
                        continue
                    
                # Apenas logs/auxiliar (não impacta a coleta de DBs do consolidado)
                #for pom in root_pom:
                external_files = find_external_files_in_pom(root_pom)
                for abs_path in external_files:
                    try:
                        rel_path = os.path.relpath(abs_path, repo_root)
                    except ValueError:
                        continue
                    file_commits = list_commits_for_file(repo_root, rel_path)
                    if args.verbose:
                        print(yellow(f"[ext] {rel_path} mudou em {len(file_commits)} commits "
                                    f"(ex.: {[c['sha'][:7] for c in file_commits[:3]]})"))

                # ====== MODO PRINCIPAL: CONSOLIDADO ======
                if USE_ALL_DEPS:
                    all_deps = generate_all_dependencies(repo_root=repo_root)
                    if not all_deps:
                        print(yellow(f"{name}: não foi possível gerar all-dependencies.txt; pulando commit {commit_sha[:7]}."))
                        output = "Não foi possível gerar all-dependencies.txt; pulando commit: " + commit_sha[:7]
                        get_or_create_execution(project, labels[0], version, commit_sha, output, args)
                        continue

                    dep_entries = parse_consolidated_dependency_tree(all_deps)
                    all_deps_text = read_text_file(all_deps)
                    if not dep_entries:
                        print(yellow(f"{name}: all-dependencies.txt sem dependências reconhecidas; pulando commit {commit_sha[:7]}."))
                        continue

                    # cria/recupera executions por label (uma vez por commit)
                    exec_id_by_label = {}
                    for label in labels:
                        eid = get_or_create_execution(project, label, version, commit_sha, all_deps_text, args)
                        exec_id_by_label[label.id] = (eid, label.heuristic.id)

                    # aplica heurísticas e persiste
                    for label in labels:
                        parsed = parse_and_extract_from_consolidated(dep_entries, label, source_path=all_deps)
                        for result in parsed:
                            file_path = result['file']
                            new_version = result['version']
                            eid, heuristic_id = exec_id_by_label[label.id]

                            if vuln_exists(version.id, file_path, heuristic_id, new_version):
                                status['Skipped'] += 1
                                continue

                            prev_sha = get_previous_vuln_sha(project.id, file_path, heuristic_id, version.id)
                            if prev_sha:
                                try:
                                    commits_between = count_commits_between(prev_sha, commit_sha)
                                except Exception:
                                    commits_between = 0
                            else:
                                commits_between = 0

                            try:
                                db.create(db.VersionVulnerability,
                                          versionNumber=new_version,
                                          file=file_path,
                                          version_id=version.id,
                                          commitsBetween=commits_between,
                                          execution_id=eid)
                                do_commit()
                                status['Success'] += 1
                                print(green('ok.'))
                            except subprocess.TimeoutExpired:
                                print(red('Git timeout.')); status['Git timeout'] += 1
                            except subprocess.CalledProcessError:
                                print(red('Git error.')); status['Git error'] += 1

                # ====== (Opcional) Fallback por POM ======
                else:
                    # Se quiser manter o fluxo “por POM” em vez do consolidado
                    exec_id_by_label = {}
                    for label in labels:
                        eid = get_or_create_execution(project, label, version, commit_sha, args)
                        exec_id_by_label[label.id] = (eid, label.heuristic.id)

                    poms = find_all_pom_files()
                    for pom in poms:
                        tree_path = generate_dependency_tree(pom, non_recursive=False)
                        if not tree_path:
                            print(yellow(f"Sem dependency:tree para {pom}."))
                            continue

                        dep_entries = parse_dependency_tree_file(tree_path)
                        if not dep_entries:
                            print(yellow(f"Nenhuma dependência resolvida em {pom}."))
                            continue

                        for label in labels:
                            parsed = parse_and_extract_from_tree(dep_entries, label)
                            # Anexa o caminho do pom que gerou a árvore para melhor rastreabilidade
                            for item in parsed:
                                file_path = f"{pom} (dependency:tree)"
                                new_version = item['version']
                                eid, heuristic_id = exec_id_by_label[label.id]

                                if vuln_exists(version.id, file_path, heuristic_id, new_version):
                                    status['Skipped'] += 1
                                    continue

                                prev_sha = get_previous_vuln_sha(project.id, file_path, heuristic_id, version.id)
                                if prev_sha:
                                    try:
                                        commits_between = count_commits_between(prev_sha, commit_sha)
                                    except Exception:
                                        commits_between = 0
                                else:
                                    commits_between = 0

                                try:
                                    db.create(db.VersionVulnerability,
                                              versionNumber=new_version,
                                              file=file_path,
                                              version_id=version.id,
                                              commitsBetween=commits_between,
                                              execution_id=eid)
                                    do_commit()
                                    status['Success'] += 1
                                    print(green('ok.'))
                                except subprocess.TimeoutExpired:
                                    print(red('Git timeout.')); status['Git timeout'] += 1
                                except subprocess.CalledProcessError:
                                    print(red('Git error.')); status['Git error'] += 1

        except subprocess.TimeoutExpired:
            continue
        except Exception as e:
            print(red(f'Unexpected error: {e}'))
            status['Git error'] += 1
            try:
                db.db.session.rollback()
            except Exception:
                pass

    if connect:
        db.close()

def main():
    run_reset() #faço o reset de todos os projetos para garantir que estou buscando os commits no branch mais atual e que não perdi nada nos checkouts.
    args = read_args(
        'extract_vulnerabilities',
        'Extract vulnerabilities heuristics from repository history',
        default_label_type="vulnerabilities",
        default_skip_remove=True,
        default_heuristics=HEURISTICS_DIR_VULNERABILITIES
    )
    args.checkout = True
    process_projects(args)

if __name__ == "__main__":
    main()
