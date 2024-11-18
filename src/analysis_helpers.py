import re
import os
from util import VARIABLES

RELATIONAL_ONLY_DBS = ['Oracle', 'MySQL', 'MS SQL Server', 'PostgreSQL', 'IBM DB2', 
                  'MS Access', 'SQLite',  'Snowflake', 'Teradata', 'SapHana', 
                  'FileMaker', 'SAP Adaptive Server', 'Informix', 'Firebird', 'Vertica', 
                  'Impala', 'ClickHouse', 'H2',  'Singlestore', 'Interbase', 
                  'Ingres', 'SAP SQL Anywhere', 'HyperSQL']
NONRELATIONAL_ONLY_DBS = ['Aerospike', 'ArangoDB', 'Cassandra', 'CouchDB', 'Couchbase',
       'DynamoDB', 'Etcd', 'Firebase Realtime', 'Google Cloud Datastore',
       'GoogleCloudFirestore', 'HBase', 'Hazelcast',
       'Influx DB', 'Kdb+', 'MarkLogic', 'Microsoft Azure CosmosDB',
       'Microsoft Azure Table Storage', 'MongoDB', 'Neo4j', 'PostGIS', 'Realm',
       'Redis', 'Riak KV']
MULTIMODEL_RELATIONAL = ['Ignite-Sql', 'Virtuoso-Sql']
MULTIMODEL_NONRELATIONAL = ['Ignite-NoSql', 'Virtuoso-NoSql']

RELATIONAL_DBS = RELATIONAL_ONLY_DBS + MULTIMODEL_RELATIONAL
NONRELATIONAL_DBS = NONRELATIONAL_ONLY_DBS + MULTIMODEL_NONRELATIONAL
MULTIMODEL_DBS = MULTIMODEL_RELATIONAL + MULTIMODEL_NONRELATIONAL



def tex_escape(text):
    """
        :param text: a plain text message
        :return: the message escaped to appear correctly in LaTeX
    """
    conv = {
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '_': r'\_',
        '{': r'\{',
        '}': r'\}',
        '~': r'\textasciitilde{}',
        '^': r'\^{}',
        '\\': r'\textbackslash{}',
        '<': r'\textless{}',
        '>': r'\textgreater{}',
    }
    regex = re.compile('|'.join(re.escape(key) for key in sorted(conv.keys(), key = lambda item: - len(item))))
    return regex.sub(lambda match: conv[match.group()], text)


def load_vars():
    data = {}
    if os.path.exists(VARIABLES):
        with open(VARIABLES, "r") as fil:
            for line in fil:
                line = line.strip()
                if line:
                    k, v = line.split(" = ")
                    data[k] = v
    return data

def var(key, value, template="{}"):
    result = template.format(value)
    latex_result = tex_escape(result)
    data = load_vars()
    data[key] = latex_result
    with open(VARIABLES, "w") as fil:
        fil.writelines(
            "{} = {}\n".format(k, v)
            for k, v in data.items()
        )
    return result

def relative_var(key, part, total, t1="{0:,}", t2="{0:.1%}"):
    relative_text = var(key, part / total, t2)
    part_text = var(key + "_total", part, t1)
    return "{} ({})".format(part_text, relative_text)
