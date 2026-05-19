#!/usr/bin/env python3
import argparse
import logging
import sqlite3
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

DEFAULT_DB_CANDIDATES = [
    "dbmining.sqlite",
    "dbmining.slite",
]

DEFAULT_OUTPUT_NAME = "resultado_rqs.xlsx"
DEFAULT_CSV_OUTPUT_DIR = "rqs_data"


def normalize_text(series: pd.Series) -> pd.Series:
    return (
        series.astype("string")
        .str.strip()
        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "NaN": pd.NA})
    )


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,)
    )
    return cur.fetchone() is not None


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    return {row[1] for row in rows}


def pick_first_existing(columns: set[str], candidates: Sequence[str]) -> Optional[str]:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def ensure_output_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_csv_required(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {path}")
    return pd.read_csv(path)


def resolve_default_db_path() -> Path:
    cwd = Path.cwd()

    for filename in DEFAULT_DB_CANDIDATES:
        candidate = cwd / filename
        if candidate.exists():
            return candidate

    for filename in DEFAULT_DB_CANDIDATES:
        matches = list(cwd.rglob(filename))
        if matches:
            return matches[0]

    searched = ", ".join(DEFAULT_DB_CANDIDATES)
    raise FileNotFoundError(
        f"Não encontrei o banco automaticamente. Procurei por: {searched}. "
        f"Diretório inicial da busca: {cwd}"
    )


def resolve_output_path(user_output: Optional[str]) -> Path:
    if user_output:
        return Path(user_output)
    return Path.cwd() / DEFAULT_OUTPUT_NAME


def build_base_history_query(conn: sqlite3.Connection) -> str:
    required_tables = [
        "project",
        "version",
        "version_vulnerability",
        "execution",
        "heuristic",
        "label",
        "vulnerability",
    ]
    for table_name in required_tables:
        if not table_exists(conn, table_name):
            raise ValueError(f"Tabela obrigatória ausente: {table_name}")

    vuln_cols = get_table_columns(conn, "vulnerability")

    published_col = pick_first_existing(vuln_cols, ["published_at", "publishedAt"])
    last_modified_col = pick_first_existing(vuln_cols, ["last_modified_at", "last_modified", "lastModifiedAt"])
    cvss_score_col = pick_first_existing(vuln_cols, ["cvss_score", "cvssScore"])
    cvss_severity_col = pick_first_existing(vuln_cols, ["cvss_severity", "cvssSeverity"])
    cvss_vector_col = pick_first_existing(vuln_cols, ["cvss_vector", "cvssVector"])
    purl_col = pick_first_existing(vuln_cols, ["purl"])

    select_optional = []
    if published_col:
        select_optional.append(f"vuln.{published_col} AS published_at")
    else:
        select_optional.append("NULL AS published_at")

    if last_modified_col:
        select_optional.append(f"vuln.{last_modified_col} AS last_modified_at")
    else:
        select_optional.append("NULL AS last_modified_at")

    if cvss_score_col:
        select_optional.append(f"vuln.{cvss_score_col} AS cvss_score")
    else:
        select_optional.append("NULL AS cvss_score")

    if cvss_severity_col:
        select_optional.append(f"vuln.{cvss_severity_col} AS cvss_severity")
    else:
        select_optional.append("NULL AS cvss_severity")

    if cvss_vector_col:
        select_optional.append(f"vuln.{cvss_vector_col} AS cvss_vector")
    else:
        select_optional.append("NULL AS cvss_vector")

    if purl_col:
        select_optional.append(f"vuln.{purl_col} AS vuln_purl")
    else:
        select_optional.append("NULL AS vuln_purl")

    optional_sql = ",\n       ".join(select_optional)

    query = f"""
    SELECT
        p.id AS project_id,
        p.name AS project_name,
        v.id AS version_id,
        v.sha1 AS sha1,
        v.date_commit AS date_commit,
        vv.id AS version_vulnerability_id,
        vv.file AS file,
        vv.versionNumber AS versionNumber,
        vv.commitsBetween AS commitsBetween,
        e.id AS execution_id,
        h.id AS heuristic_id,
        h.pattern AS heuristic_pattern,
        l.id AS label_id,
        l.name AS db_name,
        l.type AS label_type,
        vuln.id AS vulnerability_id,
        vuln.name AS vulnerability_name,
        vuln.status AS vulnerability_status,
        vuln.description AS vulnerability_description,
        vuln.reference AS reference,
        vuln.version AS vulnerable_version,
        {optional_sql}
    FROM version_vulnerability vv
    JOIN version v
      ON v.id = vv.version_id
    JOIN project p
      ON p.id = v.project_id
    LEFT JOIN execution e
      ON e.id = vv.execution_id
    LEFT JOIN heuristic h
      ON h.id = e.heuristic_id
    LEFT JOIN label l
      ON l.id = h.label_id
    LEFT JOIN vulnerability vuln
      ON vuln.label_id = l.id
     AND TRIM(LOWER(vuln.version)) = TRIM(LOWER(vv.versionNumber))
    """
    return query


def load_base_dataframe(conn: sqlite3.Connection) -> pd.DataFrame:
    query = build_base_history_query(conn)
    df = pd.read_sql_query(query, conn)

    text_cols = [
        "project_name",
        "sha1",
        "file",
        "versionNumber",
        "heuristic_pattern",
        "db_name",
        "label_type",
        "vulnerability_name",
        "vulnerability_status",
        "vulnerability_description",
        "reference",
        "vulnerable_version",
        "vuln_purl",
    ]
    for col in text_cols:
        if col in df.columns:
            df[col] = normalize_text(df[col])

    date_cols = ["date_commit", "published_at", "last_modified_at"]
    for col in date_cols:
        if col in df.columns:
            df[col] = (
            pd.to_datetime(df[col], errors="coerce", utc=True)
            .dt.tz_localize(None)
        )

    num_cols = [
        "project_id",
        "version_id",
        "version_vulnerability_id",
        "execution_id",
        "heuristic_id",
        "label_id",
        "vulnerability_id",
        "commitsBetween",
        "cvss_score",
    ]
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["project_name", "versionNumber", "date_commit"]).copy()
    df["db_name"] = normalize_text(df["db_name"]).fillna("UNKNOWN_DB")
    df["is_vulnerable"] = df["vulnerability_id"].notna()

    df = df.sort_values(
        ["project_id", "project_name", "file", "db_name", "date_commit", "sha1", "version_id", "vulnerability_id"],
        kind="mergesort"
    ).reset_index(drop=True)

    return df


