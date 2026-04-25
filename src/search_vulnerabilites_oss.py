#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests
from requests.auth import HTTPBasicAuth

OSSINDEX_API_URL = "https://ossindex.sonatype.org/api/v3/component-report"
GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"

DEFAULT_BATCH_SIZE = 64
DEFAULT_COMMIT_EVERY = 50
DEFAULT_DB_PATH = "dbmining.sqlite"
VERBOSE = False


@dataclass(frozen=True)
class DependencyRow:
    label_id: int
    label_name: str
    purl: str
    version: str
    package_name: str
    module_file: Optional[str]


def log(msg: str, level: str = "INFO", force: bool = False) -> None:
    if VERBOSE or force or level in ("WARN", "ERROR"):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [{level}] {msg}")


def short(text: Optional[str], limit: int = 180) -> str:
    if text is None:
        return ""
    text = str(text).replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def get_columns(conn: sqlite3.Connection, table_name: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row["name"] for row in rows]


def ensure_helpful_index(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uidx_vulnerability_label_version_purl_reference
        ON vulnerability(label_id, version, purl, reference)
    """)
    conn.commit()


def ensure_vulnerability_columns(conn: sqlite3.Connection) -> None:
    existing = set(get_columns(conn, "vulnerability"))

    desired_columns = {
        "name": "TEXT",
        "status": "TEXT",
        "description": "TEXT",
        "reference": "TEXT",
        "version": "TEXT",
        "purl": "TEXT",
        "published_at": "TEXT",
        "last_modified_at": "TEXT",
        "cvss_score": "REAL",
        "cvss_severity": "TEXT",
        "cvss_vector": "TEXT",
        "label_id": "INTEGER",
        "ghsa_id": "TEXT",
        "patched_versions": "TEXT",
        "first_patched_version": "TEXT",
        "vulnerable_version_range": "TEXT",
        "package_ecosystem": "TEXT",
        "package_name": "TEXT",
        "fix_source": "TEXT",
        "fix_checked_at": "TEXT",
        "fix_lookup_status": "TEXT",
        "next_version_maven_central": "TEXT",
        "resolved_version": "TEXT",
        "resolved_at": "TEXT",
        "external_alias_used": "TEXT",
        "source_details": "TEXT",
    }

    for col, col_type in desired_columns.items():
        if col not in existing:
            log(f"Adicionando coluna vulnerability.{col}", force=True)
            conn.execute(f"ALTER TABLE vulnerability ADD COLUMN {col} {col_type}")

    conn.commit()


def chunked(seq: Sequence[str], size: int) -> Iterable[List[str]]:
    for idx in range(0, len(seq), size):
        yield list(seq[idx: idx + size])


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
    "com.oracle": "com.oracle.database.jdbc",
    "com.oracle.jdbc": "com.oracle.database.jdbc",
    "com.oracle.ojdbc": "com.oracle.database.jdbc",
    "com.oracle.database.jdbc": "com.oracle.database.jdbc",
}

ORACLE_ARTIFACTS = {
    "ojdbc14",
    "ojdbc6",
    "ojdbc7",
    "ojdbc8",
    "ojdbc10",
    "ojdbc11",
    "ojdbc17",
    "ucp",
    "ons",
    "xdb",
    "oraclepki",
    "osdt_core",
    "osdt_cert",
    "simplefan",
    "xmlparserv2",
}


def is_oracle_dependency(dep: DependencyRow) -> bool:
    parsed = parse_maven_purl(dep.purl)
    if not parsed:
        return False

    group_id, artifact_id, _ = parsed
    group_id = group_id.strip().lower()
    artifact_id = artifact_id.strip().lower()
    label_name = (dep.label_name or "").strip().lower()

    if group_id in ORACLE_GROUP_ALIASES:
        return True

    if artifact_id in ORACLE_ARTIFACTS and "oracle" in label_name:
        return True

    return False


def get_oracle_candidate_purls(dep: DependencyRow) -> List[str]:
    candidates = [dep.purl]

    if not is_oracle_dependency(dep):
        return candidates

    parsed = parse_maven_purl(dep.purl)
    if not parsed:
        return candidates

    group_id, artifact_id, version = parsed
    canonical_group = ORACLE_GROUP_ALIASES.get(group_id.lower(), group_id)

    if canonical_group != group_id:
        if version:
            candidates.append(f"pkg:maven/{canonical_group}/{artifact_id}@{version}")
        else:
            candidates.append(f"pkg:maven/{canonical_group}/{artifact_id}")

    return list(dict.fromkeys(candidates))


def get_oracle_candidate_package_names(dep: DependencyRow) -> List[str]:
    candidates = [dep.package_name]

    if not is_oracle_dependency(dep):
        return candidates

    parsed = parse_maven_purl(dep.purl)
    if not parsed:
        return candidates

    group_id, artifact_id, _ = parsed
    canonical_group = ORACLE_GROUP_ALIASES.get(group_id.lower(), group_id)
    candidates.append(f"{canonical_group}:{artifact_id}")

    return list(dict.fromkeys(candidates))


def build_github_headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "db-mining-vulnerability-enrichment",
    }

    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def ossindex_auth() -> Optional[HTTPBasicAuth]:
    username = os.getenv("OSSINDEX_USERNAME", "").strip()
    token = os.getenv("OSSINDEX_TOKEN", "").strip()

    if username and token:
        return HTTPBasicAuth(username, token)

    return None


def request_with_retry(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    auth: Optional[Any] = None,
    timeout: int = 60,
    max_retries: int = 5,
) -> requests.Response:
    retryable_statuses = {429, 502, 503, 504}
    last_exception = None
    last_response = None

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
                    f"Tentativa {attempt}/{max_retries} falhou com HTTP {response.status_code}. "
                    f"Nova tentativa em {wait_time}s. URL: {url}",
                    level="WARN",
                    force=True,
                )

                if attempt < max_retries:
                    time.sleep(wait_time)
                    continue

            return response

        except (requests.Timeout, requests.ConnectionError, requests.RequestException) as exc:
            last_exception = exc
            wait_time = 2 ** (attempt - 1)

            log(
                f"Tentativa {attempt}/{max_retries} falhou por erro de rede: {exc}. "
                f"Nova tentativa em {wait_time}s. URL: {url}",
                level="WARN",
                force=True,
            )

            if attempt < max_retries:
                time.sleep(wait_time)
                continue

    if last_response is not None:
        return last_response

    raise RuntimeError(f"Falha de rede ao acessar {url}: {last_exception}")


def load_candidate_dependencies(conn: sqlite3.Connection) -> List[DependencyRow]:
    vv_cols = set(get_columns(conn, "version_vulnerability"))

    required = {"execution_id", "versionNumber", "purl"}
    missing = required - vv_cols
    if missing:
        raise RuntimeError(f"A tabela version_vulnerability precisa conter as colunas: {sorted(missing)}")

    sql = """
        SELECT
            l.id AS label_id,
            l.name AS label_name,
            vv.purl AS purl,
            vv.versionNumber AS version,
            MIN(vv.file) AS module_file
        FROM version_vulnerability vv
        JOIN execution e ON e.id = vv.execution_id
        JOIN heuristic h ON h.id = e.heuristic_id
        JOIN label l ON l.id = h.label_id
        WHERE vv.purl IS NOT NULL
          AND TRIM(vv.purl) <> ''
          AND vv.versionNumber IS NOT NULL
          AND TRIM(vv.versionNumber) <> ''
        GROUP BY
            l.id,
            l.name,
            vv.purl,
            vv.versionNumber
        ORDER BY
            l.name,
            vv.purl,
            vv.versionNumber
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
                module_file=row["module_file"],
            )
        )

    return deps


