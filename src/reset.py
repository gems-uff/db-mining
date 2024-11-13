import os
import subprocess
import argparse
import sys

import pandas as pd

from util import ANNOTATED_FILE_JAVA, REPOS_DIR, filter_repositories, green, red, CODE_DEBUG, yellow


def main():
    """
    This program can be useful to fix collisions (due to data migrated from case insensitive to case sensitive file
    systems) and to update the workspace to the most recent version.
    """

    parser = argparse.ArgumentParser(
        prog='reset',
        description='Fix collisions and update workspace to the most recent version')

    parser.add_argument(
        '-i', '--input', default=ANNOTATED_FILE_JAVA,
        help="Input xlsx file")
    parser.add_argument(
        '-f', '--filter', default=[], nargs="*",
        help="Regex filter for repository")
    parser.add_argument(
        '-pi', '--min-project', default=1, type=int,
        help="First project in interval"
    )
    parser.add_argument(
        '-pf', '--max-project', default=None, type=int,
        help="Last project in interval"
    )
    parser.add_argument(
        '-s', '--source', default="origin/HEAD",
        help="Identify the reference/column that should be used as source"
    )
    parser.add_argument(
        "-m", "--mode", choices=["reference", "column"],
        help="Reset mode. Reset by reference uses the `source` git reference. Reset by column loads the column `source` of the input file"
    )
    parser.add_argument(
        '-d', '--skip-discard', action="store_true",
        help="Skip checking for discard reason"
    )
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Invalid input path: {args.input}", file=sys.stderr)
        sys.exit(1)
    print(f'Loading repositories from {args.input}.')
    info_repositories = pd.read_excel(args.input, keep_default_na=False)
    if not args.skip_discard:
        info_repositories = info_repositories[info_repositories.discardReason == ''].reset_index(drop=True)
    info_repositories = filter_repositories(info_repositories, args.filter)

    rows = [
        iterrow for i, iterrow in enumerate(info_repositories.iterrows())
        if i >= args.min_project - 1 and (not args.max_project or i < args.max_project)
    ]
    total = len(rows)

    status = {
        'Success': 0,
        'Collided': 0,
        'Repository not found': 0,
        'Git error': 0,
        'Total': total
    }

    print(f'Resetting {status["Total"]} repositories...')
    for i, (_, row) in enumerate(rows):
        # Print progress information
        progress = '{:.2%}'.format(i / status["Total"])
        print(f'[{progress}] Processing repository {row["owner"]}/{row["name"]}:', end=' ')

        try:
            target = REPOS_DIR + os.sep + row['owner'] + os.sep + row['name']
            os.chdir(target)

            # Removes lock file, if they exist
            try:
                os.remove('.git/index.lock')
            except OSError:
                pass

            process = subprocess.run(['git', 'config', 'core.precomposeunicode', 'false'], capture_output=True)
            if process.stderr:
                raise subprocess.CalledProcessError(process.returncode, process.args, output=process.stdout, stderr=process.stderr)

            reference = args.source
            if args.mode == "column":
                reference = row[reference]

            cmd = ['git', 'reset', '--hard', '-q', reference]
            process = subprocess.run(cmd, capture_output=True)
            if process.stderr:
                raise subprocess.CalledProcessError(process.returncode, cmd, process.stdout, process.stderr)

            cmd = ['git', 'clean', '-d', '-f', '-x', '-q']
            process = subprocess.run(cmd, capture_output=True)
            if process.stderr:
                raise subprocess.CalledProcessError(process.returncode, cmd, process.stdout, process.stderr)

            process = subprocess.run(['git', 'status', '-s'], capture_output=True)
            if process.stdout or process.stderr:
                print(yellow('collided.'))
                status['Collided'] += 1
                if CODE_DEBUG:
                    print(process.stdout)
                    print(process.stderr)
            else:
                print(green('ok.'))
                status['Success'] += 1
        except NotADirectoryError:
            print(red('repository not found.'))
            status['Repository not found'] += 1
        except subprocess.CalledProcessError as ex:
            print(red('Git error.'))
            status['Git error'] += 1
            if CODE_DEBUG:
                print(ex.stderr)

    print('\n*** Processing results ***')
    for k, v in status.items():
        print(f'{k}: {v}')

    print("\nFinished.")


if __name__ == "__main__":
    main()
