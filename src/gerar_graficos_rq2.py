#!/usr/bin/env python3
import argparse
import logging
import math
import os
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", tempfile.gettempdir())

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from rq_pipeline_common import build_rq2_exposures, build_rq2_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

DEFAULT_INPUT_DIR = "rqs_data"
DEFAULT_OUTPUT_DIR = "graficos_rq2"
DEFAULT_INPUT_FILE = "rq2_exposicoes.csv"
MIN_PROJECTS_FOR_CDF = 4
CDF_XLIM_DAYS = (0, 3800)


def normalize_db_display_names(df):
    df = df.copy()
    if "db" in df.columns:
        df["db"] = df["db"].replace({
            "MS SQL Server_Microsoft Azure SQL Database": "MSSQL/MicrosoftAzure"
        })
    return df


def read_csv_required(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    return pd.read_csv(path)


def ensure_rq2_input_exists(input_path, input_dir):
    if input_path.exists():
        return

    rq1_path = Path(input_dir) / "rq1_associacoes.csv"
    logging.info(
        "%s não encontrado. Gerando a partir de %s.",
        input_path,
        rq1_path,
    )

    rq1_assoc = read_csv_required(rq1_path)
    rq2_df = build_rq2_exposures(rq1_assoc)
    rq2_summary = build_rq2_summary(rq2_df)

    rq2_df.to_csv(input_path, index=False)
    rq2_summary.to_csv(Path(input_dir) / "rq2_resumo.csv", index=False)

    logging.info("CSV gerado: %s", input_path)
    logging.info("CSV gerado: %s", Path(input_dir) / "rq2_resumo.csv")


def ensure_output_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)


def save_plot(fig, output_dir, filename):
    filepath = Path(output_dir) / filename
    fig.savefig(filepath, dpi=300, bbox_inches="tight")
    if filepath.suffix.lower() == ".png":
        pdf_path = filepath.with_suffix(".pdf")
        fig.savefig(pdf_path, bbox_inches="tight")
        logging.info("Gráfico salvo em: %s", pdf_path)
    plt.close(fig)
    logging.info("Gráfico salvo em: %s", filepath)


def prepare_data(df):
    required_cols = [
        "db",
        "project_id",
        "total_exposure_days",
        "post_disclosure_days",
        "post_resolution_days",
    ]
    missing = [col for col in required_cols if col not in df.columns]

    if missing:
        raise ValueError(f"O CSV precisa conter as colunas: {missing}")

    df = normalize_db_display_names(df)

    df["db"] = df["db"].astype(str).str.strip()
    df["project_id"] = df["project_id"].astype(str).str.strip()
    df["total_exposure_days"] = pd.to_numeric(
        df["total_exposure_days"],
        errors="coerce"
    )
    df["post_disclosure_days"] = pd.to_numeric(
        df["post_disclosure_days"],
        errors="coerce"
    ).fillna(0)
    df["post_resolution_days"] = pd.to_numeric(
        df["post_resolution_days"],
        errors="coerce"
    ).fillna(0)

    df = df.dropna(subset=["db", "project_id", "total_exposure_days"])

    df = df[
        df["db"].ne("") &
        df["project_id"].ne("") &
        (df["total_exposure_days"] >= 0) &
        (df["post_disclosure_days"] >= 0) &
        (df["post_resolution_days"] >= 0)
    ].copy()

    return df


def aggregate_by_project(df):
    return (
        df
        .groupby(["db", "project_id"], as_index=False)
        .agg(
            total_exposure_days=("total_exposure_days", "max"),
            post_disclosure_days=("post_disclosure_days", "max"),
            post_resolution_days=("post_resolution_days", "max"),
        )
    )


def export_project_level_data(df_project, input_dir):
    output_path = Path(input_dir) / "rq2_exposicao_total_por_dbms_por_projeto.csv"
    df_project.to_csv(output_path, index=False)
    logging.info("CSV agregado por projeto salvo em: %s", output_path)

    post_output_path = Path(input_dir) / "rq2_exposicao_pos_divulgacao_por_dbms_por_projeto.csv"
    df_project[["db", "project_id", "post_disclosure_days"]].to_csv(
        post_output_path,
        index=False,
    )
    logging.info("CSV pós-divulgação agregado por projeto salvo em: %s", post_output_path)

    post_resolution_output_path = (
        Path(input_dir) / "rq2_exposicao_pos_resolucao_por_dbms_por_projeto.csv"
    )
    df_project[["db", "project_id", "post_resolution_days"]].to_csv(
        post_resolution_output_path,
        index=False,
    )
    logging.info(
        "CSV pós-resolução agregado por projeto salvo em: %s",
        post_resolution_output_path,
    )


