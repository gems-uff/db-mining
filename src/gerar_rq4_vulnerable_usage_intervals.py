#!/usr/bin/env python3
import argparse
import logging
from pathlib import Path

import pandas as pd

from search_vulnerabilites import compare_versions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

DEFAULT_INPUT = "rqs_data/vulnerability_analysis_base.csv"
DEFAULT_OUTPUT = "rqs_data/rq4_vulnerable_usage_intervals.csv"

SEGMENT_KEYS = ["project_id", "project_name", "db_name"]
OBSERVATION_KEYS = SEGMENT_KEYS + [
    "version_id",
    "sha1",
    "date_commit",
    "versionNumber",
]
VULNERABILITY_KEYS = ["db_name", "versionNumber", "reference"]


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Cruza intervalos consecutivos de uso de uma versão de DBMS com "
            "as datas de divulgação e correção das vulnerabilidades."
        )
    )
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--dbms",
        help="Filtra o DBMS antes de gerar o CSV, por exemplo: H2.",
    )
    return parser.parse_args()


def as_boolean(series):
    if series.dtype == bool:
        return series.fillna(False)
    return (
        series.astype("string")
        .str.strip()
        .str.lower()
        .isin(["true", "1", "yes", "sim"])
    )


def join_unique(values):
    return "; ".join(
        sorted({str(value).strip() for value in values.dropna() if str(value).strip()})
    )


def elapsed_days(start, end):
    if pd.isna(start) or pd.isna(end) or end <= start:
        return 0.0
    return (end - start).total_seconds() / 86400.0


def overlap_days(start_a, end_a, start_b, end_b):
    if any(pd.isna(value) for value in [start_a, end_a, start_b, end_b]):
        return 0.0
    return elapsed_days(max(start_a, start_b), min(end_a, end_b))


def prepare_base(path, dbms=None):
    df = pd.read_csv(path)
    required = set(OBSERVATION_KEYS + [
        "file",
        "commitsBetween",
        "is_vulnerable",
        "reference",
        "published_at",
        "resolved_at",
        "first_patched_version",
    ])
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Colunas obrigatórias ausentes: {missing}")

    for column in ["date_commit", "published_at", "resolved_at"]:
        df[column] = pd.to_datetime(df[column], errors="coerce", utc=True)

    df["is_vulnerable"] = as_boolean(df["is_vulnerable"])
    df["commitsBetween"] = pd.to_numeric(
        df["commitsBetween"], errors="coerce"
    ).fillna(0)

    if dbms:
        df = df[df["db_name"] == dbms].copy()

    return df[df["date_commit"].notna()].copy()


def build_usage_segments(base):
    observations = (
        base[OBSERVATION_KEYS + ["file", "commitsBetween"]]
        .groupby(OBSERVATION_KEYS, dropna=False)
        .agg(
            commits_between=("commitsBetween", "max"),
            files=("file", join_unique),
            n_files=("file", "nunique"),
        )
        .reset_index()
        .sort_values(SEGMENT_KEYS + ["versionNumber", "date_commit", "sha1", "version_id"])
    )

    parts = []
    for _, group in observations.groupby(SEGMENT_KEYS, sort=False, dropna=False):
        segments = []
        project_id = group["project_id"].iloc[0]
        project = group["project_name"].iloc[0]
        db = group["db_name"].iloc[0]

        for version, version_group in group.groupby("versionNumber", sort=False, dropna=False):
            version_group = version_group.sort_values(
                ["date_commit", "sha1", "version_id"], kind="mergesort"
            )
            usage_start = version_group["date_commit"].min()
            last_seen = version_group["date_commit"].max()
            later_other_version = group[
                (group["date_commit"] > last_seen)
                & (group["versionNumber"] != version)
            ]
            usage_stop = (
                later_other_version["date_commit"].min()
                if not later_other_version.empty
                else pd.NaT
            )

            segments.append({
                "project_id": project_id,
                "project": project,
                "files": join_unique(version_group["files"]),
                "n_files": int(version_group["n_files"].max()),
                "db": db,
                "version": version,
                "usage_start": usage_start,
                "first_commit_sha": version_group["sha1"].iloc[0],
                "last_seen": last_seen,
                "last_seen_commit_sha": version_group["sha1"].iloc[-1],
                "usage_stop": usage_stop,
                "observed_slices": version_group["version_id"].nunique(),
                "activity_commits": version_group["commits_between"].sum(),
            })

        segments = pd.DataFrame(segments).sort_values(
            ["usage_start", "last_seen", "version"], kind="mergesort"
        )
        segments["stop_reason"] = segments["usage_stop"].notna().map(
            {True: "version_changed", False: "right_censored_no_later_version"}
        )
        segments["comparison_end"] = segments["usage_stop"].fillna(
            segments["last_seen"]
        )
        segments["usage_interval_days_observed"] = segments.apply(
            lambda row: elapsed_days(row["usage_start"], row["comparison_end"]),
            axis=1,
        )
        parts.append(segments)

    result = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if not result.empty:
        result.insert(0, "usage_segment_id", range(1, len(result) + 1))
    return result


