
from distutils.text_file import TextFile
from hashlib import new
import os
from pickle import TRUE
import subprocess
from sqlalchemy.sql.elements import Null
from sqlalchemy.sql.expression import null
import database as db
from sqlalchemy.orm import load_only, selectinload

import pandas as pd
from extract import print_results
from util import COUNT_FILE_IMP, REPOS_DIR, HEURISTICS_DIR_FIRST_LEVEL, red, green, yellow
from sqlalchemy import func
from pathlib import Path

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
                results_Label.append(sum/int(count_number_files_project(project)))
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

def create_list_fanin():
    index_projects = []
    index_domains = []
    list_java_files = []
    list_java_files_duplicates = [] 
    status = {
        'Opened': 0,
        'Not .Java': 0,
        'Duplicated': 0,
        'None': 0,
        'Total': 0
    }

    labels_db = search_labels('implementation')
    projects_db = search_projects()
    print("Search results in execution for label and project.")

    for i,project in enumerate(projects_db):
        for j, label in enumerate(labels_db):
            if(len(index_projects)< len(projects_db)):
                index_projects.append(project.name)
                index_domains.append(project.domain)
            execution = db.query(db.Execution) \
                .join(db.Execution.version) \
                .join(db.Execution.heuristic) \
                .filter(db.Version.project_id == project.id) \
                .filter(db.Heuristic.label_id == label.id) \
                .filter(db.Execution.output != '').first()            
            if(execution is None):
                status['None'] += 1
            else:
                output = execution.output.split('\n\n')
                for k in output:
                    file_path = REPOS_DIR + os.sep + project.owner + os.sep + project.name + os.sep + k.split('\n', 1)[0]
                    #file_path = strip_ansi("\x1b[m"+file_path+"\x1b[m")
                    file_path = file_path.replace('\x1b[m', '')
                    if file_path.endswith('.java'):
                        if not list_java_files:
                            list_java_files.append(file_path)
                        else:
                            if file_path in list_java_files:
                                list_java_files_duplicates.append(file_path)
                                status['Duplicated'] += 1
                            else:
                                list_java_files.append(file_path)
                                status['Opened'] += 1
                    else:
                        status['Not .Java'] += 1

        if len(list_java_files)>0:
            save_txt(list_java_files, project.owner+"."+project.name)
        list_java_files.clear()                

    status['Duplicated'] = len(list_java_files_duplicates)                        
    list_java_files = list(set(list_java_files))
    status['Total'] = status['Opened'] + status['Not .Java']

    print_results(status)

def save(all_results, file):
    print(f'Saving all results to {file}...', end=' ')
    df = pd.DataFrame(all_results)
    df.to_excel(file, index=False)
    print('Done!')

def print_list_files(list_files):
    for k in list_files:
        print(k, "\n")

def save_txt(list_files, project):
    print("Saving file " +project+".txt")
    os.chdir(HEURISTICS_DIR_FIRST_LEVEL)
    new_list_files = remove_duplicate_files(list_files)
    try:
        TextFile = open(project+'.txt', 'w+')
        for k in new_list_files:
            TextFile.write(k +"\n")
        TextFile.close()    
    except FileNotFoundError:
        print("The 'docs' directory does not exist")
        #Path("/my/directory").mkdir(parents=True, exist_ok=True)
    
def find_packege(file_path):
    try:
        read_obj = open(file_path)
        for line in read_obj:
            if 'package' in line:
                package = line.replace(";", "")
                return package.split(" ")[-1]
    except FileNotFoundError:
        print(red('File not found.'))
    
def main():
    create_count_implementation()
    create_list_fanin()

def search_projects():
    db.connect()
    projects_db = db.query(db.Project).options(load_only('id', 'owner', 'name'), selectinload(db.Project.versions).load_only('id')).all()
    return projects_db

def search_labels(labelType):
    db.connect()
    labels_db = db.query(db.Label).options(selectinload(db.Label.heuristic).options(selectinload(db.Heuristic.executions).defer('output').defer('user'))).filter(db.Label.type == labelType).all()
    return labels_db

def create_heuristic_class(file_path):
    file_name = file_path.split('/')[-1]
    heuristic_file = "[^a-zA-Z|^\/\"\_#|0-9]" + file_name.split('.')[0] + "[^a-zA-Z|^\/\"\_#|0-9]" #[^a-zA-Z|^\/"\_#|0-9]
    return heuristic_file

def remove_duplicate_files(list_files):
    new_list_files = []
    for file in list_files:
        file_heuristic = create_heuristic_class(file)
        if not new_list_files:
            new_list_files.append(file_heuristic)
        else:
            if file_heuristic not in new_list_files:
                new_list_files.append(file_heuristic)
                
    return new_list_files

def count_number_files_project(project):
    try:
        os.chdir(REPOS_DIR + os.sep + project.owner + os.sep + project.name)
        p = subprocess.run("git ls-files | wc -l", capture_output=True, text=True, shell=True)
        return p.stdout
    except NotADirectoryError:
        return 0
    except subprocess.CalledProcessError as ex:
        return 0
    
    
if __name__ == "__main__":
    main()