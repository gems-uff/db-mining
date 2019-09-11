import os.path
import sqlite3

from sqlalchemy import Column, Integer, String, create_engine, ForeignKey, Boolean, Table
from sqlalchemy.ext.declarative import declarative_base, declared_attr
from sqlalchemy.orm import sessionmaker, relationship

from util import DATABASE_FILE, SCHEMA_FILE

db_conn = None  # Connection to the database
session = None


###########################################
# SQLALCHEMY CLASSES
###########################################

class Base(object):
    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()

    id = Column(Integer, primary_key=True)

    def __repr__(self):
        attr = vars(self).copy()
        del attr['_sa_instance_state']
        return str(attr)


Base = declarative_base(cls=Base)


class Project(Base):
    owner = Column(String)
    name = Column(String)
    createdAt = Column(String)
    pushedAt = Column(String)
    isMirror = Column(Boolean)
    diskUsage = Column(Integer)
    languages = Column(Integer)
    contributors = Column(Integer)
    watchers = Column(Integer)
    stargazers = Column(Integer)
    forks = Column(Integer)
    issues = Column(Integer)
    commits = Column(Integer)
    pullRequests = Column(Integer)
    branches = Column(Integer)
    tags = Column(Integer)
    releases = Column(Integer)
    description = Column(String)
    primaryLanguage = Column(String)
    domain = Column(String)
    versions = relationship("Version", back_populates="project")


version_label = Table('version_label',
                      Base.metadata,
                      Column('version_id', Integer, ForeignKey('version.id')),
                      Column('label_id', Integer, ForeignKey('label.id')))


class Version(Base):
    sha1 = Column(String)
    isLast = Column(Boolean)
    createdAt = Column(String)
    project_id = Column(Integer, ForeignKey('project.id'))
    project = relationship("Project", back_populates="versions")
    labels = relationship('Label', secondary=version_label, back_populates="versions")
    executions = relationship("Execution", back_populates="version")


label_category = Table('label_category',
                       Base.metadata,
                       Column('label_id', Integer, ForeignKey('label.id')),
                       Column('category_id', Integer, ForeignKey('category.id')),
                       Column('isMain', Boolean))


class Category(Base):
    name = Column(String)
    labels = relationship('Label', secondary=label_category, back_populates="categories")


class Label(Base):
    name = Column(String)
    type = Column(String)
    heuristic = relationship("Heuristic", uselist=False, back_populates="label")
    categories = relationship('Category', secondary=label_category, back_populates="labels")
    versions = relationship('Version', secondary=version_label, back_populates="labels")


class Heuristic(Base):
    pattern = Column(String)
    label_id = Column(Integer, ForeignKey('label.id'))
    label = relationship("Label", back_populates="heuristic")
    executions = relationship("Execution", back_populates="heuristic")


class Execution(Base):
    output = Column(String)
    isValidated = Column(Boolean)
    isAccepted = Column(Boolean)
    heuristic_id = Column(Integer, ForeignKey('heuristic.id'))
    version_id = Column(Integer, ForeignKey('version.id'))
    heuristic = relationship("Heuristic", back_populates="executions")
    version = relationship("Version", back_populates="executions")


def get(model, **kwargs):
    print(f'Session: {session}')
    return session.query(model).filter_by(**kwargs).first()


def create(model, **kwargs):
    instance = model(**kwargs)
    session.add(instance)
    return instance


def get_or_create(model, **kwargs):
    instance = get(model, **kwargs)
    if not instance:
        instance = create(model, **kwargs)
    return instance


def delete(instance):
    session.delete(instance)


###########################################
# DATABASE CONNECT, COMMIT, CLOSE
###########################################

def connect():
    global db_conn, session

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

        engine = create_engine('sqlite:///' + DATABASE_FILE, echo=True)
        Session = sessionmaker(bind=engine)

        session = Session(expire_on_commit=False)
    except db_conn.DatabaseError:
        print(db_conn.Error)


def commit():
    session.commit()


def close():
    session.close()
    db_conn.close()

# def remove_old_projects():
#     """
#     Removes projects that are in the database but were not processed (insertion attempt) since the database connection was established
#     This means the project is NOT in the Excel file and should be removed
#     """
#     global projects_dict
#     global projects_set
#
#     projects_in_database = projects_dict.keys()
#     projects_to_remove = projects_in_database - projects_set
#     print(projects_in_database)
#     print(projects_set)
#     print(projects_to_remove)
#
#     for project in projects_to_remove:
#         print(f'Removing project {project}...')
#         delete_project_by_key(project)
