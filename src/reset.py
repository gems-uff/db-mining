import os
import subprocess

import pandas as pd

from util import ANNOTATED_FILE, REPOS_DIR, green, red, CODE_DEBUG, yellow


def main():
    """
    This program can be useful to fix collisions (due to data migrated from case insensitive to case sensitive file
    systems) and to update the workspace to the most recent version.
    """
    print(f'Loading repositories from {ANNOTATED_FILE}.')
    info_repositories = pd.read_excel(ANNOTATED_FILE, keep_default_na=False)
    info_repositories = info_repositories[info_repositories.discardReason == ''].reset_index(drop=True)

    status = {
        'Success': 0,
        'Collided': 0,
        'Repository not found': 0,
        'Git error': 0,
        'Total': len(info_repositories)
    }

    print(f'Resetting {status["Total"]} repositories...')
    for i, row in info_repositories.iterrows():
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
                raise subprocess.CalledProcessError(process.stderr)

            cmd = ['git', 'reset', '--hard', '-q', 'origin/HEAD']
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
