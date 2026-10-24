"""Static score chart for the README (PNG, GitHub-friendly)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def render_score_chart(summaries: list[dict[str, Any]], out_path: str | Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    if not summaries:
        raise ValueError("no summaries to plot")
    out_path = Path(out_path)
    dimension_keys = list(summaries[0]["dimension_scores"].keys())
    labels = [key.replace("_", " ").title() for key in dimension_keys]
    models = [row["model"] for row in summaries]
    palette = ["#4DBBD5", "#F39B7F", "#00A087", "#91D1C2", "#8491B4", "#FCC5A1"]

    fig, (ax_left, ax_right) = plt.subplots(
        1, 2, figsize=(11.5, 4.4), gridspec_kw={"width_ratios": [1.55, 1.0]}
    )
    x = np.arange(len(labels))
    width = 0.8 / max(len(models), 1)
    for index, row in enumerate(summaries):
        values = [row["dimension_scores"].get(key, 0.0) for key in dimension_keys]
        ax_left.bar(
            x + index * width,
            values,
            width,
            label=row["model"],
            color=palette[index % len(palette)],
        )
    ax_left.set_xticks(x + width * (len(models) - 1) / 2)
    ax_left.set_xticklabels(labels, fontsize=9)
    ax_left.set_ylim(1, 5)
    ax_left.axhline(3.0, color="#999999", linestyle="--", linewidth=0.8)
    ax_left.set_ylabel("Score (1–5)", fontsize=9)
    ax_left.set_title("Dimension scores", fontsize=11)
    ax_left.legend(frameon=False, fontsize=8, ncol=len(models))
    ax_left.grid(axis="y", alpha=0.2)

    overall = [row["overall"] for row in summaries]
    colors = [
        palette[index % len(palette)] if row["meets_constraints"] else "#CCCCCC"
        for index, row in enumerate(summaries)
    ]
    y = np.arange(len(models))
    ax_right.barh(y, overall, color=colors)
    for index, value in enumerate(overall):
        ax_right.text(value + 1.5, index, f"{value:.1f}", va="center", fontsize=9)
    ax_right.set_yticks(y)
    ax_right.set_yticklabels(models, fontsize=9)
    ax_right.set_xlim(0, 100)
    ax_right.set_xlabel("Overall score (0–100)", fontsize=9)
    ax_right.set_title("Overall score (grey = constraint not met)", fontsize=10)
    ax_right.grid(axis="x", alpha=0.2)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return out_path
