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


def plot_vulnerability_occurrences_by_project(rq1_projects: pd.DataFrame, output_dir: Path) -> None:
    if rq1_projects.empty:
        return

    rq1_projects = prepare_numeric(
        rq1_projects,
        ["dbms_affected", "vulnerable_versions", "vulnerability_occurrences"]
    )

    filtered = rq1_projects[rq1_projects["vulnerability_occurrences"] > 0].copy()
    filtered = filtered.sort_values("vulnerability_occurrences", ascending=False)

    if filtered.empty:
        return

    width = max(14, len(filtered) * 0.28)

    fig = plt.figure(figsize=(width, 6))
    plt.bar(filtered["project"], filtered["vulnerability_occurrences"])
    plt.title("RQ1, ocorrências de vulnerabilidades por projeto")
    plt.xlabel("Projeto")
    plt.ylabel("Ocorrências de vulnerabilidades")
    plt.xticks(rotation=90, ha="center")
    save_plot(fig, output_dir, "rq1_ocorrencias_vulnerabilidades_por_projeto.png")


def plot_dbms_affected_by_project(rq1_projects: pd.DataFrame, output_dir: Path) -> None:
    if rq1_projects.empty:
        return

    rq1_projects = prepare_numeric(
        rq1_projects,
        ["dbms_affected", "vulnerable_versions", "vulnerability_occurrences"]
    )

    filtered = rq1_projects[rq1_projects["dbms_affected"] > 0].copy()
    filtered = filtered.sort_values("dbms_affected", ascending=False)

    if filtered.empty:
        return

    width = max(14, len(filtered) * 0.28)

    fig = plt.figure(figsize=(width, 6))
    plt.bar(filtered["project"], filtered["dbms_affected"])
    plt.title("RQ1, quantidade de DBMS afetados por projeto")
    plt.xlabel("Projeto")
    plt.ylabel("DBMS afetados")
    plt.xticks(rotation=90, ha="center")
    save_plot(fig, output_dir, "rq1_dbms_afetados_por_projeto.png")


def plot_projects_affected_by_dbms(rq1_dbms: pd.DataFrame, output_dir: Path) -> None:
    if rq1_dbms.empty:
        return

    rq1_dbms = prepare_numeric(
        rq1_dbms,
        ["projects_affected", "vulnerable_versions", "vulnerability_occurrences"]
    ).sort_values("projects_affected", ascending=False)

    fig = plt.figure(figsize=(10, 6))
    plt.bar(rq1_dbms["db"], rq1_dbms["projects_affected"])
    plt.title("RQ1, projetos afetados por DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Projetos afetados")
    plt.xticks(rotation=45, ha="right")
    save_plot(fig, output_dir, "rq1_projetos_afetados_por_dbms.png")


def plot_vulnerability_occurrences_by_dbms(rq1_dbms: pd.DataFrame, output_dir: Path) -> None:
    if rq1_dbms.empty:
        return

    rq1_dbms = prepare_numeric(
        rq1_dbms,
        ["projects_affected", "vulnerable_versions", "vulnerability_occurrences"]
    ).sort_values("vulnerability_occurrences", ascending=False)

    fig = plt.figure(figsize=(10, 6))
    plt.bar(rq1_dbms["db"], rq1_dbms["vulnerability_occurrences"])
    plt.title("RQ1, ocorrências de vulnerabilidades por DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Ocorrências de vulnerabilidades")
    plt.xticks(rotation=45, ha="right")
    save_plot(fig, output_dir, "rq1_ocorrencias_vulnerabilidades_por_dbms.png")


def plot_vulnerable_versions_by_dbms(rq1_dbms: pd.DataFrame, output_dir: Path) -> None:
    if rq1_dbms.empty:
        return

    rq1_dbms = prepare_numeric(
        rq1_dbms,
        ["projects_affected", "vulnerable_versions", "vulnerability_occurrences"]
    ).sort_values("vulnerable_versions", ascending=False)

    fig = plt.figure(figsize=(10, 6))
    plt.bar(rq1_dbms["db"], rq1_dbms["vulnerable_versions"])
    plt.title("RQ1, versões vulneráveis observadas por DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Versões vulneráveis")
    plt.xticks(rotation=45, ha="right")
    save_plot(fig, output_dir, "rq1_versoes_vulneraveis_por_dbms.png")


def plot_heatmap_project_dbms(rq1_assoc: pd.DataFrame, output_dir: Path) -> None:
    if rq1_assoc.empty:
        return

    pivot = (
        rq1_assoc.groupby(["project", "db"], dropna=False)
        .size()
        .reset_index(name="occurrences")
        .pivot(index="project", columns="db", values="occurrences")
        .fillna(0)
    )

    if pivot.empty:
        return

    pivot = pivot.loc[(pivot.sum(axis=1) > 0), :]
    pivot["__total__"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("__total__", ascending=False).drop(columns="__total__")

    display_index = [
        name if len(str(name)) <= 25 else str(name)[:22] + "..."
        for name in pivot.index
    ]

    height = max(10, len(pivot.index) * 0.35)
    fig = plt.figure(figsize=(14, height))
    plt.imshow(pivot.values, aspect="auto")
    plt.title("RQ1, heatmap de ocorrências por projeto e DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Projetos")
    plt.xticks(range(len(pivot.columns)), pivot.columns, rotation=45, ha="right")
    plt.yticks(range(len(pivot.index)), display_index)
    plt.colorbar(label="Ocorrências")
    save_plot(fig, output_dir, "rq1_heatmap_projeto_dbms.png")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera gráficos para a RQ1 a partir dos CSVs em rqs_data."
    )
    parser.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        help="Diretório com rq1_associacoes.csv, rq1_projetos.csv e rq1_dbms.csv."
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
    rq1_projects = read_csv_required(input_dir / "rq1_projetos.csv")
    rq1_dbms = read_csv_required(input_dir / "rq1_dbms.csv")

    plot_vulnerability_occurrences_by_project(rq1_projects, output_dir)
    plot_dbms_affected_by_project(rq1_projects, output_dir)
    plot_projects_affected_by_dbms(rq1_dbms, output_dir)
    plot_vulnerability_occurrences_by_dbms(rq1_dbms, output_dir)
    plot_vulnerable_versions_by_dbms(rq1_dbms, output_dir)
    plot_heatmap_project_dbms(rq1_assoc, output_dir)

    logging.info("Geração dos gráficos da RQ1 concluída.")


if __name__ == "__main__":
    main()
