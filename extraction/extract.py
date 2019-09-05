import os

import pandas as pd

from utils.view import bold, red, green

# File to load the data with repositories
REPOS_FILE = '../resources/annotated.xlsx'

# File to load the data with database heuristics
HEURISTICS_FILE = '../resources/heuristics-database.xlsx'

# Dir to clone/update repositories
REPO_DIR = os.path.abspath('../repos')


def main():
    print(f'Loading heuristics from {HEURISTICS_FILE}.')
    heuristics_df = pd.read_excel(HEURISTICS_FILE, keep_default_na=False)

    print(f'Loading repositories from {REPOS_FILE}.')
    repos_df = pd.read_excel(REPOS_FILE, keep_default_na=False)
    repos_df = repos_df[repos_df.discardReason == '']

    print(f'Processing {len(heuristics_df)} heuristics over {len(repos_df)} repositories...')

    # open file to capture output
    f = open("log.txt", "w")

    for i, heuristic in heuristics_df.iterrows():
        print(f'Processing heuristic {bold(heuristic["regex"])}', end=' ')
        print('({:.0f}%).'.format(i / len(heuristics_df) * 100))

        # TODO: check if the heuristic already exists in the DB.

        for j, repo in repos_df.iterrows():
            print(f'\tRepository {repo["owner"]}/{repo["name"]}:', end=' ')
            target = REPO_DIR + os.sep + repo['owner'] + os.sep + repo['name']

            # TODO: check if the heuristic has already been executed over the project.

            if os.path.isdir(target):
                os.chdir(target)
                #
                # subprocess.run(['git', 'grep', '-n', '-f', '../../../extraction/patterns.txt'], stdout=f)
                print(green('ok.'))
            else:
                print(red('not found.'))

    print('Deleting missing heuristics...')
    # TODO: remove from the DB the heuristics that were removed from the excel file.

    print("\nFinished.")
    f.close()


if __name__ == "__main__":
    main()
