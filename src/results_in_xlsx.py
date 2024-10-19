from sqlalchemy.orm import load_only, selectinload
from util import RESOURCE_DIR, COUNT_FILE_IMP, REPOS_DIR, COUNT_FILE_SQL, COUNT_FILE_IMP_RATE, USAGE_FAN_IN_FILE, VULNERABILITY_LABELS

import pandas as pd
import os
import subprocess
import database as db

#gera arquivos .xlsx contendo os resultados das pesquisas, no caso, só retornar se possui ou näo o banco. Esse retorno é marcado por 1 ou pelo nome do banco.
def create_characterization(type_characterization, names, nameFile):
    create_xlsx(
        nameFile,
        label_type=type_characterization,
        select_versions="last",
        mode="exists",
        sort_label_by_usage=False,
        hide_unused=False
    )


#conta quantos arquivos foram retornados para o uso de ORM 
def create_count_implementation(rate):
    create_xlsx(
        COUNT_FILE_IMP_RATE if rate else COUNT_FILE_IMP,
        label_type='implementation',
        select_versions="last",
        mode="rate" if rate else "count",
        sort_label_by_usage=False,
        hide_unused=False,
        total_files_header="Number total of files"
    )

#conta quantos arquivos foram retornados para o uso de SQL e Builder 
def create_count_sql():
    create_xlsx(
        COUNT_FILE_SQL,
        label_type='query',
        select_versions="last",
        mode="count",
        sort_label_by_usage=False,
        hide_unused=False,
    )
    


def create_characterization_and_database(type_characterization, nameFile):
    create_xlsx(
        nameFile,
        label_type=type_characterization,
        select_versions="last",
        mode="code_test",
        sort_label_by_usage=False,
        hide_unused=False,
        total_files_header='Total Project'
    )
    

#conta os resultados dos aquivos de primeiro e segundo nível, separando por categoria
def create_count_dbCode_Dependencies():
    create_xlsx(
        USAGE_FAN_IN_FILE,
        label_type=['implementation', 'classes'],
        select_versions="last",
        mode="code_test_xml_rate",
        sort_label_by_usage=False,
        hide_unused=False,
        total_files_header='Total Project'
    )
    


def create_vulnerability_csv():
    results_Label = []
    db.connect()
    vulnerabilities_db = (
        db.query(db.Vulnerability)
        .join(db.Label)
        .filter(db.Vulnerability.label_id == db.Label.id)
    )
    for j, vulnerability in enumerate(vulnerabilities_db):
        status_dbCode = {
            'Name': vulnerability.name,
            'Description': vulnerability.description,
            'Year': vulnerability.year,
            'Label': vulnerability.label.name
        }

        results_Label.append(status_dbCode)
        
    save_local(results_Label, VULNERABILITY_LABELS)
    
def create_pomxml_characterization(type_characterization):
    create_xlsx(
        'pomXml',
        label_type=type_characterization,
        select_versions="last",
        mode="pom",
        sort_label_by_usage=False,
        hide_unused=False
    )
   



    save(all_results, 'pomXml')


def main():
    #resultados BDs
    #create_characterization('database', False, 'database')

    #implementação ORM
    #create_characterization('implementation', False, 'implementation')
    #create_characterization('implementation', True, 'implementation_names')
    
    #resultados de query
    #create_characterization('query', False, 'query')
    #create_count_sql()

    #resultados uso do ORM
    #create_count_implementation(True)
    #create_count_implementation(False)
    #list_type = ['implementation', 'classes']
    #create_characterization_and_database(list_type, 'number_of_files')
    create_count_dbCode_Dependencies()


    #create_vulnerability_csv()
    #create_pomxml_characterization('database')
    
if __name__ == "__main__":
    main()