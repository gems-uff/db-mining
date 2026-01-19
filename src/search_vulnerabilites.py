import time
import requests
from requests.auth import HTTPBasicAuth
from collections import defaultdict
from typing import List, Union, Optional, Dict, Tuple

from sqlalchemy import func
from sqlalchemy.orm import selectinload

import database as db
from util import red, green, yellow

# =========================
# Credenciais OSS Index
# =========================
USERNAME = "camila.acacio.paiva@gmail.com"
API_TOKEN = "57a1511224eb4cd7f8de724d493ed3226ae5fc15"

API_URL = "https://ossindex.sonatype.org/api/v3/component-report"

MAX_RETRIES = 5
BACKOFF_BASE = 2


# =========================
# Helpers de consulta no BD
# =========================
def search_vulnerability_heuristics_for_db_label(db_label, label_type_vuln: str = "vulnerabilities"):
    """
    Dado um label "de BD" (ex.: PostgreSQL), retorna as heurísticas do tipo vulnerabilities.
    Mantém o seu desenho atual (Label(name=..., type=...)).
    """
    return (
        db.query(db.Heuristic)
        .join(db.Label)
        .filter(db.Label.name == db_label.name, db.Label.type == label_type_vuln)
        .all()
    )


def get_unique_purls_for_heuristics(heuristic_ids: Union[int, List[int]]):
    """
    Retorna registros de VersionVulnerability únicos por PURL (já versionada),
    filtrando purl não nula e não vazia, associados às execuções de um ou mais heuristic_id(s).

    Observação: como você já salva purl com @version quando existe, não precisamos juntar version.
    """
    if isinstance(heuristic_ids, int):
        heuristic_ids = [heuristic_ids]

    # Subquery: menor ID por purl válida
    subquery = (
        db.query(func.min(db.VersionVulnerability.id).label("id"))
        .filter(
            db.VersionVulnerability.purl.isnot(None),
            func.trim(db.VersionVulnerability.purl) != ""
        )
        .group_by(db.VersionVulnerability.purl)
        .subquery()
    )

    query = (
        db.query(db.VersionVulnerability)
        .join(db.Execution, db.VersionVulnerability.execution_id == db.Execution.id)
        .join(subquery, db.VersionVulnerability.id == subquery.c.id)
        .filter(db.Execution.heuristic_id.in_(heuristic_ids))
    )
    return query.all()


# =========================
# Helpers OSS Index
# =========================
def build_ossindex_payload(coordinates: List[str]) -> dict:
    """
    Monta payload para o OSS Index com lista de purls completas.
    """
    coordinates = [c.strip() for c in coordinates if c and c.strip()]
    return {"coordinates": coordinates}


def extract_vulnerabilities(response_json: list) -> List[dict]:
    all_vulns = []
    for item in response_json:
        vulns = item.get("vulnerabilities", [])
        if vulns:
            all_vulns.extend(vulns)
    return all_vulns


def chunked(seq: List[str], size: int) -> List[List[str]]:
    """
    OSS Index aceita múltiplas coordinates por request.
    Use chunk para reduzir chamadas e evitar rate limit.
    """
    out = []
    for i in range(0, len(seq), size):
        out.append(seq[i:i + size])
    return out


# =========================
# Pipeline principal
# =========================
def process_vulnerabilities(connect: bool = True, batch_size: int = 64):
    """
    Lê PURLs diretamente de VersionVulnerability.purl e consulta OSS Index.
    Persistência permanece na tabela Vulnerability (como no seu script atual).

    batch_size controla quantas purls vão em uma única chamada ao OSS Index.
    """
    if connect:
        db.connect()

    status = {
        "Success": 0,
        "Skipped": 0,
        "No vulnerabilities": 0,
        "Rate limit": 0,
        "HTTP error": 0,
        "Total requests": 0,
        "Labels processed": 0,
        "PURLs processed": 0,
    }

    # Seus labels de "BD", usados para mapear para heurísticas vulnerabilities
    db_labels = (
        db.query(db.Label)
        .filter(db.Label.type == "vulnerabilities")  # ajuste se seu tipo for outro
        .all()
    )

    if not db_labels:
        print(yellow("Nenhum label do tipo 'vulnerabilities' encontrado. Ajuste o filtro db.Label.type."))
        if connect:
            db.close()
        return

    auth = HTTPBasicAuth(USERNAME, API_TOKEN)

    for i, db_label in enumerate(db_labels, start=1):
        vuln_heuristics = search_vulnerability_heuristics_for_db_label(db_label, label_type_vuln="vulnerabilities")
        if not vuln_heuristics:
            continue

        heuristic_ids = [h.id for h in vuln_heuristics]
        vv_rows = get_unique_purls_for_heuristics(heuristic_ids)

        coordinates = [row.purl for row in vv_rows if row.purl and row.purl.strip()]
        if not coordinates:
            continue

        status["Labels processed"] += 1
        status["PURLs processed"] += len(coordinates)

        # Faz requests em batch
        for coords_batch in chunked(coordinates, batch_size):
            payload = build_ossindex_payload(coords_batch)

            for attempt in range(MAX_RETRIES):
                response = requests.post(API_URL, json=payload, auth=auth)
                status["Total requests"] += 1

                if response.status_code == 200:
                    data = response.json()
                    vulns = extract_vulnerabilities(data)

                    if not vulns:
                        status["No vulnerabilities"] += 1
                        break

                    # Cada vuln do OSS Index se aplica ao componente consultado.
                    # Seu schema atual salva por (label_id, reference, version).
                    # Aqui vamos salvar version como parte da purl quando existir, para não perder contexto.
                    for v in vulns:
                        ref = v.get("id")
                        if not ref:
                            continue

                        exists = (
                            db.query(db.Vulnerability)
                            .filter_by(label_id=db_label.id, reference=ref)
                            .first()
                        )
                        if exists:
                            status["Skipped"] += 1
                            continue

                        db.create(
                            db.Vulnerability,
                            name=v.get("title"),
                            reference=ref,
                            description=v.get("description"),
                            version=None,  # opcional: você pode extrair @version da purl e salvar aqui
                            label_id=db_label.id,
                        )
                        status["Success"] += 1

                    db.db.session.commit()
                    print(green(f"{db_label.name}: batch ok ({len(coords_batch)} purls)."))
                    break

                if response.status_code == 429:
                    wait_time = BACKOFF_BASE ** attempt
                    print(yellow(f"{db_label.name}: rate limit 429, esperando {wait_time}s"))
                    time.sleep(wait_time)
                    status["Rate limit"] += 1
                    continue

                print(red(f"{db_label.name}: erro {response.status_code}: {response.text[:300]}"))
                status["HTTP error"] += 1
                break

    print("\nResumo de execução:")
    for k, v in status.items():
        print(f"{k}: {v}")

    if connect:
        db.close()


def main():
    process_vulnerabilities(connect=True, batch_size=64)


if __name__ == "__main__":
    main()
