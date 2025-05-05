import requests
import os
import subprocess
import argparse
import sys
from timeit import default_timer as timer
from email.utils import parsedate_to_datetime
from datetime import timezone
from collections import defaultdict

import pandas as pd

import database as db
from sqlalchemy.orm import load_only, selectinload
from sqlalchemy import update, func
from requests.auth import HTTPBasicAuth 
from util import PACKAGEPURL, red, green, yellow, CODE_DEBUG
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

#Busco todos os package_purl da pasta, salvo no banco e atualizo os tipos.
#Busto as package_purl no banco e 
#Para cada package_purl, busco todas as versões encontradas, faço a filtragem delas, retirando as versões repetidas. 
#busco cada uma das versões no ossindex
#se a vulnerabilidade for reportada, salvo tal vulnerabilidade no banco. Se não for, não terá registro.
#Depois, posso vincular a vulnerabilidade à histíria. 


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
    Retorna o payload para a requisição ao OSS Index com o package PURL e versão fornecidos.

    Parâmetros:
        base_purl (str): Exemplo → "pkg:maven/org.postgresql/postgresql"
        version (str): Exemplo → "42.6.0"

    Retorna:
        dict: Exemplo → {"coordinates": ["pkg:maven/org.postgresql/postgresql@42.6.0"]}
    """
    full_purl = f"{base_purl}{version}"
    return {"coordinates": [full_purl]}

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

#realiza o processamento macro
def process_vulnerabilites(args, connect=True):
    if connect:
        db.connect()
    cwd = os.getcwd()

    labels = get_or_create_purl_labels(
    purl_dir=PACKAGEPURL,
    label_type='packagepurl',
    skip_remove=False)

    for i, label in enumerate(labels):
        # Buscar heurísticas do tipo packagepurl
        purl_heuristics = search_packgepurl_vulnerabilites(label, label_type='packagepurl')
        print("Heurísticas tipo 'packagepurl':", purl_heuristics)

        vulnerability_heuristics = search_packgepurl_vulnerabilites(label, label_type='vulnerabilities')
        print("Heurísticas tipo 'vulnerabilities':", vulnerability_heuristics)

        if vulnerability_heuristics:
            # executions_db = search_results_db(vulnerability_heuristics[0].id) #se usar esta precisa usa tmb este método depois: executions_db = filtrar_executions_unicos(executions_db)
            #print("Resultados filtragem por método:", len(executions_db))
            executions_db_query = get_unique_version_vulnerabilities(vulnerability_heuristics[0].id)
            print("Filtragem query:", len(executions_db_query))
        else:
            print("Nenhuma heurística de vulnerabilidade encontrada.")
        for j, executionVulnerability in enumerate(executions_db_query):
            #TODO Voltar aqui e corrigir o hitmilit da API
            payload = build_ossindex_payload(purl_heuristics[0].pattern, executionVulnerability.versionNumber) 
            response = requests.post(API_URL, json=payload, auth=HTTPBasicAuth(USERNAME, API_TOKEN))
            if response.status_code == 200:
                #precisa segmentar o retorno e salvar no banco em caso das vulnerabilitades serem retornadas
                data = response.json()
                all_vulns_list = extract_vulnerabilities(data)
                if all_vulns_list:
                    for v in all_vulns_list: #mudar aqui para salvar no banco e não só imprimir em tela.
                        vulnerabilidade_bd = db.query(db.Vulnerability).filter_by(label_id=label.id,reference=v.get('id')).first()
                        if not vulnerabilidade_bd:
                            db.create(db.Vulnerability, name=v.get('title'), reference=v.get('id'), description=v.get('description'), version=executionVulnerability.versionNumber, label_id=label.id)
                            print(green('ok.'))
                            do_commit()
                        else:
                            print(f"Vulnerabilidade {v.get('id')} já existe no banco.")
                else:
                    print("Nenhuma vulnerabilidade encontrada.")
            else:
                print(f"Erro {response.status_code}: {response.text}")



def main():
    args = ('extract', 'Extract heuristics from repositories')
    process_vulnerabilites(args)
    
# Requisição autenticada
    #response = requests.post(API_URL, json=payload, auth=HTTPBasicAuth(USERNAME, API_TOKEN))

    # Exibir resposta
    #if response.status_code == 200:
    #    print(response.json())
    #else:
    #    print(f"Erro {response.status_code}: {response.text}")


if __name__ == "__main__":
    main()
