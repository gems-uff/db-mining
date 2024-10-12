import database as db
import pandas as pd
from sqlalchemy.orm import load_only
from util import HISTORICAL_FILE

from collections import namedtuple, defaultdict, Counter


def create_historical():
    labels_db = db.query(db.Label).options(
        load_only(db.Label.id, db.Label.name)
    ).filter(db.Label.type == 'database').all()
    label_map = {label.id: label.name for label in labels_db}

    heuristic_db = db.query(db.Heuristic).options(
        load_only(db.Heuristic.id, db.Heuristic.label_id)
    )
    heuristic_map = {heuristic.id: label_map[heuristic.label_id] for heuristic in heuristic_db}


    counter = Counter()
    version_map = defaultdict(set)
    execution_db = db.query(db.Execution).options(
        load_only(db.Execution.version_id, db.Execution.heuristic_id)
    ).filter(db.Execution.output != "")
    for execution in execution_db:
        heuristic = heuristic_map[execution.heuristic_id]
        counter[heuristic] += 1
        version_map[execution.version_id].add(heuristic)
            
    projects_db = db.query(db.Project).options(
        load_only(db.Project.id, db.Project.owner, db.Project.name)
    )
    project_map = {project.id: project for project in projects_db}

    versions_db = db.query(db.Version).options(
        load_only(
            db.Version.id, db.Version.project_id, 
            db.Version.part_commit, db.Version.date_commit
        )
    ).order_by(db.Version.project_id, db.Version.part_commit)
    labels = [key for key, count in counter.most_common()]
    columns = ["OWNER", "PROJECTS", "COMMITS", "DATE COMMIT"] + labels

    results_label = []
    for version in versions_db:
        project = project_map[version.project_id]
        linha = [project.owner, project.name, version.part_commit, version.date_commit] + [
            int(label in version_map.get(version.id, {}))
            for label in labels
        ]
        results_label.append(linha)

    save(results_label, columns)


def save(results_Label, heuristics): 
    print(f'Saving all results to {HISTORICAL_FILE}...', end=' ')
    df = pd.DataFrame(data = results_Label, columns = heuristics)
    
    df.to_excel(HISTORICAL_FILE, index=False) 

    print('Done!')

def main():
    db.connect()
    create_historical()

if __name__ == "__main__":
    main()