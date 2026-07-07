#!/usr/bin/env python3
import argparse
import logging
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

DEFAULT_DB_PATH = "dbmining.sqlite"
DEFAULT_OUTPUT_DIR = "graficos_rq2"
DEFAULT_DATA_DIR = "rqs_data"


def normalize_db_display_names(series):
    return series.replace({
        "MS SQL Server_Microsoft Azure SQL Database": "MSSQL/MicrosoftAzure"
    })


def ensure_dir(path):
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


def read_resolution_data(db_path):
    if not Path(db_path).exists():
        raise FileNotFoundError(f"Banco não encontrado: {db_path}")

    query = """
        SELECT DISTINCT
            l.name AS db,
            v.reference,
            v.version,
            v.published_at,
            v.resolved_at
        FROM vulnerability v
        JOIN label l
          ON l.id = v.label_id
        WHERE l.name IS NOT NULL
          AND TRIM(l.name) <> ''
          AND v.reference IS NOT NULL
          AND TRIM(v.reference) <> ''
          AND v.published_at IS NOT NULL
          AND TRIM(v.published_at) <> ''
          AND v.resolved_at IS NOT NULL
          AND TRIM(v.resolved_at) <> ''
    """

    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

    return df


def prepare_resolution_data(df):
    required_cols = ["db", "reference", "published_at", "resolved_at"]

    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Dados precisam conter as colunas: {missing}")

    df = df.copy()

    df["db"] = normalize_db_display_names(df["db"].astype(str).str.strip())
    df["reference"] = df["reference"].astype(str).str.strip()

    df = df[
        df["db"].notna() &
        df["db"].ne("") &
        df["reference"].notna() &
        df["reference"].ne("") &
        df["reference"].str.lower().ne("nan")
    ].copy()

    df["published_at"] = pd.to_datetime(
        df["published_at"],
        errors="coerce",
        utc=True
    )

    df["resolved_at"] = pd.to_datetime(
        df["resolved_at"],
        errors="coerce",
        utc=True
    )

    df = df[
        df["published_at"].notna() &
        df["resolved_at"].notna()
    ].copy()

    df["resolution_time_days"] = (
        df["resolved_at"] - df["published_at"]
    ).dt.total_seconds() / 86400

    df = df[
        df["resolution_time_days"].notna() &
        (df["resolution_time_days"] > 0)
    ].copy()

    df = df.drop_duplicates(
        subset=["db", "reference", "version", "published_at", "resolved_at"]
    )

    logging.info("Registros válidos para o boxplot: %s", len(df))

    if not df.empty:
        logging.info(
            "Resumo do tempo de resolução:\n%s",
            df["resolution_time_days"].describe()
        )

    return df


def compute_iqr(series):
    return series.quantile(0.75) - series.quantile(0.25)


def plot_resolution_time_boxplot(df, output_dir):
    if df.empty:
        logging.warning("Nenhum dado válido disponível para gerar o boxplot.")
        return

    db_order = (
        df.groupby("db")["resolution_time_days"]
        .apply(compute_iqr)
        .sort_values(ascending=False)
        .index
        .tolist()
    )

    grouped_values = []
    labels = []

    for db in db_order:
        values = df.loc[
            df["db"] == db,
            "resolution_time_days"
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
    ax.set_ylabel("Tempo de resolução da vulnerabilidade, dias")
    ax.set_title("RQ2, distribuição do tempo de resolução das vulnerabilidades por DBMS")
    ax.grid(True, axis="y", alpha=0.3)

    plt.xticks(rotation=45, ha="right")

    fig.tight_layout()

    save_plot(
        fig,
        output_dir,
        "rq2_boxplot_tempo_resolucao_vulnerabilidades_por_dbms.png"
    )


def export_resolution_data(df, data_dir):
    output_path = Path(data_dir) / "rq2_tempo_resolucao_vulnerabilidades_por_dbms.csv"
    df.to_csv(output_path, index=False)
    logging.info("CSV gerado: %s", output_path)


def main():
    parser = argparse.ArgumentParser(
        description="Gera boxplot do tempo de resolução das vulnerabilidades por DBMS."
    )

    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR)

    args = parser.parse_args()

    ensure_dir(args.output_dir)
    ensure_dir(args.data_dir)

    df = read_resolution_data(args.db_path)
    df = prepare_resolution_data(df)

    export_resolution_data(df, args.data_dir)
    plot_resolution_time_boxplot(df, args.output_dir)

    logging.info("Geração concluída.")


if __name__ == "__main__":
    main()
