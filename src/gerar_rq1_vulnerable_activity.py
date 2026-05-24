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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

DEFAULT_INPUT_DIR = "rqs_data"
DEFAULT_OUTPUT_DIR = "graficos_rq1"
DEFAULT_INPUT_FILE = "rq1_base_vulnerabilidades_cruzadas.csv"

PERIOD_ORDER = [
    "before_publication",
    "known_vulnerability",
    "after_resolution"
]

PERIOD_LABELS = {
    "before_publication": "Before disclosure",
    "known_vulnerability": "During exposure",
    "after_resolution": "After resolution"
}

PERIOD_COLORS = {
    "before_publication": "#aaedaa",
    "known_vulnerability": "#ffef93",
    "after_resolution": "#ff8d8d"
}

PERIOD_PRIORITY = {
    "before_publication": 0,
    "after_resolution": 1,
    "known_vulnerability": 2
}


def normalize_db_display_names(series):
    return series.replace({
        "MS SQL Server_Microsoft Azure SQL Database": "MSSQL/MicrosoftAzure"
    })


def ensure_output_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)


def save_plot(fig, output_dir, filename):
    filepath = Path(output_dir) / filename
    fig.tight_layout()
    fig.savefig(filepath, dpi=300, bbox_inches="tight")
    plt.close(fig)
    logging.info("Gráfico salvo em: %s", filepath)


def read_csv_required(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    return pd.read_csv(path)


def first_existing_column(df, candidates):
    for col in candidates:
        if col in df.columns:
            return col
    return None


def classify_period(row):
    date_commit = row["date_commit"]
    published_at = row["published_at"]
    resolved_at = row["resolved_at"]

    if pd.isna(date_commit) or pd.isna(published_at):
        return None

    if date_commit < published_at:
        return "before_publication"

    if pd.notna(resolved_at) and resolved_at >= published_at and date_commit >= resolved_at:
        return "after_resolution"

    return "known_vulnerability"


def add_period_column(df):
    df = df.copy()
    df["period"] = np.select(
        [
            df["date_commit"] < df["published_at"],
            (
                df["resolved_at"].notna() &
                (df["resolved_at"] >= df["published_at"]) &
                (df["date_commit"] >= df["resolved_at"])
            )
        ],
        [
            "before_publication",
            "after_resolution"
        ],
        default="known_vulnerability"
    )
    return df


def normalize_input(df):
    required_cols = [
        "db",
        "sha1",
        "date_commit",
        "commitsBetween",
        "published_at"
    ]

    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"O CSV precisa conter as colunas: {missing}")

    df = df.copy()

    if "project_id" not in df.columns and "project" not in df.columns and "project_name" not in df.columns:
        raise ValueError(
            "O CSV precisa conter project_id, project ou project_name para calcular exposição por projeto."
        )

    if "versionNumber" not in df.columns and "version" not in df.columns:
        raise ValueError(
            "O CSV precisa conter versionNumber ou version para calcular exposição por versão usada."
        )

    df["db"] = normalize_db_display_names(df["db"].astype(str).str.strip())
    df["date_commit"] = pd.to_datetime(df["date_commit"], errors="coerce", utc=True)
    df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce", utc=True)

    if "resolved_at" in df.columns:
        df["resolved_at"] = pd.to_datetime(df["resolved_at"], errors="coerce", utc=True)
    else:
        df["resolved_at"] = pd.NaT

    df["commitsBetween"] = pd.to_numeric(df["commitsBetween"], errors="coerce").fillna(0)
    df["sha1"] = df["sha1"].astype("string").str.strip()

    return df[
        df["db"].notna() &
        df["db"].ne("") &
        df["sha1"].notna() &
        df["sha1"].ne("") &
        df["date_commit"].notna() &
        df["published_at"].notna()
    ].copy()


def build_exposure_dedup_keys(df):
    keys = ["db", "sha1"]

    project_col = first_existing_column(df, ["project_id", "project", "project_name"])
    version_col = first_existing_column(df, ["versionNumber", "version"])
    vulnerability_col = first_existing_column(df, ["vulnerability_id", "reference", "cve"])

    keys.insert(0, project_col)
    keys.append(version_col)

    if vulnerability_col:
        keys.append(vulnerability_col)

    purl_col = first_existing_column(df, ["purl", "vuln_purl"])
    if purl_col:
        keys.append(purl_col)

    return keys


def consolidate_version_exposure(df):
    dedup_cols = build_exposure_dedup_keys(df)
    work_df = df.copy()
    work_df["period_priority"] = work_df["period"].map(PERIOD_PRIORITY)

    # Keep one observation per project/version/vulnerability/commit. This preserves
    # after-resolution activity for CVEs that already had a fix, even when the same
    # dependency version also has another CVE that is still during exposure.
    selected_idx = (
        work_df
        .sort_values(dedup_cols + ["period_priority", "date_commit"], kind="mergesort")
        .groupby(dedup_cols, dropna=False)["period_priority"]
        .idxmax()
    )

    exposure_df = (
        work_df.loc[selected_idx]
        .drop(columns=["period_priority"])
        .sort_values(dedup_cols + ["date_commit"], kind="mergesort")
        .reset_index(drop=True)
    )

    return exposure_df


