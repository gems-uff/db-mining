import os
import subprocess
from collections import namedtuple

import pandas as pd

from util import ANNOTATED_FILE, REPOS_DIR, HEURISTICS_DIR
from util import bold, green, red

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
    Heuristic = namedtuple('Heuristic', ['type', 'label', 'file'])
    heuristics = list()
    for label_type in os.scandir(directory):
        if label_type.is_dir():
            for label in os.scandir(label_type.path):
                if label.is_file():
                    heuristics.append(Heuristic(label_type.name, os.path.splitext(label.name)[0], label.path))
    return heuristics


def main():
    print(f'Loading repositories from {ANNOTATED_FILE}.')
    repos_df = pd.read_excel(ANNOTATED_FILE, keep_default_na=False)
    repos_df = repos_df[repos_df.discardReason == ''].reset_index(drop=True)

    print(f'Loading heuristics from {HEURISTICS_DIR}.')
    heuristics = load_heuristics(HEURISTICS_DIR)

    print(f'Processing {len(heuristics)} heuristics over {len(repos_df)} repositories.')
    i = 0
    for heuristic in heuristics:

        # TODO: check if the heuristic already exists in the DB.

        print(f'Processing heuristic for {bold(heuristic.label)}.')
        for j, repo in repos_df.iterrows():
            progress = '{:.2%}'.format((i * len(repos_df) + j) / (len(heuristics) * len(repos_df)))
            print(f'\t[{progress}] Repository {repo["owner"]}/{repo["name"]}:', end=' ')

            # TODO: check if the heuristic has already been executed over the project.

            repo = REPOS_DIR + os.sep + repo['owner'] + os.sep + repo['name']
            if os.path.isdir(repo):
                os.chdir(repo)
                process = subprocess.run(GREP_COMMAND + [heuristic.file], text=True, capture_output=True)

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

    print("\nFinished.")


if __name__ == "__main__":
    main()
