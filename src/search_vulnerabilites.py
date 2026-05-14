#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
OSV_API_URL = "https://api.osv.dev/v1/query"
NVD_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
MAVEN_SEARCH_API = "https://search.maven.org/solrsearch/select"

DEFAULT_DB_PATH = "dbmining.sqlite"
DEFAULT_COMMIT_EVERY = 50
DEFAULT_MAVEN_CACHE_FILE = "maven_release_date_cache.json"

MAVEN_CACHE: Dict[str, Optional[str]] = {}


@dataclass(frozen=True)
class DependencyRow:
    label_id: int
    label_name: str
    purl: str
    version: str
    package_name: str


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def get_columns(conn: sqlite3.Connection, table_name: str) -> List[str]:
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")]


def ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    existing = set(get_columns(conn, table))
    if column not in existing:
        log(f"Adicionando coluna {table}.{column}")
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
        conn.commit()


def ensure_vulnerability_columns(conn: sqlite3.Connection) -> None:
    required = {
        "name": "TEXT",
        "status": "TEXT",
        "description": "TEXT",
        "reference": "TEXT",
        "version": "TEXT",
        "purl": "TEXT",
        "published_at": "TEXT",
        "last_modified_at": "TEXT",
        "label_id": "INTEGER",
        "ghsa_id": "TEXT",
        "first_patched_version": "TEXT",
        "resolved_at": "TEXT",
        "vulnerable_version_range": "TEXT",
        "package_ecosystem": "TEXT",
        "package_name": "TEXT",
        "fix_source": "TEXT",
        "fix_checked_at": "TEXT",
        "fix_lookup_status": "TEXT",
        "source_details": "TEXT",
    }

    for col, col_type in required.items():
        ensure_column(conn, "vulnerability", col, col_type)


def parse_maven_purl(purl: Optional[str]) -> Optional[Tuple[str, str, Optional[str]]]:
    if not purl:
        return None

    purl = purl.strip()

    if not purl.startswith("pkg:maven/"):
        return None

    body = purl[len("pkg:maven/"):]

    if "?" in body:
        body = body.split("?", 1)[0]

    if "#" in body:
        body = body.split("#", 1)[0]

    version = None

    if "@" in body:
        package_part, version = body.rsplit("@", 1)
        version = version.strip() or None
    else:
        package_part = body

    if "/" not in package_part:
        return None

    group_id, artifact_id = package_part.split("/", 1)
    group_id = group_id.strip()
    artifact_id = artifact_id.strip()

    if not group_id or not artifact_id:
        return None

    return group_id, artifact_id, version

ORACLE_GROUP_ALIASES = {
    "com.oracle",
    "com.oracle.jdbc",
    "com.oracle.ojdbc",
    "com.oracle.database.jdbc",
}

ORACLE_ARTIFACT_ALIASES = {
    "ojdbc14",
    "ojdbc5",
    "ojdbc6",
    "ojdbc7",
    "ojdbc8",
    "ojdbc10",
    "ojdbc11",
}


def is_oracle_dependency(dep: DependencyRow) -> bool:
    package = (dep.package_name or "").lower().strip()

    if ":" not in package:
        return False

    group_id, artifact_id = package.split(":", 1)

    return (
        "oracle" in dep.label_name.lower()
        or group_id in ORACLE_GROUP_ALIASES
        or artifact_id in ORACLE_ARTIFACT_ALIASES
    )


def generate_oracle_candidate_packages(dep: DependencyRow) -> List[str]:
    candidates = []

    for group_id in ORACLE_GROUP_ALIASES:
        for artifact_id in ORACLE_ARTIFACT_ALIASES:
            candidates.append(f"{group_id}:{artifact_id}")

    candidates.append(dep.package_name)

    return sorted(set(candidates))


def load_maven_cache(cache_file: str) -> None:
    global MAVEN_CACHE

    path = Path(cache_file)

    if not path.exists():
        MAVEN_CACHE = {}
        return

    try:
        MAVEN_CACHE = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        MAVEN_CACHE = {}


