import os
import subprocess
from datetime import datetime
from sqlalchemy.sql.expression import null
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


def find_all_pom_files(project):
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


def extract_db_versions_from_pom(file_path, label):
    """
    Extrai versões de bancos de dados do pom.xml, resolvendo variáveis do tipo ${...}.
    """
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
        results = []

        # 1. Carrega propriedades definidas no <properties>
        properties = {}
        properties_node = root.find('m:properties', ns)
        if properties_node is not None:
            for prop in properties_node:
                tag = prop.tag.split('}')[-1]  # remove namespace
                properties[tag] = prop.text.strip() if prop.text else ''

        # 2. Regex de correspondência com groupId:artifactId
        raw_pattern = label.heuristic.pattern.strip()
        pattern_lines = [line.strip() for line in raw_pattern.splitlines() if line.strip()]
        combined_pattern = r'(' + '|'.join(pattern_lines) + r')'
        try:
            regex = re.compile(combined_pattern, re.IGNORECASE)
        except re.error as regex_err:
            print(yellow(f"Regex inválido na heurística '{label.name}': {regex_err}"))
            return []

        # 3. Itera sobre as dependências
        for dep in root.findall(".//m:dependency", ns):
            group_id = dep.find("m:groupId", ns)
            artifact_id = dep.find("m:artifactId", ns)
            version = dep.find("m:version", ns)

            if group_id is not None and artifact_id is not None:
                ga = f"{group_id.text}:{artifact_id.text}"
                if regex.search(ga):
                    version_text = version.text.strip() if version is not None and version.text else 'undefined'

                    # 4. Resolve variáveis como ${...}
                    if version_text.startswith('${') and version_text.endswith('}'):
                        var_name = version_text[2:-1]  # remove ${ e }
                        version_text = properties.get(var_name, version_text)  # substitui ou mantém original

                    results.append({
                        'file': file_path,
                        'group_artifact': ga,
                        'version': version_text
                    })
        return results
    except Exception as e:
        print(yellow(f"Erro ao processar {file_path}: {e}"))
        return []


#parei aqui, preciso avaliar o resto do código. 
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
            total_commit = len(commits)
            print(f"\nProcessing {total_commit} pom.xml commits of {project.name} project.")
            for commit_index, commit in enumerate(commits):
                commit_sha = commit['sha']
                commit_date = commit.get('date')
                head_sha1 = maybe_checkout(args, commit_sha, None) #muda de commit
                version, is_new = prepare_version(
                    project, commit_sha, total_commit,
                    commit_index + 1,
                    commit_date, commits[-1]['sha'] if commits else None)

                poms = find_all_pom_files(project) #aqui retorna todos os arquivos para o commit específico
                if poms:
                    for pom in poms:
                        for label in labels: #buscar no pom a label e retornar a version, validando se a versão salva é a mesma da anterior.
                            heuristic = label.heuristic
                            #results = null
                            results = extract_db_versions_from_pom(pom, label)
                            for result in results:
                                key = (result['file'], label.id)
                                new_version = result['version']

                                if key not in last_versions or last_versions[key] != new_version:
                                    try:
                                        output = find_heuristic(
                                            project, label, args.heuristics,
                                            commit=commit_sha,
                                            label_type=args.label_type,
                                            verbose=args.verbose)

                                        execution = db.create(db.Execution, output=output,
                                            version=version, heuristic=label.heuristic,
                                            isValidated=False, isAccepted=False)
                                        do_commit()

                                        version_vulnerability = db.create(db.VersionVulnerability,
                                            versionNumber=new_version,
                                            file=result['file'],
                                            version_id=version.id,
                                            execution_id=execution.id)

                                        last_versions[key] = new_version  # atualiza o cache
                                        status['Success'] += 1
                                        print(green('ok.'))
                                        do_commit()
                                    except subprocess.TimeoutExpired:
                                        print(red('Git timeout.'))
                                        status['Git timeout'] += 1
                                    except subprocess.CalledProcessError:
                                        print(red('Git error.'))
                                        status['Git error'] += 1
                                else:
                                    status['Iguais'] += 1
                                    #print(yellow(f"Versão '{new_version}' já registrada anteriormente para {result['file']} — ignorado."))
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
