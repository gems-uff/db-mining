import os
import subprocess

import pandas as pd

import database as db
from util import ANNOTATED_FILE, HEURISTICS_DIR, REPOS_DIR, red, green, yellow, CODE_DEBUG

# Git grep command
GREP_COMMAND = [
    'git',
    'grep',
    '-I',
    '--context=5',
    '--break',
    '--heading',
    '--line-number',
    '--color=always',
    '--extended-regexp',
    '-f'
]

# Git rev-parse command
REVPARSE_COMMAND = [
    'git',
    'rev-parse',
    '--verify',
    'HEAD'
]


def load_heuristics(directory):
    heuristics = list()
    for label_type in os.scandir(directory):
        if label_type.is_dir():
            for label in os.scandir(label_type.path):
                if label.is_file() and not label.name.startswith('.'):
                    with open(label.path) as file:
                        pattern = file.read()
                    heuristic = {
                        'id': None,
                        'name': os.path.splitext(label.name)[0],
                        'type': label_type.name,
                        'pattern': pattern,
                        'pattern_file': label.path
                    }
                    heuristics.append(heuristic)
    heuristics.sort(key=lambda item: item['name'])
    return heuristics


def main():
    print(f'Loading repositories from {ANNOTATED_FILE}.')
    info_repositories = pd.read_excel(ANNOTATED_FILE, keep_default_na=False)
    info_repositories = info_repositories[info_repositories.discardReason == ''].reset_index(drop=True)

    print(f'Loading heuristics from {HEURISTICS_DIR}.')
    info_heuristics = load_heuristics(HEURISTICS_DIR)

    db.connect()

    status = {
        'Success': 0,
        'Skipped': 0,
        'Repository not found': 0,
        'Git error': 0,
        'Total': len(info_heuristics) * len(info_repositories)
    }

    print(f'Processing {len(info_heuristics)} heuristics over {len(info_repositories)} repositories.')
    i = 0
    for info_heuristic in info_heuristics:

        # Retrieve or create the Label and Heuristic objects
        label = db.get_or_create(db.Label, name=info_heuristic['name'], type=info_heuristic['type'])
        heuristic = label.heuristic
        new_pattern = False
        if heuristic:
            if heuristic.pattern != info_heuristic['pattern']:
                new_pattern = True
                heuristic.pattern = info_heuristic['pattern']
        else:
            heuristic = db.create(db.Heuristic, pattern=info_heuristic['pattern'], label=label)

        # Applies the heuristic over each repository
        for j, info_repository in info_repositories.iterrows():
            try:
                # Retrieve or create the Project object
                repo_dict = info_repository.to_dict()
                repo_dict = {k: v for k, v in repo_dict.items() if k not in ['url', 'isSoftware', 'discardReason']}
                repo_dict['createdAt'] = str(repo_dict['createdAt'])
                repo_dict['pushedAt'] = str(repo_dict['pushedAt'])
                project = db.get_or_create(db.Project, **repo_dict)

                # Print progress information
                progress = '{:.2%}'.format((i * len(info_repositories) + j) / status['Total'])
                print(f'[{progress}] Searching for {label.name} in {project.owner}/{project.name}:', end=' ')

                # Enter in the repository workspace
                os.chdir(REPOS_DIR + os.sep + project.owner + os.sep + project.name)

                # Retrieve or create the Version object
                version = db.query(db.Version, isLast=True, project=project).first()
                if not version:
                    p = subprocess.run(REVPARSE_COMMAND, capture_output=True)
                    if p.stderr:
                        raise subprocess.CalledProcessError(p.returncode, REVPARSE_COMMAND, p.stdout, p.stderr)
                    version = db.create(db.Version, sha1=p.stdout, isLast=True, project=project)

                # Executes the heuristic over the project if was not executed before or if the pattern has changes
                # and the execution was not validated ans accepted
                execution = db.query(db.Execution, version=version, heuristic=heuristic).first()
                if new_pattern and execution and not (execution.isValidated and execution.isAccepted):
                    db.delete(execution)
                if not execution:
                    cmd = GREP_COMMAND + [info_heuristic['pattern_file']]
                    p = subprocess.run(cmd, capture_output=True)
                    if p.stderr:
                        raise subprocess.CalledProcessError(p.returncode, cmd, p.stdout, p.stderr)
                    db.create(db.Execution, output=p.stdout.decode(errors='replace').replace('\x00', '\uFFFD'), version=version, heuristic=heuristic, isValidated=False, isAccepted=False)

                    print(green('ok.'))
                    status['Success'] += 1
                    db.commit()
                else:  # Execution already exists
                    print(yellow('already done.'))
                    status['Skipped'] += 1
            except NotADirectoryError:
                print(red('repository not found.'))
                status['Repository not found'] += 1
            except subprocess.CalledProcessError as ex:
                print(red('Git error.'))
                status['Git error'] += 1
                if CODE_DEBUG:
                    print(ex.stderr)
        i += 1

    print('Deleting missing heuristics...', end=' ')
    dir_labels = {(info_heuristic['name'], info_heuristic['type']) for info_heuristic in info_heuristics}
    bd_labels = db.query(db.Label).all()
    for label in bd_labels:
        if (label.name, label.type) not in dir_labels:
            print(f'{red(label.name)} ({label.type})', end=' ')
            db.delete(label)
    db.commit()

    db.close()

    print('\n*** Processing results ***')
    for k, v in status.items():
        print(f'{k}: {v}')

    print("\nFinished.")


if __name__ == "__main__":
    main()
