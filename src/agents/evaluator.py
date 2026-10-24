"""Evaluator: scores every candidate model on every test case."""

from __future__ import annotations

from typing import Any

from .base import BaseAgent


class EvaluatorAgent(BaseAgent):
    name = "evaluator"
    system_prompt = (
        "你是模型评测员。对每个候选模型、每条测试用例，按评测计划的维度打 1–5 分"
        "（1=明显不满足，3=基本满足，5=优秀），并给出简短理由。输出 JSON："
        '{"evaluations": [{"case_id": str, "model": str, '
        '"scores": {"<dimension_key>": 1-5}, "weighted_score": float, '
        '"passed": bool, "rationale": str}]}。'
        "weighted_score 必须等于各维度分按权重加权的和；只输出 JSON。"
    )

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = super().run(payload)
        evaluations = result.get("evaluations")
        if not isinstance(evaluations, list) or not evaluations:
            raise ValueError("evaluator output must contain a non-empty 'evaluations' list")
        for row in evaluations:
            scores = row.get("scores")
            if not isinstance(scores, dict) or not scores:
                raise ValueError("each evaluation needs a non-empty scores object")
        return {"evaluations": evaluations}
