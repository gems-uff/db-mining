#!/usr/bin/env python3
import argparse
import logging
import os
import tempfile
from pathlib import Path

cache_root = Path(tempfile.gettempdir()) / "db-mining-matplotlib-cache"
os.environ.setdefault("MPLCONFIGDIR", str(cache_root / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(cache_root / "xdg"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from gerar_rq4_vulnerable_usage_intervals import (
    add_overlap_metrics,
    build_usage_segments,
    build_vulnerability_catalog,
    elapsed_days,
    prepare_base,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

PERIOD_ORDER = ["pre_disclosure", "post_disclosure", "post_resolution"]
PERIOD_PRIORITY = {
    "pre_disclosure": 1,
    "post_disclosure": 2,
    "post_resolution": 3,
}
PERIOD_LABELS = {
    "pre_disclosure": "Pre-disclosure",
    "post_disclosure": "Post-disclosure (pre-resolution)",
    "post_resolution": "Post-resolution",
}
PERIOD_COLORS = {
    "pre_disclosure": "#aaedaa",
    "post_disclosure": "#ffef93",
    "post_resolution": "#ff8d8d",
}
VULNERABLE_ACTIVITY_LABEL = (
    "Commits = number of commits performed while using vulnerable releases"
)


def phase_at(timestamp, published_at, resolved_at):
    if pd.notna(resolved_at) and timestamp >= resolved_at:
        return "post_resolution"
    if pd.notna(published_at) and timestamp >= published_at:
        return "post_disclosure"
    return "pre_disclosure"


def timestamps_inside(group, start, end):
    points = {start, end}
    for column in ["published_at", "resolved_at"]:
        for value in group[column].dropna():
            if start < value < end:
                points.add(value)
    return sorted(points)


def build_segment_phase_intervals(overlap_df):
    vulnerable = overlap_df[overlap_df["has_known_vulnerability"]].copy()
    records = []

    for segment_id, group in vulnerable.groupby("usage_segment_id", sort=False):
        first = group.iloc[0]
        start = first["usage_start"]
        end = first["comparison_end"]
        if pd.isna(start) or pd.isna(end) or end <= start:
            continue

        boundaries = timestamps_inside(group, start, end)
        for interval_start, interval_end in zip(boundaries, boundaries[1:]):
            phases = [
                phase_at(interval_start, row.published_at, row.resolved_at)
                for row in group.itertuples(index=False)
            ]
            phase = max(phases, key=PERIOD_PRIORITY.get)
            records.append({
                "project_id": first["project_id"],
                "project": first["project"],
                "db": first["db"],
                "usage_segment_id": segment_id,
                "files": first["files"],
                "n_files": first["n_files"],
                "version": first["version"],
                "interval_start": interval_start,
                "interval_end": interval_end,
                "days": elapsed_days(interval_start, interval_end),
                "period": phase,
                "cves": "; ".join(sorted(group["cve"].dropna().unique())),
                "stop_reason": first["stop_reason"],
            })

    return pd.DataFrame(records)


def consolidate_project_db_intervals(segment_intervals):
    records = []
    group_cols = ["project_id", "project", "db"]

    for keys, group in segment_intervals.groupby(group_cols, sort=False):
        boundaries = sorted(
            set(group["interval_start"]).union(set(group["interval_end"]))
        )
        for interval_start, interval_end in zip(boundaries, boundaries[1:]):
            active = group[
                (group["interval_start"] < interval_end)
                & (group["interval_end"] > interval_start)
            ]
            if active.empty:
                continue

            phase = max(active["period"], key=PERIOD_PRIORITY.get)
            selected = active[active["period"] == phase]
            records.append({
                "project_id": keys[0],
                "project": keys[1],
                "db": keys[2],
                "interval_start": interval_start,
                "interval_end": interval_end,
                "days": elapsed_days(interval_start, interval_end),
                "period": phase,
                "active_segments": active["usage_segment_id"].nunique(),
                "active_files": active["n_files"].sum(),
                "active_versions": active["version"].nunique(),
                "cves": "; ".join(sorted(selected["cves"].unique())),
            })

    return pd.DataFrame(records)


def build_commit_activity(base, project_intervals):
    observations = (
        base.groupby(
            [
                "project_id",
                "project_name",
                "db_name",
                "version_id",
                "sha1",
                "date_commit",
            ],
            dropna=False,
        )
        .agg(activity_commits=("commitsBetween", "max"))
        .reset_index()
        .rename(columns={"project_name": "project", "db_name": "db"})
    )

    records = []
    for keys, intervals in project_intervals.groupby(
        ["project_id", "project", "db"], sort=False
    ):
        commits = observations[
            (observations["project_id"] == keys[0])
            & (observations["db"] == keys[2])
        ].copy()
        if commits.empty:
            continue

        intervals = intervals.sort_values("interval_start").reset_index(drop=True)
        starts = intervals["interval_start"].to_numpy(dtype="datetime64[ns]")
        ends = intervals["interval_end"].to_numpy(dtype="datetime64[ns]")
        dates = commits["date_commit"].to_numpy(dtype="datetime64[ns]")
        positions = np.searchsorted(starts, dates, side="right") - 1
        valid_position = positions >= 0
        valid = valid_position.copy()
        valid[valid_position] &= dates[valid_position] <= ends[positions[valid_position]]

        commits = commits.loc[valid].copy()
        positions = positions[valid]
        commits["period"] = intervals.iloc[positions]["period"].to_numpy()
        commits["interval_start"] = intervals.iloc[positions][
            "interval_start"
        ].to_numpy()
        commits["interval_end"] = intervals.iloc[positions]["interval_end"].to_numpy()
        commits["cves"] = intervals.iloc[positions]["cves"].to_numpy()
        records.append(commits)

    return pd.concat(records, ignore_index=True) if records else pd.DataFrame()


def build_summary(commit_activity):
    summary = (
        commit_activity.groupby(["db", "period"], dropna=False)
        .agg(
            commits=("activity_commits", "sum"),
            projects=("project_id", "nunique"),
            observed_commits=("sha1", "nunique"),
        )
        .reset_index()
    )
    pivot = summary.pivot(index="db", columns="period", values="commits").fillna(0)
    for period in PERIOD_ORDER:
        if period not in pivot.columns:
            pivot[period] = 0.0
    pivot = pivot[PERIOD_ORDER]
    pivot["total"] = pivot.sum(axis=1)
    return pivot[pivot["total"] > 0].sort_values("total")


def plot_summary(pivot, output_dir):
    plot_df = pivot[PERIOD_ORDER].div(pivot["total"], axis=0).fillna(0)
    fig, ax = plt.subplots(figsize=(12, max(6, len(plot_df) * 0.45)))
    left = pd.Series(0.0, index=plot_df.index)
    display_names = {
        "MS SQL Server_Microsoft Azure SQL Database": "MSSQL/MicrosoftAzure",
    }

    for period in PERIOD_ORDER:
        ax.barh(
            plot_df.index,
            plot_df[period],
            left=left,
            label=PERIOD_LABELS[period],
            color=PERIOD_COLORS[period],
            edgecolor="black",
            linewidth=0.4,
        )
        left += plot_df[period]

    ax.set_xlim(0, 1)
    ax.set_xlabel("Proportion of commits during vulnerable-release use")
    ax.set_yticks(range(len(plot_df.index)))
    ax.set_yticklabels([display_names.get(db, db) for db in plot_df.index])
    ax.set_ylabel("DBMS")
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, -0.25),
        ncol=3,
        frameon=True,
        title=VULNERABLE_ACTIVITY_LABEL,
    )

    for index, db in enumerate(plot_df.index):
        ax.text(
            1.01,
            index,
            f"Commits: {pivot.loc[db, 'total']:,.0f}",
            va="center",
            fontsize=8,
        )

    fig.tight_layout(rect=[0, 0.14, 1, 1])
    output = Path(output_dir) / "rq4_vulnerable_activity_periods_by_dbms.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=300, bbox_inches="tight")
    pdf_output = output.with_suffix(".pdf")
    fig.savefig(pdf_output, bbox_inches="tight")
    plt.close(fig)
    logging.info("Gráfico salvo em: %s", pdf_output)
    logging.info("Gráfico salvo em: %s", output)


def export_data(
    overlap,
    segment_intervals,
    project_intervals,
    commit_activity,
    pivot,
    input_dir,
):
    input_dir = Path(input_dir)
    overlap.to_csv(input_dir / "rq4_vulnerable_usage_intervals.csv", index=False)
    segment_intervals.to_csv(
        input_dir / "rq4_vulnerable_activity_segment_intervals.csv", index=False
    )
    project_intervals.to_csv(
        input_dir / "rq4_vulnerable_activity_project_db_intervals.csv", index=False
    )
    commit_activity.to_csv(
        input_dir / "rq4_vulnerable_activity_by_commit.csv", index=False
    )
    pivot.reset_index().to_csv(
        input_dir / "rq4_vulnerable_activity_periods_by_dbms.csv", index=False
    )

    project_summary = (
        commit_activity.pivot_table(
            index=["project_id", "project", "db"],
            columns="period",
            values="activity_commits",
            aggfunc="sum",
            fill_value=0,
        )
        .reset_index()
    )
    for period in PERIOD_ORDER:
        if period not in project_summary.columns:
            project_summary[period] = 0.0
    project_summary["total_activity_commits"] = project_summary[
        PERIOD_ORDER
    ].sum(axis=1)
    project_summary.to_csv(
        input_dir / "rq4_vulnerable_activity_periods_by_project_dbms.csv", index=False
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Gera rq4_vulnerable_activity_periods_by_dbms usando intervalos reais de "
            "uso das versões e sua sobreposição com divulgação/correção."
        )
    )
    parser.add_argument("--input-dir", default="rqs_data")
    parser.add_argument("--output-dir", default="graficos_rq4")
    parser.add_argument("--input-file", default="vulnerability_analysis_base.csv")
    return parser.parse_args()


def main():
    args = parse_args()
    input_dir = Path(args.input_dir)
    base = prepare_base(input_dir / args.input_file)
    segments = build_usage_segments(base)
    catalog = build_vulnerability_catalog(base)
    overlap = add_overlap_metrics(segments, catalog)
    segment_intervals = build_segment_phase_intervals(overlap)
    project_intervals = consolidate_project_db_intervals(segment_intervals)
    commit_activity = build_commit_activity(base, project_intervals)
    pivot = build_summary(commit_activity)

    export_data(
        overlap,
        segment_intervals,
        project_intervals,
        commit_activity,
        pivot,
        input_dir,
    )
    plot_summary(pivot, args.output_dir)

    logging.info(
        "Segmentos vulneráveis: %d | commits observados classificados: %d | DBMS: %d",
        overlap.loc[overlap["has_known_vulnerability"], "usage_segment_id"].nunique(),
        len(commit_activity),
        len(pivot),
    )


if __name__ == "__main__":
    main()
