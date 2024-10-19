import os
import subprocess
import database as db
import pandas as pd
from sqlalchemy.orm import load_only
from util import HISTORICAL_FILE, REPOS_DIR

from collections import defaultdict, Counter
from functools import partial


def select_mode(mode, project_file_map):
    execution_fields = [db.Execution.version_id, db.Execution.heuristic_id]
    if mode == "exists":
        return exists, execution_fields
    execution_fields.append(db.Execution.output)
    
    if mode == "count":
        return count_output, execution_fields
    # if mode == "rate":
    return partial(rate_output, project_file_map=project_file_map), execution_fields


def load_labels(label_type, verbose):
    if verbose:
        print("Loading labels...", end=" ", flush=True)
    labels_db = db.query(db.Label).options(load_only(db.Label.id, db.Label.name))
    if label_type:
        labels_db = labels_db.filter(db.Label.type == label_type)
    label_tuples = [(label.id, label.name) for label in labels_db]
    if verbose:
        print(f"found {len(label_tuples)}.")
    return label_tuples


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


def load_executions(execution_fields, heuristic_map, version_ids, verbose):
    if verbose:
        print("Loading executions...", end=" ", flush=True)
    counter = Counter()
    version_map = defaultdict(lambda: defaultdict(set))
    execution_db = db.query(db.Execution).options(
        load_only(*execution_fields)
    ).filter(
        (db.Execution.output != "")
        & (db.Execution.heuristic_id.in_(list(heuristic_map.keys())))
        & (db.Execution.version_id.in_(version_ids))
    )
    count = 0
    for execution in execution_db:
        count += 1
        heuristic = heuristic_map[execution.heuristic_id]
        counter[heuristic] += 1
        version_map[execution.version_id][heuristic].add(execution)
    if verbose:
        print(f"found {count}.")
    return counter, version_map


def prepare_labels(label_tuples, counter, sort_label_by_usage, hide_unused):
    if sort_label_by_usage:
        labels = [name for name, _ in counter.most_common()]
        if not hide_unused:
            labels += [name for _, name in label_tuples if name not in labels]
        return labels
    return [name for _, name in label_tuples if not hide_unused or name in counter]



def create_xlsx(
    filename,
    label_type='database',
    header="owner,name,sha1,part_commit,date_commit,isLast",
    mode="exists", # exists, count, rate
    select_versions="all", # all, last, historical
    sort_label_by_usage=True,
    hide_unused=True,
    verbose=True,
    total_files_header=None,

):
    strategies = []
    if mode != "exists" and select_versions in ("all", "historical"):
        print("Warning: this script currently only counts files in the HEAD of the repository. The count will be wrong for previous versions")
    projects_db = db.query_projects(with_version=False, eager=False)
    project_map = {project.id: project for project in projects_db}
    project_file_map = {}
    if total_files_header or mode == "rate":
        if verbose:
            print("Counting files per project...", end=" ", flush=True)
        for project_id, project in project_map.items():
            project_file_map[project_id] = count_number_files_project(project)
        if verbose:
            print("ok.")
    count_strategy, execution_fields = select_mode(mode, project_file_map)
    label_tuples = load_labels(label_type, verbose)
    label_map = dict(label_tuples)
    heuristic_map = load_heuristics(label_map, verbose)
    versions_db = load_versions(select_versions, verbose)
    version_ids = [version.id for version in versions_db]
    counter, version_map = load_executions(execution_fields, heuristic_map, version_ids, verbose)
    count_strategy.version_map = version_map
    labels = prepare_labels(label_tuples, counter, sort_label_by_usage, hide_unused)
    header_list = [x.strip() for x in header.split(',')]
    columns = header_list[:]
    results_label = []
    for version in versions_db:
        project = project_map[version.project_id]
        row = count_strategy.add_version(header_list, version, project)
        for label in labels:
            count_strategy.add_label(row, version, project, label)
        row = count_strategy.post_process(row, version, project)
        for key in row:
            if key not in columns:
                columns.append(key)
        results_label.append(row)

    save(filename, results_label, columns)


class PopulateStrategy:
    def __init__(self, *args, **kwargs):
        self.version_map = {}
        self.header = None
        self.results = []
        self.columns = []

    def set_header(self, header):
        self.header = header
        self.columns = header[:]

    def add_version(self, header, version, project):
        self.header = header
        return {
            header[0]: project.owner,
            header[1]: project.name,
            header[2]: version.sha1,
            header[3]: version.part_commit,
            header[4]: version.date_commit,
            header[5]: version.isLast
        }

    def add_label(self, row, version, project, label):
        pass

    def post_process(self, row, version, project):
        return row

    def get_executions(self, version, label):
        executions = self.version_map.get(version.id, {}).get(label, None)
        if len(executions) > 1:
            print(f"Warning: version {version} has {len(executions)} executions of heuristic {label}.")
        return executions

class ExistsStrategy(PopulateStrategy):
    def add_label(self, row, version, project, label):
        row[label] = int(bool(self.get_executions(version, label)))


class CountOutputStrategy(PopulateStrategy):
    def __init__(self, total_files_header, project_file_map, *args, **kwargs):
        super().__init__(total_files_header, project_file_map, *args, **kwargs)
        self.total_files_header = total_files_header
        self.project_file_map = project_file_map

    def add_version(self, header, version, project):
        row = super().add_version(header, version, project)
        if self.total_files_header:
            row[self.total_files_header] = self.project_file_map[version.project_id]
        return row
        
    def add_label(self, row, version, project, label):
        executions = self.get_executions(version, label)
        if executions is None:
            row[label] = 0
            return
        row[label] = sum(len(execution.output.split('\n\n')) for execution in executions)


