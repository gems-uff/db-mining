#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

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


PACKAGE_REPLACEMENTS = {
    # MySQL moved the Maven coordinates. Some advisories keep the old artifact
    # as affected with "patched versions: None", while the replacement artifact
    # carries the actual fixed release.
    "mysql:mysql-connector-java": ["com.mysql:mysql-connector-j"],
}


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
        "patched_versions": "TEXT",
        "first_patched_version": "TEXT",
        "resolved_at": "TEXT",
        "vulnerable_version_range": "TEXT",
        "package_ecosystem": "TEXT",
        "package_name": "TEXT",
        "fix_source": "TEXT",
        "fix_checked_at": "TEXT",
        "fix_lookup_status": "TEXT",
        "source_details": "TEXT",
        "cvss_score": "TEXT",
        "cvss_severity": "TEXT",
        "cvss_vector": "TEXT",
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


def generate_candidate_packages(dep: DependencyRow) -> List[str]:
    # Creation of vulnerability-version associations must be strict: only the
    # exact Maven package observed in the project can create a new row. Aliases
    # and replacement artifacts are used later only to enrich already matched
    # advisories with fixed versions/release dates.
    return [dep.package_name]


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


def version_sort_key(version: str) -> Tuple[Any, ...]:
    parts = re.split(r"([0-9]+)", version or "")
    key = []

    for part in parts:
        if part == "":
            continue

        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part.lower()))

    return tuple(key)


def compare_versions(left: Optional[str], right: Optional[str]) -> Optional[int]:
    if not left or not right:
        return None

    def tokenize(version: str) -> List[Tuple[int, Any]]:
        version = str(version).strip().lstrip("vV")
        raw_parts = re.split(r"[.\-+_]", version)
        tokens: List[Tuple[int, Any]] = []

        qualifier_order = {
            "snapshot": -5,
            "alpha": -4,
            "a": -4,
            "beta": -3,
            "b": -3,
            "milestone": -2,
            "m": -2,
            "rc": -1,
            "cr": -1,
            "final": 0,
            "ga": 0,
            "release": 0,
        }

        for raw_part in raw_parts:
            if raw_part == "":
                continue

            for part in re.findall(r"\d+|[A-Za-z]+", raw_part):
                if part.isdigit():
                    tokens.append((0, int(part)))
                else:
                    qualifier = part.lower()
                    if qualifier in qualifier_order:
                        tokens.append((1, (0, qualifier_order[qualifier])))
                    else:
                        tokens.append((1, (1, qualifier)))

        return tokens

    left_tokens = tokenize(left)
    right_tokens = tokenize(right)
    max_len = max(len(left_tokens), len(right_tokens))

    for idx in range(max_len):
        left_token = left_tokens[idx] if idx < len(left_tokens) else (0, 0)
        right_token = right_tokens[idx] if idx < len(right_tokens) else (0, 0)

        if left_token == right_token:
            continue

        if left_token[0] != right_token[0]:
            return -1 if left_token[0] < right_token[0] else 1

        return -1 if left_token[1] < right_token[1] else 1

    return 0


def version_matches_constraint(version: str, operator: str, boundary: str) -> Optional[bool]:
    boundary = str(boundary or "").strip()

    if not boundary or boundary == "*":
        return None

    if boundary == "0" and operator in {">", ">="}:
        return True

    comparison = compare_versions(version, boundary)

    if comparison is None:
        return None

    if operator == "<":
        return comparison < 0
    if operator == "<=":
        return comparison <= 0
    if operator == ">":
        return comparison > 0
    if operator == ">=":
        return comparison >= 0
    if operator in {"=", "=="}:
        return comparison == 0

    return None


def vulnerable_range_affects_version(version: str, range_text: Optional[str]) -> Optional[bool]:
    if not version or not range_text:
        return None

    range_groups = [part.strip() for part in str(range_text).split(";") if part.strip()]
    if not range_groups:
        return None

    known_results: List[bool] = []

    for range_group in range_groups:
        constraints = re.findall(
            r"(<=|>=|<|>|==|=)\s*([A-Za-z0-9][A-Za-z0-9._+\-]*)",
            range_group,
        )

        if not constraints:
            continue

        group_results = [
            version_matches_constraint(version, operator, boundary)
            for operator, boundary in constraints
        ]

        if any(result is None for result in group_results):
            continue

        known_results.append(all(bool(result) for result in group_results))

    if not known_results:
        return None

    return any(known_results)


