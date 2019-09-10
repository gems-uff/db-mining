import os.path
import sqlite3

from util import DATABASE_FILE, SCHEMA_FILE

db_conn = None  # Connection to the database
categories_dict = None  # dictionary with categories
labels_by_name = None  # dictionary with labels
heuristics_by_label_id = None  # dictionary with heuristics
projects_dict = None  # dictionary with projects
projects_set = None  # set with dictionaries that were processed
projects_versions_dict = None  # dictionary with project versions


def sub_dict(super_dict, keys):
    return dict((k, super_dict[k]) for k in keys)

###########################################
# DATABASE CONNECT, COMMIT, CLOSE
###########################################

def load(table_name, key, cache):
    cursor = db_conn.cursor()
    cursor.execute(f'SELECT * FROM {table_name}')
    for row in cursor:
        cache[row[key]] = dict(row)


def load_categories_dict():
    global categories_dict
    sql = 'SELECT * FROM category'
    cursor = db_conn.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    for row in results:
        categories_dict[row[1]] = row[0]


def load_projects_dict():
    global projects_dict
    sql = 'SELECT * FROM project'
    cursor = db_conn.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    for row in results:
        key = row[1] + row[2]
        projects_dict[key] = row[0]


def load_projects_versions():
    global projects_versions_dict
    sql = 'SELECT * FROM project_version'
    cursor = db_conn.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    for row in results:
        projects_versions_dict[row[1]] = row[0]


def load_existing_data():
    global categories_dict
    global labels_by_name
    global heuristics_by_label_id
    global projects_dict
    global projects_set
    global projects_versions_dict

    categories_dict = {}
    labels_by_name = {}
    heuristics_by_label_id = {}
    projects_dict = {}
    projects_set = set()
    projects_versions_dict = {}
    load_categories_dict()
    load('label', 'name', labels_by_name)
    load('heuristic', 'label_id', heuristics_by_label_id)
    load_projects_dict()
    load_projects_versions()


def connect():
    global db_conn

    new_db = not os.path.exists(DATABASE_FILE)
    db_conn = sqlite3.connect(DATABASE_FILE)
    db_conn.row_factory = sqlite3.Row
    try:
        if new_db:
            print('Creating Database...')
            f = open(SCHEMA_FILE, 'r')
            sql_file = f.read()
            f.close()

            # all SQL commands (split on ';')
            sql_commands = sql_file.split(';')
            # Execute every command from the input file
            for command in sql_commands:
                db_conn.execute(command)
            db_conn.commit()

        # if there is data in the database, load it
        load_existing_data()
    except db_conn.DatabaseError:
        print(db_conn.Error)


def close():
    db_conn.close()


###########################################
# DATABASE INSERT FUNCTIONS
###########################################

def insert_category(name):
    global categories_dict
    category_id = categories_dict.get(name, None)
    if category_id is None:
        # saves category
        print(f'Inserting category: {name}')
        sql = 'INSERT INTO category (name) VALUES (?)'
        category_id = db_conn.execute(sql, [name]).lastrowid
        categories_dict[name] = category_id
    return category_id


def insert_label(label):
    global labels_by_name

    existing_label = labels_by_name.get(label['name'], None)
    if not existing_label:
        try:  # saves label
            cursor = db_conn.cursor()  # starts transaction
            sql = 'INSERT INTO label(name, type) VALUES (?,?)'
            label['id'] = cursor.execute(sql, [label['name'], label['type']]).lastrowid
            labels_by_name[label['name']] = label
        except db_conn.DatabaseError:
            db_conn.rollback()
        else:
            db_conn.commit()
    else:
        label = existing_label

    return label


def insert_heuristic(heuristic):
    global heuristics_by_label_id

    label = insert_label(sub_dict(heuristic, ['name', 'type']))
    heuristic['label_id'] = label['id']

    existing_heuristic = heuristics_by_label_id.get(label['name'], None)
    if not existing_heuristic:
        try:  # saves heuristic
            cursor = db_conn.cursor()  # starts transaction
            sql = 'INSERT INTO heuristic(pattern, label_id) VALUES(?,?)'
            heuristic['id'] = cursor.execute(sql, [heuristic['pattern'], heuristic['label_id']]).lastrowid
            heuristics_by_label_id[heuristic['name']] = sub_dict(heuristic, ['id', 'pattern', 'label_id'])
        except db_conn.DatabaseError:
            db_conn.rollback()
        else:
            db_conn.commit()
    return heuristic


