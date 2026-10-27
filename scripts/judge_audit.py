#!/usr/bin/env python
"""Judge audit: re-score an existing run's answers with a different judge.

Motivation
----------
A single LLM-as-judge run cannot separate three things: real quality差、judge 自偏好
（judge 给自家模型的回答打分更高）、位置偏差（放在前面的回答更容易得高分）。
This script holds the answers fixed and only swaps the judge / the answer order,
so any score change is attributable to the judge, not to the candidates.

Usage
-----
    python scripts/judge_audit.py --run runs/<run_id> \
        --judge doubao-seed-2-1-pro-260915 \
        --base-url-env ARK_BASE_URL --api-key-env ARK_API_KEY \
        --both-orders

Writes ``judge_audit_<judge>[_reversed].json`` into the run directory and prints
a comparison table against the original evaluations.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.evaluator import EvaluatorAgent  # noqa: E402
from src.llm import OpenAICompatibleLLM  # noqa: E402


def summarize(
    evaluations: list[dict[str, Any]], plan: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    dimension_keys = [dim["key"] for dim in plan["dimensions"]]
    by_model: dict[str, list[dict[str, Any]]] = {}
    for row in evaluations:
        by_model.setdefault(str(row["model"]), []).append(row)
    summary: dict[str, dict[str, Any]] = {}
    for model, rows in by_model.items():
        summary[model] = {
            "overall": round(sum(r["weighted_score"] for r in rows) / len(rows) * 20, 1),
            "pass_rate": round(sum(1 for r in rows if r["passed"]) / len(rows), 3),
            "dimensions": {
                key: round(sum(r["scores"][key] for r in rows) / len(rows), 2)
                for key in dimension_keys
            },
            "n": len(rows),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-judge a run with another judge model")
    parser.add_argument("--run", required=True, help="path to runs/<run_id>")
    parser.add_argument("--judge", required=True, help="judge model id")
    parser.add_argument("--base-url-env", default="LLM_BASE_URL")
    parser.add_argument("--api-key-env", default="LLM_API_KEY")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--thinking", default="disabled")
    parser.add_argument("--both-orders", action="store_true", help="also score with reversed order")
    parser.add_argument("--reverse", action="store_true", help="only score with reversed order")
    args = parser.parse_args()

    run_dir = Path(args.run)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    scenario = payload["scenario"]
    plan = payload["plan"]
    cases = payload["cases"]
    answers = payload["answers"]
    original = payload["evaluations"]

    base_url = os.getenv(args.base_url_env, "").strip()
    api_key = os.getenv(args.api_key_env, "").strip()
    if not (base_url and api_key):
        raise SystemExit(f"missing {args.base_url_env} / {args.api_key_env}")

    orders = [False, True] if args.both_orders else [args.reverse]
    baseline = summarize(original, plan)
    print("=== baseline (as recorded in run.json) ===")
    print(json.dumps(baseline, ensure_ascii=False, indent=2))

    results: dict[str, Any] = {"judge": args.judge, "orders": {}}
    for reversed_order in orders:
        client = OpenAICompatibleLLM(
            base_url=base_url,
            api_key=api_key,
            model=args.judge,
            temperature=args.temperature,
            thinking=args.thinking or None,
        )
        agent = EvaluatorAgent(client)
        used = list(reversed(answers)) if reversed_order else answers
        evaluations = agent.run(
            {
                "scenario": scenario,
                "plan": plan,
                "cases": cases,
                "answers": used,
                "mode": "real",
            }
        )["evaluations"]
        label = "reversed" if reversed_order else "normal"
        summary = summarize(evaluations, plan)
        tokens = sum(int(row.get("total_tokens", 0)) for row in client.usage)
        results["orders"][label] = {"summary": summary, "tokens": tokens}
        print(f"=== judge={args.judge} order={label} tokens={tokens} ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))

        suffix = "_reversed" if reversed_order else ""
        out = run_dir / f"judge_audit_{args.judge}{suffix}.json"
        out.write_text(
            json.dumps({"summary": summary, "evaluations": evaluations}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"written: {out}")

    # Absolute score deltas against the recorded judge.
    print("=== delta vs baseline (overall, 0-100) ===")
    for label, item in results["orders"].items():
        for model, row in item["summary"].items():
            base = baseline.get(model, {}).get("overall")
            delta = None if base is None else round(row["overall"] - base, 1)
            print(f"{label:8s} {model:12s} {row['overall']:5.1f}  (baseline {base}, delta {delta})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())