#!/usr/bin/env python3
import argparse
import logging
from pathlib import Path

from rq_pipeline_common import (
    build_rq1_associations,
    build_rq1_db_usage_summary,
    build_rq1_project_summary,
    normalize_text,
    read_csv_required,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

DEFAULT_INPUT_DIR = "rqs_data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gera as saidas da RQ1 a partir de vulnerability_analysis_base.csv."
    )
    parser.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        help="Diretorio com vulnerability_analysis_base.csv.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir)

    base_df = read_csv_required(input_dir / "vulnerability_analysis_base.csv")
    if "is_vulnerable" not in base_df.columns:
        raise ValueError("vulnerability_analysis_base.csv deve conter a coluna is_vulnerable.")

    base_df["db_name"] = normalize_text(base_df["db_name"])
    is_vulnerable = base_df["is_vulnerable"]
    if is_vulnerable.dtype == bool:
        vulnerable_mask = is_vulnerable
    else:
        vulnerable_mask = (
            is_vulnerable.astype("string")
            .str.strip()
            .str.lower()
            .isin(["true", "1", "yes", "sim"])
        )

    matched_vuln_df = base_df[vulnerable_mask].copy()
    if not matched_vuln_df.empty:
        matched_vuln_df["db"] = matched_vuln_df["db_name"]

    rq1_assoc = build_rq1_associations(base_df)
    rq1_projects = build_rq1_project_summary(rq1_assoc)
    rq1_dbms = build_rq1_db_usage_summary(rq1_assoc, base_df)

    matched_path = input_dir / "rq1_base_vulnerabilidades_cruzadas.csv"
    assoc_path = input_dir / "vulnerability_release_project_associations.csv"
    projects_path = input_dir / "rq3_project_vulnerability_exposure_summary.csv"
    dbms_path = input_dir / "rq3_dbms_project_exposure_summary.csv"

    matched_vuln_df.to_csv(matched_path, index=False)
    rq1_assoc.to_csv(assoc_path, index=False)
    rq1_projects.to_csv(projects_path, index=False)
    rq1_dbms.to_csv(dbms_path, index=False)

    logging.info("CSV gerado: %s", matched_path)
    logging.info("CSV gerado: %s", assoc_path)
    logging.info("CSV gerado: %s", projects_path)
    logging.info("CSV gerado: %s", dbms_path)


if __name__ == "__main__":
    main()
