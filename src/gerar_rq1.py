#!/usr/bin/env python3
import argparse
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

DEFAULT_INPUT_DIR = "rqs_data"


def read_csv_required(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    return pd.read_csv(path)


def build_rq1_associations(base_df: pd.DataFrame) -> pd.DataFrame:
    for col in ["date_commit", "published_at", "last_modified_at"]:
        if col in base_df.columns:
            base_df[col] = pd.to_datetime(base_df[col], errors="coerce")

    vuln_df = base_df[base_df["is_vulnerable"] == True].copy()
    if vuln_df.empty:
        return pd.DataFrame()

    rq1 = (
        vuln_df.groupby(
            [
                "project_id", "project_name", "file", "db_name",
                "versionNumber", "vulnerability_id", "reference",
            ],
            dropna=False
        )
        .agg(
            first_seen_in_project=("date_commit", "min"),
            last_seen_in_project=("date_commit", "max"),
            commits_observed=("sha1", "nunique"),
            rows_observed=("version_vulnerability_id", "count"),
            published_at=("published_at", "first"),
            last_modified_at=("last_modified_at", "first"),
            cvss_score=("cvss_score", "first"),
            cvss_severity=("cvss_severity", "first"),
            cvss_vector=("cvss_vector", "first"),
            vulnerability_status=("vulnerability_status", "first"),
            vulnerability_name=("vulnerability_name", "first"),
            vulnerability_description=("vulnerability_description", "first"),
            vuln_purl=("vuln_purl", "first"),
        )
        .reset_index()
        .rename(columns={
            "project_name": "project",
            "db_name": "db",
            "reference": "cve",
        })
        .sort_values(["project", "db", "file", "first_seen_in_project", "cve"], kind="mergesort")
    )
    return rq1


def build_rq1_project_summary(rq1_assoc: pd.DataFrame) -> pd.DataFrame:
    if rq1_assoc.empty:
        return pd.DataFrame()
    return (
        rq1_assoc.groupby(["project_id", "project"], dropna=False)
        .agg(
            dbms_affected=("db", "nunique"),
            vulnerable_versions=("versionNumber", "nunique"),
            vulnerability_occurrences=("cve", "count"),
        )
        .reset_index()
        .sort_values(["vulnerability_occurrences", "dbms_affected", "project"], ascending=[False, False, True], kind="mergesort")
    )


def build_rq1_db_summary(rq1_assoc: pd.DataFrame) -> pd.DataFrame:
    if rq1_assoc.empty:
        return pd.DataFrame()
    return (
        rq1_assoc.groupby(["db"], dropna=False)
        .agg(
            projects_affected=("project", "nunique"),
            vulnerable_versions=("versionNumber", "nunique"),
            vulnerability_occurrences=("cve", "count"),
        )
        .reset_index()
        .sort_values(["projects_affected", "vulnerability_occurrences", "db"], ascending=[False, False, True], kind="mergesort")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera as saídas da RQ1 a partir da base intermediária.")
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR, help="Diretório com base_rqs.csv.")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    base_df = read_csv_required(input_dir / "base_rqs.csv")

    rq1_assoc = build_rq1_associations(base_df)
    rq1_projects = build_rq1_project_summary(rq1_assoc)
    rq1_dbms = build_rq1_db_summary(rq1_assoc)

    rq1_assoc.to_csv(input_dir / "rq1_associacoes.csv", index=False)
    rq1_projects.to_csv(input_dir / "rq1_projetos.csv", index=False)
    rq1_dbms.to_csv(input_dir / "rq1_dbms.csv", index=False)

    logging.info("CSV gerado: %s", input_dir / "rq1_associacoes.csv")
    logging.info("CSV gerado: %s", input_dir / "rq1_projetos.csv")
    logging.info("CSV gerado: %s", input_dir / "rq1_dbms.csv")


if __name__ == "__main__":
    main()
