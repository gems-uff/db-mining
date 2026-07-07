#!/usr/bin/env python3
import argparse
import re
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.path import Path as MplPath
from matplotlib.projections import register_projection
from matplotlib.projections.polar import PolarAxes
from matplotlib.spines import Spine
from matplotlib.transforms import Affine2D
import numpy as np
import pandas as pd


METRIC_COLUMNS = [
    "vulnerable_releases_pct",
    "propagation_pct",
    "project_exposure_pct",
    "post_resolution_persistence_pct",
    "post_resolution_lifetime_exposure_pct",
]

RADAR_LABELS = ["RQ1a", "RQ1b", "RQ3", "RQ4", "RQ5"]

RADAR_LEGEND_TEXT = (
    "RQ1a: vulnerable library releases | "
    "RQ1b: long-propagation vulnerabilities | "
    "RQ3: project exposure | "
    "RQ4: post-resolution persistence | "
    "RQ5: post-resolution exposure"
)

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


def calculate_post_resolution_lifetime_exposure(vulnerable_usage, project_lifetimes):
    """
    Post-resolution Project Lifetime Exposure:
    Para cada par (projeto, DBMS):
      post_resolution_exposure_days / project_lifetime_days * 100

    Depois agrega por DBMS usando a mediana.
    Intervalos sobrepostos no mesmo par (projeto, DBMS) são mesclados antes
    da soma para evitar dupla contagem.
    """
    df = vulnerable_usage.dropna(
        subset=["db", "project_id", "date_commit", "resolved_at"]
    ).copy()

    raw_intervals = (
        df.groupby(
            ["db", "project_id", "file", "version_number", "purl", "cve", "resolved_at"],
            dropna=False,
        )
        .agg(usage_start=("date_commit", "min"), usage_end=("date_commit", "max"))
        .reset_index()
    )
    raw_intervals["post_resolution_start"] = raw_intervals[
        ["usage_start", "resolved_at"]
    ].max(axis=1)
    raw_intervals = raw_intervals[
        raw_intervals["usage_end"] > raw_intervals["post_resolution_start"]
    ].copy()

    project_lifetimes = project_lifetimes.copy()
    project_lifetimes["project_lifetime_days"] = (
        project_lifetimes["last_observed_commit_date"]
        - project_lifetimes["first_observed_commit_date"]
    ).dt.days

    records = []
    for (db, project_id), group in raw_intervals.groupby(["db", "project_id"]):
        intervals = [
            (row.post_resolution_start, row.usage_end)
            for row in group.itertuples(index=False)
            if pd.notna(row.post_resolution_start) and pd.notna(row.usage_end)
        ]
        merged = merge_intervals(intervals)
        exposure_days = interval_days(merged)
        records.append(
            {
                "db": db,
                "project_id": project_id,
                "post_resolution_exposure_days": exposure_days,
            }
        )

    exposure = pd.DataFrame(records)
    if exposure.empty:
        return pd.DataFrame(columns=["db", "post_resolution_lifetime_exposure_pct"])

    exposure = exposure.merge(
        project_lifetimes[["project_id", "project_lifetime_days"]],
        on="project_id",
        how="left",
    )
    exposure = exposure[exposure["project_lifetime_days"] > 0].copy()
    exposure["post_resolution_lifetime_exposure_pct"] = (
        exposure["post_resolution_exposure_days"]
        / exposure["project_lifetime_days"]
        * 100
    )
    exposure["post_resolution_lifetime_exposure_pct"] = exposure[
        "post_resolution_lifetime_exposure_pct"
    ].clip(0, 100)

    result = (
        exposure.groupby("db")["post_resolution_lifetime_exposure_pct"]
        .median()
        .reset_index(name="post_resolution_lifetime_exposure_pct")
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
        calculate_post_resolution_lifetime_exposure(vulnerable_usage, project_lifetimes),
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


def register_pentagonal_radar_projection():
    theta = np.linspace(0, 2 * np.pi, len(METRIC_COLUMNS), endpoint=False)

    class RadarTransform(PolarAxes.PolarTransform):
        def transform_path_non_affine(self, path):
            if path._interpolation_steps > 1:
                path = path.interpolated(len(METRIC_COLUMNS))
            return MplPath(self.transform(path.vertices), path.codes)

    class RadarAxes(PolarAxes):
        name = "radar_pentagonal"
        PolarTransform = RadarTransform

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.set_theta_zero_location("N")

        def fill(self, *args, closed=True, **kwargs):
            return super().fill(closed=closed, *args, **kwargs)

        def plot(self, *args, **kwargs):
            lines = super().plot(*args, **kwargs)
            for line in lines:
                x, y = line.get_data()
                if x[0] != x[-1]:
                    line.set_data(np.append(x, x[0]), np.append(y, y[0]))
            return lines

        def set_varlabels(self, labels, fontsize=9):
            self.set_thetagrids(np.degrees(theta), labels, fontsize=fontsize)

        def _gen_axes_patch(self):
            return plt.Polygon(
                self._unit_poly_verts(theta),
                closed=True,
                edgecolor="black",
            )

        def _gen_axes_spines(self):
            spine = Spine(
                axes=self,
                spine_type="circle",
                path=MplPath.unit_regular_polygon(len(METRIC_COLUMNS)),
            )
            spine.set_transform(
                Affine2D().scale(0.5).translate(0.5, 0.5) + self.transAxes
            )
            return {"polar": spine}

        @staticmethod
        def _unit_poly_verts(theta_values):
            x0, y0, r = [0.5] * 3
            return [
                (r * np.cos(t) + x0, r * np.sin(t) + y0)
                for t in theta_values
            ]

    register_projection(RadarAxes)
    return theta


PENTAGONAL_ANGLES = register_pentagonal_radar_projection()


def setup_radar_axis(ax):
    angles = radar_angles()
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(RADAR_LABELS, fontsize=9)
    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20", "40", "60", "80", "100"], fontsize=8)
    ax.grid(True, alpha=0.35)


def setup_pentagonal_radar_axis(ax, label_fontsize=9, radial_fontsize=8):
    ax.set_varlabels(RADAR_LABELS, fontsize=label_fontsize)
    ax.set_ylim(0, 100)
    ax.set_rgrids([20, 40, 60, 80, 100], angle=90, fontsize=radial_fontsize)
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


def generate_small_multiples_radar(df, output_dir):
    plot_df = df.copy()
    if plot_df.empty:
        return

    n_cols = 5
    n_rows = int(np.ceil(len(plot_df) / n_cols))
    angles = radar_angles()

    fig, axes = plt.subplots(
        n_rows,
        n_cols,
        figsize=(n_cols * 2.45, n_rows * 2.65),
        subplot_kw={"projection": "polar"},
    )
    axes = np.asarray(axes).reshape(-1)

    for ax, (_, row) in zip(axes, plot_df.iterrows()):
        values = row[METRIC_COLUMNS].astype(float).to_numpy()
        values = np.concatenate([values, values[:1]])

        setup_radar_axis(ax)
        ax.set_xticklabels(RADAR_LABELS, fontsize=8)
        ax.set_yticks([50, 100])
        ax.set_yticklabels(["50", "100"], fontsize=6)
        ax.plot(angles, values, linewidth=1.4, color="#1c4587")
        ax.fill(angles, values, alpha=0.22, color="#6fa8dc")
        ax.set_title(row["db"], fontsize=10, pad=10)

    for ax in axes[len(plot_df):]:
        ax.set_visible(False)

    fig.suptitle("Post-resolution vulnerability profiles by DBMS", fontsize=16, y=0.99)
    fig.text(
        0.5,
        0.015,
        RADAR_LEGEND_TEXT,
        ha="center",
        va="bottom",
        fontsize=9,
    )
    fig.tight_layout(rect=[0, 0.05, 1, 0.96])

    for ext in ("png", "pdf"):
        fig.savefig(
            Path(output_dir) / f"radar_mini_radares_dbms_pos_resolucao.{ext}",
            dpi=300,
            bbox_inches="tight",
        )
    plt.close(fig)


def generate_small_multiples_pentagonal_radar(df, output_dir):
    plot_df = df.copy()
    if plot_df.empty:
        return

    n_cols = 5
    n_rows = int(np.ceil(len(plot_df) / n_cols))

    fig, axes = plt.subplots(
        n_rows,
        n_cols,
        figsize=(n_cols * 2.45, n_rows * 2.65),
        subplot_kw={"projection": "radar_pentagonal"},
    )
    axes = np.asarray(axes).reshape(-1)

    for ax, (_, row) in zip(axes, plot_df.iterrows()):
        values = row[METRIC_COLUMNS].astype(float).to_numpy()

        setup_pentagonal_radar_axis(ax, label_fontsize=8, radial_fontsize=6)
        ax.set_rgrids([50, 100], angle=90, fontsize=6)
        ax.plot(PENTAGONAL_ANGLES, values, linewidth=1.4, color="#1c4587")
        ax.fill(PENTAGONAL_ANGLES, values, alpha=0.22, color="#6fa8dc")
        ax.set_title(row["db"], fontsize=10, pad=10)

    for ax in axes[len(plot_df):]:
        ax.set_visible(False)

    fig.suptitle("Post-resolution vulnerability profiles by DBMS", fontsize=16, y=0.99)
    fig.text(
        0.5,
        0.015,
        RADAR_LEGEND_TEXT,
        ha="center",
        va="bottom",
        fontsize=9,
    )
    fig.tight_layout(rect=[0, 0.05, 1, 0.96])

    for ext in ("png", "pdf"):
        fig.savefig(
            Path(output_dir)
            / f"radar_mini_radares_dbms_pos_resolucao_pentagonal.{ext}",
            dpi=300,
            bbox_inches="tight",
        )
    plt.close(fig)


def generate_comparative_radar(df, output_dir):
    plot_df = df.copy()
    if plot_df.empty:
        return

    angles = radar_angles()
    fig, ax = plt.subplots(figsize=(9, 9), subplot_kw={"projection": "polar"})
    setup_radar_axis(ax)

    cmap = plt.get_cmap("tab20")
    for idx, row in plot_df.reset_index(drop=True).iterrows():
        values = row[METRIC_COLUMNS].astype(float).to_numpy()
        values = np.concatenate([values, values[:1]])
        color = cmap(idx % 20)
        ax.plot(angles, values, linewidth=1.5, label=row["db"], color=color)
        ax.fill(angles, values, alpha=0.04, color=color)

    ax.set_title("Comparative post-resolution vulnerability profile for DBMSs", pad=24)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=5, frameon=True)

    for ext in ("png", "pdf"):
        fig.savefig(
            Path(output_dir) / f"radar_comparativo_principais_dbms_pos_resolucao.{ext}",
            dpi=300,
            bbox_inches="tight",
        )
    plt.close(fig)


