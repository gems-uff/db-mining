import os.path
import sqlite3

DB_FILENAME = '../resources/db-mining.db'
DB_SCRIPT = '../resources/create-database.sql'

db_conn = None  # Connection to the database
database_types_dict = None  # dictionary with database types
databases_dict = None  # dictionary with database names
query_strategies_dict = None  # dictionary with query strategies
impl_strategies_dict = None  # dictionary with implementation strategies
heuristics_dict = None  # dictionary with heuristics
languages_dict = None  # dictionary with languages
domains_dict = None  # dictionary with domains
projects_dict = None  # dictionary with projects
projects_set = None  # set with dictionaries that were processed


###########################################
# DATABASE CONNECT, COMMIT, CLOSE
###########################################
def load_database_types_dict():
    global database_types_dict
    sql = 'SELECT * FROM database_type'
    cursor = db_conn.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    for row in results:
        database_types_dict[row[1]] = row[0]


def load_databases_dict():
    global databases_dict
    sql = 'SELECT * FROM database'
    cursor = db_conn.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    for row in results:
        databases_dict[row[1]] = row[0]


def load_query_strategies_dict():
    global query_strategies_dict
    sql = 'SELECT * FROM query_strategy'
    cursor = db_conn.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    for row in results:
        query_strategies_dict[row[1]] = row[0]


def load_impl_strategies_dict():
    global impl_strategies_dict
    sql = 'SELECT * FROM implementation_strategy'
    cursor = db_conn.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    for row in results:
        impl_strategies_dict[row[1]] = row[0]


def load_heuristics_dict():
    global heuristics_dict
    sql = 'SELECT * FROM heuristic'
    cursor = db_conn.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    for row in results:
        key = row[1] + '-' + row[2] + '-' + str(row[3]) + '-' + str(row[4]) + '-' + str(row[5]) + '-' + str(row[6])
        heuristics_dict[key] = row[0]
    print(heuristics_dict)


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


def load_existing_data():
    global database_types_dict
    global databases_dict
    global query_strategies_dict
    global impl_strategies_dict
    global heuristics_dict
    global languages_dict
    global domains_dict
    global projects_dict
    global projects_set

    database_types_dict = {}
    databases_dict = {}
    query_strategies_dict = {}
    impl_strategies_dict = {}
    heuristics_dict = {}
    languages_dict = {}
    domains_dict = {}
    projects_dict = {}
    projects_set = set()
    load_database_types_dict()
    load_databases_dict()
    load_query_strategies_dict()
    load_impl_strategies_dict()
    load_heuristics_dict()
    load_languages_dict()
    load_domains_dict()
    load_projects_dict()


def connect():
    global db_conn

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
    load_existing_data()


def commit():
    db_conn.commit()


def close():
    db_conn.close()


###########################################
# DATABASE INSERT FUNCTIONS
###########################################

def insert_database_type(name):
    global database_types_dict
    type_id = database_types_dict.get(name, 0)
    if type_id == 0:
        # saves database type
        print(f'Inserting {name}')
        sql = 'INSERT INTO database_type (name) VALUES (?)'
        type_id = db_conn.execute(sql, [name]).lastrowid
        database_types_dict[name] = type_id
    return type_id


def insert_database(name, type):
    global databases_dict
    database_id = databases_dict.get(name, 0)

    if database_id == 0:
        # saves database
        type_id = insert_database_type(type)
        print(f'Inserting {name}...')
        sql = 'INSERT INTO database(name, type_id) VALUES(?,?)'
        database_id = db_conn.execute(sql, [name, type_id]).lastrowid
        databases_dict[name] = database_id
    return database_id


def insert_query_strategy(name):
    global query_strategies_dict
    query_strategy_id = query_strategies_dict.get(name, 0)
    if query_strategy_id == 0:
        # saves query strategy type
        print(f'Inserting {name}')
        sql = 'INSERT INTO query_strategy (name) VALUES (?)'
        query_strategy_id = db_conn.execute(sql, [name]).lastrowid
        query_strategies_dict[name] = query_strategy_id
    return query_strategy_id


def insert_impl_strategy(name):
    global impl_strategies_dict
    impl_strategy_id = impl_strategies_dict.get(name, 0)
    if impl_strategy_id == 0:
        # saves implementation strategy type
        print(f'Inserting {name}')
        sql = 'INSERT INTO implementation_strategy (name) VALUES (?)'
        query_strategy_id = db_conn.execute(sql, [name]).lastrowid
        impl_strategies_dict[name] = impl_strategy_id
    return impl_strategy_id


