import os.path
import json

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

from util import DATABASE_FILE, DATABASE_CONFIG_FILE, DATABASE_DEBUG, REACT_STATIC_DIR, REACT_BUILD_DIR

app = Flask(__name__, static_folder=REACT_STATIC_DIR, template_folder=REACT_BUILD_DIR)


app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + DATABASE_FILE
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = DATABASE_DEBUG
db = SQLAlchemy(app)


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
    versions = db.relationship('Version', back_populates='project')


class Version(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sha1 = db.Column(db.String)
    isLast = db.Column(db.Boolean)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id', ondelete='RESTRICT'))
    project = db.relationship('Project', back_populates='versions')
    executions = db.relationship('Execution', back_populates='version')


label_category = db.Table('label_category',
                          db.Column('label_id', db.Integer, db.ForeignKey('label.id', ondelete='RESTRICT')),
                          db.Column('category_id', db.Integer, db.ForeignKey('category.id', ondelete='RESTRICT')),
                          db.Column('isMain', db.Boolean))


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    labels = db.relationship('Label', secondary=label_category, back_populates='categories')


class Label(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    type = db.Column(db.String)
    heuristic = db.relationship('Heuristic', uselist=False, back_populates='label')
    categories = db.relationship('Category', secondary=label_category, back_populates='labels')


class Heuristic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pattern = db.Column(db.String)
    label_id = db.Column(db.Integer, db.ForeignKey('label.id', ondelete='RESTRICT'))
    label = db.relationship('Label', back_populates='heuristic')
    executions = db.relationship('Execution', back_populates='heuristic')


class Execution(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    output = db.Column(db.String)
    isValidated = db.Column(db.Boolean)
    isAccepted = db.Column(db.Boolean)
    heuristic_id = db.Column(db.Integer, db.ForeignKey('heuristic.id', ondelete='RESTRICT'))
    version_id = db.Column(db.Integer, db.ForeignKey('version.id', ondelete='RESTRICT'))
    heuristic = db.relationship('Heuristic', back_populates='executions')
    version = db.relationship('Version', back_populates='executions')


###########################################
# DATABASE CONNECT, COMMIT, CLOSE
###########################################

def connect():
#    db = json.loads(DATABASE_CONFIG_FILE)
#    print(db)
    if not os.path.exists(DATABASE_FILE):
        print('Creating Database...')
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
