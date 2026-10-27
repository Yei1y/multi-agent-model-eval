"""Analyst: aggregates scores, clusters failures and recommends a model."""

from __future__ import annotations

from collections import defaultdict
from math import inf
from typing import Any

from .base import BaseAgent


class AnalystAgent(BaseAgent):
    name = "analyst"
    system_prompt = (
        "你是评测分析师。输入为场景、评测计划、用例和逐条评分。输出 JSON："
        '{"analysis": {"summaries": [{"model","overall","dimension_scores",'
        '"pass_rate","cost_per_1k","latency_ms","meets_constraints"}], '
        '"failures": [{"tag","count","models","example_case_ids"}], '
        '"recommendation": str, "rationale": str, "tradeoffs": [str]}}。'
        "综合分按 0–100 报告；推荐时必须先满足延迟/成本约束，再比较综合分；"
        "如果所有模型都超约束，要明确指出。只输出 JSON。"
    )

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = super().run(payload)
        analysis = result.get("analysis")
        if not isinstance(analysis, dict):
            raise ValueError("analyst output must contain an 'analysis' object")
        if not analysis.get("summaries") or not analysis.get("recommendation"):
            raise ValueError("analysis needs summaries and a recommendation")
        self._normalize_units(analysis)
        self._recompute_from_evaluations(analysis, payload)
        self._apply_measurements(analysis, payload)
        self._enforce_constraints(analysis)
        self._rewrite_numeric_prose(analysis, payload)
        return {"analysis": analysis}

    # ------------------------------------------------------------------
    # Numbers belong to the code, prose belongs to the model
    # ------------------------------------------------------------------

    @staticmethod
    def _recompute_from_evaluations(
        analysis: dict[str, Any], payload: dict[str, Any]
    ) -> None:
        """Overwrite overall / dimension / pass-rate with arithmetic on evaluations.

        Real runs showed the analyst reporting 87.0 while its own evaluations
        averaged 89.8. Any aggregate a reader may quote has to be recomputed,
        not narrated.
        """
        evaluations = payload.get("evaluations") or []
        dimensions = [d["key"] for d in (payload.get("plan") or {}).get("dimensions", [])]
        if not evaluations or not dimensions:
            return

        by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in evaluations:
            by_model[str(row["model"])].append(row)

        existing = {str(row.get("model")): row for row in analysis.get("summaries", [])}
        for model, rows in by_model.items():
            overall = round(sum(float(r["weighted_score"]) for r in rows) / len(rows) * 20, 1)
            dimension_scores = {
                key: round(sum(float(r["scores"][key]) for r in rows) / len(rows), 2)
                for key in dimensions
            }
            pass_rate = round(sum(1 for r in rows if r["passed"]) / len(rows), 3)
            row = existing.get(model)
            if row is None:
                row = {
                    "model": model,
                    "overall": overall,
                    "dimension_scores": dimension_scores,
                    "pass_rate": pass_rate,
                    "cost_per_1k": 0.0,
                    "latency_ms": 0,
                    "meets_constraints": True,
                    "rationale": "",
                }
                analysis.setdefault("summaries", []).append(row)
            else:
                row["overall"] = overall
                row["dimension_scores"] = dimension_scores
                row["pass_rate"] = pass_rate

    @staticmethod
    def _apply_measurements(analysis: dict[str, Any], payload: dict[str, Any]) -> None:
        """Overwrite latency/token fields with values recorded from real calls.

        A judge LLM cannot know how long a candidate took; letting it fill these
        fields is how fabricated numbers end up in a report.
        """
        measurements = payload.get("measurements") or {}
        if not measurements:
            return
        constraints = (payload.get("scenario") or {}).get("constraints", {})
        max_latency = float(constraints.get("max_latency_ms", inf))
        max_cost = float(constraints.get("max_cost_per_1k", inf))
        for row in analysis["summaries"]:
            measurement = measurements.get(str(row.get("model", "")))
            if not measurement:
                continue
            latency = int(measurement.get("latency_ms") or row.get("latency_ms") or 0)
            priced = bool(measurement.get("priced"))
            cost_per_1k = (
                float(measurement["cost_per_1k"])
                if priced and measurement.get("cost_per_1k") is not None
                else float(row.get("cost_per_1k") or 0.0)
            )
            row["latency_ms"] = latency
            row["cost_per_1k"] = cost_per_1k
            row["cost_per_case"] = measurement.get("cost_per_case")
            row["cost_total"] = measurement.get("cost_total")
            row["tokens_in"] = int(measurement.get("tokens_in_per_case") or 0)
            row["tokens_out"] = int(measurement.get("tokens_out_per_case") or 0)
            row["tokens_per_case"] = int(measurement.get("tokens_per_case") or 0)
            row["priced"] = priced
            row["latency_source"] = "measured" if measurement.get("measured") else "config"
            row["meets_constraints"] = bool(
                latency <= max_latency and cost_per_1k <= max_cost
            )

    @staticmethod
    def _rewrite_numeric_prose(analysis: dict[str, Any], payload: dict[str, Any]) -> None:
        """Regenerate the number-bearing prose from the computed summaries.

        A live run showed the analyst writing "87.0 vs 78.0" while its own
        evaluations implied 89.8 vs 80.0. Qualitative reasoning is the model's
        job; any sentence a reader may quote must be rebuilt from the data.
        """
        summaries = analysis.get("summaries") or []
        if not summaries:
            return
        constraints = (payload.get("scenario") or {}).get("constraints", {})
        max_latency = float(constraints.get("max_latency_ms", inf))
        max_cost = float(constraints.get("max_cost_per_1k", inf))

        eligible = [row for row in summaries if row.get("meets_constraints")]
        if eligible:
            best = max(eligible, key=lambda row: float(row.get("overall", 0.0)))
            rationale = (
                f"在满足延迟与成本约束的模型中，{best['model']} 的综合分最高"
                f"（{float(best['overall']):.1f}）。"
            )
            excluded = sorted(
                [row for row in summaries if not row.get("meets_constraints")],
                key=lambda row: -float(row.get("overall", 0.0)),
            )
            if excluded:
                top = excluded[0]
                rationale += (
                    f"原始分更高的 {top['model']}（{float(top['overall']):.1f}）"
                    f"因超过延迟 {max_latency:.0f}ms 或成本 {max_cost:.3f}/千 token 的约束被排除。"
                )
        else:
            best = max(summaries, key=lambda row: float(row.get("overall", 0.0)))
            rationale = (
                f"没有候选模型同时满足延迟与成本约束；按综合分推荐 {best['model']}"
                f"（{float(best['overall']):.1f}），但需要先确认约束是否可以放宽。"
            )
        analysis["recommendation"] = str(best["model"])
        analysis["rationale"] = rationale
        analysis["tradeoffs"] = [
            (
                f"{row['model']}：综合 {float(row.get('overall', 0.0)):.1f}，"
                f"延迟 {int(row.get('latency_ms') or 0)}ms，"
                f"成本 {float(row.get('cost_per_1k') or 0.0):.3f}/千 token，"
                f"{'满足' if row.get('meets_constraints') else '不满足'}约束"
            )
            for row in summaries
        ]

    @staticmethod
    def _enforce_constraints(analysis: dict[str, Any]) -> None:
        """Never recommend a model that the computed constraints already exclude."""
        summaries = analysis.get("summaries") or []
        eligible = [row for row in summaries if row.get("meets_constraints")]
        if not eligible:
            return
        recommended = str(analysis.get("recommendation", ""))
        if recommended in {str(row.get("model")) for row in eligible}:
            return
        best = max(eligible, key=lambda row: float(row.get("overall", 0.0)))
        analysis["recommendation"] = str(best.get("model"))
        note = f"（约束复核：{best.get('model')} 是满足延迟/成本约束的模型中综合分最高者）"
        rationale = str(analysis.get("rationale", "")).strip()
        analysis["rationale"] = f"{rationale}{note}" if rationale else note

    @staticmethod
    def _normalize_units(analysis: dict[str, Any]) -> None:
        """Accept either 0–1 or 0–100 summaries and normalize to the report contract.

        The mock engine emits 1–5 dimensions and 0–1 pass rates. Real LLMs often
        answer in 0–100, which produced ``10000%`` in an early real run; this
        guard keeps the report contract stable without trusting prompt wording.
        """
        for row in analysis["summaries"]:
            overall = float(row.get("overall", 0.0))
            if 0.0 < overall <= 1.0:
                overall *= 100.0
            elif 0.0 < overall <= 5.0:
                overall *= 20.0
            row["overall"] = round(min(100.0, max(0.0, overall)), 1)

            dimensions = row.get("dimension_scores") or {}
            if dimensions:
                values = [float(value) for value in dimensions.values()]
                max_value = max(values)
                if max_value > 5.0:
                    row["dimension_scores"] = {
                        key: round(float(value) / 20.0, 2)
                        for key, value in dimensions.items()
                    }
                elif max_value <= 1.0:
                    row["dimension_scores"] = {
                        key: round(float(value) * 5.0, 2)
                        for key, value in dimensions.items()
                    }

            pass_rate = float(row.get("pass_rate", 0.0))
            if pass_rate > 1.0:
                pass_rate /= 100.0
            row["pass_rate"] = round(min(1.0, max(0.0, pass_rate)), 3)

        # An LLM analyst may list "failure" tags even when every evaluation passed.
        # Keep the report internally consistent: no failed evaluations -> no clusters.
        if all(float(row.get("pass_rate", 0.0)) >= 1.0 for row in analysis["summaries"]):
            analysis["failures"] = []
