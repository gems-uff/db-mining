import os

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

REACT_BUILD_DIR = BASE_DIR + os.sep + 'web' + os.sep + 'build'
REACT_STATIC_DIR = REACT_BUILD_DIR + os.sep + 'static'

# Files
PROJECTS_FILE = RESOURCE_DIR + os.sep + 'projects.xlsx'
FILTERED_FILE = RESOURCE_DIR + os.sep + 'filtered_projects.xlsx'
ANNOTATED_FILE = RESOURCE_DIR + os.sep + 'annotated.xlsx'
DBLP_FILE = RESOURCE_DIR + os.sep + 'dblp.xml'
VENUE_KEYS = RESOURCE_DIR + os.sep + 'venue_keys.txt'
PAPERS_FILE = RESOURCE_DIR + os.sep + 'papers.xlsx'
FILTERED_PAPERS_FILE = RESOURCE_DIR + os.sep + 'filtered_papers.xlsx'

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