def deduplicate_history_for_segments(base_df: pd.DataFrame) -> pd.DataFrame:
    subset_cols = [
        "project_id",
        "project_name",
        "file",
        "db_name",
        "version_id",
        "sha1",
        "date_commit",
        "versionNumber",
    ]
    dedup = base_df[subset_cols].drop_duplicates().copy()

    dedup = dedup.sort_values(
        ["project_id", "project_name", "file", "db_name", "date_commit", "sha1", "version_id"],
        kind="mergesort"
    ).reset_index(drop=True)

    return dedup


def build_segments_for_group(sub: pd.DataFrame) -> pd.DataFrame:
    sub = sub.sort_values(["date_commit", "sha1", "version_id"], kind="mergesort").copy()

    sub["prev_version"] = sub["versionNumber"].shift(1)
    sub["is_change"] = sub["prev_version"].isna() | (sub["versionNumber"] != sub["prev_version"])
    sub["segment_id"] = sub["is_change"].cumsum()

    seg = (
        sub.groupby("segment_id", dropna=False)
        .agg(
            project_id=("project_id", "first"),
            project=("project_name", "first"),
            file=("file", "first"),
            db=("db_name", "first"),
            versionNumber=("versionNumber", "first"),
            start_date=("date_commit", "min"),
            last_seen_date=("date_commit", "max"),
            commits=("sha1", "nunique"),
            rows=("version_id", "count"),
        )
        .reset_index(drop=True)
    )

    seg["next_start_date"] = seg["start_date"].shift(-1)
    seg["end_date"] = seg["last_seen_date"]

    mask = seg["next_start_date"].notna()
    if mask.any():
        candidate = seg.loc[mask, "next_start_date"] - pd.Timedelta(days=1)
        seg.loc[mask, "end_date"] = np.maximum(
            seg.loc[mask, "last_seen_date"].values.astype("datetime64[ns]"),
            candidate.values.astype("datetime64[ns]")
        )

    seg["duration_days"] = (seg["end_date"] - seg["start_date"]).dt.days + 1
    seg["is_reintroduced_later"] = seg.duplicated(subset=["versionNumber"], keep=False)

    return seg.drop(columns=["next_start_date"])


