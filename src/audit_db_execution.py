import sqlite3
import csv
import os
from typing import List, Dict, Set

OUTPUT_CSV = "audit_execution_report.csv"


def get_tables(conn) -> Set[str]:
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cur.fetchall()}


def get_columns(conn, table_name: str) -> Set[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cur.fetchall()}


def table_exists(conn, table_name: str) -> bool:
    return table_name in get_tables(conn)


def detect_tables(conn) -> Dict[str, str]:
    """
    Tenta localizar os nomes reais das tabelas mais comuns.
    Ajuste aqui se no seu banco os nomes forem diferentes.
    """
    tables = get_tables(conn)

    candidates = {
        "project": ["project", "projects", "Project"],
        "version": ["version", "versions", "Version"],
        "execution": ["execution", "executions", "Execution"],
        "version_vulnerability": [
            "version_vulnerability",
            "versionvulnerability",
            "version_vulnerabilities",
            "VersionVulnerability",
        ],
    }

    detected = {}
    for logical_name, names in candidates.items():
        for name in names:
            if name in tables:
                detected[logical_name] = name
                break

    return detected


def fetch_all_projects(conn, project_table: str) -> List[Dict]:
    cols = get_columns(conn, project_table)
    cur = conn.cursor()

    name_col = None
    for candidate in ["name", "project_name", "full_name", "slug"]:
        if candidate in cols:
            name_col = candidate
            break

    if not name_col:
        raise RuntimeError(
            f"Não encontrei uma coluna de nome na tabela {project_table}. Colunas: {sorted(cols)}"
        )

    cur.execute(f"SELECT id, {name_col} FROM {project_table} ORDER BY {name_col}")
    return [{"id": row[0], "name": row[1]} for row in cur.fetchall()]


def run_scalar(conn, query: str, params=()):
    cur = conn.cursor()
    cur.execute(query, params)
    row = cur.fetchone()
    if not row:
        return 0
    return row[0] if row[0] is not None else 0


def main():
    DB_PATH = os.path.join(os.getcwd(), "dbmining.sqlite")
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Banco não encontrado: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    detected = detect_tables(conn)
    print("Tabelas detectadas:", detected)

    required = ["project", "version", "execution"]
    missing = [r for r in required if r not in detected]
    if missing:
        raise RuntimeError(
            f"Não foi possível localizar todas as tabelas necessárias. Faltando: {missing}"
        )

    project_table = detected["project"]
    version_table = detected["version"]
    execution_table = detected["execution"]
    vv_table = detected.get("version_vulnerability")

    version_cols = get_columns(conn, version_table)
    execution_cols = get_columns(conn, execution_table)

    if "project_id" not in version_cols:
        raise RuntimeError(
            f"A tabela {version_table} não possui coluna project_id. Colunas: {sorted(version_cols)}"
        )

    if "version_id" not in execution_cols:
        raise RuntimeError(
            f"A tabela {execution_table} não possui coluna version_id. Colunas: {sorted(execution_cols)}"
        )

    vv_cols = get_columns(conn, vv_table) if vv_table else set()

    projects = fetch_all_projects(conn, project_table)

    status_col = "status" if "status" in execution_cols else None
    output_col = "execution_output" if "execution_output" in execution_cols else None

    rows = []

    for project in projects:
        project_id = project["id"]
        project_name = project["name"]

        versions_count = run_scalar(
            conn,
            f"""
            SELECT COUNT(*)
            FROM {version_table}
            WHERE project_id = ?
            """,
            (project_id,),
        )

        executions_count = run_scalar(
            conn,
            f"""
            SELECT COUNT(*)
            FROM {execution_table} e
            JOIN {version_table} v ON v.id = e.version_id
            WHERE v.project_id = ?
            """,
            (project_id,),
        )

        failed_executions = 0
        if status_col:
            failed_executions = run_scalar(
                conn,
                f"""
                SELECT COUNT(*)
                FROM {execution_table} e
                JOIN {version_table} v ON v.id = e.version_id
                WHERE v.project_id = ?
                  AND LOWER(COALESCE(e.{status_col}, '')) IN ('error', 'failed', 'failure')
                """,
                (project_id,),
            )
        elif output_col:
            failed_executions = run_scalar(
                conn,
                f"""
                SELECT COUNT(*)
                FROM {execution_table} e
                JOIN {version_table} v ON v.id = e.version_id
                WHERE v.project_id = ?
                  AND e.{output_col} IS NOT NULL
                  AND TRIM(e.{output_col}) <> ''
                """,
                (project_id,),
            )

        vulnerabilities_count = ""
        if vv_table and "execution_id" in vv_cols:
            vulnerabilities_count = run_scalar(
                conn,
                f"""
                SELECT COUNT(*)
                FROM {vv_table} vv
                JOIN {execution_table} e ON e.id = vv.execution_id
                JOIN {version_table} v ON v.id = e.version_id
                WHERE v.project_id = ?
                """,
                (project_id,),
            )

        if executions_count == 0:
            audit_status = "SEM_EXECUCAO"
        elif vv_table and vulnerabilities_count == 0:
            audit_status = "EXECUTADO_SEM_VULNERABILIDADE"
        elif failed_executions > 0 and executions_count > 0:
            audit_status = "EXECUCAO_COM_FALHAS"
        else:
            audit_status = "OK_OU_PRECISA_VALIDAR"

        rows.append({
            "project_id": project_id,
            "project_name": project_name,
            "versions_count": versions_count,
            "executions_count": executions_count,
            "failed_executions": failed_executions,
            "vulnerabilities_count": vulnerabilities_count,
            "audit_status": audit_status,
        })

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "project_id",
                "project_name",
                "versions_count",
                "executions_count",
                "failed_executions",
                "vulnerabilities_count",
                "audit_status",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    total_projects = len(rows)
    no_execution = sum(1 for r in rows if r["audit_status"] == "SEM_EXECUCAO")
    no_vulns = sum(1 for r in rows if r["audit_status"] == "EXECUTADO_SEM_VULNERABILIDADE")
    with_failures = sum(1 for r in rows if r["audit_status"] == "EXECUCAO_COM_FALHAS")

    print("\nResumo:")
    print(f"Total de projetos: {total_projects}")
    print(f"Projetos sem execução: {no_execution}")
    print(f"Projetos executados sem vulnerabilidades: {no_vulns}")
    print(f"Projetos com falhas em execução: {with_failures}")
    print(f"\nRelatório salvo em: {OUTPUT_CSV}")

    print("\nProjetos sem execução:")
    for r in rows:
        if r["audit_status"] == "SEM_EXECUCAO":
            print(f"  {r['project_name']}")

    conn.close()


if __name__ == "__main__":
    main()