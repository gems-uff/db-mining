import os
import sys
import subprocess
import argparse

import pandas as pd

from util import ANNOTATED_FILE_JAVA, REPOS_DIR, filter_repositories


def main():
    parser = argparse.ArgumentParser(
        prog='download',
        description='Download repositories from xlsx')

    parser.add_argument(
        '-i', '--input', default=ANNOTATED_FILE_JAVA,
        help="Input xlsx file")
    parser.add_argument(
        '-u', '--uriformat', default='https://github.com/{owner}/{name}.git',
        help="URI format for obtaining the repositories")
    parser.add_argument(
        '-f', '--filter', default=[], nargs="*",
        help="Regex filter for repository")
    parser.add_argument(
        '--min-project', default=1, type=int,
        help="First project in interval"
    )
    parser.add_argument(
        '--max-project', default=None, type=int,
        help="Last project in interval"
    )

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Invalid input path: {args.input}", file=sys.stderr)
        sys.exit(1)
    print(f'Loading repositories from {args.input}.')
    df = pd.read_excel(args.input, keep_default_na=False)

    print('Removing discarded repositories.')
    df = df[df.discardReason == '']
    df = filter_repositories(df, args.filter)

    rows = [
        iterrow for i, iterrow in enumerate(df.iterrows())
        if i >= args.min_project - 1 and (not args.max_project or i < args.max_project)
    ]
    total = len(rows)

    print(f'Cloning/updating {total} repositories...')
    for i, (_, row) in enumerate(rows):
        print(f'Processing repository {row["owner"]}/{row["name"]}.')
        source = args.uriformat.format(**row)
        target = REPOS_DIR + os.sep + row['owner'] + os.sep + row['name']

        if os.path.isdir(target):
            os.chdir(target)
            subprocess.run(['git', 'remote', 'update'])
            subprocess.run(['git', 'reset', '--hard', '-q', 'origin/HEAD'])
            subprocess.run(['git', 'clean', '-d', '-f', '-x', '-q'])
            subprocess.run(['git', 'status', '-s'])
        else:
            os.makedirs(target, exist_ok=True)
            subprocess.run(['git', 'clone', source, target])

        print('Ok ({:.0f}%).'.format((i + 1) / total * 100))

    print("\nFinished.")


if __name__ == "__main__":
    main()
