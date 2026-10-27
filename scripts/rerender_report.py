#!/usr/bin/env python
"""Re-render an existing run with recomputed aggregates and costs — no API calls.

Use it when the reporting layer changed (e.g. aggregates are now computed in
code, or unit prices were filled in later): the answers and evaluations on disk
stay untouched, only the derived summary/report are rebuilt.

Examples
--------
    # Recompute aggregates from evaluations (fixes analyst-narrated numbers)
    python scripts/rerender_report.py --run runs/<run_id>

    # Also apply unit prices (CNY per 1k tokens, input/output) to compute cost
    python scripts/rerender_report.py --run runs/<run_id> \
        --set-price candidate-a=0.0008/0.002 \
        --set-price candidate-b=0.004/0.016
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.analyst import AnalystAgent  # noqa: E402
from src.measurements import measure_models  # noqa: E402
from src.orchestrator import Orchestrator  # noqa: E402
from src.report import render_report  # noqa: E402


def parse_prices(values: list[str]) -> dict[str, tuple[float, float]]:
    prices: dict[str, tuple[float, float]] = {}
    for item in values:
        try:
            name, pair = item.split("=", 1)
            price_in, price_out = pair.split("/", 1)
            prices[name.strip()] = (float(price_in), float(price_out))
        except ValueError as exc:  # noqa: BLE001 - surface the exact bad argument
            raise SystemExit(f"bad --set-price value {item!r}; expected NAME=IN/OUT") from exc
    return prices


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-render a run without calling any model")
    parser.add_argument("--run", required=True)
    parser.add_argument(
        "--set-price",
        action="append",
        default=[],
        metavar="MODEL=IN/OUT",
        help="CNY per 1k tokens, e.g. candidate-a=0.0008/0.002",
    )
    args = parser.parse_args()

    run_dir = Path(args.run)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    scenario: dict[str, Any] = payload["scenario"]
    plan = payload["plan"]
    analysis = payload["analysis"]

    prices = parse_prices(args.set_price)
    for model in scenario.get("models", []):
        if model["name"] in prices:
            price_in, price_out = prices[model["name"]]
            model["price_input_per_1k"] = price_in
            model["price_output_per_1k"] = price_out

    before = {row["model"]: row["overall"] for row in analysis["summaries"]}

    # Answers recorded before the token-split existed: recover prompt/completion
    # from llm_usage.json, which logged every candidate call in the same order.
    usage_path = run_dir / "llm_usage.json"
    if usage_path.exists():
        calls_by_model: dict[str, list[dict[str, Any]]] = {}
        for call in json.loads(usage_path.read_text(encoding="utf-8")):
            agent = str(call.get("agent", ""))
            if agent.startswith("responder:"):
                calls_by_model.setdefault(agent.split(":", 1)[1], []).append(call)
        for model, calls in calls_by_model.items():
            answers = [row for row in payload["answers"] if row.get("model") == model]
            if len(answers) != len(calls):
                continue
            for answer, call in zip(answers, calls):
                if not answer.get("prompt_tokens") and not answer.get("completion_tokens"):
                    answer["prompt_tokens"] = int(call.get("prompt_tokens") or 0)
                    answer["completion_tokens"] = int(call.get("completion_tokens") or 0)

    # Rebuild every derived number from the recorded evaluations / answers.
    AnalystAgent._recompute_from_evaluations(analysis, payload)
    measurements = measure_models(payload["answers"], scenario.get("models"))
    payload["measurements"] = measurements
    AnalystAgent._apply_measurements(
        analysis, {"measurements": measurements, "scenario": scenario}
    )
    AnalystAgent._enforce_constraints(analysis)
    AnalystAgent._rewrite_numeric_prose(analysis, {"scenario": scenario})

    report = render_report(
        scenario=scenario,
        plan=plan,
        analysis=analysis,
        run_id=payload["run_id"],
        mode=payload.get("mode", "mock"),
        answers=payload.get("answers"),
        measurements=measurements,
    )
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    Orchestrator._write_summary_csv(run_dir / "summary.csv", plan, analysis["summaries"])
    payload["analysis"] = analysis
    (run_dir / "run.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"run: {run_dir}")
    print(f"{'model':14s} {'before':>7s} {'after':>7s} {'cost/case':>10s} {'tokens/case':>12s}")
    for row in analysis["summaries"]:
        cost = row.get("cost_per_case")
        cost_text = f"{float(cost):.4f}" if cost is not None else "—"
        print(
            f"{row['model']:14s} {before.get(row['model'], float('nan')):7.1f} "
            f"{row['overall']:7.1f} {cost_text:>10s} {int(row.get('tokens_per_case') or 0):12d}"
        )
    print(f"report: {run_dir / 'report.md'}")
    if not any(row.get("priced") for row in analysis["summaries"]):
        print("note: no unit prices set; cost columns stay empty (use --set-price)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())