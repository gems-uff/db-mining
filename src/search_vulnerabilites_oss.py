import os
import time
import requests
from requests.auth import HTTPBasicAuth
from typing import List, Union, Optional, Dict, Tuple
from sqlalchemy import func, text

import database as db
from util import red, green, yellow

# =========================
# APIs
# =========================
API_URL = "https://ossindex.sonatype.org/api/v3/component-report"

NVD_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
NVD_API_KEY = os.getenv("NVD_API_KEY", "")  # opcional

# =========================
# Config
# =========================
MAX_RETRIES = 5
BACKOFF_BASE = 2

USERNAME = os.getenv("OSSINDEX_USERNAME", "camila.acacio.paiva@gmail.com")
API_TOKEN = os.getenv("OSSINDEX_TOKEN", "57a1511224eb4cd7f8de724d493ed3226ae5fc15")

# Cache: CVE -> (published, last_modified, cvss_score, cvss_severity, cvss_vector)
NvdTuple = Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]
# =========================

# =========================
# Helpers BD
# =========================
def search_vulnerability_heuristics_for_db_label(db_label, label_type_vuln: str = "vulnerabilities"):
    return (
        db.query(db.Heuristic)
        .join(db.Label)
        .filter(db.Label.name == db_label.name, db.Label.type == label_type_vuln)
        .all()
    )


def get_unique_purls_for_heuristics(heuristic_ids: Union[int, List[int]]):
    if isinstance(heuristic_ids, int):
        heuristic_ids = [heuristic_ids]

    subquery = (
        db.query(func.min(db.VersionVulnerability.id).label("id"))
        .filter(
            db.VersionVulnerability.purl.isnot(None),
            func.trim(db.VersionVulnerability.purl) != ""
        )
        .group_by(db.VersionVulnerability.purl)
        .subquery()
    )

    return (
        db.query(db.VersionVulnerability)
        .join(db.Execution, db.VersionVulnerability.execution_id == db.Execution.id)
        .join(subquery, db.VersionVulnerability.id == subquery.c.id)
        .filter(db.Execution.heuristic_id.in_(heuristic_ids))
        .all()
    )


# =========================
# Helpers gerais
# =========================
def chunked(seq: List[str], size: int) -> List[List[str]]:
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def build_ossindex_payload(coordinates: List[str]) -> dict:
    coordinates = [c.strip() for c in coordinates if c and c.strip()]
    return {"coordinates": coordinates}


def purl_version(purl: str) -> Optional[str]:
    if not purl:
        return None
    if "@" in purl:
        v = purl.rsplit("@", 1)[1].strip()
        return v or None
    return None


def is_cve(ref: Optional[str]) -> bool:
    return bool(ref) and ref.startswith("CVE-")