def fetch_existing_coverage(conn: sqlite3.Connection) -> set[Tuple[int, str, str]]:
    rows = conn.execute("""
        SELECT DISTINCT
            label_id,
            COALESCE(version, '') AS version,
            COALESCE(purl, '') AS purl
        FROM vulnerability
        WHERE label_id IS NOT NULL
          AND COALESCE(version, '') <> ''
          AND COALESCE(purl, '') <> ''
    """).fetchall()

    return {(row["label_id"], row["version"], row["purl"]) for row in rows}


def fetch_ossindex_batch(purls: List[str], auth: Optional[HTTPBasicAuth]) -> Dict[str, List[Dict[str, Any]]]:
    if not purls:
        return {}

    response = request_with_retry(
        "POST",
        OSSINDEX_API_URL,
        headers={"Accept": "application/json"},
        json_body={"coordinates": purls},
        auth=auth,
        timeout=90,
    )

    if response.status_code != 200:
        log(f"OSS Index retornou {response.status_code}: {short(response.text, 300)}", level="ERROR", force=True)
        return {}

    data = response.json() or []
    by_purl: Dict[str, List[Dict[str, Any]]] = {}

    for component in data:
        purl = component.get("coordinates") or component.get("coordinate")
        vulns = component.get("vulnerabilities") or []

        if purl:
            by_purl[purl] = vulns

    return by_purl


