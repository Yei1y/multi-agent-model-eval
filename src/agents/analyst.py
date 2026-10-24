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
        return {"analysis": analysis}
