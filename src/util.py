import os
import time
import sys

# Flags
DATABASE_DEBUG = False
CODE_DEBUG = False

# Directories
SRC_DIR = os.path.dirname(os.path.realpath(__file__))
BASE_DIR = os.path.dirname(SRC_DIR)
WORKSPACE_DIR = os.path.dirname(BASE_DIR)
REPOS_DIR = WORKSPACE_DIR + os.sep + 'repos'
RESOURCE_DIR = BASE_DIR + os.sep + 'resources'
HEURISTICS_DIR = RESOURCE_DIR + os.sep + 'heuristics'
HEURISTICS_DIR_EOI = HEURISTICS_DIR + os.sep + 'eo'
HEURISTICS_DIR_FIRST_LEVEL = HEURISTICS_DIR + os.sep + '.first-level'
HEURISTICS_DIR_SECOND_LEVEL = HEURISTICS_DIR + os.sep + '.second-level'
HEURISTICS_DIR_TEMP_FILES = HEURISTICS_DIR + os.sep + '.tempFiles'
HEURISTICS_DIR_VULNERABILITIES = HEURISTICS_DIR + os.sep + '.vulnerabilities'
HEURISTICS_DIR_IMPLEMENTATION = HEURISTICS_DIR + os.sep + 'implementation'

SEQ_PATTERNS_DIR = RESOURCE_DIR + os.sep + 'seq_patterns'


REACT_BUILD_DIR = BASE_DIR + os.sep + 'web' + os.sep + 'build'
REACT_STATIC_DIR = REACT_BUILD_DIR + os.sep + 'static'

# Files
PROJECTS_FILE = RESOURCE_DIR + os.sep + 'projects.xlsx'
POMRESULTS = RESOURCE_DIR + os.sep + 'pomXmlResults.xlsx'
FILTERED_FILE = RESOURCE_DIR + os.sep + 'filtered_projects.xlsx'
ANNOTATED_FILE = RESOURCE_DIR + os.sep + 'annotated.xlsx'
ANNOTATED_FILE_JAVA = RESOURCE_DIR + os.sep + 'annotated_java.xlsx' #'annotated_java_test.xlsx' 
ANNOTATED_FILE_JAVA_TEST = RESOURCE_DIR + os.sep + 'annotated_java_test.xlsx'
ANNOTATED_FILE_JAVA_SAMPLE = RESOURCE_DIR + os.sep + 'annotated_java_sample.xlsx'
DBLP_FILE = RESOURCE_DIR + os.sep + 'dblp.xml'
VENUE_KEYS = RESOURCE_DIR + os.sep + 'venue_keys.txt'
PAPERS_FILE = RESOURCE_DIR + os.sep + 'papers.xlsx'
FILTERED_PAPERS_FILE = RESOURCE_DIR + os.sep + 'filtered_papers.xlsx'
FILTERED_PAPERS_FILE_2022 = RESOURCE_DIR + os.sep + 'filtered_papers_2022.xlsx'
AGREEMENT_FILE = RESOURCE_DIR + os.sep + 'agreement.xlsx'
CHARACTERIZATION_FILE_IMP = RESOURCE_DIR + os.sep + 'characterization_implementation.xlsx'
COUNT_FILE_IMP = RESOURCE_DIR + os.sep + 'count_implementation.xlsx'
COUNT_FILE_IMP_RATE = RESOURCE_DIR + os.sep + 'count_implementation_rate.xlsx'
COUNT_FILE_SQL = RESOURCE_DIR + os.sep + 'count_sql.xlsx'
COUNT_LINE_FILE_IMP = RESOURCE_DIR + os.sep + 'count_line_implementation.xlsx'
HISTORICAL_FILE = RESOURCE_DIR + os.sep + 'historical.xlsx'
USAGE_FAN_IN_FILE = RESOURCE_DIR + os.sep + 'usage_fan_in_file.xlsx'
USAGE_FAN_IN_FILE_2 = RESOURCE_DIR + os.sep + 'usage_fan_in_file_2.xlsx'
HISTORICAL_FILE_SAMPLE = RESOURCE_DIR + os.sep + 'historical_sample.xlsx'
HISTORICAL_FILE_JOIN = RESOURCE_DIR + os.sep + 'historical_join.xlsx'
HISTORICAL_RULES_FILE = RESOURCE_DIR + os.sep + 'historical_rules.xlsx'
HISTORICAL_FILE_JOIN_DB = RESOURCE_DIR + os.sep + 'historical_join_db.xlsx'
DATABASES_MODELS = RESOURCE_DIR + os.sep + 'databases_models.xlsx'
HISTORICAL_INPUT_SEQUENCIAL = SEQ_PATTERNS_DIR + os.sep + 'input_sequencial.txt'
HISTORICAL_INPUT_SEQUENCIAL_NEG = SEQ_PATTERNS_DIR + os.sep + 'input_sequencial_neg.txt'
HISTORICAL_INPUT_SEQUENCIAL_NUMBERS = SEQ_PATTERNS_DIR + os.sep + 'input_sequencial_numbers.txt'
HISTORICAL_INPUT_SEQUENCIAL_NUMBERSNEG = SEQ_PATTERNS_DIR + os.sep + 'input_sequencial_numbersneg.txt'
HISTORICAL_OUTPUT_SEQUENCIAL_NUMBERS = SEQ_PATTERNS_DIR + os.sep + '"output_seq.txt'
HISTORICAL_OUTPUT_SEQUENCIAL_NUMBERSNEG = SEQ_PATTERNS_DIR + os.sep + '"output_seq_neg.txt'
VULNERABILITY_FILE = RESOURCE_DIR + os.sep + 'Vulnerability_Version_20061101_Date_20220913.xlsx'
HISTORICAL_INPUT_SEQUENCIAL_IN_OUT = SEQ_PATTERNS_DIR + os.sep + 'input_sequencial_in_out.txt'
HISTORICAL_OUTPUT_SEQUENCIAL_IN_OUT = SEQ_PATTERNS_DIR + os.sep + 'output_seq_in_out.txt'
HISTORICAL_DB_KEEP_OUT = RESOURCE_DIR + os.sep + 'databases_keep_out.xlsx'
VULNERABILITY_LABELS = RESOURCE_DIR + os.sep + 'vulnetabilities_labels.xlsx'


DATABASE_CONFIG_FILE = BASE_DIR + os.sep + 'database.json'

def bold(string):
    return '\033[1m' + string + '\033[0m'


def red(string):
    return '\033[31m' + string + '\033[0m'


def green(string):
    return '\033[32m' + string + '\033[0m'


def yellow(string):
    return '\033[33m' + string + '\033[0m'


def get_database_uri(database_name):
    return BASE_DIR + os.sep + database_name


def filter_repositories(df, filters, sysexit=True):
    """Apply regex filters in repositories df"""
    df['reponame'] = df["owner"] + "/" + df["name"]
    if filters:
        condition = (df['reponame'] == '') | False
        for filter in filters:
            condition = condition | df['reponame'].str.match(filter)
        df = df[condition]
    if len(df) == 0 and sysexit:
        print('No repositories found. Exiting.', file=sys.stderr)
        sys.exit(1)
    del df['reponame']
    return df
