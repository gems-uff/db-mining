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

VERSION_BUCKET_ORDER = ["1", "2", "3", "4", "5+"]
VULN_BUCKET_ORDER = ["1", "2-3", "4-9", "10-19", "20+"]

VERSION_BUCKET_COLORS = {
    "1": "#dbe9f6",
    "2": "#a9cce3",
    "3": "#6fa8dc",
    "4": "#3d85c6",
    "5+": "#1c4587",
}

VULN_BUCKET_COLORS = {
    "1": "#dbe9f6",
    "2-3": "#a9cce3",
    "4-9": "#6fa8dc",
    "10-19": "#3d85c6",
    "20+": "#1c4587",
}


def normalize_db_display_names(series):
    return series.replace({
        "MS SQL Server_Microsoft Azure SQL Database": "MSSQL/MicrosoftAzure"
    })


def read_csv_required(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
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


def bucketize_vulns_per_version(value):
    value = int(value)
    if value >= 5:
        return "5+"
    return str(value)


def bucketize_versions_per_vuln(value):
    value = int(value)
    if value == 1:
        return "1"
    elif value <= 3:
        return "2-3"
    elif value <= 9:
        return "4-9"
    elif value <= 19:
        return "10-19"
    return "20+"


def prepare_rq1_assoc(rq1_assoc):
    required_cols = ["db", "versionNumber", "cve"]

    missing = [col for col in required_cols if col not in rq1_assoc.columns]
    if missing:
        raise ValueError(f"rq1_associacoes.csv deve conter as colunas: {missing}")

    df = rq1_assoc.copy()

    df["db"] = df["db"].astype(str).str.strip()
    df["versionNumber"] = df["versionNumber"].astype(str).str.strip()
    df["cve"] = df["cve"].astype(str).str.strip()

    df = df[
        df["db"].ne("") &
        df["versionNumber"].ne("") &
        df["cve"].ne("") &
        df["cve"].str.lower().ne("nan")
    ].copy()

    df["db"] = normalize_db_display_names(df["db"])

    return df


def build_versions_by_vulnerability_count(rq1_assoc):
    version_level = (
        rq1_assoc
        .groupby(["db", "versionNumber"], dropna=False)
        .agg(
            vulnerabilities_in_version=("cve", "nunique")
        )
        .reset_index()
    )

    version_level["bucket"] = version_level["vulnerabilities_in_version"].apply(
        bucketize_vulns_per_version
    )

    stacked = (
        version_level
        .groupby(["db", "bucket"], dropna=False)
        .agg(
            vulnerable_versions=("versionNumber", "nunique")
        )
        .reset_index()
    )

    pivot = (
        stacked
        .pivot(index="db", columns="bucket", values="vulnerable_versions")
        .fillna(0)
        .astype(int)
    )

    for bucket in VERSION_BUCKET_ORDER:
        if bucket not in pivot.columns:
            pivot[bucket] = 0

    pivot = pivot[VERSION_BUCKET_ORDER]
    pivot["total"] = pivot.sum(axis=1)
    pivot = pivot[pivot["total"] > 0]
    pivot = pivot.sort_values("total", ascending=False)

    return pivot


def build_vulnerabilities_by_affected_versions_count(rq1_assoc):
    vulnerability_level = (
        rq1_assoc
        .groupby(["db", "cve"], dropna=False)
        .agg(
            affected_versions=("versionNumber", "nunique")
        )
        .reset_index()
    )

    vulnerability_level["bucket"] = vulnerability_level["affected_versions"].apply(
        bucketize_versions_per_vuln
    )

    stacked = (
        vulnerability_level
        .groupby(["db", "bucket"], dropna=False)
        .agg(
            vulnerabilities=("cve", "nunique")
        )
        .reset_index()
    )

    pivot = (
        stacked
        .pivot(index="db", columns="bucket", values="vulnerabilities")
        .fillna(0)
        .astype(int)
    )

    for bucket in VULN_BUCKET_ORDER:
        if bucket not in pivot.columns:
            pivot[bucket] = 0

    pivot = pivot[VULN_BUCKET_ORDER]
    pivot["total"] = pivot.sum(axis=1)
    pivot = pivot[pivot["total"] > 0]
    pivot = pivot.sort_values("total", ascending=False)

    return pivot


def label_for_bucket(bucket, legend_title):
    if "vulnerabilidades por versão" in legend_title.lower():
        if bucket == "1":
            return "1 vulnerabilidade"
        if bucket == "5+":
            return "5 ou mais vulnerabilidades"
        return f"{bucket} vulnerabilidades"

    if bucket == "1":
        return "Afeta 1 versão"
    if bucket == "20+":
        return "Afeta 20 ou mais versões"
    return f"Afeta {bucket} versões"


def plot_stacked_bar(
    pivot,
    bucket_order,
    output_dir,
    filename,
    title,
    ylabel,
    legend_title,
    colors
):
    if pivot.empty:
        logging.warning("Base vazia para o gráfico: %s", filename)
        return

    plot_df = pivot[bucket_order].copy()

    width = max(11, len(plot_df) * 0.85)
    fig, ax = plt.subplots(figsize=(width, 7))

    bottom = pd.Series([0] * len(plot_df), index=plot_df.index)

    for bucket in bucket_order:
        values = plot_df[bucket]

        ax.bar(
            plot_df.index,
            values,
            bottom=bottom,
            label=label_for_bucket(bucket, legend_title),
            color=colors[bucket],
            edgecolor="black",
            linewidth=0.4
        )

        bottom = bottom + values

    ax.set_title(title)
    ax.set_xlabel("DBMS")
    ax.set_ylabel(ylabel)
    ax.set_xticks(range(len(plot_df.index)))
    ax.set_xticklabels(plot_df.index, rotation=45, ha="right")
    ax.legend(title=legend_title)

    ymax = int(plot_df.sum(axis=1).max())
    ax.set_ylim(0, ymax * 1.15 if ymax > 0 else 1)

    for i, total in enumerate(plot_df.sum(axis=1)):
        ax.text(
            i,
            total + max(0.1, ymax * 0.02),
            str(int(total)),
            ha="center",
            va="bottom",
            fontsize=9
        )

    save_plot(fig, output_dir, filename)


def export_intermediate_tables(
    versions_pivot,
    vulnerabilities_pivot,
    input_dir
):
    versions_out = Path(input_dir) / "rq1_distribuicao_versoes_por_qtd_vulnerabilidades.csv"
    vulnerabilities_out = Path(input_dir) / "rq1_distribuicao_vulnerabilidades_por_qtd_versoes.csv"

    versions_pivot.reset_index().to_csv(versions_out, index=False)
    vulnerabilities_pivot.reset_index().to_csv(vulnerabilities_out, index=False)

    logging.info("CSV gerado: %s", versions_out)
    logging.info("CSV gerado: %s", vulnerabilities_out)


def main():
    parser = argparse.ArgumentParser(
        description="Gera gráficos empilhados para detalhar versões vulneráveis e vulnerabilidades por BD."
    )
    parser.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        help="Diretório com rq1_associacoes.csv."
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
    rq1_assoc = prepare_rq1_assoc(rq1_assoc)

    versions_pivot = build_versions_by_vulnerability_count(rq1_assoc)
    vulnerabilities_pivot = build_vulnerabilities_by_affected_versions_count(rq1_assoc)

    export_intermediate_tables(
        versions_pivot,
        vulnerabilities_pivot,
        input_dir
    )

    plot_stacked_bar(
        pivot=versions_pivot,
        bucket_order=VERSION_BUCKET_ORDER,
        output_dir=output_dir,
        filename="rq1_bd_versoes_por_qtd_vulnerabilidades_empilhado.png",
        title="Distribuição de versões vulneráveis por quantidade de vulnerabilidades",
        ylabel="Quantidade de versões vulneráveis",
        legend_title="Vulnerabilidades por versão",
        colors=VERSION_BUCKET_COLORS
    )

    plot_stacked_bar(
        pivot=vulnerabilities_pivot,
        bucket_order=VULN_BUCKET_ORDER,
        output_dir=output_dir,
        filename="rq1_bd_vulnerabilidades_por_qtd_versoes_afetadas_empilhado.png",
        title="Distribuição de vulnerabilidades por quantidade de versões afetadas",
        ylabel="Quantidade de vulnerabilidades",
        legend_title="Versões afetadas por vulnerabilidade",
        colors=VULN_BUCKET_COLORS
    )

    logging.info("Geração dos gráficos empilhados concluída.")


if __name__ == "__main__":
    main()