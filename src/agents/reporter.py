"""Reporter: renders the final selection memo."""

from __future__ import annotations

from typing import Any

from .base import BaseAgent


class ReporterAgent(BaseAgent):
    name = "reporter"
    system_prompt = (
        "你是选型报告撰写人。根据场景、评测计划和分析结果，写一份中文 Markdown 报告，"
        "必须包含：结论与推荐、模型汇总表、维度得分表、主要失败聚类、权衡与风险、"
        "方法与局限、复现命令。输出 JSON：{\"report_markdown\": str}。只输出 JSON。"
    )

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = super().run(payload)
        markdown = result.get("report_markdown")
        if not isinstance(markdown, str) or len(markdown.strip()) < 50:
            raise ValueError("reporter output must contain a non-trivial report_markdown")
        return {"report_markdown": markdown}
