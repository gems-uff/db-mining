#!/usr/bin/env python3
import argparse
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

DEFAULT_INPUT_FILE = "rqs_data/vulnerability_release_project_associations.csv"
DEFAULT_DATA_DIR = "rqs_data"
DEFAULT_OUTPUT_DIR = "graficos_rq4"

BUCKET_ORDER = [
    "Before disclosure",
    "0–1 day",
    "2–30 days",
    "31–180 days",
    "181–365 days",
    ">365 days",
    "Missing resolution date",
    "Missing publication date",
]

BUCKET_COLORS = {
    "Before disclosure": "#dbe9f6",
    "0–1 day": "#a9cce3",
    "2–30 days": "#6fa8dc",
    "31–180 days": "#3d85c6",
    "181–365 days": "#1c4587",
    ">365 days": "#0b2f5b",
    "Missing resolution date": "#08213f",
    "Missing publication date": "#041426",
}

LIGHT_TEXT_BUCKETS = {
    "31–180 days",
    "181–365 days",
    ">365 days",
    "Missing resolution date",
    "Missing publication date",
}


def normalize_db_display_names(series):
    return series.replace({
        "MS SQL Server_Microsoft Azure SQL Database": "MSSQL/MicrosoftAzure",
    })


def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)


def join_unique(values):
    clean = sorted({
        str(value).strip()
        for value in values.dropna()
        if str(value).strip() and str(value).strip().lower() != "nan"
    })
    return "; ".join(clean)


def classify_resolution_bucket(row):
    if not row["has_publication_date"]:
        return "Missing publication date"
    if not row["has_resolution_date"]:
        return "Missing resolution date"

    days = row["resolution_days"]
    if days < 0:
        return "Before disclosure"
    if days <= 1:
        return "0–1 day"
    if days <= 30:
        return "2–30 days"
    if days <= 180:
        return "31–180 days"
    if days <= 365:
        return "181–365 days"
    return ">365 days"


def build_release_cve_dataset(input_file):
    df = pd.read_csv(input_file)
    required = [
        "db",
        "versionNumber",
        "cve",
        "published_at",
        "resolved_at",
        "first_patched_version",
        "project",
    ]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"CSV must contain columns: {missing}")

    df = df[required].copy()
    df["db"] = normalize_db_display_names(df["db"].astype("string").str.strip())
    df["versionNumber"] = df["versionNumber"].astype("string").str.strip()
    df["cve"] = df["cve"].astype("string").str.strip()
    df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce", utc=True)
    df["resolved_at"] = pd.to_datetime(df["resolved_at"], errors="coerce", utc=True)

    df = df[
        df["db"].notna()
        & df["db"].ne("")
        & df["versionNumber"].notna()
        & df["versionNumber"].ne("")
        & df["cve"].notna()
        & df["cve"].ne("")
    ].copy()

    release_cve = (
        df.groupby(["db", "versionNumber", "cve"], dropna=False)
        .agg(
            published_at=("published_at", "min"),
            resolved_at=("resolved_at", "min"),
            first_patched_version=("first_patched_version", join_unique),
            projects=("project", "nunique"),
        )
        .reset_index()
        .rename(columns={"versionNumber": "release"})
    )
    release_cve["resolution_days"] = (
        release_cve["resolved_at"] - release_cve["published_at"]
    ).dt.total_seconds() / 86400
    release_cve["has_publication_date"] = release_cve["published_at"].notna()
    release_cve["has_resolution_date"] = release_cve["resolved_at"].notna()
    release_cve["has_first_patched_release"] = (
        release_cve["first_patched_version"].astype("string").str.len().fillna(0) > 0
    )
    release_cve["resolution_bucket"] = release_cve.apply(
        classify_resolution_bucket,
        axis=1,
    )
    return release_cve


def percentile(series, value):
    clean = series.dropna()
    return clean.quantile(value) if not clean.empty else pd.NA


