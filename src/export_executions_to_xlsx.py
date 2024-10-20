import os
import subprocess
import database as db
import pandas as pd
from sqlalchemy.orm import load_only
from util import (
    HISTORICAL_FILE, REPOS_DIR, COUNT_FILE_IMP_RATE, COUNT_FILE_IMP,
    USAGE_FAN_IN_FILE, RESOURCE_DIR, COUNT_FILE_SQL, VULNERABILITY_LABELS
)

from collections import defaultdict, Counter
from functools import partial


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
        labels = [label for label, _ in counter.most_common()]
        if not hide_unused:
            labels += [label for _, label in label_tuples if label not in labels]
        return labels
    return [label for _, label in label_tuples if not hide_unused or label in counter]


def create_xlsx(
    strategies,
    header="owner,name,domain,sha1,part_commit,date_commit,isLast",
    sort_label_by_usage=False,
    hide_unused=False,
    verbose=True
):
    projects_db = db.query_projects(with_version=False, eager=False)
    project_map = {project.id: project for project in projects_db}
    project_file_map = {}
    all_select_versions = set()
    label_types = set()
    loads_output = False
    for strategy in strategies:
        if strategy.has_file_count and not project_file_map:
            if verbose:
                print("Counting files per project...", end=" ", flush=True)
            for project_id, project in project_map.items():
                project_file_map[project_id] = count_number_files_project(project)
            if verbose:
                print("ok.")
        strategy.set_project_file_map(project_file_map)
        all_select_versions.add(strategy.select_versions)
        label_types.update(strategy.label_types)
        loads_output |= strategy.loads_output
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
    counter, version_map = load_executions(execution_fields, heuristic_map, version_ids, verbose)
    labels = prepare_labels(label_tuples, counter, sort_label_by_usage, hide_unused)
    header_list = [x.strip() for x in header.split(',')]
    for strategy in strategies:
        strategy.reset(header_list, labels, version_map)
        for version in versions_db:
            project = project_map[version.project_id]
            strategy.process_version(version, project)
        strategy.save()


class PopulateStrategy:
    def __init__(
        self, filename, *args,
        label_types=['database'],
        select_versions="all", # all, last, historical
        **kwargs
    ):
        self.version_map = {}
        self.filename = filename
        self.label_types = label_types
        self.select_versions = select_versions
        self.header = None
        self.results = []
        self.columns = []
        self.has_file_count = False
        self.loads_output = False
        self._labels = None

    def set_project_file_map(self, project_file_map):
        pass

    def reset(self, header, labels, version_map):
        self.version_map = version_map
        self.header = header
        self.results = []
        self.columns = header[:]
        use_all_labels = None in self.label_types
        self._labels = [
            (name, ltype) for name, ltype in labels
            if use_all_labels or ltype in self.label_types
        ]

    def process_version(self, version, project):
        if self.select_versions == "historical" and version.part_commit is None:
            return
        if self.select_versions == "last" and not version.isLast:
            return
        row = self.add_version(version, project)
        for label in self._labels:
            self.add_label(row, version, project, label)
        row = self.post_process(row, version, project)
        for key in row:
            if key not in self.columns:
                self.columns.append(key)
        self.results.append(row)

    def save(self):
        print("\n")
        print(f'Saving results to {self.filename}...', end=' ')
        df = pd.DataFrame(data=self.results, columns=self.columns)
        df.to_excel(self.filename, index=False)
        print('Done!')

    def add_version(self, version, project):
        return {
            self.header[0]: project.owner,
            self.header[1]: project.name,
            self.header[2]: project.domain,
            self.header[3]: version.sha1,
            self.header[4]: version.part_commit,
            self.header[5]: version.date_commit,
            self.header[6]: version.isLast

        }

    def add_label(self, row, version, project, label):
        pass

    def post_process(self, row, version, project):
        return row

    def get_executions(self, version, label):
        executions = self.version_map.get(version.id, {}).get(label, None)
        if executions and len(executions) > 1:
            print(f"Warning: version {version} has {len(executions)} executions of heuristic {label}.")
        return executions

class ExistsStrategy(PopulateStrategy):
    def add_label(self, row, version, project, label):
        row[label] = int(bool(self.get_executions(version, label)))


