# 架构与设计取舍

本文说明 `multi-agent-model-eval` 的角色契约、编排方式、运行产物与扩展方法。README 面向「先看懂价值」，本文面向「要改代码的人」。

## 1. 目标与边界

**目标**：把一个模糊的选型问题（「客服场景该选哪个模型？」）变成可复现的评测流程：场景化维度、四类用例、逐条打分、失败归因、约束下的推荐。

**边界**：

- 不替代真实 benchmark，也不替代人工评审；它是选型初筛与沟通材料。
- mock 模式只验证流水线，不产生真实结论。
- 真实模式依赖外部 LLM 端点；提示词、JSON 解析与重试在同一层处理，不把供应商 SDK 写进 Agent。

## 2. 角色契约

| Agent | 输入 | 输出（顶层 key） | 校验 | 失败行为 |
| --- | --- | --- | --- | --- |
| `PlannerAgent` | `scenario` | `plan` | 维度非空、权重和 = 1.0 | 抛错，台账记 `error` |
| `CaseDesignerAgent` | `scenario`、`plan` | `cases` | 列表非空、每条有 id/category | 同上 |
| `EvaluatorAgent` | `scenario`、`plan`、`cases` | `evaluations` | 列表非空、每条有 scores | 同上 |
| `AnalystAgent` | `scenario`、`plan`、`cases`、`evaluations` | `analysis` | summaries 与 recommendation 非空 | 同上 |
| `ReporterAgent` | `scenario`、`plan`、`analysis`、`run_id` | `report_markdown` | 字符串长度 ≥ 50 | 同上 |

所有 Agent 继承 `src/agents/base.py::BaseAgent`，共享同一个 `BaseLLM` 接口。Agent 只负责「组装 payload + 校验输出」，不关心底层是 mock 还是真实模型。

## 3. 编排流程

`src/orchestrator.py::Orchestrator.run()` 顺序执行五步：

```text
load scenario
  → PlannerAgent.run       → plan
  → CaseDesignerAgent.run  → cases
  → EvaluatorAgent.run     → evaluations
  → AnalystAgent.run       → analysis
  → ReporterAgent.run      → report_markdown
  → 落盘 + 出图
```

每一步调用 `_step()`，负责计时、记录台账、校验顶层 key。任一步抛错时，台账先写入 `status: "error"` 和错误信息，再把异常向上抛给 CLI，避免「报告已生成但中间步骤失败」的静默错误。

## 4. 任务台账

`task_ledger.jsonl` 每行一条 JSON，实际示例：

```json
{"step": "planner", "agent": "planner", "status": "ok", "started_at": "2026-10-24T11:49:13", "duration_ms": 0.03, "summary": "5 dimensions, case mix {'normal': 6, 'edge': 6, 'adversarial': 6, 'multi_turn': 6}"}
{"step": "case_designer", "agent": "case_designer", "status": "ok", "started_at": "2026-10-24T11:49:13", "duration_ms": 0.13, "summary": "24 cases"}
{"step": "evaluator", "agent": "evaluator", "status": "ok", "started_at": "2026-10-24T11:49:13", "duration_ms": 1.31, "summary": "72 evaluations"}
{"step": "analyst", "agent": "analyst", "status": "ok", "started_at": "2026-10-24T11:49:13", "duration_ms": 0.2, "summary": "recommendation=mock-balanced, models=3"}
{"step": "reporter", "agent": "reporter", "status": "ok", "started_at": "2026-10-24T11:49:13", "duration_ms": 5.84, "summary": "2053 chars"}
```

台账的作用：

- **可追溯**：每个结论都能对应到哪一步、耗时多少、产出多少条。
- **可调试**：真实模式某一 Agent 超时或 JSON 解析失败时，能立刻定位到步骤。
- **可扩展**：后续加并行分支或动态选择时，台账字段不需要重设计。

## 5. 运行产物

```text
runs/<run_id>/
├── run.json             # 场景、plan、cases、evaluations、analysis 全量快照
├── report.md            # 中文选型报告（Reporter 产出）
├── summary.csv          # 模型级汇总：综合分/维度分/通过率/成本/延迟/约束
├── evaluations.csv      # 用例 × 模型明细：每维度分、加权分、是否过线
└── task_ledger.jsonl    # 五步台账
```

`docs/assets/model_scores.png` 由 `src/charts.py` 生成，固定路径覆盖更新，方便 README 引用；历史 run 的原始数据不受影响。

## 6. mock / real 双模式

```text
              ┌──────────────┐
scenario ───► │ BaseLLM 接口 │ ───► Agent.run
              └──────┬───────┘
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
   MockLLM                  OpenAICompatibleLLM
   (profile + seed)         (/chat/completions, JSON, retry)
```

