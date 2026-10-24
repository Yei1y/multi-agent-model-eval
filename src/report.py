"""Markdown report rendering for a single evaluation run."""

from __future__ import annotations

from typing import Any


def _fmt(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}"


def render_report(
    scenario: dict[str, Any],
    plan: dict[str, Any],
    analysis: dict[str, Any],
    run_id: str,
    mode: str = "mock",
) -> str:
    dimensions = plan["dimensions"]
    model_rows = analysis["summaries"]
    failures = analysis["failures"]
    constraints = scenario.get("constraints", {})
    max_latency = float(constraints.get("max_latency_ms", float("nan")))
    max_cost = float(constraints.get("max_cost_per_1k", float("nan")))
    n_cases = sum(int(v) for v in plan["case_mix"].values())

    lines: list[str] = []
    lines.append(f"# 模型选型评测报告：{scenario['domain']}")
    lines.append("")
    lines.append(
        f"> 运行 ID：`{run_id}`｜模式：`{mode}`｜场景：`{scenario['name']}`"
    )
    lines.append("")
    lines.append("## 结论")
    lines.append("")
    lines.append(f"**推荐 {analysis['recommendation']}。** {analysis['rationale']}")
    lines.append("")
    lines.append("## 评测设计")
    lines.append("")
    lines.append(f"- 任务：{scenario['task']}")
    lines.append(
        "- 维度："
        + "、".join(f"{d['name']}（{d['key']}，权重 {d['weight']:.2f}）" for d in dimensions)
    )
    lines.append(
        f"- 约束：延迟 ≤ {max_latency:.0f} ms；成本 ≤ {max_cost:.3f} / 千 token"
    )
    lines.append(
        f"- 用例：{n_cases} 条（"
        + "、".join(f"{k} {v}" for k, v in plan["case_mix"].items())
        + "），通过线 "
        + f"{float(plan['pass_threshold']):.1f}/5"
    )
    lines.append("")
    lines.append("## 模型汇总")
    lines.append("")
    header = (
        "| 模型 | 综合分（0–100） | 通过率 | 延迟（ms） | 成本（/千 token） | 满足约束 |"
    )
    lines.append(header)
    lines.append("| --- | ---: | ---: | ---: | ---: | :---: |")
    for row in model_rows:
        lines.append(
            f"| {row['model']} | {_fmt(row['overall'])} | {row['pass_rate'] * 100:.1f}% | "
            f"{row['latency_ms']} | {row['cost_per_1k']:.3f} | "
            f"{'是' if row['meets_constraints'] else '否'} |"
        )
    lines.append("")
    lines.append("## 维度得分（1–5）")
    lines.append("")
    lines.append("| 模型 | " + " | ".join(d["name"] for d in dimensions) + " |")
    lines.append("| --- | " + " | ".join("---:" for _ in dimensions) + " |")
    for row in model_rows:
        cells = " | ".join(
            f"{row['dimension_scores'].get(d['key'], 0.0):.2f}" for d in dimensions
        )
        lines.append(f"| {row['model']} | {cells} |")
    lines.append("")
    lines.append("## 主要失败聚类")
    lines.append("")
    if failures:
        lines.append("| 标签 | 失败次数 | 涉及模型 | 示例用例 |")
        lines.append("| --- | ---: | --- | --- |")
        for item in failures:
            lines.append(
                f"| `{item['tag']}` | {item['count']} | "
                f"{', '.join(item['models'])} | {', '.join(item['example_case_ids'])} |"
            )
    else:
        lines.append("本次运行没有失败用例（通过线以下）。")
    lines.append("")
    lines.append("## 权衡与风险")
    lines.append("")
    for item in analysis["tradeoffs"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 方法与局限")
    lines.append("")
    lines.append(
        "- 本报告由 Planner → Case Designer → Evaluator → Analyst → Reporter "
        "五个 Agent 顺序协作生成，每一步的输入/输出/耗时记录在 `task_ledger.jsonl`。"
    )
    lines.append(
        "- 当前为 mock 模式：候选模型的画像与分数是**合成数据**，只用于演示流水线，"
        "**不代表任何真实模型的性能**；真实结论必须用 `--mode real` 重新评测。"
    )
    lines.append(
        "- 评测采用规则化的 1–5 分打分；真实模式可切换为 LLM-as-judge，但仍需人工抽检与"
        "标注校准，避免位置偏差与自洽偏差。"
    )
    lines.append(
        f"- 样本量为 {n_cases} 条用例，不足以覆盖长尾；结论应作为选型初筛，而不是最终采购依据。"
    )
    lines.append("")
    lines.append("## 复现")
    lines.append("")
    lines.append("```bash")
    lines.append(
        "python scripts/run_demo.py --scenario data/scenarios/"
        + str(scenario["name"]).replace("-", "_")
        + ".yaml --mode mock"
    )
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append(
        f"*由 multi-agent-model-eval 自动生成｜模式 {mode}｜运行 {run_id}*"
    )
    return "\n".join(lines) + "\n"
