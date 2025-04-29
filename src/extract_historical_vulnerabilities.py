import os
import subprocess
from datetime import datetime
from sqlalchemy.sql.expression import null
import re

import database as db
from extract import (
    get_or_create_projects, index_executions, do_commit, print_results,
    get_or_create_labels,
    GREP_COMMAND, CHECKOUT_COMMAND, read_args, find_heuristic,
    maybe_checkout, prepare_commits, prepare_version
)
from util import REPOS_DIR, red, green, yellow, HEURISTICS_DIR_VULNERABILITIES

GREP_COMMAND_LOG_COMMAND = [
    'git',
    'log',
    '-p',
    '--reverse',
    '--',
    '**/pom.xml'
]

def list_pom_commits():
    """Retorna a lista de commits que alteraram algum pom.xml (ordem cronológica)."""
    cmd = GREP_COMMAND_LOG_COMMAND
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

def remove_duplicates(lista_vulnerabilidades):
    """
    Remove entradas duplicadas com base em ('file', 'versionNumber').

    :param lista_vulnerabilidades: lista de dicionários com dados de vulnerabilidade
    :return: lista com entradas únicas
    """
    unique_entries = set()
    cleaned_data = []

    for entry in lista_vulnerabilidades:
        key = (entry['file'], entry['versionNumber'])
        if key not in unique_entries:
            unique_entries.add(key)
            cleaned_data.append(entry)

    print(f"Total original: {len(lista_vulnerabilidades)}")
    print(f"Total limpo: {len(cleaned_data)}")
    return cleaned_data

def extract_version(linha):
    """Extrai a versão a partir de uma linha com a tag <version>."""
    pom_version = linha.strip().replace('<version>', '').replace('</version>', '')
    match = re.search(r'\b\d+(?:\.\d+){1,3}\b', pom_version)
    return match.group() if match else None

def parse_heuristic_output(output, version, project, execution):
    blocos = re.split(r'(?=\b[0-9a-f]{40}:[^\n]+)', output) # Regex para dividir pelos hashes de commit
    blocos = [bloco.strip() for bloco in blocos if bloco.strip()]
    resultados = []

    for bloco in blocos:
        pom_version = None
        primeira_linha = True
        #o output é uma lista de retornos, preciso quebrar cada retorno e depois extrair as listas
        for line in bloco.splitlines():
            if ":" in line and primeira_linha:
                _, caminho_arquivo = line.split(":", 1) # usa 1 para evitar problemas se houver ":" no caminho
                primeira_linha = False
            if re.search(r'<\s*version\s*>', line):
                pom_version = extract_version(line)
                break

        resultados.append({
            'versionNumber': pom_version,
            'file': caminho_arquivo,
            'version_id': version.id,
            'project_id': project.id,
            'execution_id': execution.id
        })

    return resultados

def save_vulnerabilities(results_list):
    status = {
        'Saved': 0,
        'Errors': 0
    }
    errors = []

    for item in results_list:
        try:
            db.create(
                db.VersionVulnerability,
                versionNumber=item['versionNumber'],
                file=item['file'],
                version_id=item['version_id'],
                execution_id=item['execution_id']
            )
            status['Saved'] += 1
        except Exception as e:
            status['Errors'] += 1
            errors.append({
                'item': item,
                'error': str(e)
            })

    try:
        db.commit()
    except Exception as e:
        print(red(f"\n Commit failed: {e}"))
        return

    print(f"\n Vulnerabilities saved: {status['Saved']}")
    print(f"⚠️ Save errors: {status['Errors']}")

    if errors:
        print("🔍 Failed items:")
        for err in errors:
            print(f" - {err['item']} → {err['error']}")


def process_projects(args):
    vulnerability_results = []
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

    executions = index_executions(labels)
    print(f"\nProcessing {len(labels)} heuristics over {len(projects)} projects commits.")
    for project in projects:
        try:
            os.chdir(REPOS_DIR + os.sep + project.owner + os.sep + project.name)
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
                head_sha1 = maybe_checkout(args, commit_sha, None)
                version, is_new = prepare_version(
                    project, commit_sha, total_commit,
                    commit_index + 1,
                    commit_date, commits[-1]['sha'] if commits else None)

                for label in labels:
                    heuristic = label.heuristic
                    execution = executions.get((heuristic, version), None)
                    if execution:
                        print(yellow('already done.'))
                        status['Skipped'] += 1
                        continue

                    try:
                        output = find_heuristic(
                            project, label, args.heuristics,
                            commit=commit_sha,
                            label_type=args.label_type,
                            verbose=args.verbose)
                        
                        #cria a execution no banco
                        execution = db.create(db.Execution, output=output,
                            version=version, heuristic=heuristic,
                            isValidated=False, isAccepted=False)

                        status['Success'] += 1
                        print(green('ok.'))
                        do_commit()         
                    except subprocess.TimeoutExpired:
                        print(red('Git timeout.'))
                        status['Git timeout'] += 1
                    except subprocess.CalledProcessError:
                        print(red('Git error.'))
                        status['Git error'] += 1
                        
                    if output: #entra aqui se tem resultado
                            vulnerability_results += parse_heuristic_output(output, version, project, execution)
        except Exception as e:
            print(red(f'Unexpected error: {e}'))
            status['Git error'] += 1
        
        cleaned_results = remove_duplicates(vulnerability_results)
        save_vulnerabilities(cleaned_results)
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
