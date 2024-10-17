
import database as db
import os
from util import  REPOS_DIR, HEURISTICS_DIR_FIRST_LEVEL, HEURISTICS_DIR_SECOND_LEVEL, USAGE_FAN_IN_FILE
from results_in_xlsx import count_number_files_project
from create_1st_level_heuristics import create_level_heuristics, read_args, save_list_of_dicts_table, save_txt, search_projects


def create_separate_file_level(args):
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

        save_txt(
            second_level_pure, f"{project.owner}.{project.name}", 
            args.heuristics, args.multiple, args.remove_duplicates
        )

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
    save_list_of_dicts_table(all_results, USAGE_FAN_IN_FILE)


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
               
    
def main():
    def extra(parser):
        parser.add_argument(
            '--separate-file-level', action="store_true",
            help="Run old separate file level code. May ignore other parameters"
        )
    args = read_args(
        'create_2nd_level_heuristics',
        'Populate 2nd level directories with their heuristics.',
        default_label="classes",
        default_heuristics=HEURISTICS_DIR_SECOND_LEVEL,
        default_remove_duplicates=False,
        extra=extra
    )
    if args.separate_file_level:
        create_separate_file_level(args)
    else:
        create_level_heuristics(args)

if __name__ == "__main__":
    main()
