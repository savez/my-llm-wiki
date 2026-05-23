#!/usr/bin/env python3
"""chart.py — Generate chart PNG for a view."""

from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUTPUT_DIR = Path(__file__).parent / "assets"
OUTPUT_NAME = "chart.png"

TITLE = "Chart title"
XLABEL = "X"
YLABEL = "Y"

labels = ["A", "B", "C"]
values = [12, 19, 7]


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(labels, values)
    ax.set_title(TITLE)
    ax.set_xlabel(XLABEL)
    ax.set_ylabel(YLABEL)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    fig.tight_layout()
    out = OUTPUT_DIR / OUTPUT_NAME
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
