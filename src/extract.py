"""Extract heuristics from projects.

By default, this script extracts heuristics from the history dividing into slices of 100 commits.

It accepts arguments to change the default behavior, and some addotional scripts 
implement common parameters that are useful.
"""

import os
import subprocess
import argparse
import sys
from timeit import default_timer as timer
from email.utils import parsedate_to_datetime
from datetime import timezone
from collections import defaultdict

import pandas as pd

import database as db
from sqlalchemy.orm import load_only, selectinload
from sqlalchemy import update
from util import ANNOTATED_FILE_JAVA, HEURISTICS_DIR, REPOS_DIR, filter_repositories, red, green, yellow, CODE_DEBUG


class ExtractException(Exception):
    def __init__(self, message, status='Git error'):            
        super().__init__(message)
            
        self.status = status

# Git rev-parse command
REVPARSE_COMMAND = [
    'git',
    'rev-parse',
    '--verify',
    'HEAD'
]

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
    '--extended-regexp',
    '-f'
]

GREP_COMMAND_IGNORECASE = [
    'git',
    'grep',
    '--ignore-case',
    '--context=5',
    '--break',
    '--heading',
    '--line-number',
    '--color=always',
    '--extended-regexp',
    '-f'
]


# Git comands to list commits historical
REVLIST_COMMAND = ['git','rev-list', '--reverse', "--pretty='%H %aD'"]
CHECKOUT_COMMAND = ['git','checkout', '-f']


def print_results(status):
    print('\nRESULTS')
    for k, v in status.items():
        print(f'{k}: {v}')
    print()


def do_commit():
    print('Committing changes...')
    db.commit()


def get_or_create_projects(
    filename=ANNOTATED_FILE_JAVA,
    filters=None, min_project=1, max_project=None,
    sysexit=True, create_version=False,
    skip_remove=False
):

    if not os.path.exists(filename) and sysexit:
        print(f"Invalid input path: {filename}", file=sys.stderr)
        sys.exit(1)
    print(f'Loading projects from {filename}.')
    projects = []

    # Loading projects from the Excel.
    df = pd.read_excel(filename, keep_default_na=False)
    df = df[df.discardReason == ''].reset_index(drop=True)
    projects_excel = {}
    ignore = set()
    for i, (_, project_excel) in enumerate(df.iterrows()):
        project_tup = (project_excel['owner'], project_excel['name'])
        if filters and f"{project_excel.owner}/{project_excel.name}" not in filters:
            ignore.add(project_tup)
            continue
        if i < min_project - 1 or (max_project and i >= max_project):
            ignore.add(project_tup)
            continue
        #project_excel["pos"] = i
        projects_excel[project_tup] = project_excel


    # Loading projects from the database.
    projects_db = db.query(db.Project).options(
        load_only(db.Project.id, db.Project.owner, db.Project.name)
    ).all()

    status = {
        'Excel': len(projects_excel),
        'Database': len(projects_db),
        'Added': 0,
        'Deleted': 0,
        'Repository not found': 0,
        'Git error': 0
    }

    i = 0
    # Deleting projects that do not exist in the Excel file
    for project in projects_db:
        project_tup = (project.owner, project.name)
        if projects_excel.pop(project_tup, None) is not None:
            # Print progress information
            i += 1
            progress = '{:.2%}'.format(i / status['Excel'])
            print(f'[{progress}] Adding project {project.owner}/{project.name}:', end=' ')
            projects.append(project)
            print(yellow('already done.'))
        elif project_tup not in ignore and not skip_remove:
            db.delete(project)
            status['Deleted'] += 1

    # Adding missing projects in the database
    for project_excel in projects_excel.values():
        # Print progress information
        project_tup = (project_excel['owner'], project_excel['name'])
        if project_tup in ignore:
            continue
        i += 1
        progress = '{:.2%}'.format(i / status['Excel'])
        print(f'[{progress}] Adding project {project_excel["owner"]}/{project_excel["name"]}:', end=' ')

        project_dict = {k: v for k, v in project_excel.to_dict().items() if
                        k not in ['url', 'isSoftware', 'discardReason']}
        project_dict['createdAt'] = str(project_dict['createdAt'])
        project_dict['pushedAt'] = str(project_dict['pushedAt'])
        try:
            os.chdir(REPOS_DIR + os.sep + project_dict['owner'] + os.sep + project_dict['name'])
            sha1 = do_rev_parse(False)
            project = db.create(db.Project, **project_dict)
            if create_version:
                db.create(db.Version, sha1=sha1, isLast=True, project=project)
            projects.append(project)
            print(green('ok.'))
            status['Added'] += 1

        except NotADirectoryError:
            print(red('repository not found.'))
            status['Repository not found'] += 1
        except FileNotFoundError:
            print(red('Project not found.'))
            status['Repository not found'] += 1
        except ExtractException as ex:
            print(red('Git error.'))
            status['Git error'] += 1
            if CODE_DEBUG:
                print(ex.stderr)

    status['Total'] = len(projects)
    print_results(status)
    do_commit()
    return projects


