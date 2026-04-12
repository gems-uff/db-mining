#!/usr/bin/env python3
import argparse
import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

DEFAULT_INPUT_DIR = "rqs_data"
DEFAULT_OUTPUT_DIR = "graficos_rq2"


def read_csv_required(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    return pd.read_csv(path)


def ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def save_plot(fig: plt.Figure, output_dir: Path, filename: str) -> None:
    filepath = output_dir / filename
    fig.tight_layout()
    fig.savefig(filepath, dpi=300, bbox_inches="tight")
    plt.close(fig)
    logging.info("Gráfico salvo em: %s", filepath)


def prepare_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    df = df.copy()
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def plot_boxplot_post_disclosure(rq2_exposicoes: pd.DataFrame, output_dir: Path) -> None:
    if rq2_exposicoes.empty:
        return

    rq2_exposicoes = prepare_numeric(
        rq2_exposicoes,
        ["pre_disclosure_days", "post_disclosure_days", "total_exposure_days"]
    )

    grouped = []
    labels = []
    for db, sub in rq2_exposicoes.groupby("db", dropna=False):
        vals = sub["post_disclosure_days"].dropna()
        if len(vals) > 0:
            grouped.append(vals.values)
            labels.append(db)

    if not grouped:
        return

    fig = plt.figure(figsize=(12, 6))
    plt.boxplot(grouped, labels=labels)
    plt.title("RQ2, distribuição do tempo pós divulgação por DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Dias")
    plt.xticks(rotation=45, ha="right")
    save_plot(fig, output_dir, "rq2_boxplot_pos_divulgacao_por_dbms.png")


def plot_boxplot_total_exposure(rq2_exposicoes: pd.DataFrame, output_dir: Path) -> None:
    if rq2_exposicoes.empty:
        return

    rq2_exposicoes = prepare_numeric(
        rq2_exposicoes,
        ["total_exposure_days"]
    )

    grouped = []
    labels = []
    for db, sub in rq2_exposicoes.groupby("db", dropna=False):
        vals = sub["total_exposure_days"].dropna()
        if len(vals) > 0:
            grouped.append(vals.values)
            labels.append(db)

    if not grouped:
        return

    fig = plt.figure(figsize=(12, 6))
    plt.boxplot(grouped, labels=labels)
    plt.title("RQ2, distribuição do tempo total de exposição por DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Dias")
    plt.xticks(rotation=45, ha="right")
    save_plot(fig, output_dir, "rq2_boxplot_exposicao_total_por_dbms.png")


def plot_cdf_post_disclosure(rq2_exposicoes: pd.DataFrame, output_dir: Path) -> None:
    if rq2_exposicoes.empty:
        return

    rq2_exposicoes = prepare_numeric(rq2_exposicoes, ["post_disclosure_days"])
    values = rq2_exposicoes["post_disclosure_days"].dropna()
    values = values[values >= 0].sort_values()

    if values.empty:
        return

    y = np.arange(1, len(values) + 1) / len(values)

    fig = plt.figure(figsize=(10, 6))
    plt.plot(values.values, y)
    plt.title("RQ2, CDF do tempo pós divulgação")
    plt.xlabel("Dias")
    plt.ylabel("Proporção acumulada")
    save_plot(fig, output_dir, "rq2_cdf_pos_divulgacao.png")


def plot_cdf_total_exposure(rq2_exposicoes: pd.DataFrame, output_dir: Path) -> None:
    if rq2_exposicoes.empty:
        return

    rq2_exposicoes = prepare_numeric(rq2_exposicoes, ["total_exposure_days"])
    values = rq2_exposicoes["total_exposure_days"].dropna()
    values = values[values >= 0].sort_values()

    if values.empty:
        return

    y = np.arange(1, len(values) + 1) / len(values)

    fig = plt.figure(figsize=(10, 6))
    plt.plot(values.values, y)
    plt.title("RQ2, CDF do tempo total de exposição")
    plt.xlabel("Dias")
    plt.ylabel("Proporção acumulada")
    save_plot(fig, output_dir, "rq2_cdf_exposicao_total.png")


def plot_summary_post_disclosure(rq2_resumo: pd.DataFrame, output_dir: Path) -> None:
    if rq2_resumo.empty:
        return

    rq2_resumo = prepare_numeric(
        rq2_resumo,
        [
            "projects_affected",
            "vulnerability_occurrences",
            "median_total_exposure_days",
            "mean_total_exposure_days",
            "median_pre_disclosure_days",
            "mean_pre_disclosure_days",
            "median_post_disclosure_days",
            "mean_post_disclosure_days",
            "max_post_disclosure_days",
        ]
    ).sort_values("median_post_disclosure_days", ascending=False)

    fig = plt.figure(figsize=(10, 6))
    plt.bar(rq2_resumo["db"], rq2_resumo["median_post_disclosure_days"])
    plt.title("RQ2, mediana do tempo pós divulgação por DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Dias")
    plt.xticks(rotation=45, ha="right")
    save_plot(fig, output_dir, "rq2_mediana_pos_divulgacao_por_dbms.png")


def plot_summary_total_exposure(rq2_resumo: pd.DataFrame, output_dir: Path) -> None:
    if rq2_resumo.empty:
        return

    rq2_resumo = prepare_numeric(
        rq2_resumo,
        ["mean_total_exposure_days"]
    ).sort_values("mean_total_exposure_days", ascending=False)

    fig = plt.figure(figsize=(10, 6))
    plt.bar(rq2_resumo["db"], rq2_resumo["mean_total_exposure_days"])
    plt.title("RQ2, média do tempo total de exposição por DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Dias")
    plt.xticks(rotation=45, ha="right")
    save_plot(fig, output_dir, "rq2_media_exposicao_total_por_dbms.png")


def plot_pre_vs_post_summary(rq2_resumo: pd.DataFrame, output_dir: Path) -> None:
    if rq2_resumo.empty:
        return

    rq2_resumo = prepare_numeric(
        rq2_resumo,
        [
            "median_pre_disclosure_days",
            "median_post_disclosure_days",
        ]
    ).sort_values("median_post_disclosure_days", ascending=False)

    x = np.arange(len(rq2_resumo))
    width = 0.38

    fig = plt.figure(figsize=(12, 6))
    plt.bar(x - width / 2, rq2_resumo["median_pre_disclosure_days"], width=width, label="Pré divulgação")
    plt.bar(x + width / 2, rq2_resumo["median_post_disclosure_days"], width=width, label="Pós divulgação")
    plt.title("RQ2, mediana do tempo pré e pós divulgação por DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Dias")
    plt.xticks(x, rq2_resumo["db"], rotation=45, ha="right")
    plt.legend()
    save_plot(fig, output_dir, "rq2_mediana_pre_vs_pos_por_dbms.png")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera gráficos para a RQ2 a partir dos CSVs em rqs_data."
    )
    parser.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        help="Diretório com rq2_exposicoes.csv e rq2_resumo.csv."
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Diretório onde os gráficos serão salvos."
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    ensure_output_dir(output_dir)

    rq2_exposicoes = read_csv_required(input_dir / "rq2_exposicoes.csv")
    rq2_resumo = read_csv_required(input_dir / "rq2_resumo.csv")

    plot_boxplot_post_disclosure(rq2_exposicoes, output_dir)
    plot_boxplot_total_exposure(rq2_exposicoes, output_dir)
    plot_cdf_post_disclosure(rq2_exposicoes, output_dir)
    plot_cdf_total_exposure(rq2_exposicoes, output_dir)
    plot_summary_post_disclosure(rq2_resumo, output_dir)
    plot_summary_total_exposure(rq2_resumo, output_dir)
    plot_pre_vs_post_summary(rq2_resumo, output_dir)

    logging.info("Geração dos gráficos da RQ2 concluída.")


if __name__ == "__main__":
    main()