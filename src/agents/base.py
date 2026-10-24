"""Shared agent interface. Each agent owns one step of the evaluation workflow."""

from __future__ import annotations

from typing import Any

from ..llm import BaseLLM


class BaseAgent:
    name = "base"
    system_prompt = "You are a helpful assistant."

    def __init__(self, llm: BaseLLM) -> None:
        self.llm = llm

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.llm.structured(self.name, self.system_prompt, payload)
        if not isinstance(result, dict):
            raise ValueError(f"{self.name} must return a JSON object, got {type(result)!r}")
        return result
