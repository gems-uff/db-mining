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

# 1 - Busca todos os commis relacionados à alterações no Pom.xml
# 2 - Busca todos os arquivos de pom.xml presentes no projeto para a versão modificada.
# 3 - Busca todos os BDs que vamos usar na coleta.
# 4 - Para cada arquivo de pom buscar todos os BDs da listagem do item 3. Extraindo a versão de cada um deles. 


GREP_COMMAND_LOG_COMMAND_POM = [ #revisado
    'git',
    'log',
    '-p',
    '--reverse',
    '--',
    '**/pom.xml'
]

def generate_effective_pom(file_path):
    """
    Executa 'mvn help:effective-pom' no diretório do pom.xml
    e retorna o caminho do effective-pom.xml gerado.
    """
    pom_dir = os.path.dirname(file_path)
    output_file = os.path.join(pom_dir, 'effective-pom.xml')
    try:
        subprocess.run( ["/opt/homebrew/bin/mvn", "help:effective-pom", "-Doutput=effective-pom.xml"],
                       cwd=pom_dir,
                       check=True,
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL
                       )

        return output_file
    except subprocess.CalledProcessError as e:
        print(yellow(f"Não foi possível gerar effective-pom com Maven para {file_path}, usando fallback."))
        return None

def list_pom_commits():#revisado 
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

def find_all_pom_files(project): #revisado
    """ Retorna todos os arquivos pom.xml presentes na estrutura do projeto no estado 
    atual do repositório (após o checkout já realizado externamente). """
    project_path = os.path.join(REPOS_DIR, project.owner, project.name)
    try:
        # Garante que estamos no diretório correto do repositório
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

def count_commits_between(start_sha, end_sha): #revisado
    """
    Conta quantos commits existem entre start_sha (exclusivo) e end_sha (inclusivo).
    """
    try:
        cmd = ["git", "rev-list", "--count", f"{start_sha}..{end_sha}"]
        p = subprocess.run(cmd, capture_output=True, check=True)
        count = int(p.stdout.decode().strip())
        return count
    except Exception as e:
        print(yellow(f"Erro ao contar commits entre {start_sha} e {end_sha}: {e}"))
        return 0

def clean_effective_pom(raw_content):
    idx = raw_content.find("<project")
    return raw_content[idx:] if idx != -1 else raw_content

def parse_and_extract(tree, properties, label, file_origin, ns):
    root = tree.getroot()
    results = []

    pattern_lines = [line.strip() for line in label.heuristic.pattern.strip().splitlines() if line.strip()]
    try:
        regex = re.compile(r'(' + '|'.join(pattern_lines) + r')', re.IGNORECASE)
    except re.error as regex_err:
        print(yellow(f"Regex inválido na heurística '{label.name}': {regex_err}"))
        return []

    for dep in root.findall(".//m:dependency", ns):
        group_id = dep.find("m:groupId", ns)
        artifact_id = dep.find("m:artifactId", ns)
        version = dep.find("m:version", ns)

        if group_id is not None and artifact_id is not None:
            ga = f"{group_id.text}:{artifact_id.text}"
            if regex.search(ga):
                if version is not None and version.text:
                    version_text = version.text.strip()
                    if version_text.startswith('${') and version_text.endswith('}'):
                        var_name = version_text[2:-1]
                        version_text = properties.get(var_name, version_text)
                else:
                    version_text = 'undefined'

                results.append({
                    'file': file_origin,
                    'group_artifact': ga,
                    'version': version_text
                })
    return results
    
