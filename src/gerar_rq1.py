#!/usr/bin/env python3
import argparse
import logging
import sqlite3
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

DEFAULT_INPUT_DIR = "rqs_data"
DEFAULT_DB_PATH = "dbmining.sqlite"


def read_csv_required(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    return pd.read_csv(path)


def normalize_text(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()


def read_vulnerability_catalog_from_sqlite(db_path: Path) -> pd.DataFrame:
    if not db_path.exists():
        raise FileNotFoundError(f"Banco não encontrado: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        query = """
            SELECT DISTINCT
                v.id AS vulnerability_id,
                TRIM(l.name) AS db,
                TRIM(v.version) AS versionNumber,
                v.reference,
                v.status AS vulnerability_status
            FROM vulnerability AS v
            JOIN label AS l
              ON l.id = v.label_id
            WHERE l.name IS NOT NULL
              AND TRIM(l.name) <> ''
              AND v.version IS NOT NULL
              AND TRIM(v.version) <> ''
        """
        vuln_df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

    if vuln_df.empty:
        return vuln_df

    vuln_df["db"] = normalize_text(vuln_df["db"])
    vuln_df["versionNumber"] = normalize_text(vuln_df["versionNumber"])
    vuln_df["reference"] = normalize_text(vuln_df["reference"]).replace({"nan": pd.NA, "None": pd.NA})
    vuln_df["vulnerability_status"] = normalize_text(vuln_df["vulnerability_status"]).replace({"nan": pd.NA, "None": pd.NA})

    return vuln_df


def build_matched_vulnerability_df(base_df: pd.DataFrame, vuln_catalog_df: pd.DataFrame) -> pd.DataFrame:
    required_base_cols = [
        "project_id", "project_name", "db_name", "versionNumber",
        "date_commit", "sha1"
    ]
    missing = [col for col in required_base_cols if col not in base_df.columns]
    if missing:
        raise ValueError(f"Colunas obrigatórias ausentes em base_rqs.csv: {missing}")

    if vuln_catalog_df.empty:
        return pd.DataFrame()

    base = base_df.copy()

    for col in ["date_commit", "published_at", "last_modified_at"]:
        if col in base.columns:
            base[col] = pd.to_datetime(base[col], errors="coerce")

    base["db"] = normalize_text(base["db_name"])
    base["versionNumber"] = normalize_text(base["versionNumber"])
    base = base[
        base["db"].ne("") &
        base["versionNumber"].ne("")
    ].copy()

    if base.empty:
        return pd.DataFrame()

    matched = base.merge(
        vuln_catalog_df,
        on=["db", "versionNumber"],
        how="inner",
        suffixes=("", "_catalog")
    )

    if matched.empty:
        return matched

    matched["reference"] = matched["reference"].replace({"nan": pd.NA, "None": pd.NA})
    matched["vulnerability_status"] = matched["vulnerability_status"].replace({"nan": pd.NA, "None": pd.NA})

    return matched


def build_rq1_associations(matched_df: pd.DataFrame) -> pd.DataFrame:
    if matched_df.empty:
        return pd.DataFrame()

    group_cols = [
        "project_id",
        "project_name",
        "db",
        "versionNumber",
        "vulnerability_id",
        "reference",
    ]

    if "file" in matched_df.columns:
        group_cols.insert(2, "file")

    agg_map = {
        "first_seen_in_project": ("date_commit", "min"),
        "last_seen_in_project": ("date_commit", "max"),
        "commits_observed": ("sha1", "nunique"),
    }

    if "version_vulnerability_id" in matched_df.columns:
        agg_map["rows_observed"] = ("version_vulnerability_id", "count")
    else:
        agg_map["rows_observed"] = ("sha1", "count")

    optional_first_fields = [
        "published_at",
        "last_modified_at",
        "cvss_score",
        "cvss_severity",
        "cvss_vector",
        "vulnerability_status",
        "vulnerability_name",
        "vulnerability_description",
        "vuln_purl",
    ]

    for field in optional_first_fields:
        if field in matched_df.columns:
            agg_map[field] = (field, "first")

    rq1 = (
        matched_df.groupby(group_cols, dropna=False)
        .agg(**agg_map)
        .reset_index()
        .rename(columns={
            "project_name": "project",
            "reference": "cve",
        })
    )

    sort_cols = ["project", "db", "first_seen_in_project", "versionNumber", "vulnerability_id"]
    if "file" in rq1.columns:
        sort_cols.insert(2, "file")

    rq1 = rq1.sort_values(sort_cols, kind="mergesort")
    return rq1


def build_rq1_project_summary(rq1_assoc: pd.DataFrame) -> pd.DataFrame:
    if rq1_assoc.empty:
        return pd.DataFrame()

    return (
        rq1_assoc.groupby(["project_id", "project"], dropna=False)
        .agg(
            dbms_affected=("db", "nunique"),
            vulnerable_versions=("versionNumber", "nunique"),
            vulnerability_occurrences=("vulnerability_id", "nunique"),
        )
        .reset_index()
        .sort_values(
            ["vulnerability_occurrences", "dbms_affected", "project"],
            ascending=[False, False, True],
            kind="mergesort"
        )
    )


def build_rq1_db_summary(rq1_assoc: pd.DataFrame) -> pd.DataFrame:
    if rq1_assoc.empty:
        return pd.DataFrame()

    return (
        rq1_assoc.groupby(["db"], dropna=False)
        .agg(
            projects_affected=("project", "nunique"),
            vulnerable_versions=("versionNumber", "nunique"),
            vulnerability_occurrences=("vulnerability_id", "nunique"),
        )
        .reset_index()
        .sort_values(
            ["projects_affected", "vulnerability_occurrences", "db"],
            ascending=[False, False, True],
            kind="mergesort"
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera as saídas da RQ1 cruzando base_rqs.csv com o catálogo de vulnerability por BD + versão."
    )
    parser.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        help="Diretório com base_rqs.csv."
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help="Caminho para o banco SQLite."
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    db_path = Path(args.db_path)

    base_df = read_csv_required(input_dir / "base_rqs.csv")
    vuln_catalog_df = read_vulnerability_catalog_from_sqlite(db_path)
    matched_vuln_df = build_matched_vulnerability_df(base_df, vuln_catalog_df)

    rq1_assoc = build_rq1_associations(matched_vuln_df)
    rq1_projects = build_rq1_project_summary(rq1_assoc)
    rq1_dbms = build_rq1_db_summary(rq1_assoc)

    matched_vuln_df.to_csv(input_dir / "rq1_base_vulnerabilidades_cruzadas.csv", index=False)
    rq1_assoc.to_csv(input_dir / "rq1_associacoes.csv", index=False)
    rq1_projects.to_csv(input_dir / "rq1_projetos.csv", index=False)
    rq1_dbms.to_csv(input_dir / "rq1_dbms.csv", index=False)

    logging.info("CSV gerado: %s", input_dir / "rq1_base_vulnerabilidades_cruzadas.csv")
    logging.info("CSV gerado: %s", input_dir / "rq1_associacoes.csv")
    logging.info("CSV gerado: %s", input_dir / "rq1_projetos.csv")
    logging.info("CSV gerado: %s", input_dir / "rq1_dbms.csv")


if __name__ == "__main__":
    main()