- `MockLLM` 为每个 Agent 维护独立 `random.Random(seed + index)`，避免不同步骤互相影响随机序列；同一 seed 的输出可逐字节复现。
- `MockLLM.structured()` 不调用网络，按 Agent 名分派到 `src/mock_engine.py` 的确定性函数。
- `OpenAICompatibleLLM` 用标准库 `urllib`，不额外依赖 SDK；`temperature=0.1`、`response_format={"type":"json_object"}`，最多重试 3 次（2 次重试）。

## 7. 设计取舍

**为什么顺序编排，而不是动态选择下一个 Agent？**
评测的步骤是固定的，顺序执行最容易被复现、测试与逐行核对；Magentic-One 的动态选择适合开放式网页/文件任务，但会引入不可预测的分支。当前版本优先可复现性，动态规划留在后续（见第 9 节）。

**为什么不用 CrewAI / AutoGen 运行时？**
依赖重、版本变化快，且真实调用需要 API key。本项目把「角色—任务—输出」的结构保留下来，用纯 Python 实现最小编排，面试演示和 CI 都能离线跑。上游借鉴关系见 `docs/upstream.md`。

**为什么用 1–5 分，而不是 0/1 通过率？**
1–5 分能区分「勉强可用」和「优秀」，也方便做维度画像；通过线 3.8 再转成二元结果。真实场景可以改成 0–100 或 pairwise 偏好，`schemas.py` 的 `Evaluation.scores` 结构不需要变。

**为什么通过线是 3.8？**
这是演示值：电商场景下 mock-fast 的加权分约 3.86，3.8 能暴露它在高难度对抗用例上的失败，又不至于让所有模型全军覆没。真实项目应根据业务容忍度设定，并在 `results.md` 中记录变更。

## 8. 扩展方式

**新增场景**：复制 `data/scenarios/ecommerce_customer_service.yaml`，修改 `domain/task/constraints/dimensions/models`。必须满足：

- 所有维度权重之和 = 1.0；
- `sum(category_mix) == n_cases`，且四个类别齐全；
- mock 模型的 `profile` 覆盖所有维度 key。

**新增维度**：在 YAML 的 `dimensions` 加一项并重新归一化权重；在 mock 模型的 `profile` 加同名 key。Evaluator 与报告会自动读取。

**新增 Agent**：继承 `BaseAgent`，设置 `name` 与 `system_prompt`，在 `src/agents/__init__.py` 导出，并在 `Orchestrator.run()` 插入一步；同时在 `_summarize_step()` 加摘要分支、在 `MockLLM.structured()` 加 mock 分派（若需要离线跑）。

**接真实模型**：`src/llm.py::build_llm("real", scenario)` 读取 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`；端点需兼容 `/chat/completions` 与 JSON 输出。首次接入建议先用一条用例验证返回结构，再跑全量。

## 9. 与 Magentic-One 的差异

| 维度 | Magentic-One (AutoGen) | 本项目 |
| --- | --- | --- |
| 任务类型 | 开放式网页/文件/代码任务 | 封闭式模型选型评测 |
| 编排 | Orchestrator 动态选择下一个 Agent，带进度台账 | 固定五步顺序编排，带任务台账 |
| 专家角色 | WebSurfer / FileSurfer / Coder / ComputerTerminal | Planner / CaseDesigner / Evaluator / Analyst / Reporter |
| 终止条件 | 进度检查 + 任务完成判断 | 五步完成即结束；失败即终止 |
| 输出 | 任务结果 | 选型报告 + CSV + JSON |

保留的共同点：**角色分工、任务台账、每一步可追溯**。这正是本项目从上游借鉴的核心，而不是复制具体实现。

## 10. 失败模式与排查

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| `plan dimension weights must sum to 1.0` | YAML 权重没归一化 | 调整权重或改 `PlannerAgent` 的归一化逻辑 |
| `sum(category_mix) must equal n_cases` | 用例配比与总数不一致 | 改 YAML 的 `category_mix` 或 `n_cases` |
| `real mode requires LLM_BASE_URL...` | 环境变量缺失 | 设三个 env，或改用 `--mode mock` |
| 真实模式 JSON 解析失败 | 端点不支持 `response_format`，或返回带 Markdown 围栏 | 先删 `response_format`，在 prompt 中强调「只输出 JSON」；查看 `task_ledger.jsonl` 定位步骤 |
| 图表中文乱码 | matplotlib 未配置中文字体 | 当前图表用英文标签；如需中文，设置 `font.sans-serif` 为 `SimHei` |