def save_maven_cache(cache_file: str) -> None:
    Path(cache_file).write_text(
        json.dumps(MAVEN_CACHE, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def build_github_headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "db-mining-research/1.0",
    }

    token = os.getenv("GITHUB_TOKEN", "").strip()

    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def require_github_token() -> None:
    if not os.getenv("GITHUB_TOKEN", "").strip():
        raise RuntimeError(
            "GITHUB_TOKEN não configurado. Configure o token antes de rodar "
            "para evitar rate limit e resultados incompletos."
        )


def build_nvd_headers() -> Dict[str, str]:
    headers = {
        "User-Agent": "db-mining-research/1.0",
    }

    api_key = os.getenv("NVD_API_KEY", "").strip()

    if api_key:
        headers["apiKey"] = api_key

    return headers


def request_with_retry(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    auth: Optional[Any] = None,
    timeout: int = 90,
    max_retries: int = 5,
) -> requests.Response:
    retryable_statuses = {429, 500, 502, 503, 504}
    headers = dict(headers or {})
    headers.setdefault("User-Agent", "db-mining-research/1.0")

    last_response = None
    last_exception = None

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                auth=auth,
                timeout=timeout,
            )

            last_response = response

            if response.status_code in (200, 201, 404):
                return response

            if response.status_code in retryable_statuses:
                wait_time = 2 ** (attempt - 1)

                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait_time = max(wait_time, float(retry_after))
                    except ValueError:
                        pass

                log(
                    f"Tentativa {attempt}/{max_retries} falhou com HTTP "
                    f"{response.status_code}. Nova tentativa em {wait_time}s."
                )

                if attempt < max_retries:
                    time.sleep(wait_time)
                    continue

            return response

        except (requests.Timeout, requests.ConnectionError, requests.RequestException) as exc:
            last_exception = exc
            wait_time = 2 ** (attempt - 1)

            log(
                f"Tentativa {attempt}/{max_retries} falhou por erro de rede: "
                f"{exc}. Nova tentativa em {wait_time}s."
            )

            if attempt < max_retries:
                time.sleep(wait_time)
                continue

    if last_response is not None:
        return last_response

    raise RuntimeError(f"Falha de rede após {max_retries} tentativas: {last_exception}")


def fetch_maven_release_date(package_name: str, version: Optional[str]) -> Optional[str]:
    if not package_name or not version or ":" not in package_name:
        return None

    cache_key = f"{package_name}@{version}"

    if cache_key in MAVEN_CACHE:
        return MAVEN_CACHE[cache_key]

    group_id, artifact_id = package_name.split(":", 1)

    params = {
        "q": f'g:"{group_id}" AND a:"{artifact_id}" AND v:"{version}"',
        "rows": "1",
        "wt": "json",
    }

    time.sleep(0.5)

    response = request_with_retry(
        "GET",
        MAVEN_SEARCH_API,
        params=params,
        timeout=90,
        max_retries=5,
    )

    if response.status_code != 200:
        log(f"Maven Central retornou {response.status_code} para {cache_key}")
        MAVEN_CACHE[cache_key] = None
        return None

    try:
        data = response.json()
    except ValueError:
        MAVEN_CACHE[cache_key] = None
        return None

    docs = data.get("response", {}).get("docs", [])

    if not docs:
        MAVEN_CACHE[cache_key] = None
        return None

    timestamp = docs[0].get("timestamp")

    if not timestamp:
        MAVEN_CACHE[cache_key] = None
        return None

    resolved_at = datetime.fromtimestamp(
        timestamp / 1000,
        tz=timezone.utc
    ).replace(microsecond=0).isoformat()

    MAVEN_CACHE[cache_key] = resolved_at
    return resolved_at


def load_candidate_dependencies(conn: sqlite3.Connection) -> List[DependencyRow]:
    sql = """
        SELECT DISTINCT
            l.id AS label_id,
            l.name AS label_name,
            vv.purl AS purl,
            vv.versionNumber AS version
        FROM version_vulnerability vv
        JOIN execution e ON e.id = vv.execution_id
        JOIN heuristic h ON h.id = e.heuristic_id
        JOIN label l ON l.id = h.label_id

        LEFT JOIN vulnerability v
            ON v.label_id = l.id
           AND TRIM(v.version) = TRIM(vv.versionNumber)
           AND TRIM(v.purl) = TRIM(vv.purl)

        WHERE vv.purl IS NOT NULL
          AND TRIM(vv.purl) <> ''
          AND vv.versionNumber IS NOT NULL
          AND TRIM(vv.versionNumber) <> ''

          -- 🔥 AQUI ESTÁ O FILTRO
          AND (
                v.id IS NULL
             OR v.published_at IS NULL
             OR v.resolved_at IS NULL
          )
    """

    rows = conn.execute(sql).fetchall()
    deps: List[DependencyRow] = []

    for row in rows:
        parsed = parse_maven_purl(row["purl"])

        if not parsed:
            continue

        group_id, artifact_id, _ = parsed

        deps.append(
            DependencyRow(
                label_id=row["label_id"],
                label_name=row["label_name"],
                purl=row["purl"],
                version=row["version"],
                package_name=f"{group_id}:{artifact_id}",
            )
        )

    return deps