def build_vulnerability_catalog(base):
    vulnerable = base[
        base["is_vulnerable"]
        & base["reference"].notna()
        & base["reference"].astype("string").str.strip().ne("")
    ].copy()

    inferred_patches = (
        vulnerable[
            vulnerable["first_patched_version"].notna()
            & vulnerable["first_patched_version"].astype("string").str.strip().ne("")
        ]
        .groupby(["db_name", "reference"], dropna=False)["first_patched_version"]
        .agg(lambda values: sorted(set(values.astype(str).str.strip())))
    )
    inferred_patches = {
        key: values[0]
        for key, values in inferred_patches.items()
        if len(values) == 1
    }
    vulnerable["effective_published_at"] = vulnerable.groupby(
        ["db_name", "reference"], dropna=False
    )["published_at"].transform("min")
    vulnerable["effective_resolved_at"] = vulnerable.groupby(
        ["db_name", "reference"], dropna=False
    )["resolved_at"].transform("min")

    def version_is_vulnerable(row):
        patch = row["first_patched_version"]
        if pd.isna(patch) or not str(patch).strip():
            patch = inferred_patches.get((row["db_name"], row["reference"]))
        if pd.isna(patch) or not str(patch).strip():
            return True
        comparison = compare_versions(str(row["versionNumber"]), str(patch))
        return comparison is None or comparison < 0

    vulnerable = vulnerable[vulnerable.apply(version_is_vulnerable, axis=1)]
    vulnerable["effective_first_patched_version"] = vulnerable.apply(
        lambda row: (
            str(row["first_patched_version"]).strip()
            if pd.notna(row["first_patched_version"])
            and str(row["first_patched_version"]).strip()
            else inferred_patches.get((row["db_name"], row["reference"]))
        ),
        axis=1,
    )
    if vulnerable.empty:
        return pd.DataFrame()

    aggregations = {
        "published_at": ("effective_published_at", "min"),
        "resolved_at": ("effective_resolved_at", "min"),
        "first_patched_version": ("effective_first_patched_version", join_unique),
    }
    if "cvss_score" in vulnerable.columns:
        aggregations["cvss_score"] = ("cvss_score", "first")
    if "cvss_severity" in vulnerable.columns:
        aggregations["cvss_severity"] = ("cvss_severity", "first")

    return (
        vulnerable.groupby(VULNERABILITY_KEYS, dropna=False)
        .agg(**aggregations)
        .reset_index()
        .rename(columns={
            "db_name": "db",
            "versionNumber": "version",
            "reference": "cve",
        })
    )


def add_overlap_metrics(segments, catalog):
    result = segments.merge(catalog, on=["db", "version"], how="left")
    result["has_known_vulnerability"] = result["cve"].notna()

    def metrics(row):
        start = row["usage_start"]
        end = row["comparison_end"]
        published = row["published_at"]
        resolved = row["resolved_at"]

        pre_disclosure = (
            overlap_days(start, end, start, min(end, published))
            if pd.notna(published)
            else 0.0
        )
        known_unresolved = (
            overlap_days(start, end, published, resolved)
            if pd.notna(published) and pd.notna(resolved)
            else overlap_days(start, end, published, end)
            if pd.notna(published)
            else 0.0
        )
        post_resolution = (
            overlap_days(start, end, resolved, end)
            if pd.notna(resolved)
            else 0.0
        )
        return pd.Series({
            "pre_disclosure_overlap_days": pre_disclosure,
            "known_unresolved_overlap_days": known_unresolved,
            "post_resolution_vulnerable_use_days": post_resolution,
            "resolution_before_disclosure": (
                pd.notna(published)
                and pd.notna(resolved)
                and resolved < published
            ),
            "used_when_vulnerability_public": known_unresolved > 0,
            "continued_using_after_resolution": post_resolution > 0,
        })

    calculated = result.apply(metrics, axis=1)
    return pd.concat([result, calculated], axis=1)


def main():
    args = parse_args()
    base = prepare_base(args.input, args.dbms)
    segments = build_usage_segments(base)
    catalog = build_vulnerability_catalog(base)
    result = add_overlap_metrics(segments, catalog)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False)

    logging.info("CSV gerado: %s", output)
    logging.info(
        "Segmentos de uso: %d | associações segmento-CVE: %d | "
        "segmentos vulneráveis: %d | términos censurados: %d",
        result["usage_segment_id"].nunique(),
        int(result["cve"].notna().sum()),
        result.loc[result["has_known_vulnerability"], "usage_segment_id"].nunique(),
        result.loc[
            result["stop_reason"] == "right_censored_no_later_version",
            "usage_segment_id",
        ].nunique(),
    )


if __name__ == "__main__":
    main()
