import os
import subprocess
from datetime import datetime

from sqlalchemy.sql.expression import null

import database as db
from extract import (
    get_or_create_projects, index_executions, do_commit, print_results,
    get_or_create_labels,
    GREP_COMMAND, CHECKOUT_COMMAND
)
from sqlalchemy.orm import selectinload
from util import ANNOTATED_FILE_JAVA, REPOS_DIR, red, green, yellow, HEURISTICS_DIR_VULNERABILITIES

LOG_COMMAND = [
    'git',
    'log',
    '--',
    'pom.xml'
]

def list_commits_project(project):
    list_commits_project = []
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
                    if(len(commit_txt) == 4):
                        try:
                            date = commit_txt[3].split("   ")[1]
                        except :
                            date = null
                    else:
                        try:
                            date = commit_txt[2].split("   ")[1]
                        except :
                            date = null
                    if date != '':
                        try:
                            commitDate = datetime.strptime(date, '%c %z').date()
                        except :
                            date = null
                    list_commits_project.append(hashCommit)
                    version_db = db.query(db.Version).filter(db.Version.project_id==project.id).filter(db.Version.sha1 == hashCommit).first() 
                    if version_db is None and hashCommit != "":
                        db.create(db.Version, sha1=hashCommit, isLast=False, project=project, part_commit=m, date_commit=commitDate)
                        do_commit()
        except subprocess.TimeoutExpired:
                print(red('Git error.'))
    except NotADirectoryError:
            print(red('Repository not found.'))
    print('Lista de Commits finalizada')
    return list_commits_project

def main():

    db.connect()
    list_commit= []

    projects = get_or_create_projects(create_version=True)
    labels = get_or_create_labels(HEURISTICS_DIR_VULNERABILITIES, 'vulnerabilities')

    # Indexing executions by label heuristic and project version.
    executions = index_executions(labels)

    status = {
        'Success': 0,
        'Skipped': 0,
        'Iguais': 0,
        'Repository not found': 0,
        'Git error': 0,
        'Git timeout': 0
    }

    print(f'\nProcessing {len(labels)} heuristics over {len(projects)} projects commits.')
    for i, project in enumerate(projects):
        if (project is None ):
            continue
        list_commit = list_commits_project(project)
        try:
            os.chdir(REPOS_DIR + os.sep + project.owner + os.sep + project.name)
            print(f'\nProcessing {len(list_commit)} commits of {project.name} project.')
            for j, label in enumerate(labels):
                newOutput = ""
                for commit_txt in list_commit:
                    cmd = CHECKOUT_COMMAND + [commit_txt]
                    try:
                        p = subprocess.run(cmd, capture_output=True, timeout=360)
                        version_db = db.query(db.Version).filter(db.Version.project_id==project.id).filter(db.Version.sha1 == commit_txt).first() 
                        if(version_db is None):
                            continue
                        cmd = GREP_COMMAND + [HEURISTICS_DIR_VULNERABILITIES + os.sep + label.name + '.txt']
                        p = subprocess.run(cmd, capture_output=True, timeout=360)
                        if p.stderr:
                            raise subprocess.CalledProcessError(p.returncode, cmd, p.stdout, p.stderr)

                        if(p.stdout.decode(errors='replace').replace('\x00', '\uFFFD') == ''):
                            db.create(db.Execution, output=p.stdout.decode(errors='replace').replace('\x00', '\uFFFD'),
                              version_id=version_db.id, heuristic_id=label.id, isValidated=False, isAccepted=False)
                            do_commit()
                        elif(newOutput == ''):
                            newOutput=str(p.stdout.decode(errors='replace').replace('\x00', '\uFFFD'))
                            db.create(db.Execution, output=p.stdout.decode(errors='replace').replace('\x00', '\uFFFD'),
                              version_id=version_db.id, heuristic_id=label.id, isValidated=False, isAccepted=False)
                            do_commit()
                        else:
                            oldOutput = newOutput
                            newOutput=p.stdout.decode(errors='replace').replace('\x00', '\uFFFD')
                            if oldOutput == newOutput:
                                print("Iguais")
                                status['Iguais'] += 1
                            else:
                                db.create(db.Execution, output=p.stdout.decode(errors='replace').replace('\x00', '\uFFFD'),
                              version_id=version_db.id, heuristic_id=label.id, isValidated=False, isAccepted=False)
                                print(green('ok.'))
                                status['Success'] += 1
                                do_commit()
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
