"""Typed schemas shared by agents, the orchestrator and the report renderer."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

CATEGORIES = ("normal", "edge", "adversarial", "multi_turn")


@dataclass
class Dimension:
    key: str
    name: str
    weight: float
    description: str = ""


@dataclass
class ModelCandidate:
    name: str
    provider: str = "mock"
    model_id: str = ""
    cost_per_1k: float = 0.0
    latency_ms: int = 0
    # Mock-only capability profile in [0, 1]. Never used in real mode.
    profile: dict[str, float] = field(default_factory=dict)
    # Real-mode wiring: env var names holding the endpoint and the credential.
    # ``model_id`` may be a literal or an ``env:NAME`` reference.
    base_url: str = ""
    base_url_env: str = "LLM_BASE_URL"
    api_key_env: str = "LLM_API_KEY"
    # Some reasoning models only accept a fixed temperature (Kimi k-series: 1.0).
    temperature: float | None = None
    # Vendor-specific switch (Ark/Doubao: "disabled"|"enabled"). Opt-in per model:
    # sending it to a vendor that does not understand it returns 400.
    thinking: str | None = None
    # CNY per 1k tokens. With token counts on record these turn into measured
    # cost; leaving them at 0 means "price unknown", never "free".
    price_input_per_1k: float = 0.0
    price_output_per_1k: float = 0.0


@dataclass
class Scenario:
    name: str
    domain: str
    task: str
    constraints: dict[str, float]
    dimensions: list[Dimension]
    models: list[ModelCandidate]
    n_cases: int = 24
    category_mix: dict[str, int] = field(default_factory=dict)
    seed: int = 42

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scenario":
        scenario = cls(
            name=str(data["name"]),
            domain=str(data["domain"]),
            task=str(data["task"]),
            constraints={k: float(v) for k, v in data.get("constraints", {}).items()},
            dimensions=[Dimension(**d) for d in data["dimensions"]],
            models=[ModelCandidate(**m) for m in data["models"]],
            n_cases=int(data.get("n_cases", 24)),
            category_mix={str(k): int(v) for k, v in data.get("category_mix", {}).items()},
            seed=int(data.get("seed", 42)),
        )
        if not scenario.category_mix:
            scenario.category_mix = {
                "normal": scenario.n_cases // 4,
                "edge": scenario.n_cases // 4,
                "adversarial": scenario.n_cases // 4,
                "multi_turn": scenario.n_cases - 3 * (scenario.n_cases // 4),
            }
        scenario.validate()
        return scenario

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Scenario":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(yaml.safe_load(fh))

    def validate(self) -> None:
        if not self.models:
            raise ValueError("scenario must define at least one model candidate")
        if not self.dimensions:
            raise ValueError("scenario must define at least one dimension")
        weight_sum = sum(d.weight for d in self.dimensions)
        if not math.isclose(weight_sum, 1.0, abs_tol=1e-6):
            raise ValueError(f"dimension weights must sum to 1.0, got {weight_sum}")
        for dim in self.dimensions:
            if dim.weight <= 0:
                raise ValueError(f"dimension {dim.key} must have a positive weight")
        if set(self.category_mix) != set(CATEGORIES):
            raise ValueError(f"category_mix must cover exactly {CATEGORIES}")
        if sum(self.category_mix.values()) != self.n_cases:
            raise ValueError("sum(category_mix) must equal n_cases")
        for model in self.models:
            if model.provider not in ("mock", "real"):
                raise ValueError(
                    f"model {model.name} has unknown provider {model.provider!r}; "
                    "expected 'mock' or 'real'"
                )
            if model.provider == "real" and not model.model_id:
                raise ValueError(f"real model {model.name} needs a model_id")
            missing = [d.key for d in self.dimensions if d.key not in model.profile]
            if model.provider == "mock" and missing:
                raise ValueError(f"mock model {model.name} missing profile keys: {missing}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TestCase:
    id: str
    category: str
    input: str
    expected_points: list[str]
    tags: list[str]
    difficulty: float = 0.5
    turns: list[str] = field(default_factory=list)


@dataclass
class Evaluation:
    case_id: str
    model: str
    scores: dict[str, float]
    weighted_score: float
    passed: bool
    rationale: str = ""


@dataclass
class ModelSummary:
    model: str
    overall: float
    dimension_scores: dict[str, float]
    pass_rate: float
    cost_per_1k: float
    latency_ms: int
    meets_constraints: bool


@dataclass
class FailureCluster:
    tag: str
    count: int
    models: list[str]
    example_case_ids: list[str]


@dataclass
class Analysis:
    summaries: list[ModelSummary]
    failures: list[FailureCluster]
    recommendation: str
    rationale: str
    tradeoffs: list[str]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def round_dict(values: dict[str, float], digits: int = 3) -> dict[str, float]:
    return {key: round(float(value), digits) for key, value in values.items()}
