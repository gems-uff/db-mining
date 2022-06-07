
import database as db
from sqlalchemy.orm import load_only, selectinload
import pandas as pd
from util import COUNT_FILE_SQL


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
                    print(f"k: {k}")
                results_Label.append(sum)
        if(i==0):
            all_results["Projects"] = index_projects
            all_results["Domains"] = index_domains
        all_results[label.name] = results_Label.copy()
        results_Label.clear()
    save(all_results, COUNT_FILE_SQL)



def save(all_results, file):
    print(f'Saving all results to {file}...', end=' ')
    df = pd.DataFrame(all_results)
    df.to_excel(file, index=False)
    print('Done!')

def main():
    create_count_sql()
    
if __name__ == "__main__":
    main()