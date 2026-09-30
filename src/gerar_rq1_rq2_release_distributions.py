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

DEFAULT_INPUT_DIR = "rqs_data"
DEFAULT_OUTPUT_DIR = "graficos_rq1"
DEFAULT_RQ2_OUTPUT_DIR = "graficos_rq2"

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
        "MS SQL Server_Microsoft Azure SQL Database": "MSSQL/MicrosoftAzure",
        "MS SQL Server/Microsoft Azure SQL Database": "MSSQL/MicrosoftAzure",
    })


def read_csv_required(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    return pd.read_csv(path)


def ensure_output_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)


def read_maven_release_denominators(input_dir):
    path = Path(input_dir) / "maven_family_version_counts_by_dbms.csv"
    if not path.exists():
        logging.warning(
            "Arquivo não encontrado para proporções de releases Maven: %s",
            path,
        )
        return {}

    df = pd.read_csv(path)
    required_cols = ["db", "maven_central_distinct_versions_family"]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        logging.warning(
            "Arquivo %s sem colunas necessárias para proporções: %s",
            path,
            missing,
        )
        return {}

    df = df.copy()
    df["db"] = normalize_db_display_names(df["db"].astype(str).str.strip())
    df["maven_central_distinct_versions_family"] = pd.to_numeric(
        df["maven_central_distinct_versions_family"],
        errors="coerce",
    )
    df = df.dropna(subset=["db", "maven_central_distinct_versions_family"])

    return dict(
        zip(
            df["db"],
            df["maven_central_distinct_versions_family"].astype(int),
        )
    )


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
        raise ValueError(f"vulnerability_release_project_associations.csv deve conter as colunas: {missing}")

    df = rq1_assoc.copy()

    df["db"] = df["db"].astype(str).str.strip()
    df["versionNumber"] = df["versionNumber"].astype(str).str.strip()
    df["cve"] = df["cve"].astype(str).str.strip()
    if "vuln_purl" in df.columns:
        df["vuln_purl"] = df["vuln_purl"].astype(str).str.strip()
        df.loc[df["vuln_purl"].str.lower().isin(["", "nan", "none"]), "vuln_purl"] = pd.NA
    else:
        df["vuln_purl"] = pd.NA

    df = df[
        df["db"].ne("") &
        df["versionNumber"].ne("") &
        df["cve"].ne("") &
        df["cve"].str.lower().ne("nan")
    ].copy()

    df["db"] = normalize_db_display_names(df["db"])
    df["package_release_id"] = (
        df["vuln_purl"].fillna(df["db"] + "@" + df["versionNumber"])
    )

    return df


