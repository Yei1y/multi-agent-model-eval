"""Evaluator: scores every candidate model on every test case.

In mock mode the scores are synthetic (profile + seed) and the answers are
ignored, so the documented mock numbers stay reproducible. In real mode the
judge reads the *actual answer each candidate gave* and scores that text; it is
never allowed to infer a score from a model name.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .base import BaseAgent


class EvaluatorAgent(BaseAgent):
    name = "evaluator"
    system_prompt = (
        "你是模型评测员。你会收到一条测试用例、若干候选模型对它的实际回答，以及评分维度。"
        "请**只依据回答正文**打分，禁止根据模型名称、厂商或过往印象推断分数；"
        "回答没覆盖 expected_points 里的要点就要在对应维度扣分。"
        "对每个模型、每个维度打 1–5 分（1=明显不满足，3=基本满足，5=优秀），并给出简短理由。输出 JSON："
        '{"evaluations": [{"case_id": str, "model": str, '
        '"scores": {"<dimension_key>": 1-5}, "weighted_score": float, '
        '"passed": bool, "rationale": str}]}。'
        "每个模型都必须出现在输出里，一条都不能少。只输出 JSON。"
    )

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("mode") == "real":
            evaluations = self._judge_per_case(payload)
        else:
            result = super().run(payload)
            evaluations = result.get("evaluations")
            if not isinstance(evaluations, list) or not evaluations:
                raise ValueError(
                    "evaluator output must contain a non-empty 'evaluations' list"
                )
        return {"evaluations": self._finalize(evaluations, payload)}

    # ------------------------------------------------------------------
    # Real mode: one judge call per case, so the judge compares answers side by side
    # ------------------------------------------------------------------

    def _judge_per_case(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        plan = payload["plan"]
        cases = payload["cases"]
        answers = payload.get("answers") or []
        if not answers:
            raise ValueError(
                "real evaluator needs answers; did the responder step run?"
            )

        by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in answers:
            by_case[str(row["case_id"])].append(row)

        evaluations: list[dict[str, Any]] = []
        for case in cases:
            rows = by_case.get(str(case["id"])) or []
            if not rows:
                raise ValueError(f"no candidate answer for case {case['id']}")
            case_payload = {
                "scenario": payload["scenario"],
                "plan": plan,
                "case": case,
                "answers": [
                    {"model": row["model"], "answer": row["answer"]} for row in rows
                ],
            }
            got = self._ask_judge(case_payload)
            missing = {row["model"] for row in rows} - {
                str(item.get("model")) for item in got if isinstance(item, dict)
            }
            if missing:
                # One explicit retry: an itemized reminder is usually enough.
                retry_payload = dict(case_payload)
                retry_payload["missing_models"] = sorted(missing)
                got = self._ask_judge(retry_payload, stricter=True)
                still_missing = {row["model"] for row in rows} - {
                    str(item.get("model")) for item in got if isinstance(item, dict)
                }
                if still_missing:
                    raise ValueError(
                        f"judge did not score {sorted(still_missing)} on case {case['id']}"
                    )
            evaluations.extend(item for item in got if isinstance(item, dict))
        return evaluations

    def _ask_judge(
        self, case_payload: dict[str, Any], stricter: bool = False
    ) -> list[dict[str, Any]]:
        payload = case_payload
        if stricter:
            payload = dict(case_payload)
            payload["reminder"] = (
                "上一轮遗漏了这些模型："
                + "、".join(case_payload.get("missing_models", []))
                + "。每个模型必须各出现一次。"
            )
        result = self.llm.structured(self.name, self.system_prompt, payload)
        rows = result.get("evaluations")
        if not isinstance(rows, list) or not rows:
            raise ValueError("judge output must contain a non-empty 'evaluations' list")
        return rows

    # ------------------------------------------------------------------
    # Shared contract: numbers are recomputed here, never trusted from the model
    # ------------------------------------------------------------------

    def _finalize(
        self, evaluations: list[dict[str, Any]], payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
        plan = payload["plan"]
        cases = payload["cases"]
        scenario = payload["scenario"]

        dimension_keys = [str(dim["key"]) for dim in plan["dimensions"]]
        weights = {str(dim["key"]): float(dim["weight"]) for dim in plan["dimensions"]}
        threshold = float(plan.get("pass_threshold", 3.0))
        case_ids = {str(case["id"]) for case in cases}
        model_names = {str(model["name"]) for model in scenario["models"]}

        finalized: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for row in evaluations:
            case_id = str(row.get("case_id", "")).strip()
            model = str(row.get("model", "")).strip()
            if case_id not in case_ids:
                raise ValueError(f"evaluation references unknown case: {case_id!r}")
            if model not in model_names:
                raise ValueError(f"evaluation references unknown model: {model!r}")
            if (case_id, model) in seen:
                raise ValueError(f"duplicate evaluation for {case_id}/{model}")
            seen.add((case_id, model))

            raw = row.get("scores")
            if not isinstance(raw, dict) or not raw:
                raise ValueError(f"evaluation {case_id}/{model} needs a scores object")
            lowered = {str(key).strip().lower(): value for key, value in raw.items()}
            scores: dict[str, float] = {}
            for key in dimension_keys:
                if key not in lowered:
                    raise ValueError(
                        f"evaluation {case_id}/{model} is missing dimension {key!r}; "
                        f"got {sorted(lowered)}"
                    )
                value = float(lowered[key])
                if not 1.0 <= value <= 5.0:
                    raise ValueError(
                        f"score for {case_id}/{model}/{key} out of range: {value}"
                    )
                scores[key] = round(value, 2)

            # Recompute rather than trust the judge's arithmetic.
            weighted = sum(scores[key] * weights[key] for key in dimension_keys)
            finalized.append(
                {
                    "case_id": case_id,
                    "model": model,
                    "scores": scores,
                    "weighted_score": round(weighted, 3),
                    "passed": weighted >= threshold,
                    "rationale": str(row.get("rationale", "")).strip(),
                }
            )

        expected = {(case_id, model) for case_id in case_ids for model in model_names}
        missing = expected - seen
        if missing:
            sample = ", ".join(f"{case}/{model}" for case, model in sorted(missing)[:5])
            raise ValueError(
                f"evaluations incomplete: {len(missing)} of {len(expected)} "
                f"(case, model) pairs missing, e.g. {sample}"
            )
        return finalized


__all__ = ["EvaluatorAgent"]