def insert_execution(sha1, pattern, output, validated, accepted):
    execution_id = 0
    project_version_id = get_project_version_id(sha1)
    heuristic_id = get_heuristic_id(pattern)
    if heuristic_id is not None and project_version_id is not None:
        try:
            cursor = db_conn.cursor()  # starts transaction
            # saves execution
            sql = 'INSERT INTO execution(output, validated, accepted, heuristic_id, project_version_id) VALUES(?,?,?,?,?)'
            execution_id = cursor.execute(sql,
                                          [output, validated, accepted, heuristic_id, project_version_id]).lastrowid
        except db_conn.DatabaseError:
            db_conn.rollback()
        else:
            db_conn.commit()
    else:
        if project_version_id is None:
            print(f'ERROR: project version {sha1} not found...')
        if heuristic_id is None:
            print(f'ERROR: heuristic {pattern} not found...')
    return execution_id


def insert_project(project):
    global projects_dict
    global projects_set
    key = project['owner'] + project['name']
    projects_set.add(key)
    project_id = projects_dict.get(key, None)

    if project_id is None:
        # saves project
        try:
            cursor = db_conn.cursor()  # starts transaction
            print(f'Inserting project: {project["owner"]}/{project["name"]}...')
            createdAt = str(project['createdAt'])
            pushedAt = str(project['pushedAt'])

            sql = 'INSERT INTO project(owner, name, createdAt, pushedAt, isMirror, diskUsage, languages, contributors, watchers, stargazers, forks, issues, commits, pullRequests, branches, tags, releases, description, primaryLanguage, domain) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'
            project_id = cursor.execute(sql,
                                        [project['owner'], project['name'], createdAt, pushedAt, project['isMirror'],
                                         project['diskUsage'], project['languages'], project['contributors'],
                                         project['watchers'], project['stargazers'], project['forks'],
                                         project['issues'], project['commits'], project['pullRequests'],
                                         project['branches'], project['tags'], project['releases'],
                                         project['description'], project['primaryLanguage'],
                                         project['domain']]).lastrowid
            projects_dict[key] = project_id
        except db_conn.DatabaseError:
            db_conn.rollback()
        else:
            db_conn.commit()
    else:
        print(f'Skipping project {project["owner"]}/{project["name"]}...')
    return project_id


def insert_project_version(owner, name, sha1, last):
    global projects_versions_dict
    key = owner + name
    project_id = projects_dict.get(key, None)
    project_version_id = None
    if project_id is not None:
        project_version_id = projects_versions_dict.get(sha1, None)
        if project_version_id is None:
            # saves project version
            try:
                cursor = db_conn.cursor()  # starts transaction
                print(f'Inserting project version: {owner}/{name}; sha1={sha1} ...')
                sql = 'INSERT INTO project_version(sha1, last, project_id) VALUES(?,?,?)'
                project_version_id = cursor.execute(sql, [sha1, last, project_id]).lastrowid
                projects_versions_dict[sha1] = project_version_id
            except db_conn.DatabaseError:
                db_conn.rollback()
            else:
                db_conn.commit()
    else:
        print(f'ERROR: project {owner}/{name} not found...')
    return project_version_id


def insert_project_version_label(owner, name, sha1, label, label_type, category, is_main):
    project_version_id = projects_versions_dict.get(sha1, None)
    if project_version_id is not None:
        # saves project version label
        try:
            cursor = db_conn.cursor()  # starts transaction
            label_id = insert_label(label, label_type, category, is_main)
            print(f'Inserting project version label: {owner}/{name}; sha1={sha1}; label={label} ...')
            sql = 'INSERT INTO project_version_label(project_version_id, label_id) VALUES(?,?)'
            cursor.execute(sql, [project_version_id, label_id])
        except db_conn.DatabaseError:
            db_conn.rollback()
        else:
            db_conn.commit()
    else:
        print(f'ERROR: project {owner}/{name} version {sha1} not found...')


