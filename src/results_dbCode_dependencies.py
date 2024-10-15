
import database as db
import os
import pandas as pd
from util import  REPOS_DIR, HEURISTICS_DIR_FIRST_LEVEL, HEURISTICS_DIR_SECOND_LEVEL, USAGE_FAN_IN_FILE
from create_file_dbCode import search_labels, search_projects, create_heuristic_class, print_results, remove_duplicate_files
from results_in_xlsx import count_number_files_project

#conta os resultados obtidos através do dbCode e suas dependencias para cada projeto
def create_list_fanin_second_level():
    index_projects = []
    index_domains = []
    list_java_files = [] 
    status = {
        'Opened': 0,
        'Not .Java': 0,
        'Duplicated': 0,
        'None' : 0,
        'Total': 0
    }

    labels_db = search_labels('classes')
    projects_db = search_projects()
    print("Search SECOND-LEVEL results for label and project.")

    for i,project in enumerate(projects_db):
        for j, label in enumerate(labels_db):
            if(len(index_projects)< len(projects_db)):
                index_projects.append(project.name)
                index_domains.append(project.domain)
            execution = (
                db.query(db.Execution)
                .join(db.Execution.version)
                .join(db.Execution.heuristic)
                .filter(db.Version.project_id == project.id)
                .filter(db.Heuristic.label_id == label.id)
                .filter(db.Execution.output != '').first()
            )
            if(execution is None):
                status['None'] += 1
            else:
                output = execution.output.split('\n\n')
                for k in output:                    
                    file_path = REPOS_DIR + os.sep + project.owner + os.sep + project.name + os.sep + k.split('\n', 1)[0]
                    file_path = file_path.replace('\x1b[m', '')
                    #print(file_path)
                    if file_path.endswith('.java'):
                        #print('is Java')
                        list_java_files.append(create_heuristic_class(file_path))                        
                        status['Opened'] += 1
                    else:
                        status['Not .Java'] += 1
        #print(list_java_files)
        save_txt(list_java_files, project.owner+"."+project.name)
        list_java_files.clear()                

    status['Duplicated'] = len(list_java_files)                        
    list_java_files = list(set(list_java_files))
    status['Duplicated'] = status['Duplicated'] - len(list_java_files)
    status['Total'] = status['Opened'] + status['Not .Java']

    print_results(status)

def create_separate_file_level():
    results = dict()
    all_results = []
    first_level=[]
    second_level = []
    second_level_pure=[]

    print("Filtering results.")
    projects_db = search_projects()

    for i, project in enumerate(projects_db):
        status = {
        'DB-Code(Java) Number': 0,
        'DB-Code(Java)': 0,
        'DB-Code(Java - Test)': 0,
        'DB-Code(XML) Number': 0,
        'DB-Code(XML)': 0,
        'Dependencies Number': 0,
        'Dependencies': 0,
        'Error-first':0,
        'Error-second':0,
        'Total': 0,
        'Total-Project': 0
        }
        file_path = HEURISTICS_DIR_FIRST_LEVEL + os.sep + project.owner + "." + project.name + ".txt"
        try:
            with open(file_path) as file:
                first_level = file.read().splitlines()
        except FileNotFoundError:
            status['Error-first'] += 1
            print("The 'HEURISTICS_DIR_FIRST_LEVEL' directory does not exist")

        file_path = HEURISTICS_DIR_SECOND_LEVEL + os.sep + project.owner + "." + project.name + ".txt"
        try:
            with open(file_path) as file:
                second_level = file.read().splitlines()
        except FileNotFoundError:
            status['Error-second'] += 1
            print("The 'HEURISTICS_DIR_SECOND_LEVEL' directory does not exist")
        for i in second_level:
            if i in first_level:
                status['DB-Code(Java)'] += 1
            else:
                second_level_pure.append(i)
                status['Dependencies'] += 1

        save_txt(second_level_pure, project.owner+"."+project.name)

        total_project = int(count_number_files_project(project))
        results["Projects"] = project.name
        results["DB-Code(Java) Number"] = status['DB-Code(Java)']
        results["DB-Code(Java)"] = (int(status['DB-Code(Java)'])/total_project)*100
        results["DB-Code(XML) Number"] = count_file_xml(project)
        results["DB-Code(XML)"] = (count_file_xml(project)/total_project)*100
        results["Dependencies Number"] = status['Dependencies']
        results["Dependencies"] = (int(status['Dependencies'])/total_project)*100
        results["Total-DB Files Number"] = results['DB-Code(Java) Number'] + results["DB-Code(XML) Number"] + results['Dependencies Number']
        results["Total-Project Files"] = total_project
        results["Total-DB Files"] = (results["Total-DB Files Number"] / int(results["Total-Project Files"]))*100
        results['Error-second'] = status['Error-second']
        results['Error-first'] = status['Error-first']
        all_results.append(results.copy())

        status.clear()
        second_level_pure.clear()
        results.clear()
    save(all_results)

def count_file_xml(project):
    number_of_xml_files = 0 
    none = 0

    execution = (
        db.query(db.Execution)
        .join(db.Execution.version)
        .join(db.Execution.heuristic)
        .filter(db.Version.project_id == project.id)
        .filter(db.Execution.output != '').first()
    )
    if(execution is None):
            none += 1
    else:
        output = execution.output.split('\n\n')
        for k in output:                    
            file_path = REPOS_DIR + os.sep + project.owner + os.sep + project.name + os.sep + k.split('\n', 1)[0]
            file_path = file_path.replace('\x1b[m', '')
            #print(file_path)
            if file_path.endswith('.xml'):
                number_of_xml_files += 1
            else:
                continue

    return number_of_xml_files
    
def save(all_results):
    print(f'Saving all results to {USAGE_FAN_IN_FILE}...', end=' ')
    df = pd.DataFrame(all_results)
    df.to_excel(USAGE_FAN_IN_FILE, index=False)
    print('Done!')

def save_txt(list_files, project):
    print("Saving file " +project+".txt")
    os.chdir(HEURISTICS_DIR_SECOND_LEVEL)
    print(os.getcwd())
    print(project)
    #new_list_files = remove_duplicate_files(list_files)
    try:
        TextFile = open(project+'.txt', 'w+')
        for k in list_files:
            TextFile.write(k +"\n")
        TextFile.close()    
    except FileNotFoundError:
        print("The directory does not exist")                       
    
def main():
    create_list_fanin_second_level()
    #create_separate_file_level()

if __name__ == "__main__":
    main()