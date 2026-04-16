#!/usr/bin/env python3
from pathlib import Path
import sqlite3
import pandas as pd

DB_PATH = Path("dbmining.sqlite")
OUTPUT_DIR = Path("resultados_falhas_build")


def classify_build_failure(output: str) -> str:
    text = (output or "").lower()

    if "could not find artifact" in text:
        return "ARTIFACT_NOT_FOUND"

    if "blocked mirror for repositories" in text or "maven-default-http-blocker" in text:
        return "BLOCKED_HTTP_REPOSITORY"

    if "could not resolve dependencies" in text:
        return "DEPENDENCY_RESOLUTION_FAILED"

    if "cannot build project dependency graph" in text:
        return "DEPENDENCY_GRAPH_FAILED"

    if "non-resolvable parent pom" in text:
        return "PARENT_POM_NOT_RESOLVED"

    if "pluginresolutionexception" in text or "could not resolve plugin" in text:
        return "PLUGIN_RESOLUTION_FAILED"

    if "compilation failure" in text:
        return "COMPILATION_FAILURE"

    if "java.lang.outofmemoryerror" in text or "outofmemoryerror" in text:
        return "OUT_OF_MEMORY"

    if "pkix path building failed" in text or "sun.security.validator.validatorexception" in text:
        return "SSL_CERTIFICATE_ERROR"

    if "connection timed out" in text or "read timed out" in text or "connect timed out" in text:
        return "NETWORK_TIMEOUT"

    if "temporary failure in name resolution" in text or "unknown host" in text:
        return "DNS_OR_HOST_ERROR"

    if "permission denied" in text:
        return "PERMISSION_DENIED"

    if "no such file or directory" in text:
        return "FILE_NOT_FOUND"

    if "failed to execute goal" in text:
        return "MAVEN_GOAL_FAILED"

    return "OTHER"


def extract_short_reason(output: str) -> str:
    if not output:
        return ""

    lines = [line.strip() for line in output.splitlines() if line.strip()]

    error_lines = []
    for line in lines:
        lower = line.lower()
        if "[error]" in lower or "build failed:" in lower:
            error_lines.append(line)

    if error_lines:
        return " | ".join(error_lines[:3])[:1000]

    return " | ".join(lines[:3])[:1000]


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Banco não encontrado: {DB_PATH.resolve()}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)

    try:
        query = """
        SELECT
            e.id AS execution_id,
            e.output,
            e.heuristic_id,
            v.id AS version_id,
            v.part_commit,
            v.sha1,
            v.isLast,
            p.id AS project_id,
            p.owner,
            p.name
        FROM execution e
        JOIN version v ON e.version_id = v.id
        JOIN project p ON v.project_id = p.id
        WHERE e.output LIKE '%BUILD FAILED:%'
        ORDER BY p.id, v.part_commit ASC
        """

        df = pd.read_sql_query(query, conn)

        if df.empty:
            print("Nenhuma falha de build encontrada.")
            return

        df["failure_category"] = df["output"].apply(classify_build_failure)
        df["short_reason"] = df["output"].apply(extract_short_reason)
        df["project_full_name"] = df["owner"].astype(str) + "/" + df["name"].astype(str)

        project_summary = (
            df.groupby(["project_id", "project_full_name"], as_index=False)
            .agg(
                total_build_failures=("execution_id", "count"),
                affected_versions=("version_id", "nunique"),
                affected_heuristics=("heuristic_id", "nunique"),
            )
            .sort_values(["total_build_failures", "affected_versions"], ascending=[False, False])
        )

        project_category_summary = (
            df.groupby(
                ["project_id", "project_full_name", "failure_category"],
                as_index=False
            )
            .agg(
                failures=("execution_id", "count"),
                affected_versions=("version_id", "nunique"),
            )
            .sort_values(
                ["project_id", "failures"],
                ascending=[True, False]
            )
        )

        global_category_summary = (
            df.groupby("failure_category", as_index=False)
            .agg(
                failures=("execution_id", "count"),
                affected_projects=("project_id", "nunique"),
                affected_versions=("version_id", "nunique"),
            )
            .sort_values("failures", ascending=False)
        )

        top_reasons = (
            df.groupby(["failure_category", "short_reason"], as_index=False)
            .agg(
                failures=("execution_id", "count"),
                affected_projects=("project_id", "nunique"),
            )
            .sort_values(
                ["failures", "affected_projects"],
                ascending=[False, False]
            )
        )

        details_path = OUTPUT_DIR / "falhas_build_detalhadas.csv"
        project_summary_path = OUTPUT_DIR / "falhas_build_por_projeto.csv"
        project_category_path = OUTPUT_DIR / "falhas_build_por_projeto_e_categoria.csv"
        global_category_path = OUTPUT_DIR / "falhas_build_categorias_global.csv"
        top_reasons_path = OUTPUT_DIR / "falhas_build_principais_motivos.csv"

        df.to_csv(details_path, index=False)
        project_summary.to_csv(project_summary_path, index=False)
        project_category_summary.to_csv(project_category_path, index=False)
        global_category_summary.to_csv(global_category_path, index=False)
        top_reasons.to_csv(top_reasons_path, index=False)

        print("Arquivos gerados com sucesso.")
        print(f"Pasta de saída: {OUTPUT_DIR.resolve()}")
        print(f"Detalhamento: {details_path.resolve()}")
        print(f"Resumo por projeto: {project_summary_path.resolve()}")
        print(f"Resumo por projeto e categoria: {project_category_path.resolve()}")
        print(f"Resumo global por categoria: {global_category_path.resolve()}")
        print(f"Principais motivos: {top_reasons_path.resolve()}")
        print()
        print("Top 10 projetos com mais falhas de build:")
        print(project_summary.head(10).to_string(index=False))
        print()
        print("Top 10 categorias de falha:")
        print(global_category_summary.head(10).to_string(index=False))

    finally:
        conn.close()


if __name__ == "__main__":
    main()