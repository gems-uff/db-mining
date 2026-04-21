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


def read_csv_required(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError("Arquivo não encontrado: {}".format(path))
    return pd.read_csv(path)


def ensure_output_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)


def save_plot(fig, output_dir, filename):
    filepath = Path(output_dir) / filename
    fig.tight_layout()
    fig.savefig(filepath, dpi=300, bbox_inches="tight")
    plt.close(fig)
    logging.info("Gráfico salvo em: %s", filepath)


def prepare_numeric(df, columns):
    df = df.copy()
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def plot_projects_affected_by_dbms(rq1_dbms, output_dir):
    if rq1_dbms.empty:
        logging.warning("rq1_dbms.csv está vazio. Gráfico não será gerado.")
        return

    rq1_dbms = prepare_numeric(
        rq1_dbms,
        ["projects_affected", "vulnerable_versions", "vulnerability_occurrences"]
    )

    if "db" not in rq1_dbms.columns or "projects_affected" not in rq1_dbms.columns:
        raise ValueError(
            "rq1_dbms.csv deve conter as colunas 'db' e 'projects_affected'."
        )

    filtered = rq1_dbms[rq1_dbms["projects_affected"] > 0].copy()
    filtered = filtered.sort_values("projects_affected", ascending=False)

    if filtered.empty:
        logging.warning(
            "Nenhum BD com projects_affected > 0 encontrado. Gráfico não será gerado."
        )
        return

    width = max(10, len(filtered) * 0.7)
    fig = plt.figure(figsize=(width, 6))
    bars = plt.bar(filtered["db"], filtered["projects_affected"])

    plt.title("RQ1, quantidade de projetos afetados por BD")
    plt.xlabel("BD")
    plt.ylabel("Projetos afetados")
    plt.xticks(rotation=45, ha="right")

    ymax = filtered["projects_affected"].max()
    offset = max(0.1, ymax * 0.01)

    for bar in bars:
        height = bar.get_height()
        plt.text(
            bar.get_x() + bar.get_width() / 2.0,
            height + offset,
            str(int(height)),
            ha="center",
            va="bottom"
        )

    save_plot(fig, output_dir, "rq1_projetos_afetados_por_bd.png")


