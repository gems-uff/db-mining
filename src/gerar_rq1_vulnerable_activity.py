#!/usr/bin/env python3
import argparse
import logging
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

DEFAULT_INPUT_DIR = "rqs_data"
DEFAULT_OUTPUT_DIR = "graficos_rq1"
DEFAULT_INPUT_FILE = "rq1_base_vulnerabilidades_cruzadas.csv"


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


def classify_period(row):
    date_commit = row["date_commit"]
    published_at = row["published_at"]
    resolved_at = row["resolved_at"]

    if pd.isna(published_at):
        return None

    if pd.notna(resolved_at) and date_commit >= resolved_at:
        return "after_resolution"

    if date_commit >= published_at:
        return "known_vulnerability"

    return "before_publication"


def build_vulnerable_activity_summary(df):
    required_cols = [
        "db",
        "sha1",
        "date_commit",
        "commitsBetween",
        "published_at",
        "resolved_at"
    ]

    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"O CSV precisa conter as colunas: {missing}")

    df = df.copy()

    df["db"] = normalize_db_display_names(df["db"].astype(str).str.strip())
    df["date_commit"] = pd.to_datetime(df["date_commit"], errors="coerce", utc=True)
    df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce", utc=True)
    df["resolved_at"] = pd.to_datetime(df["resolved_at"], errors="coerce", utc=True)
    df["commitsBetween"] = pd.to_numeric(df["commitsBetween"], errors="coerce").fillna(0)

    df = df[
        df["db"].notna() &
        df["db"].ne("") &
        df["sha1"].notna() &
        df["date_commit"].notna() &
        df["published_at"].notna()
    ].copy()

    if df.empty:
        return pd.DataFrame()

    df["period"] = df.apply(classify_period, axis=1)
    df = df[df["period"].notna()].copy()

    dedup_cols = ["db", "sha1", "period"]

    if "file" in df.columns:
        dedup_cols.insert(2, "file")

    if "cve" in df.columns:
        dedup_cols.append("cve")
    elif "reference" in df.columns:
        dedup_cols.append("reference")
    elif "vulnerability_id" in df.columns:
        dedup_cols.append("vulnerability_id")

    df = df.drop_duplicates(subset=dedup_cols)

    summary = (
        df
        .groupby(["db", "period"], dropna=False)
        .agg(commits=("commitsBetween", "sum"))
        .reset_index()
    )

    period_order = [
        "before_publication",
        "known_vulnerability",
        "after_resolution"
    ]

    pivot = (
        summary
        .pivot(index="db", columns="period", values="commits")
        .fillna(0)
    )

    for period in period_order:
        if period not in pivot.columns:
            pivot[period] = 0

    pivot = pivot[period_order]
    pivot["total"] = pivot.sum(axis=1)
    pivot = pivot[pivot["total"] > 0]
    pivot = pivot.sort_values("total", ascending=True)

    return pivot


def plot_vulnerable_activity_by_dbms(pivot, output_dir):
    if pivot.empty:
        logging.warning("Nenhum dado disponível para gerar o gráfico.")
        return

    period_order = [
        "before_publication",
        "known_vulnerability",
        "after_resolution"
    ]

    labels = {
        "before_publication": "Antes da publicação",
        "known_vulnerability": "Vulnerabilidade conhecida",
        "after_resolution": "Após resolução"
    }

    colors = {
        "before_publication": "green",
        "known_vulnerability": "yellow",
        "after_resolution": "red"
    }

    height = max(6, len(pivot) * 0.45)
    fig, ax = plt.subplots(figsize=(12, height))

    y_positions = range(len(pivot))
    left = pd.Series([0] * len(pivot), index=pivot.index)

    for period in period_order:
        values = pivot[period]

        ax.barh(
            y_positions,
            values,
            left=left,
            label=labels[period],
            color=colors[period],
            edgecolor="black",
            linewidth=0.4
        )

        left = left + values

    ax.set_yticks(y_positions)
    ax.set_yticklabels(pivot.index)

    ax.set_xlabel("Quantidade de commits entre slices")
    ax.set_ylabel("DBMS")
    ax.set_title("Atividade entre slices por período da vulnerabilidade")
    ax.legend(
    loc="lower left",
    bbox_to_anchor=(0, -0.25),
    ncol=3,
    frameon=True
)

    max_value = pivot["total"].max()
    ax.set_xlim(0, max_value * 1.15)

    for i, total in enumerate(pivot["total"]):
        ax.text(
            total + max_value * 0.01,
            i,
            str(int(total)),
            va="center",
            fontsize=8
        )

    save_plot(
        fig,
        output_dir,
        "rq1_vulnerable_activity_by_dbms.png"
    )


def export_summary(pivot, input_dir):
    output_path = Path(input_dir) / "rq1_vulnerable_activity_by_dbms_periodos.csv"
    pivot.reset_index().to_csv(output_path, index=False)
    logging.info("CSV gerado: %s", output_path)


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

    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    input_path = input_dir / args.input_file

    ensure_output_dir(output_dir)

    df = read_csv_required(input_path)
    pivot = build_vulnerable_activity_summary(df)

    export_summary(pivot, input_dir)
    plot_vulnerable_activity_by_dbms(pivot, output_dir)

    logging.info("Geração concluída.")


if __name__ == "__main__":
    main()