
from sqlalchemy.orm import load_only, selectinload
from util import RESOURCE_DIR, COUNT_FILE_IMP, REPOS_DIR, COUNT_FILE_SQL, COUNT_FILE_IMP_RATE

import pandas as pd
import os
import subprocess
import database as db

#gera arquivos .xlsx contendo os resultados das pesquisas, no caso, só retornar se possui ou näo o banco. Esse retorno é marcado por 1 ou pelo nome do banco.

def create_characterization(type_characterization, names, nameFile):
    db.connect()
    all_results = dict()
    index_projects = []
    index_domains = []
    results_Label = []
    projects_db = db.query(db.Project).options(load_only('id', 'owner', 'name'), selectinload(db.Project.versions).load_only('id')).all()
    labels_db = db.query(db.Label).options(selectinload(db.Label.heuristic).options(selectinload(db.Heuristic.executions).defer('output').defer('user'))).filter(db.Label.type == type_characterization).all()
    print("Search results in execution for label and project.")
    print("File to be generated: ", type_characterization)
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
                .filter(db.Heuristic.label_id == label.id).first()
            if(execution is None):
                if names:
                    results_Label.append("")
                else:
                    results_Label.append(0)
            else:
                if(execution.output != ''):
                    if names:
                        results_Label.append(label.name)
                    else:
                        results_Label.append(1)
                else:
                    if names:
                        results_Label.append("")
                    else:
                        results_Label.append(0)
                        
        if(i==0):
            all_results["Projects"] = index_projects
            all_results["Domains"] = index_domains
        all_results[label.name] = results_Label.copy()
        results_Label.clear()
    save(all_results, nameFile)

#conta quantos arquivos foram retornados para o uso de frameworks ORM 
def create_count_implementation(rate):
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
                if(rate == True): 
                    results_Label.append(round(sum/int(count_number_files_project(project))), 4)
                else:
                    results_Label.append(sum)
        if(i==0):
            all_results["Projects"] = index_projects
            all_results["Domains"] = index_domains
            all_results["Total"] = int(count_number_files_project(project))
        all_results[label.name] = results_Label.copy()
        results_Label.clear()
    if(rate == True):    
        save_local(all_results, COUNT_FILE_IMP_RATE)
    else:
        save_local(all_results, COUNT_FILE_IMP)

#conta quantos arquivos foram retornados para o uso de SQL e Builder 
def create_count_sql():
    db.connect()
    all_results = dict()
    index_projects = []
    index_domains = []
    results_Label = []
    projects_db = db.query(db.Project).options(load_only('id', 'owner', 'name'), selectinload(db.Project.versions).load_only('id')).all()
    labels_db = db.query(db.Label).options(selectinload(db.Label.heuristic).options(selectinload(db.Heuristic.executions).defer('output').defer('user'))).filter(db.Label.type == 'query').all()
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
    save_local(all_results, COUNT_FILE_SQL)
    
def save(all_results, type_characterization):
    print("\n")
    print(f'Saving all results {type_characterization} to {RESOURCE_DIR}...', end=' ')
    df = pd.DataFrame(all_results)
    CHARACTERIZATION_FILE_PATH = RESOURCE_DIR + os.sep + type_characterization+ '.xlsx'
    df.to_excel(CHARACTERIZATION_FILE_PATH, index=False)
    print('Done!')

def save_local(all_results, LocalToSave):
    print("\n")
    print(f'Saving all results to {LocalToSave}...', end=' ')
    df = pd.DataFrame(all_results)
    df.to_excel(LocalToSave, index=False)
    print('Done!')

def count_number_files_project(project):
    try:
        os.chdir(REPOS_DIR + os.sep + project.owner + os.sep + project.name)
        p = subprocess.run("git ls-files | wc -l", capture_output=True, text=True, shell=True)
        return p.stdout
    except NotADirectoryError:
        return 0
    except subprocess.CalledProcessError as ex:
        return 0

def main():
    create_characterization('database', False, 'database')
    create_characterization('implementation', False, 'implementation')
    create_characterization('implementation', True, 'implementation_names')
    create_characterization('query', False, 'query')
    create_count_sql()
    create_count_implementation(True)
    create_count_implementation(False)
    

if __name__ == "__main__":
    main()