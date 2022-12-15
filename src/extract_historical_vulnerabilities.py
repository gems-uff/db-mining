import os
import subprocess
from sys import version
from time import time

import pandas as pd
from sqlalchemy.sql.expression import null

import database as db
from extract import get_or_create_projects, index_executions, commit, print_results, REVPARSE_COMMAND
from sqlalchemy.orm import selectinload, load_only
from util import ANNOTATED_FILE_JAVA, REPOS_DIR, red, green, yellow, HEURISTICS_DIR_VULNERABILITIES
from pickle import FALSE, TRUE

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

LOG_COMMAND = [
    'git',
    'log',
    '--',
    'pom.xml'
]

CHECKCOUT_COMMAND = [
    'git',
    'checkout'
]

def get_or_create_labels():
    labels = []

    # Loading heuristics from the file system.
    labels_fs = dict()
    for label in os.scandir(HEURISTICS_DIR_VULNERABILITIES):
        if label.is_file() and not label.name.startswith('.'):
            with open(label.path) as file:
                pattern = file.read()
                label_fs = {
                    'name': os.path.splitext(label.name)[0],
                    'type': 'vulnerabilities',
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

                        #db.delete(execution)
                        count += 1
                print(green(f'heuristic updated ({count} executions removed).'))
                status['Updated'] += 1
            else:
                print(yellow('already done.'))
        else:
            #db.delete(label)
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

def list_commits_project(project):
    list_commits_project = []
    list_date_commits = [] 
    try:
        os.chdir(REPOS_DIR + os.sep + project.owner + os.sep + project.name)
        try:
            p = subprocess.run(LOG_COMMAND, capture_output=True, timeout=360)
            output = p.stdout.decode(errors='replace').replace('\x00', '\uFFFD')
            logCommit = output.split('\n\n')
            for m, k in enumerate(logCommit):
                if "commit" in k:
                    commit_txt = k.split('\n')
                    hashCommit = commit_txt[0].split(" ")[1]
                    commitDate = commit_txt[2].split("   ")[1] #criar um método que manipula a data
                    list_commits_project.append(hashCommit)
                    version_db = db.query(db.Version).filter(db.Version.project_id==project.id).filter(db.Version.sha1 == hashCommit).first() 
                    if version_db is None and hashCommit != "":
                        db.create(db.Version, sha1=hashCommit, isLast=False, project=project, part_commit=m, date_commit=commitDate)
                        commit()          
        except subprocess.TimeoutExpired:
                print(red('Git error.'))
    except NotADirectoryError:
            print(red('Repository not found.')) 
    return list_commits_project

def main():

    db.connect()
    list_commit= []

    print(f'Loading projects from {ANNOTATED_FILE_JAVA}.')
    projects = get_or_create_projects()

    print(f'\nLoading heuristics from {HEURISTICS_DIR_VULNERABILITIES}.')
    labels = get_or_create_labels()

    # Indexing executions by label heuristic and project version.
    executions = index_executions(labels)

    status = {
        'Success': 0,
        'Skipped': 0,
        'Repository not found': 0,
        'Git error': 0,
        'Git timeout': 0,
        'Total': len(labels) * len(projects)
    }
    
    print(f'\nProcessing {len(labels)} heuristics over {len(projects)} projects commits.')
    for i, project in enumerate(projects):
        if (project is None ):
            continue
        list_commit = list_commits_project(project)
        try: 
            os.chdir(REPOS_DIR + os.sep + project.owner + os.sep + project.name)
            for commit_txt in list_commit:
                cmd = CHECKCOUT_COMMAND + [commit_txt]
                try:
                    p = subprocess.run(cmd, capture_output=True, timeout=360)
                    for j, label in enumerate(labels):
                        version_db = db.query(db.Version).filter(db.Version.project_id==project.id).filter(db.Version.sha1 == commit_txt).first() 
    
                        cmd = GREP_COMMAND + [HEURISTICS_DIR_VULNERABILITIES + os.sep + label.name + '.txt']
                        p = subprocess.run(cmd, capture_output=True, timeout=360)
                        if p.stderr:
                            raise subprocess.CalledProcessError(p.returncode, cmd, p.stdout, p.stderr)

                        db.create(db.Execution, output=p.stdout.decode(errors='replace').replace('\x00', '\uFFFD'),
                              version_id=version_db.id, heuristic_id=label.id, isValidated=False, isAccepted=False)
                   #realizar a busca para as strings              
                    print(green('ok.'))
                    status['Success'] += 1
                    commit()
                except subprocess.TimeoutExpired:
                    print(red('Git error.'))
                    status['Git error'] += 1
                except subprocess.CalledProcessError as ex:
                    print(red('Git error.'))
                    status['Git error'] += 1
        except NotADirectoryError:
            print(red('repository not found.'))
            status['Repository not found'] += 1
    
    print_results(status)
    db.close()


if __name__ == "__main__":
    main()