def normalize_ossindex_vulnerability(v: Dict[str, Any], dep: DependencyRow, alias_used: Optional[str]) -> Optional[Dict[str, Any]]:
    reference = v.get("id")
    if not reference:
        return None

    return {
        "name": v.get("title"),
        "status": v.get("cwe") if isinstance(v.get("cwe"), str) else None,
        "description": v.get("description"),
        "reference": reference,
        "version": dep.version,
        "purl": dep.purl,
        "published_at": None,
        "last_modified_at": None,
        "cvss_score": None,
        "cvss_severity": None,
        "cvss_vector": None,
        "label_id": dep.label_id,
        "ghsa_id": None,
        "patched_versions": None,
        "first_patched_version": None,
        "vulnerable_version_range": None,
        "package_ecosystem": "maven",
        "package_name": dep.package_name,
        "fix_source": "OSS Index",
        "fix_checked_at": now_utc_iso(),
        "fix_lookup_status": "MATCHED",
        "next_version_maven_central": None,
        "resolved_version": None,
        "resolved_at": None,
        "external_alias_used": alias_used,
        "source_details": json.dumps(
            {
                "source": "ossindex",
                "queried_purl": alias_used or dep.purl,
                "original_purl": dep.purl,
            },
            ensure_ascii=False,
        ),
    }


def fetch_github_advisories_for_package_version(package_name: str, version: str) -> List[Dict[str, Any]]:
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
        timeout=60,
    )

    if response.status_code != 200:
        log(f"GitHub Advisory retornou {response.status_code}: {short(response.text, 300)}", level="ERROR", force=True)
        return []

    payload = response.json()
    return payload if isinstance(payload, list) else []


def normalize_github_matches(
    advisories: List[Dict[str, Any]],
    dep: DependencyRow,
    queried_package_name: str,
) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []

    for advisory in advisories:
        ghsa_id = advisory.get("ghsa_id")
        cve_id = advisory.get("cve_id")
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

            if package_name not in {dep.package_name, queried_package_name}:
                continue

            first_patched = item.get("first_patched_version")
            if isinstance(first_patched, dict):
                first_patched = first_patched.get("identifier")

            reference = cve_id or ghsa_id
            if not reference:
                continue

            alias_used = queried_package_name if queried_package_name != dep.package_name else None

            matches.append(
                {
                    "name": summary,
                    "status": severity,
                    "description": description,
                    "reference": reference,
                    "version": dep.version,
                    "purl": dep.purl,
                    "published_at": published_at,
                    "last_modified_at": updated_at,
                    "cvss_score": None,
                    "cvss_severity": severity,
                    "cvss_vector": None,
                    "label_id": dep.label_id,
                    "ghsa_id": ghsa_id,
                    "patched_versions": json.dumps([first_patched], ensure_ascii=False) if first_patched else None,
                    "first_patched_version": first_patched,
                    "vulnerable_version_range": item.get("vulnerable_version_range"),
                    "package_ecosystem": "maven",
                    "package_name": package_name or dep.package_name,
                    "fix_source": "GitHub Advisory Database",
                    "fix_checked_at": now_utc_iso(),
                    "fix_lookup_status": "MATCHED",
                    "next_version_maven_central": None,
                    "resolved_version": first_patched,
                    "resolved_at": published_at,
                    "external_alias_used": alias_used,
                    "source_details": json.dumps(
                        {
                            "source": "github_advisory",
                            "ghsa_id": ghsa_id,
                            "queried_package": queried_package_name,
                            "original_package": dep.package_name,
                        },
                        ensure_ascii=False,
                    ),
                }
            )

    return matches


def vulnerability_exists(conn: sqlite3.Connection, row_data: Dict[str, Any]) -> Optional[sqlite3.Row]:
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
            row_data.get("label_id"),
            row_data.get("version"),
            row_data.get("purl"),
            row_data.get("reference"),
        ),
    ).fetchone()