def extract_all_versions_from_pom(file_path, labels):
    """
    Extrai versões de bancos de dados do pom.xml para todas as labels de uma vez.
    """
    ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
    results_per_label = {label.id: [] for label in labels}

    def apply_labels(tree, properties, file_origin):
        for label in labels:
            parsed = parse_and_extract(tree, properties, label, file_origin, ns)
            results_per_label[label.id].extend(parsed)

    try:
        effective_pom_path = generate_effective_pom(file_path)
        if effective_pom_path and os.path.isfile(effective_pom_path):
            with open(effective_pom_path, 'r', encoding='utf-8') as f:
                raw_xml = f.read()
                cleaned_xml = clean_effective_pom(raw_xml)
                tree = ET.parse(StringIO(cleaned_xml))
                apply_labels(tree, {}, file_path + " (effective)") #todo
                return results_per_label
            print(yellow(f"Nenhum resultado no effective POM, fallback para POM original."))
    except Exception as e:
        print(yellow(f"Erro com effective POM para {file_path}: {e}"))

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        properties = {}
        props = root.find('m:properties', ns)
        if props is not None:
            for prop in props:
                tag = prop.tag.split('}')[-1]
                properties[tag] = prop.text.strip() if prop.text else ''

        parent = root.find('m:parent', ns)
        if parent is not None:
            parent_pom = os.path.abspath(os.path.join(os.path.dirname(file_path), '..', 'pom.xml'))
            if os.path.isfile(parent_pom):
                parent_tree = ET.parse(parent_pom)
                parent_root = parent_tree.getroot()
                parent_props = parent_root.find('m:properties', ns)
                if parent_props is not None:
                    for prop in parent_props:
                        tag = prop.tag.split('}')[-1]
                        if tag not in properties:
                            properties[tag] = prop.text.strip() if prop.text else ''

        apply_labels(tree, properties, file_path)
        return results_per_label
    except Exception as e:
        print(yellow(f"Erro ao processar POM original {file_path}: {e}"))
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

    labels = get_or_create_labels( #cria as labels já com groupId e artifactId 
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
               .order_by(db.Execution.id.desc())   # usa id como proxy de "mais recente"
               .first())

def get_last_vuln_for_project(project):
    q = (db.query(db.VersionVulnerability)
           .join(db.Version, db.Version.id == db.VersionVulnerability.version_id)
           .filter(db.Version.project_id == project.id)
           .order_by(desc(db.Version.id), desc(db.VersionVulnerability.id))  # mais recente por commit; desempata pelo próprio VV
           .first())
    return q  

def vuln_exists(version_id, file_path, heuristic_id, version_num):
    # Existe VV para (version_id, file, versionNumber) e MESMA heurística?
    # Checa via join em Execution (pelo execution_id)
    q = (db.query(db.VersionVulnerability.id)
           .join(db.Execution, db.Execution.id == db.VersionVulnerability.execution_id)
           .filter(db.VersionVulnerability.version_id == version_id)
           .filter(db.VersionVulnerability.file == file_path)
           .filter(db.VersionVulnerability.versionNumber == version_num)
           .filter(db.Execution.heuristic_id == heuristic_id))
    return db.db.session.query(q.exists()).scalar()

