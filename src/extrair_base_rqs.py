#!/usr/bin/env python3
import argparse
import logging
import sqlite3
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

DEFAULT_DB_CANDIDATES = ["dbmining.sqlite", "dbmining.slite"]
DEFAULT_OUTPUT_DIR = "rqs_data"


def normalize_text(series: pd.Series) -> pd.Series:
    return (
        series.astype("string")
        .str.strip()
        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "NaN": pd.NA})
    )


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,)
    )
    return cur.fetchone() is not None


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    return {row[1] for row in rows}


def pick_first_existing(columns: set[str], candidates: Sequence[str]) -> Optional[str]:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def resolve_default_db_path() -> Path:
    cwd = Path.cwd()
    for filename in DEFAULT_DB_CANDIDATES:
        candidate = cwd / filename
        if candidate.exists():
            return candidate
    for filename in DEFAULT_DB_CANDIDATES:
        matches = list(cwd.rglob(filename))
        if matches:
            return matches[0]
    raise FileNotFoundError(
        f"Não encontrei o banco automaticamente. Procurei por: {', '.join(DEFAULT_DB_CANDIDATES)}"
    )


def build_base_query(conn: sqlite3.Connection) -> str:
    required_tables = [
        "project", "version", "version_vulnerability",
        "execution", "heuristic", "label", "vulnerability",
    ]
    for table_name in required_tables:
        if not table_exists(conn, table_name):
            raise ValueError(f"Tabela obrigatória ausente: {table_name}")

    vuln_cols = get_table_columns(conn, "vulnerability")

    published_col = pick_first_existing(vuln_cols, ["published_at", "publishedAt"])
    last_modified_col = pick_first_existing(vuln_cols, ["last_modified_at", "last_modified", "lastModifiedAt"])
    cvss_score_col = pick_first_existing(vuln_cols, ["cvss_score", "cvssScore"])
    cvss_severity_col = pick_first_existing(vuln_cols, ["cvss_severity", "cvssSeverity"])
    cvss_vector_col = pick_first_existing(vuln_cols, ["cvss_vector", "cvssVector"])
    purl_col = pick_first_existing(vuln_cols, ["purl"])

    select_optional = []
    select_optional.append(f"vuln.{published_col} AS published_at" if published_col else "NULL AS published_at")
    select_optional.append(f"vuln.{last_modified_col} AS last_modified_at" if last_modified_col else "NULL AS last_modified_at")
    select_optional.append(f"vuln.{cvss_score_col} AS cvss_score" if cvss_score_col else "NULL AS cvss_score")
    select_optional.append(f"vuln.{cvss_severity_col} AS cvss_severity" if cvss_severity_col else "NULL AS cvss_severity")
    select_optional.append(f"vuln.{cvss_vector_col} AS cvss_vector" if cvss_vector_col else "NULL AS cvss_vector")
    select_optional.append(f"vuln.{purl_col} AS vuln_purl" if purl_col else "NULL AS vuln_purl")

    optional_sql = ",\n        ".join(select_optional)

    return f"""
    SELECT
        p.id AS project_id,
        p.name AS project_name,
        v.id AS version_id,
        v.sha1 AS sha1,
        v.date_commit AS date_commit,
        vv.id AS version_vulnerability_id,
        vv.file AS file,
        vv.versionNumber AS versionNumber,
        vv.commitsBetween AS commitsBetween,
        e.id AS execution_id,
        h.id AS heuristic_id,
        h.pattern AS heuristic_pattern,
        l.id AS label_id,
        l.name AS db_name,
        l.type AS label_type,
        vuln.id AS vulnerability_id,
        vuln.name AS vulnerability_name,
        vuln.status AS vulnerability_status,
        vuln.description AS vulnerability_description,
        vuln.reference AS reference,
        vuln.version AS vulnerable_version,
        {optional_sql}
    FROM version_vulnerability vv
    JOIN version v
      ON v.id = vv.version_id
    JOIN project p
      ON p.id = v.project_id
    LEFT JOIN execution e
      ON e.id = vv.execution_id
    LEFT JOIN heuristic h
      ON h.id = e.heuristic_id
    LEFT JOIN label l
      ON l.id = h.label_id
    LEFT JOIN vulnerability vuln
      ON vuln.label_id = l.id
     AND TRIM(LOWER(vuln.version)) = TRIM(LOWER(vv.versionNumber))
    """


def load_base_dataframe(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query(build_base_query(conn), conn)

    text_cols = [
        "project_name", "sha1", "file", "versionNumber", "heuristic_pattern",
        "db_name", "label_type", "vulnerability_name", "vulnerability_status",
        "vulnerability_description", "reference", "vulnerable_version", "vuln_purl",
    ]
    for col in text_cols:
        if col in df.columns:
            df[col] = normalize_text(df[col])

    for col in ["date_commit", "published_at", "last_modified_at"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    for col in [
        "project_id", "version_id", "version_vulnerability_id", "execution_id",
        "heuristic_id", "label_id", "vulnerability_id", "commitsBetween", "cvss_score",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["project_name", "versionNumber", "date_commit"]).copy()
    df["db_name"] = normalize_text(df["db_name"]).fillna("UNKNOWN_DB")
    df["is_vulnerable"] = df["vulnerability_id"].notna()

    return df.sort_values(
        ["project_id", "project_name", "file", "db_name", "date_commit", "sha1", "version_id", "vulnerability_id"],
        kind="mergesort"
    ).reset_index(drop=True)


def deduplicate_history(base_df: pd.DataFrame) -> pd.DataFrame:
    subset_cols = [
        "project_id", "project_name", "file", "db_name",
        "version_id", "sha1", "date_commit", "versionNumber",
    ]
    dedup = base_df[subset_cols].drop_duplicates().copy()
    return dedup.sort_values(
        ["project_id", "project_name", "file", "db_name", "date_commit", "sha1", "version_id"],
        kind="mergesort"
    ).reset_index(drop=True)


def build_summary(history_df: pd.DataFrame) -> pd.DataFrame:
    return (
        history_df.groupby(["project_id", "project_name", "file", "db_name"], dropna=False)
        .agg(
            distinct_versions=("versionNumber", "nunique"),
            first_commit=("date_commit", "min"),
            last_commit=("date_commit", "max"),
            total_commits_observed=("sha1", "nunique"),
            total_rows=("version_id", "count"),
        )
        .reset_index()
        .rename(columns={"project_name": "project", "db_name": "db"})
        .sort_values(["project", "db", "file"], kind="mergesort")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrai a base intermediária para as RQs a partir do SQLite.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Diretório de saída dos CSVs.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    db_path = resolve_default_db_path()
    logging.info("Banco localizado em: %s", db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        base_df = load_base_dataframe(conn)
    finally:
        conn.close()

    history_df = deduplicate_history(base_df)
    summary_df = build_summary(history_df)

    (output_dir / "base_rqs.csv").write_text("", encoding="utf-8")
    base_df.to_csv(output_dir / "base_rqs.csv", index=False)
    history_df.to_csv(output_dir / "historico_dedup.csv", index=False)
    summary_df.to_csv(output_dir / "resumo_base.csv", index=False)

    logging.info("CSV gerado: %s", output_dir / "base_rqs.csv")
    logging.info("CSV gerado: %s", output_dir / "historico_dedup.csv")
    logging.info("CSV gerado: %s", output_dir / "resumo_base.csv")
    logging.info("Linhas base: %s", len(base_df))
    logging.info("Linhas histórico deduplicado: %s", len(history_df))


if __name__ == "__main__":
    main()
