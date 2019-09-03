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

    # removing discarded repositories
    df = df[df.discardReason == '']

    total = len(df)
    print(f'Processing {total} repositories...')

    #open file to capture output
    f = open("log.txt", "w")

    for i, row in df.iterrows():
        print(f'Processing repository {row["owner"]}/{row["name"]}.')
        f.write(f'\n*** Processing repository {row["owner"]}/{row["name"]}.\n')
        f.flush()
        target = REPO_DIR + os.sep + row['owner'] + os.sep + row['name']

        if os.path.isdir(target):
            os.chdir(target)
            subprocess.run(['git', 'grep', '-n', '-f', '../../../extraction/patterns.txt'], stdout=f)
        else:
            print('Repository path not found...')
        print('Ok ({:.0f}%).'.format((i + 1) / total * 100))
        if i == 5:
            break

    print("\nFinished.")
    f.close()


if __name__ == "__main__":
    main()
