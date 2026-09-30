#!/usr/bin/env python3
"""Reproducible audit of severity, resolution timing, and post-fix exposure.

Reads existing project outputs only. It does not modify the source database or
the RQ data files. All derived files are written under --output-dir.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "MODERATE": 2, "HIGH": 3, "CRITICAL": 4}
SEVERITY_LABELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def spearman(x: pd.Series, y: pd.Series) -> dict:
    result = stats.spearmanr(x, y)
    rho = getattr(result, "statistic", getattr(result, "correlation", result[0]))
    return {"n": int(len(x)), "rho": float(rho), "p": float(result.pvalue)}


def kruskal(frame: pd.DataFrame, value: str) -> dict:
    groups = [g[value].to_numpy() for _, g in frame.groupby("severity", observed=True)]
    result = stats.kruskal(*groups)
    return {"n": int(len(frame)), "H": float(result.statistic), "p": float(result.pvalue)}


def describe(frame: pd.DataFrame, value: str) -> pd.DataFrame:
    return (
        frame.groupby("severity", observed=True)[value]
        .agg(n="count", median="median", mean="mean", minimum="min", maximum="max")
        .reindex(SEVERITY_LABELS)
        .reset_index()
    )


def merge_intervals(intervals: list[tuple[pd.Timestamp, pd.Timestamp]]) -> list[tuple]:
    clean = sorted((start, end) for start, end in intervals if pd.notna(start) and pd.notna(end) and end >= start)
    if not clean:
        return []
    merged = [list(clean[0])]
    for start, end in clean[1:]:
        # Adjacent observations are treated as continuous use.
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def build_question_a(db_path: Path) -> tuple[pd.DataFrame, dict, pd.DataFrame, pd.DataFrame]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    # Filtering by nonempty categorical severity permits an index-assisted scan
    # in this large database. Values are constant within reference (checked below).
    query = """
        SELECT reference, package_name, UPPER(TRIM(cvss_severity)) AS severity,
               NULLIF(TRIM(cvss_score), '') AS cvss_score,
               published_at, resolved_at
        FROM vulnerability
        WHERE TRIM(COALESCE(cvss_severity, '')) <> ''
        GROUP BY reference, package_name
    """
    raw = pd.read_sql_query(query, connection)
    connection.close()

    conflicts = {
        column: int((raw.groupby("reference")[column].nunique(dropna=True) > 1).sum())
        for column in ["severity", "cvss_score", "published_at", "resolved_at"]
    }
    # A CVE/GHSA reference is the study's definition of a distinct vulnerability.
    vulnerabilities = raw.sort_values(["reference", "package_name"]).drop_duplicates("reference").copy()
    vulnerabilities["published_at"] = pd.to_datetime(vulnerabilities["published_at"], utc=True, errors="coerce")
    vulnerabilities["resolved_at"] = pd.to_datetime(vulnerabilities["resolved_at"], utc=True, errors="coerce")
    vulnerabilities["cvss_score"] = pd.to_numeric(vulnerabilities["cvss_score"], errors="coerce")
    vulnerabilities["severity_ordinal"] = vulnerabilities["severity"].map(SEVERITY_ORDER)
    vulnerabilities["resolution_delay_days"] = (
        vulnerabilities["resolved_at"] - vulnerabilities["published_at"]
    ).dt.total_seconds() / 86400
    vulnerabilities["timing"] = np.select(
        [vulnerabilities["resolution_delay_days"] < 0, vulnerabilities["resolution_delay_days"] > 0],
        ["before_publication", "after_publication"],
        default="same_time",
    )

    complete = vulnerabilities.dropna(subset=["severity_ordinal", "resolution_delay_days"]).copy()
    after = complete[complete["resolution_delay_days"] > 0].copy()
    before = complete[complete["resolution_delay_days"] < 0].copy()
    before["prepublication_distance_days"] = -before["resolution_delay_days"]

    results = {
        "counts": {
            "distinct_vulnerabilities": int(len(vulnerabilities)),
            "complete_for_ordinal_timing": int(len(complete)),
            "missing_numeric_cvss": int(vulnerabilities["cvss_score"].isna().sum()),
            "missing_severity_category": int(vulnerabilities["severity_ordinal"].isna().sum()),
            "missing_published_at": int(vulnerabilities["published_at"].isna().sum()),
            "missing_resolved_at": int(vulnerabilities["resolved_at"].isna().sum()),
            "before_publication": int((complete["resolution_delay_days"] < 0).sum()),
            "after_publication": int((complete["resolution_delay_days"] > 0).sum()),
            "exactly_zero": int((complete["resolution_delay_days"] == 0).sum()),
        },
        "within_reference_conflicts": conflicts,
        "all_62_spearman": spearman(complete["severity_ordinal"], complete["resolution_delay_days"]),
        "all_62_kruskal": kruskal(complete, "resolution_delay_days"),
        "positive_delay_spearman": spearman(after["severity_ordinal"], after["resolution_delay_days"]),
        "positive_delay_kruskal": kruskal(after, "resolution_delay_days"),
        "prepublication_distance_spearman": spearman(
            before["severity_ordinal"], before["prepublication_distance_days"]
        ),
        "prepublication_distance_kruskal": kruskal(before, "prepublication_distance_days"),
    }
    return vulnerabilities, results, describe(complete, "resolution_delay_days"), describe(after, "resolution_delay_days")


def build_question_b(interval_path: Path) -> tuple[pd.DataFrame, dict, dict[str, pd.DataFrame]]:
    usecols = [
        "project_id", "project", "db", "usage_segment_id", "usage_start",
        "comparison_end", "stop_reason", "cve", "resolved_at", "cvss_severity",
        "has_known_vulnerability",
    ]
    raw = pd.read_csv(interval_path, usecols=usecols, low_memory=False)
    raw = raw[raw["has_known_vulnerability"].astype(str).str.lower().isin(["true", "1"])].copy()
    for column in ["usage_start", "comparison_end", "resolved_at"]:
        raw[column] = pd.to_datetime(raw[column], utc=True, errors="coerce")
    raw["severity"] = raw["cvss_severity"].astype("string").str.strip().str.upper()
    raw["severity_ordinal"] = raw["severity"].map(SEVERITY_ORDER)

    keys = ["project_id", "project", "db", "cve"]
    records = []
    for key, group in raw.groupby(keys, dropna=False, sort=False):
        resolved_values = group["resolved_at"].dropna().unique()
        severity_values = group["severity"].dropna().unique()
        resolved = pd.Timestamp(resolved_values[0]) if len(resolved_values) else pd.NaT
        severity = str(severity_values[0]) if len(severity_values) else None
        all_intervals = merge_intervals(list(zip(group["usage_start"], group["comparison_end"])))

        post_intervals = []
        if pd.notna(resolved):
            for start, end in all_intervals:
                clipped_start = max(start, resolved)
                if end > clipped_start:
                    post_intervals.append((clipped_start, end))
        total_post_days = sum((end - start).total_seconds() / 86400 for start, end in post_intervals)
        active_at_resolution = any(start <= resolved < end for start, end in all_intervals) if pd.notna(resolved) else False

        # For the response-time cohort, follow the continuous vulnerable-use spell
        # that contains resolved_at. Its terminal source tells whether cessation was
        # observed (version_changed) or only last observed (right censored).
        response_days = np.nan
        response_censored = False
        response_end = pd.NaT
        if active_at_resolution:
            containing = next((pair for pair in all_intervals if pair[0] <= resolved < pair[1]), None)
            if containing:
                response_end = containing[1]
                response_days = (response_end - resolved).total_seconds() / 86400
                terminal = group[group["comparison_end"] == response_end]
                response_censored = bool((terminal["stop_reason"] == "right_censored_no_later_version").any())

        q1 = group["usage_start"].min()
        q3 = group["comparison_end"].max()
        records.append({
            "project_id": key[0], "project": key[1], "db": key[2], "cve": key[3],
            "severity": severity, "severity_ordinal": SEVERITY_ORDER.get(severity),
            "resolved_at": resolved, "first_vulnerable_use": q1, "last_vulnerable_observation": q3,
            "post_resolution_exposure_days": total_post_days,
            "active_at_resolution": active_at_resolution,
            "response_time_days": response_days,
            "response_end": response_end,
            "right_censored": response_censored,
            "source_segments": int(group["usage_segment_id"].nunique()),
            "severity_conflict": int(len(severity_values) > 1),
            "resolution_date_conflict": int(len(resolved_values) > 1),
        })

    pairs = pd.DataFrame(records)
    complete = pairs.dropna(subset=["severity_ordinal", "post_resolution_exposure_days"]).copy()
    risk = pairs[pairs["active_at_resolution"]].dropna(subset=["severity_ordinal", "response_time_days"]).copy()
    events = risk[~risk["right_censored"]].copy()
    positive = complete[complete["post_resolution_exposure_days"] > 0].copy()
    vulnerability_level = (
        risk.groupby(["cve", "severity", "severity_ordinal"], as_index=False)
        .agg(
            median_response_time_days=("response_time_days", "median"),
            n_projects=("project_id", "nunique"),
            censor_fraction=("right_censored", "mean"),
        )
    )

    def test_bundle(frame: pd.DataFrame, value: str) -> dict:
        if frame.empty:
            return {"spearman": None, "kruskal": None}
        return {
            "spearman": spearman(frame["severity_ordinal"], frame[value]),
            "kruskal": kruskal(frame, value),
        }

    def outliers(frame: pd.DataFrame, value: str) -> pd.DataFrame:
        rows = []
        for severity, group in frame.groupby("severity", observed=True):
            q1, q3 = group[value].quantile([0.25, 0.75])
            iqr = q3 - q1
            cutoff = q3 + 1.5 * iqr
            rows.append({
                "severity": severity, "q1": q1, "q3": q3, "iqr": iqr,
                "upper_outlier_cutoff": cutoff,
                "n_above_cutoff": int((group[value] > cutoff).sum()),
                "maximum": group[value].max(),
            })
        return pd.DataFrame(rows).sort_values("severity")

    results = {
        "counts": {
            "source_segment_cve_rows": int(len(raw)),
            "project_library_vulnerability_pairs": int(len(pairs)),
            "distinct_projects": int(pairs["project_id"].nunique()),
            "distinct_vulnerabilities": int(pairs["cve"].nunique()),
            "missing_severity": int(pairs["severity_ordinal"].isna().sum()),
            "missing_resolution_date": int(pairs["resolved_at"].isna().sum()),
            "positive_post_resolution_exposure": int(len(positive)),
            "active_at_resolution": int(len(risk)),
            "right_censored_in_risk_cohort": int(risk["right_censored"].sum()),
            "observed_cessations_in_risk_cohort": int((~risk["right_censored"]).sum()),
            "projects_repeated": int((pairs.groupby("project_id").size() > 1).sum()),
            "vulnerabilities_repeated": int((pairs.groupby("cve").size() > 1).sum()),
            "max_pairs_per_project": int(pairs.groupby("project_id").size().max()),
            "max_pairs_per_vulnerability": int(pairs.groupby("cve").size().max()),
        },
        "all_pairs_observed_lower_bound_tests": test_bundle(complete, "post_resolution_exposure_days"),
        "positive_exposure_tests_selection_biased": test_bundle(positive, "post_resolution_exposure_days"),
        "at_risk_observed_lower_bound_tests": test_bundle(risk, "response_time_days"),
        "at_risk_complete_case_tests_censoring_biased": test_bundle(events, "response_time_days"),
        "vulnerability_level_median_sensitivity": test_bundle(
            vulnerability_level.rename(columns={"median_response_time_days": "response_time_days"}),
            "response_time_days",
        ),
    }
    tables = {
        "all_pairs_descriptives": describe(complete, "post_resolution_exposure_days"),
        "positive_exposure_descriptives": describe(positive, "post_resolution_exposure_days"),
        "at_risk_descriptives": describe(risk, "response_time_days"),
        "at_risk_censoring": (
            risk.groupby("severity", observed=True)
            .agg(n=("response_time_days", "size"), censored=("right_censored", "sum"))
            .reindex(SEVERITY_LABELS).reset_index()
        ),
        "all_pairs_outliers": outliers(complete, "post_resolution_exposure_days"),
        "at_risk_outliers": outliers(risk, "response_time_days"),
        "vulnerability_level_sensitivity": vulnerability_level,
        "vulnerability_level_descriptives": describe(
            vulnerability_level.rename(columns={"median_response_time_days": "response_time_days"}),
            "response_time_days",
        ),
        "all_pairs_zero_counts": (
            complete.groupby("severity", observed=True)["post_resolution_exposure_days"]
            .agg(n="size", zeros=lambda values: int((values == 0).sum()))
            .reindex(SEVERITY_LABELS).reset_index()
        ),
    }
    return pairs, results, tables


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="dbmining.sqlite")
    parser.add_argument("--intervals", default="rqs_data/rq4_vulnerable_usage_intervals.csv")
    parser.add_argument("--output-dir", default="statistical_audit_severity_20260903/results")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    vulnerabilities, result_a, desc_a, desc_a_positive = build_question_a(Path(args.db))
    pairs, result_b, tables_b = build_question_b(Path(args.intervals))

    vulnerabilities.to_csv(output / "question_a_vulnerability_level.csv", index=False)
    desc_a.to_csv(output / "question_a_descriptives.csv", index=False)
    desc_a_positive.to_csv(output / "question_a_positive_delay_descriptives.csv", index=False)
    pairs.to_csv(output / "question_b_project_library_vulnerability.csv", index=False)
    for name, table in tables_b.items():
        table.to_csv(output / f"question_b_{name}.csv", index=False)
    with (output / "audit_results.json").open("w", encoding="utf-8") as handle:
        json.dump({"question_a": result_a, "question_b": result_b}, handle, indent=2)

    print(json.dumps({"question_a": result_a, "question_b": result_b}, indent=2))


if __name__ == "__main__":
    main()
