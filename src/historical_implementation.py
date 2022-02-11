from itertools import count
from sys import version
from sqlalchemy.sql.elements import Null
from sqlalchemy.sql.expression import column, null
import database as db
from sqlalchemy.orm import load_only, selectinload

import pandas as pd
from util import HISTORICAL_FILE
from sqlalchemy import func


def create_characterization():
    db.connect()
    all_results = dict()
    index_projects = []
    index_commits = []
    #column = []
    heuristics = []
    results_Label = []
    projects_db = db.query(db.Project).options(load_only('id', 'owner', 'name'), selectinload(db.Project.versions).load_only('id')).all()
    #print(projects_db)
    labels_db = db.query(db.Label).options(selectinload(db.Label.heuristic).options(selectinload(db.Heuristic.executions).defer('output').defer('user'))).filter(db.Label.type == 'database').all()
    versions_db = db.query(db.Version).options(load_only('id','part_commit','project_id'), selectinload(db.Version.executions).load_only('id')).all()
    print(versions_db)
   
    print(versions_db)
    print("Search results in execution for label and project.")
    for j, project in enumerate(projects_db):
        if(len(index_projects)< len(projects_db)):
            index_projects.append(project.name)
            #for k, versioni in enumerate(versions_db):
            for k, version in enumerate (db.query(db.Version).filter(db.Version.project_id == project.id)):
                linha = []
               
                index_commits.append(version.part_commit)
                linha.append(project.name)
                linha.append(version.part_commit)
                for i,label in enumerate(labels_db):
                    # Search results in execution for label and project #.filter(db.Version.project_id == version.id) \
                    execution = db.query(db.Execution) \
                        .join(db.Execution.version) \
                        .join(db.Execution.heuristic) \
                        .filter(db.Version.id == version.id) \
                        .filter(db.Version.id == db.Execution.version_id) \
                        .filter(db.Heuristic.label_id == label.id).first()
                    
                    if(execution is None):
                        #results_Label.append(0)
                        linha.append(0)
                    else:
                        #if(execution.output != ''):
                        if(execution.output != ''):
                           #results_Label.append(1)
                           linha.append(1)
                        else:
                            #results_Label.append(0)
                            linha.append(0)
                    if (j==0) and (k==0):
                        heuristics.append(label.name)
                results_Label.append(linha)
        if(j==0):
            all_results["Projects"] = index_projects
            all_results["Commits"] = index_commits
    #all_results[str(heuristics)] = results_Label.copy()
    #results_Label.clear()
    #print(index_commits)
    
    print(heuristics)   
    heuristics.insert(0,'COMMITS')
    heuristics.insert(0,'PROJECTS')
    print(labels_db)
    print(heuristics)
    print(results_Label)
    save(all_results, results_Label, heuristics)


def save(all_results, results_Label, heuristics): 
    print(f'Saving all results to {HISTORICAL_FILE}...', end=' ')
    df = pd.DataFrame(data = results_Label, columns = heuristics)
    
    df.to_excel(HISTORICAL_FILE, index=False) 

    print('Done!')

def main():
    create_characterization()

if __name__ == "__main__":
    main()