class CountOutputStrategy(PopulateStrategy):
    def __init__(
        self, *args,
        total_files_header=None,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.total_files_header = total_files_header
        self.project_file_map = {}
        self.has_file_count = bool(total_files_header)
        self.loads_output = True

    def set_project_file_map(self, project_file_map):
        if self.has_file_count and self.select_versions in ("all", "historical"):
            print("Warning: this script currently only counts files in the HEAD of the repository. The count will be wrong for previous versions")
        self.project_file_map = project_file_map

    def add_version(self, version, project):
        row = super().add_version(version, project)
        if self.total_files_header:
            row[self.total_files_header] = self.project_file_map[version.project_id]
        return row

    def add_label(self, row, version, project, label):
        executions = self.get_executions(version, label)
        if executions is None:
            row[label[0]] = 0
            return
        row[label[0]] = sum(len(execution.output.split('\n\n')) for execution in executions)


class RateOutputStrategy(CountOutputStrategy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_file_count = True

    def add_label(self, row, version, project, label):
        super().add_label(row, version, project, label)
        if row[label[0]]:
            row[label[0]] = row[label[0]] / self.project_file_map[version.project_id] * 100


class CodeTestStrategy(CountOutputStrategy):
    def add_version(self, version, project):
        row = super().add_version(version, project)
        row['Code'] = 0
        row['Test'] = 0
        row['None'] = 0
        row['Not Java'] = 0
        row[self.total_files_header] = self.project_file_map[version.project_id]
        return row

    def add_label(self, row, version, project, label):
        executions = self.get_executions(version, label)
        if executions is None:
            row['None'] += 1
            return
        for execution in executions:
            output = execution.output.split('\n\n')
            for k in output:
                file_path = extract_file_path(k)
                if file_path.endswith('.java'):
                    if "src/test"in file_path:
                        row['Test'] += 1
                    else:
                        row['Code'] += 1
                else:
                    row['Not Java'] += 1


class CodeTestXMLStrategy(CountOutputStrategy):
    def add_version(self, version, project):
        row = super().add_version(version, project)
        row['DB-Code Test'] = 0
        row['DB-Code Java'] = 0
        row['DB-Code XML'] = 0
        row['DB-Code Not Java/XML'] = 0
        row['None'] = 0
        row['Dependencies Test'] = 0
        row['Dependencies Code'] = 0
        row['Dependencies XML'] = 0
        row['Dependencies Not Java/XML'] = 0
        row[self.total_files_header] = self.project_file_map[version.project_id]
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
                file_path = extract_file_path(k)
                if label[0].startswith(f"{project.owner}.{project.name}"):  # level labels
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
            row[label[0]] = 0
            return
        for execution in executions:
            pom = 0
            output = execution.output.split('\n\n')
            for k in output: #a forma de olhar os resultados está incorreta (?)
                file_path = extract_file_path(k)
                if file_path.endswith('pom.xml'):
                    pom += 1
            if pom:
                if pom == 1:
                    row[label[0]] = file_path
                else:
                    row[label[0]] = pom # len(output)
            else:
                row[label[0]] = -1

def extract_file_path(match):
    return match.split('\n', 1)[0].split(':', 1)[-1].replace('\x1b[m', '').replace('\x1b[35m', '')



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


def create_vulnerability_csv():
    results_Label = []
    db.connect()
    vulnerabilities_db = (
        db.query(db.Vulnerability)
        .join(db.Label)
        .filter(db.Vulnerability.label_id == db.Label.id)
    )
    for j, vulnerability in enumerate(vulnerabilities_db):
        status_dbCode = {
            'Name': vulnerability.name,
            'Description': vulnerability.description,
            'Year': vulnerability.year,
            'Label': vulnerability.label.name
        }

        results_Label.append(status_dbCode)
    save_local(results_Label, VULNERABILITY_LABELS)


def save_local(all_results, LocalToSave):
    print("\n")
    print(f'Saving all results to {LocalToSave}...', end=' ')
    df = pd.DataFrame(all_results)
    df.to_excel(LocalToSave, index=False)
    print('Done!')


def main():
    db.connect()
    # ToDo: add arguments to choose strategies
    create_xlsx([
        # Database results
        ExistsStrategy(
            RESOURCE_DIR + os.sep + 'database.xlsx', label_types=['database'],
            select_versions='last',
        ),
        PomStrategy(
            RESOURCE_DIR + os.sep + 'pomXml.xlsx', label_types=['database'],
            select_versions='last',
        ),
        # ORM implementation
        ExistsStrategy(
            RESOURCE_DIR + os.sep + 'implementation.xlsx',
            label_types=['implementation'], select_versions='last',
        ),
        # Query results
        ExistsStrategy(
            RESOURCE_DIR + os.sep + 'query.xlsx',
            label_types=['query'], select_versions='last',
        ),
        CountOutputStrategy(
            COUNT_FILE_SQL, label_types=['query'], select_versions='last',
        ),
        # ORM usage results
        RateOutputStrategy(
            COUNT_FILE_IMP_RATE, label_types=['implementation'],
            select_versions='last', total_files_header="Number total of files"
        ),
        CountOutputStrategy(
            COUNT_FILE_IMP, label_types=['implementation'],
            select_versions='last', total_files_header="Number total of files"
        ),
        CodeTestStrategy(
            RESOURCE_DIR + os.sep + 'number_of_files.xlsx', label_types=['implementation', 'classes'],
            select_versions='last', total_files_header='Total Project'
        ),
        CodeTestXMLStrategy(
            USAGE_FAN_IN_FILE, label_types=['implementation', 'classes'],
            select_versions="last", total_files_header='Total Project'
        ),
        # Historical
        ExistsStrategy(
            HISTORICAL_FILE, label_types=['database'],
            select_versions='historical',
        ),
    ])
    create_vulnerability = False
    if create_vulnerability:
        create_vulnerability_csv()

if __name__ == "__main__":
    main()
