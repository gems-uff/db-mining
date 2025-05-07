import requests
import os
import time
from timeit import default_timer as timer
from email.utils import parsedate_to_datetime
from datetime import timezone
from collections import defaultdict

import pandas as pd

import database as db
from sqlalchemy.orm import load_only, selectinload
from sqlalchemy import update, func
from requests.auth import HTTPBasicAuth 
from util import PACKAGEPURL, red, green, yellow
from extract import populate_labels_fs, print_results, do_commit
from typing import Union, List

# Credenciais (substitua pelos seus dados)
USERNAME = "camila.acacio.paiva@gmail.com"
API_TOKEN = "57a1511224eb4cd7f8de724d493ed3226ae5fc15"

# Endpoint da API do OSS Index
API_URL = "https://ossindex.sonatype.org/api/v3/component-report"

# Pacote a ser consultado
package_purl = "pkg:maven/org.postgresql/postgresql@42.6.0"
payload = {"coordinates": [package_purl]}

MAX_RETRIES = 5  # número máximo de tentativas para 429
BACKOFF_BASE = 2  # tempo inicial de espera (segundos)

    # Etapas principais da função process_vulnerabilites():
    # 1. Conecta ao banco de dados.
    # 2. Carrega todos os labels do tipo 'packagepurl' do sistema de arquivos e do banco.
    # 3. Para cada label:
    #    - Busca heurísticas associadas ao tipo 'packagepurl' e 'vulnerabilities'.
    #    - Se houver heurísticas de vulnerabilidade:
    #        - Obtém as versões únicas e válidas via get_unique_version_vulnerabilities().
    # 4. Para cada versão encontrada:
    #    - Constrói o payload no formato 'package_purl@version'.
    #    - Realiza requisição POST autenticada à API do OSS Index.
    #    - Se a resposta for 200:
    #        - Extrai as vulnerabilidades do JSON retornado.
    #        - Para cada vulnerabilidade:
    #            - Verifica se já existe no banco (por label_id e reference).
    #            - Se não existir, salva no banco com db.create() e faz commit.
    #            - Se já existir, exibe uma mensagem informando que a vulnerabilidade já está registrada.
    #    - Se a resposta for erro (ex: 429 ou 500), imprime o código e a mensagem de erro.



def get_or_create_purl_labels(purl_dir=PACKAGEPURL, label_type=None, skip_remove=False):
    print(f'\nLoading PURL from {purl_dir}.')
    labels = []

    # Carregando PURLs do sistema de arquivos
    labels_fs = dict()
    if label_type is None:
        for label_type_dir in os.scandir(purl_dir):
            if label_type_dir.is_dir() and not label_type_dir.name.startswith('.'):
                populate_labels_fs(labels_fs, label_type_dir.path, label_type_dir.name)
    else:
        populate_labels_fs(labels_fs, purl_dir, label_type)

    # TODO voltar aqui em caso de utilizar outra tabela
    labels_db = db.query(db.Label).options(
        selectinload(db.Label.heuristic)
        .options(selectinload(db.Heuristic.executions)
                 .defer(db.Execution.output)
                 .defer(db.Execution.user))
    )
    if label_type is not None:
        labels_db = labels_db.filter(db.Label.type == label_type)
    labels_db = labels_db.all()

    status = {
        'File System': len(labels_fs),
        'Database': len(labels_db),
        'Added': 0,
        'Deleted': 0,
        'Updated': 0,
    }

    i = 0
    for label in labels_db:
        label_fs = labels_fs.pop((label.type, label.name), None)
        if label_fs is not None:
            i += 1
            progress = '{:.2%}'.format(i / status['File System'])
            print(f'[{progress}] Updating label {label.type}/{label.name}:', end=' ')
            labels.append(label)

            heuristic = label.heuristic
            if heuristic.pattern != label_fs['pattern']:
                heuristic.pattern = label_fs['pattern']
                count = 0
                if not skip_remove:
                    for execution in list(heuristic.executions):
                        if not (execution.isValidated and execution.isAccepted):
                            execution.heuristic = None
                            execution.version = None
                            db.delete(execution)
                            count += 1
                    print(green(f'heuristic updated ({count} executions removed).'))
                status['Updated'] += 1
            else:
                print(yellow('already done.'))
        elif not skip_remove:
            db.delete(label)
            status['Deleted'] += 1

    # Adicionando novos PURLs
    for label_fs in labels_fs.values():
        i += 1
        progress = '{:.2%}'.format(i / status['File System'])
        print(f'[{progress}] Adding PURL label {label_fs["type"]}/{label_fs["name"]}:', end=' ')

        label = db.create(db.Label, name=label_fs['name'], type=label_fs['type'])
        db.create(db.Heuristic, pattern=label_fs['pattern'], label=label, executions=[])
        labels.append(label)
        print(green('ok.'))
        status['Added'] += 1

    status['Total'] = len(labels)
    print_results(status)
    do_commit()

    return sorted(labels, key=lambda item: (item.type.lower(), item.name.lower()))

