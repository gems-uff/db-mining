import os
import subprocess

import pandas as pd

from utils.view import bold, red, green

# File to load the data with repositories
REPOS_FILE = '../resources/annotated.xlsx'

# File to load the data with database heuristics
HEURISTICS_FILE = '../resources/heuristics-database.xlsx'

# Dir to clone/update repositories
REPO_DIR = os.path.abspath('../repos')

# Basic git grep command
BASIC_GREP_COMMAND = ['git', 'grep', '-I', '--context=5', '--break', '--heading', '--line-number']


def main():
    print(f'Loading heuristics from {HEURISTICS_FILE}.')
    heuristics_df = pd.read_excel(HEURISTICS_FILE, keep_default_na=False)

    print(f'Loading repositories from {REPOS_FILE}.')
    repos_df = pd.read_excel(REPOS_FILE, keep_default_na=False)
    repos_df = repos_df[repos_df.discardReason == '']

    print(f'Processing {len(heuristics_df)} heuristics over {len(repos_df)} repositories...')

    for i, heuristic in heuristics_df.iterrows():
        print(f'Processing heuristic {bold(heuristic["pattern"])}', end=' ')
        print('({:.0f}%).'.format(i / len(heuristics_df) * 100))

        grep_command = BASIC_GREP_COMMAND
        if heuristic['regex']:
            grep_command.append('--extended-regexp')
        else:
            grep_command.append('--fixed-strings')
        if not heuristic['case-sensitive']:
            grep_command.append('--ignore-case')
        grep_command.append(heuristic['pattern'])

        # TODO: check if the heuristic already exists in the DB.

        for j, repo in repos_df.iterrows():
            print(f'\tRepository {repo["owner"]}/{repo["name"]}:', end=' ')
            target = REPO_DIR + os.sep + repo['owner'] + os.sep + repo['name']

            # TODO: check if the heuristic has already been executed over the project.

            if os.path.isdir(target):
                os.chdir(target)
                process = subprocess.run(grep_command, text=True, capture_output=True)
                print(process.stdout)
                print(red(process.stderr))

                print(green('ok.'))
            else:
                print(red('not found.'))

    print('Deleting missing heuristics...')
    # TODO: remove from the DB the heuristics that were removed from the excel file.

    print("\nFinished.")


if __name__ == "__main__":
    main()