def get_or_create_execution(project, label, version, commit_sha, args):
    # já existe?
    existing = (db.query(db.Execution.id)
                  .filter_by(version_id=version.id, heuristic_id=label.heuristic.id)
                  .first())
    if existing:
        return existing[0]

    # cria (roda o grep uma vez por label/commit)
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
    # última VV anterior a current_version_id para (file, heuristic)
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
    """
    ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
    pom_dir = os.path.dirname(file_path)

    # Use o effective-pom se já existir; caso contrário, o POM original
    try:
        eff = os.path.join(pom_dir, 'effective-pom.xml')
        tree = ET.parse(eff if os.path.isfile(eff) else file_path)
    except Exception:
        return []

    root = tree.getroot()
    found = []

    # Procura qualquer <configuration>... e, dentro dele, tags típicas de caminho
    for conf in root.findall('.//m:configuration', ns):
        for node in conf.iter():
            name = _strip_ns(node.tag).lower()
            if name in ('file', 'configfile', 'include'):  # cobre <file>, <configFile>, <includes><include>
                if node.text and node.text.strip():
                    raw = node.text.strip()
                    resolved = _resolve_basedir(raw, pom_dir)
                    if not os.path.isabs(resolved):
                        resolved = os.path.normpath(os.path.join(pom_dir, resolved))
                    found.append(resolved)

    # Também cobre <files><file> explicitamente (alguns parsers não pegam com o iter acima)
    for n in root.findall('.//m:configuration//m:files//m:file', ns):
        if n.text and n.text.strip():
            raw = n.text.strip()
            resolved = _resolve_basedir(raw, pom_dir)
            if not os.path.isabs(resolved):
                resolved = os.path.normpath(os.path.join(pom_dir, resolved))
            found.append(resolved)

    # dedup e só os que existem no checkout atual
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

    labels = get_or_create_labels( #cria as labels já com groupId e artifactId 
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
            last_execution = get_last_execution_for_version(last_verson.id)

            # 2) se já processou o último commit por completo, pode pular
            if last_execution and last_execution == commits[-1]['sha']:
                # Verifica se todas as heurísticas já têm Execution nesse version_id
                have = set(h_id for (h_id,) in db.query(db.Execution.heuristic_id)
                                          .filter_by(version_id=last_verson.id).all())
                all_ids = set(lbl.heuristic.id for lbl in labels)
                if all_ids.issubset(have):
                    print(green(f"{project.name}: already complete up to latest commit ({last_execution[:7]}). Skipping."))
                    continue
                # caso contrário, vamos reabrir esse commit para completar

            # 3) decide onde começar:
            #    - sem last_execution => do início;
            #    - com last_execution => reprocessa o PRÓPRIO commit salvo para fechar lacunas.
            if last_execution:
                try:
                    start_idx = next(i for i, c in enumerate(commits) if c['sha'] == last_execution)
                    print(yellow(f"{project.name}: resuming at saved commit {last_execution[:7]} (to fill gaps)."))
                except StopIteration:
                    print(yellow(f"{project.name}: saved SHA {last_execution[:7]} not found. Reprocessing from start."))
                    start_idx = 0
            else:
                start_idx = 0

            print(f"\nProcessing {total_commit - start_idx} pom.xml commits of {project.name} project.")
            
            for commit_index in range(start_idx, total_commit):
                commit = commits[commit_index]
                commit_sha = commit['sha']
                commit_date = commit.get('date')

                # checkout no commit alvo
                head_sha1 = maybe_checkout(args, commit_sha, None) #muda de commit

                # upsert da Version
                version, is_new = prepare_version(
                    project, commit_sha, total_commit,
                    commit_index + 1,
                    commit_date, commits[-1]['sha'] if commits else None)
                
                # lista POMs do repositório nesse commit
                poms = find_all_pom_files(project) #aqui retorna todos os arquivos para o commit específico
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

                        # aqui você decide o que fazer: logar, usar na métrica, ou persistir
                        #TODO
                        if args.verbose:
                            print(yellow(f"[ext] {rel_path} mudou em {len(file_commits)} commits "
                                         f"(ex.: {[c['sha'][:7] for c in file_commits[:3]]})"))
                    
                    # roda extração de versões de TODOS os DBs para esse arquivo
                    results_dict = extract_all_versions_from_pom(pom, labels)
                    for label in labels:
                        eid, heuristic_id = exec_id_by_label[label.id]
                        for result in results_dict[label.id]:
                            file_path = result['file']
                            new_version = result['version']

                            # já existe VV para (version, file, heurística, versionNumber)?
                            if vuln_exists(version.id, file_path, heuristic_id, new_version):
                                status['Skipped'] += 1
                                continue

                            # calcula commitsBetween com base na última VV anterior (para MESMO file+heurística)
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
                                #else:
                                #    status['Iguais'] += 1
        except subprocess.TimeoutExpired:
            continue
        except Exception as e:
            print(red(f'Unexpected error: {e}'))
            status['Git error'] += 1
    if connect:
        db.close()

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


#last_vulnerability = get_last_vuln_for_project(project)

            #não tem commit -> iniciar o processo todo. Buscar os commits, e para todos os commits, buscar todos os arquivos para o commit, e para cada aruqivo buscar todas as heurísticas
            #tem commit e não tem execução -> retomar a execução. Buscar os commits, e para os commits faltantes, buscar todos os arquivos para o commit, e para cada aruqivo buscar todas as heurísticas
            #tem commit e tem execução -> retomar a execução. Buscar os commits, e para os commits faltantes, buscar os arquivos faltantes para o commit, e para cada aruqivo buscar as heurísticas faltantes.
        