def plot_cdf_small_multiples_by_project(
    df_project,
    output_dir,
    min_projects=MIN_PROJECTS_FOR_CDF,
    value_col="total_exposure_days",
    xlabel="Tempo total de exposição por projeto, dias",
    filename="rq2_cdf_exposicao_total_por_dbms_por_projeto.png",
    n_cols=4,
    xlim=None,
):
    if df_project.empty:
        logging.warning("Nenhum dado disponível para gerar o CDF.")
        return

    project_counts = df_project.groupby("db")["project_id"].nunique()
    excluded_dbs = project_counts[project_counts < min_projects].index.tolist()

    if excluded_dbs:
        logging.info(
            "DBMS removidos do CDF por terem menos de %d projetos: %s",
            min_projects,
            ", ".join(excluded_dbs),
        )

    df_plot = df_project[
        df_project["db"].isin(project_counts[project_counts >= min_projects].index)
    ].copy()

    if df_plot.empty:
        logging.warning("Nenhum DBMS com pelo menos %d projetos para gerar o CDF.", min_projects)
        return

    db_order = (
        df_plot.groupby("db")[value_col]
        .median()
        .sort_values(ascending=False)
        .index
        .tolist()
    )

    n_dbs = len(db_order)
    n_rows = math.ceil(n_dbs / n_cols)

    fig, axes = plt.subplots(
        n_rows,
        n_cols,
        figsize=(4.2 * n_cols, 3.2 * n_rows),
        sharey=True
    )

    axes = np.array(axes).reshape(-1)

    for ax, db in zip(axes, db_order):
        values = (
            df_plot.loc[df_plot["db"] == db, value_col]
            .dropna()
            .sort_values()
        )

        if values.empty:
            ax.axis("off")
            continue

        y = np.arange(1, len(values) + 1) / len(values)

        ax.plot(values.values, y, linewidth=2, color="#4c78a8")

        median_value = values.median()

        ax.axvline(
            median_value,
            linestyle=":",
            linewidth=1,
            color="gray"
        )

        ax.set_title(f"{db} (n={len(values)} projetos)", fontsize=10)
        ax.set_ylim(0, 1.02)
        if xlim is not None:
            ax.set_xlim(*xlim)
        ax.grid(True, alpha=0.25)

        ax.text(
            0.03,
            0.08,
            f"mediana: {median_value:.0f} dias",
            transform=ax.transAxes,
            fontsize=8
        )

    for ax in axes[n_dbs:]:
        ax.axis("off")

    fig.supxlabel(xlabel)
    fig.supylabel("Proporção acumulada de projetos")

    fig.tight_layout(rect=[0, 0.03, 1, 1])

    save_plot(
        fig,
        output_dir,
        filename
    )

def compute_iqr(series):
    return series.quantile(0.75) - series.quantile(0.25)


def plot_boxplot_by_project(df_project, output_dir):
    if df_project.empty:
        logging.warning("Nenhum dado disponível para gerar o boxplot.")
        return

    
    db_order = (
    df_project.groupby("db")["total_exposure_days"]
    .apply(compute_iqr)
    .sort_values(ascending=False)
    .index
    .tolist()
)

    grouped_values = []
    labels = []

    for db in db_order:
        values = df_project.loc[
            df_project["db"] == db,
            "total_exposure_days"
        ].dropna().values

        if len(values) > 0:
            grouped_values.append(values)
            labels.append(db)

    if not grouped_values:
        logging.warning("Nenhum grupo válido para gerar o boxplot.")
        return

    width = max(12, len(labels) * 0.75)
    fig, ax = plt.subplots(figsize=(width, 7))

    box = ax.boxplot(
        grouped_values,
        labels=labels,
        patch_artist=True,
        showfliers=False
    )

    for patch in box["boxes"]:
        patch.set_facecolor("#9ecae1")
        patch.set_alpha(0.85)

    for median in box["medians"]:
        median.set_color("black")
        median.set_linewidth(1.5)

    ax.set_xlabel("DBMS")
    ax.set_ylabel("Tempo total de exposição por projeto, dias")
    ax.set_title("RQ2, distribuição do tempo total de exposição por projeto e DBMS")
    ax.grid(True, axis="y", alpha=0.3)

    plt.xticks(rotation=45, ha="right")

    fig.tight_layout()

    save_plot(
        fig,
        output_dir,
        "rq2_boxplot_exposicao_total_por_dbms_por_projeto.png"
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Gera CDF por DBMS e boxplot do tempo total de exposição, "
            "com cada ponto representando um projeto."
        )
    )

    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--input-file", default=DEFAULT_INPUT_FILE)

    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    input_path = input_dir / args.input_file

    ensure_output_dir(output_dir)
    ensure_rq2_input_exists(input_path, input_dir)

    df = read_csv_required(input_path)
    df = prepare_data(df)
    df_project = aggregate_by_project(df)

    export_project_level_data(df_project, input_dir)
    plot_cdf_small_multiples_by_project(
        df_project,
        output_dir,
        value_col="post_disclosure_days",
        xlabel="Tempo de exposição pós-divulgação por projeto, dias",
        filename="rq5_cdf_exposicao_pos_divulgacao_por_dbms_por_projeto.png",
        n_cols=3,
        xlim=CDF_XLIM_DAYS,
    )
    plot_cdf_small_multiples_by_project(
        df_project,
        output_dir,
        value_col="post_resolution_days",
        xlabel="Tempo de exposição pós-resolução por projeto, dias",
        filename="rq5_cdf_exposicao_pos_resolucao_por_dbms_por_projeto.png",
        n_cols=3,
        xlim=CDF_XLIM_DAYS,
    )

    logging.info("Geração concluída.")


if __name__ == "__main__":
    main()
