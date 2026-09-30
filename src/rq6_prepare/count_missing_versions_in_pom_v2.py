import os
import subprocess
import csv
import xml.etree.ElementTree as ET
import database as db
from sqlalchemy.orm import load_only
from collections import defaultdict, Counter
import re
from util import (REPOS_DIR, VULNERABILITY_COUNT)

#O script percorre execuções de heurísticas (provavelmente de varreduras nos projetos) 
# e conta, por projeto, quantas execuções indicam a presença de um pom.xml sem uma tag 
# <version> (possivelmente para identificar POMs sem versão definida) vs. execuções “normais” 
# (com <version>). Depois, salva esse resumo em CSV.

NAMESPACE = {'m': 'http://maven.apache.org/POM/4.0.0'}

def load_labels(label_types, verbose):
    if verbose:
        print("Loading labels...", end=" ", flush=True)
    labels_db = db.query(db.Label).options(
        load_only(db.Label.id, db.Label.name, db.Label.type)
    )
    if not None in label_types:
        labels_db = labels_db.filter(db.Label.type.in_(label_types))
    label_tuples = [(label.id, (label.name, label.type)) for label in labels_db]
    if verbose:
        print(f"found {len(label_tuples)}.")
    return label_tuples


def load_versions(select_versions, verbose):
    if verbose:
        print("Loading versions...", end=" ", flush=True)
    versions_db = db.query(db.Version).options(
        load_only(
            db.Version.id, db.Version.project_id, db.Version.isLast,
            db.Version.part_commit, db.Version.date_commit
        )
    )
    if select_versions == "last":
        versions_db = versions_db.filter(db.Version.isLast.is_(True))
    elif select_versions == "historical":
        versions_db = versions_db.filter(db.Version.part_commit.is_not(None))
    versions_db = versions_db.order_by(db.Version.project_id, db.Version.part_commit).all()
    if verbose:
        print(f"found {len(versions_db)}.")
    return versions_db


def load_executions(execution_fields, heuristic_map, version_ids, project_map, verbose, output_csv_path):
    if verbose:
        print("Loading executions...", end=" ", flush=True)
        
    # Contadores por projeto
    project_counter = defaultdict(lambda: {"normal_output": 0, "pom_no_version": 0})
    version_map = defaultdict(lambda: defaultdict(set))
    
    # Consulta ao banco de dados
    execution_db = db.query(db.Execution).options(
        load_only(*execution_fields)
    ).filter(
        (db.Execution.output != "")
        & (db.Execution.heuristic_id.in_(list(heuristic_map.keys())))
        & (db.Execution.version_id.in_(version_ids))
    )
    
    # Expressão regular para encontrar 'pom.xml' e verificar a ausência de '<version>'
    pom_pattern = re.compile(r'pom\.xml', re.IGNORECASE)
    version_pattern = re.compile(r'version>.*?', re.IGNORECASE)
    
    count = 0
    for execution in execution_db:
        count += 1
        output = execution.output
        version_id = execution.version_id
        version_db = db.query(db.Version).options(load_only(db.Version.id, db.Version.project_id, db.Version.isLast,
            db.Version.part_commit, db.Version.date_commit)).filter(db.Version.id == version_id).first()
        
        # Identificar o projeto atual usando o version_id
        project = project_map.get(version_db.project_id)
        if not project:
            continue
        
        project_name = project.name
        
        # Verifica se contém 'pom.xml'
        if pom_pattern.search(output):
            #print(output)
            #print("\n\n")
            # Verifica se não contém uma declaração de versão
            if not version_pattern.search(output):
                project_counter[project_name]["pom_no_version"] += 1
            else:
                project_counter[project_name]["normal_output"] += 1
        else:
            print("The project no conatains pom.xml")

            #project_counter[project_name]["normal_output"] += 1  # Considera como um output normal
            
    if verbose:
        print(f"Found {count} executions. Matches found: {sum(sum(c.values()) for c in project_counter.values())}.")
    
    # Salvar os resultados em um arquivo CSV
    with open(output_csv_path, mode='w', newline='', encoding='utf-8') as csv_file:
        csv_writer = csv.writer(csv_file)
        
        # Escreve os cabeçalhos
        csv_writer.writerow(['project_name', 'normal_output_count', 'pom_no_version_count'])
        
        # Escreve os dados de cada projeto
        for project_name, counts in project_counter.items():
            csv_writer.writerow([
                project_name,
                counts.get("normal_output", 0),
                counts.get("pom_no_version", 0)
            ])
                
    print(f"✅ Resultados salvos em: {output_csv_path}")
    return project_counter, version_map


def load_heuristics(label_map, verbose):
    if verbose:
        print("Loading heuristics...", end=" ", flush=True)
    heuristic_db = db.query(db.Heuristic).options(load_only(db.Heuristic.id, db.Heuristic.label_id))
    heuristic_map = {
        heuristic.id: label_map[heuristic.label_id]
        for heuristic in heuristic_db
        if heuristic.label_id in label_map
    }
    if verbose:
        print(f"found {len(heuristic_map)}.")
    return heuristic_map


def count_number_files_project(project):
    try:
        cwd = os.getcwd()
        os.chdir(REPOS_DIR + os.sep + project.owner + os.sep + project.name)
        p = subprocess.run("git ls-files | wc -l", capture_output=True, text=True, shell=True)
        return int(p.stdout)
    except NotADirectoryError:
        return 0
    except subprocess.CalledProcessError as ex:
        return 0
    finally:
        os.chdir(cwd)


def main():
    verbose=True
    select_versions = 'last'

    projects_db = db.query_projects(with_version=False, eager=False)
    project_map = {project.id: project for project in projects_db}
    all_select_versions = set()
    label_types = set()
    label_types.add('database')
    loads_output = True
    all_select_versions.add(select_versions)
    label_types.update(label_types)
    if len(all_select_versions) > 1:
        select_versions = "all"
    else:
        select_versions = next(iter(all_select_versions))
    label_types = list(label_types)
    if any(label_type is None for label_type in label_types):
        label_types = None
    execution_fields = [db.Execution.version_id, db.Execution.heuristic_id]
    if loads_output:
        execution_fields.append(db.Execution.output)

    label_tuples = load_labels(label_types, verbose)
    label_map = dict(label_tuples)
    heuristic_map = load_heuristics(label_map, verbose)
    versions_db = load_versions(select_versions, verbose)
    version_ids = [version.id for version in versions_db]
    load_executions(execution_fields, heuristic_map, version_ids, project_map, verbose, VULNERABILITY_COUNT)
    #print(version_map)
    
    
    #analyze_projects_from_db()
    #ExistsStrategy(RESOURCE_DIR + os.sep + 'database.xlsx', label_types=['database'],select_versions='last',)


if __name__ == "__main__":
    main()
