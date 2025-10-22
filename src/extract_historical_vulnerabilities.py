import os
import subprocess
from datetime import datetime
from sqlalchemy.sql.expression import null
from sqlalchemy import desc
import re
import xml.etree.ElementTree as ET
from io import StringIO
import database as db
from extract import (get_or_create_projects, index_executions, do_commit,
    get_or_create_labels, read_args, find_heuristic,
    maybe_checkout, prepare_version
)
from util import REPOS_DIR, red, green, yellow, HEURISTICS_DIR_VULNERABILITIES
from typing import Optional

# Rodar somente na raiz do repo e não em cada módulo?
ROOT_ONLY = True


# 1 - Busca todos os commits relacionados a alterações no pom.xml
# 2 - Busca todos os arquivos de pom.xml presentes no projeto para a versão modificada.
# 3 - Busca todos os BDs que vamos usar na coleta.
# 4 - Para cada arquivo de pom buscar todos os BDs da listagem do item 3, extraindo a versão de cada um.

GREP_COMMAND_LOG_COMMAND_POM = [  # revisado
    'git',
    'log',
    '-p',
    '--reverse',
    '--',
    '**/pom.xml'
]

def generate_dependency_tree(file_path: str, non_recursive: bool = False):
    """
    Executa 'mvn dependency:tree' no diretório do pom.xml e grava em dep-tree.txt.
    Se non_recursive=True, adiciona '-N' para não entrar nos módulos.
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

        cmd = [
            "mvn",
            "dependency:tree",
            "-DoutputFile=dep-tree.txt",
            "-DoutputType=text"
        ]
        if non_recursive:
            cmd.insert(1, "-N")  # mvn -N -q dependency:tree ...

        subprocess.run(
            cmd,
            cwd=pom_dir,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print(f"Dependency:tree {pom_dir}.")
        return output_file if os.path.isfile(output_file) else None
    except subprocess.CalledProcessError:
        print(yellow(f"Não foi possível gerar dependency:tree para {file_path}."))
        return None

def list_pom_commits():  # revisado
    """Retorna a lista de commits que alteraram algum pom.xml (ordem cronológica)."""
    cmd = GREP_COMMAND_LOG_COMMAND_POM
    try:
        p = subprocess.run(cmd, capture_output=True)
        output = p.stdout.decode(errors='replace').replace('\x00', '\uFFFD')
        commits = []
        current_commit = None

        for line in output.splitlines():
            if line.startswith('commit '):
                if current_commit:
                    commits.append(current_commit)
                current_commit = {'sha': line.split()[1]}
            elif line.startswith('Date:') and current_commit is not None:
                date_str = line.replace('Date:', '').strip()
                # Formatos de data do git podem variar; cobrimos o padrão default
                try:
                    commit_date = datetime.strptime(date_str, '%a %b %d %H:%M:%S %Y %z').date()
                    current_commit['date'] = commit_date
                except ValueError:
                    current_commit['date'] = None
        if current_commit:
            commits.append(current_commit)
        return commits
    except subprocess.TimeoutExpired:
        print(red('Git timeout during log.'))
    except subprocess.CalledProcessError:
        print(red('Git error during log.'))
    return []

def find_all_pom_files(project):  # revisado
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

def count_commits_between(start_sha, end_sha):  # revisado
    """Conta quantos commits existem entre start_sha (exclusivo) e end_sha (inclusivo)."""
    try:
        cmd = ["git", "rev-list", "--count", f"{start_sha}..{end_sha}"]
        p = subprocess.run(cmd, capture_output=True, check=True)
        count = int(p.stdout.decode().strip())
        return count
    except Exception as e:
        print(yellow(f"Erro ao contar commits entre {start_sha} e {end_sha}: {e}"))
        return 0

def clean_effective_pom(raw_content):
    # Mantido apenas caso ainda queira usar em algum fallback futuro
    idx = raw_content.find("<project")
    return raw_content[idx:] if idx != -1 else raw_content

# -----------------------------
# Parsing do dependency:tree
# -----------------------------
_DEP_LINE_RE = re.compile(r'^\s*(?:\[INFO\]\s*)?(?:[\|\+\-\\ ]*)\s*([^\s:]+):([^\s:]+):([^\s:]+):([^\s:]+)(?::([^\s:]+))?')

def parse_dependency_tree_file(dep_tree_path: str):
    """
    Lê o dep-tree.txt e retorna lista de dicts:
    [{'group':..., 'artifact':..., 'version':..., 'scope':...}, ...]
    Aceita linhas no formato típico:
      [INFO] +- group:artifact:type:version[:scope]
    Ignora linhas que não sigam o padrão.
    """
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
                # Algumas linhas de árvore incluem o próprio projeto como raiz; manter ou não é opcional.
                results.append({
                    'group': group.strip(),
                    'artifact': artifact.strip(),
                    'version': version.strip(),
                    'scope': (scope or '').strip()
                })
    except Exception as e:
        print(yellow(f"Falha ao parsear dependency:tree: {e}"))
    return results

def parse_and_extract_from_tree(dep_entries, label):
    """
    Aplica a heurística (label) sobre a lista de dependências resolvidas do dependency:tree
    Retorna lista de dicts {file, group_artifact, version}.
    """
    results = []
    # cada label.heuristic.pattern pode ter múltiplas linhas (groupId:artifactId)
    pattern_lines = [line.strip() for line in label.heuristic.pattern.strip().splitlines() if line.strip()]
    try:
        regex = re.compile(r'(' + '|'.join(pattern_lines) + r')', re.IGNORECASE)
    except re.error as regex_err:
        print(yellow(f"Regex inválido na heurística '{label.name}': {regex_err}"))
        return results

    for d in dep_entries:
        ga = f"{d['group']}:{d['artifact']}"
        if regex.search(ga):
            version_text = d['version'] if d['version'] else 'undefined'
            results.append({
                'file': '(dependency:tree)',  # origem lógica; podemos anexar o caminho do POM chamador ao montar
                'group_artifact': ga,
                'version': version_text
            })
    return results

def extract_all_versions_from_pom(file_path, labels):
    """
    Extrai versões de bancos de dados a partir do dependency:tree do módulo do POM informado.
    Retorna dict {label.id: [ {file, group_artifact, version}, ... ] }
    """

    results_per_label = {label.id: [] for label in labels}
    try:
        repo_root = os.getcwd()
        is_root_pom = os.path.abspath(file_path) == os.path.join(repo_root, 'pom.xml')

        tree_path = generate_dependency_tree(file_path, non_recursive=is_root_pom and ROOT_ONLY)
        if not tree_path:
            print(yellow(f"Sem dependency:tree para {file_path}."))
            return results_per_label

        dep_entries = parse_dependency_tree_file(tree_path)
        if not dep_entries:
            print(yellow(f"Nenhuma dependência resolvida em {file_path}."))
            return results_per_label

        for label in labels:
            parsed = parse_and_extract_from_tree(dep_entries, label)
            # Anexa o caminho do pom que gerou a árvore para melhor rastreabilidade
            for item in parsed:
                item['file'] = f"{file_path} (dependency:tree)"
            results_per_label[label.id].extend(parsed)

        return results_per_label
    except Exception as e:
        print(yellow(f"Erro ao processar dependency:tree de {file_path}: {e}"))
        return results_per_label

def count_numbers(args, connect=True):
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

    labels = get_or_create_labels(  # cria as labels já com groupId e artifactId
        heuristics_dir=args.heuristics,
        label_type=args.label_type,
        skip_remove=args.skip_remove
    )

    print(f"\nProcessing {len(labels)} heuristics over {len(projects)} projects commits.")

    for project in projects:
        try:
            os.chdir(REPOS_DIR + os.sep + project.owner + os.sep + project.name)
            last_versions = {}
        except NotADirectoryError:
            print(red('Repository not found.'))
            status['Repository not found'] += 1
            continue

        try:
            commits = list_pom_commits()
            total_commit = len(commits)
            poms = find_all_pom_files(project)
            total_pom = len(poms)
            print(f"\nProcessing {total_commit} projects commits over {total_pom} pom.xml")
        except Exception as e:
            print(red(f'Unexpected error: {e}'))
            status['Git error'] += 1

def get_last_verson_project(project):
    return (db.query(db.Version)
               .filter_by(project_id=project.id)
               .order_by(db.Version.id.desc())
               .first())

def get_last_execution_for_version(version_id):
    return (db.query(db.Execution)
               .filter_by(version_id=version_id)
               .order_by(db.Execution.id.desc())
               .first())

def get_last_vuln_for_project(project):
    q = (db.query(db.VersionVulnerability)
           .join(db.Version, db.Version.id == db.VersionVulnerability.version_id)
           .filter(db.Version.project_id == project.id)
           .order_by(desc(db.Version.id), desc(db.VersionVulnerability.id))
           .first())
    return q

def vuln_exists(version_id, file_path, heuristic_id, version_num):
    q = (db.query(db.VersionVulnerability.id)
           .join(db.Execution, db.Execution.id == db.VersionVulnerability.execution_id)
           .filter(db.VersionVulnerability.version_id == version_id)
           .filter(db.VersionVulnerability.file == file_path)
           .filter(db.VersionVulnerability.versionNumber == version_num)
           .filter(db.Execution.heuristic_id == heuristic_id))
    return db.db.session.query(q.exists()).scalar()

def get_or_create_execution(project, label, version, commit_sha, args):
    existing = (db.query(db.Execution.id)
                  .filter_by(version_id=version.id, heuristic_id=label.heuristic.id)
                  .first())
    if existing:
        return existing[0]

    output = find_heuristic(
        project, label, args.heuristics,
        commit=commit_sha,
        label_type=args.label_type,
        verbose=args.verbose
    )
    execution = db.create(db.Execution,
                          output=output,
                          version=version,
                          heuristic=label.heuristic,
                          isValidated=False,
                          isAccepted=False)
    do_commit()
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
    Observação: aqui mantivemos o parse do POM (ou effective, se existir localmente)
    apenas para a análise auxiliar de arquivos externos referenciados.
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
    """
    Lista commits que alteraram 'rel_path' (relativo à raiz do repo), seguindo renomes.
    Retorna [{'sha':..., 'date':...}, ...]
    """
    try:
        p = subprocess.run(
            ['git', 'log', '--follow', '--format=%H|%ad', '--date=iso-strict', '--', rel_path],
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

    labels = get_or_create_labels(  # cria as labels já com groupId e artifactId
        heuristics_dir=args.heuristics,
        label_type=args.label_type,
        skip_remove=args.skip_remove
    )

    print(f"\nProcessing {len(labels)} heuristics over {len(projects)} projects commits.")
    
    for project in projects:
        try:
            os.chdir(REPOS_DIR + os.sep + project.owner + os.sep + project.name)
            last_versions = {}
        except NotADirectoryError:
            print(red('Repository not found.'))
            status['Repository not found'] += 1
            continue

        try:
            commits = list_pom_commits()
            if not commits:
                print(yellow(f"{project.name}: no commits touching pom.xml."))
                continue

            total_commit = len(commits)

            # 1) pega a última Version persistida (linha inteira)
            last_verson = get_last_verson_project(project)
            last_execution = get_last_execution_for_version(last_verson.id) if last_verson else None

            # 2) Heurística simplificada para decidir retomar (mantida)
            #    OBS: comparar 'last_execution' com SHA exige campo correspondente; mantido como no original.
            if last_execution and hasattr(last_execution, "sha") and last_execution.sha == commits[-1]['sha']:
                have = set(h_id for (h_id,) in db.query(db.Execution.heuristic_id)
                                          .filter_by(version_id=last_verson.id).all())
                all_ids = set(lbl.heuristic.id for lbl in labels)
                if all_ids.issubset(have):
                    print(green(f"{project.name}: already complete up to latest commit ({last_execution.sha[:7]}). Skipping."))
                    continue

            if last_execution and hasattr(last_execution, "sha"):
                try:
                    start_idx = next(i for i, c in enumerate(commits) if c['sha'] == last_execution.sha)
                    print(yellow(f"{project.name}: resuming at saved commit {last_execution.sha[:7]} (to fill gaps)."))
                except StopIteration:
                    print(yellow(f"{project.name}: saved SHA {last_execution.sha[:7]} not found. Reprocessing from start."))
                    start_idx = 0
            else:
                start_idx = 0

            print(f"\nProcessing {total_commit - start_idx} pom.xml commits of {project.name} project.")

            for commit_index in range(start_idx, total_commit):
                commit = commits[commit_index]
                commit_sha = commit['sha']
                commit_date = commit.get('date')

                head_sha1 = maybe_checkout(args, commit_sha, None)

                version, is_new = prepare_version(
                    project, commit_sha, total_commit,
                    commit_index + 1,
                    commit_date, commits[-1]['sha'] if commits else None)

                # repo_root para funções auxiliares
                repo_root = os.getcwd()

                if ROOT_ONLY:
                    root_pom = get_root_pom_path()
                    if not root_pom:
                        print(yellow(f"{project.name}: sem pom.xml na raiz; nada a processar em ROOT_ONLY."))
                        continue
                    poms = [root_pom]
                else:
                    poms = find_all_pom_files(project)

                if not poms:
                    continue


                exec_id_by_label = {}
                for label in labels:
                    eid = get_or_create_execution(project, label, version, commit_sha, args)
                    exec_id_by_label[label.id] = (eid, label.heuristic.id)

                for pom in poms:
                    # 1) detectar arquivos externos referenciados
                    external_files = find_external_files_in_pom(pom)

                    # 2) para cada arquivo, listar commits que o tocaram
                    for abs_path in external_files:
                        try:
                            rel_path = os.path.relpath(abs_path, repo_root)
                        except ValueError:
                            continue  # se estiver fora do repo, ignora

                        file_commits = list_commits_for_file(repo_root, rel_path)
                        if args.verbose:
                            print(yellow(f"[ext] {rel_path} mudou em {len(file_commits)} commits "
                                         f"(ex.: {[c['sha'][:7] for c in file_commits[:3]]})"))

                    # 3) roda extração de versões de TODOS os DBs para esse POM via dependency:tree
                    results_dict = extract_all_versions_from_pom(pom, labels)
                    for label in labels:
                        eid, heuristic_id = exec_id_by_label[label.id]
                        for result in results_dict[label.id]:
                            file_path = result['file']
                            new_version = result['version']

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
                                print(red('Git timeout.'))
                                status['Git timeout'] += 1
                            except subprocess.CalledProcessError:
                                print(red('Git error.'))
                                status['Git error'] += 1
        except subprocess.TimeoutExpired:
            continue
        except Exception as e:
            print(red(f'Unexpected error: {e}'))
            status['Git error'] += 1

    if connect:
        db.close()

def get_root_pom_path() -> Optional[str]:

    """
    Retorna o caminho absoluto para o pom.xml da raiz do repositório atual (cwd),
    ou None se não existir.
    """
    root_pom = os.path.abspath(os.path.join(os.getcwd(), 'pom.xml'))
    return root_pom if os.path.isfile(root_pom) else None


def main():
    args = read_args(
        'extract_vulnerabilities',
        'Extract vulnerabilities heuristics from repository history',
        default_label_type="vulnerabilities",
        default_skip_remove=True,
        default_heuristics=HEURISTICS_DIR_VULNERABILITIES
    )
    process_projects(args)

if __name__ == "__main__":
    main()

# Observações finais:
# - Caso queira incluir scopes adicionais (runtime/test), ajuste -DincludeScope.
# - Se seu Maven for muito antigo e não suportar outputType, remova -DoutputType=text.
# - Para forçar um binário específico: export MAVEN_BIN=/caminho/para/mvn
