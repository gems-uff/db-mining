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

def normalize_db_display_names(series):
    return series.replace({
        "MS SQL Server_Microsoft Azure SQL Database": "MSSQL/MicrosoftAzure"
    })


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
        logging.warning("rq1_dbms.csv is empty. Chart will not be generated.")
        return

    rq1_dbms = prepare_numeric(
        rq1_dbms,
        [
            "projects_affected",
            "projects_using_db",
            "exposure_project_percent"
        ]
    )

    required_cols = [
        "db",
        "projects_affected",
        "projects_using_db",
        "exposure_project_percent",
        "projects_exposure_label"
    ]

    missing = [col for col in required_cols if col not in rq1_dbms.columns]
    if missing:
        raise ValueError(f"rq1_dbms.csv must contain columns: {missing}")

    filtered = rq1_dbms[rq1_dbms["projects_affected"] > 0].copy()

    filtered = filtered.sort_values(
        ["projects_affected", "projects_using_db", "db"],
        ascending=[False, False, True]
    )

    if filtered.empty:
        logging.warning("No DBMS with affected projects found. Chart will not be generated.")
        return

    width = max(10, len(filtered) * 0.8)
    fig = plt.figure(figsize=(width, 8))

    bars = plt.bar(
        filtered["db"],
        filtered["projects_affected"],
        color="dimgray",
        label="Affected projects"
    )

    plt.title("Affected projects by DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Affected projects")
    plt.xticks(rotation=45, ha="right")
    plt.legend()

    ymax = filtered["projects_affected"].max()
    offset = max(0.1, ymax * 0.03)

    plt.ylim(0, ymax * 1.30)

    for bar, (_, row) in zip(bars, filtered.iterrows()):
        height = bar.get_height()

        label = (
            f"{row['projects_exposure_label']} projects\n"
            f"{row['exposure_project_percent']:.1f}% exposed"
        )

        plt.text(
            bar.get_x() + bar.get_width() / 2,
            height + offset,
            label,
            ha="center",
            va="bottom",
            fontsize=8,
            color="black",
            rotation=90
        )

    save_plot(fig, output_dir, "rq1_projetos_afetados_por_bd.png")


def plot_db_versions_and_vulnerabilities(rq1_dbms, output_dir):
    if rq1_dbms.empty:
        logging.warning("rq1_dbms.csv is empty. Chart will not be generated.")
        return

    rq1_dbms = prepare_numeric(
        rq1_dbms,
        ["vulnerable_versions", "vulnerability_occurrences"]
    )

    required_cols = [
        "db",
        "vulnerable_versions",
        "vulnerability_occurrences"
    ]

    missing = [col for col in required_cols if col not in rq1_dbms.columns]
    if missing:
        raise ValueError(f"rq1_dbms.csv must contain columns: {missing}")

    filtered = rq1_dbms[
        (rq1_dbms["vulnerable_versions"] > 0) |
        (rq1_dbms["vulnerability_occurrences"] > 0)
    ].copy()

    filtered = filtered.sort_values(
        ["vulnerable_versions", "vulnerability_occurrences", "db"],
        ascending=[False, False, True]
    )

    if filtered.empty:
        logging.warning("No DBMS with values greater than zero found.")
        return

    positions = list(range(len(filtered)))
    bar_width = 0.4
    left_positions = [p - bar_width / 2 for p in positions]
    right_positions = [p + bar_width / 2 for p in positions]

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
        label="Unique vulnerable versions",
        color="dimgray"
    )

    bars_vulns = plt.bar(
        right_positions,
        filtered["vulnerability_occurrences"],
        width=bar_width,
        label="Unique vulnerabilities",
        color="lightgray",
        edgecolor="black"
    )

    plt.title("Unique vulnerable versions and vulnerabilities by DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Count")
    plt.xticks(positions, filtered["db"], rotation=45, ha="right")
    plt.legend()

    for bar in bars_versions:
        height = bar.get_height()
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            height + offset,
            str(int(height)),
            ha="center",
            va="bottom",
            fontsize=9
        )

    for bar in bars_vulns:
        height = bar.get_height()
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            height + offset,
            str(int(height)),
            ha="center",
            va="bottom",
            fontsize=9
        )

    save_plot(
        fig,
        output_dir,
        "rq1_bd_versoes_vulneraveis_e_vulnerabilidades.png"
    )