def build_versions_by_vulnerability_count(rq1_assoc):
    version_level = (
        rq1_assoc
        .groupby(["db", "package_release_id"], dropna=False)
        .agg(
            versionNumber=("versionNumber", "first"),
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
            vulnerable_versions=("package_release_id", "nunique")
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
    if (
        "vulnerabilidades por versão" in legend_title.lower()
        or "vulnerabilities per version" in legend_title.lower()
        or "vulnerabilities per release" in legend_title.lower()
    ):
        if bucket == "1":
            return "1 vulnerability"
        if bucket == "5+":
            return "5 or more vulnerabilities"
        return f"{bucket} vulnerabilities"

    if bucket == "1":
        return "Affects 1 release"
    if bucket == "20+":
        return "Affects 20 or more releases"
    return f"Affects {bucket} releases"


def plot_stacked_bar(
    pivot,
    bucket_order,
    output_dir,
    filename,
    title,
    ylabel,
    legend_title,
    colors,
    release_denominators=None,
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

    if title:
        ax.set_title(title)
    ax.set_xlabel("DBMS")
    ax.set_ylabel(ylabel)
    ax.set_xticks(range(len(plot_df.index)))
    ax.set_xticklabels(plot_df.index, rotation=45, ha="right")
    ax.legend(title=legend_title)

    ymax = int(plot_df.sum(axis=1).max())
    label_headroom = 1.15
    ax.set_ylim(0, ymax * label_headroom if ymax > 0 else 1)

    for i, total in enumerate(plot_df.sum(axis=1)):
        label = str(int(total))

        ax.text(
            i,
            total + max(0.1, ymax * 0.02),
            label,
            ha="center",
            va="bottom",
            fontsize=9
        )

    save_plot(fig, output_dir, filename)


def plot_normalized_vulnerable_releases(
    pivot,
    bucket_order,
    output_dir,
    filename,
    ylabel,
    legend_title,
    colors,
    release_denominators,
):
    if pivot.empty:
        logging.warning("Base vazia para o gráfico normalizado: %s", filename)
        return

    rows = []
    for db, row in pivot.iterrows():
        denominator = release_denominators.get(db)
        if not denominator or denominator <= 0:
            logging.warning("Sem denominador Maven para normalizar: %s", db)
            continue

        normalized = {bucket: row[bucket] / denominator for bucket in bucket_order}
        normalized["db"] = db
        normalized["total"] = row[bucket_order].sum() / denominator
        normalized["vulnerable_releases"] = int(row[bucket_order].sum())
        normalized["maven_releases"] = int(denominator)
        rows.append(normalized)

    if not rows:
        logging.warning("Nenhum dado com denominador para o gráfico normalizado.")
        return

    plot_df = pd.DataFrame(rows).set_index("db")
    plot_df = plot_df.sort_values("total", ascending=False)

    width = max(11, len(plot_df) * 0.85)
    fig, ax = plt.subplots(figsize=(width, 7))
    bottom = pd.Series(0.0, index=plot_df.index)

    for bucket in bucket_order:
        values = plot_df[bucket]
        ax.bar(
            plot_df.index,
            values,
            bottom=bottom,
            label=label_for_bucket(bucket, legend_title),
            color=colors[bucket],
            edgecolor="black",
            linewidth=0.4,
        )
        bottom = bottom + values

    ax.set_xlabel("DBMS")
    ax.set_ylabel(ylabel)
    ax.set_xticks(range(len(plot_df.index)))
    ax.set_xticklabels(plot_df.index, rotation=45, ha="right")
    ax.legend(title=legend_title)
    ax.set_ylim(0, max(1.0, float(plot_df["total"].max()) * 1.18))

    for i, row in enumerate(plot_df.itertuples()):
        ax.text(
            i,
            row.total + max(0.01, float(plot_df["total"].max()) * 0.02),
            f"{row.total * 100:.1f}%",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    save_plot(fig, output_dir, filename)


def export_intermediate_tables(
    versions_pivot,
    vulnerabilities_pivot,
    input_dir
):
    versions_out = Path(input_dir) / "rq1_affected_releases_by_vulnerability_count.csv"
    vulnerabilities_out = Path(input_dir) / "rq2_vulnerabilities_by_affected_release_count.csv"

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
        help="Diretório com vulnerability_release_project_associations.csv."
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Diretório onde os gráficos serão salvos."
    )
    parser.add_argument(
        "--rq2-output-dir",
        default=DEFAULT_RQ2_OUTPUT_DIR,
        help="Diretório onde o gráfico de vulnerabilidades por quantidade de versões afetadas será salvo."
    )

    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    rq2_output_dir = Path(args.rq2_output_dir)

    ensure_output_dir(output_dir)
    ensure_output_dir(rq2_output_dir)

    rq1_assoc = read_csv_required(input_dir / "vulnerability_release_project_associations.csv")
    rq1_assoc = prepare_rq1_assoc(rq1_assoc)

    versions_pivot = build_versions_by_vulnerability_count(rq1_assoc)
    vulnerabilities_pivot = build_vulnerabilities_by_affected_versions_count(rq1_assoc)
    maven_release_denominators = read_maven_release_denominators(input_dir)

    export_intermediate_tables(
        versions_pivot,
        vulnerabilities_pivot,
        input_dir
    )

    plot_stacked_bar(
        pivot=versions_pivot,
        bucket_order=VERSION_BUCKET_ORDER,
        output_dir=output_dir,
        filename="rq1_affected_releases_by_vulnerability_count.png",
        title="",
        ylabel="Number of vulnerable releases",
        legend_title="Vulnerabilities per release",
        colors=VERSION_BUCKET_COLORS,
        release_denominators=maven_release_denominators,
    )

    plot_normalized_vulnerable_releases(
        pivot=versions_pivot,
        bucket_order=VERSION_BUCKET_ORDER,
        output_dir=output_dir,
        filename="rq1_affected_releases_share_by_vulnerability_count.png",
        ylabel="Proportion of vulnerable library releases",
        legend_title="Vulnerabilities per release",
        colors=VERSION_BUCKET_COLORS,
        release_denominators=maven_release_denominators,
    )

    plot_stacked_bar(
        pivot=vulnerabilities_pivot,
        bucket_order=VULN_BUCKET_ORDER,
        output_dir=rq2_output_dir,
        filename="rq2_vulnerabilities_by_affected_release_count.png",
        title="",
        ylabel="Number of vulnerabilities",
        legend_title="Affected releases per vulnerability",
        colors=VULN_BUCKET_COLORS
    )

    logging.info("Geração dos gráficos empilhados concluída.")


if __name__ == "__main__":
    main()
