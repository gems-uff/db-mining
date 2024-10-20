
import argparse
import os
import sys
import database as db
import pandas as pd

from sqlalchemy.orm import load_only, selectinload
from extract import print_results
from util import REPOS_DIR, HEURISTICS_DIR_FIRST_LEVEL, COUNT_LINE_FILE_IMP


def create_level_heuristics(args, connect=True):
    """Create level heuristics"""
    if connect:
        db.connect()
    list_results = []
    status = {
        'Opened': 0,
        'None': 0,
        'Total': 0
    }
    if args.ext:
        status[f"Not {args.ext}"] = 0
    if args.count_result:
        status['Repository not found'] = 0
    if args.remove_duplicates:
        status['Duplicated'] = 0

    labels_db = db.query_labels(args.label)
    projects_db = db.query_projects(eager=False)
    print("Search results in execution for label and project.")

    for project in projects_db:
        list_files = []
        for label in labels_db:
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
                continue
    
            output = execution.output.split('\n\n')
            for k in output:
                status['Total'] += 1
                file_path = project.owner + os.sep + project.name + os.sep + k.split('\n', 1)[0]
                file_path = file_path.replace('\x1b[m', '')
                #file_path = strip_ansi("\x1b[m"+file_path+"\x1b[m")
                full_path = REPOS_DIR + os.sep + file_path
                if args.ext and not file_path.endswith(args.ext):
                    status[f"Not {args.ext}"] += 1
                    continue

                if args.remove_duplicates and full_path in list_files:
                    status['Duplicated'] += 1
                    if args.count_result:
                        list_results.append({"file": file_path, "lines" : 'duplicated', "label": label.name})
                else:
                    list_files.append(full_path)
                    status['Opened'] += 1
                    if args.count_result:
                        try:
                            with open(full_path, 'r') as open_file:
                                number_lines_open_file = len(open_file.readlines())
                            full_string_result = {"file": file_path, "lines" : number_lines_open_file, "label": label.name}
                            list_results.append(full_string_result) 
                        except NotADirectoryError:
                            status['Repository not found'] += 1
                    
        if len(list_files) > 0:
            save_txt(
                list_files, f"{project.owner}.{project.name}",
                args.heuristics, args.multiple, args.remove_duplicates
            )

    if args.count_result:
        save_list_of_dicts_table(list_results, args.count_result)
        
    print_results(status)
    

def save_list_of_dicts_table(all_results, file):
    print(f'Saving all results to {file}...', end=' ')
    df = pd.DataFrame(all_results)
    df.to_excel(file, index=False)
    print('Done!')
    

def save_txt(list_files, project, directory, multiple_files, remove_duplicates):
    os.chdir(directory)
    for fname in os.listdir('.'):
        if fname.startswith(project) and fname.endswith('.txt'):
            os.remove(fname)
            print(f"{fname} has been deleted.")
    
    heuristics = [create_heuristic_class(file) for file in list_files]
    if remove_duplicates:
        non_duplicated = set(heuristics)
        heuristics = sorted(non_duplicated, key=heuristics.index)
    if multiple_files:
        for i, heuristic in enumerate(heuristics):
            print(f"Saving file {project}.{i+1}.txt")
            with open(f'{project}.{i+1}.txt', 'w+') as text_file:
                text_file.write(f"{heuristic}\n")
    else:
        print(f"Saving file {project}.txt")
        with open(f'{project}.txt', 'w+') as text_file:
            text_file.write('\n'.join(heuristics) + "\n")
    

def create_heuristic_class(file_path):
    file_name = file_path.split('/')[-1]
    #heuristic_file = "[^a-zA-Z|^\/\"\_#|0-9]" + file_name.split('.')[0] + "[^a-zA-Z|^\/\"\_#|0-9]" #[^a-zA-Z|^\/"\_#|0-9]
    #heuristic_file = "(\s{1,}|[.,(]|^)" + file_name.split('.')[0] + "(\s{1,}|[.,(]|^)" #[^a-zA-Z|^\/"\_#|0-9]
    heuristic_file = "(\s|[.,(]|^)" + file_name.split('.')[0] + "(\s|[.,(]|$)"
    return heuristic_file


def read_args(
        prog, description,
        default_label="implementation",
        default_heuristics=HEURISTICS_DIR_FIRST_LEVEL,
        default_count=None,
        default_ext=".java",
        default_remove_duplicates=True,
        extra=lambda parser: None
    ):
    parser = argparse.ArgumentParser(
        prog=prog,
        description=description)
    parser.add_argument(
        '-l', '--label', default=default_label,
        help="Label in the database"
    )
    parser.add_argument(
        '-x', '--heuristics', default=default_heuristics,
        help="Heuristics directory"
    )
    parser.add_argument(
        '-c', '--count-result', default=default_count, 
        help="Export file with counts"
    )
    parser.add_argument(
        '-e', '--ext', default=default_ext, 
        help="Filter file extension"
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        '-m', '--multiple', action="store_true",
        help="Create multiple heuristic files for the same project"
    )
    group.add_argument(
        '--single', dest="multiple", action="store_false",
        help="Create single heuristic file"
    )
    parser.set_defaults(multiple=False)

    group2 = parser.add_mutually_exclusive_group(required=False)
    group2.add_argument(
        '-d', '--remove-duplicates', action="store_true",
        help="Remove duplicates"
    )
    group2.add_argument(
        '-a', '--allow-duplicates', dest="remove_duplicates", action="store_false",
        help="Allow duplicates"
    )
    parser.set_defaults(remove_duplicates=default_remove_duplicates)
    extra(parser)
    args = parser.parse_args()
    if not os.path.isdir(args.heuristics):
        sys.exit(f"The '{args.heuristics}' directory does not exist")
    return args


def main():
    args = read_args(
        'create_level_heuristics',
        'Populate level directories with their heuristics. Default: first-level based on the label `implementation`',
        #default_count=COUNT_LINE_FILE_IMP,default_ext=None # -- uncomment this line for old create_list_implementation
    )
    create_level_heuristics(args)
    
if __name__ == "__main__":
    main()