def row_known_not_affected(row: Dict[str, Any]) -> bool:
    version = row.get("version")
    range_text = row.get("vulnerable_version_range")

    if not version or not range_text:
        return False

    return vulnerable_range_affects_version(str(version), str(range_text)) is False


def unique_sorted_versions(versions: List[Optional[str]]) -> List[str]:
    clean = {str(version).strip() for version in versions if version and str(version).strip()}
    return sorted(clean, key=version_sort_key)


def json_list_or_none(items: List[str]) -> Optional[str]:
    return json.dumps(items, ensure_ascii=False) if items else None


def first_known_version(versions: List[str]) -> Optional[str]:
    return versions[0] if versions else None


def first_maven_release_date(package_name: str, versions: List[str]) -> Optional[str]:
    package_names = [package_name] + PACKAGE_REPLACEMENTS.get(package_name, [])

    for version in versions:
        for candidate_package in package_names:
            released_at = fetch_maven_release_date(candidate_package, version)
            if released_at:
                return released_at

    return None


def extract_cvss_from_nvd_metrics(metrics: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        metric = (metrics.get(key) or [None])[0] or {}
        cvss_data = metric.get("cvssData") or {}

        score = cvss_data.get("baseScore")
        severity = metric.get("baseSeverity")
        vector = cvss_data.get("vectorString")

        if score is not None or severity or vector:
            return (
                str(score) if score is not None else None,
                severity,
                vector,
            )

    return None, None, None


def extract_nvd_fixed_versions_and_ranges(cve: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    fixed_versions: List[Optional[str]] = []
    ranges: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for cpe_match in node.get("cpeMatch") or []:
                if not cpe_match.get("vulnerable", True):
                    continue

                start_including = cpe_match.get("versionStartIncluding")
                start_excluding = cpe_match.get("versionStartExcluding")
                end_including = cpe_match.get("versionEndIncluding")
                end_excluding = cpe_match.get("versionEndExcluding")

                if end_excluding:
                    fixed_versions.append(end_excluding)

                range_parts = []
                if start_including:
                    range_parts.append(f">= {start_including}")
                if start_excluding:
                    range_parts.append(f"> {start_excluding}")
                if end_including:
                    range_parts.append(f"<= {end_including}")
                if end_excluding:
                    range_parts.append(f"< {end_excluding}")

                if range_parts:
                    ranges.append(", ".join(range_parts))

            for child in node.get("nodes") or []:
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(cve.get("configurations") or [])
    return unique_sorted_versions(fixed_versions), sorted(set(ranges))


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
        replacement_patch: Optional[Tuple[str, List[str]]] = None
        replacement_packages = set(PACKAGE_REPLACEMENTS.get(dep.package_name, []))

        if replacement_packages:
            for replacement_item in advisory.get("vulnerabilities", []) or []:
                replacement_package = replacement_item.get("package") or {}
                replacement_package_name = replacement_package.get("name") or ""

                if replacement_package_name not in replacement_packages:
                    continue

                first_patched_candidate = replacement_item.get("first_patched_version")

                if isinstance(first_patched_candidate, dict):
                    first_patched_candidate = first_patched_candidate.get("identifier")

                patched_candidates = unique_sorted_versions([first_patched_candidate])

                if patched_candidates:
                    replacement_patch = (replacement_package_name, patched_candidates)
                    break

        for item in advisory.get("vulnerabilities", []) or []:
            package = item.get("package") or {}

            if (package.get("ecosystem") or "").lower() != "maven":
                continue

            package_name = package.get("name") or ""

            if package_name != dep.package_name:
                continue

            affected_by_range = vulnerable_range_affects_version(
                dep.version,
                item.get("vulnerable_version_range"),
            )

            if affected_by_range is False:
                log(
                    f"Ignorando {reference} para {dep.package_name}@{dep.version}: "
                    f"fora do range afetado do GitHub ({item.get('vulnerable_version_range')})"
                )
                continue

            first_patched_raw = item.get("first_patched_version")

            if isinstance(first_patched_raw, dict):
                first_patched_raw = first_patched_raw.get("identifier")

            patched_versions = unique_sorted_versions([first_patched_raw])
            patched_package_name = package_name

            if not patched_versions and replacement_patch:
                patched_package_name, patched_versions = replacement_patch

            first_patched = first_known_version(patched_versions)

            resolved_at = first_maven_release_date(patched_package_name, patched_versions)

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
                    "patched_versions": json_list_or_none(patched_versions),
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
                            "last_modified_at_source": "github_advisory.updated_at",
                            "patched_versions_source": "github_advisory.vulnerabilities[].first_patched_version",
                            "first_patched_version_source": "github_advisory.first_patched_version",
                            "resolved_at_source": "maven_central.timestamp_of_first_patched_version",
                            "original_purl": dep.purl,
                            "queried_package": dep.package_name,
                            "patched_package": patched_package_name,
                            "advisory_url": advisory.get("url"),
                            "html_url": advisory.get("html_url"),
                            "match_strategy": "exact_package",
                        },
                        ensure_ascii=False,
                    ),
                }
            )

    return matches


