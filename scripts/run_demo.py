#!/usr/bin/env python
"""CLI entry point for the multi-agent model-selection evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm import build_llm  # noqa: E402
from src.orchestrator import Orchestrator  # noqa: E402
from src.schemas import Scenario  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the multi-agent model evaluation workflow")
    parser.add_argument(
        "--scenario",
        default="data/scenarios/ecommerce_customer_service.yaml",
        help="path to a scenario YAML",
    )
    parser.add_argument("--mode", choices=["mock", "real"], default="mock")
    parser.add_argument("--out", default="runs", help="run directory root")
    parser.add_argument(
        "--chart",
        default="docs/assets/model_scores.png",
        help="path for the score chart (use a different path for real runs)",
    )
    parser.add_argument("--seed", type=int, default=None, help="override the scenario seed")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scenario_path = Path(args.scenario)
    if not scenario_path.is_absolute():
        scenario_path = ROOT / scenario_path
    scenario = Scenario.from_yaml(scenario_path)
    if args.seed is not None:
        scenario.seed = args.seed
    llm = build_llm(args.mode, scenario)
    orchestrator = Orchestrator(
        scenario=scenario,
        llm=llm,
        out_root=ROOT / args.out,
        mode=args.mode,
        chart_path=ROOT / args.chart,
    )
    result = orchestrator.run()
    usage = getattr(llm, "usage", [])
    summary = {
        "run_dir": str(result.run_dir),
        "report": str(result.report_path),
        "recommendation": result.analysis["recommendation"],
        "rationale": result.analysis["rationale"],
        "scores": {row["model"]: row["overall"] for row in result.analysis["summaries"]},
        "total_tokens": sum(int(row.get("total_tokens", 0)) for row in usage),
        "total_llm_duration_ms": round(
            sum(float(row.get("duration_ms", 0.0)) for row in usage), 1
        ),
        "llm_usage": usage,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
