"""LLM adapters.

Two implementations share one interface:

* ``MockLLM`` returns deterministic synthetic outputs so the pipeline runs
  offline, with no API key. It is the default mode for demos and CI.
* ``OpenAICompatibleLLM`` talks to any OpenAI-compatible ``/chat/completions``
  endpoint (Volcengine Ark, DeepSeek, vLLM, etc.). It is used both as the
  workflow's own "brain" and as the client for each candidate model, so the
  candidates really get called instead of being described by name.

Two call shapes matter:

* ``structured()`` asks for JSON and returns a parsed ``dict`` (agent I/O).
* ``chat()`` returns plain text (candidate answers, which are free-form).
"""

from __future__ import annotations

import http.client
import json
import os
import random
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from . import mock_engine
from .schemas import ModelCandidate, Scenario


class LLMError(RuntimeError):
    """Raised when a real LLM call fails after retries."""


def _load_json_object(content: str) -> dict[str, Any]:
    """Parse one JSON object, tolerating Markdown code fences."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed


class BaseLLM:
    def __init__(self) -> None:
        self.usage: list[dict[str, Any]] = []

    def structured(self, agent: str, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def chat(self, agent: str, system: str, user_text: str) -> str:
        raise NotImplementedError


class MockLLM(BaseLLM):
    """Deterministic, offline stand-in for a real model."""

    # ``responder`` is appended last on purpose: indices feed the per-agent seeds,
    # so inserting it earlier would silently change every documented mock score.
    _AGENTS = ("planner", "case_designer", "evaluator", "analyst", "reporter", "responder")

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
        if agent == "responder":
            return mock_engine.generate_answers(
                payload["scenario"],
                payload["plan"],
                payload["cases"],
                self._rng(agent),
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
                    payload.get("answers"),
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
                    answers=payload.get("answers"),
                    measurements=payload.get("measurements"),
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
        temperature: float | None = None,
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
        # Callers may pin the temperature (some models accept exactly one value).
        self.temperature = temperature

    def _temperature(self, default: float) -> float:
        return float(self.temperature) if self.temperature is not None else default

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

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

    def _call(
        self, agent: str, body: dict[str, Any], converter: Callable[[str], Any]
    ) -> Any:
        """POST with retries. ``converter`` runs inside the try block so that a
        malformed JSON body is retried like any other transient failure."""
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
                return converter(content)
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

    # ------------------------------------------------------------------
    # Call shapes
    # ------------------------------------------------------------------

    def structured(self, agent: str, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": self.model,
            "temperature": self._temperature(0.1),
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
        return self._call(agent, body, _load_json_object)

    def chat(self, agent: str, system: str, user_text: str) -> str:
        """Free-form answer generation; used to interrogate candidate models."""
        body = {
            "model": self.model,
            "temperature": self._temperature(0.3),
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
        }
        return self._call(agent, body, lambda content: content)


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _resolve_ref(value: str) -> str:
    """Resolve ``env:NAME`` indirection so scenarios never hard-code secrets."""
    text = (value or "").strip()
    if text.startswith("env:"):
        return _env(text[4:])
    return text


def build_llm(mode: str, scenario: Scenario) -> BaseLLM:
    if mode == "mock":
        return MockLLM(seed=scenario.seed)
    if mode != "real":
        raise ValueError(f"unknown mode: {mode}")
    base_url = _env("LLM_BASE_URL")
    api_key = _env("LLM_API_KEY")
    model = _env("LLM_MODEL")
    if not (base_url and api_key and model):
        raise ValueError(
            "real mode requires LLM_BASE_URL, LLM_API_KEY and LLM_MODEL; "
            "use --mode mock to run without a key"
        )
    thinking = _env("LLM_THINKING") or None
    raw_temperature = _env("LLM_TEMPERATURE")
    temperature = float(raw_temperature) if raw_temperature else None
    return OpenAICompatibleLLM(
        base_url=base_url,
        api_key=api_key,
        model=model,
        thinking=thinking,
        temperature=temperature,
    )


def build_candidate_llm(model: ModelCandidate) -> OpenAICompatibleLLM:
    """Client for one candidate model, configured from the scenario entry.

    Endpoint and key come from the environment variables named in the YAML, so
    the same scenario file can be shared without leaking credentials.
    """
    base_url = _resolve_ref(model.base_url) if model.base_url else _env(model.base_url_env)
    api_key = _env(model.api_key_env)
    model_id = _resolve_ref(model.model_id)
    missing = [
        label
        for label, value in (
            ("base_url", base_url),
            (f"api_key ({model.api_key_env})", api_key),
            ("model_id", model_id),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            f"candidate model {model.name} is missing {', '.join(missing)}; "
            "set the environment variables referenced by the scenario"
        )
    return OpenAICompatibleLLM(
        base_url=base_url,
        api_key=api_key,
        model=model_id,
        thinking=model.thinking,
        temperature=model.temperature,
    )


def build_candidate_llms(scenario: Scenario) -> dict[str, OpenAICompatibleLLM]:
    """Fail fast: every real candidate must be callable before any money is spent."""
    clients: dict[str, OpenAICompatibleLLM] = {}
    for model in scenario.models:
        if model.provider == "real":
            clients[model.name] = build_candidate_llm(model)
    return clients