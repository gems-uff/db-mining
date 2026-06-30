#!/usr/bin/env python3
import argparse
import re
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


METRIC_COLUMNS = [
    "vulnerable_releases_pct",
    "propagation_pct",
    "project_exposure_pct",
    "post_resolution_persistence_pct",
    "project_lifetime_exposure_pct",
]

RADAR_LABELS = [
    "Vulnerable releases",
    "Propagation",
    "Project exposure",
    "Post-resolution",
    "Lifetime exposure",
]

MAIN_DBMS = [
    "H2",
    "MySQL",
    "PostgreSQL",
    "Redis",
    "SQLite",
    "HyperSQL",
    "Hazelcast",
    "MongoDB",
]

DEFAULT_TARGET_DBMS = [
    "MySQL",
    "Redis",
    "PostgreSQL",
    "Snowflake",
    "H2",
    "Hazelcast",
    "SQLite",
    "HyperSQL",
    "MSSQL/MicrosoftAzure",
    "Cassandra",
    "Ignite",
    "MongoDB",
    "Couchbase",
    "Neo4j",
    "HBase",
]

DB_DISPLAY_REPLACEMENTS = {
    "MS SQL Server_Microsoft Azure SQL Database": "MSSQL/MicrosoftAzure",
}


def sqlite_uri(path):
    return f"file:{Path(path).resolve()}?mode=ro&immutable=1"


def normalize_db_name(series):
    return series.replace(DB_DISPLAY_REPLACEMENTS)


def sanitize_filename(value):
    clean = re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_").lower()
    return clean or "unknown"


def parse_datetime_utc_naive(series):
    return pd.to_datetime(series, errors="coerce", utc=True).dt.tz_localize(None)


def load_data(db_path):
    """
    Carrega os dados primários do SQLite.

    O schema real do banco possui:
    - label: nomes dos DBMSs;
    - heuristic: ligação entre label/DBMS e execução;
    - execution: execução de heurística em um commit;
    - version: commits observados por projeto;
    - version_vulnerability: ocorrências de dependências DBMS-related;
    - vulnerability: CVEs por pacote/versão vulnerável.
    """
    conn = sqlite3.connect(sqlite_uri(db_path), uri=True)

    all_usage = pd.read_sql_query(
        """
        SELECT
            l.name AS db,
            ver.project_id AS project_id,
            vv.version_id AS version_id,
            ver.date_commit AS date_commit,
            vv.versionNumber AS version_number,
            vv.file AS file,
            vv.purl AS purl
        FROM version_vulnerability vv
        JOIN version ver ON ver.id = vv.version_id
        JOIN execution e ON e.id = vv.execution_id
        JOIN heuristic h ON h.id = e.heuristic_id
        JOIN label l ON l.id = h.label_id
        WHERE l.type = 'vulnerabilities'
        """,
        conn,
    )

    vulnerable_usage = pd.read_sql_query(
        """
        SELECT
            l.name AS db,
            ver.project_id AS project_id,
            vv.version_id AS version_id,
            ver.date_commit AS date_commit,
            vv.versionNumber AS version_number,
            vv.file AS file,
            vv.purl AS purl,
            vul.reference AS cve,
            vul.version AS vulnerable_version,
            vul.resolved_at AS resolved_at
        FROM version_vulnerability vv
        JOIN version ver ON ver.id = vv.version_id
        JOIN execution e ON e.id = vv.execution_id
        JOIN heuristic h ON h.id = e.heuristic_id
        JOIN label l ON l.id = h.label_id
        JOIN vulnerability vul
            ON vul.purl = vv.purl
           AND vul.label_id = h.label_id
        WHERE l.type = 'vulnerabilities'
        """,
        conn,
    )

    vulnerability_versions = pd.read_sql_query(
        """
        SELECT
            l.name AS db,
            vul.reference AS cve,
            vul.version AS vulnerable_version
        FROM vulnerability vul
        JOIN label l ON l.id = vul.label_id
        WHERE l.type = 'vulnerabilities'
          AND vul.reference IS NOT NULL
          AND TRIM(vul.reference) <> ''
        """,
        conn,
    )

    project_lifetimes = pd.read_sql_query(
        """
        SELECT
            project_id,
            MIN(date_commit) AS first_observed_commit_date,
            MAX(date_commit) AS last_observed_commit_date
        FROM version
        WHERE date_commit IS NOT NULL
        GROUP BY project_id
        """,
        conn,
    )

    conn.close()

    for df in (all_usage, vulnerable_usage, vulnerability_versions):
        df["db"] = normalize_db_name(df["db"])

    all_usage["date_commit"] = parse_datetime_utc_naive(all_usage["date_commit"])
    vulnerable_usage["date_commit"] = parse_datetime_utc_naive(
        vulnerable_usage["date_commit"]
    )
    vulnerable_usage["resolved_at"] = parse_datetime_utc_naive(
        vulnerable_usage["resolved_at"]
    )
    project_lifetimes["first_observed_commit_date"] = parse_datetime_utc_naive(
        project_lifetimes["first_observed_commit_date"]
    )
    project_lifetimes["last_observed_commit_date"] = parse_datetime_utc_naive(
        project_lifetimes["last_observed_commit_date"]
    )

    return all_usage, vulnerable_usage, vulnerability_versions, project_lifetimes