def search_packgepurl_vulnerabilites(label, label_type): 
    packgepurl_db = db.query(db.Heuristic).join(db.Label).filter(db.Label.name ==label.name, db.Label.type == label_type).all()
    return packgepurl_db
    
def search_results_db(heuristic_id):
    result_db = (db.query(db.VersionVulnerability).join(db.Execution).filter(db.Execution.heuristic_id == heuristic_id).all())
    return result_db

def filtrar_executions_unicos(executions):
    """
    Retorna uma nova lista com apenas execuções únicas por versionNumber,
    ignorando aquelas com versionNumber vazio (None, '', ou apenas espaços).
    """
    seen_versions = set()
    unique_executions = []

    for item in executions:
        vn = item.versionNumber.strip() if item.versionNumber else None
        if vn and vn not in seen_versions:
            seen_versions.add(vn)
            unique_executions.append(item)

    return unique_executions

def get_unique_version_vulnerabilities(heuristic_ids: Union[int, List[int]]):
    """
    Retorna os registros de VersionVulnerability com versionNumber distintos e válidos
    (não nulos e não vazios), associados às execuções de um ou mais heuristic_id(s).
    """

    if isinstance(heuristic_ids, int):
        heuristic_ids = [heuristic_ids]

    # Subquery: menor ID por versionNumber válido
    subquery = (
        db.query(func.min(db.VersionVulnerability.id).label("id"))
        .filter(
            db.VersionVulnerability.versionNumber.isnot(None),
            func.trim(db.VersionVulnerability.versionNumber) != ''
        )
        .group_by(db.VersionVulnerability.versionNumber)
        .subquery()
    )

    # Query principal
    query = (
        db.query(db.VersionVulnerability)
        .join(db.Execution, db.VersionVulnerability.execution_id == db.Execution.id)
        .join(subquery, db.VersionVulnerability.id == subquery.c.id)
        .filter(db.Execution.heuristic_id.in_(heuristic_ids))
    )

    return query.all()

def build_ossindex_payload(base_purl: str, version: str) -> dict:
    """
    Retorna o payload para a requisição ao OSS Index com base em um ou mais package PURLs e uma versão.

    Parâmetros:
        base_purl (str): Uma ou mais PURLs separadas por vírgula ou quebra de linha. Ex:
                         "pkg:maven/org.mariadb.jdbc/mariadb-java-client@\npkg:maven/mysql/mysql-connector-java@"
        version (str): Versão a ser usada. Ex: "8.0.33"

    Retorna:
        dict: Payload com a chave "coordinates" contendo a lista completa de PURLs com versão.
    """
    # Quebra a string em linhas ou vírgulas, remove espaços e ignora vazios
    base_purls = [
        purl.strip()
        for purl in base_purl.replace(',', '\n').splitlines()
        if purl.strip()
    ]

    # Concatena a versão em cada purl
    coordinates = [f"{purl}{version}" for purl in base_purls]

    return {"coordinates": coordinates}

