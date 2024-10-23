"""This script shows which repositories would have less than 10 slices"""
import argparse
import os
import sys

import pandas as pd

from extract import list_commits
from util import ANNOTATED_FILE_JAVA, REPOS_DIR, filter_repositories



def main():
    parser = argparse.ArgumentParser(
        prog='filter_by_slices_count',
        description='Show which repositories would have less than N slices')
    
    parser.add_argument(
        '-i', '--input', default=ANNOTATED_FILE_JAVA,
        help="Input xlsx file")
    parser.add_argument(
        '-n', '--number', default=10, type=int,
        help="Number of slices to filter"
    )
    parser.add_argument(
        '-s', '--slices', default=100, type=int,
        help="Slice division"
    )
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
        '-l', '--list-commits-mode', default='firstparent',
        choices=['firstparent', 'all'],
        help="Rev-list execution mode"
    )
    parser.add_argument(
        '-v', '--verbose', action="store_true",
        help="Show command"
    )
    parser.add_argument(
        '-e', '--export', default=None,
        help="Export file with ALL slices. Note: it does not apply the number of slices filter"
    )
    cwd = os.getcwd()
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
    count = 0
    print(f'Checking {total} repositories...')
    results = []
    for i, (_, row) in enumerate(rows):
        owner, name = row['owner'], row['name']
        os.chdir(REPOS_DIR + os.sep + owner + os.sep + name)
        commits, last_sha1 = list_commits(args.list_commits_mode, args.slices, False, args.verbose)
        if len(commits) < args.number:
            print(f"- {owner}/{name}: {len(commits)} slices")
            count += 1
        results.append([
            owner, name, len(commits), last_sha1, 
            '; '.join(sha1 for sha1, date in commits),
            '; '.join(date.isoformat() for sha1, date in commits),
        ])


    print(f"Found {count} projects that should be filtered")
    os.chdir(cwd)
    if args.export:
        print(f"Saving all slices to {args.export}")
        resdf = pd.DataFrame(results, columns=['owner', 'name', 'count', 'commit', 'slices', 'dates'])
        #resdf.to_excel(args.export, index=False)
        resdf.to_csv(args.export, index=False, sep=";")

if __name__ == '__main__':
    main()
