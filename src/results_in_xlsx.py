from sqlalchemy.orm import load_only, selectinload
from util import RESOURCE_DIR, COUNT_FILE_IMP, REPOS_DIR, COUNT_FILE_SQL, COUNT_FILE_IMP_RATE, USAGE_FAN_IN_FILE, VULNERABILITY_LABELS

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

#conta quantos arquivos foram retornados para o uso de ORM 
def create_count_implementation(rate):
    db.connect()
    all_results = dict()
    index_projects = []
    index_domains = []
    results_Label = []
    list_total_projects=[]
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
                results_Label.append("")
            else:
                output = execution.output.split('\n\n')
                sum = 0
                for k in output:
                    sum = sum +1
                if(rate == True):
                    value = sum/int(count_number_files_project(project))*100
                    results_Label.append(value)
                else:
                    results_Label.append(sum)
            if(len(list_total_projects)< len(projects_db)):
                list_total_projects.append(count_number_files_project(project))
        if(i==0):
            all_results["Projects"] = index_projects
            all_results["Domains"] = index_domains
        all_results[label.name] = results_Label.copy()
        results_Label.clear()
    if(rate == True):    
        save_local(all_results, COUNT_FILE_IMP_RATE)
    else:
        #print(list_total_projects)
        all_results["Number total of files"] = list_total_projects
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
                results_Label.append("")
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

def create_characterization_and_database(type_characterization, nameFile):
    db.connect()
    index_projects = []
    index_domains = []
    all_results = []
    projects_db = db.query(db.Project).options(load_only('id', 'owner', 'name'), selectinload(db.Project.versions).load_only('id')).all()
    labels_db_implementation = db.query(db.Label).options(selectinload(db.Label.heuristic).options(selectinload(db.Heuristic.executions).defer('output').defer('user'))).filter(db.Label.type == type_characterization[0]).all()
    labels_db_classes = db.query(db.Label).options(selectinload(db.Label.heuristic).options(selectinload(db.Heuristic.executions).defer('output').defer('user'))).filter(db.Label.type == type_characterization[1]).all()
    print("Search results in execution for label and project.")
    print("File to be generated: ", type_characterization)
    for j, project in enumerate(projects_db):
        status = {
        'Test': 0,
        'Code': 0,
        'None' : 0,
        'Not Java': 0, 
        'Total Project': 0
    }
        status['Project'] = project.name
        for i,label in enumerate(labels_db_implementation):
            if(len(index_projects)< len(projects_db)):
                index_projects.append(project.name)
                index_domains.append(project.domain)
            # Search results in execution for label and project
            execution = db.query(db.Execution) \
                .join(db.Execution.version) \
                .join(db.Execution.heuristic) \
                .filter(db.Version.project_id == project.id) \
                .filter(db.Heuristic.label_id == label.id).first()
            if(execution is None) :
                status['None'] += 1
            else:
                if(execution.output != ''):
                    output = execution.output.split('\n\n')
                    for k in output:                    
                        file_path = REPOS_DIR + os.sep + project.owner + os.sep + project.name + os.sep + k.split('\n', 1)[0]
                        file_path = file_path.replace('\x1b[m', '')
                        if file_path.endswith('.java'):
                            if "/src/test"in file_path:
                                status['Test'] += 1   
                            else:
                                status['Code'] += 1   
                        else:
                            status['Not Java'] += 1          

        for i,label in enumerate(labels_db_classes):
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
                status['None'] += 1
            else:
                if(execution.output != ''):
                    output = execution.output.split('\n\n')
                    for k in output:                    
                        file_path = REPOS_DIR + os.sep + project.owner + os.sep + project.name + os.sep + k.split('\n', 1)[0]
                        file_path = file_path.replace('\x1b[m', '')
                        if file_path.endswith('.java'):
                            if "src/test"in file_path:
                                status['Test'] += 1   
                            else:
                                status['Code'] += 1   
                        else:
                            status['Not Java'] += 1 
        status['Total Project'] = count_number_files_project(project)                    
        all_results.append(status.copy())
        status.clear()
    
    save(all_results, nameFile)