def build_segments(history_df: pd.DataFrame) -> pd.DataFrame:
    parts = []
    group_cols = ["project_id", "project_name", "file", "db_name"]

    for _, sub in history_df.groupby(group_cols, sort=False, dropna=False):
        parts.append(build_segments_for_group(sub))

    if not parts:
        return pd.DataFrame(columns=[
            "project_id", "project", "file", "db", "versionNumber",
            "start_date", "last_seen_date", "end_date", "commits", "rows",
            "duration_days", "is_reintroduced_later"
        ])

    return pd.concat(parts, ignore_index=True)


def build_rq3_reintroductions(segments_df: pd.DataFrame) -> pd.DataFrame:
    if segments_df.empty:
        return pd.DataFrame()

    rq3 = (
        segments_df.groupby(["project_id", "project", "file", "db", "versionNumber"], dropna=False)
        .agg(
            inclusions=("start_date", "count"),
            first_inclusion=("start_date", "min"),
            last_removal=("end_date", "max"),
            total_days_present=("duration_days", "sum"),
        )
        .reset_index()
    )

    rq3["reintroductions"] = rq3["inclusions"] - 1
    rq3["has_reintroduction"] = rq3["reintroductions"] > 0

    return rq3.sort_values(
        ["has_reintroduction", "reintroductions", "project", "db", "file", "versionNumber"],
        ascending=[False, False, True, True, True, True],
        kind="mergesort"
    )


def build_rq1_associations(base_df: pd.DataFrame) -> pd.DataFrame:
    is_vulnerable = base_df["is_vulnerable"]
    if is_vulnerable.dtype == bool:
        vulnerable_mask = is_vulnerable
    else:
        vulnerable_mask = (
            is_vulnerable.astype("string")
            .str.strip()
            .str.lower()
            .isin(["true", "1", "yes", "sim"])
        )

    vuln_df = base_df[vulnerable_mask].copy()
    if vuln_df.empty:
        return pd.DataFrame()

    rq1 = (
        vuln_df.groupby(
            [
                "project_id",
                "project_name",
                "file",
                "db_name",
                "versionNumber",
                "vulnerability_id",
                "reference",
            ],
            dropna=False
        )
        .agg(
            first_seen_in_project=("date_commit", "min"),
            last_seen_in_project=("date_commit", "max"),
            commits_observed=("sha1", "nunique"),
            rows_observed=("version_vulnerability_id", "count"),
            published_at=("published_at", "first"),
            last_modified_at=("last_modified_at", "first"),
            cvss_score=("cvss_score", "first"),
            cvss_severity=("cvss_severity", "first"),
            cvss_vector=("cvss_vector", "first"),
            vulnerability_status=("vulnerability_status", "first"),
            vulnerability_name=("vulnerability_name", "first"),
            vulnerability_description=("vulnerability_description", "first"),
            vuln_purl=("vuln_purl", "first"),
        )
        .reset_index()
        .rename(columns={
            "project_name": "project",
            "db_name": "db",
            "reference": "cve",
        })
    )

    return rq1.sort_values(
        ["project", "db", "file", "first_seen_in_project", "cve"],
        kind="mergesort"
    )


