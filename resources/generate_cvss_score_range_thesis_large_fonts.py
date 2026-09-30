#!/usr/bin/env python3
"""Recreate the thesis CVSS-range chart with larger typography only."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


RANGES = ["0-1", "1-2", "2-3", "3-4", "4-5", "5-6", "6-7", "7-8", "8-9", "9+"]
COUNTS = [2_779, 653, 4_194, 5_003, 34_247, 63_149, 57_111, 91_106, 41_857, 60_759]


def main() -> None:
    output = Path("/tmp/cvss_score_range_thesis_with_legend_large_fonts.pdf")

    fig, ax = plt.subplots(figsize=(12, 5))
    bars = ax.bar(
        RANGES,
        COUNTS,
        color="#1f77b4",
        edgecolor="#333333",
        linewidth=0.8,
        label="Vulnerabilities",
    )

    ax.set_xlabel("CVSS Score Range", fontsize=15)
    ax.set_ylabel("Number of vulnerabilities", fontsize=15)
    ax.set_ylim(0, 100_000)
    ax.set_yticks([0, 25_000, 50_000, 75_000, 100_000])
    ax.tick_params(axis="both", labelsize=13)
    ax.legend(loc="upper right", fontsize=13)

    for bar, value in zip(bars, COUNTS):
        ax.annotate(
            f"{value:,}",
            xy=(bar.get_x() + bar.get_width() / 2, value),
            xytext=(0, 5),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=12,
        )

    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    print(output)


if __name__ == "__main__":
    main()