def plot_dbms_usage_vs_exposure(rq1_dbms, output_dir):
    if rq1_dbms.empty:
        logging.warning("rq1_dbms.csv is empty. Chart will not be generated.")
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
        raise ValueError(f"rq1_dbms.csv must contain columns: {missing}")

    filtered = rq1_dbms[rq1_dbms["projects_using_db"] > 0].copy()

    filtered = filtered.sort_values(
        ["projects_affected", "projects_using_db", "db"],
        ascending=[True, True, False]
    )

    height = max(6, len(filtered) * 0.45)
    fig = plt.figure(figsize=(10, height))

    y_positions = range(len(filtered))

    plt.barh(
        y_positions,
        filtered["projects_using_db"],
        label="Projects using DBMS",
        color="gainsboro",
        edgecolor="black"
    )

    plt.barh(
        y_positions,
        filtered["projects_affected"],
        label="Affected projects",
        color="dimgray"
    )

    plt.yticks(y_positions, filtered["db"])
    plt.xlabel("Number of projects")
    plt.ylabel("DBMS")
    plt.title("RQ1, Projects using each DBMS and affected projects")
    plt.legend()

    for i, row in enumerate(filtered.itertuples()):
        label = f"{int(row.projects_affected)}/{int(row.projects_using_db)} projects, {row.exposure_project_percent:.1f}%"

        plt.text(
            row.projects_using_db + 0.2,
            i,
            label,
            va="center",
            fontsize=8
        )

    save_plot(fig, output_dir, "rq1_bd_uso_vs_exposicao.png")

def plot_dbms_commits_present_vs_vulnerable(input_dir, output_dir):
    path = Path("rq1_bd_aparecem_com_sem_vulnerabilidade.csv")

    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")

    df = pd.read_csv(path)
    df["db"] = normalize_db_display_names(df["db"])

    required_cols = [
        "db",
        "commits_present",
        "vulnerable_commits",
        "exposure_commit_pct"
    ]

    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"O CSV deve conter as colunas: {missing}")

    df = prepare_numeric(
        df,
        ["commits_present", "vulnerable_commits", "exposure_commit_pct"]
    )

    filtered = df[
    (df["commits_present"] > 0) &
    (df["vulnerable_commits"] > 0)].copy()

    filtered = filtered.sort_values(
        ["vulnerable_commits", "commits_present", "db"],
        ascending=[True, True, False]
    )

    height = max(6, len(filtered) * 0.45)
    fig = plt.figure(figsize=(11, height))

    y_positions = range(len(filtered))

    plt.barh(
        y_positions,
        filtered["commits_present"],
        label="Commits with DBMS usage",
        color="gainsboro",
        edgecolor="black"
    )

    plt.barh(
        y_positions,
        filtered["vulnerable_commits"],
        label="Vulnerable commits",
        color="dimgray"
    )

    plt.yticks(y_positions, filtered["db"])
    plt.xlabel("Number of commits")
    plt.ylabel("DBMS")
    plt.title("Commits with DBMS usage and vulnerable commits by DBMS")
    plt.legend()

    max_value = filtered["commits_present"].max()
    plt.xlim(0, max_value * 1.25)

    for i, row in enumerate(filtered.itertuples()):
        label = (
            f"{int(row.vulnerable_commits)}/"
            f"{int(row.commits_present)} commits, "
            f"{row.exposure_commit_pct:.1f}%"
        )

        plt.text(
            row.commits_present + max_value * 0.01,
            i,
            label,
            va="center",
            fontsize=8
        )

    save_plot(fig, output_dir, "rq1_commits_present_vs_vulnerable_by_dbms.png")


def plot_dbms_vulnerable_activity(input_dir, output_dir):
    path = Path("rq1_bd_aparecem_com_sem_vulnerabilidade.csv")

    if not path.exists():
        path = Path(input_dir) / "rq1_bd_aparecem_com_sem_vulnerabilidade.csv"

    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")

    df = pd.read_csv(path)

    required_cols = ["db", "vulnerable_activity_commits"]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"O CSV deve conter as colunas: {missing}")

    df = prepare_numeric(df, ["vulnerable_activity_commits"])
    df["db"] = normalize_db_display_names(df["db"])

    filtered = df[df["vulnerable_activity_commits"] > 0].copy()

    filtered = filtered.sort_values(
        "vulnerable_activity_commits",
        ascending=True
    )

    height = max(6, len(filtered) * 0.45)
    fig = plt.figure(figsize=(11, height))

    y_positions = range(len(filtered))

    bars = plt.barh(
        y_positions,
        filtered["vulnerable_activity_commits"],
        color="dimgray"
    )

    plt.yticks(y_positions, filtered["db"])
    plt.xlabel("Commits between vulnerable DBMS observations")
    plt.ylabel("DBMS")
    plt.title("Vulnerable activity by DBMS")

    max_value = filtered["vulnerable_activity_commits"].max()
    plt.xlim(0, max_value * 1.15)

    for bar in bars:
        width = bar.get_width()
        plt.text(
            width + max_value * 0.01,
            bar.get_y() + bar.get_height() / 2,
            str(int(width)),
            va="center",
            fontsize=8
        )

    save_plot(fig, output_dir, "rq1_vulnerable_activity_by_dbms.png")

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
    rq1_dbms["db"] = normalize_db_display_names(rq1_dbms["db"])

    plot_projects_affected_by_dbms(rq1_dbms, output_dir)
    plot_db_versions_and_vulnerabilities(rq1_dbms, output_dir)
    plot_dbms_usage_vs_exposure(rq1_dbms, output_dir)
    plot_dbms_commits_present_vs_vulnerable(input_dir, output_dir)
    plot_dbms_vulnerable_activity(input_dir, output_dir)

    
    logging.info("Geração dos gráficos da RQ1 concluída.")


if __name__ == "__main__":
    main()