def insert_heuristic(regex, reg_type, database, language, query_strategy, impl_strategy):
    global heuristics_dict
    database_id = None
    language_id = None
    query_strategy_id = None
    impl_strategy_id = None
    if database is not None and database != '':
        database_id = insert_database(database)
    if language is not None and language != '':
        language_id = insert_language(language)
    if query_strategy is not None and query_strategy != '':
        query_strategy_id = insert_query_strategy(query_strategy)
    if impl_strategy is not None and impl_strategy != '':
        impl_strategy_id = insert_impl_strategy(impl_strategy)

    key = regex + '-' + reg_type + '-' + str(database_id) + '-' + str(language_id) + '-' + str(query_strategy_id) + '-' + str(impl_strategy_id)
    heuristic_id = heuristics_dict.get(key, 0)

    if heuristic_id == 0:
        # saves heuristic
        print(f'Inserting {key}...')
        sql = 'INSERT INTO heuristic(regex, type, database_id, language_id, query_strategy_id, implementation_strategy_id) VALUES(?,?,?,?,?,?)'
        heuristic_id = db_conn.execute(sql, [regex, reg_type, database_id, language_id, query_strategy_id, impl_strategy_id]).lastrowid
        heuristics_dict[key] = heuristic_id
    return heuristic_id


def insert_language(name):
    global languages_dict
    language_id = languages_dict.get(name, 0)
    if language_id == 0:
        # saves language
        print(f'Inserting {name}')
        sql = 'INSERT INTO language (name) VALUES (?)'
        language_id = db_conn.execute(sql, [name]).lastrowid
        languages_dict[name] = language_id
    return language_id


def insert_domain(name):
    global domains_dict
    domain_id = domains_dict.get(name, 0)
    if domain_id == 0:
        # saves domain
        print(f'Inserting {name}')
        sql = 'INSERT INTO domain (name) VALUES (?)'
        domain_id = db_conn.execute(sql, [name]).lastrowid
        domains_dict[name] = domain_id
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
        project_id = db_conn.execute(sql, [project['owner'], project['name'], createdAt, pushedAt, project['isMirror'],
                                           project['diskUsage'], project['languages'], project['contributors'],
                                           project['watchers'], project['stargazers'], project['forks'],
                                           project['issues'], project['commits'], project['pullRequests'],
                                           project['branches'], project['tags'], project['releases'],
                                           project['description'], language_id, domain_id]).lastrowid
        projects_dict[key] = project_id
    else:
        print(f'Skipping project {project["owner"]}/{project["name"]}...')
    return project_id


###########################################
# DATABASE GET FUNCTIONS
###########################################

def get_database_type_id(name):
    database_type_id = database_types_dict.get(name, 0)
    return database_type_id


def get_database_id(name):
    database_id = databases_dict.get(name, 0)
    return database_id


def get_language_id(name):
    language_id = languages_dict.get(name, 0)
    return language_id


def get_domain_id(name):
    domain_id = domains_dict.get(name, 0)
    return domain_id


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
    global languages_dict
    sql = 'DELETE FROM language WHERE language_id = ?'
    language_id = languages_dict.get(language)
    db_conn.execute(sql, [language_id])
    languages_dict.pop(language)  # removes language from the dictionary


def delete_language_by_id(language_id):
    global languages_dict
    sql = 'DELETE FROM language WHERE language_id = ?'
    db_conn.execute(sql, [language_id])
    language_name = (list(languages_dict.keys())[list(languages_dict.values()).index(language_id)])
    languages_dict.pop(language_name)  # removes language from the dictionary


def delete_domain(domain):
    global domains_dict
    sql = 'DELETE FROM domain WHERE domain_id = ?'
    domain_id = domains_dict.get(domain)
    db_conn.execute(sql, [domain_id])
    domains_dict.pop(domain)  # removes domain from dictionary


def delete_domain_by_id(domain_id):
    global domains_dict
    sql = 'DELETE FROM domain WHERE domain_id = ?'
    db_conn.execute(sql, [domain_id])
    domain_name = (list(domains_dict.keys())[list(domains_dict.values()).index(domain_id)])
    domains_dict.pop(domain_name)  # removes domain from the dictionary


def delete_project(owner, name):
    global projects_dict
    global projects_set
    key = owner + name
    sql = 'DELETE FROM project WHERE project_id = ?'
    project_id = projects_dict.get(key)
    db_conn.execute(sql, [project_id])
    projects_dict.pop(key)  # removes project from dictionary
    if key in projects_set:
        projects_set.remove(key)  # removes project from set of processed projects


def delete_project_by_id(project_id):
    global projects_dict
    global projects_set
    sql = 'DELETE FROM project WHERE project_id = ?'
    db_conn.execute(sql, [project_id])
    project_key = (list(projects_dict.keys())[list(projects_dict.values()).index(project_id)])
    projects_dict.pop(project_key)  # removes project from the dictionary
    if project_key in projects_set:
        projects_set.remove(project_key)  # removes project from set of processed projects


def remove_old_projects():
    """
    Removes projects that are in the database but were not processed (insertion attempt) since the database connection was established
    This means the project is NOT in the Excel file and should be removed
    """
    global projects_dict
    global projects_set

    projects_in_database = projects_dict.keys()
    projects_to_remove = projects_in_database - projects_set

    for project in projects_to_remove:
        print(f'Removing project {project}...')
        delete_project(project[0])
        projects_dict.pop(project[1] + project[2])  # removes project from dictionary
        projects_set.remove(project[1] + project[2])  # removes project from set of processed projects


def main():
    connect()
    insert_heuristic('teste', 'database', None, 'Java', None, None)
    insert_heuristic('teste', 'database', None, 'Java', None, None)
    print(heuristics_dict)
    commit()
    close()

if __name__ == '__main__':
    main()
