import os
import subprocess
import argparse
import sys
from timeit import default_timer as timer
from email.utils import parsedate_to_datetime
from datetime import timezone

import pandas as pd

import database as db
from sqlalchemy.orm import load_only, selectinload
from sqlalchemy import update
from util import ANNOTATED_FILE_JAVA, HEURISTICS_DIR, REPOS_DIR, filter_repositories, red, green, yellow, CODE_DEBUG


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
CHECKOUT_COMMAND = ['git','checkout']


def print_results(status):
    print('\nRESULTS')
    for k, v in status.items():
        print(f'{k}: {v}')
    print()


def do_commit():
    print('Committing changes...')
    db.commit()


def get_or_create_projects(filename=ANNOTATED_FILE_JAVA, filters=[], sysexit=True, create_version=False):

    if not os.path.exists(filename) and sysexit:
        print(f"Invalid input path: {filename}", file=sys.stderr)
        sys.exit(1)
    print(f'Loading projects from {filename}.')
    projects = []

    # Loading projects from the Excel.
    df = pd.read_excel(filename, keep_default_na=False)
    df = df[df.discardReason == ''].reset_index(drop=True)
    df = filter_repositories(df, filters, sysexit=sysexit)
    projects_excel = dict()
    for i, project_excel in df.iterrows():
        projects_excel[(project_excel['owner'], project_excel['name'])] = project_excel

    # Loading projects from the database.
    projects_db = db.query(db.Project).options(load_only('id', 'owner', 'name'), selectinload(db.Project.versions).load_only('id')).all()

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
        if projects_excel.pop((project.owner, project.name), None) is not None:
            # Print progress information
            i += 1
            progress = '{:.2%}'.format(i / status['Excel'])
            print(f'[{progress}] Adding project {project.owner}/{project.name}:', end=' ')
            projects.append(project)
            print(yellow('already done.'))
        else:
            db.delete(project)
            status['Deleted'] += 1

    # Adding missing projects in the database
    for project_excel in projects_excel.values():
        # Print progress information
        i += 1
        progress = '{:.2%}'.format(i / status['Excel'])
        print(f'[{progress}] Adding project {project_excel["owner"]}/{project_excel["name"]}:', end=' ')

        project_dict = {k: v for k, v in project_excel.to_dict().items() if
                        k not in ['url', 'isSoftware', 'discardReason']}
        project_dict['createdAt'] = str(project_dict['createdAt'])
        project_dict['pushedAt'] = str(project_dict['pushedAt'])
        try:
            os.chdir(REPOS_DIR + os.sep + project_dict['owner'] + os.sep + project_dict['name'])
            p = subprocess.run(REVPARSE_COMMAND, capture_output=True)
            if p.stderr:
                raise subprocess.CalledProcessError(p.returncode, REVPARSE_COMMAND, p.stdout, p.stderr)

            project = db.create(db.Project, **project_dict)
            if create_version:
                db.create(db.Version, sha1=p.stdout.decode().strip(), isLast=True, project=project)
            projects.append(project)
            print(green('ok.'))
            status['Added'] += 1
        except NotADirectoryError:
            print(red('repository not found.'))
            status['Repository not found'] += 1
        except FileNotFoundError:
            print(red('Project not found.'))
            status['Repository not found'] += 1
        except subprocess.CalledProcessError as ex:
            print(red('Git error.'))
            status['Git error'] += 1
            if CODE_DEBUG:
                print(ex.stderr)

    status['Total'] = len(projects)
    print_results(status)
    do_commit()
    return sorted(projects, key=lambda item: (item.owner.lower(), item.name.lower()))


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


def get_or_create_labels(heuristics_dir=HEURISTICS_DIR, label_type=None):
    print(f'\nLoading heuristics from {heuristics_dir}.')
    labels = []

    # Loading heuristics from the file system.
    labels_fs = dict()
    if label_type is None:
        for label_type in os.scandir(heuristics_dir):
            if label_type.is_dir() and not label_type.name.startswith('.'):
                populate_labels_fs(labels_fs, label_type.path, label_type.name)
    else:
        populate_labels_fs(labels_fs, heuristics_dir, label_type)

    # Loading labels from the database.
    labels_db = db.query(db.Label).options(selectinload(db.Label.heuristic).options(selectinload(db.Heuristic.executions).defer('output').defer('user'))).all()

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
        else:
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