def insert_or_update_vulnerability(conn: sqlite3.Connection, row_data: Dict[str, Any]) -> str:
    existing = vulnerability_exists(conn, row_data)

    if existing:
        updates = {}

        for key, value in row_data.items():
            if key == "id" or value in (None, ""):
                continue

            if key not in existing.keys():
                continue

            if existing[key] in (None, ""):
                updates[key] = value

        if updates:
            set_sql = ", ".join([f"{key} = ?" for key in updates])
            params = list(updates.values()) + [existing["id"]]
            conn.execute(f"UPDATE vulnerability SET {set_sql} WHERE id = ?", params)
            return "updated"

        return "existing"

    cols = get_columns(conn, "vulnerability")
    insert_cols = [col for col in row_data.keys() if col in cols]

    placeholders = ", ".join(["?"] * len(insert_cols))
    cols_sql = ", ".join(insert_cols)

    sql = f"INSERT INTO vulnerability ({cols_sql}) VALUES ({placeholders})"
    conn.execute(sql, [row_data[col] for col in insert_cols])

    return "created"


def stage_1_ossindex(
    deps: List[DependencyRow],
    batch_size: int,
) -> Tuple[Dict[Tuple[int, str, str], List[Dict[str, Any]]], List[DependencyRow]]:
    auth = ossindex_auth()

    dep_candidates: Dict[Tuple[int, str, str], List[str]] = {}
    all_candidate_purls: List[str] = []

    for dep in deps:
        dep_key = (dep.label_id, dep.purl, dep.version)
        candidates = get_oracle_candidate_purls(dep)
        dep_candidates[dep_key] = candidates
        all_candidate_purls.extend(candidates)

    unique_purls = list(dict.fromkeys(all_candidate_purls))

    log(f"Etapa 1, consultando OSS Index para {len(unique_purls)} PURLs distintas", force=True)

    oss_results_by_purl: Dict[str, List[Dict[str, Any]]] = {}

    for batch_number, batch in enumerate(chunked(unique_purls, batch_size), start=1):
        log(f"Batch OSS {batch_number} com {len(batch)} PURLs", force=True)
        results = fetch_ossindex_batch(batch, auth=auth)
        oss_results_by_purl.update(results)

    oss_vulns_by_dep: Dict[Tuple[int, str, str], List[Dict[str, Any]]] = {}
    with_match_keys = set()

    for dep in deps:
        dep_key = (dep.label_id, dep.purl, dep.version)
        matches: List[Dict[str, Any]] = []

        for candidate_purl in dep_candidates[dep_key]:
            alias_used = candidate_purl if candidate_purl != dep.purl else None
            vulns = oss_results_by_purl.get(candidate_purl, [])

            normalized = [
                normalize_ossindex_vulnerability(v, dep, alias_used)
                for v in vulns
            ]
            normalized = [item for item in normalized if item]
            matches.extend(normalized)

        dedup = {}

        for item in matches:
            key = (
                item.get("reference"),
                item.get("version"),
                item.get("purl"),
                item.get("external_alias_used"),
            )
            dedup[key] = item

        final_matches = list(dedup.values())
        oss_vulns_by_dep[dep_key] = final_matches

        if final_matches:
            with_match_keys.add(dep_key)

    missing_after_oss = [
        dep for dep in deps
        if (dep.label_id, dep.purl, dep.version) not in with_match_keys
    ]

    log(
        f"Etapa 1 concluída. Dependências com match no OSS: {len(with_match_keys)}. "
        f"Dependências sem match no OSS: {len(missing_after_oss)}",
        force=True,
    )

    return oss_vulns_by_dep, missing_after_oss


def stage_2_github(missing_after_oss: List[DependencyRow]) -> Dict[Tuple[int, str, str], List[Dict[str, Any]]]:
    enriched: Dict[Tuple[int, str, str], List[Dict[str, Any]]] = {}
    github_found = 0

    for idx, dep in enumerate(missing_after_oss, start=1):
        dep_key = (dep.label_id, dep.purl, dep.version)

        log(
            f"Etapa 2, GitHub Advisory para {idx}/{len(missing_after_oss)}: "
            f"{dep.package_name}@{dep.version}",
            force=True,
        )

        all_matches: List[Dict[str, Any]] = []
        seen = set()

        for candidate_package in get_oracle_candidate_package_names(dep):
            advisories = fetch_github_advisories_for_package_version(candidate_package, dep.version)
            matches = normalize_github_matches(advisories, dep, candidate_package)

            for match in matches:
                key = (
                    match.get("reference"),
                    match.get("ghsa_id"),
                    match.get("version"),
                    match.get("purl"),
                    match.get("external_alias_used"),
                )

                if key not in seen:
                    seen.add(key)
                    all_matches.append(match)

        enriched[dep_key] = all_matches

        if all_matches:
            github_found += 1

    log(f"Etapa 2 concluída. Dependências cobertas via GitHub: {github_found}.", force=True)

    return enriched