def build_rq1_project_summary(rq1_assoc: pd.DataFrame) -> pd.DataFrame:
    if rq1_assoc.empty:
        return pd.DataFrame()

    return (
        rq1_assoc.groupby(["project_id", "project"], dropna=False)
        .agg(
            dbms_affected=("db", "nunique"),
            vulnerable_versions=("versionNumber", "nunique"),
            vulnerability_occurrences=("cve", "count"),
        )
        .reset_index()
        .sort_values(
            ["vulnerability_occurrences", "dbms_affected", "project"],
            ascending=[False, False, True],
            kind="mergesort"
        )
    )


def build_rq1_db_summary(rq1_assoc: pd.DataFrame) -> pd.DataFrame:
    if rq1_assoc.empty:
        return pd.DataFrame()

    return (
        rq1_assoc.groupby(["db"], dropna=False)
        .agg(
            projects_affected=("project", "nunique"),
            vulnerable_versions=("versionNumber", "nunique"),
            vulnerability_occurrences=("cve", "count"),
        )
        .reset_index()
        .sort_values(
            ["projects_affected", "vulnerability_occurrences", "db"],
            ascending=[False, False, True],
            kind="mergesort"
        )
    )


def build_rq1_db_usage_summary(rq1_assoc: pd.DataFrame, base_df: pd.DataFrame) -> pd.DataFrame:
    if rq1_assoc.empty:
        return pd.DataFrame()

    required_cols = ["project_id", "db_name", "sha1"]
    missing = [col for col in required_cols if col not in base_df.columns]
    if missing:
        raise ValueError(f"Colunas obrigatorias ausentes na base RQ: {missing}")

    base = base_df.copy()
    base["db"] = normalize_text(base["db_name"])

    db_usage = (
        base[base["db"].notna()]
        .groupby("db", dropna=False)
        .agg(
            projects_using_db=("project_id", "nunique"),
            commits_using_db=("sha1", "nunique"),
        )
        .reset_index()
    )

    db_exposure = (
        rq1_assoc.groupby("db", dropna=False)
        .agg(
            projects_affected=("project_id", "nunique"),
            vulnerable_commits=("commits_observed", "sum"),
            vulnerable_versions=("versionNumber", "nunique"),
            vulnerability_occurrences=("vulnerability_id", "nunique"),
        )
        .reset_index()
    )

    summary = db_exposure.merge(db_usage, on="db", how="left")
    summary["projects_using_db"] = summary["projects_using_db"].fillna(0).astype(int)
    summary["commits_using_db"] = summary["commits_using_db"].fillna(0).astype(int)

    summary["exposure_project_ratio"] = (
        summary["projects_affected"] / summary["projects_using_db"]
    ).where(summary["projects_using_db"] > 0, 0)
    summary["exposure_commit_ratio"] = (
        summary["vulnerable_commits"] / summary["commits_using_db"]
    ).where(summary["commits_using_db"] > 0, 0)

    summary["exposure_project_percent"] = (summary["exposure_project_ratio"] * 100).round(2)
    summary["exposure_commit_percent"] = (summary["exposure_commit_ratio"] * 100).round(2)
    summary["projects_exposure_label"] = (
        summary["projects_affected"].astype(str)
        + "/"
        + summary["projects_using_db"].astype(str)
    )
    summary["commits_exposure_label"] = (
        summary["vulnerable_commits"].astype(str)
        + "/"
        + summary["commits_using_db"].astype(str)
    )

    return summary.sort_values(
        ["vulnerable_commits", "exposure_commit_ratio", "projects_affected", "db"],
        ascending=[False, False, False, True],
        kind="mergesort",
    )