def load_maven_release_counts(path):
    """
    Carrega o denominador de releases Maven.

    O SQLite inspecionado não possui uma tabela de metadados Maven Central.
    Por isso, esta métrica usa o CSV derivado do projeto como fonte do
    denominador total_releases_maven.
    """
    maven_path = Path(path)
    if not maven_path.exists():
        return pd.DataFrame(columns=["db", "total_releases_maven"])

    df = pd.read_csv(maven_path)
    if "maven_central_distinct_versions_family" in df.columns:
        total_col = "maven_central_distinct_versions_family"
    elif "maven_central_metadata_releases_total" in df.columns:
        total_col = "maven_central_metadata_releases_total"
    else:
        raise ValueError(
            "CSV Maven precisa conter 'maven_central_distinct_versions_family' "
            "ou 'maven_central_metadata_releases_total'."
        )

    result = df[["db", total_col]].copy()
    result["db"] = normalize_db_name(result["db"].astype(str).str.strip())
    result = result.rename(columns={total_col: "total_releases_maven"})
    result["total_releases_maven"] = pd.to_numeric(
        result["total_releases_maven"], errors="coerce"
    ).fillna(0)
    return result


def load_target_dbms(path):
    """
    Define quais DBMSs entram nos radares.

    Por padrão, reutiliza a lista do gráfico
    rq1_release_cve_resolution_distribution_by_dbms, isto é, apenas os DBMSs
    com registros DBMS-release-CVE no recorte de resolução.
    """
    filter_path = Path(path)
    if not filter_path.exists():
        return DEFAULT_TARGET_DBMS

    df = pd.read_csv(filter_path)
    if "db" not in df.columns:
        return DEFAULT_TARGET_DBMS

    dbms = normalize_db_name(df["db"]).dropna().astype(str).str.strip()
    dbms = [db for db in dbms if db]
    return dbms or DEFAULT_TARGET_DBMS


def calculate_vulnerable_releases(vulnerable_usage, maven_counts):
    """
    Vulnerable Releases:
    distinct_vulnerable_releases / total_releases_maven * 100
    """
    vulnerable_releases = (
        vulnerable_usage.dropna(subset=["db", "version_number"])
        .groupby("db")["version_number"]
        .nunique()
        .reset_index(name="distinct_vulnerable_releases")
    )

    result = vulnerable_releases.merge(maven_counts, on="db", how="left")
    result["total_releases_maven"] = result["total_releases_maven"].fillna(0)
    result["vulnerable_releases_pct"] = np.where(
        result["total_releases_maven"] > 0,
        result["distinct_vulnerable_releases"] / result["total_releases_maven"] * 100,
        0,
    )
    return result[["db", "vulnerable_releases_pct"]]


def calculate_propagation(vulnerability_versions):
    """
    Propagation:
    long_propagation_cves / total_distinct_cves * 100

    Uma CVE é considerada de longa propagação quando afeta 20 ou mais releases.
    """
    per_cve = (
        vulnerability_versions.dropna(subset=["db", "cve"])
        .groupby(["db", "cve"])["vulnerable_version"]
        .nunique()
        .reset_index(name="affected_releases")
    )
    per_cve["is_long_propagation"] = per_cve["affected_releases"] >= 20

    result = (
        per_cve.groupby("db")
        .agg(
            total_distinct_cves=("cve", "nunique"),
            long_propagation_cves=("is_long_propagation", "sum"),
        )
        .reset_index()
    )
    result["propagation_pct"] = np.where(
        result["total_distinct_cves"] > 0,
        result["long_propagation_cves"] / result["total_distinct_cves"] * 100,
        0,
    )
    return result[["db", "propagation_pct"]]


def calculate_project_exposure(all_usage, vulnerable_usage):
    """
    Project Exposure:
    exposed_projects / total_projects_using_dbms * 100
    """
    total_projects = (
        all_usage.dropna(subset=["db", "project_id"])
        .groupby("db")["project_id"]
        .nunique()
        .reset_index(name="total_projects_using_dbms")
    )
    exposed_projects = (
        vulnerable_usage.dropna(subset=["db", "project_id"])
        .groupby("db")["project_id"]
        .nunique()
        .reset_index(name="exposed_projects")
    )

    result = total_projects.merge(exposed_projects, on="db", how="left")
    result["exposed_projects"] = result["exposed_projects"].fillna(0)
    result["project_exposure_pct"] = np.where(
        result["total_projects_using_dbms"] > 0,
        result["exposed_projects"] / result["total_projects_using_dbms"] * 100,
        0,
    )
    return result[["db", "project_exposure_pct"]]


