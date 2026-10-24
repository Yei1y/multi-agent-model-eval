"""Sequential orchestrator with a task ledger.

The design is deliberately closer to Magentic-One's orchestrator/ledger idea
than to a heavy framework: each step is a named agent, every input/output is
recorded, and the run directory is the single source of truth.
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .agents import (
    AnalystAgent,
    CaseDesignerAgent,
    EvaluatorAgent,
    PlannerAgent,
    ReporterAgent,
)
from .charts import render_score_chart
from .llm import BaseLLM
from .schemas import Scenario


@dataclass
class RunResult:
    run_dir: Path
    analysis: dict[str, Any]
    report_path: Path
    ledger_path: Path


class Orchestrator:
    def __init__(
        self,
        scenario: Scenario,
        llm: BaseLLM,
        out_root: str | Path = "runs",
        mode: str = "mock",
        chart_path: str | Path = "docs/assets/model_scores.png",
    ) -> None:
        self.scenario = scenario
        self.llm = llm
        self.out_root = Path(out_root)
        self.mode = mode
        self.chart_path = Path(chart_path)

    def run(self) -> RunResult:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + self.scenario.name
        run_dir = self._unique_dir(self.out_root / run_id)
        run_dir.mkdir(parents=True)
        ledger_path = run_dir / "task_ledger.jsonl"
        scenario_dict = self.scenario.to_dict()

        plan = self._step(
            "planner",
            PlannerAgent(self.llm),
            {"scenario": scenario_dict},
            "plan",
            ledger_path,
        )["plan"]
        cases = self._step(
            "case_designer",
            CaseDesignerAgent(self.llm),
            {"scenario": scenario_dict, "plan": plan},
            "cases",
            ledger_path,
        )["cases"]
        evaluations = self._step(
            "evaluator",
            EvaluatorAgent(self.llm),
            {"scenario": scenario_dict, "plan": plan, "cases": cases},
            "evaluations",
            ledger_path,
        )["evaluations"]
        analysis = self._step(
            "analyst",
            AnalystAgent(self.llm),
            {
                "scenario": scenario_dict,
                "plan": plan,
                "cases": cases,
                "evaluations": evaluations,
            },
            "analysis",
            ledger_path,
        )["analysis"]
        report_markdown = self._step(
            "reporter",
            ReporterAgent(self.llm),
            {
                "scenario": scenario_dict,
                "plan": plan,
                "analysis": analysis,
                "run_id": run_id,
                "mode": self.mode,
            },
            "report_markdown",
            ledger_path,
        )["report_markdown"]

        (run_dir / "report.md").write_text(report_markdown, encoding="utf-8")
        self._write_evaluations_csv(run_dir / "evaluations.csv", plan, evaluations)
        self._write_summary_csv(run_dir / "summary.csv", plan, analysis["summaries"])
        payload = {
            "run_id": run_id,
            "mode": self.mode,
            "scenario": scenario_dict,
            "plan": plan,
            "cases": cases,
            "evaluations": evaluations,
            "analysis": analysis,
            "report": "report.md",
            "evaluations_csv": "evaluations.csv",
            "summary_csv": "summary.csv",
            "task_ledger": "task_ledger.jsonl",
        }
        (run_dir / "run.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        self.chart_path.parent.mkdir(parents=True, exist_ok=True)
        render_score_chart(analysis["summaries"], self.chart_path)

        return RunResult(
            run_dir=run_dir,
            analysis=analysis,
            report_path=run_dir / "report.md",
            ledger_path=ledger_path,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _unique_dir(candidate: Path) -> Path:
        if not candidate.exists():
            return candidate
        for index in range(1, 100):
            alternative = candidate.with_name(f"{candidate.name}-{index}")
            if not alternative.exists():
                return alternative
        raise RuntimeError(f"cannot allocate a unique run directory under {candidate.parent}")

    def _step(
        self,
        name: str,
        agent: Any,
        payload: dict[str, Any],
        value_key: str,
        ledger_path: Path,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        record: dict[str, Any] = {
            "step": name,
            "agent": agent.name,
            "status": "ok",
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            result = agent.run(payload)
        except Exception as exc:  # noqa: BLE001 - we must log the failing step
            record.update(status="error", error=str(exc))
            record["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
            self._append_ledger(ledger_path, record)
            raise
        if value_key not in result:
            raise ValueError(f"{name} output missing key: {value_key}")
        record["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        record["summary"] = self._summarize_step(name, result[value_key])
        self._append_ledger(ledger_path, record)
        return result

    @staticmethod
    def _summarize_step(name: str, value: Any) -> str:
        if name == "planner":
            return f"{len(value.get('dimensions', []))} dimensions, case mix {value.get('case_mix')}"
        if name == "case_designer":
            return f"{len(value)} cases"
        if name == "evaluator":
            return f"{len(value)} evaluations"
        if name == "analyst":
            return (
                f"recommendation={value.get('recommendation')}, "
                f"models={len(value.get('summaries', []))}"
            )
        if name == "reporter":
            return f"{len(str(value))} chars"
        return "ok"

    @staticmethod
    def _append_ledger(path: Path, record: dict[str, Any]) -> None:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _write_evaluations_csv(
        path: Path, plan: dict[str, Any], evaluations: list[dict[str, Any]]
    ) -> None:
        dimension_keys = [d["key"] for d in plan["dimensions"]]
        fieldnames = ["case_id", "model", *dimension_keys, "weighted_score", "passed"]
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in evaluations:
                flat = {
                    "case_id": row["case_id"],
                    "model": row["model"],
                    "weighted_score": row["weighted_score"],
                    "passed": row["passed"],
                }
                for key in dimension_keys:
                    flat[key] = row["scores"].get(key)
                writer.writerow(flat)

    @staticmethod
    def _write_summary_csv(
        path: Path, plan: dict[str, Any], summaries: list[dict[str, Any]]
    ) -> None:
        dimension_keys = [d["key"] for d in plan["dimensions"]]
        fieldnames = [
            "model",
            "overall",
            *dimension_keys,
            "pass_rate",
            "cost_per_1k",
            "latency_ms",
            "meets_constraints",
        ]
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in summaries:
                flat = {
                    "model": row["model"],
                    "overall": row["overall"],
                    "pass_rate": row["pass_rate"],
                    "cost_per_1k": row["cost_per_1k"],
                    "latency_ms": row["latency_ms"],
                    "meets_constraints": row["meets_constraints"],
                }
                for key in dimension_keys:
                    flat[key] = row["dimension_scores"].get(key)
                writer.writerow(flat)
