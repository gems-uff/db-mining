#!/usr/bin/env python3
import argparse
import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

DEFAULT_INPUT_NAME = "resultado_rqs.xlsx"
DEFAULT_OUTPUT_DIR = "graficos_rqs"


def resolve_input_path(user_input: str | None) -> Path:
    if user_input:
        path = Path(user_input)
        if not path.exists():
            raise FileNotFoundError(f"Arquivo Excel não encontrado: {path}")
        return path

    cwd = Path.cwd()
    candidate = cwd / DEFAULT_INPUT_NAME
    if candidate.exists():
        return candidate

    matches = list(cwd.rglob(DEFAULT_INPUT_NAME))
    if matches:
        return matches[0]

    raise FileNotFoundError(
        f"Não encontrei {DEFAULT_INPUT_NAME} automaticamente a partir de {cwd}"
    )


def ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sanitize_filename(name: str) -> str:
    valid = []
    for ch in name.lower():
        if ch.isalnum():
            valid.append(ch)
        elif ch in [" ", "_"]:
            valid.append("_")
    result = "".join(valid).strip("_")
    return result or "grafico"


def save_plot(fig: plt.Figure, output_dir: Path, filename: str) -> None:
    filepath = output_dir / filename
    fig.tight_layout()
    fig.savefig(filepath, dpi=300, bbox_inches="tight")
    plt.close(fig)
    logging.info("Gráfico salvo em: %s", filepath)


def read_sheet_safe(excel_path: Path, sheet_name: str) -> pd.DataFrame:
    try:
        return pd.read_excel(excel_path, sheet_name=sheet_name)
    except ValueError:
        logging.warning("A aba %s não foi encontrada em %s", sheet_name, excel_path)
        return pd.DataFrame()


