import os
import subprocess

import pandas as pd

from utils.view import bold, red, green

# File to load the data with repositories
REPOS_FILE = os.path.abspath('../resources/annotated.xlsx')

# Directories with heuristics
HEURISTICS_DIRS = {
    'database': os.path.abspath('../heuristics/database'),
    'implementation': os.path.abspath('../heuristics/implementation'),
    'query': os.path.abspath('../heuristics/query')
}

# Directory with repositories
REPO_DIR = os.path.abspath('../repos')

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
    heuristics = dict()
    for dirpath, dirnames, filenames in os.walk(directory):
        for filename in filenames:
            heuristics[os.path.splitext(filename)[0]] = os.path.join(dirpath, filename)
    return heuristics


def main():
    print(f'Loading repositories from {REPOS_FILE}.')
    repos_df = pd.read_excel(REPOS_FILE, keep_default_na=False)
    repos_df = repos_df[repos_df.discardReason == '']

    for heuristic_type in HEURISTICS_DIRS.keys():
        print(f'Loading {heuristic_type} heuristics from {HEURISTICS_DIRS[heuristic_type]}.')
        heuristics = load_heuristics(HEURISTICS_DIRS[heuristic_type])

        print(f'Processing {len(heuristics)} {heuristic_type} heuristics over {len(repos_df)} repositories...')
        count_heuristic = 1
        for heuristic, heuristic_file in heuristics.items():

            # TODO: check if the heuristic already exists in the DB.

            print(f'Processing heuristic for {bold(heuristic)}.')
            for i, repo in repos_df.iterrows():
                print(f'\tRepository {repo["owner"]}/{repo["name"]}:', end=' ')

                # TODO: check if the heuristic has already been executed over the project.

                target = REPO_DIR + os.sep + repo['owner'] + os.sep + repo['name']
                if os.path.isdir(target):
                    os.chdir(target)
                    process = subprocess.run(GREP_COMMAND + [heuristic_file], text=True, capture_output=True)

                    if process.stderr:
                        print(red('error.'))
                        print(process.stderr)
                        exit(1)
                    else:

                        # TODO: save process.stdout

                        print(green('ok.'))
                else:
                    print(red('not found.'))

            count_heuristic += 1

        print('Deleting missing heuristics...')
        # TODO: remove from the DB the heuristics that were removed from the directory.

    print("\nFinished.")


if __name__ == "__main__":
    main()
