#buscar os resultados com mais de 1 linha
#validar se a quantidade de reultados confere com o número de arquivos
#se estiver correto, unir os resultados em uma linha só
#se não estiver correto, apagar as execuções

from math import ceil
from sqlalchemy.orm import load_only, selectinload
from util import HEURISTICS_DIR_FIRST_LEVEL
from extract import print_results

import database as db
import os 



def merge_lines_db():
    concatenated_results = ""
    status = {
        'None': 0,
        'SizeOne': 0,
        'Merge': 0,
        'Deleted': 0
    }
    db.connect()
    projects_db = db.query(db.Project).options(load_only('id', 'owner', 'name'), selectinload(db.Project.versions).load_only('id')).all()
    for j, project in enumerate(projects_db):
        name_project = project.owner+'.'+project.name
        labels_db = db.query(db.Label).options(selectinload(db.Label.heuristic).options(selectinload(db.Heuristic.executions).defer('output').defer('user'))).filter(db.Label.name == name_project).first()
        list_execution = db.query(db.Execution) \
                .join(db.Execution.version) \
                .join(db.Execution.heuristic) \
                .filter(db.Version.project_id == project.id) \
                .filter(db.Heuristic.label_id == labels_db.id).all()
        if(list_execution is None):
            status['None'] += 1
        elif(len(list(list_execution)) == 1):
            status['SizeOne'] += 1
        else:
            lisf_of_parts = sifeOfSplits(HEURISTICS_DIR_FIRST_LEVEL + os.sep + name_project + '.txt')
            version = project.versions[0]
            heuristic = labels_db.heuristic
            if(len(list(list_execution)) == lisf_of_parts):
                for execution in list_execution:
                    concatenated_results = concatenated_results + execution.output
                    status['Merge'] += 1 
                    db.delete(execution)
                db.create(db.Execution, output=concatenated_results, version=version, heuristic=heuristic, isValidated=False, isAccepted=False)
                db.commit()
            else:
                for execution in list_execution:
                    db.delete(execution)
                status['Deleted'] += 1

    print_results(status)
    db.close()

def sifeOfSplits(file_path):
    size = 50  
    input = open(file_path).readlines(  )
    return ceil(len(input)/size)

def main():
    merge_lines_db()
    

if __name__ == "__main__":
    main()