def build_vulnerable_activity_summary(df):
    df = normalize_input(df)

    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    df = add_period_column(df)

    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    exposure_df = consolidate_version_exposure(df)

    summary = (
        exposure_df
        .groupby(["db", "period"], dropna=False)
        .agg(
            commits=("commitsBetween", "sum"),
            unique_commits=("sha1", "nunique"),
            exposure_rows=("sha1", "count")
        )
        .reset_index()
    )

    pivot = (
        summary
        .pivot(index="db", columns="period", values="commits")
        .fillna(0)
    )

    for period in PERIOD_ORDER:
        if period not in pivot.columns:
            pivot[period] = 0

    pivot = pivot[PERIOD_ORDER]
    pivot["total"] = pivot.sum(axis=1)
    pivot = pivot[pivot["total"] > 0]
    pivot = pivot.sort_values("total", ascending=True)

    return pivot, exposure_df


def build_diagnostic_summary(raw_df, exposure_df):
    raw = normalize_input(raw_df)
    if raw.empty:
        return pd.DataFrame()

    raw = add_period_column(raw)

    if raw.empty:
        return pd.DataFrame()

    group_cols = ["db", "period"]

    diagnostic = (
        raw.groupby(group_cols, dropna=False)
        .agg(
            raw_rows=("sha1", "count"),
            raw_files=("file", "nunique") if "file" in raw.columns else ("sha1", "count"),
            raw_unique_commits=("sha1", "nunique"),
            raw_commits_between_sum=("commitsBetween", "sum")
        )
        .reset_index()
    )

    corrected = (
        exposure_df.groupby(group_cols, dropna=False)
        .agg(
            dedup_rows=("sha1", "count"),
            dedup_unique_commits=("sha1", "nunique"),
            dedup_commits_between_sum=("commitsBetween", "sum")
        )
        .reset_index()
    )

    return diagnostic.merge(corrected, on=group_cols, how="left")


def plot_vulnerable_activity_by_dbms(pivot, output_dir):
    if pivot.empty:
        logging.warning("Nenhum dado disponível para gerar o gráfico.")
        return

    pivot = pivot.copy()

    absolute_total = pivot["total"].copy()

    plot_df = pivot[PERIOD_ORDER].copy()
    plot_df = plot_df.div(plot_df.sum(axis=1), axis=0).fillna(0)

    height = max(6, len(plot_df) * 0.45)
    fig, ax = plt.subplots(figsize=(12, height))

    y_positions = range(len(plot_df))
    left = pd.Series([0.0] * len(plot_df), index=plot_df.index)

    for period in PERIOD_ORDER:
        values = plot_df[period]

        ax.barh(
            y_positions,
            values,
            left=left,
            label=PERIOD_LABELS[period],
            color=PERIOD_COLORS[period],
            edgecolor="black",
            linewidth=0.4
        )

        left = left + values

    ax.set_yticks(y_positions)
    ax.set_yticklabels(plot_df.index)

    ax.set_xlim(0, 1)
    ax.set_xlabel("Proportion of commits")
    ax.set_ylabel("DBMS")
    ax.set_title("Activity by vulnerability period")

    ax.legend(
        loc="lower left",
        bbox_to_anchor=(0, -0.25),
        ncol=3,
        frameon=True
    )

    for i, db in enumerate(plot_df.index):
        ax.text(
            1.01,
            i,
            f"{int(absolute_total.loc[db])} commits",
            va="center",
            fontsize=8
        )

    fig.tight_layout(rect=[0, 0.12, 1, 1])

    save_plot(
        fig,
        output_dir,
        "rq1_vulnerable_activity_by_dbms.png"
    )


def export_summary(pivot, exposure_df, diagnostic_df, input_dir, export_dedup=False):
    output_path = Path(input_dir) / "rq1_vulnerable_activity_by_dbms_periodos.csv"
    diagnostic_path = Path(input_dir) / "rq1_vulnerable_activity_diagnostico.csv"

    pivot.reset_index().to_csv(output_path, index=False)
    diagnostic_df.to_csv(diagnostic_path, index=False)

    logging.info("CSV gerado: %s", output_path)
    logging.info("CSV gerado: %s", diagnostic_path)

    if export_dedup:
        exposure_path = Path(input_dir) / "rq1_vulnerable_activity_exposure_dedup.csv"
        exposure_df.to_csv(exposure_path, index=False)
        logging.info("CSV gerado: %s", exposure_path)


def main():
    parser = argparse.ArgumentParser(
        description="Gera o gráfico rq1_vulnerable_activity_by_dbms segmentado por período da vulnerabilidade."
    )

    parser.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        help="Diretório onde está o CSV de entrada."
    )

    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Diretório onde o gráfico será salvo."
    )

    parser.add_argument(
        "--input-file",
        default=DEFAULT_INPUT_FILE,
        help="Nome do CSV de entrada."
    )

    parser.add_argument(
        "--export-dedup",
        action="store_true",
        help="Exporta a base deduplicada completa usada no cálculo."
    )

    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    input_path = input_dir / args.input_file

    ensure_output_dir(output_dir)

    df = read_csv_required(input_path)
    pivot, exposure_df = build_vulnerable_activity_summary(df)
    diagnostic_df = build_diagnostic_summary(df, exposure_df)

    export_summary(pivot, exposure_df, diagnostic_df, input_dir, args.export_dedup)
    plot_vulnerable_activity_by_dbms(pivot, output_dir)

    logging.info("Geração concluída.")


if __name__ == "__main__":
    main()