def process_dependencies(
    conn: sqlite3.Connection,
    batch_size: int,
    commit_every: int,
    only_missing: bool,
) -> None:
    ensure_vulnerability_columns(conn)
    ensure_helpful_index(conn)

    deps = load_candidate_dependencies(conn)

    if not deps:
        log("Nenhuma dependência candidata encontrada.", level="WARN", force=True)
        return

    if only_missing:
        already_covered = fetch_existing_coverage(conn)
        deps = [
            dep for dep in deps
            if (dep.label_id, dep.version, dep.purl) not in already_covered
        ]
        log(f"Modo only-missing ativo. Dependências restantes após filtro: {len(deps)}", force=True)

    if not deps:
        log("Nenhuma dependência restante após aplicar filtro only-missing.", level="WARN", force=True)
        return

    stats = {
        "dependencies_total": len(deps),
        "dependencies_with_github_match": 0,
        "dependencies_without_github_match": 0,
        "dependencies_with_oss_match": 0,
        "dependencies_without_oss_match": 0,
        "dependencies_without_any_match": 0,
        "created": 0,
        "updated": 0,
        "existing": 0,
    }

    github_matches_map = stage_2_github(deps)

    matched_in_github = {
        (dep.label_id, dep.purl, dep.version)
        for dep in deps
        if github_matches_map.get((dep.label_id, dep.purl, dep.version))
    }

    missing_after_github = [
        dep for dep in deps
        if (dep.label_id, dep.purl, dep.version) not in matched_in_github
    ]

    if missing_after_github:
        oss_matches_map, missing_after_oss = stage_1_ossindex(
            missing_after_github,
            batch_size
        )
    else:
        oss_matches_map = {}
        missing_after_oss = []

    stats["dependencies_with_github_match"] = len(matched_in_github)
    stats["dependencies_without_github_match"] = len(missing_after_github)
    stats["dependencies_with_oss_match"] = sum(1 for v in oss_matches_map.values() if v)
    stats["dependencies_without_oss_match"] = len(missing_after_oss)
    stats["dependencies_without_any_match"] = len(missing_after_oss)

    processed_since_commit = 0

    for dep in deps:
        dep_key = (dep.label_id, dep.purl, dep.version)

        final_matches = github_matches_map.get(dep_key, [])

        if not final_matches:
            final_matches = oss_matches_map.get(dep_key, [])

        for match in final_matches:
            result = insert_or_update_vulnerability(conn, match)
            stats[result] += 1
            processed_since_commit += 1

        if processed_since_commit >= commit_every:
            conn.commit()
            log(f"Commit parcial realizado após {processed_since_commit} operações", force=True)
            processed_since_commit = 0

    conn.commit()
    log("Commit final realizado", force=True)

    print("\nResumo:")
    for key, value in stats.items():
        print(f"{key}: {value}")


def main() -> None:
    global VERBOSE

    parser = argparse.ArgumentParser(
        description=(
        "Enriquece a tabela vulnerability a partir das dependências detectadas em "
        "version_vulnerability. Consulta GitHub Advisory Database primeiro e usa "
        "OSS Index como fallback para os casos sem match."
)
    )

    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="Caminho para o banco SQLite.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Tamanho do batch no OSS Index.")
    parser.add_argument("--commit-every", type=int, default=DEFAULT_COMMIT_EVERY, help="Quantidade de inserts ou updates antes de cada commit.")
    parser.add_argument("--only-missing", action="store_true", help="Processa apenas combinações label + version + purl ainda sem registro na tabela vulnerability.")
    parser.add_argument("--verbose", action="store_true", help="Ativa logs detalhados.")

    args = parser.parse_args()
    VERBOSE = args.verbose

    conn = connect_db(args.db_path)

    try:
        process_dependencies(
        conn=conn,
        batch_size=args.batch_size,
        commit_every=args.commit_every,
        only_missing=args.only_missing,
    )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