#conta os resultados dos aquivos de primeiro e segundo nível, separando por categoria
def create_count_dbCode_Dependencies():
    db.connect()
    list_status_dbCode = []
    index_projects = []
    results_Label = []
    status_dbCode = dict()
    projects_db = db.query(db.Project).options(load_only('id', 'owner', 'name'), selectinload(db.Project.versions).load_only('id')).all()
    labels_db = db.query(db.Label).options(selectinload(db.Label.heuristic).options(selectinload(db.Heuristic.executions).defer('output').defer('user'))).filter(db.Label.type == 'implementation').all()
    print("Search results in execution for label and project.")
    for i, project in enumerate(projects_db):
        status_dbCode = {
        'Project': project.name,
        'DB-Code Test': 0,
        'DB-Code Java': 0,
        'DB-Code XML': 0,
        'DB-Code Not Java/XML' : 0,
        'None': 0, 
        'Dependencies Test': 0,
        'Dependencies Code': 0,
        'Dependencies XML': 0,
        'Dependencies Not Java/XML': 0,
        'Total Project' : 0,
        'Total DB' : 0
    }   #busca as labels de banco labels de Bd - primeiro nível
        for j, label in enumerate(labels_db):
            if(len(index_projects)< len(projects_db)):
                index_projects.append(project.name)
            # Search results in execution for label and project
            execution = db.query(db.Execution) \
                .join(db.Execution.version) \
                .join(db.Execution.heuristic) \
                .filter(db.Version.project_id == project.id) \
                .filter(db.Heuristic.label_id == label.id) \
                .filter(db.Execution.output != '').first()
            if(execution is None):
                status_dbCode['None'] += 1 
            else:
                output = execution.output.split('\n\n')
                for k in output:
                    file_path = REPOS_DIR + os.sep + project.owner + os.sep + project.name + os.sep + k.split('\n', 1)[0]
                    file_path = file_path.replace('\x1b[m', '')
                    if file_path.endswith('.java'):
                        if "src/test" in file_path:
                            status_dbCode['DB-Code Test'] += 1   
                        else:
                            status_dbCode['DB-Code Java'] += 1   
                    else:
                        if file_path.endswith('.xml'):
                            status_dbCode['DB-Code XML'] += 1 
                        else:
                            status_dbCode['DB-Code Not Java/XML'] += 1 
                status_dbCode['Total DB'] = len(output)

        #busca as labels de banco labels de dependencia - segundo nível
        label_classes_db = db.query(db.Label).options(selectinload(db.Label.heuristic).
                                                           options(selectinload(db.Heuristic.executions)
                                                                   .defer('output').defer('user'))).filter(db.Label.name == project.owner+"."+project.name).first()
        if (label_classes_db is None): 
            print(project.owner+"."+project.name)
            status_dbCode['Dependencies Test'] = 0
            status_dbCode['Dependencies Code'] = 0
            status_dbCode['Dependencies XML'] = 0 
            status_dbCode['Dependencies Not Java/XML'] = 0
            status_dbCode['Total DB'] = 0 
            status_dbCode['Total Project'] = 0 
        else:
            execution = db.query(db.Execution) \
                .join(db.Execution.version) \
                .join(db.Execution.heuristic) \
                .filter(db.Version.project_id == project.id) \
                .filter(db.Heuristic.label_id == label_classes_db.id) \
                .filter(db.Execution.output != '').first()

            if(execution is None):
                results_Label.append("")
            else:
                output = execution.output.split('\n\n')
                for k in output:
                    file_path = REPOS_DIR + os.sep + project.owner + os.sep + project.name + os.sep + k.split('\n', 1)[0]
                    file_path = file_path.replace('\x1b[m', '')
                    if file_path.endswith('.java'):
                        if "src/test" in file_path:
                            status_dbCode['Dependencies Test'] += 1   
                        else:
                            status_dbCode['Dependencies Code'] += 1   
                    else:
                        if file_path.endswith('.xml'):
                            status_dbCode['Dependencies XML'] += 1 
                        else:
                            status_dbCode['Dependencies Not Java/XML'] += 1 
                else:
                    results_Label.append(status_dbCode)
            status_dbCode['Total DB'] += len(output)
        
        status_dbCode['Total Project']= int(count_number_files_project(project))
        list_status_dbCode.append(calculate_rate(project, status_dbCode))
       
    save_local_pd(list_status_dbCode, USAGE_FAN_IN_FILE)

def save_local_pd( dicResults, LocalToSave):
    print("\n")
    print(f'Saving all results to {LocalToSave}...', end=' ')
    df = pd.DataFrame(dicResults)
    df.to_excel(LocalToSave, index=False)
    print('Done!')