def populate_labels_fs(labels_fs, label_type_path, label_type_name):
    for label in os.scandir(label_type_path):
        if label.is_file() and not label.name.startswith('.'):
            with open(label.path) as file:
                pattern = file.read()
                label_fs = {
                    'name': os.path.splitext(label.name)[0],
                    'type': label_type_name,
                    'pattern': pattern,
                }
                labels_fs[(label_fs['type'], label_fs['name'])] = label_fs


def get_or_create_labels(heuristics_dir=HEURISTICS_DIR, label_type=None, skip_remove=False):
    print(f'\nLoading heuristics from {heuristics_dir}.')
    labels = []

    # Loading heuristics from the file system.
    labels_fs = dict()
    if label_type is None:
        for label_type_dir in os.scandir(heuristics_dir):
            if label_type_dir.is_dir() and not label_type_dir.name.startswith('.'):
                populate_labels_fs(labels_fs, label_type_dir.path, label_type_dir.name)
    else:
        populate_labels_fs(labels_fs, heuristics_dir, label_type)

    # Loading labels from the database.
    labels_db = db.query(db.Label).options(
        selectinload(db.Label.heuristic)
        .options(selectinload(db.Heuristic.executions)
                 .defer(db.Execution.output)
                 .defer(db.Execution.user))
    )
    if label_type is not None:
        labels_db = labels_db.filter(db.Label.type == label_type)
    labels_db = labels_db.all()

    status = {
        'File System': len(labels_fs),
        'Database': len(labels_db),
        'Added': 0,
        'Deleted': 0,
        'Updated': 0,
    }

    i = 0
    # Deleting labels that do not exist in the file system
    for label in labels_db:
        label_fs = labels_fs.pop((label.type, label.name), None)
        if label_fs is not None:
            # Print progress information
            i += 1
            progress = '{:.2%}'.format(i / status['File System'])
            print(f'[{progress}] Adding label {label.type}/{label.name}:', end=' ')
            labels.append(label)

            # Check if pattern has changed and, in this case, remove executions that are not accepted and verified
            heuristic = label.heuristic
            if heuristic.pattern != label_fs['pattern']:
                heuristic.pattern = label_fs['pattern']
                count = 0
                if not skip_remove:
                    for execution in list(heuristic.executions):
                        if not (execution.isValidated and execution.isAccepted):
                            # The commit does not invalidate the objects for performance reasons,
                            # so we need to remove the relationships before deleting the execution.
                            execution.heuristic = None
                            execution.version = None

                            db.delete(execution)
                            count += 1
                    print(green(f'heuristic updated ({count} executions removed).'))
                status['Updated'] += 1
            else:
                print(yellow('already done.'))
        elif not skip_remove:
            db.delete(label)
            status['Deleted'] += 1

    # Adding missing labels in the database
    for label_fs in labels_fs.values():
        # Print progress information
        i += 1
        progress = '{:.2%}'.format(i / status['File System'])
        print(f'[{progress}] Adding label {label_fs["type"]}/{label_fs["name"]}:', end=' ')

        label = db.create(db.Label, name=label_fs['name'], type=label_fs['type'])
        db.create(db.Heuristic, pattern=label_fs['pattern'], label=label, executions=[])
        labels.append(label)
        print(green('ok.'))
        status['Added'] += 1

    status['Total'] = len(labels)
    print_results(status)
    do_commit()
    return sorted(labels, key=lambda item: (item.type.lower(), item.name.lower()))


def index_executions(labels):
    executions = dict()

    for label in labels:
        heuristic = label.heuristic
        for execution in heuristic.executions:
            executions[(heuristic, execution.version)] = execution

    return executions


def validate_ignore_case(label):
    return label.name.startswith('(IgnoreCase')


