import os

# Flags
DEBUG = False

# Directories
SRC_DIR = os.path.dirname(os.path.realpath(__file__))
BASE_DIR = os.path.dirname(SRC_DIR)
REPOS_DIR = BASE_DIR + os.sep + 'repos'
RESOURCE_DIR = BASE_DIR + os.sep + "resources"
HEURISTICS_DIR = RESOURCE_DIR + os.sep + 'heuristics'

# Files
PROJECTS_FILE = RESOURCE_DIR + os.sep + 'projects.xlsx'
FILTERED_FILE = RESOURCE_DIR + os.sep + 'filtered.xlsx'
ANNOTATED_FILE = RESOURCE_DIR + os.sep + 'annotated.xlsx'

SCHEMA_FILE = RESOURCE_DIR + os.sep + 'create-database.sql'
DATABASE_FILE = RESOURCE_DIR + os.sep + 'db-mining.db'


def bold(string):
    return '\033[1m' + string + '\033[0m'


def red(string):
    return '\033[31m' + string + '\033[0m'


def green(string):
    return '\033[32m' + string + '\033[0m'


def yellow(string):
    return '\033[33m' + string + '\033[0m'