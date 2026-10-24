"""Planner: turns a business scenario into an evaluation plan."""

from __future__ import annotations

import math
from typing import Any

from .base import BaseAgent


class PlannerAgent(BaseAgent):
    name = "planner"
    system_prompt = (
        "你是企业大模型选型评测的 Planner。给定业务场景（domain/task/constraints/"
        "dimensions/models/case_mix），输出一个 JSON 对象："
        '{"plan": {"dimensions": [{"key","name","weight","description"}], '
        '"case_mix": {"normal": int, "edge": int, "adversarial": int, "multi_turn": int}, '
        '"pass_threshold": 3.0, "notes": [str]}}。'
        "维度权重之和必须为 1.0；不要改变场景给出的维度 key。只输出 JSON。"
    )

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = super().run(payload)
        plan = result.get("plan")
        if not isinstance(plan, dict):
            raise ValueError("planner output must contain a 'plan' object")
        dimensions = plan.get("dimensions")
        if not isinstance(dimensions, list) or not dimensions:
            raise ValueError("plan.dimensions must be a non-empty list")
        weight_sum = sum(float(d.get("weight", 0)) for d in dimensions)
        if not math.isclose(weight_sum, 1.0, abs_tol=1e-6):
            raise ValueError(f"plan dimension weights must sum to 1.0, got {weight_sum}")
        return {"plan": plan}
