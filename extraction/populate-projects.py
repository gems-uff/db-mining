import sqlite3
from sqlite3 import Error
import pandas as pd

# File to load the data with repositories
REPO_FILE = '../resources/annotated.xlsx'

def create_connection(db_file):
    conn = None
    try:
        conn = sqlite3.connect(db_file)
    except Error as e:
        print(e)
    return conn

def create_tables(conn):
    try:
        c = conn.cursor()
        fd = open('../resources/create-database.sql', 'r')
        sqlFile = fd.read()
        fd.close()

        # all SQL commands (split on ';')
        sqlCommands = sqlFile.split(';')

        # Execute every command from the input file
        for command in sqlCommands:
            c.execute(command)
        conn.commit()
    except Error as e:
        print(e)

def load_languages_dict(connection):
    sql = 'SELECT * FROM language'
    cursor = connection.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    languages = {}
    for row in results:
        languages[row[1]] = row[0]
    print(languages)
    return languages

def load_domains_dict(connection):
    sql = 'SELECT * FROM domain'
    cursor = connection.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    domains = {}
    for row in results:
        domains[row[1]] = row[0]
    print(domains)
    return domains

def load_projects_dict(connection):
    sql = 'SELECT * FROM project'
    cursor = connection.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    projects = {}
    for row in results:
        key = row[1] + row[2]
        projects[key] = row[0]
    print(projects)
    return projects

def check_insert_language(connection, language, languages_dict):
    language_id = languages_dict.get(language, 0)
    if language_id == 0:
        # saves language
        print(f'Inserting {language}')
        sql = 'INSERT INTO language (name) VALUES (?)'
        cur = connection.cursor()
        cur.execute(sql, [language])
        language_id = cur.lastrowid
        languages_dict[language] = language_id
    print(languages_dict)
    return language_id

def check_insert_domain(connection, domain, domains_dict):
    domain_id = domains_dict.get(domain, 0)
    if domain_id == 0:
        # saves domain
        print(f'Inserting {domain}')
        sql = 'INSERT INTO domain (name) VALUES (?)'
        cur = connection.cursor()
        cur.execute(sql, [domain])
        domain_id = cur.lastrowid
        domains_dict[domain] = domain_id
    print(domains_dict)
    return domain_id

def check_insert_project(connection, project, projects_dict, languages_dict, domains_dict):
    key = project['owner'] + project['name']
    project_id = projects_dict.get(key, 0)

    if project_id == 0:
        # saves project
        language_id = check_insert_language(connection, project['primaryLanguage'], languages_dict)
        domain_id = check_insert_domain(connection, project['domain'], domains_dict)
        print(f'Inserting {project["owner"]}/{project["name"]}...')
        createdAt = str(project['createdAt'])
        pushedAt = str(project['pushedAt'])

        sql = 'INSERT INTO project(owner, name, createdAt, pushedAt, isMirror, diskUsage, languages, contributors, watchers, stargazers, forks, issues, commits, pullRequests, branches, tags, releases, description, language_id, domain_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'
        cur = connection.cursor()
        cur.execute(sql, [project['owner'], project['name'], createdAt, pushedAt, project['isMirror'], project['diskUsage'], project['languages'], project['contributors'], project['watchers'], project['stargazers'], project['forks'], project['issues'], project['commits'], project['pullRequests'], project['branches'], project['tags'], project['releases'], project['description'], language_id, domain_id])
        project_id = cur.lastrowid
        projects_dict[key] = project_id
    else:
        print(f'Skipping project {project["owner"]}/{project["name"]}...')
    print(projects_dict)
    return project_id

def main():
    database = '../resources/db-mining.db'

    # create a database connection
    conn = create_connection(database)

    # create tables
    if conn is not None:
        # create tables
        create_tables(conn)

    print(f'Loading repositories from {REPO_FILE}...')
    df = pd.read_excel(REPO_FILE, keep_default_na=False)
    # removing discarded repositories
    df = df[df.discardReason == '']

    print(f'Loading data from the database...')
    languages_dict = load_languages_dict(conn)
    domains_dict = load_domains_dict(conn)
    projects_dict = load_projects_dict(conn)

    total = len(df)
    print(f'Processing {total} projects...')

    with conn:
        for i, row in df.iterrows():
            print(f'\nProcessing repository {row["owner"]}/{row["name"]}.')
            project_id = check_insert_project(conn, row, projects_dict, languages_dict, domains_dict)

    print('Commiting changes...')
    conn.commit()
    print('Closing database connection...')
    conn.close()

if __name__ == '__main__':
    main()
