import os
import subprocess

import pandas as pd

# File to load the data with repositories
REPO_FILE = '../resources/annotated.xlsx'

# Dir to clone/update repositories
REPO_DIR = os.path.abspath('../repos')


def main():
    """
    This program can be useful to fix collisions (due to data migrated from case insensitive to case sensitive file
    systems) and to update the workspace to the most recent version.
    """
    print(f'Loading repositories from {REPO_FILE}.')
    df = pd.read_excel(REPO_FILE, keep_default_na=False)

    print('Removing discarded repositories.')
    df = df[df.discardReason == '']

    total = len(df)
    print(f'Checking out {total} repositories...')

    for i, row in df.iterrows():
        print(f'Processing repository {row["owner"]}/{row["name"]}.')
        target = REPO_DIR + os.sep + row['owner'] + os.sep + row['name']

        os.chdir(target)
        subprocess.run(['git', 'reset', '--hard', '-q', 'origin/HEAD'])
        subprocess.run(['git', 'clean', '-d', '-f', '-x', '-q'])
        subprocess.run(['git', 'status', '-s'])

        print('Ok ({:.0f}%).'.format((i + 1) / total * 100))

    print("\nFinished.")


if __name__ == "__main__":
    main()