def choose_osv_reference(vuln: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    osv_id = vuln.get("id")
    aliases = vuln.get("aliases") or []

    cve_id = osv_id if is_cve(osv_id) else next((alias for alias in aliases if is_cve(alias)), None)
    ghsa_id = next((alias for alias in aliases if str(alias).upper().startswith("GHSA-")), None)

    reference = cve_id or ghsa_id or osv_id
    return reference, cve_id, ghsa_id


def osv_range_affects_version(range_data: Dict[str, Any], version: str) -> Optional[bool]:
    events = range_data.get("events") or []

    if not events:
        return None

    saw_boundary = False
    active = False

    for event in events:
        if "introduced" in event:
            saw_boundary = True
            introduced = str(event.get("introduced") or "0")
            active = introduced == "0" or version_matches_constraint(version, ">=", introduced) is True

        if "fixed" in event:
            saw_boundary = True
            fixed = str(event.get("fixed") or "")
            if active and version_matches_constraint(version, "<", fixed) is True:
                return True
            active = False

        if "last_affected" in event:
            saw_boundary = True
            last_affected = str(event.get("last_affected") or "")
            if active and version_matches_constraint(version, "<=", last_affected) is True:
                return True
            active = False

        if "limit" in event:
            saw_boundary = True
            limit = str(event.get("limit") or "")
            if active and version_matches_constraint(version, "<", limit) is True:
                return True
            active = False

    if active:
        return True

    return False if saw_boundary else None


def osv_affects_package_version(vuln: Dict[str, Any], dep: DependencyRow) -> Optional[bool]:
    saw_package = False
    saw_version_evidence = False
    saw_unknown_range = False

    for affected in vuln.get("affected") or []:
        package = affected.get("package") or {}

        if (package.get("ecosystem") or "").lower() != "maven":
            continue

        if package.get("name") != dep.package_name:
            continue

        saw_package = True
        versions = {str(version) for version in affected.get("versions") or []}
        if versions:
            saw_version_evidence = True
            if dep.version in versions:
                return True

        range_results = [
            osv_range_affects_version(ranges, dep.version)
            for ranges in affected.get("ranges") or []
        ]

        if any(result is True for result in range_results):
            return True

        if any(result is None for result in range_results):
            saw_unknown_range = True

        if range_results:
            saw_version_evidence = True

    if saw_version_evidence and not saw_unknown_range:
        return False

    return None if saw_package else False


def extract_osv_fixed_version(vuln: Dict[str, Any], package_name: str) -> Optional[str]:
    fixed_versions = extract_osv_fixed_versions(vuln, package_name)
    return first_known_version(fixed_versions)


def extract_osv_fixed_versions(vuln: Dict[str, Any], package_name: str) -> List[str]:
    fixed_versions: List[Optional[str]] = []

    for affected in vuln.get("affected") or []:
        package = affected.get("package") or {}

        if package.get("name") != package_name:
            continue

        for ranges in affected.get("ranges") or []:
            for event in ranges.get("events") or []:
                fixed = event.get("fixed")
                if fixed:
                    fixed_versions.append(fixed)

    return unique_sorted_versions(fixed_versions)


def looks_like_release_version(value: Optional[str]) -> bool:
    if not value:
        return False

    value = str(value).strip()

    if not value:
        return False

    # Git hashes are not Maven releases. OSV often has both commit and release
    # metadata for the same vulnerability.
    if re.fullmatch(r"[0-9a-f]{32,40}", value.lower()):
        return False

    return bool(re.search(r"\d+\.\d+", value))


def extract_osv_fixed_versions_any_package(vuln: Dict[str, Any]) -> List[str]:
    fixed_versions: List[Optional[str]] = []

    for affected in vuln.get("affected") or []:
        for ranges in affected.get("ranges") or []:
            for event in ranges.get("events") or []:
                fixed = event.get("fixed")
                if looks_like_release_version(fixed):
                    fixed_versions.append(fixed)

        database_specific = affected.get("database_specific") or {}
        for item in database_specific.get("versions") or []:
            fixed = item.get("fixed")
            if looks_like_release_version(fixed):
                fixed_versions.append(fixed)

    return unique_sorted_versions(fixed_versions)


def extract_osv_vulnerable_ranges(vuln: Dict[str, Any], package_name: str) -> Optional[str]:
    ranges_text: List[str] = []

    for affected in vuln.get("affected") or []:
        package = affected.get("package") or {}

        if package.get("name") != package_name:
            continue

        for ranges in affected.get("ranges") or []:
            events = []
            for event in ranges.get("events") or []:
                if "introduced" in event:
                    events.append(f">= {event.get('introduced')}")
                if "fixed" in event:
                    events.append(f"< {event.get('fixed')}")
                if "last_affected" in event:
                    events.append(f"<= {event.get('last_affected')}")
                if "limit" in event:
                    events.append(f"< {event.get('limit')}")

            if events:
                ranges_text.append(", ".join(events))

    return "; ".join(sorted(set(ranges_text))) or None


def normalize_osv_vulnerability(
    dep: DependencyRow,
    vuln: Dict[str, Any],
    *,
    allow_any_package_fixed: bool = False,
    require_package_version_match: bool = True,
) -> Optional[Dict[str, Any]]:
    affects_version = osv_affects_package_version(vuln, dep)

    if affects_version is False:
        return None

    if require_package_version_match and affects_version is not True:
        return None

    reference, _cve_id, ghsa_id = choose_osv_reference(vuln)

    if not reference:
        return None

    patched_versions = extract_osv_fixed_versions(vuln, dep.package_name)
    fixed_source = "osv.affected.ranges.events.fixed"

    if not patched_versions and allow_any_package_fixed:
        patched_versions = extract_osv_fixed_versions_any_package(vuln)
        fixed_source = "osv.affected.database_specific.versions.fixed_or_git_range_release"

    first_patched = first_known_version(patched_versions)
    resolved_at = first_maven_release_date(dep.package_name, patched_versions)

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
        "match_strategy": "reference_enrichment" if allow_any_package_fixed else "exact_package",
        "published_at_source": "osv.published",
        "last_modified_at_source": "osv.modified",
        "patched_versions_source": fixed_source,
        "first_patched_version_source": fixed_source,
        "resolved_at_source": "maven_central.timestamp_of_first_patched_version",
    }

    return {
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
        "patched_versions": json_list_or_none(patched_versions),
        "first_patched_version": first_patched,
        "resolved_at": resolved_at,
        "vulnerable_version_range": extract_osv_vulnerable_ranges(vuln, dep.package_name),
        "package_ecosystem": "maven",
        "package_name": dep.package_name,
        "fix_source": "OSV.dev",
        "fix_checked_at": now_utc_iso(),
        "fix_lookup_status": "MATCHED_OSV",
        "source_details": json.dumps(details, ensure_ascii=False),
    }


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
        match = normalize_osv_vulnerability(dep, vuln)
        if match:
            matches.append(match)

    return matches