def list_commits(mode="all", n=10, proportional=False, verbose=False):
    if mode == "firstparent":
        mode_cmd = ["--first-parent", "HEAD"]
    else:
        mode_cmd = ["--all"]
    cmd = REVLIST_COMMAND + mode_cmd
    if verbose:
        print('\n>>>', ' '.join(cmd))
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.stderr:
        raise subprocess.CalledProcessError(p.returncode, cmd, p.stdout, p.stderr)

    all_commits = []
    for i, line in enumerate(iter(p.stdout.decode('utf-8').split('\n'))):
        if i % 2 == 0:
            continue
        commit, datestr = line.strip().strip("'").split(' ', 1)
        commit_date = parsedate_to_datetime(datestr).astimezone(timezone.utc)
        all_commits.append((commit, commit_date))

    if not all_commits:
        return [], None

    if proportional:
        # Divide repository into n slices
        if not n:
            return all_commits, all_commits[-1][0]
        size = len(all_commits) // n

        return all_commits[size-1::size], all_commits[-1][0]
    else:
        # Create slices with n commits
        commits_by_n = []
        for i in range(n - 1, len(all_commits), n):  # Pula n commits e pega o último de cada intervalo
            commits_by_n.append(all_commits[i])

        return commits_by_n, all_commits[-1][0]


def do_rev_parse(verbose):
    cmd = REVPARSE_COMMAND
    if verbose:
        print('\n>>>', ' '.join(cmd))
    try:
        p = subprocess.run(cmd, capture_output=True)
        if p.stderr:
            raise ExtractException("Git error (rev-parse).")
        last_sha1 = p.stdout.decode(errors='replace').replace('\x00', '\uFFFD').strip()
        return last_sha1
    except subprocess.TimeoutExpired as e:
        raise ExtractException("Git error (rev-parse).") from e
    except subprocess.CalledProcessError as ex:
        raise ExtractException("Git error (rev-parse).") from e
        

def do_checkout(commit, verbose):
    print(f"Checkout commit {commit}.")
    cmd = CHECKOUT_COMMAND + [commit]
    if verbose:
        print('\n>>>', ' '.join(cmd))
    try:
        p = subprocess.run(cmd, capture_output=True)
    except subprocess.TimeoutExpired as ex:
        raise ExtractException("Git error (checkout).") from ex
    except subprocess.CalledProcessError as ex:
        raise ExtractException("Git error (checkout).") from ex


def read_args(
        prog, description,
        default_proportional=False,
        default_slices=100,
        default_label_type=None,
        default_skip_remove=False,
        default_heuristics=HEURISTICS_DIR,
        default_label_selection="all",
        default_grep_workspace=False,
    ):
    parser = argparse.ArgumentParser(
        prog=prog,
        description=description)

    parser.add_argument(
        '-i', '--input', default=ANNOTATED_FILE_JAVA,
        help="Input xlsx file")
    parser.add_argument(
        '-f', '--filter', default=[], nargs="*",
        help="Select specific repositories")
    parser.add_argument(
        '-x', '--heuristics', default=default_heuristics,
        help="Heuristics directory")
    parser.add_argument(
        "-t", '--label-type', default=default_label_type,
        help="Heuristics label type"
    )
    parser.add_argument(
        '-l', '--list-commits-mode', default='firstparent',
        choices=['firstparent', 'all'],
        help="Rev-list execution mode"
    )
    parser.add_argument(
        '-s', '--slices', default=default_slices, type=int,
        help="Slice division. In proportional mode, use 0 to get all commits and 1 to get latest."
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        '-p', '--proportional', action="store_true",
        help="Split history into S slices."
    )
    group.add_argument(
        '--by-s-commits', dest="proportional", action="store_false",
        help="Split history into slices of S commits."
    )
    parser.set_defaults(proportional=default_proportional)
    parser.add_argument(
        '--min-slice', default=1, type=int,
        help="First slice in interval"
    )
    parser.add_argument(
        '--max-slice', default=None, type=int,
        help="Last slice in interval"
    )
    parser.add_argument(
        '-pi', '--min-project', default=1, type=int,
        help="First project in interval"
    )
    parser.add_argument(
        '-pf', '--max-project', default=None, type=int,
        help="Last project in interval"
    )
    parser.add_argument(
        '-v', '--verbose', action="store_true",
        help="Show command"
    )
    parser.add_argument(
        '-c', '--checkout', action="store_true",
        help="Checkout version before analysis"
    )
    parser.add_argument(
        '-r', '--restore', action="store_true",
        help="Restore repository to initial version. Only valid with checkout flag"
    )
    parser.add_argument(
        '--dry-run', action="store_true",
        help="Dry-run. Do not extract repositories"
    )
    group2 = parser.add_mutually_exclusive_group(required=False)
    group2.add_argument(
        '-a', '--skip-remove', action="store_true",
        help="Additive mode. Do not remove database records"
    )
    group2.add_argument(
        '--remove', dest="skip_remove", action="store_false",
        help="Remove projects that do not exist on the spreadsheet and heuristics that do not exist on the directories."
    )
    parser.set_defaults(skip_remove=default_skip_remove)
    parser.add_argument(
        '--label-selection', choices=["all", "project"], default=default_label_selection,
        help="Indicate how to select labels by project. all = Find all heuristics in each project; project = Find only heuristics that have the same name as the project"
    )
    group3 = parser.add_mutually_exclusive_group(required=False)
    group3.add_argument(
        '--may-grep-workspace', action="store_true",
        help="Grep workspace when analyzing the HEAD commit"
    )
    group3.add_argument(
        '--grep-version', dest="may_grep_workspace", action="store_false",
        help="Grep by version."
    )
    parser.set_defaults(may_grep_workspace=default_grep_workspace)
    
    return parser.parse_args()


