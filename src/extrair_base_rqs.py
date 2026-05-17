#!/usr/bin/env python3
import argparse
import logging
import sqlite3
from pathlib import Path

from rq_pipeline_common import (
    build_summary,
    deduplicate_history_for_segments,
    load_base_dataframe,
    resolve_default_db_path,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

DEFAULT_OUTPUT_DIR = "rqs_data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai a base intermediaria para as RQs a partir do SQLite."
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Diretorio de saida dos CSVs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    db_path = resolve_default_db_path()
    logging.info("Banco localizado em: %s", db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        base_df = load_base_dataframe(conn)
    finally:
        conn.close()

    history_df = deduplicate_history_for_segments(base_df)
    summary_df = build_summary(history_df)

    base_path = output_dir / "base_rqs.csv"
    history_path = output_dir / "historico_dedup.csv"
    summary_path = output_dir / "resumo_base.csv"

    base_df.to_csv(base_path, index=False)
    history_df.to_csv(history_path, index=False)
    summary_df.to_csv(summary_path, index=False)

    logging.info("CSV gerado: %s", base_path)
    logging.info("CSV gerado: %s", history_path)
    logging.info("CSV gerado: %s", summary_path)
    logging.info("Linhas base: %s", len(base_df))
    logging.info("Linhas historico deduplicado: %s", len(history_df))


if __name__ == "__main__":
    main()