# =========================
# CVSS helpers
# =========================
def severity_from_score(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    if score > 0.0:
        return "LOW"
    return "NONE"


def extract_cvss(metrics: dict) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """
    Retorna (baseScore, baseSeverity, vectorString).
    baseSeverity pode não existir, então derivamos pelo score.
    """
    def extract_v3(key: str):
        arr = metrics.get(key) or []
        if not arr:
            return None, None, None
        metric = arr[0] or {}
        cvss = metric.get("cvssData") or {}
        score = cvss.get("baseScore")
        vector = cvss.get("vectorString")
        severity = metric.get("baseSeverity")
        if severity is None and score is not None:
            severity = severity_from_score(float(score))
        return score, severity, vector

    score, sev, vec = extract_v3("cvssMetricV31")
    if score is not None or sev is not None or vec is not None:
        return score, sev, vec

    score, sev, vec = extract_v3("cvssMetricV30")
    if score is not None or sev is not None or vec is not None:
        return score, sev, vec

    arr2 = metrics.get("cvssMetricV2") or []
    if arr2:
        metric = arr2[0] or {}
        cvss = metric.get("cvssData") or {}
        score = cvss.get("baseScore")
        vector = cvss.get("vectorString")
        severity = metric.get("baseSeverity")
        if severity is None and score is not None:
            severity = severity_from_score(float(score))
        return score, severity, vector

    return None, None, None


# =========================
# NVD
# =========================
def fetch_nvd_details(cve_id: str, nvd_cache: Dict[str, NvdTuple]) -> NvdTuple:
    """
    Retorna:
    (published, last_modified, cvss_score, cvss_severity, cvss_vector)
    """
    if cve_id in nvd_cache:
        return nvd_cache[cve_id]

    headers = {"Accept": "application/json"}
    if NVD_API_KEY:
        headers["apiKey"] = NVD_API_KEY

    # Sem API key, rate limit é bem baixo, então espaça bastante
    time.sleep(0.7 if NVD_API_KEY else 6.2)

    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(NVD_API_URL, params={"cveId": cve_id}, headers=headers, timeout=30)

            if r.status_code == 200:
                payload = r.json() or {}
                vulns = payload.get("vulnerabilities", [])
                if not vulns:
                    nvd_cache[cve_id] = (None, None, None, None, None)
                    return nvd_cache[cve_id]

                cve = (vulns[0] or {}).get("cve", {}) or {}
                published = cve.get("published")
                last_modified = cve.get("lastModified")

                metrics = cve.get("metrics", {}) or {}
                score, severity, vector = extract_cvss(metrics)

                result: NvdTuple = (
                    published,
                    last_modified,
                    str(score) if score is not None else None,
                    severity,
                    vector,
                )
                nvd_cache[cve_id] = result
                return result

            if r.status_code == 429:
                wait_time = BACKOFF_BASE ** attempt
                time.sleep(wait_time)
                continue

            # Outros erros: não cacheia para não "congelar" None
            time.sleep(BACKOFF_BASE ** attempt)

        except requests.RequestException:
            wait_time = BACKOFF_BASE ** attempt
            time.sleep(wait_time)

    nvd_cache[cve_id] = (None, None, None, None, None)
    return nvd_cache[cve_id]


# =========================
# Upsert
# =========================
def upsert_vulnerability_row(
    db_label_id: int,
    purl: str,
    v: dict,
    nvd_cache: Dict[str, NvdTuple]
) -> bool:
    ref = v.get("id")
    if not ref or not purl:
        return False

    title = v.get("title")
    desc = v.get("description")

    cwe = v.get("cwe")
    status_value = cwe if isinstance(cwe, str) else None

    ver = purl_version(purl)

    published_at = None
    last_modified_at = None
    cvss_score = None
    cvss_severity = None
    cvss_vector = None


    if is_cve(ref):
        (
            published_at,
            last_modified_at,
            cvss_score,
            cvss_severity,
            cvss_vector
        ) = fetch_nvd_details(ref, nvd_cache)

    row = (
        db.query(db.Vulnerability)
        .filter_by(label_id=db_label_id, reference=ref, purl=purl)
        .first()
    )

    if not row:
        db.create(
            db.Vulnerability,
            name=title,
            status=status_value,
            description=desc,
            reference=ref,
            version=ver,
            purl=purl,
            published_at=published_at,
            last_modified_at=last_modified_at,
            cvss_score=cvss_score,
            cvss_severity=cvss_severity,
            cvss_vector=cvss_vector,
            label_id=db_label_id,
        )
        return True

    # Atualiza apenas se estiver vazio
    if (not row.name) and title:
        row.name = title
    if (not row.description) and desc:
        row.description = desc
    if (not row.status) and status_value:
        row.status = status_value
    if (not row.version) and ver:
        row.version = ver

    if (not getattr(row, "published_at", None)) and published_at:
        row.published_at = published_at
    if (not getattr(row, "last_modified_at", None)) and last_modified_at:
        row.last_modified_at = last_modified_at

    if (not getattr(row, "cvss_score", None)) and cvss_score:
        row.cvss_score = cvss_score
    if (not getattr(row, "cvss_vector", None)) and cvss_vector:
        row.cvss_vector = cvss_vector
    if (not getattr(row, "cvss_severity", None)) and cvss_severity:
        row.cvss_severity = cvss_severity

    return False


# =========================
# Pipeline principal
# =========================
def process_vulnerabilities(connect: bool = True, batch_size: int = 64):
    if connect:
        db.connect()


    if not API_TOKEN:
        print(yellow("OSSINDEX_TOKEN está vazio. Defina a variável de ambiente para autenticar."))
        if connect:
            db.close()
        return

    status = {
        "Created": 0,
        "Existing or updated": 0,
        "No vulnerabilities in batch": 0,
        "Rate limit": 0,
        "HTTP error": 0,
        "Total requests": 0,
        "Labels processed": 0,
        "PURLs processed": 0,
    }

    nvd_cache: Dict[str, NvdTuple] = {}

    db_labels = (
        db.query(db.Label)
        .filter(db.Label.type == "vulnerabilities")
        .all()
    )

    if not db_labels:
        print(yellow("Nenhum label do tipo 'vulnerabilities' encontrado."))
        if connect:
            db.close()
        return

    auth = HTTPBasicAuth(USERNAME, API_TOKEN)

    for db_label in db_labels:
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

        for coords_batch in chunked(coordinates, batch_size):
            payload = build_ossindex_payload(coords_batch)

            for attempt in range(MAX_RETRIES):
                response = requests.post(API_URL, json=payload, auth=auth)
                status["Total requests"] += 1

                if response.status_code == 200:
                    data = response.json() or []
                    any_vuln_in_batch = False

                    for component in data:
                        comp_purl = component.get("coordinates") or component.get("coordinate")
                        if not comp_purl:
                            continue

                        vulns = component.get("vulnerabilities") or []
                        if not vulns:
                            continue

                        any_vuln_in_batch = True

                        for v in vulns:
                            created = upsert_vulnerability_row(db_label.id, comp_purl, v, nvd_cache)
                            if created:
                                status["Created"] += 1
                            else:
                                status["Existing or updated"] += 1

                    db.db.session.commit()

                    if not any_vuln_in_batch:
                        status["No vulnerabilities in batch"] += 1

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