def calculate_rate(project, status_dbCode):
    status_dbCode_rate = {
        'Projects': project.name,
        'N DB-Code Test': int(status_dbCode['DB-Code Test']) if int(status_dbCode['DB-Code Test'])>0 else "",
        'N DB-Code Java': int(status_dbCode['DB-Code Java']) if int(status_dbCode['DB-Code Java'])>0 else "",
        'N DB-Code XML': int(status_dbCode['DB-Code XML']) if int(status_dbCode['DB-Code XML'])>0 else "",
        'N DB-Code Not Java/XML' : int(status_dbCode['DB-Code Not Java/XML']) if int(status_dbCode['DB-Code Not Java/XML']) >0 else "",
        'N Dependencies Test': int(status_dbCode['Dependencies Test']) if int(status_dbCode['Dependencies Test'])>0 else "",
        'N Dependencies Code': int(status_dbCode['Dependencies Code']) if int(status_dbCode['Dependencies Code'])>0 else "",
        'N Dependencies XML': int(status_dbCode['Dependencies XML']) if int(status_dbCode['Dependencies XML'])>0 else "",
        'N Dependencies Not Java/XML': int(status_dbCode['Dependencies XML']) if int(status_dbCode['Dependencies XML'])>0 else "",
        'N Total Project': int(status_dbCode['Total Project'])  if int(status_dbCode['Total Project'])>0 else "",
        'N Total DB': int(status_dbCode['Total DB'])  if int(status_dbCode['Total DB'])>0 else "",
        'DB-Code Test': int(status_dbCode['DB-Code Test'])/int(status_dbCode['Total Project'])*100  if int(status_dbCode['DB-Code Test'])/int(status_dbCode['Total Project'])*100>0 else "",
        'DB-Code Java': int(status_dbCode['DB-Code Java'])/int(status_dbCode['Total Project'])*100  if int(status_dbCode['DB-Code Java'])/int(status_dbCode['Total Project'])*100 >0 else "",
        'DB-Code XML': int(status_dbCode['DB-Code XML'])/int(status_dbCode['Total Project'])*100  if int(status_dbCode['DB-Code XML'])/int(status_dbCode['Total Project'])*100>0 else "",
        'Dependencies Test': int(status_dbCode['Dependencies Test'])/int(status_dbCode['Total Project'])*100  if int(status_dbCode['Dependencies Test'])/int(status_dbCode['Total Project'])*100>0 else "",
        'Dependencies Code': int(status_dbCode['Dependencies Code'])/int(status_dbCode['Total Project'])*100  if int(status_dbCode['Dependencies Code'])/int(status_dbCode['Total Project'])*100 >0 else "",
        'Dependencies XML': int(status_dbCode['Dependencies XML'])/int(status_dbCode['Total Project'])*100  if int(status_dbCode['Dependencies XML'])/int(status_dbCode['Total Project'])*100>0 else "", 
        'Total DB': int(status_dbCode['Total DB'])/int(status_dbCode['Total Project'])*100  if int(status_dbCode['Total DB'])/int(status_dbCode['Total Project'])*100>0 else ""
    }
    return status_dbCode_rate

def create_vulnerability_csv():
    results_Label = []
    db.connect()
    vulnerabilities_db = db.query(db.Vulnerability) \
                .join(db.Label) \
                .filter(db.Vulnerability.label_id == db.Label.id)
    for j, vulnerability in enumerate(vulnerabilities_db):
        status_dbCode = {
            'Name': vulnerability.name,
            'Description': vulnerability.description,
            'Year': vulnerability.year,
            'Label': vulnerability.label.name
        }

        results_Label.append(status_dbCode)
        
    save_local(results_Label, VULNERABILITY_LABELS)
    
def create_pomxml_characterization(type_characterization):
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
                print("None")
            if (execution.output == ''):
                results_Label.append(len(0)) 
            else:
                for output in execution.output:
                    pom = False
                    for k in output:                    
                        file_path = REPOS_DIR + os.sep + project.owner + os.sep + project.name + os.sep + k.split('\n', 1)[0]
                        file_path = file_path.replace('\x1b[m', '')
                        if file_path.endswith('pom.xml'):
                            pom = True
                            results_Label.append(len(output))
                    if(pom ==False):
                        results_Label.append(-1)
        else:
            print(" ")            
        if(i==0):
            all_results["Projects"] = index_projects
            all_results["Domains"] = index_domains
        all_results[label.name] = results_Label.copy()
        results_Label.clear()



    save()


def main():
    # create_characterization('database', False, 'database')
    # create_characterization('implementation', False, 'implementation')
    # create_characterization('implementation', True, 'implementation_names')
    # create_characterization('query', False, 'query')
    # create_count_sql()
    # create_count_implementation(True)
    # create_count_implementation(False)
    # list_type = ['implementation', 'classes']
    # create_characterization_and_database(list_type, 'number_of_files')
    # create_count_dbCode_Dependencies()
    #create_vulnerability_csv()
    create_pomxml_characterization('database')
    
if __name__ == "__main__":
    main()