def calculate_post_resolution_persistence(vulnerable_usage):
    """
    Post Resolution Persistence:
    vulnerable_commits_after_resolution / total_vulnerable_commits * 100

    A unidade de commit vulnerável é deduplicada por (db, project_id, version_id).
    Um commit entra no numerador se ao menos uma CVE associada já possuía
    resolved_at <= date_commit.
    """
    df = vulnerable_usage.dropna(subset=["db", "project_id", "version_id", "date_commit"]).copy()
    df["after_resolution"] = (
        df["resolved_at"].notna() & (df["date_commit"] >= df["resolved_at"])
    )

    per_commit = (
        df.groupby(["db", "project_id", "version_id"], as_index=False)
        .agg(after_resolution=("after_resolution", "max"))
    )

    result = (
        per_commit.groupby("db")
        .agg(
            total_vulnerable_commits=("version_id", "size"),
            vulnerable_commits_after_resolution=("after_resolution", "sum"),
        )
        .reset_index()
    )
    result["post_resolution_persistence_pct"] = np.where(
        result["total_vulnerable_commits"] > 0,
        result["vulnerable_commits_after_resolution"]
        / result["total_vulnerable_commits"]
        * 100,
        0,
    )
    return result[["db", "post_resolution_persistence_pct"]]


def merge_intervals(intervals):
    if not intervals:
        return []

    ordered = sorted(intervals, key=lambda item: item[0])
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        previous_start, previous_end = merged[-1]
        if start <= previous_end:
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def interval_days(intervals):
    return sum(max((end - start).days, 0) for start, end in intervals)


def calculate_project_lifetime_exposure(vulnerable_usage, project_lifetimes):
    """
    Project Lifetime Exposure:
    Para cada par (projeto, DBMS):
      vulnerable_exposure_days / project_lifetime_days * 100

    Depois agrega por DBMS usando a mediana.
    Intervalos sobrepostos no mesmo par (projeto, DBMS) são mesclados antes
    da soma para evitar dupla contagem.
    """
    df = vulnerable_usage.dropna(subset=["db", "project_id", "date_commit"]).copy()

    raw_intervals = (
        df.groupby(["db", "project_id", "file", "version_number", "purl"], dropna=False)
        .agg(start=("date_commit", "min"), end=("date_commit", "max"))
        .reset_index()
    )

    project_lifetimes = project_lifetimes.copy()
    project_lifetimes["project_lifetime_days"] = (
        project_lifetimes["last_observed_commit_date"]
        - project_lifetimes["first_observed_commit_date"]
    ).dt.days

    records = []
    for (db, project_id), group in raw_intervals.groupby(["db", "project_id"]):
        intervals = [
            (row.start, row.end)
            for row in group.itertuples(index=False)
            if pd.notna(row.start) and pd.notna(row.end)
        ]
        merged = merge_intervals(intervals)
        exposure_days = interval_days(merged)
        records.append(
            {
                "db": db,
                "project_id": project_id,
                "vulnerable_exposure_days": exposure_days,
            }
        )

    exposure = pd.DataFrame(records)
    if exposure.empty:
        return pd.DataFrame(columns=["db", "project_lifetime_exposure_pct"])

    exposure = exposure.merge(
        project_lifetimes[["project_id", "project_lifetime_days"]],
        on="project_id",
        how="left",
    )
    exposure = exposure[exposure["project_lifetime_days"] > 0].copy()
    exposure["exposure_lifetime_pct"] = (
        exposure["vulnerable_exposure_days"] / exposure["project_lifetime_days"] * 100
    )
    exposure["exposure_lifetime_pct"] = exposure["exposure_lifetime_pct"].clip(0, 100)

    result = (
        exposure.groupby("db")["exposure_lifetime_pct"]
        .median()
        .reset_index(name="project_lifetime_exposure_pct")
    )
    return result