def pick_disclosure_date_column(rq1_assoc: pd.DataFrame) -> str:
    has_published = "published_at" in rq1_assoc.columns and rq1_assoc["published_at"].notna().any()
    if has_published:
        return "published_at"
    return "last_modified_at"


def merge_intervals(intervals: list[tuple]) -> list[tuple]:
    """
    Recebe uma lista de (start, end) como timestamps e retorna a lista
    de intervalos após fusão dos sobrepostos/contíguos.
    Usado para calcular o total de dias de exposição sem dupla contagem.
    """
    if not intervals:
        return []
    sorted_ivs = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_ivs[0]]
    for start, end in sorted_ivs[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + pd.Timedelta(days=1):
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def compute_merged_days(intervals: list[tuple]) -> float:
    """Soma os dias dos intervalos já mesclados (inclusivo em ambas as pontas)."""
    return sum((end - start).days + 1 for start, end in intervals)


def compute_merged_days_before(intervals: list[tuple], cutoff) -> float:
    """Dias dos intervalos mesclados que ocorrem ANTES de cutoff."""
    total = 0.0
    for start, end in intervals:
        clipped_end = min(end, cutoff - pd.Timedelta(days=1))
        if clipped_end >= start:
            total += (clipped_end - start).days + 1
    return total


def compute_merged_days_from(intervals: list[tuple], cutoff) -> float:
    """Dias dos intervalos mesclados que ocorrem A PARTIR de cutoff."""
    total = 0.0
    for start, end in intervals:
        clipped_start = max(start, cutoff)
        if clipped_start <= end:
            total += (end - clipped_start).days + 1
    return total


def build_rq2_exposures(rq1_assoc: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula o tempo de exposição por (project, db) sem dupla contagem.

    O problema original: rq1_assoc tem uma linha por (arquivo × CVE), e cada
    linha carrega seu próprio intervalo [first_seen, last_seen]. Somar
    total_exposure_days diretamente inflata o resultado porque intervalos de
    arquivos/CVEs diferentes se sobrepõem no tempo.

    Correção: para cada (project_id, db), coletamos todos os intervalos
    [first_seen, last_seen], fundimos os sobrepostos (merge de intervalos) e
    só então calculamos os dias totais, pré- e pós-divulgação.

    A granularidade do CSV de saída continua sendo (project × db) — uma linha
    por par — o que é o nível correto para o gráfico de CDF.
    """
    if rq1_assoc.empty:
        return pd.DataFrame()

    df = rq1_assoc.copy()
    for col in ["first_seen_in_project", "last_seen_in_project", "published_at", "last_modified_at"]:
        if col in df.columns:
            df[col] = (
                pd.to_datetime(df[col], errors="coerce", utc=True)
                .dt.tz_localize(None)
            )

    disclosure_col = pick_disclosure_date_column(df)
    df["disclosure_date_used"] = (
        pd.to_datetime(df[disclosure_col], errors="coerce", utc=True)
        .dt.tz_localize(None)
    )
    df["disclosure_source"] = disclosure_col

    records = []

    for (project_id, project, db), group in df.groupby(
        ["project_id", "project", "db"], dropna=False
    ):
        # Todos os intervalos de exposição deste (projeto × DBMS)
        raw_intervals = [
            (row.first_seen_in_project, row.last_seen_in_project)
            for row in group.itertuples(index=False)
            if pd.notna(row.first_seen_in_project) and pd.notna(row.last_seen_in_project)
        ]

        if not raw_intervals:
            continue

        merged = merge_intervals(raw_intervals)
        total_days = compute_merged_days(merged)

        # Data de divulgação: mínima do grupo (conservador — primeira CVE divulgada)
        disclosure_dates = group["disclosure_date_used"].dropna()
        disclosure_date = disclosure_dates.min() if not disclosure_dates.empty else pd.NaT
        disclosure_source = group["disclosure_source"].iloc[0]

        if pd.notna(disclosure_date):
            pre_days = compute_merged_days_before(merged, disclosure_date)
            post_days = compute_merged_days_from(merged, disclosure_date)
        else:
            pre_days = 0.0
            post_days = 0.0

        records.append({
            "project_id":                  project_id,
            "project":                     project,
            "db":                          db,
            "first_seen_in_project":       min(s for s, _ in merged),
            "last_seen_in_project":        max(e for _, e in merged),
            "total_exposure_days":         total_days,
            "pre_disclosure_days":         pre_days,
            "post_disclosure_days":        post_days,
            "disclosure_date_used":        disclosure_date,
            "disclosure_source":           disclosure_source,
            "was_publicly_known_during_use": post_days > 0,
            "used_before_disclosure":      pre_days > 0,
            # Métricas auxiliares para conferência
            "n_cves":                      group["cve"].nunique(),
            "n_files":                     group["file"].nunique(),
            "n_raw_intervals":             len(raw_intervals),
            "n_merged_intervals":          len(merged),
        })

    result = pd.DataFrame(records)

    logging.info(
        "RQ2: %d pares (projeto × DBMS) | intervalos brutos totais: %d | "
        "intervalos após merge: %d",
        len(result),
        result["n_raw_intervals"].sum() if not result.empty else 0,
        result["n_merged_intervals"].sum() if not result.empty else 0,
    )

    return result.sort_values(
        ["project", "db", "first_seen_in_project"],
        kind="mergesort"
    )


def build_rq2_summary(rq2_df: pd.DataFrame) -> pd.DataFrame:
    if rq2_df.empty:
        return pd.DataFrame()

    return (
        rq2_df.groupby(["db"], dropna=False)
        .agg(
            projects_affected=("project", "nunique"),
            total_cves=("n_cves", "sum"),
            median_total_exposure_days=("total_exposure_days", "median"),
            mean_total_exposure_days=("total_exposure_days", "mean"),
            median_post_disclosure_days=("post_disclosure_days", "median"),
            mean_post_disclosure_days=("post_disclosure_days", "mean"),
            max_post_disclosure_days=("post_disclosure_days", "max"),
        )
        .reset_index()
        .sort_values(
            ["median_post_disclosure_days", "mean_total_exposure_days", "db"],
            ascending=[False, False, True],
            kind="mergesort"
        )
    )


def build_summary(history_df: pd.DataFrame) -> pd.DataFrame:
    if history_df.empty:
        return pd.DataFrame()

    return (
        history_df.groupby(["project_id", "project_name", "file", "db_name"], dropna=False)
        .agg(
            distinct_versions=("versionNumber", "nunique"),
            first_commit=("date_commit", "min"),
            last_commit=("date_commit", "max"),
            total_commits_observed=("sha1", "nunique"),
            total_rows=("version_id", "count"),
        )
        .reset_index()
        .rename(columns={
            "project_name": "project",
            "db_name": "db",
        })
        .sort_values(["project", "db", "file"], kind="mergesort")
    )


def export_results(
    output_path: Path,
    base_df: pd.DataFrame,
    history_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    segments_df: pd.DataFrame,
    rq1_assoc: pd.DataFrame,
    rq1_project: pd.DataFrame,
    rq1_db: pd.DataFrame,
    rq2_df: pd.DataFrame,
    rq2_summary: pd.DataFrame,
    rq3_df: pd.DataFrame,
) -> None:
    ensure_output_dir(output_path)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, index=False, sheet_name="Resumo")
        base_df.to_excel(writer, index=False, sheet_name="Base_Completa")
        history_df.to_excel(writer, index=False, sheet_name="Historico_Dedup")
        segments_df.to_excel(writer, index=False, sheet_name="Segmentos")
        rq1_assoc.to_excel(writer, index=False, sheet_name="RQ1_Associacoes")
        rq1_project.to_excel(writer, index=False, sheet_name="RQ1_Projetos")
        rq1_db.to_excel(writer, index=False, sheet_name="RQ1_DBMS")
        rq2_df.to_excel(writer, index=False, sheet_name="RQ2_Exposicoes")
        rq2_summary.to_excel(writer, index=False, sheet_name="RQ2_Resumo")
        rq3_df.to_excel(writer, index=False, sheet_name="RQ3_Reintroducoes")

    logging.info("Arquivo Excel gerado em: %s", output_path)


def export_rq2_csv_results(
    csv_output_dir: Path,
    rq2_df: pd.DataFrame,
    rq2_summary: pd.DataFrame,
) -> None:
    ensure_dir(csv_output_dir)

    rq2_path = csv_output_dir / "rq2_exposicoes.csv"
    rq2_summary_path = csv_output_dir / "rq2_resumo.csv"

    rq2_df.to_csv(rq2_path, index=False)
    rq2_summary.to_csv(rq2_summary_path, index=False)

    logging.info("CSV gerado: %s", rq2_path)
    logging.info("CSV gerado: %s", rq2_summary_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pipeline final para responder RQ1, RQ2 e RQ3 direto do SQLite."
    )
    parser.add_argument(
        "--output",
        required=False,
        default=None,
        help="Caminho do Excel de saída. Se omitido, usa resultado_rqs.xlsx no diretório atual."
    )
    parser.add_argument(
        "--csv-output-dir",
        required=False,
        default=DEFAULT_CSV_OUTPUT_DIR,
        help="Diretório para salvar CSVs derivados. Se omitido, usa rqs_data."
    )
    parser.add_argument(
        "--skip-excel",
        action="store_true",
        help="Gera os CSVs derivados sem escrever o arquivo Excel completo."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    db_path = resolve_default_db_path()
    output_path = resolve_output_path(args.output)
    csv_output_dir = Path(args.csv_output_dir)

    logging.info("Banco localizado automaticamente em: %s", db_path)
    logging.info("Arquivo de saída será gerado em: %s", output_path)
    logging.info("CSVs derivados serão gerados em: %s", csv_output_dir)

    conn = sqlite3.connect(str(db_path))

    try:
        base_df = load_base_dataframe(conn)
        history_df = deduplicate_history_for_segments(base_df)

        summary_df = build_summary(history_df)
        segments_df = build_segments(history_df)
        rq3_df = build_rq3_reintroductions(segments_df)

        rq1_assoc = build_rq1_associations(base_df)
        rq1_project = build_rq1_project_summary(rq1_assoc)
        rq1_db = build_rq1_db_summary(rq1_assoc)

        rq2_df = build_rq2_exposures(rq1_assoc)
        rq2_summary = build_rq2_summary(rq2_df)

        export_rq2_csv_results(
            csv_output_dir=csv_output_dir,
            rq2_df=rq2_df,
            rq2_summary=rq2_summary,
        )
        if args.skip_excel:
            logging.info("Exportação do Excel ignorada por --skip-excel.")
        else:
            export_results(
                output_path=output_path,
                base_df=base_df,
                history_df=history_df,
                summary_df=summary_df,
                segments_df=segments_df,
                rq1_assoc=rq1_assoc,
                rq1_project=rq1_project,
                rq1_db=rq1_db,
                rq2_df=rq2_df,
                rq2_summary=rq2_summary,
                rq3_df=rq3_df,
            )

        logging.info("Resumo geral")
        logging.info("Linhas base: %s", len(base_df))
        logging.info("Histórico deduplicado: %s", len(history_df))
        logging.info("Segmentos: %s", len(segments_df))
        logging.info("RQ1 associações: %s", len(rq1_assoc))
        logging.info("RQ2 exposições: %s", len(rq2_df))
        logging.info("RQ3 reintroduções: %s", len(rq3_df))

        if not rq2_df.empty:
            disclosure_source = rq2_df["disclosure_source"].dropna().iloc[0]
            logging.info("Fonte temporal usada em RQ2: %s", disclosure_source)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
