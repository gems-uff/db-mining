import os

import pandas as pd

import database
from util import ANNOTATED_FILE, HEURISTICS_DIR

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
    heuristics = load_heuristics(HEURISTICS_DIR)

    print(f'Processing {len(heuristics)} heuristics over {len(repos_df)} repositories.')
    i = 0
    for heuristic in heuristics:
        label = database.insert_label(heuristic)
        existing_heuristic = database.get_heuristic_by_label_id(label['id'])
        if existing_heuristic and existing_heuristic['pattern'] != heuristic['pattern']:
            database.delete_heuristic(existing_heuristic)
            existing_heuristic = None
        if not existing_heuristic:
            database.insert_heuristic(heuristic)

        # for j, repo in repos_df.iterrows():
        #     progress = '{:.2%}'.format((i * len(repos_df) + j) / (len(heuristics) * len(repos_df)))
        #     print(f'[{progress}] Searching for {heuristic["name"]} in {repo["owner"]}/{repo["name"]}:', end=' ')
        #
        #     # TODO: check if the heuristic has already been executed over the project.
        #
        #     repo = REPOS_DIR + os.sep + repo['owner'] + os.sep + repo['name']
        #     if os.path.isdir(repo):
        #         os.chdir(repo)
        #         process = subprocess.run(GREP_COMMAND + [heuristic['pattern_file']], text=True, capture_output=True)
        #
        #         if process.stderr:
        #             print(red('error.'))
        #             print(process.stderr)
        #             exit(1)
        #         else:
        #
        #             # TODO: save process.stdout
        #
        #             print(green('ok.'))
        #     else:
        #         print(red('not found.'))

        i += 1

    print('Deleting missing heuristics...')
    # TODO: remove from the DB the heuristics that were removed from the directory.

    print("\nFinished.")


if __name__ == "__main__":
    main()
