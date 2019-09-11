import os
import subprocess

import pandas as pd

import database
from util import ANNOTATED_FILE, HEURISTICS_DIR, REPOS_DIR, red, green, DEBUG, yellow

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
    '--perl-regexp',
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
                if label.is_file():
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
    return heuristics


def main():
    print(f'Loading repositories from {ANNOTATED_FILE}.')
    info_repositories = pd.read_excel(ANNOTATED_FILE, keep_default_na=False)
    info_repositories = info_repositories[info_repositories.discardReason == ''].reset_index(drop=True)

    print(f'Loading heuristics from {HEURISTICS_DIR}.')
    info_heuristics = load_heuristics(HEURISTICS_DIR)

    database.connect()

    print(f'Processing {len(info_heuristics)} heuristics over {len(info_repositories)} repositories.')
    i = 0
    for heuristic_info in info_heuristics:

        # Retrieve or create the Label and Heuristic objects
        label = database.get_or_create(database.Label, name=heuristic_info['name'], type=heuristic_info['type'])
        heuristic = label.heuristic
        if heuristic and heuristic.pattern != heuristic_info['pattern']:
            database.delete(heuristic)
            heuristic = None
        if not heuristic:
            heuristic = database.create(database.Heuristic, pattern=heuristic_info['pattern'], label=label)

        # Applies the heuristic over each repository
        for j, info_repository in info_repositories.iterrows():
            # Retrieve or create the Repository object
            repo_dict = info_repository.to_dict()
            repo_dict = {k: v for k, v in repo_dict.items() if k not in ['url', 'isSoftware', 'discardReason']}
            repo_dict['createdAt'] = str(repo_dict['createdAt'])
            repo_dict['pushedAt'] = str(repo_dict['pushedAt'])
            project = database.get_or_create(database.Project, **repo_dict)

            # Print progress information
            progress = '{:.2%}'.format(
                (i * len(info_repositories) + j) / (len(info_heuristics) * len(info_repositories)))
            print(f'[{progress}] Searching for {label.name} in {project.owner}/{project.name}:', end=' ')

            # Enter in the repository workspace and run Git commands
            repo_dir = REPOS_DIR + os.sep + project.owner + os.sep + project.name
            if os.path.isdir(repo_dir):
                os.chdir(repo_dir)

                # Retrieve or create the Version object
                process = subprocess.run(REVPARSE_COMMAND, text=True, capture_output=True)
                if not process.stderr:
                    version = database.get_or_create(database.Version, sha1=process.stdout, isLast=True,
                                                     project=project)

                    # Avoids executing the heuristic when it has been executed before
                    execution = database.get(database.Execution, version=version, heuristic=heuristic)
                    if not execution:
                        # Executes the heuristic over the project
                        process = subprocess.run(GREP_COMMAND + [heuristic_info['pattern_file']], text=True,
                                                 capture_output=True)
                        if not process.stderr:
                            database.create(database.Execution, output=process.stdout, version=version, heuristic=heuristic, isValidated=False, isAccepted=False)
                            print(green('ok.'))
                        else:  # Git grep failed
                            print(red('error.'))
                            if DEBUG:
                                print(process.stderr)
                    else:  # Execution already exists
                        print(yellow('already done.'))
                else:  # Git rev-parse failed
                    print(red('version not found.'))
                    if DEBUG:
                        print(process.stderr)
            else:  # Repo dir does not exist
                print(red('repository not found.'))

            database.commit()

        i += 1

    print('Deleting missing heuristics...')
    # TODO: remove from the DB the heuristics that were removed from the directory.

    database.commit()
    database.close()
    print("\nFinished.")


if __name__ == "__main__":
    main()
