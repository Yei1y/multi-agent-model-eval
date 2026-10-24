"""LLM adapters.

Two implementations share one interface:

* ``MockLLM`` returns deterministic synthetic outputs so the pipeline runs
  offline, with no API key. It is the default mode for demos and CI.
* ``OpenAICompatibleLLM`` calls any OpenAI-compatible ``/chat/completions``
  endpoint (Volcengine Ark, DeepSeek, vLLM, etc.). It is only used when the
  operator explicitly sets the environment variables and passes ``--mode real``.
"""

from __future__ import annotations

import json
import http.client
import os
import random
import time
import urllib.error
import urllib.request
from typing import Any

from . import mock_engine
from .schemas import Scenario


class LLMError(RuntimeError):
    """Raised when a real LLM call fails after retries."""


class BaseLLM:
    def __init__(self) -> None:
        self.usage: list[dict[str, Any]] = []

    def structured(self, agent: str, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class MockLLM(BaseLLM):
    """Deterministic, offline stand-in for a real model."""

    _AGENTS = ("planner", "case_designer", "evaluator", "analyst", "reporter")

    def __init__(self, seed: int = 42) -> None:
        super().__init__()
        self.seed = seed
        self._rngs = {name: random.Random(seed + index) for index, name in enumerate(self._AGENTS)}

    def _rng(self, agent: str) -> random.Random:
        return self._rngs[agent]

    def structured(self, agent: str, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        if agent == "planner":
            return {"plan": mock_engine.generate_plan(payload["scenario"], self._rng(agent))}
        if agent == "case_designer":
            return mock_engine.generate_cases(
                payload["scenario"], payload["plan"], self._rng(agent)
            )
        if agent == "evaluator":
            return mock_engine.generate_evaluations(
                payload["scenario"],
                payload["plan"],
                payload["cases"],
                self._rng(agent),
            )
        if agent == "analyst":
            return {
                "analysis": mock_engine.summarize(
                    payload["scenario"],
                    payload["plan"],
                    payload["cases"],
                    payload["evaluations"],
                )
            }
        if agent == "reporter":
            from .report import render_report

            return {
                "report_markdown": render_report(
                    scenario=payload["scenario"],
                    plan=payload["plan"],
                    analysis=payload["analysis"],
                    run_id=payload["run_id"],
                    mode=payload.get("mode", "mock"),
                )
            }
        raise LLMError(f"unknown mock agent: {agent}")


class OpenAICompatibleLLM(BaseLLM):
    """Minimal chat-completions client with JSON output and retries."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 180,
        max_retries: int = 2,
        max_tokens: int = 8192,
        thinking: str | None = None,
    ) -> None:
        super().__init__()
        if not base_url or not api_key or not model:
            raise ValueError("base_url, api_key and model are required for real mode")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self.thinking = thinking

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def structured(self, agent: str, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": self.model,
            "temperature": 0.1,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
        }
        if self.thinking:
            body["thinking"] = {"type": self.thinking}
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            started = time.perf_counter()
            try:
                response = self._post(body)
                duration_ms = round((time.perf_counter() - started) * 1000, 1)
                usage = response.get("usage") or {}
                self.usage.append(
                    {
                        "agent": agent,
                        "model": self.model,
                        "attempt": attempt + 1,
                        "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                        "completion_tokens": int(usage.get("completion_tokens", 0)),
                        "total_tokens": int(
                            usage.get(
                                "total_tokens",
                                int(usage.get("prompt_tokens", 0))
                                + int(usage.get("completion_tokens", 0)),
                            )
                        ),
                        "duration_ms": duration_ms,
                    }
                )
                content = response["choices"][0]["message"]["content"].strip()
                if content.startswith("```"):
                    content = content.strip("`")
                    if content.lower().startswith("json"):
                        content = content[4:]
                return json.loads(content)
            except (
                KeyError,
                json.JSONDecodeError,
                urllib.error.URLError,
                TimeoutError,
                ConnectionError,
                http.client.RemoteDisconnected,
            ) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"agent={agent} failed after {self.max_retries + 1} attempts: {last_error}")


def build_llm(mode: str, scenario: Scenario) -> BaseLLM:
    if mode == "mock":
        return MockLLM(seed=scenario.seed)
    if mode != "real":
        raise ValueError(f"unknown mode: {mode}")
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    if not (base_url and api_key and model):
        raise ValueError(
            "real mode requires LLM_BASE_URL, LLM_API_KEY and LLM_MODEL; "
            "use --mode mock to run without a key"
        )
    thinking = os.getenv("LLM_THINKING", "").strip() or None
    return OpenAICompatibleLLM(
        base_url=base_url, api_key=api_key, model=model, thinking=thinking
    )