def prepare_commits(args, project):
    """Get subset of commits based on slice definition and update part_commit of existing versions"""
    commits, last_sha1 = list_commits(args.list_commits_mode, args.slices, args.proportional, args.verbose)
    total_commit = len(commits)
    commits = commits[args.min_slice - 1:args.max_slice]
    last_commit = total_commit if not args.max_slice else args.max_slice
    if total_commit > 1 and not args.dry_run:
        # Remove all existing part_commits because the new selection will override it
        condition = (
            (db.Version.project_id == project.id)
            & (db.Version.part_commit >= args.min_slice)    
        )
        if args.max_slice:
            condition = condition & (db.Version.part_commit <= last_commit)
        update(db.Version).where(condition).values(part_commit = None)
    return commits, last_sha1, total_commit, last_commit


def prepare_version(project, commit, total_commit, part, commit_date, last_sha1):
    """Find or create version"""
    version = db.db.session.query(db.Version).filter(
        (db.Version.project_id == project.id) &
        (db.Version.sha1 == commit)
    ).first()
    if version:
        if total_commit > 1:
            version.part_commit = part
        version.date_commit = commit_date
        version.isLast = commit == last_sha1
        is_new = False
    else:
        version = db.Version(
            project=project, sha1=commit,
            isLast=commit == last_sha1,
            part_commit=part, date_commit=commit_date
        )
        is_new = True
    db.db.session.add(version)
    return version, is_new


def maybe_checkout(args, commit, head_sha1):
    if args.checkout:
        do_checkout(commit, args.verbose)
        current_commit = do_rev_parse(args.verbose)
        if current_commit != commit:
            raise ExtractException(f'Git error (checkout failed: {current_commit}, {commit}).')
        return current_commit
    return head_sha1
    

def find_heuristic(project, label, heuristic_path, commit=None, label_type=None, verbose=False):
    try:
        ignore_case = validate_ignore_case(label)
        os.chdir(REPOS_DIR + os.sep + project.owner + os.sep + project.name)
        cmd = GREP_COMMAND_IGNORECASE if ignore_case else GREP_COMMAND
            
        if not label_type:
            heuristic_path = heuristic_path + os.sep + label.type
        cmd = cmd + [heuristic_path + os.sep + label.name + '.txt']
        if commit:  # Find in specific commit instead of workspace
            cmd = cmd + [commit]
        if verbose:
            print('\n>>>', ' '.join(cmd))
        p = subprocess.run(cmd, capture_output=True)
        if p.stderr:
            raise ExtractException("Git error (git grep stderr).") from ex
        output = p.stdout.decode(errors='replace').replace('\x00', '\uFFFD')
        return output
    except subprocess.TimeoutExpired as ex:
        raise ExtractException("Git error (git grep timeout).") from ex
    except subprocess.CalledProcessError as ex:
        raise ExtractException("Git error (git grep).") from ex