def extract_vulnerabilities(response_json):
    """
    Extrai as vulnerabilidades de uma resposta JSON do OSS Index.

    Parâmetros:
        response_json (list): Lista de dicionários retornados pela API

    Retorna:
        List[dict]: Lista de vulnerabilidades encontradas (pode estar vazia)
    """
    all_vulns = []

    for item in response_json:
        vulns = item.get("vulnerabilities", [])
        if vulns:
            all_vulns.extend(vulns)  # adiciona cada vulnerabilidade individualmente

    return all_vulns

#realiza o processamento principal
def process_vulnerabilites(args, connect=True): 
    if connect:
        db.connect()
    cwd = os.getcwd()

    #Busca todas as labels, do tipo packagepurl no BD. Aqui ainda não temos as 'heurísticas'. 
    labels = get_or_create_purl_labels( purl_dir=PACKAGEPURL, label_type='packagepurl', skip_remove=False)

    status = {
        'Success': 0,
        'Skipped': 0,
        'No vulnerabilities': 0,
        'Rate limit': 0,
        'HTTP error': 0,
        'Total requests': 0
    }

    for i, label in enumerate(labels): #em cada BD
        #Busco as heurísticas dos BDs para serem buscadas na execution, passo a seguir. 
        vulnerability_heuristics_bd = search_packgepurl_vulnerabilites(label, label_type='vulnerabilities')

        if vulnerability_heuristics_bd:
            #Busca os registros de VersionVulnerability com versionNumber distintos e válidos associados às execuções de um ou mais heuristic_id(s)
            executions_db_query = get_unique_version_vulnerabilities(vulnerability_heuristics_bd[0].id)
        else:
            print("No vulnerability-related heuristic was found.")
        for j, executionVulnerability in enumerate(executions_db_query):
            #Busca heurísticas do tipo Package URL. aqui de fato são as strings que são usadas na chamada da API (sempre retorna 1)
            purl_heuristics = search_packgepurl_vulnerabilites(label, label_type='packagepurl')
            payload = build_ossindex_payload(purl_heuristics[0].pattern, executionVulnerability.versionNumber) 
            for attempt in range(MAX_RETRIES):
                response = requests.post(API_URL, json=payload, auth=HTTPBasicAuth(USERNAME, API_TOKEN))
                status['Total requests'] += 1

                if response.status_code == 200:
                    data = response.json()
                    all_vulns_list = extract_vulnerabilities(data)
                    if all_vulns_list:
                        for v in all_vulns_list:
                            vulnerabilidade_bd = db.query(db.Vulnerability).filter_by(label_id=label.id, reference=v.get('id')).first()
                            if not vulnerabilidade_bd:
                                db.create(
                                    db.Vulnerability,
                                    name=v.get('title'),
                                    reference=v.get('id'),
                                    description=v.get('description'),
                                    version=executionVulnerability.versionNumber,
                                    label_id=label.id
                                )
                                print(green('ok.'))
                                do_commit()
                                status['Success'] += 1
                            else:
                                print(f"Vulnerability {v.get('id')} already exists in the database.")
                                status['Skipped'] += 1
                    else:
                        print("No vulnerabilities was found.")
                        status['No vulnerabilities'] += 1
                        break  # validar se este brear está correto aqui.

                elif response.status_code == 429:
                    wait_time = BACKOFF_BASE ** attempt
                    print(f"Rate limit reached (429). Waiting {wait_time} seconds before retrying...")
                    time.sleep(wait_time)
                    status['Rate limit'] += 1
                else:
                    print(f"Erro {response.status_code}: {response.text}")
                    status['HTTP error'] += 1
                break  # para o loop se for outro tipo de erro

    print("\nResumo de execução:")
    for key, value in status.items():
        print(f"{key}: {value}")

    if connect:
        db.close()

def main():
    args = ('extract', 'Extract heuristics from repositories')
    process_vulnerabilites(args)


if __name__ == "__main__":
    main()