def fetch_osv_by_reference(reference: str) -> Optional[Dict[str, Any]]:
    response = request_with_retry(
        "GET",
        f"https://api.osv.dev/v1/vulns/{quote(reference)}",
        headers={"Accept": "application/json"},
        timeout=90,
        max_retries=5,
    )

    if response.status_code != 200:
        return None

    try:
        payload = response.json()
    except ValueError:
        return None

    return payload if isinstance(payload, dict) else None


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
    cvss_score, cvss_severity, cvss_vector = extract_cvss_from_nvd_metrics(cve.get("metrics") or {})
    fixed_versions, vulnerable_ranges = extract_nvd_fixed_versions_and_ranges(cve)

    return {
        "published_at": cve.get("published"),
        "last_modified_at": cve.get("lastModified"),
        "cvss_score": cvss_score,
        "cvss_severity": cvss_severity,
        "cvss_vector": cvss_vector,
        "fixed_versions": fixed_versions,
        "vulnerable_ranges": vulnerable_ranges,
        "source_details": {
            "source": "nvd",
            "nvd_id": reference,
        }
    }


def load_missing_references_for_dependency(conn: sqlite3.Connection, dep: DependencyRow) -> List[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT reference
        FROM vulnerability
        WHERE label_id = ?
          AND COALESCE(version, '') = COALESCE(?, '')
          AND COALESCE(purl, '') = COALESCE(?, '')
          AND reference IS NOT NULL
          AND TRIM(reference) <> ''
          AND (
                first_patched_version IS NULL
             OR TRIM(first_patched_version) = ''
             OR resolved_at IS NULL
             OR TRIM(resolved_at) = ''
          )
        """,
        (dep.label_id, dep.version, dep.purl),
    ).fetchall()

    return sorted({row["reference"] for row in rows})


def match_needs_resolution(match: Dict[str, Any]) -> bool:
    return not match.get("first_patched_version") or not match.get("resolved_at")


def merge_missing_fields(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)

    for key, value in extra.items():
        if value in (None, ""):
            continue

        if not merged.get(key):
            merged[key] = value

    return merged


def build_nvd_reference_match(dep: DependencyRow, reference: str) -> Optional[Dict[str, Any]]:
    if not is_cve(reference):
        return None

    nvd_data = fetch_nvd_by_cve(reference)

    if not nvd_data:
        return None

    fixed_versions = nvd_data.get("fixed_versions") or []
    first_patched = first_known_version(fixed_versions)
    vulnerable_ranges = nvd_data.get("vulnerable_ranges") or []

    if vulnerable_ranges:
        range_results = [
            vulnerable_range_affects_version(dep.version, vulnerable_range)
            for vulnerable_range in vulnerable_ranges
        ]

        if range_results and all(result is False for result in range_results):
            log(
                f"Ignorando {reference} para {dep.package_name}@{dep.version}: "
                f"fora do range afetado do NVD ({'; '.join(vulnerable_ranges)})"
            )
            return None

    return {
        "label_id": dep.label_id,
        "version": dep.version,
        "purl": dep.purl,
        "reference": reference,
        "name": reference,
        "description": None,
        "status": nvd_data.get("cvss_severity"),
        "published_at": nvd_data.get("published_at"),
        "last_modified_at": nvd_data.get("last_modified_at"),
        "ghsa_id": None,
        "patched_versions": json_list_or_none(fixed_versions),
        "first_patched_version": first_patched,
        "resolved_at": first_maven_release_date(dep.package_name, fixed_versions),
        "vulnerable_version_range": "; ".join(vulnerable_ranges) or None,
        "package_ecosystem": "maven",
        "package_name": dep.package_name,
        "fix_source": "NVD",
        "fix_checked_at": now_utc_iso(),
        "fix_lookup_status": "MATCHED_NVD_BY_REFERENCE",
        "cvss_score": nvd_data.get("cvss_score"),
        "cvss_severity": nvd_data.get("cvss_severity"),
        "cvss_vector": nvd_data.get("cvss_vector"),
        "source_details": json.dumps(
            {
                "source": "nvd_by_reference",
                "reference": reference,
                "published_at_source": "nvd.cve.published",
                "last_modified_at_source": "nvd.cve.lastModified",
                "patched_versions_source": "nvd.cve.configurations.cpeMatch.versionEndExcluding",
                "first_patched_version_source": "nvd.cve.configurations.cpeMatch.versionEndExcluding",
                "resolved_at_source": "maven_central.timestamp_of_first_patched_version",
            },
            ensure_ascii=False,
        ),
    }


def fetch_reference_matches(dep: DependencyRow, references: List[str]) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []

    for reference in references:
        osv_vuln = fetch_osv_by_reference(reference)

        if osv_vuln:
            osv_match = normalize_osv_vulnerability(
                dep,
                osv_vuln,
                allow_any_package_fixed=True,
                require_package_version_match=False,
            )

            if osv_match:
                matches.append(enrich_with_nvd(osv_match))
                continue

        nvd_match = build_nvd_reference_match(dep, reference)

        if nvd_match:
            matches.append(nvd_match)

    return matches


def complete_matches_with_references(
    dep: DependencyRow,
    matches: List[Dict[str, Any]],
    references: List[str],
) -> List[Dict[str, Any]]:
    references_to_lookup = sorted({
        *(references or []),
        *(match.get("reference") for match in matches if match.get("reference")),
        *(match.get("ghsa_id") for match in matches if match.get("ghsa_id")),
    })

    if not references_to_lookup:
        return matches

    reference_matches = fetch_reference_matches(dep, references_to_lookup)

    if not matches:
        return reference_matches

    by_reference: Dict[str, Dict[str, Any]] = {}
    for reference_match in reference_matches:
        by_reference[reference_match.get("reference")] = reference_match
        if reference_match.get("ghsa_id"):
            by_reference[reference_match.get("ghsa_id")] = reference_match

    completed = []
    for match in matches:
        if not match_needs_resolution(match):
            completed.append(match)
            continue

        reference_match = by_reference.get(match.get("reference")) or by_reference.get(match.get("ghsa_id"))

        if reference_match:
            completed.append(merge_missing_fields(match, reference_match))
        else:
            completed.append(match)

    return completed


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

    fixed_versions = nvd_data.get("fixed_versions") or []

    if not match.get("patched_versions") and fixed_versions:
        match["patched_versions"] = json_list_or_none(fixed_versions)

    if not match.get("first_patched_version") and fixed_versions:
        match["first_patched_version"] = first_known_version(fixed_versions)

    if not match.get("resolved_at") and match.get("first_patched_version"):
        match["resolved_at"] = first_maven_release_date(
            match.get("package_name") or "",
            [match.get("first_patched_version")],
        )

    if not match.get("vulnerable_version_range") and nvd_data.get("vulnerable_ranges"):
        match["vulnerable_version_range"] = "; ".join(nvd_data.get("vulnerable_ranges") or [])

    for key in ("cvss_score", "cvss_severity", "cvss_vector"):
        if not match.get(key) and nvd_data.get(key):
            match[key] = nvd_data.get(key)

    details = {
        "source": "nvd_enriched",
        "original_source": match.get("fix_source"),
        "nvd": nvd_data.get("source_details"),
        "published_at_source": "nvd.cve.published",
        "last_modified_at_source": "nvd.cve.lastModified",
        "patched_versions_source": "nvd.cve.configurations.cpeMatch.versionEndExcluding",
        "first_patched_version_source": "nvd.cve.configurations.cpeMatch.versionEndExcluding",
        "resolved_at_source": "maven_central.timestamp_of_first_patched_version",
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
        cvss_score, cvss_severity, cvss_vector = extract_cvss_from_nvd_metrics(cve.get("metrics") or {})
        fixed_versions, vulnerable_ranges = extract_nvd_fixed_versions_and_ranges(cve)
        first_patched = first_known_version(fixed_versions)
        resolved_at = first_maven_release_date(dep.package_name, fixed_versions)

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
            "patched_versions": json_list_or_none(fixed_versions),
            "first_patched_version": first_patched,
            "resolved_at": resolved_at,
            "vulnerable_version_range": "; ".join(vulnerable_ranges) if vulnerable_ranges else None,
            "package_ecosystem": "maven",
            "package_name": dep.package_name,
            "fix_source": "NVD",
            "fix_checked_at": now_utc_iso(),
            "fix_lookup_status": "MATCHED_NVD_DIRECT",
            "cvss_score": cvss_score,
            "cvss_severity": cvss_severity,
            "cvss_vector": cvss_vector,
            "source_details": json.dumps({
                "source": "nvd_direct",
                "query": dep.package_name,
                "published_at_source": "nvd.cve.published",
                "last_modified_at_source": "nvd.cve.lastModified",
                "patched_versions_source": "nvd.cve.configurations.cpeMatch.versionEndExcluding",
                "first_patched_version_source": "nvd.cve.configurations.cpeMatch.versionEndExcluding",
                "resolved_at_source": "maven_central.timestamp_of_first_patched_version",
            }, ensure_ascii=False),
        })

    return results


def vulnerability_identifiers(row: Dict[str, Any]) -> List[str]:
    identifiers = {
        str(value).strip()
        for value in (row.get("reference"), row.get("ghsa_id"))
        if value and str(value).strip()
    }

    source_details = row.get("source_details")
    if source_details:
        try:
            details = json.loads(source_details) if isinstance(source_details, str) else source_details
        except (TypeError, ValueError):
            details = {}

        for value in [details.get("osv_id"), *(details.get("aliases") or [])]:
            if value and str(value).strip():
                identifiers.add(str(value).strip())

    return sorted(identifiers)


def vulnerability_exists(conn: sqlite3.Connection, row: Dict[str, Any]) -> Optional[sqlite3.Row]:
    identifiers = vulnerability_identifiers(row)

    if not identifiers:
        return None

    placeholders = ", ".join("?" for _ in identifiers)
    exact_reference = row.get("reference") or ""

    return conn.execute(
        f"""
        SELECT *
        FROM vulnerability
        WHERE label_id = ?
          AND COALESCE(version, '') = COALESCE(?, '')
          AND COALESCE(purl, '') = COALESCE(?, '')
          AND (
                reference IN ({placeholders})
             OR ghsa_id IN ({placeholders})
          )
        ORDER BY CASE WHEN reference = ? THEN 0 ELSE 1 END, id
        LIMIT 1
        """,
        (
            row.get("label_id"),
            row.get("version"),
            row.get("purl"),
            *identifiers,
            *identifiers,
            exact_reference,
        ),
    ).fetchone()


def row_can_create_new_association(row: Dict[str, Any]) -> bool:
    source_details = row.get("source_details")
    if not source_details:
        return True

    try:
        details = json.loads(source_details) if isinstance(source_details, str) else source_details
    except (TypeError, ValueError):
        return True

    if details.get("match_strategy") == "reference_enrichment":
        return False

    if details.get("source") == "nvd_by_reference":
        return False

    return True


def insert_or_update_vulnerability(conn: sqlite3.Connection, row: Dict[str, Any]) -> str:
    if row_known_not_affected(row):
        log(
            f"Ignorando {row.get('reference')} para {row.get('package_name')}@{row.get('version')}: "
            f"fora do range afetado ({row.get('vulnerable_version_range')})"
        )
        return "skipped_not_affected"

    existing = vulnerability_exists(conn, row)

    if existing:
        updates = {}

        if is_cve(row.get("reference")) and str(existing["reference"] or "").upper().startswith("GHSA-"):
            updates["reference"] = row.get("reference")
            if "ghsa_id" in existing.keys() and not existing["ghsa_id"]:
                updates["ghsa_id"] = existing["reference"]

        for key, value in row.items():
            if key == "id" or value in (None, ""):
                continue

            if key not in existing.keys():
                continue

            if existing[key] in (None, "") or key in {
                "published_at",
                "last_modified_at",
                "patched_versions",
                "first_patched_version",
                "resolved_at",
                "vulnerable_version_range",
                "package_ecosystem",
                "package_name",
                "fix_source",
                "fix_checked_at",
                "fix_lookup_status",
                "source_details",
                "cvss_score",
                "cvss_severity",
                "cvss_vector",
            }:
                updates[key] = value

        if updates:
            set_sql = ", ".join(f"{key} = ?" for key in updates)
            params = list(updates.values()) + [existing["id"]]
            conn.execute(f"UPDATE vulnerability SET {set_sql} WHERE id = ?", params)
            return "updated"

        return "existing"

    if not row_can_create_new_association(row):
        return "skipped"

    cols = get_columns(conn, "vulnerability")
    insert_cols = [col for col in row.keys() if col in cols]

    placeholders = ", ".join(["?"] * len(insert_cols))
    cols_sql = ", ".join(insert_cols)

    conn.execute(
        f"INSERT INTO vulnerability ({cols_sql}) VALUES ({placeholders})",
        [row[col] for col in insert_cols],
    )

    return "created"


def canonical_cve_from_row(row: sqlite3.Row) -> Optional[str]:
    if is_cve(row["reference"]):
        return row["reference"]

    source_details = row["source_details"] if "source_details" in row.keys() else None
    if not source_details:
        return None

    try:
        details = json.loads(source_details)
    except (TypeError, ValueError):
        return None

    candidates = [details.get("osv_id"), *(details.get("aliases") or [])]
    return next((candidate for candidate in candidates if is_cve(candidate)), None)


def consolidate_cve_ghsa_duplicates(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT *
        FROM vulnerability
        WHERE reference LIKE 'GHSA-%'
          AND source_details IS NOT NULL
          AND TRIM(source_details) <> ''
        ORDER BY id
        """
    ).fetchall()
    removed = 0

    for alias_row in rows:
        canonical_cve = canonical_cve_from_row(alias_row)
        if not canonical_cve:
            continue

        canonical_row = conn.execute(
            """
            SELECT *
            FROM vulnerability
            WHERE label_id = ?
              AND COALESCE(version, '') = COALESCE(?, '')
              AND COALESCE(purl, '') = COALESCE(?, '')
              AND reference = ?
            LIMIT 1
            """,
            (
                alias_row["label_id"],
                alias_row["version"],
                alias_row["purl"],
                canonical_cve,
            ),
        ).fetchone()

        if canonical_row:
            updates = {}
            for key in alias_row.keys():
                if key in {"id", "label_id", "version", "purl", "reference"}:
                    continue
                if canonical_row[key] in (None, "") and alias_row[key] not in (None, ""):
                    updates[key] = alias_row[key]

            if "ghsa_id" in alias_row.keys() and not canonical_row["ghsa_id"]:
                updates["ghsa_id"] = alias_row["reference"]

            if updates:
                set_sql = ", ".join(f"{key} = ?" for key in updates)
                conn.execute(
                    f"UPDATE vulnerability SET {set_sql} WHERE id = ?",
                    [*updates.values(), canonical_row["id"]],
                )

            conn.execute("DELETE FROM vulnerability WHERE id = ?", (alias_row["id"],))
            removed += 1
        else:
            conn.execute(
                """
                UPDATE vulnerability
                SET reference = ?,
                    ghsa_id = COALESCE(NULLIF(ghsa_id, ''), ?)
                WHERE id = ?
                """,
                (canonical_cve, alias_row["reference"], alias_row["id"]),
            )

    if removed:
        conn.commit()
        log(f"Duplicações CVE/GHSA consolidadas: {removed}")

    return removed


