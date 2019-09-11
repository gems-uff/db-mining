import os
import subprocess

import pandas as pd

import database
from util import ANNOTATED_FILE, HEURISTICS_DIR, REPOS_DIR, red, green

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
    repos_df = pd.read_excel(ANNOTATED_FILE, keep_default_na=False)
    repos_df = repos_df[repos_df.discardReason == ''].reset_index(drop=True)

    print(f'Loading heuristics from {HEURISTICS_DIR}.')
    heuristic_infos = load_heuristics(HEURISTICS_DIR)

    database.connect()

    print(f'Processing {len(heuristic_infos)} heuristics over {len(repos_df)} repositories.')
    i = 0
    for heuristic_info in heuristic_infos:
        label = database.get_or_create(database.Label, name=heuristic_info['name'], type=heuristic_info['type'])
        heuristic = label.heuristic
        if heuristic and heuristic.pattern != heuristic_info['pattern']:
            database.delete(heuristic)
            heuristic = None
        if not heuristic:
            heuristic = database.create(database.Heuristic, pattern=heuristic_info['pattern'], label=label)

        for j, repo in repos_df.iterrows():
            progress = '{:.2%}'.format((i * len(repos_df) + j) / (len(heuristic_infos) * len(repos_df)))
            print(f'[{progress}] Searching for {label.name} in {repo["owner"]}/{repo["name"]}:', end=' ')

            # TODO: check if the heuristic has already been executed over the project.

            repo = REPOS_DIR + os.sep + repo['owner'] + os.sep + repo['name']
            if os.path.isdir(repo):
                os.chdir(repo)
                process = subprocess.run(GREP_COMMAND + [heuristic_info['pattern_file']], text=True,
                                         capture_output=True)

                if process.stderr:
                    print(red('error.'))
                    print(process.stderr)
                    exit(1)
                else:

                    # TODO: save process.stdout

                    print(green('ok.'))
            else:
                print(red('not found.'))

        i += 1

    print('Deleting missing heuristics...')
    # TODO: remove from the DB the heuristics that were removed from the directory.

    database.commit()
    database.close()
    print("\nFinished.")


if __name__ == "__main__":
    main()