def list_commits(mode="all", slices=10):
    if mode == "firstparent":
        mode_cmd = ["--first-parent", "HEAD"]
    else:
        mode_cmd = ["--all"]
    cmd = REVLIST_COMMAND + mode_cmd
    p = subprocess.run(REVLIST_COMMAND + mode_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.stderr:
        raise subprocess.CalledProcessError(p.returncode, cmd, p.stdout, p.stderr)
    all_commits = []
    for i, line in enumerate(iter(p.stdout.decode('utf-8').split('\n'))):
        if i % 2 == 0:
            continue
        commit, datestr = line.strip().strip("'").split(' ', 1)
        commit_date = parsedate_to_datetime(datestr).astimezone(timezone.utc)
        all_commits.append((commit, commit_date))
    if not slices:
        return all_commits, all_commits[-1][0]
    size = len(all_commits) // slices
    #print(list(range(len(all_commits)))[size-1::size])
    return all_commits[size-1::size], all_commits[-1][0]

def list_commits_by_n(mode="all", n=100):
    if mode == "firstparent":
        mode_cmd = ["--first-parent", "HEAD"]
    else:
        mode_cmd = ["--all"]
    cmd = REVLIST_COMMAND + mode_cmd
    p = subprocess.run(REVLIST_COMMAND + mode_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
    
    # Pegar commits de n em n
    commits_by_n = []
    for i in range(n - 1, len(all_commits), n):  # Pula n commits e pega o último de cada intervalo
        commits_by_n.append(all_commits[i])
    
    return commits_by_n, all_commits[-1][0]


def main():
    parser = argparse.ArgumentParser(
        prog='extract',
        description='Extract heuristics from repositories')

    parser.add_argument(
        '-i', '--input', default=ANNOTATED_FILE_JAVA,
        help="Input xlsx file")
    parser.add_argument(
        '-f', '--filter', default=[], nargs="*",
        help="Regex filter for repository")
    parser.add_argument(
        '-x', '--heuristics', default=HEURISTICS_DIR,
        help="Heuristics directory")
    parser.add_argument(
        '-l', '--list-commits-mode', default='all',
        choices=['firstparent', 'all'],
        help="Rev-list execution mode"
    )
    parser.add_argument(
        '-s', '--slices', default=1, type=int,
        help="Number of slices. Use 0 to get all commits and 1 to get latest."
    )

    args = parser.parse_args()

    db.connect()
    projects = get_or_create_projects(filename=args.input, filters=args.filter)
    labels = get_or_create_labels(heuristics_dir=args.heuristics)

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
    # Searching all heuristics in 10 commits of each project
    print(f'\nProcessing {len(projects)} projects over {len(labels)} heuristics.')
    for j, project in enumerate(projects):
        try:
            os.chdir(REPOS_DIR + os.sep + project.owner + os.sep + project.name)
            commits, last_sha1 = list_commits(args.list_commits_mode, args.slices) #mudar para list_commits_by_n quando for histórico
            tam = len(commits)
            print(f'\nProcessing {tam} commits of {project.name} project.')
            if tam > 1:
                # Remove all existing part_commits because the new selection will override it
                (
                    update(db.Version)
                    .where(db.Version.project_id == project.id)
                    .values(part_commit = None)
                )
            for i, (commit, commit_date) in enumerate(commits):
                start = timer()
                part = i + 1 if tam > 1 else None
                print(f"Commit: {i}/{tam} {commit}. ", end="")
                cmd = CHECKOUT_COMMAND + [commit]
                try:
                    p = subprocess.run(cmd, capture_output=True)
                except subprocess.TimeoutExpired:
                    print(red('Git error.'))
                    status['Git error'] += 1
                    continue
                except subprocess.CalledProcessError as ex:
                    print(red('Git error.'))
                    status['Git error'] += 1
                    continue
                version = db.db.session.query(db.Version).filter(
                    (db.Version.project_id == project.id) &
                    (db.Version.sha1 == commit)
                ).first()
                if version:
                    print("... Found version.")
                    if tam > 1:
                        version.part_commit = part
                    version.date_commit = commit_date
                    version.isLast = commit == last_sha1
                    db.db.session.add(version)
                else:
                    print("... New version.")
                    version = db.Version(
                        project=project, sha1=commit,
                        isLast=commit == last_sha1,
                        part_commit=part, date_commit=commit_date
                    )
                    db.db.session.add(version)
                #db.session.commit()
                for i, label in enumerate(labels):
                    heuristic = label.heuristic
                    # Print progress information Heuristics #projects * len(labels) + (j + 1))
                    progress = '{:.2%}'.format((j * len(labels) + (i + 1)) / status['Total'])
                    print(f'[{progress}] Searching for {label.name} in {project.owner}/{project.name}:', end=' ')

                    # Try to get a previous execution
                    execution = executions.get((heuristic, version), None)
                    if not execution:
                        try:
                            ignore_case = validate_ignore_case(label)
                            os.chdir(REPOS_DIR + os.sep + project.owner + os.sep + project.name)
                            if ignore_case:
                                cmd = GREP_COMMAND_IGNORECASE + [args.heuristics + os.sep + label.type + os.sep + label.name + '.txt']
                            else:
                                cmd = GREP_COMMAND + [args.heuristics + os.sep + label.type + os.sep + label.name + '.txt']
                            p = subprocess.run(cmd, capture_output=True)
                            if p.stderr:
                                raise subprocess.CalledProcessError(p.returncode, cmd, p.stdout, p.stderr)
                            db.create(db.Execution, output=p.stdout.decode(errors='replace').replace('\x00', '\uFFFD'),
                                      version=version, heuristic=heuristic, isValidated=False, isAccepted=False)
                            print(green('ok.'))
                            status['Success'] += 1
                        except subprocess.TimeoutExpired:
                            print(red('Git error.'))
                            status['Git error'] += 1
                        except subprocess.CalledProcessError as ex:
                            print(red('Git error GREP_COMMAND.'))
                            status['Git error'] += 1
                            if CODE_DEBUG:
                                print("Error debug", ex.stderr)
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
        finally:
            do_commit()
            print("Checkout last commit.")
            cmd = CHECKOUT_COMMAND + [last_sha1]
            try:
                p = subprocess.run(cmd, capture_output=True)
                print(green('ok.'))
            except subprocess.TimeoutExpired:
                print(red('Git error.'))
            except subprocess.CalledProcessError:
                print(red('Git error.'))

    print_results(status)
    db.close()


if __name__ == "__main__":
    main()