###########################################
# DATABASE GET FUNCTIONS
###########################################

def get_label_group_id(name):
    group_id = categories_dict.get(name, None)
    return group_id


def get_label(name):
    return labels_by_name.get(name, None)


def get_project_id_by_key(project_key):
    project_id = projects_dict.get(project_key, None)
    return project_id


def get_project_id(owner, name):
    project_id = get_project_id_by_key(owner + name)
    return project_id


def get_project(project_id):
    sql = 'SELECT * FROM project WHERE project_id = ?'
    cursor = db_conn.cursor()
    cursor.execute(sql, [project_id])
    project = cursor.fetchone()
    return project


def get_project_version_id(sha1):
    project_version_id = projects_versions_dict.get(sha1, None)
    return project_version_id


def get_heuristic_id(pattern):
    heuristic_id = heuristics_by_label_id.get(pattern, None)
    return heuristic_id


def get_heuristic_by_label_id(label_id):
    return heuristics_by_label_id.get(label_id, None)


###########################################
# DATABASE DELETE FUNCTIONS
###########################################

def delete_project(owner, name):
    global projects_dict
    global projects_set
    key = owner + name
    project_id = projects_dict.get(key, None)
    if project_id is not None:
        try:
            cursor = db_conn.cursor()  # starts transaction
            sql = 'DELETE FROM project WHERE project_id = ?'
            cursor.execute(sql, [project_id])
            projects_dict.pop(key)  # removes project from dictionary
            if key in projects_set:
                projects_set.remove(key)  # removes project from set of processed projects
        except db_conn.DatabaseError:
            db_conn.rollback()
        else:
            db_conn.commit()
    else:
        print(f'ERROR: project {owner}/{name} not found...')


def delete_project_by_id(project_id):
    global projects_dict
    global projects_set
    try:
        cursor = db_conn.cursor()  # starts transaction
        sql = 'DELETE FROM project WHERE project_id = ?'
        cursor.execute(sql, [project_id])
        project_key = (list(projects_dict.keys())[list(projects_dict.values()).index(project_id)])
        projects_dict.pop(project_key)  # removes project from the dictionary
        if project_key in projects_set:
            projects_set.remove(project_key)  # removes project from set of processed projects
    except db_conn.DatabaseError:
        db_conn.rollback()
    else:
        db_conn.commit()


def delete_project_by_key(project_key):
    project_id = get_project_id_by_key(project_key)
    delete_project_by_id(project_id)


def delete_project_version_by_id(project_version_id):
    global projects_versions_dict
    try:
        cursor = db_conn.cursor()  # starts transaction
        sql = 'DELETE FROM project_version WHERE project_version_id = ?'
        cursor.execute(sql, [project_version_id])
        sha1 = (list(projects_versions_dict.keys())[list(projects_versions_dict.values()).index(project_version_id)])
        projects_versions_dict.pop(sha1)  # removes project version from the dictionary
    except db_conn.DatabaseError:
        db_conn.rollback()
    else:
        db_conn.commit()


def delete_by_id(table_name, row_id, cache, key):
    try:
        cursor = db_conn.cursor()  # starts transaction
        cursor.execute('DELETE FROM ? WHERE id = ?', [table_name, row_id])
        del cache[key]
    except db_conn.DatabaseError:
        db_conn.rollback()
    else:
        db_conn.commit()


def delete_heuristic(heuristic):
    delete_by_id('heuristic', heuristic['id'], heuristics_by_label_id, heuristic['label_id'])


def remove_old_projects():
    """
    Removes projects that are in the database but were not processed (insertion attempt) since the database connection was established
    This means the project is NOT in the Excel file and should be removed
    """
    global projects_dict
    global projects_set

    projects_in_database = projects_dict.keys()
    projects_to_remove = projects_in_database - projects_set
    print(projects_in_database)
    print(projects_set)
    print(projects_to_remove)

    for project in projects_to_remove:
        print(f'Removing project {project}...')
        delete_project_by_key(project)


connect()  # Connects to the database if someone imports this module
