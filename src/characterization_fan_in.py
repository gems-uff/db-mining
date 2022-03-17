
import database as db
import os
from util import  REPOS_DIR, HEURISTICS_DIR_FIRST_LEVEL, HEURISTICS_DIR_SECOND_LEVEL, red, green, yellow
from characterization_implementation import search_labels, search_projects, create_package_heuristic_import, save_txt, print_results


def create_list_fanin_second_level():
    index_projects = []
    index_domains = []
    list_java_files = [] 
    status = {
        'Opened': 0,
        'Not .Java': 0,
        'Duplicated': 0,
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
            execution = db.query(db.Execution) \
                .join(db.Execution.version) \
                .join(db.Execution.heuristic) \
                .filter(db.Version.project_id == project.id) \
                .filter(db.Heuristic.label_id == label.id) \
                .filter(db.Execution.output != '').first()            
            if(execution is None):
                print("Execution is none")
            else:
                output = execution.output.split('\n\n')
                for k in output:
                    file_path = REPOS_DIR + os.sep + project.owner + os.sep + project.name + os.sep + k.split('\n', 1)[0]
                    if file_path.endswith('.java'):
                        list_java_files.append(create_package_heuristic_import(file_path))                        
                        status['Opened'] += 1
                    else:
                        status['Not .Java'] += 1

        save_txt(list_java_files, project.owner+"."+project.name, HEURISTICS_DIR_SECOND_LEVEL)
        list_java_files.clear()                

    status['Duplicated'] = len(list_java_files)                        
    list_java_files = list(set(list_java_files))
    status['Duplicated'] = status['Duplicated'] - len(list_java_files)
    status['Total'] = status['Opened'] + status['Not .Java']

    print_results(status)

def create_separate_file_level():
    first_level=[]
    second_level = []
    second_level_pure=[]

    print("Filtering results.")
    projects_db = search_projects()

    for i, project in enumerate(projects_db):
        status = {
        'First-Level': 0,
        'Second-Level': 0,
        'Error-first':0,
        'Error-second':0,
        'Total': 0
        }
        file_path = HEURISTICS_DIR_FIRST_LEVEL + os.sep + project.owner + "." + project.name + ".txt"
        try:
            with open(file_path) as file:
                first_level = file.read().splitlines()
        except FileNotFoundError:
            status['Error-first'] += 1
            print("The 'docs' directory does not exist")
        file_path = HEURISTICS_DIR_SECOND_LEVEL + os.sep + project.owner + "." + project.name + ".txt"
        try:
            with open(file_path) as file:
                second_level = file.read().splitlines()
        except FileNotFoundError:
            status['Error-second'] += 1
            print("The 'docs' directory does not exist")
        for i in second_level:
            if i in first_level:
                status['First-Level'] += 1
            else:
                second_level_pure.append(i)
                status['Second-Level'] += 1

        save_txt(second_level_pure, project.owner+"."+project.name, HEURISTICS_DIR_SECOND_LEVEL)
        status['Total'] = status['First-Level'] + status['Second-Level']
        print_results(status)
        status.clear()
        second_level_pure.clear()

    

    
def main():
    create_list_fanin_second_level()
    create_separate_file_level()

if __name__ == "__main__":
    main()