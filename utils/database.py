import os.path
import sqlite3

DB_FILENAME = '../resources/db-mining.db'
DB_SCRIPT = '../resources/create-database.sql'

db_conn = None  # Connection to the database
languages_dict = None # dictionary with languages
domains_dict = None # dictionary with domains
projects_dict = None # dictionary with projects
projects_set = None # set with dictionaries that were processed

###########################################
# DATABASE CONNECT, COMMIT, CLOSE
###########################################

def load_languages_dict():
    global languages_dict
    sql = 'SELECT * FROM language'
    cursor = db_conn.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    for row in results:
        languages_dict[row[1]] = row[0]

def load_domains_dict():
    global domains_dict
    sql = 'SELECT * FROM domain'
    cursor = db_conn.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    for row in results:
        domains_dict[row[1]] = row[0]

def load_projects_dict():
    global projects_dict
    sql = 'SELECT * FROM project'
    cursor = db_conn.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    for row in results:
        key = row[1] + row[2]
        projects_dict[key] = row[0]

def connect():
    global db_conn
    global languages_dict
    global domains_dict
    global projects_dict
    global projects_set

    db_path = os.path.abspath(DB_FILENAME)
    new_db = not os.path.exists(db_path)
    db_conn = sqlite3.connect(db_path)
    if new_db:
        print('Creating Database...')
        script_path = os.path.abspath(DB_SCRIPT)
        f = open(script_path, 'r')
        sqlFile = f.read()
        f.close()

        # all SQL commands (split on ';')
        sqlCommands = sqlFile.split(';')
        # Execute every command from the input file
        for command in sqlCommands:
            db_conn.execute(command)
        db_conn.commit()

    # if there is data in the database, load it
    languages_dict = {}
    domains_dict = {}
    projects_dict = {}
    projects_set = set()
    load_languages_dict()
    load_domains_dict()
    load_projects_dict()

def commit():
    db_conn.commit()

def close():
    db_conn.close()

###########################################
# DATABASE INSERT FUNCTIONS
###########################################

def insert_language(language):
    global languages_dict
    language_id = languages_dict.get(language, 0)
    if language_id == 0:
        # saves language
        print(f'Inserting {language}')
        sql = 'INSERT INTO language (name) VALUES (?)'
        language_id = db_conn.execute(sql, [language]).lastrowid
        languages_dict[language] = language_id
    return language_id

def insert_domain(domain):
    global domains_dict
    domain_id = domains_dict.get(domain, 0)
    if domain_id == 0:
        # saves domain
        print(f'Inserting {domain}')
        sql = 'INSERT INTO domain (name) VALUES (?)'
        domain_id = db_conn.execute(sql, [domain]).lastrowid
        domains_dict[domain] = domain_id
    return domain_id

def insert_project(project):
    global projects_dict
    global projects_set
    key = project['owner'] + project['name']
    projects_set.add(key)
    project_id = projects_dict.get(key, 0)

    if project_id == 0:
        # saves project
        language_id = insert_language(project['primaryLanguage'])
        domain_id = insert_domain(project['domain'])
        print(f'Inserting {project["owner"]}/{project["name"]}...')
        createdAt = str(project['createdAt'])
        pushedAt = str(project['pushedAt'])

        sql = 'INSERT INTO project(owner, name, createdAt, pushedAt, isMirror, diskUsage, languages, contributors, watchers, stargazers, forks, issues, commits, pullRequests, branches, tags, releases, description, language_id, domain_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'
        project_id = db_conn.execute(sql, [project['owner'], project['name'], createdAt, pushedAt, project['isMirror'], project['diskUsage'], project['languages'], project['contributors'], project['watchers'], project['stargazers'], project['forks'], project['issues'], project['commits'], project['pullRequests'], project['branches'], project['tags'], project['releases'], project['description'], language_id, domain_id]).lastrowid
        projects_dict[key] = project_id
    else:
        print(f'Skipping project {project["owner"]}/{project["name"]}...')
    return project_id

###########################################
# DATABASE GET FUNCTIONS
###########################################

def get_project_id(owner, name):
    key = owner + name
    project_id = projects_dict.get(key, 0)
    return project_id

def get_project(projec_id):
    sql = 'SELECT * FROM project WHERE project_id = ?'
    cursor = db_conn.cursor()
    cursor.execute(sql, [projec_id])
    project = cursor.fetchone()
    return project

###########################################
# DATABASE DELETE FUNCTIONS
###########################################

def delete_language(language):
    sql = 'DELETE FROM language WHERE language_id = ?'
    language_id = domains_dict.get(language)
    db_conn.execute(sql, [language_id])

def delete_language_by_id(language_id):
    sql = 'DELETE FROM language WHERE language_id = ?'
    db_conn.execute(sql, [language_id])

def delete_domain(domain):
    sql = 'DELETE FROM domain WHERE domain_id = ?'
    domain_id = domains_dict.get(domain)
    db_conn.execute(sql, [domain_id])

def delete_domain_by_id(domain_id):
    sql = 'DELETE FROM domain WHERE domain_id = ?'
    db_conn.execute(sql, [domain_id])

def delete_project(owner, name):
    global projects_dict
    global projects_set
    key = owner + name
    sql = 'DELETE FROM project WHERE project_id = ?'
    project_id = projects_dict.get(key)
    db_conn.execute(sql, [project_id])

def delete_project(project_id):
    sql = 'DELETE FROM project WHERE project_id = ?'
    db_conn.execute(sql, [project_id])

# Removes projects that are in the database but were not inserted since the database connection was established
def remove_old_projects():
    projects_in_database = projects_dict.keys()
    projects_to_remove = projects_in_database - projects_set

    for project in projects_to_remove:
        print(f'Removing project {project}...')
        delete_project(project[0])