def build_summary_by_dbms(release_cve):
    summary = (
        release_cve.groupby("db", dropna=False)
        .agg(
            release_cve_records=("cve", "size"),
            unique_cves=("cve", "nunique"),
            vulnerable_releases=("release", "nunique"),
            records_with_resolution_date=("has_resolution_date", "sum"),
            records_with_first_patched_release=("has_first_patched_release", "sum"),
            resolved_before_publication=("resolution_days", lambda s: (s < 0).sum()),
            median_signed_resolution_days=("resolution_days", "median"),
            p75_signed_resolution_days=("resolution_days", lambda s: percentile(s, 0.75)),
            median_nonnegative_resolution_days=(
                "resolution_days",
                lambda s: s[s >= 0].median(),
            ),
            max_nonnegative_resolution_days=(
                "resolution_days",
                lambda s: s[s >= 0].max(),
            ),
        )
        .reset_index()
    )
    summary["resolution_date_coverage_pct"] = (
        summary["records_with_resolution_date"]
        / summary["release_cve_records"]
        * 100
    ).round(1)
    summary["first_patched_release_coverage_pct"] = (
        summary["records_with_first_patched_release"]
        / summary["release_cve_records"]
        * 100
    ).round(1)

    numeric_cols = [
        "median_signed_resolution_days",
        "p75_signed_resolution_days",
        "median_nonnegative_resolution_days",
        "max_nonnegative_resolution_days",
    ]
    summary[numeric_cols] = summary[numeric_cols].round(1)
    return summary.sort_values(
        ["median_nonnegative_resolution_days", "release_cve_records"],
        ascending=[False, False],
        na_position="last",
    )


def build_bucket_table(release_cve):
    table = (
        release_cve.pivot_table(
            index="db",
            columns="resolution_bucket",
            values="cve",
            aggfunc="size",
            fill_value=0,
        )
        .reindex(columns=BUCKET_ORDER, fill_value=0)
        .reset_index()
    )
    table["total"] = table[BUCKET_ORDER].sum(axis=1)
    return table.sort_values("total", ascending=False)


def plot_bucket_distribution(bucket_table, output_dir):
    plot_df = bucket_table.set_index("db")[BUCKET_ORDER]
    plot_df = plot_df.loc[plot_df.sum(axis=1).sort_values().index]
    db_totals = plot_df.sum(axis=1)

    fig, ax = plt.subplots(figsize=(13, max(6, len(plot_df) * 0.45)))
    left = pd.Series(0, index=plot_df.index, dtype=float)
    for bucket in BUCKET_ORDER:
        values = plot_df[bucket]
        if values.sum() == 0:
            continue
        ax.barh(
            plot_df.index,
            values,
            left=left,
            label=bucket,
            color=BUCKET_COLORS[bucket],
            edgecolor="black",
            linewidth=0.4,
        )
        for db, value in values.items():
            if value <= 0:
                continue
            ax.text(
                left[db] + value / 2,
                db,
                str(int(value)),
                va="center",
                ha="center",
                fontsize=8,
                color="white" if bucket in LIGHT_TEXT_BUCKETS else "black",
            )
        left += values

    ax.set_xlabel("Number of vulnerable release–CVE records")
    ax.set_ylabel("DBMS")
    ax.set_xlim(0, db_totals.max() * 1.04)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.32), ncol=3, frameon=True)
    fig.tight_layout(rect=[0, 0.16, 1, 1])

    output = Path(output_dir) / "rq4_release_cve_resolution_timing_by_dbms.png"
    fig.savefig(output, dpi=300, bbox_inches="tight")
    pdf_output = output.with_suffix(".pdf")
    fig.savefig(pdf_output, bbox_inches="tight")
    plt.close(fig)
    logging.info("Graph saved: %s", pdf_output)
    logging.info("Graph saved: %s", output)


def export_outputs(release_cve, summary, bucket_table, data_dir):
    data_dir = Path(data_dir)
    release_cve.to_csv(
        data_dir / "rq4_release_cve_resolution_dates.csv",
        index=False,
    )
    summary.to_csv(
        data_dir / "rq4_release_cve_resolution_summary_by_dbms.csv",
        index=False,
    )
    bucket_table.to_csv(
        data_dir / "rq4_release_cve_resolution_buckets_by_dbms.csv",
        index=False,
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Compare publication and resolution dates for unique DBMS-release-CVE records."
        )
    )
    parser.add_argument("--input-file", default=DEFAULT_INPUT_FILE)
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main():
    args = parse_args()
    ensure_dir(args.data_dir)
    ensure_dir(args.output_dir)

    release_cve = build_release_cve_dataset(args.input_file)
    summary = build_summary_by_dbms(release_cve)
    bucket_table = build_bucket_table(release_cve)

    export_outputs(release_cve, summary, bucket_table, args.data_dir)
    plot_bucket_distribution(bucket_table, args.output_dir)

    logging.info("Unique DBMS-release-CVE records: %d", len(release_cve))
    logging.info("Unique CVEs: %d", release_cve["cve"].nunique())
    logging.info("Unique DBMS releases: %d", release_cve[["db", "release"]].drop_duplicates().shape[0])


if __name__ == "__main__":
    main()