def fetch_github_advisories(package_name: str, version: str) -> List[Dict[str, Any]]:
    params = {
        "ecosystem": "maven",
        "affects": f"{package_name}@{version}",
        "per_page": "100",
        "type": "reviewed",
    }

    response = request_with_retry(
        "GET",
        f"{GITHUB_API_BASE}/advisories",
        headers=build_github_headers(),
        params=params,
        timeout=90,
        max_retries=5,
    )

    if response.status_code != 200:
        if response.status_code == 403 and "rate limit" in response.text.lower():
            raise RuntimeError(
                "GitHub Advisory API rate limit excedido. Configure/valide GITHUB_TOKEN "
                "e rode novamente."
            )

        log(f"GitHub Advisory retornou {response.status_code}: {response.text[:200]}")
        return []

    payload = response.json()
    return payload if isinstance(payload, list) else []


def extract_github_matches(
    advisories: List[Dict[str, Any]],
    dep: DependencyRow,
) -> List[Dict[str, Any]]:
    matches = []

    for advisory in advisories:
        ghsa_id = advisory.get("ghsa_id")
        cve_id = advisory.get("cve_id")
        reference = cve_id or ghsa_id

        if not reference:
            continue

        published_at = advisory.get("published_at")
        updated_at = advisory.get("updated_at")
        summary = advisory.get("summary")
        description = advisory.get("description")
        severity = advisory.get("severity")

        for item in advisory.get("vulnerabilities", []) or []:
            package = item.get("package") or {}

            if (package.get("ecosystem") or "").lower() != "maven":
                continue

            package_name = package.get("name") or ""

            if package_name != dep.package_name:
                continue

            first_patched = item.get("first_patched_version")

            if isinstance(first_patched, dict):
                first_patched = first_patched.get("identifier")

            resolved_at = None

            if first_patched:
                resolved_at = fetch_maven_release_date(
                    dep.package_name,
                    first_patched
                )

            matches.append(
                {
                    "label_id": dep.label_id,
                    "version": dep.version,
                    "purl": dep.purl,
                    "reference": reference,
                    "name": summary,
                    "description": description,
                    "status": severity,
                    "published_at": published_at,
                    "last_modified_at": updated_at,
                    "ghsa_id": ghsa_id,
                    "first_patched_version": first_patched,
                    "resolved_at": resolved_at,
                    "vulnerable_version_range": item.get("vulnerable_version_range"),
                    "package_ecosystem": "maven",
                    "package_name": package_name or dep.package_name,
                    "fix_source": "GitHub Advisory Database",
                    "fix_checked_at": now_utc_iso(),
                    "fix_lookup_status": "MATCHED_GITHUB",
                    "source_details": json.dumps(
                        {
                            "source": "github_advisory",
                            "published_at_source": "github_advisory.published_at",
                            "first_patched_version_source": "github_advisory.first_patched_version",
                            "resolved_at_source": "maven_central.timestamp_of_first_patched_version",
                            "original_purl": dep.purl,
                            "queried_package": dep.package_name,
                            "match_strategy": "oracle_alias_family" if is_oracle_dependency(dep) else "exact_package",
                        },
                        ensure_ascii=False,
                    ),
                }
            )

    return matches


