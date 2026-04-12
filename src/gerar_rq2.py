#!/usr/bin/env python3
import argparse
import logging
from pathlib import Path

import numpy as np
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


def pick_disclosure_date_column(rq1_assoc: pd.DataFrame) -> str:
    has_published = "published_at" in rq1_assoc.columns and rq1_assoc["published_at"].notna().any()
    if has_published:
        return "published_at"
    return "last_modified_at"


def build_rq2_exposures(rq1_assoc: pd.DataFrame) -> pd.DataFrame:
    if rq1_assoc.empty:
        return pd.DataFrame()

    df = rq1_assoc.copy()

    for col in ["first_seen_in_project", "last_seen_in_project", "published_at", "last_modified_at"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    disclosure_col = pick_disclosure_date_column(df)
    df["disclosure_date_used"] = pd.to_datetime(df[disclosure_col], errors="coerce")
    df["disclosure_source"] = disclosure_col

    df["pre_disclosure_days"] = 0.0
    pre_mask = df["disclosure_date_used"].notna() & (df["first_seen_in_project"] < df["disclosure_date_used"])
    if pre_mask.any():
        pre_end = pd.Series(
            np.minimum(
                df.loc[pre_mask, "last_seen_in_project"].values.astype("datetime64[ns]"),
                df.loc[pre_mask, "disclosure_date_used"].values.astype("datetime64[ns]")
            )
        )
        df.loc[pre_mask, "pre_disclosure_days"] = (
            pre_end.values.astype("datetime64[ns]") -
            df.loc[pre_mask, "first_seen_in_project"].values.astype("datetime64[ns]")
        ).astype("timedelta64[D]").astype(float)

    df["post_disclosure_days"] = 0.0
    post_mask = df["disclosure_date_used"].notna() & (df["last_seen_in_project"] >= df["disclosure_date_used"])
    if post_mask.any():
        post_start = pd.Series(
            np.maximum(
                df.loc[post_mask, "first_seen_in_project"].values.astype("datetime64[ns]"),
                df.loc[post_mask, "disclosure_date_used"].values.astype("datetime64[ns]")
            )
        )
        df.loc[post_mask, "post_disclosure_days"] = (
            df.loc[post_mask, "last_seen_in_project"].values.astype("datetime64[ns]") -
            post_start.values.astype("datetime64[ns]")
        ).astype("timedelta64[D]").astype(float) + 1.0

    df["total_exposure_days"] = (
        df["last_seen_in_project"] - df["first_seen_in_project"]
    ).dt.days + 1

    df["was_publicly_known_during_use"] = df["post_disclosure_days"] > 0
    df["used_before_disclosure"] = df["pre_disclosure_days"] > 0

    return df.sort_values(
        ["project", "db", "file", "first_seen_in_project", "cve"],
        kind="mergesort"
    )


def build_rq2_summary(rq2_df: pd.DataFrame) -> pd.DataFrame:
    if rq2_df.empty:
        return pd.DataFrame()

    return (
        rq2_df.groupby(["db"], dropna=False)
        .agg(
            projects_affected=("project", "nunique"),
            vulnerability_occurrences=("cve", "count"),
            median_total_exposure_days=("total_exposure_days", "median"),
            mean_total_exposure_days=("total_exposure_days", "mean"),
            median_pre_disclosure_days=("pre_disclosure_days", "median"),
            mean_pre_disclosure_days=("pre_disclosure_days", "mean"),
            median_post_disclosure_days=("post_disclosure_days", "median"),
            mean_post_disclosure_days=("post_disclosure_days", "mean"),
            max_post_disclosure_days=("post_disclosure_days", "max"),
        )
        .reset_index()
        .sort_values(
            ["median_post_disclosure_days", "mean_total_exposure_days", "db"],
            ascending=[False, False, True],
            kind="mergesort"
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera as saídas da RQ2 a partir da RQ1.")
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR, help="Diretório com rq1_associacoes.csv.")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    rq1_assoc = read_csv_required(input_dir / "rq1_associacoes.csv")

    rq2_df = build_rq2_exposures(rq1_assoc)
    rq2_summary = build_rq2_summary(rq2_df)

    rq2_df.to_csv(input_dir / "rq2_exposicoes.csv", index=False)
    rq2_summary.to_csv(input_dir / "rq2_resumo.csv", index=False)

    logging.info("CSV gerado: %s", input_dir / "rq2_exposicoes.csv")
    logging.info("CSV gerado: %s", input_dir / "rq2_resumo.csv")


if __name__ == "__main__":
    main()