def process_projects(args, connect=True):
    if connect:
        db.connect()
    cwd = os.getcwd()

    projects = get_or_create_projects(
        filename=args.input, filters=args.filter,
        min_project=args.min_project, max_project=args.max_project,
        skip_remove=args.skip_remove
    )

    labels = get_or_create_labels(
        heuristics_dir=args.heuristics,
        label_type=args.label_type,
        skip_remove=args.skip_remove
    )

    if args.label_selection == "all":
        def project_labels(project_qual_name):
            return labels
    elif args.label_selection == "project":
        label_map = defaultdict(list)
        for label in labels:
            # Get first label that implements this heuristics
            heuristic = label.heuristic
            heuristic_objct_label = db.query(db.Label).filter(db.Label.id == heuristic.label_id).first()
            owner, name, *_ = heuristic_objct_label.name.split(".")
            label_map[f"{owner}/{name}"].append(label)

        def project_labels(project_qual_name):
            return label_map.get(project_qual_name, [])
                

    # Indexing executions by label heuristic and project version.
    executions = index_executions(labels)

    status = {
        'Success': 0,
        'Skipped': 0,
        'Repository not found': 0,
        'Git error': 0,
        'Total': len(labels) * len(projects)
    }

    times = []
    # Searching all heuristics in the commits of each project
    total_project = len(projects)
    last_project = total_project if not args.max_project else args.max_project
    print(f'\nProcessing {len(projects)} projects {args.min_project}..{last_project} (out of {total_project}) over {len(labels)} heuristics.')
    for j, project in enumerate(projects):
        try:
            project_qual_name = f"{project.owner}/{project.name}"
            os.chdir(REPOS_DIR + os.sep + project.owner + os.sep + project.name)
            commits, last_sha1, total_commit, last_commit = prepare_commits(args, project)
            if args.may_grep_workspace or (args.checkout and args.restore):
                current_sha1 = do_rev_parse(args.verbose)
            head_sha1 = current_sha1 if args.may_grep_workspace else None
            last_sha1 = current_sha1 if args.checkout and args.restore else last_sha1

            tam = len(commits)
            part_project = args.min_project + j if total_project > 1 else None
            print(f'\nProcessing {tam} commits {args.min_slice}..{last_commit} (out of {total_commit}) of [Project {part_project or 1}: {j + 1}/{total_project}] {project_qual_name} project.')
            if args.dry_run:
                continue
            for c, (commit, commit_date) in enumerate(commits):
                if os.path.exists(os.path.join(cwd, ".stop")):
                    print("Found .stop file. Stopping execution")
                    break
                start = timer()
                part = args.min_slice + c if total_commit > 1 else None
                print(f"Commit {part or 1}: {c}/{tam} {commit}. ", end="")
                head_sha1 = maybe_checkout(args, commit, head_sha1)
                version, is_new = prepare_version(project, commit, total_commit, part, commit_date, last_sha1)
                print(f"... {'New' if is_new else 'Found'} version.")
                for i, label in enumerate(project_labels(project_qual_name)):
                    if os.path.exists(os.path.join(cwd, ".break")):
                        print("Found .break file. Pausing execution")
                        breakpoint()
                    heuristic = label.heuristic
                    # Print progress information Heuristics #projects * len(labels) + (j + 1))
                    progress = '{:.2%}'.format(((j + c/tam) * len(labels) + (i + 1)/tam) / status['Total'])
                    print(f'[{progress}] Searching for {label.name} in [Project {part_project or 1}: {j + 1}/{total_project} -- Commit {part or 1}: {c + 1}/{tam}] {project_qual_name}:', end=' ', flush=True)
                    # Try to get a previous execution
                    execution = executions.get((heuristic, version), None)
                    if not execution:
                        try:
                            output = find_heuristic(
                                project, label, args.heuristics,
                                commit=commit if commit != head_sha1 else None, # Grep workspace when commit == head_sha1
                                label_type=args.label_type,
                                verbose=args.verbose
                            )
                            db.create(db.Execution, output=output,
                                      version=version, heuristic=heuristic, isValidated=False, isAccepted=False)
                            print(green('uses.' if output else 'does not use.'))
                            status['Success'] += 1
                        except ExtractException as e:
                            print(red(e.message))
                            status[e.status] += 1
                    else:  # Execution already exists
                        print(yellow('already done.'))
                        status['Skipped'] += 1
                do_commit()
                end = timer()
                delta = end - start
                times.append(delta)
                print(f"Commit {commit} analysis took {delta}s. Average: {sum(times) / len(times)}")
        except NotADirectoryError:
            print(red('repository not found.'))
            status['Repository not found'] += 1
        except ExtractException as e:
            print(red(e.message))
            status[e.status] += 1
        finally:
            do_commit()
            if args.checkout and args.restore:
                print(f"Restore commit {last_sha1}.")
                do_checkout(last_sha1, args.verbose)

    print_results(status)
    if connect:
        db.close()

def main():
    args = read_args('extract', 'Extract heuristics from repositories')
    process_projects(args)


if __name__ == "__main__":
    main()
