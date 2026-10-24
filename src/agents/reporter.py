"""Reporter: renders the final selection memo deterministically.

The report is intentionally template-based rather than LLM-written: it keeps
tables and numbers exactly aligned with the evaluation artifacts, and it avoids
an extra API call. The other four agents still do the reasoning.
"""

from __future__ import annotations

from typing import Any

from .base import BaseAgent


class ReporterAgent(BaseAgent):
    name = "reporter"

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        from ..report import render_report

        markdown = render_report(
            scenario=payload["scenario"],
            plan=payload["plan"],
            analysis=payload["analysis"],
            run_id=payload["run_id"],
            mode=payload.get("mode", "mock"),
        )
        return {"report_markdown": markdown}
