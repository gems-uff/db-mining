import os
import subprocess
from time import time

import pandas as pd

import database as db
from sqlalchemy.orm import load_only, selectinload
from util import ANNOTATED_FILE, HEURISTICS_DIR, REPOS_DIR, red, green, yellow, CODE_DEBUG

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


def print_results(status):
    print('\nRESULTS')
    for k, v in status.items():
        print(f'{k}: {v}')
    print()


def commit():
    print('Committing changes...')
    db.commit()


def get_or_create_projects():
    projects = []

    # Loading projects from the Excel.
    df = pd.read_excel(ANNOTATED_FILE, keep_default_na=False)
    df = df[df.discardReason == ''].reset_index(drop=True)
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
            db.create(db.Version, sha1=p.stdout.decode().strip(), isLast=True, project=project)
            projects.append(project)
            print(green('ok.'))
            status['Added'] += 1
        except NotADirectoryError:
            print(red('repository not found.'))
            status['Repository not found'] += 1
        except subprocess.CalledProcessError as ex:
            print(red('Git error.'))
            status['Git error'] += 1
            if CODE_DEBUG:
                print(ex.stderr)

    status['Total'] = len(projects)
    print_results(status)
    commit()
    return sorted(projects, key=lambda item: (item.owner.lower(), item.name.lower()))


def get_or_create_labels():
    labels = []

    # Loading heuristics from the file system.
    labels_fs = dict()
    for label_type in os.scandir(HEURISTICS_DIR):
        if label_type.is_dir() and not label_type.name.startswith('.'):
            for label in os.scandir(label_type.path):
                if label.is_file() and not label.name.startswith('.'):
                    with open(label.path) as file:
                        pattern = file.read()
                    label_fs = {
                        'name': os.path.splitext(label.name)[0],
                        'type': label_type.name,
                        'pattern': pattern,
                    }
                    labels_fs[(label_fs['type'], label_fs['name'])] = label_fs

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
    commit()
    return sorted(labels, key=lambda item: (item.type.lower(), item.name.lower()))


def index_executions(labels):
    executions = dict()

    for label in labels:
        heuristic = label.heuristic
        for execution in heuristic.executions:
            executions[(heuristic, execution.version)] = execution

    return executions


def main():
    db.connect()

    print(f'Loading projects from {ANNOTATED_FILE}.')
    projects = get_or_create_projects()

    print(f'\nLoading heuristics from {HEURISTICS_DIR}.')
    labels = get_or_create_labels()

    # Indexing executions by label heuristic and project version.
    executions = index_executions(labels)

    status = {
        'Success': 0,
        'Skipped': 0,
        'Repository not found': 0,
        'Git error': 0,
        'Total': len(labels) * len(projects)
    }

    print(f'\nProcessing {len(labels)} heuristics over {len(projects)} projects.')
    for i, label in enumerate(labels):
        heuristic = label.heuristic
        for j, project in enumerate(projects):
            version = project.versions[0]  # TODO: fix this to deal with multiple versions

            # Print progress information
            progress = '{:.2%}'.format((i * len(projects) + (j + 1)) / status['Total'])
            print(f'[{progress}] Searching for {label.name} in {project.owner}/{project.name}:', end=' ')

            # Try to get a previous execution
            execution = executions.get((heuristic, version), None)
            if not execution:
                try:
                    os.chdir(REPOS_DIR + os.sep + project.owner + os.sep + project.name)
                    cmd = GREP_COMMAND + [HEURISTICS_DIR + os.sep + label.type + os.sep + label.name + '.txt']
                    p = subprocess.run(cmd, capture_output=True)
                    if p.stderr:
                        raise subprocess.CalledProcessError(p.returncode, cmd, p.stdout, p.stderr)
                    db.create(db.Execution, output=p.stdout.decode(errors='replace').replace('\x00', '\uFFFD'),
                              version=version, heuristic=heuristic, isValidated=False, isAccepted=False)
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
            else:  # Execution already exists
                print(yellow('already done.'))
                status['Skipped'] += 1
        commit()

    print_results(status)
    db.close()


if __name__ == "__main__":
    main()
