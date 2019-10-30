import json

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy_utils import database_exists, create_database, drop_database

from util import DATABASE_DEBUG, REACT_STATIC_DIR, REACT_BUILD_DIR, DATABASE_CONFIG_FILE, get_database_uri

application = Flask(__name__, static_folder=REACT_STATIC_DIR, template_folder=REACT_BUILD_DIR)

application.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
application.config['SQLALCHEMY_ECHO'] = DATABASE_DEBUG

# for SQLite, the JSON file needs to have "database_type": "sqlite"
# for PostgreSQL, the JSON file needs to have
# "database_type": "postgresql",
# "host": "myhostname",
# "port" : "port",
# "username": "myusername",
# "password": "mypassword"

# The drop_database flag indicates whether the user wants to drop the current database and create a new empty one
# "drop_database": "False",

with open(DATABASE_CONFIG_FILE) as json_file:
    config = json.load(json_file)

if config['database_type'].lower() == 'sqlite':
    application.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + get_database_uri(config['database_name'])
elif config['database_type'].lower() == 'postgresql':
    application.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://' + config['username'] + ':' + config['password'] + '@' + config['host'] + ':' + config['port'] + '/' + config['database_name']

db = SQLAlchemy(application, session_options={"expire_on_commit": False})


###########################################
# SQLALCHEMY CLASSES
###########################################

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String)
    name = db.Column(db.String)
    createdAt = db.Column(db.String)
    pushedAt = db.Column(db.String)
    isMirror = db.Column(db.Boolean)
    diskUsage = db.Column(db.Integer)
    languages = db.Column(db.Integer)
    contributors = db.Column(db.Integer)
    watchers = db.Column(db.Integer)
    stargazers = db.Column(db.Integer)
    forks = db.Column(db.Integer)
    issues = db.Column(db.Integer)
    commits = db.Column(db.Integer)
    pullRequests = db.Column(db.Integer)
    branches = db.Column(db.Integer)
    tags = db.Column(db.Integer)
    releases = db.Column(db.Integer)
    description = db.Column(db.String)
    primaryLanguage = db.Column(db.String)
    domain = db.Column(db.String)
    versions = db.relationship('Version', back_populates='project', cascade="all, delete-orphan")


class Version(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sha1 = db.Column(db.String)
    isLast = db.Column(db.Boolean)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'))
    project = db.relationship('Project', back_populates='versions')
    executions = db.relationship('Execution', back_populates='version', cascade="all, delete-orphan")


label_category = db.Table('label_category',
                          db.Column('label_id', db.Integer, db.ForeignKey('label.id')),
                          db.Column('category_id', db.Integer, db.ForeignKey('category.id')),
                          db.Column('isMain', db.Boolean))


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    labels = db.relationship('Label', secondary=label_category, back_populates='categories')


class Label(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    type = db.Column(db.String)
    heuristic = db.relationship('Heuristic', uselist=False, back_populates='label', cascade="all, delete-orphan")
    categories = db.relationship('Category', secondary=label_category, back_populates='labels')


class Heuristic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pattern = db.Column(db.String)
    label_id = db.Column(db.Integer, db.ForeignKey('label.id'))
    label = db.relationship('Label', back_populates='heuristic')
    executions = db.relationship('Execution', back_populates='heuristic', cascade="all, delete-orphan")


class Execution(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    output = db.Column(db.String)
    isValidated = db.Column(db.Boolean)
    isAccepted = db.Column(db.Boolean)
    user = db.Column(db.String)
    heuristic_id = db.Column(db.Integer, db.ForeignKey('heuristic.id'))
    version_id = db.Column(db.Integer, db.ForeignKey('version.id'))
    heuristic = db.relationship('Heuristic', back_populates='executions')
    version = db.relationship('Version', back_populates='executions')


###########################################
# DATABASE CONNECT, COMMIT, CLOSE
###########################################

def connect():
    if config['drop_database'] == 'True':
        print('Deleting database...')
        drop_database(application.config['SQLALCHEMY_DATABASE_URI'])

    if not database_exists(application.config['SQLALCHEMY_DATABASE_URI']):
        print('Creating Database...')
        create_database(application.config['SQLALCHEMY_DATABASE_URI'])
        db.create_all()


def commit():
    db.session.commit()


def close():
    db.session.close()


###########################################
# DATABASE ACCESSOR METHODS
###########################################

def query(*model, **kwargs):
    return db.session.query(*model).filter_by(**kwargs)


def create(model, **kwargs):
    instance = model(**kwargs)
    db.session.add(instance)
    return instance


def get_or_create(model, **kwargs):
    instance = query(model, **kwargs).first()
    if not instance:
        instance = create(model, **kwargs)
    return instance


def add(instance):
    db.session.add(instance)


def delete(instance):
    db.session.delete(instance)


def main():
    connect()


if __name__ == "__main__":
    main()
