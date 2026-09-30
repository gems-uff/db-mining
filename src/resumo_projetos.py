#!/usr/bin/env python3
from pathlib import Path
import sqlite3
import pandas as pd

DB_PATH = Path("dbmining.sqlite")
OUTPUT_DIR = Path("resultados_resumo_projetos")


def normalize_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def detect_dependency_tree_failure(row) -> bool:
    event_type = normalize_text(row["event_type"])
    status = normalize_text(row["status"])
    message = normalize_text(row["message"])

    combined = f"{event_type} {status} {message}"

    has_dependency_context = (
        "dependency" in combined
        or "dependency tree" in combined
        or "dependency:tree" in combined
        or "maven" in combined
    )

    has_failure_signal = (
        "fail" in combined
        or "error" in combined
        or "exception" in combined
        or "non-zero" in combined
        or "return code" in combined
    )

    explicit_event_names = {
        "prepare_version_failed",
        "generate_dependency_tree_failed",
        "dependency_tree_failed",
        "maven_dependency_tree_failed",
        "all_dependencies_failed",
    }

    if event_type in explicit_event_names:
        return True

    if has_dependency_context and has_failure_signal:
        return True

    return False


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Banco não encontrado: {DB_PATH.resolve()}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)

    try:
        projects_df = pd.read_sql_query(
            """
            SELECT
                id AS project_id,
                name AS project_name
            FROM project
            ORDER BY name
            """,
            conn,
        )

        versions_df = pd.read_sql_query(
            """
            SELECT
                id AS version_id,
                sha1,
                project_id,
                date_commit
            FROM version
            """,
            conn,
        )

        execution_df = pd.read_sql_query(
            """
            SELECT DISTINCT
                version_id
            FROM execution
            WHERE version_id IS NOT NULL
            """,
            conn,
        )

        analysis_event_df = pd.read_sql_query(
            """
            SELECT
                id,
                project_id,
                version_id,
                event_type,
                status,
                commit_sha,
                message
            FROM analysis_event
            """,
            conn,
        )

        versions_with_execution = set(
            execution_df["version_id"].dropna().astype(int).tolist()
        )

        if analysis_event_df.empty:
            failed_version_ids = set()
        else:
            analysis_event_df["is_dependency_tree_failed"] = analysis_event_df.apply(
                detect_dependency_tree_failure,
                axis=1
            )

            failed_version_ids = set(
                analysis_event_df.loc[
                    analysis_event_df["is_dependency_tree_failed"] &
                    analysis_event_df["version_id"].notna(),
                    "version_id"
                ].astype(int).tolist()
            )

        details = versions_df.copy()

        def classify_version(version_id: int) -> str:
            if version_id in failed_version_ids:
                return "DEPENDENCY_TREE_FAILED"
            if version_id in versions_with_execution:
                return "WITH_DB_RESULT"
            return "NO_DB_FOUND"

        details["classification"] = details["version_id"].apply(classify_version)

        summary_df = (
            details.groupby("project_id")
            .agg(
                versions_total=("version_id", "nunique"),
                versions_with_db=("classification", lambda s: (s == "WITH_DB_RESULT").sum()),
                versions_no_db_found=("classification", lambda s: (s == "NO_DB_FOUND").sum()),
                versions_dependency_tree_failed=("classification", lambda s: (s == "DEPENDENCY_TREE_FAILED").sum()),
            )
            .reset_index()
        )

        summary_df = projects_df.merge(summary_df, on="project_id", how="left")

        for col in [
            "versions_total",
            "versions_with_db",
            "versions_no_db_found",
            "versions_dependency_tree_failed",
        ]:
            summary_df[col] = summary_df[col].fillna(0).astype(int)

        summary_df["check_total"] = (
            summary_df["versions_with_db"]
            + summary_df["versions_no_db_found"]
            + summary_df["versions_dependency_tree_failed"]
        )

        summary_df["is_consistent"] = (
            summary_df["versions_total"] == summary_df["check_total"]
        )

        failed_events_export = analysis_event_df.copy()
        if not failed_events_export.empty:
            failed_events_export = failed_events_export[
                failed_events_export["is_dependency_tree_failed"] == True
            ].copy()

        summary_path = OUTPUT_DIR / "resumo_por_projeto.csv"
        details_path = OUTPUT_DIR / "detalhamento_por_versao.csv"
        failed_events_path = OUTPUT_DIR / "eventos_dependency_tree_failed.csv"

        summary_df.to_csv(summary_path, index=False)
        details.to_csv(details_path, index=False)

        if not failed_events_export.empty:
            failed_events_export.to_csv(failed_events_path, index=False)
        else:
            pd.DataFrame(
                columns=[
                    "id",
                    "project_id",
                    "version_id",
                    "event_type",
                    "status",
                    "commit_sha",
                    "message",
                    "is_dependency_tree_failed",
                ]
            ).to_csv(failed_events_path, index=False)

        total_projects = summary_df["project_id"].nunique()
        total_versions = summary_df["versions_total"].sum()
        total_with_db = summary_df["versions_with_db"].sum()
        total_no_db = summary_df["versions_no_db_found"].sum()
        total_failed = summary_df["versions_dependency_tree_failed"].sum()

        print("Arquivos gerados com sucesso.")
        print(f"Pasta de saída: {OUTPUT_DIR.resolve()}")
        print(f"Resumo por projeto: {summary_path.resolve()}")
        print(f"Detalhamento por versão: {details_path.resolve()}")
        print(f"Eventos de falha do dependency tree: {failed_events_path.resolve()}")
        print()
        print("Resumo global:")
        print(f"Projetos: {total_projects}")
        print(f"Versões totais: {total_versions}")
        print(f"Versões com resultado de BD: {total_with_db}")
        print(f"Versões sem BD encontrado: {total_no_db}")
        print(f"Versões com falha no dependency tree: {total_failed}")

        inconsistent_df = summary_df[summary_df["is_consistent"] == False]
        if not inconsistent_df.empty:
            print()
            print("Projetos com inconsistência na soma:")
            print(
                inconsistent_df[
                    [
                        "project_name",
                        "versions_total",
                        "versions_with_db",
                        "versions_no_db_found",
                        "versions_dependency_tree_failed",
                        "check_total",
                    ]
                ].to_string(index=False)
            )

    finally:
        conn.close()


if __name__ == "__main__":
    main()