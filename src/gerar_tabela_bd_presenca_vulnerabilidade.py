#!/usr/bin/env python3
import argparse
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

DEFAULT_DB_PATH = 'dbmining.sqlite'
DEFAULT_OUTPUT_XLSX = 'rq1_bd_aparecem_com_sem_vulnerabilidade.xlsx'
DEFAULT_OUTPUT_CSV = 'rq1_bd_aparecem_com_sem_vulnerabilidade.csv'
DEFAULT_LABEL_TYPE = 'vulnerabilities'


def connect_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f'PRAGMA table_info({table_name})').fetchall()
    return {row['name'] for row in rows}


def build_label_filter(conn: sqlite3.Connection, label_type: Optional[str]) -> str:
    label_cols = get_columns(conn, 'label')
    if label_type and 'type' in label_cols:
        return 'WHERE l.type = :label_type'
    return ''


def build_query(conn: sqlite3.Connection, label_type: Optional[str]) -> str:
    label_filter = build_label_filter(conn, label_type)

    vuln_cols = get_columns(conn, 'vulnerability')
    if 'label_id' not in vuln_cols or 'version' not in vuln_cols:
        raise RuntimeError(
            'A tabela vulnerability precisa conter as colunas label_id e version '
            'para validar exposição usando apenas label_id + version.'
        )

    return f'''
WITH db_catalog AS (
    SELECT
        l.id AS label_id,
        l.name AS db,
        l.id AS id_database
    FROM label l
    {label_filter}
),
base_presence AS (
    SELECT DISTINCT
        dc.label_id,
        dc.db,
        dc.id_database,
        vv.version_id,
        vv.versionNumber,
        vv.commitsBetween,
        ver.project_id,
        ver.date_commit
    FROM db_catalog dc
    JOIN heuristic h
      ON h.label_id = dc.label_id
    JOIN execution e
      ON e.heuristic_id = h.id
    JOIN version_vulnerability vv
      ON vv.execution_id = e.id
    JOIN version ver
      ON ver.id = vv.version_id
    WHERE vv.version_id IS NOT NULL
      AND vv.versionNumber IS NOT NULL
      AND TRIM(vv.versionNumber) <> ''
),
presence_with_flag AS (
    SELECT
        b.*,
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM vulnerability v
                WHERE v.label_id = b.label_id
                  AND COALESCE(v.version, '') = COALESCE(b.versionNumber, '')
            ) THEN 1
            ELSE 0
        END AS has_vulnerability
    FROM base_presence b
),
aggregated AS (
    SELECT
        dc.id_database,
        dc.db,
        COUNT(DISTINCT pwf.project_id) AS projects_present,
        COUNT(DISTINCT pwf.version_id) AS commits_present,
        MIN(pwf.date_commit) AS first_seen,
        MAX(pwf.date_commit) AS last_seen,
        COUNT(DISTINCT CASE WHEN pwf.has_vulnerability = 1 THEN pwf.project_id END) AS projects_with_exposure,
        COUNT(DISTINCT CASE WHEN pwf.has_vulnerability = 1 THEN pwf.version_id END) AS vulnerable_commits,
        MIN(CASE WHEN pwf.has_vulnerability = 1 THEN pwf.date_commit END) AS first_vulnerable_seen,
        MAX(CASE WHEN pwf.has_vulnerability = 1 THEN pwf.date_commit END) AS last_vulnerable_seen,
        COUNT(DISTINCT CASE WHEN pwf.has_vulnerability = 0 THEN pwf.project_id END) AS projects_without_exposure,
        COUNT(DISTINCT CASE WHEN pwf.has_vulnerability = 0 THEN pwf.version_id END) AS commits_without_vulnerability,
        SUM(
            CASE
                WHEN pwf.has_vulnerability = 1
                THEN COALESCE(pwf.commitsBetween, 0)
                ELSE 0
            END
        ) AS vulnerable_activity_commits
    FROM db_catalog dc
    LEFT JOIN presence_with_flag pwf
      ON pwf.label_id = dc.label_id
    GROUP BY dc.id_database, dc.db
)
SELECT
    db,
    id_database,
    projects_present,
    commits_present,
    first_seen,
    last_seen,
    projects_with_exposure,
    vulnerable_commits,
    first_vulnerable_seen,
    last_vulnerable_seen,
    projects_without_exposure,
    commits_without_vulnerability,
    vulnerable_activity_commits,
    CASE
        WHEN commits_present > 0 THEN ROUND(CAST(vulnerable_commits AS REAL) / commits_present, 4)
        ELSE 0
    END AS exposure_commit_ratio,
    CASE
        WHEN commits_present > 0 THEN ROUND(100.0 * vulnerable_commits / commits_present, 2)
        ELSE 0
    END AS exposure_commit_pct
FROM aggregated
ORDER BY
    CASE WHEN commits_present = 0 THEN 2
         WHEN vulnerable_commits = 0 THEN 1
         ELSE 0
    END,
    vulnerable_commits DESC,
    commits_present DESC,
    db ASC
'''