class RateOutputStrategy(CountOutputStrategy):
    def add_label(self, row, version, project, label):
        super().add_label(row, version, project, label)
        if row[label]:
            row[label] = row[label] / self.project_file_map[version.project_id] * 100


class CodeTestStrategy(CountOutputStrategy):
    def add_version(self, header, version, project):
        row = super().add_version(header, version, project)
        row['Code'] = 0
        row['None'] = 0
        row['Not Java'] = 0
        row[self.total_files_header] = self.project_file_map[version.ptoject_id]
        return row

    def add_label(self, row, version, project, label):
        executions = self.get_executions(version, label)
        if executions is None:
            row['None'] += 1
            return
        for execution in executions:
            output = execution.output.split('\n\n')
            for k in output:
                file_path = k.split('\n', 1)[0].replace('\x1b[m', '')
                if file_path.endswith('.java'):
                    if "src/test"in file_path:
                        row['Test'] += 1   
                    else:
                        row['Code'] += 1   
                else:
                    row['Not Java'] += 1


class CodeTestXMLStrategy(CountOutputStrategy):
    def add_version(self, header, version, project):
        row = super().add_version(header, version, project)
        row['DB-Code Test'] = 0
        row['DB-Code Java'] = 0
        row['DB-Code XML'] = 0
        row['DB-Code Not Java/XML'] = 0
        row['None'] = 0
        row['Dependencies Test'] = 0
        row['Dependencies Code'] = 0
        row['Dependencies XML'] = 0
        row['Dependencies Not Java/XML'] = 0
        row[self.total_files_header] = self.project_file_map[version.ptoject_id]
        row['Total DB'] = 0
        return row

    def add_label(self, row, version, project, label):
        executions = self.get_executions(version, label)
        if executions is None:
            row['None'] += 1
            return
        
        for execution in executions:
            output = execution.output.split('\n\n')
            row['Total DB'] += len(output)
            for k in output:
                file_path = k.split('\n', 1)[0].replace('\x1b[m', '')
                if label.startswith(f"{project.owner}.{project.name}"):  # level labels
                    if file_path.endswith('.java'):
                        if "src/test" in file_path:
                            row['Dependencies Test'] += 1
                        else:
                            row['Dependencies Code'] += 1
                    else:
                        if file_path.endswith('.xml'):
                            row['Dependencies XML'] += 1
                        else:
                            row['Dependencies Not Java/XML'] += 1
                else:
                    if file_path.endswith('.java'):
                        if "src/test" in file_path:
                            row['DB-Code Test'] += 1
                        else:
                            row['DB-Code Java'] += 1
                    else:
                        if file_path.endswith('.xml'):
                            row['DB-Code XML'] += 1
                        else:
                            row['DB-Code Not Java/XML'] += 1

    def post_process(self, row, version, project):
        result = { key: row[key] for key in self.header }
        result['N DB-Code Test'] = row['DB-Code Test'] or ""
        result['N DB-Code Java'] = row['DB-Code Java'] or ""
        result['N DB-Code XML'] = row['DB-Code XML'] or ""
        result['N DB-Code Not Java/XML'] = row['DB-Code Not Java/XML'] or ""
        result['N Dependencies Test'] = row['Dependencies Test'] or ""
        result['N Dependencies Code'] = row['Dependencies Code'] or ""
        result['N Dependencies XML'] = row['Dependencies XML'] or ""
        result['N Dependencies Not Java/XML'] = row['Dependencies Not Java/XML'] or ""
        result[f'N {self.total_files_header}'] = row[self.total_files_header] or ""
        result['N Total DB'] = row['Total DB'] or ""
        result['DB-Code Test'] = ""
        result['DB-Code Java'] = ""
        result['DB-Code XML'] = ""
        result['Dependencies Test'] = ""
        result['Dependencies Code'] = ""
        result['Dependencies XML'] = ""
        result['Total DB'] = ""
        total = row[self.total_files_header] 
        if total > 0:
            result['DB-Code Test'] = (row['DB-Code Test'] / total * 100) or ""
            result['DB-Code Java'] = (row['DB-Code Java'] / total * 100) or ""
            result['DB-Code XML'] = (row['DB-Code XML'] / total * 100) or ""
            result['Dependencies Test'] = (row['Dependencies Test'] / total * 100) or ""
            result['Dependencies Code'] = (row['Dependencies Code'] / total * 100) or ""
            result['Dependencies XML'] = (row['Dependencies XML'] / total * 100) or ""
            result['Total DB'] = (row['Total DB'] / total * 100) or ""
        return result
            

class PomStrategy(CountOutputStrategy):
    def add_label(self, row, version, project, label):
        executions = self.get_executions(version, label)
        if executions is None:
            row[label] = 0
            return
        for execution in executions:
            pom = 0
            output = execution.output.split('\n\n')
            for k in output: #a forma de olhar os resultados está incorreta (?)
                file_path = k.split('\n', 1)[0].replace('\x1b[m', '')
                if file_path.endswith('pom.xml'):
                    pom += 1
            if pom:
                if pom == 1:
                    row[label] = file_path
                else:
                    row[label] = pom # len(output)
            else:
                row[label] = -1


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


def save(filename, results_Label, heuristics): 
    print("\n")
    print(f'Saving all results to {filename}...', end=' ')
    df = pd.DataFrame(data = results_Label, columns = heuristics)
    df.to_excel(filename, index=False) 
    print('Done!')


def main():
    db.connect()
    create_xlsx("database", header="OWNER,PROJECTS,SHA1,COMMITS,DATE COMMIT,IS LAST")
    create_historical(HISTORICAL_FILE)

if __name__ == "__main__":
    main()