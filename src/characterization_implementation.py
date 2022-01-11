
import os
import subprocess
from sqlalchemy.sql.elements import Null
from sqlalchemy.sql.expression import null
import database as db
from sqlalchemy.orm import load_only, selectinload

import pandas as pd
from extract import print_results
from util import COUNT_LINE_FILE_IMP, COUNT_FILE_IMP, REPOS_DIR, red, green, yellow
from sqlalchemy import func


def create_count_implementation():
    db.connect()
    all_results = dict()
    index_projects = []
    index_domains = []
    results_Label = []
    projects_db = db.query(db.Project).options(load_only('id', 'owner', 'name'), selectinload(db.Project.versions).load_only('id')).all()
    labels_db = db.query(db.Label).options(selectinload(db.Label.heuristic).options(selectinload(db.Heuristic.executions).defer('output').defer('user'))).filter(db.Label.type == 'implementation').all()
    print("Search results in execution for label and project.")
    for i,label in enumerate(labels_db):
        for j, project in enumerate(projects_db):
            if(len(index_projects)< len(projects_db)):
                index_projects.append(project.name)
                index_domains.append(project.domain)
            # Search results in execution for label and project
            execution = db.query(db.Execution) \
                .join(db.Execution.version) \
                .join(db.Execution.heuristic) \
                .filter(db.Version.project_id == project.id) \
                .filter(db.Heuristic.label_id == label.id) \
                .filter(db.Execution.output != '').first()
            if(execution is None):
                results_Label.append(0)
            else:
                output = execution.output.split('\n\n')
                sum = 0
                for k in output:
                    sum = sum +1
                results_Label.append(sum)
        if(i==0):
            all_results["Projects"] = index_projects
            all_results["Domains"] = index_domains
        all_results[label.name] = results_Label.copy()
        results_Label.clear()
    save(all_results, COUNT_FILE_IMP)

def create_list_implementation():
    db.connect()
    full_string_result = dict()
    index_projects = []
    index_domains = []
    list_results = []
    list_files = [] 
    list_files_duplicate = [] 
    status = {
        'Opened': 0,
        'Repository not found': 0,
        'Duplicated': 0,
        'Total': 0
    }

    projects_db = db.query(db.Project).options(load_only('id', 'owner', 'name'), selectinload(db.Project.versions).load_only('id')).all()
    labels_db = db.query(db.Label).options(selectinload(db.Label.heuristic).options(selectinload(db.Heuristic.executions).defer('output').defer('user'))).filter(db.Label.type == 'implementation').all()
    print("Search results in execution for label and project.")

    for i,label in enumerate(labels_db):
        for j, project in enumerate(projects_db):
            if(len(index_projects)< len(projects_db)):
                index_projects.append(project.name)
                index_domains.append(project.domain)
            # Search results in execution for label and project
            execution = db.query(db.Execution) \
                .join(db.Execution.version) \
                .join(db.Execution.heuristic) \
                .filter(db.Version.project_id == project.id) \
                .filter(db.Heuristic.label_id == label.id) \
                .filter(db.Execution.output != '').first()
            if(execution is None):
                print("Execution is None")
            else:
                output = execution.output.split('\n\n')
                for k in output:
                    file_path = project.owner + os.sep + project.name + os.sep + k.split('\n', 1)[0]
                    #Valida se o elemento está na lista
                    if not list_files:
                        list_files.append(file_path)
                    else:
                        if file_path in list_files:
                            list_files_duplicate.append(file_path)
                            print(yellow('Duplicated.'))
                            status['Duplicated'] += 1
                            full_string_result = {"file": file_path, "lines" : 0, "label": label.name}
                            list_results.append(full_string_result)
                        else:
                            list_files.append(file_path)
                            #progress = '{:.2%}'.format(status['Opened'] / status['Files'])
                            print('Counting the number of lines.', end=' ')
                            try:
                                open_file = open(REPOS_DIR + os.sep + file_path)
                                number_lines_open_file = len(open_file.readlines())
                                open_file.close()
                                print(green('ok.'))
                                status['Opened'] += 1
                                full_string_result = {"file": [file_path], "lines" : [number_lines_open_file], "label": [label.name]}
                                list_results.append(full_string_result) 
                            except NotADirectoryError:
                                print(red('Repository not found.'))
                                status['Repository not found'] += 1
    status['Total'] = status['Opened'] + status['Duplicated']
    print_results(status)
    print_list_files(list_results)
    #save(full_string_result, COUNT_LINE_FILE_IMP)

def save(all_results, file):
    print(f'Saving all results to {file}...', end=' ')
    df = pd.DataFrame(all_results)
    df.to_excel(file, index=False)
    print('Done!')

def print_list_files(list_files):
    for k in list_files:
        print(k, "\n")

    
def main():
    create_count_implementation()
    #create_list_implementation()

if __name__ == "__main__":
    main()