def format_dates(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        out[col] = pd.to_datetime(out[col], errors='coerce').dt.date.astype('string')
    return out


def build_sections(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with_vuln = df[df['vulnerable_commits'] > 0].copy()
    without_vuln = df[(df['commits_present'] > 0) & (df['vulnerable_commits'] == 0)].copy()
    not_present = df[df['commits_present'] == 0].copy()
    return with_vuln, without_vuln, not_present


def export_outputs(df: pd.DataFrame, output_xlsx: Path, output_csv: Path) -> None:
    date_cols = ['first_seen', 'last_seen', 'first_vulnerable_seen', 'last_vulnerable_seen']
    df_fmt = format_dates(df, date_cols)
    with_vuln, without_vuln, not_present = build_sections(df_fmt)

    ordered_cols = [
        'db',
        'id_database',
        'projects_present',
        'commits_present',
        'first_seen',
        'last_seen',
        'projects_with_exposure',
        'vulnerable_commits',
        'first_vulnerable_seen',
        'last_vulnerable_seen',
        'projects_without_exposure',
        'commits_without_vulnerability',
        'exposure_commit_ratio',
        'exposure_commit_pct',
        'vulnerable_activity_commits',
    ]

    with pd.ExcelWriter(output_xlsx, engine='openpyxl') as writer:
        with_vuln[ordered_cols].to_excel(writer, index=False, sheet_name='com_vulnerabilidade')
        without_vuln[ordered_cols].to_excel(writer, index=False, sheet_name='sem_vulnerabilidade')
        not_present[ordered_cols].to_excel(writer, index=False, sheet_name='nao_aparecem')

        resumo = pd.DataFrame(
            [
                ['BDS com vulnerabilidade', len(with_vuln)],
                ['BDS sem vulnerabilidade', len(without_vuln)],
                ['BDS que não aparecem em nenhum projeto', len(not_present)],
            ],
            columns=['categoria', 'quantidade']
        )
        resumo.to_excel(writer, index=False, sheet_name='resumo')

        completa = df_fmt[ordered_cols].copy()
        completa.to_excel(writer, index=False, sheet_name='tabela_completa')

    df_fmt[ordered_cols].to_csv(output_csv, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Gera a tabela resumo de presença e exposição dos BDs usando validação por label_id + version.'
    )
    parser.add_argument('--db-path', default=DEFAULT_DB_PATH, help='Caminho para o banco SQLite.')
    parser.add_argument('--output-xlsx', default=DEFAULT_OUTPUT_XLSX, help='Arquivo XLSX de saída.')
    parser.add_argument('--output-csv', default=DEFAULT_OUTPUT_CSV, help='Arquivo CSV de saída.')
    parser.add_argument(
        '--label-type',
        default=DEFAULT_LABEL_TYPE,
        help='Tipo na tabela label. Use string vazia para não filtrar por tipo.'
    )
    args = parser.parse_args()

    label_type = args.label_type.strip() or None
    conn = connect_db(args.db_path)
    try:
        query = build_query(conn, label_type)
        params = {'label_type': label_type} if label_type else None
        df = pd.read_sql_query(query, conn, params=params)
        export_outputs(df, Path(args.output_xlsx), Path(args.output_csv))
    finally:
        conn.close()


if __name__ == '__main__':
    main()
