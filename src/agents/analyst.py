"""Analyst: aggregates scores, clusters failures and recommends a model."""

from __future__ import annotations

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
        return {"analysis": analysis}

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