def build_final_table(
    all_usage,
    vulnerable_usage,
    vulnerability_versions,
    project_lifetimes,
    maven_counts,
    target_dbms,
):
    metrics = [
        calculate_vulnerable_releases(vulnerable_usage, maven_counts),
        calculate_propagation(vulnerability_versions),
        calculate_project_exposure(all_usage, vulnerable_usage),
        calculate_post_resolution_persistence(vulnerable_usage),
        calculate_project_lifetime_exposure(vulnerable_usage, project_lifetimes),
    ]

    dbs = pd.DataFrame({"db": target_dbms, "target_order": range(len(target_dbms))})
    final = dbs
    for metric in metrics:
        final = final.merge(metric, on="db", how="left")

    final[METRIC_COLUMNS] = final[METRIC_COLUMNS].fillna(0).clip(lower=0, upper=100)
    return final.sort_values("target_order").drop(columns=["target_order"])


def radar_angles():
    angles = np.linspace(0, 2 * np.pi, len(METRIC_COLUMNS), endpoint=False)
    return np.concatenate([angles, angles[:1]])


def setup_radar_axis(ax):
    angles = radar_angles()
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(RADAR_LABELS, fontsize=9)
    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20", "40", "60", "80", "100"], fontsize=8)
    ax.grid(True, alpha=0.35)


def generate_individual_radar(row, output_dir):
    values = row[METRIC_COLUMNS].astype(float).to_numpy()
    values = np.concatenate([values, values[:1]])
    angles = radar_angles()

    fig, ax = plt.subplots(figsize=(6.5, 6.5), subplot_kw={"projection": "polar"})
    setup_radar_axis(ax)
    ax.plot(angles, values, linewidth=2, color="#1c4587")
    ax.fill(angles, values, alpha=0.25, color="#6fa8dc")
    ax.set_title(f"Vulnerability profile for {row['db']}", pad=20)

    stem = f"radar_individual_{sanitize_filename(row['db'])}"
    for ext in ("png", "pdf"):
        fig.savefig(Path(output_dir) / f"{stem}.{ext}", dpi=300, bbox_inches="tight")
    plt.close(fig)


def generate_comparative_radar(df, output_dir, dbms=MAIN_DBMS):
    plot_df = df[df["db"].isin(dbms)].copy()
    if plot_df.empty:
        return

    angles = radar_angles()
    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw={"projection": "polar"})
    setup_radar_axis(ax)

    cmap = plt.get_cmap("tab10")
    for idx, row in plot_df.set_index("db").loc[[db for db in dbms if db in set(plot_df["db"])]].reset_index().iterrows():
        values = row[METRIC_COLUMNS].astype(float).to_numpy()
        values = np.concatenate([values, values[:1]])
        color = cmap(idx % 10)
        ax.plot(angles, values, linewidth=1.8, label=row["db"], color=color)
        ax.fill(angles, values, alpha=0.08, color=color)

    ax.set_title("Comparative vulnerability profile for main DBMSs", pad=24)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=3, frameon=True)

    for ext in ("png", "pdf"):
        fig.savefig(
            Path(output_dir) / f"radar_comparativo_principais_dbms.{ext}",
            dpi=300,
            bbox_inches="tight",
        )
    plt.close(fig)


def generate_all_radars(df, output_dir):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for _, row in df.iterrows():
        generate_individual_radar(row, output_path)

    generate_comparative_radar(df, output_path)


def cleanup_previous_radars(output_dir):
    output_path = Path(output_dir)
    if not output_path.exists():
        return

    patterns = [
        "radar_individual_*.png",
        "radar_individual_*.pdf",
        "radar_comparativo_principais_dbms.png",
        "radar_comparativo_principais_dbms.pdf",
    ]
    for pattern in patterns:
        for path in output_path.glob(pattern):
            path.unlink()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Gera gráficos de radar com métricas percentuais de vulnerabilidade por DBMS."
    )
    parser.add_argument("--db-path", default="dbmining.sqlite")
    parser.add_argument(
        "--maven-counts",
        default="rqs_data/maven_family_version_counts_by_dbms.csv",
        help="CSV com total de releases Maven por DBMS.",
    )
    parser.add_argument(
        "--dbms-filter",
        default="rqs_data/rq1_release_cve_resolution_buckets_by_dbms.csv",
        help="CSV com coluna db indicando os DBMSs que devem entrar nos radares.",
    )
    parser.add_argument("--output-dir", default="output")
    return parser.parse_args()


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_usage, vulnerable_usage, vulnerability_versions, project_lifetimes = load_data(
        args.db_path
    )
    maven_counts = load_maven_release_counts(args.maven_counts)
    target_dbms = load_target_dbms(args.dbms_filter)

    final = build_final_table(
        all_usage,
        vulnerable_usage,
        vulnerability_versions,
        project_lifetimes,
        maven_counts,
        target_dbms,
    )

    cleanup_previous_radars(output_dir)
    final.to_csv(output_dir / "radar_dbms_metrics.csv", index=False)
    generate_all_radars(final, output_dir)

    print(f"Saved metrics and radar charts to {output_dir}")


if __name__ == "__main__":
    main()
