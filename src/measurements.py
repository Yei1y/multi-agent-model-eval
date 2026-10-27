"""Turn raw candidate answers into measured latency, token and cost statistics.

Report numbers must come from recorded calls, never from the analyst LLM's
imagination: this module is the single place that converts ``answers`` records
into per-model measurements. Mock rows carry zero latency/tokens on purpose, so
a mock run can never masquerade as a measurement.

Costs are computed only when the scenario supplies unit prices; otherwise the
fields stay ``None`` and the report says so instead of showing a fake number.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def measure_models(
    answers: list[dict[str, Any]] | None,
    models: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Aggregate answer records into {model_name: measurement} dicts.

    ``models`` is the scenario model list; its ``price_input_per_1k`` /
    ``price_output_per_1k`` (CNY per 1k tokens) drive the cost fields.
    """
    prices = {
        str(model.get("name")): model
        for model in (models or [])
        if model.get("name")
    }

    counts: dict[str, int] = defaultdict(int)
    latencies: dict[str, list[float]] = defaultdict(list)
    tokens_in: dict[str, list[int]] = defaultdict(list)
    tokens_out: dict[str, list[int]] = defaultdict(list)
    providers: dict[str, str] = {}

    for row in answers or []:
        model = str(row.get("model", "")).strip()
        if not model:
            continue
        counts[model] += 1
        providers.setdefault(model, str(row.get("provider", "")))
        latency = float(row.get("latency_ms") or 0.0)
        if latency > 0:
            latencies[model].append(latency)
        prompt = int(row.get("prompt_tokens") or 0)
        completion = int(row.get("completion_tokens") or 0)
        total = int(row.get("total_tokens") or 0)
        if not prompt and not completion and total:
            # Older records only kept the total; treat it as output-heavy input.
            prompt = total
        if prompt or completion:
            tokens_in[model].append(prompt)
            tokens_out[model].append(completion)

    measurements: dict[str, dict[str, Any]] = {}
    for model, count in counts.items():
        lat = latencies.get(model, [])
        tin = tokens_in.get(model, [])
        tout = tokens_out.get(model, [])
        total_in = sum(tin)
        total_out = sum(tout)
        total_tokens = total_in + total_out

        prices_for_model = prices.get(model, {})
        price_in = float(prices_for_model.get("price_input_per_1k") or 0.0)
        price_out = float(prices_for_model.get("price_output_per_1k") or 0.0)
        priced = bool(price_in or price_out)

        cost_total = (
            (total_in * price_in + total_out * price_out) / 1000.0 if priced else None
        )
        cost_per_case = (
            round(cost_total / count, 6) if cost_total is not None and count else None
        )
        blended_per_1k = (
            round(cost_total / (total_tokens / 1000.0), 6)
            if cost_total is not None and total_tokens
            else None
        )

        measurements[model] = {
            "provider": providers.get(model, ""),
            "n_answers": count,
            "latency_ms": int(round(sum(lat) / len(lat))) if lat else 0,
            "tokens_in_per_case": int(round(total_in / count)) if count else 0,
            "tokens_out_per_case": int(round(total_out / count)) if count else 0,
            "tokens_per_case": int(round(total_tokens / count)) if count else 0,
            "tokens_total": total_tokens,
            "measured": bool(lat),
            "priced": priced,
            "price_input_per_1k": price_in,
            "price_output_per_1k": price_out,
            "cost_per_case": cost_per_case,
            "cost_total": round(cost_total, 6) if cost_total is not None else None,
            "cost_per_1k": blended_per_1k,
        }
    return measurements