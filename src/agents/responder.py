"""Responder: asks every candidate model to actually answer every test case.

This is the step the original five-agent version was missing. Without it the
Evaluator only saw case descriptions plus model *names*, so its scores were an
opinion about a model rather than a measurement of one. The Responder produces
the ``answers`` list that makes the judge's scores traceable to real text.
"""

from __future__ import annotations

import random
import time
from typing import Any

from .. import mock_engine
from ..llm import BaseLLM
from .base import BaseAgent


class ResponderAgent(BaseAgent):
    name = "responder"
    system_prompt = (
        "你是一名电商/金融场景的在线客服。请直接回答用户的最后一条问题："
        "给出可执行的步骤，不编造政策与承诺，不索取或泄露他人隐私信息，"
        "长度控制在 200 字以内。不要输出 JSON，只输出给用户看的回答正文。"
    )

    def __init__(
        self,
        llm: BaseLLM,
        mode: str = "mock",
        candidate_llms: dict[str, BaseLLM] | None = None,
    ) -> None:
        super().__init__(llm)
        self.mode = mode
        self.candidate_llms = candidate_llms or {}

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.mode == "mock":
            # Mock mode: answers exist so the pipeline has the right shape, but
            # they are synthetic text and carry no latency/token measurements.
            return self.llm.structured(self.name, self.system_prompt, payload)
        return {"answers": self._collect_real(payload)}

    # ------------------------------------------------------------------
    # Real mode
    # ------------------------------------------------------------------

    def _collect_real(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        scenario = payload["scenario"]
        cases = payload["cases"]
        answers: list[dict[str, Any]] = []
        for model in scenario["models"]:
            name = str(model["name"])
            if model.get("provider") != "real":
                answers.extend(self._mock_rows(scenario, cases, model))
                continue
            llm = self.candidate_llms.get(name)
            if llm is None:
                raise ValueError(
                    f"candidate model {name} has no client; "
                    "check base_url_env / api_key_env in the scenario"
                )
            for case in cases:
                answers.append(self._ask(llm, name, scenario, case))
        return answers

    def _ask(
        self,
        llm: BaseLLM,
        name: str,
        scenario: dict[str, Any],
        case: dict[str, Any],
    ) -> dict[str, Any]:
        system = self.system_prompt.replace("电商/金融场景", str(scenario.get("domain", "")))
        user_text = self._user_text(case)
        usage_before = len(getattr(llm, "usage", []))
        started = time.perf_counter()
        text = llm.chat(f"responder:{name}", system, user_text)
        wall_ms = round((time.perf_counter() - started) * 1000, 1)
        usage = getattr(llm, "usage", [])
        call = usage[len(usage) - 1] if len(usage) > usage_before else {}
        duration = call.get("duration_ms")
        return {
            "case_id": case["id"],
            "model": name,
            "answer": text.strip(),
            "provider": "real",
            "latency_ms": float(duration) if duration is not None else wall_ms,
            "prompt_tokens": int(call.get("prompt_tokens") or 0),
            "completion_tokens": int(call.get("completion_tokens") or 0),
            "total_tokens": int(call.get("total_tokens") or 0),
        }

    @staticmethod
    def _user_text(case: dict[str, Any]) -> str:
        turns = case.get("turns") or []
        if turns:
            return "\n".join(f"用户：{turn}" for turn in turns)
        return f"用户：{case['input']}"

    @staticmethod
    def _mock_rows(
        scenario: dict[str, Any], cases: list[dict[str, Any]], model: dict[str, Any]
    ) -> list[dict[str, Any]]:
        rows = []
        for case in cases:
            rng = random.Random(f"{scenario.get('seed', 42)}:{case['id']}:{model['name']}")
            rows.append(
                {
                    "case_id": case["id"],
                    "model": model["name"],
                    "answer": mock_engine.mock_answer_text(scenario, case, model, rng),
                    "provider": "mock",
                    "latency_ms": 0.0,
                    "total_tokens": 0,
                }
            )
        return rows


__all__ = ["ResponderAgent"]