def prepare_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    df = df.copy()
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def prepare_datetime(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    df = df.copy()
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def plot_rq1_projects(rq1_projects: pd.DataFrame, output_dir: Path) -> None:
    if rq1_projects.empty:
        return

    rq1_projects = prepare_numeric(
        rq1_projects,
        ["dbms_affected", "vulnerable_versions", "vulnerability_occurrences"]
    )

    top = rq1_projects.sort_values(
        "vulnerability_occurrences", ascending=False
    ).head(15)

    fig = plt.figure(figsize=(12, 6))
    plt.bar(top["project"], top["vulnerability_occurrences"])
    plt.title("RQ1, ocorrências de vulnerabilidades por projeto")
    plt.xlabel("Projeto")
    plt.ylabel("Ocorrências")
    plt.xticks(rotation=45, ha="right")
    save_plot(fig, output_dir, "rq1_ocorrencias_por_projeto.png")


def plot_rq1_dbms(rq1_db: pd.DataFrame, output_dir: Path) -> None:
    if rq1_db.empty:
        return

    rq1_db = prepare_numeric(
        rq1_db,
        ["projects_affected", "vulnerable_versions", "vulnerability_occurrences"]
    ).sort_values("projects_affected", ascending=False)

    fig = plt.figure(figsize=(10, 6))
    plt.bar(rq1_db["db"], rq1_db["projects_affected"])
    plt.title("RQ1, projetos afetados por DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Projetos afetados")
    plt.xticks(rotation=45, ha="right")
    save_plot(fig, output_dir, "rq1_projetos_afetados_por_dbms.png")

    fig = plt.figure(figsize=(10, 6))
    plt.bar(rq1_db["db"], rq1_db["vulnerability_occurrences"])
    plt.title("RQ1, ocorrências de vulnerabilidades por DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Ocorrências")
    plt.xticks(rotation=45, ha="right")
    save_plot(fig, output_dir, "rq1_ocorrencias_por_dbms.png")


def plot_rq1_heatmap(rq1_assoc: pd.DataFrame, output_dir: Path) -> None:
    if rq1_assoc.empty:
        return

    pivot = (
        rq1_assoc.groupby(["project", "db"], dropna=False)
        .size()
        .reset_index(name="occurrences")
        .pivot(index="project", columns="db", values="occurrences")
        .fillna(0)
    )

    if pivot.empty:
        return

    fig = plt.figure(figsize=(12, 8))
    plt.imshow(pivot.values, aspect="auto")
    plt.title("RQ1, heatmap de ocorrências por projeto e DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Projetos")
    plt.xticks(range(len(pivot.columns)), pivot.columns, rotation=45, ha="right")
    plt.yticks(range(len(pivot.index)), pivot.index)
    plt.colorbar(label="Ocorrências")
    save_plot(fig, output_dir, "rq1_heatmap_projeto_dbms.png")


def plot_rq2_boxplot(rq2_exposicoes: pd.DataFrame, output_dir: Path) -> None:
    if rq2_exposicoes.empty:
        return

    rq2_exposicoes = prepare_numeric(
        rq2_exposicoes,
        ["pre_disclosure_days", "post_disclosure_days", "total_exposure_days"]
    )

    grouped = []
    labels = []
    for db, sub in rq2_exposicoes.groupby("db", dropna=False):
        vals = sub["post_disclosure_days"].dropna()
        if len(vals) > 0:
            grouped.append(vals.values)
            labels.append(db)

    if not grouped:
        return

    fig = plt.figure(figsize=(12, 6))
    plt.boxplot(grouped, labels=labels)
    plt.title("RQ2, distribuição do tempo pós divulgação por DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Dias")
    plt.xticks(rotation=45, ha="right")
    save_plot(fig, output_dir, "rq2_boxplot_pos_divulgacao_por_dbms.png")


def plot_rq2_cdf(rq2_exposicoes: pd.DataFrame, output_dir: Path) -> None:
    if rq2_exposicoes.empty:
        return

    rq2_exposicoes = prepare_numeric(
        rq2_exposicoes,
        ["post_disclosure_days", "total_exposure_days"]
    )

    values = rq2_exposicoes["post_disclosure_days"].dropna()
    values = values[values >= 0].sort_values()

    if values.empty:
        return

    y = np.arange(1, len(values) + 1) / len(values)

    fig = plt.figure(figsize=(10, 6))
    plt.plot(values.values, y.values if hasattr(y, "values") else y)
    plt.title("RQ2, CDF do tempo pós divulgação")
    plt.xlabel("Dias")
    plt.ylabel("Proporção acumulada")
    save_plot(fig, output_dir, "rq2_cdf_pos_divulgacao.png")


def plot_rq2_summary(rq2_summary: pd.DataFrame, output_dir: Path) -> None:
    if rq2_summary.empty:
        return

    rq2_summary = prepare_numeric(
        rq2_summary,
        [
            "projects_affected",
            "vulnerability_occurrences",
            "median_total_exposure_days",
            "mean_total_exposure_days",
            "median_post_disclosure_days",
            "mean_post_disclosure_days",
            "max_post_disclosure_days",
        ]
    ).sort_values("median_post_disclosure_days", ascending=False)

    fig = plt.figure(figsize=(10, 6))
    plt.bar(rq2_summary["db"], rq2_summary["median_post_disclosure_days"])
    plt.title("RQ2, mediana do tempo pós divulgação por DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Dias")
    plt.xticks(rotation=45, ha="right")
    save_plot(fig, output_dir, "rq2_mediana_pos_divulgacao_por_dbms.png")

    fig = plt.figure(figsize=(10, 6))
    plt.bar(rq2_summary["db"], rq2_summary["mean_total_exposure_days"])
    plt.title("RQ2, média do tempo total de exposição por DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Dias")
    plt.xticks(rotation=45, ha="right")
    save_plot(fig, output_dir, "rq2_media_exposicao_total_por_dbms.png")


def plot_rq3_reintroductions(rq3: pd.DataFrame, output_dir: Path) -> None:
    if rq3.empty:
        return

    rq3 = prepare_numeric(rq3, ["inclusions", "reintroductions", "total_days_present"])

    by_db = (
        rq3.groupby("db", dropna=False)["reintroductions"]
        .sum()
        .reset_index()
        .sort_values("reintroductions", ascending=False)
    )

    fig = plt.figure(figsize=(10, 6))
    plt.bar(by_db["db"], by_db["reintroductions"])
    plt.title("RQ3, reintroduções acumuladas por DBMS")
    plt.xlabel("DBMS")
    plt.ylabel("Reintroduções")
    plt.xticks(rotation=45, ha="right")
    save_plot(fig, output_dir, "rq3_reintroducoes_por_dbms.png")

    top_projects = (
        rq3.groupby("project", dropna=False)["reintroductions"]
        .sum()
        .reset_index()
        .sort_values("reintroductions", ascending=False)
        .head(15)
    )

    fig = plt.figure(figsize=(12, 6))
    plt.bar(top_projects["project"], top_projects["reintroductions"])
    plt.title("RQ3, reintroduções acumuladas por projeto")
    plt.xlabel("Projeto")
    plt.ylabel("Reintroduções")
    plt.xticks(rotation=45, ha="right")
    save_plot(fig, output_dir, "rq3_reintroducoes_por_projeto.png")


def plot_rq3_scatter(rq2_exposicoes: pd.DataFrame, rq3: pd.DataFrame, output_dir: Path) -> None:
    if rq2_exposicoes.empty or rq3.empty:
        return

    rq2_exposicoes = prepare_numeric(rq2_exposicoes, ["post_disclosure_days"])
    rq3 = prepare_numeric(rq3, ["reintroductions"])

    rq2_proj = (
        rq2_exposicoes.groupby("project", dropna=False)["post_disclosure_days"]
        .mean()
        .reset_index(name="mean_post_disclosure_days")
    )

    rq3_proj = (
        rq3.groupby("project", dropna=False)["reintroductions"]
        .sum()
        .reset_index(name="total_reintroductions")
    )

    merged = rq2_proj.merge(rq3_proj, on="project", how="inner")
    if merged.empty:
        return

    fig = plt.figure(figsize=(10, 6))
    plt.scatter(merged["total_reintroductions"], merged["mean_post_disclosure_days"])
    plt.title("RQ3, reintroduções versus tempo médio pós divulgação")
    plt.xlabel("Reintroduções acumuladas")
    plt.ylabel("Tempo médio pós divulgação, em dias")
    save_plot(fig, output_dir, "rq3_scatter_reintroducoes_vs_tempo.png")


def plot_rq3_timelines(segmentos: pd.DataFrame, output_dir: Path) -> None:
    if segmentos.empty:
        return

    segmentos = prepare_datetime(segmentos, ["start_date", "end_date"])
    segmentos = prepare_numeric(segmentos, ["duration_days"])

    reintro_counts = (
        segmentos.groupby(["project", "db", "versionNumber"], dropna=False)
        .size()
        .reset_index(name="segment_count")
    )
    reintro_counts = reintro_counts[reintro_counts["segment_count"] > 1]

    if reintro_counts.empty:
        logging.info("Nenhum caso de reintrodução com timeline foi encontrado.")
        return

    top_case = reintro_counts.sort_values("segment_count", ascending=False).iloc[0]
    case_segments = segmentos[
        (segmentos["project"] == top_case["project"]) &
        (segmentos["db"] == top_case["db"]) &
        (segmentos["versionNumber"] == top_case["versionNumber"])
    ].sort_values("start_date")

    if case_segments.empty:
        return

    fig = plt.figure(figsize=(12, 3))
    y_pos = [1] * len(case_segments)
    start_nums = case_segments["start_date"].map(pd.Timestamp.toordinal)
    end_nums = case_segments["end_date"].map(pd.Timestamp.toordinal)

    for i, (_, row) in enumerate(case_segments.iterrows()):
        plt.hlines(y=1, xmin=start_nums.iloc[i], xmax=end_nums.iloc[i], linewidth=6)

    ticks = start_nums.tolist() + end_nums.tolist()
    tick_labels = (
        case_segments["start_date"].dt.strftime("%Y-%m-%d").tolist() +
        case_segments["end_date"].dt.strftime("%Y-%m-%d").tolist()
    )
    unique_ticks = []
    unique_labels = []
    seen = set()
    for tick, label in zip(ticks, tick_labels):
        if tick not in seen:
            seen.add(tick)
            unique_ticks.append(tick)
            unique_labels.append(label)

    plt.xticks(unique_ticks, unique_labels, rotation=45, ha="right")
    plt.yticks([1], [f"{top_case['project']} | {top_case['db']} | {top_case['versionNumber']}"])
    plt.title("RQ3, exemplo de timeline de reintrodução")
    plt.xlabel("Tempo")
    save_plot(fig, output_dir, "rq3_timeline_exemplo_reintroducao.png")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera gráficos para responder RQ1, RQ2 e RQ3 a partir do Excel de resultados."
    )
    parser.add_argument(
        "--input",
        required=False,
        default=None,
        help="Caminho do Excel resultado_rqs.xlsx. Se omitido, procura automaticamente."
    )
    parser.add_argument(
        "--output-dir",
        required=False,
        default=DEFAULT_OUTPUT_DIR,
        help="Diretório onde os gráficos serão salvos."
    )
    args = parser.parse_args()

    excel_path = resolve_input_path(args.input)
    output_dir = Path(args.output_dir)
    ensure_output_dir(output_dir)

    logging.info("Lendo arquivo Excel: %s", excel_path)
    logging.info("Salvando gráficos em: %s", output_dir)

    rq1_assoc = read_sheet_safe(excel_path, "RQ1_Associacoes")
    rq1_projects = read_sheet_safe(excel_path, "RQ1_Projetos")
    rq1_db = read_sheet_safe(excel_path, "RQ1_DBMS")
    rq2_exposicoes = read_sheet_safe(excel_path, "RQ2_Exposicoes")
    rq2_summary = read_sheet_safe(excel_path, "RQ2_Resumo")
    rq3 = read_sheet_safe(excel_path, "RQ3_Reintroducoes")
    segmentos = read_sheet_safe(excel_path, "Segmentos")

    plot_rq1_projects(rq1_projects, output_dir)
    plot_rq1_dbms(rq1_db, output_dir)
    plot_rq1_heatmap(rq1_assoc, output_dir)

    plot_rq2_boxplot(rq2_exposicoes, output_dir)
    plot_rq2_cdf(rq2_exposicoes, output_dir)
    plot_rq2_summary(rq2_summary, output_dir)

    plot_rq3_reintroductions(rq3, output_dir)
    plot_rq3_scatter(rq2_exposicoes, rq3, output_dir)
    plot_rq3_timelines(segmentos, output_dir)

    logging.info("Geração dos gráficos concluída.")


if __name__ == "__main__":
    main()