def choose_osv_reference(vuln: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    osv_id = vuln.get("id")
    aliases = vuln.get("aliases") or []

    cve_id = next((alias for alias in aliases if is_cve(alias)), None)
    ghsa_id = next((alias for alias in aliases if str(alias).upper().startswith("GHSA-")), None)

    reference = cve_id or ghsa_id or osv_id
    return reference, cve_id, ghsa_id


def extract_osv_fixed_version(vuln: Dict[str, Any], package_name: str) -> Optional[str]:
    for affected in vuln.get("affected") or []:
        package = affected.get("package") or {}

        if package.get("name") != package_name:
            continue

        for ranges in affected.get("ranges") or []:
            for event in ranges.get("events") or []:
                fixed = event.get("fixed")
                if fixed:
                    return fixed

    return None


def fetch_osv_matches(dep: DependencyRow) -> List[Dict[str, Any]]:
    response = request_with_retry(
        "POST",
        OSV_API_URL,
        headers={"Accept": "application/json"},
        json_body={
            "version": dep.version,
            "package": {
                "name": dep.package_name,
                "ecosystem": "Maven",
            },
        },
        timeout=90,
        max_retries=5,
    )

    if response.status_code != 200:
        log(f"OSV retornou {response.status_code} para {dep.package_name}@{dep.version}")
        return []

    try:
        payload = response.json()
    except ValueError:
        return []

    matches = []

    for vuln in payload.get("vulns") or []:
        reference, _cve_id, ghsa_id = choose_osv_reference(vuln)

        if not reference:
            continue

        first_patched = extract_osv_fixed_version(vuln, dep.package_name)
        resolved_at = None

        if first_patched:
            resolved_at = fetch_maven_release_date(dep.package_name, first_patched)

        severity = None
        severities = vuln.get("severity") or []
        if severities:
            severity = severities[0].get("score") or severities[0].get("type")

        details = {
            "source": "osv",
            "osv_id": vuln.get("id"),
            "aliases": vuln.get("aliases") or [],
            "queried_package": dep.package_name,
            "queried_version": dep.version,
            "original_purl": dep.purl,
            "match_strategy": (
                "oracle_alias_family"
                if is_oracle_dependency(dep)
                else "exact_package"
            ),
            "published_at_source": "osv.published",
            "first_patched_version_source": "osv.affected.ranges.events.fixed",
            "resolved_at_source": "maven_central.timestamp_of_first_patched_version",
        }

        matches.append({
            "label_id": dep.label_id,
            "version": dep.version,
            "purl": dep.purl,
            "reference": reference,
            "name": vuln.get("summary") or reference,
            "description": vuln.get("details"),
            "status": severity,
            "published_at": vuln.get("published"),
            "last_modified_at": vuln.get("modified"),
            "ghsa_id": ghsa_id,
            "first_patched_version": first_patched,
            "resolved_at": resolved_at,
            "vulnerable_version_range": None,
            "package_ecosystem": "maven",
            "package_name": dep.package_name,
            "fix_source": "OSV.dev",
            "fix_checked_at": now_utc_iso(),
            "fix_lookup_status": "MATCHED_OSV",
            "source_details": json.dumps(details, ensure_ascii=False),
        })

    return matches


def is_cve(reference: Optional[str]) -> bool:
    return bool(reference and reference.upper().startswith("CVE-"))


def fetch_nvd_by_cve(reference: str) -> Optional[Dict[str, Any]]:
    params = {"cveId": reference}

    response = request_with_retry(
        "GET",
        NVD_API_URL,
        headers=build_nvd_headers(),
        params=params,
        timeout=90,
        max_retries=5,
    )

    if response.status_code != 200:
        log(f"NVD retornou {response.status_code} para {reference}: {response.text[:200]}")
        return None

    try:
        payload = response.json()
    except ValueError:
        return None

    vulnerabilities = payload.get("vulnerabilities") or []

    if not vulnerabilities:
        return None

    cve = vulnerabilities[0].get("cve") or {}

    return {
        "published_at": cve.get("published"),
        "last_modified_at": cve.get("lastModified"),
        "source_details": {
            "source": "nvd",
            "nvd_id": reference,
        }
    }


def enrich_with_nvd(match: Dict[str, Any]) -> Dict[str, Any]:
    reference = match.get("reference")

    if not is_cve(reference):
        return match

    nvd_data = fetch_nvd_by_cve(reference)

    if not nvd_data:
        return match

    match = dict(match)

    if not match.get("published_at"):
        match["published_at"] = nvd_data.get("published_at")

    if not match.get("last_modified_at"):
        match["last_modified_at"] = nvd_data.get("last_modified_at")

    match["resolved_at"] = None

    details = {
        "source": "nvd_enriched",
        "original_source": match.get("fix_source"),
        "nvd": nvd_data.get("source_details"),
    }

    match["source_details"] = json.dumps(details, ensure_ascii=False)

    match["fix_lookup_status"] = "MATCHED_NVD_ENRICHED"

    return match


def fetch_nvd_direct_matches(dep: DependencyRow) -> List[Dict[str, Any]]:
    results = []

    params = {
        "keywordSearch": dep.package_name,
        "resultsPerPage": 20
    }

    response = request_with_retry(
        "GET",
        NVD_API_URL,
        headers=build_nvd_headers(),
        params=params,
        timeout=90,
        max_retries=5,
    )

    if response.status_code != 200:
        log(f"NVD retornou {response.status_code} para {dep.package_name}")
        return []

    try:
        data = response.json()
    except ValueError:
        return []

    vulns = data.get("vulnerabilities", [])

    for item in vulns:
        cve = item.get("cve", {})

        cve_id = cve.get("id")
        published = cve.get("published")
        last_modified = cve.get("lastModified")

        descriptions = cve.get("descriptions", [])
        description = None

        for d in descriptions:
            if d.get("lang") == "en":
                description = d.get("value")
                break

        if not cve_id:
            continue

        results.append({
            "label_id": dep.label_id,
            "version": dep.version,
            "purl": dep.purl,
            "reference": cve_id,
            "name": cve_id,
            "description": description,
            "status": None,
            "published_at": published,
            "last_modified_at": last_modified,
            "ghsa_id": None,
            "first_patched_version": None,
            "resolved_at": None,
            "vulnerable_version_range": None,
            "package_ecosystem": "maven",
            "package_name": dep.package_name,
            "fix_source": "NVD",
            "fix_checked_at": now_utc_iso(),
            "fix_lookup_status": "MATCHED_NVD_DIRECT",
            "source_details": json.dumps({
                "source": "nvd_direct",
                "query": dep.package_name
            }, ensure_ascii=False),
        })

    return results


def vulnerability_exists(conn: sqlite3.Connection, row: Dict[str, Any]) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT *
        FROM vulnerability
        WHERE label_id = ?
          AND COALESCE(version, '') = COALESCE(?, '')
          AND COALESCE(purl, '') = COALESCE(?, '')
          AND COALESCE(reference, '') = COALESCE(?, '')
        LIMIT 1
        """,
        (
            row.get("label_id"),
            row.get("version"),
            row.get("purl"),
            row.get("reference"),
        ),
    ).fetchone()


def insert_or_update_vulnerability(conn: sqlite3.Connection, row: Dict[str, Any]) -> str:
    existing = vulnerability_exists(conn, row)

    if existing:
        updates = {}

        for key, value in row.items():
            if key == "id" or value in (None, ""):
                continue

            if key not in existing.keys():
                continue

            if existing[key] in (None, "") or key in {
                "published_at",
                "last_modified_at",
                "first_patched_version",
                "resolved_at",
                "vulnerable_version_range",
                "package_ecosystem",
                "package_name",
                "fix_source",
                "fix_checked_at",
                "fix_lookup_status",
                "source_details",
            }:
                updates[key] = value

        if updates:
            set_sql = ", ".join(f"{key} = ?" for key in updates)
            params = list(updates.values()) + [existing["id"]]
            conn.execute(f"UPDATE vulnerability SET {set_sql} WHERE id = ?", params)
            return "updated"

        return "existing"

    cols = get_columns(conn, "vulnerability")
    insert_cols = [col for col in row.keys() if col in cols]

    placeholders = ", ".join(["?"] * len(insert_cols))
    cols_sql = ", ".join(insert_cols)

    conn.execute(
        f"INSERT INTO vulnerability ({cols_sql}) VALUES ({placeholders})",
        [row[col] for col in insert_cols],
    )

    return "created"


def process(conn: sqlite3.Connection, commit_every: int) -> None:
    require_github_token()
    ensure_vulnerability_columns(conn)

    deps = load_candidate_dependencies(conn)

    log(f"Dependências candidatas: {len(deps)}")

    stats = {
        "github_matches": 0,
        "osv_matches": 0,
        "nvd_enriched": 0,
        "without_any_match": 0,
        "created": 0,
        "updated": 0,
        "existing": 0,
        "without_first_patched_version": 0,
        "without_resolved_at": 0,
        "network_or_api_errors": 0,
    }

    pending = 0

    for idx, dep in enumerate(deps, start=1):
        log(f"Processando {idx}/{len(deps)}: {dep.package_name}@{dep.version}")

        final_matches: List[Dict[str, Any]] = []
        candidate_packages = (
                generate_oracle_candidate_packages(dep)
                if is_oracle_dependency(dep)
                else [dep.package_name]
            )
        try:
            github_matches = []

            for candidate_package in candidate_packages:
                dep_candidate = DependencyRow(
                    label_id=dep.label_id,
                    label_name=dep.label_name,
                    purl=dep.purl,
                    version=dep.version,
                    package_name=candidate_package,
                )

                github_advisories = fetch_github_advisories(
                    dep_candidate.package_name,
                    dep_candidate.version
                )

                github_matches.extend(
                    extract_github_matches(github_advisories, dep_candidate)
                )
        except Exception as exc:
            stats["network_or_api_errors"] += 1
            log(f"Erro no GitHub para {dep.package_name}@{dep.version}: {exc}")
            github_matches = []

        if github_matches:
            stats["github_matches"] += 1
            final_matches = github_matches
        else:
            try:
                osv_matches = []
                for candidate_package in candidate_packages:
                    dep_candidate = DependencyRow(
                        label_id=dep.label_id,
                        label_name=dep.label_name,
                        purl=dep.purl,
                        version=dep.version,
                        package_name=candidate_package,
                    )

                    osv_matches.extend(fetch_osv_matches(dep_candidate))
            except Exception as exc:
                stats["network_or_api_errors"] += 1
                log(f"Erro no OSV para {dep.package_name}@{dep.version}: {exc}")
                osv_matches = []

            if osv_matches:
                stats["osv_matches"] += 1
                final_matches = [enrich_with_nvd(match) for match in osv_matches]

                if any(match.get("fix_lookup_status") == "MATCHED_NVD_ENRICHED" for match in final_matches):
                    stats["nvd_enriched"] += 1
            else:
                USE_NVD_FALLBACK_LABELS = {
                    "Oracle",
                    "Maria DB",
                }
                
                should_use_nvd = dep.label_name in USE_NVD_FALLBACK_LABELS

                if not should_use_nvd:
                    stats["without_any_match"] += 1
                    continue

                log(f"Fallback para NVD: {dep.package_name}@{dep.version}")
                
                final_matches = []
                
                for candidate_package in candidate_packages:
                    dep_candidate = DependencyRow(
                        label_id=dep.label_id,
                        label_name=dep.label_name,
                        purl=dep.purl,
                        version=dep.version,
                        package_name=candidate_package,
                    )

                    final_matches.extend(fetch_nvd_direct_matches(dep_candidate))

                if final_matches:
                    stats["nvd_enriched"] += 1
                else:
                    stats["without_any_match"] += 1
                    continue

        for match in final_matches:
            if not match.get("first_patched_version"):
                stats["without_first_patched_version"] += 1

            if not match.get("resolved_at"):
                stats["without_resolved_at"] += 1

            result = insert_or_update_vulnerability(conn, match)
            stats[result] += 1
            pending += 1

        if pending >= commit_every:
            conn.commit()
            pending = 0
            log("Commit parcial realizado")

    conn.commit()

    print("\nResumo:")
    for key, value in stats.items():
        print(f"{key}: {value}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Busca vulnerabilidades usando GitHub Advisory, OSV.dev e NVD."
    )

    parser.add_argument("--db-path", default="dbmining.sqlite")
    parser.add_argument("--commit-every", type=int, default=DEFAULT_COMMIT_EVERY)
    parser.add_argument("--maven-cache-file", default=DEFAULT_MAVEN_CACHE_FILE)

    args = parser.parse_args()

    load_maven_cache(args.maven_cache_file)

    conn = connect_db(args.db_path)

    try:
        process(conn, args.commit_every)
    finally:
        save_maven_cache(args.maven_cache_file)
        conn.close()


if __name__ == "__main__":
    main()