def process(conn: sqlite3.Connection, commit_every: int) -> None:
    require_github_token()
    ensure_vulnerability_columns(conn)
    consolidate_cve_ghsa_duplicates(conn)

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
        "skipped": 0,
        "skipped_not_affected": 0,
        "without_first_patched_version": 0,
        "without_resolved_at": 0,
        "network_or_api_errors": 0,
    }

    pending = 0

    for idx, dep in enumerate(deps, start=1):
        log(f"Processando {idx}/{len(deps)}: {dep.package_name}@{dep.version}")

        final_matches: List[Dict[str, Any]] = []
        candidate_packages = generate_candidate_packages(dep)
        known_references = load_missing_references_for_dependency(conn, dep)

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
            final_matches = complete_matches_with_references(
                dep,
                github_matches,
                known_references,
            )
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
                final_matches = complete_matches_with_references(
                    dep,
                    [enrich_with_nvd(match) for match in osv_matches],
                    known_references,
                )

                if any(match.get("fix_lookup_status") == "MATCHED_NVD_ENRICHED" for match in final_matches):
                    stats["nvd_enriched"] += 1
            else:
                log(f"Fallback para NVD: {dep.package_name}@{dep.version}")

                # Reference lookups only enrich vulnerabilities already linked
                # to this exact dependency/version. A keyword search cannot
                # prove that a CVE affects the version used by the project.
                final_matches = fetch_reference_matches(dep, known_references)

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