def generate_comparative_pentagonal_radar(df, output_dir):
    plot_df = df.copy()
    if plot_df.empty:
        return

    fig, ax = plt.subplots(figsize=(9, 9), subplot_kw={"projection": "radar_pentagonal"})
    setup_pentagonal_radar_axis(ax)

    cmap = plt.get_cmap("tab20")
    for idx, row in plot_df.reset_index(drop=True).iterrows():
        values = row[METRIC_COLUMNS].astype(float).to_numpy()
        color = cmap(idx % 20)
        ax.plot(PENTAGONAL_ANGLES, values, linewidth=1.5, label=row["db"], color=color)
        ax.fill(PENTAGONAL_ANGLES, values, alpha=0.04, color=color)

    ax.set_title("Comparative post-resolution vulnerability profile for DBMSs", pad=24)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=5, frameon=True)

    for ext in ("png", "pdf"):
        fig.savefig(
            Path(output_dir)
            / f"radar_comparativo_principais_dbms_pos_resolucao_pentagonal.{ext}",
            dpi=300,
            bbox_inches="tight",
        )
    plt.close(fig)


def generate_all_radars(df, output_dir):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    generate_small_multiples_radar(df, output_path)


def cleanup_previous_radars(output_dir):
    output_path = Path(output_dir)
    if not output_path.exists():
        return

    patterns = [
        "radar_individual_*.png",
        "radar_individual_*.pdf",
        "radar_mini_radares_dbms.png",
        "radar_mini_radares_dbms.pdf",
        "radar_mini_radares_dbms_pos_resolucao.png",
        "radar_mini_radares_dbms_pos_resolucao.pdf",
        "radar_mini_radares_dbms_pentagonal.png",
        "radar_mini_radares_dbms_pentagonal.pdf",
        "radar_mini_radares_dbms_pos_resolucao_pentagonal.png",
        "radar_mini_radares_dbms_pos_resolucao_pentagonal.pdf",
        "radar_comparativo_principais_dbms.png",
        "radar_comparativo_principais_dbms.pdf",
        "radar_comparativo_principais_dbms_pos_resolucao.png",
        "radar_comparativo_principais_dbms_pos_resolucao.pdf",
        "radar_comparativo_principais_dbms_pentagonal.png",
        "radar_comparativo_principais_dbms_pentagonal.pdf",
        "radar_comparativo_principais_dbms_pos_resolucao_pentagonal.png",
        "radar_comparativo_principais_dbms_pos_resolucao_pentagonal.pdf",
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
    parser.add_argument("--output-dir", default="graficos_discussão")
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
