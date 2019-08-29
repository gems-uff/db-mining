import os
import subprocess

import pandas as pd

# File to load the data with repositories
REPO_FILE = '../docs/annotated.xlsx'

# Dir to clone/update repositories
REPO_DIR = os.path.abspath('../repos')


def main():
    print(f'Loading repositories from {REPO_FILE}.')
    df = pd.read_excel(REPO_FILE, keep_default_na=False)

    print('Removing discarded repositories.')
    df = df[df.discardReason == '']

    total = len(df)
    print(f'Cloning/updating {total} repositories...')

    for i, row in df.iterrows():
        print(f'Processing repository {row["owner"]}/{row["name"]}.')
        source = f'https://github.com/{row["owner"]}/{row["name"]}.git'
        target = REPO_DIR + os.sep + row['owner'] + os.sep + row['name']

        if os.path.isdir(target):
            os.chdir(target)
            subprocess.run(['git', 'remote', 'update'])
        else:
            os.makedirs(target, exist_ok=True)
            subprocess.run(['git', 'clone', source, target])

        print('Ok ({:.0f}%).'.format((i + 1) / total * 100))

    print("\nFinished.")


if __name__ == "__main__":
    main()
