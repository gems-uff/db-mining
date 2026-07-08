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
    format="%(asctime)s | %(levelname)s | %(message)s"
)

DEFAULT_INPUT_FILE = "rqs_data/rq3_dbms_project_exposure_summary.csv"
DEFAULT_OUTPUT_DIR = "graficos_rq3"


def normalize_db_display_names(series):
    return series.replace({
        "MS SQL Server_Microsoft Azure SQL Database": "MSSQL/MicrosoftAzure"
    })


def prepare_numeric(df, columns):
    df = df.copy()

    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def ensure_output_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)


def save_plot(fig, output_dir, filename):
    filepath = Path(output_dir) / filename

    fig.tight_layout()
    fig.savefig(filepath, dpi=300, bbox_inches="tight")
    if filepath.suffix.lower() == ".png":
        pdf_path = filepath.with_suffix(".pdf")
        fig.savefig(pdf_path, bbox_inches="tight")
        logging.info("Gráfico salvo em: %s", pdf_path)

    plt.close(fig)

    logging.info("Gráfico salvo em: %s", filepath)


def plot_dbms_usage_vs_exposure(rq1_dbms, output_dir):
    if rq1_dbms.empty:
        logging.warning("rq3_dbms_project_exposure_summary.csv está vazio.")
        return

    rq1_dbms = prepare_numeric(
        rq1_dbms,
        [
            "projects_using_db",
            "projects_affected",
            "exposure_project_percent"
        ]
    )

    required_cols = [
        "db",
        "projects_using_db",
        "projects_affected",
        "exposure_project_percent"
    ]

    missing = [col for col in required_cols if col not in rq1_dbms.columns]

    if missing:
        raise ValueError(
            f"rq3_dbms_project_exposure_summary.csv deve conter as colunas: {missing}"
        )

    filtered = rq1_dbms[
        rq1_dbms["projects_using_db"] > 0
    ].copy()

    filtered["db"] = normalize_db_display_names(filtered["db"])

    filtered = filtered.sort_values(
        ["projects_affected", "projects_using_db", "db"],
        ascending=[True, True, False]
    )
    filtered["projects_not_affected"] = (
        filtered["projects_using_db"] - filtered["projects_affected"]
    ).clip(lower=0)

    height = max(6, len(filtered) * 0.45)

    fig = plt.figure(figsize=(10, height))

    y_positions = range(len(filtered))

    PROJECT_COLORS = {
        "projects_not_affected": "#7fbf7f",
        "projects_affected": "#ff8d8d"
    }

    plt.barh(
        y_positions,
        filtered["projects_not_affected"],
        label="Not affected projects",
        color=PROJECT_COLORS["projects_not_affected"],
        edgecolor="black"
    )

    plt.barh(
        y_positions,
        filtered["projects_affected"],
        left=filtered["projects_not_affected"],
        label="Affected projects",
        color=PROJECT_COLORS["projects_affected"],
        edgecolor="black"
    )

    plt.yticks(y_positions, filtered["db"])

    plt.xlabel("Number of projects")
    plt.ylabel("DBMS")

    plt.legend()

    for i, row in enumerate(filtered.itertuples()):
        label = (
            f"{int(row.projects_affected)}/"
            f"{int(row.projects_using_db)} projects, "
            f"{row.exposure_project_percent:.1f}%"
        )

        plt.text(
            row.projects_using_db + 0.2,
            i,
            label,
            va="center",
            fontsize=8
        )

    save_plot(
        fig,
        output_dir,
        "rq3_project_exposure_vs_dbms_usage.png"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Gera apenas o gráfico rq3_project_exposure_vs_dbms_usage."
    )

    parser.add_argument(
        "--input-file",
        default=DEFAULT_INPUT_FILE,
        help="Arquivo rq3_dbms_project_exposure_summary.csv"
    )

    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Diretório de saída"
    )

    args = parser.parse_args()

    input_file = Path(args.input_file)

    if not input_file.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {input_file}"
        )

    ensure_output_dir(args.output_dir)

    rq1_dbms = pd.read_csv(input_file)

    plot_dbms_usage_vs_exposure(
        rq1_dbms,
        args.output_dir
    )

    logging.info("Gráfico gerado com sucesso.")


if __name__ == "__main__":
    main()