def plot_heatmap_project_dbms(rq1_assoc, output_dir):
    if rq1_assoc.empty:
        logging.warning("rq1_associacoes.csv está vazio. Heatmap não será gerado.")
        return

    required_cols = ["project", "db", "versionNumber"]
    missing = [col for col in required_cols if col not in rq1_assoc.columns]
    if missing:
        raise ValueError(
            "rq1_associacoes.csv deve conter as colunas {}.".format(missing)
        )

    work_df = rq1_assoc.copy()
    work_df["project"] = work_df["project"].astype(str).str.strip()
    work_df["db"] = work_df["db"].astype(str).str.strip()
    work_df["versionNumber"] = work_df["versionNumber"].astype(str).str.strip()

    grouped = (
        work_df.groupby(["project", "db"], dropna=False)
        .agg(unique_vulnerable_versions=("versionNumber", "nunique"))
        .reset_index()
    )

    if grouped.empty:
        logging.warning("Não há associações válidas para gerar o heatmap.")
        return

    pivot = grouped.pivot(
        index="project",
        columns="db",
        values="unique_vulnerable_versions"
    ).fillna(0)

    if pivot.empty:
        logging.warning("A matriz do heatmap ficou vazia.")
        return

    pivot = pivot.loc[pivot.sum(axis=1) > 0, :]
    if pivot.empty:
        logging.warning("Nenhum projeto com versões vulneráveis únicas > 0 no heatmap.")
        return

    pivot["__total__"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("__total__", ascending=False).drop(columns="__total__")

    display_index = []
    for name in pivot.index:
        name = str(name)
        if len(name) <= 25:
            display_index.append(name)
        else:
            display_index.append(name[:22] + "...")

    height = max(8, len(pivot.index) * 0.35)
    width = max(10, len(pivot.columns) * 0.8)

    fig = plt.figure(figsize=(width, height))
    image = plt.imshow(pivot.values, aspect="auto")

    plt.title("RQ1, heatmap de versões únicas vulneráveis por projeto e BD")
    plt.xlabel("BD")
    plt.ylabel("Projetos")
    plt.xticks(range(len(pivot.columns)), pivot.columns, rotation=45, ha="right")
    plt.yticks(range(len(pivot.index)), display_index)
    plt.colorbar(image, label="Versões únicas com vulnerabilidades")

    save_plot(fig, output_dir, "rq1_heatmap_projeto_bd.png")


def plot_db_versions_and_vulnerabilities(rq1_dbms, output_dir):
    if rq1_dbms.empty:
        logging.warning("rq1_dbms.csv está vazio. Gráfico comparativo não será gerado.")
        return

    rq1_dbms = prepare_numeric(
        rq1_dbms,
        ["vulnerable_versions", "vulnerability_occurrences"]
    )

    required_cols = ["db", "vulnerable_versions", "vulnerability_occurrences"]
    missing = [col for col in required_cols if col not in rq1_dbms.columns]
    if missing:
        raise ValueError(
            "rq1_dbms.csv deve conter as colunas {}.".format(missing)
        )

    filtered = rq1_dbms[
        (rq1_dbms["vulnerable_versions"] > 0) |
        (rq1_dbms["vulnerability_occurrences"] > 0)
    ].copy()

    filtered = filtered.sort_values(
        ["vulnerable_versions", "vulnerability_occurrences", "db"],
        ascending=[False, False, True]
    )

    if filtered.empty:
        logging.warning("Nenhum BD com versões ou vulnerabilidades > 0 encontrado.")
        return

    positions = list(range(len(filtered)))
    bar_width = 0.4
    left_positions = [pos - bar_width / 2 for pos in positions]
    right_positions = [pos + bar_width / 2 for pos in positions]

    width = max(11, len(filtered) * 0.9)
    ymax = max(
        filtered["vulnerable_versions"].max(),
        filtered["vulnerability_occurrences"].max()
    )
    offset = max(0.1, ymax * 0.01)

    fig = plt.figure(figsize=(width, 6))
    bars_versions = plt.bar(
        left_positions,
        filtered["vulnerable_versions"],
        width=bar_width,
        label="Versões únicas vulneráveis"
    )
    bars_vulns = plt.bar(
        right_positions,
        filtered["vulnerability_occurrences"],
        width=bar_width,
        label="Vulnerabilidades únicas"
    )

    plt.title("RQ1, versões únicas vulneráveis e vulnerabilidades únicas por BD")
    plt.xlabel("BD")
    plt.ylabel("Quantidade")
    plt.xticks(positions, filtered["db"], rotation=45, ha="right")
    plt.legend()

    for bar in bars_versions:
        height = bar.get_height()
        plt.text(
            bar.get_x() + bar.get_width() / 2.0,
            height + offset,
            str(int(height)),
            ha="center",
            va="bottom",
            fontsize=9
        )

    for bar in bars_vulns:
        height = bar.get_height()
        plt.text(
            bar.get_x() + bar.get_width() / 2.0,
            height + offset,
            str(int(height)),
            ha="center",
            va="bottom",
            fontsize=9
        )

    save_plot(fig, output_dir, "rq1_bd_versoes_vulneraveis_e_vulnerabilidades.png")


def main():
    parser = argparse.ArgumentParser(
        description="Gera gráficos da RQ1 focados em BDs."
    )
    parser.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        help="Diretório com rq1_associacoes.csv e rq1_dbms.csv."
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

    rq1_assoc = read_csv_required(input_dir / "rq1_associacoes.csv")
    rq1_dbms = read_csv_required(input_dir / "rq1_dbms.csv")

    plot_projects_affected_by_dbms(rq1_dbms, output_dir)
    plot_heatmap_project_dbms(rq1_assoc, output_dir)
    plot_db_versions_and_vulnerabilities(rq1_dbms, output_dir)

    logging.info("Geração dos gráficos da RQ1 concluída.")


if __name__ == "__main__":
    main()
