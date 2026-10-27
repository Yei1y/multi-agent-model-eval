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
| `ResponderAgent` | `scenario`、`cases` | `answers` | real 模式每个候选都能建连；空回答视为失败 | 同上 |
| `EvaluatorAgent` | `scenario`、`plan`、`cases`、`answers` | `evaluations` | 覆盖全部 (case, model)；维度 key 必须齐全且在 1–5 | 同上，缺模型时先重问一次 |
| `AnalystAgent` | `scenario`、`plan`、`cases`、`evaluations`、`measurements` | `analysis` | summaries 与 recommendation 非空 | 同上 |
| `ReporterAgent` | `scenario`、`plan`、`analysis`、`answers`、`measurements`、`run_id` | `report_markdown` | 字符串长度 ≥ 50 | 同上 |

所有 Agent 继承 `src/agents/base.py::BaseAgent`，共享同一个 `BaseLLM` 接口。Agent 只负责「组装 payload + 校验输出」，不关心底层是 mock 还是真实模型。

## 3. 编排流程

`src/orchestrator.py::Orchestrator.run()` 顺序执行六步：

```text
load scenario
  → PlannerAgent.run       → plan
  → CaseDesignerAgent.run  → cases
  → ResponderAgent.run     → answers（候选模型真实作答；mock 模式为合成文本）
  → EvaluatorAgent.run     → evaluations（依据回答打分）
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
{"step": "responder", "agent": "responder", "status": "ok", "started_at": "2026-10-24T11:49:13", "duration_ms": 0.66, "summary": "72 answers, models=3, measured=0"}
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
├── report.md            # 中文选型报告（Reporter 用模板渲染）
├── summary.csv          # 模型级汇总：综合分/维度分/通过率/成本/延迟/约束
├── evaluations.csv      # 用例 × 模型明细：每维度分、加权分、是否过线
├── task_ledger.jsonl    # 六步台账
├── answers.csv          # 候选模型逐条回答 + 耗时 + 输入/输出 token
└── llm_usage.json       # 逐次 token/耗时（real 模式含候选调用；mock 模式为空）
```

成本不在 answers 里凭空出现：`src/measurements.py` 用 answers 的输入/输出 token 乘场景单价
（`price_input_per_1k` / `price_output_per_1k`）算出单条成本、每千 token 成本与总成本；
单价留空时这三项为 `None`，报告如实显示"—"。

`docs/assets/model_scores.png` 由 `src/charts.py` 生成，固定路径覆盖更新，方便 README 引用；历史 run 的原始数据不受影响。真实运行建议用 `--chart runs/real_smoke_chart.png`，避免覆盖 mock 图。Reporter 用模板渲染而不是再调一次模型，保证表格数字与 CSV 一致，也减少一次 API 费用。

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

- `MockLLM` 为每个 Agent 维护独立 `random.Random(seed + index)`，避免不同步骤互相影响随机序列；同一 seed 的输出可逐字节复现。`responder` 刻意排在 `_AGENTS` 末尾，插在中间会改变后续 Agent 的种子，把已记录的全部 mock 结论改掉。
- `MockLLM.structured()` 不调用网络，按 Agent 名分派到 `src/mock_engine.py` 的确定性函数。mock 的回答只是文本占位，不参与打分，也不产生耗时/token。
- `OpenAICompatibleLLM` 用标准库 `urllib`，不额外依赖 SDK；两种调用形状：`structured()`（JSON 强制、`temperature=0.1`）与 `chat()`（自由文本，用于候选模型作答）。最多重试 3 次（2 次重试），超时默认 180 s，并捕获 `ConnectionError` / `RemoteDisconnected`。
- 候选模型各自建连：`build_candidate_llms()` 按 YAML 的 `base_url_env` / `api_key_env` / `model_id`（支持 `env:NAME`）创建客户端，缺环境变量时在运行前 fail fast，避免跑了一半才发现没配。候选人调用与工作流调用的 usage 会合并进同一个 `llm_usage.json`。
- 真实 smoke（2026-10-24）：火山方舟 `doubao-seed-2-1-lite`，1 模型 × 8 条用例，9,055 tokens，46.7 s。**该次运行早于 Responder 补丁，候选模型未被调用**，其分数不是实测成绩。火山方舟可设 `LLM_THINKING=disabled` 关闭思考，避免单次调用超过 60 s。

## 7. 设计取舍

**为什么顺序编排，而不是动态选择下一个 Agent？**
评测的步骤是固定的，顺序执行最容易被复现、测试与逐行核对；Magentic-One 的动态选择适合开放式网页/文件任务，但会引入不可预测的分支。当前版本优先可复现性，动态规划留在后续（见第 9 节）。

**为什么不用 CrewAI / AutoGen 运行时？**
依赖重、版本变化快，且真实调用需要 API key。本项目把「角色—任务—输出」的结构保留下来，用纯 Python 实现最小编排，面试演示和 CI 都能离线跑。上游借鉴关系见 `docs/upstream.md`。

**为什么用 1–5 分，而不是 0/1 通过率？**
1–5 分能区分「勉强可用」和「优秀」，也方便做维度画像；通过线 3.8 再转成二元结果。真实场景可以改成 0–100 或 pairwise 偏好，`schemas.py` 的 `Evaluation.scores` 结构不需要变。

**为什么通过线是 3.8？**
这是演示值：电商场景下 mock-fast 的加权分约 3.86，3.8 能暴露它在高难度对抗用例上的失败，又不至于让所有模型全军覆没。真实项目应根据业务容忍度设定，并在 `results.md` 中记录变更。

**为什么数字都由代码算，而不是让 Analyst 报？**
早期版本让 LLM 填延迟、成本与"是否满足约束"，实测出现过把 0–1 的通过率写成 `10000%` 的事故。现在加权分由 `EvaluatorAgent._finalize` 重算，延迟/token 由 `src/measurements.py` 统计，约束判定由 `AnalystAgent._apply_measurements` 覆盖，推荐若与约束冲突还会被 `_enforce_constraints` 纠正。代价是放弃了"让模型自己总结数字"的灵活性，换来报告、CSV、图表三者永远一致。

## 8. 扩展方式

**新增场景**：复制 `data/scenarios/ecommerce_customer_service.yaml`，修改 `domain/task/constraints/dimensions/models`。必须满足：

- 所有维度权重之和 = 1.0；
- `sum(category_mix) == n_cases`，且四个类别齐全；
- mock 模型的 `profile` 覆盖所有维度 key。

**新增维度**：在 YAML 的 `dimensions` 加一项并重新归一化权重；在 mock 模型的 `profile` 加同名 key。Evaluator 与报告会自动读取。

**新增 Agent**：继承 `BaseAgent`，设置 `name` 与 `system_prompt`，在 `src/agents/__init__.py` 导出，并在 `Orchestrator.run()` 插入一步；同时在 `_summarize_step()` 加摘要分支、在 `MockLLM.structured()` 加 mock 分派（若需要离线跑）。

**接真实模型**：`src/llm.py::build_llm("real", scenario)` 读取 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`，可选 `LLM_THINKING`；端点需兼容 `/chat/completions` 与 JSON 输出。首次接入建议先用一条用例验证返回结构，再跑 8–12 条 smoke；成本与账单以服务商控制台为准。

## 9. 与 Magentic-One 的差异

| 维度 | Magentic-One (AutoGen) | 本项目 |
| --- | --- | --- |
| 任务类型 | 开放式网页/文件/代码任务 | 封闭式模型选型评测 |
| 编排 | Orchestrator 动态选择下一个 Agent，带进度台账 | 固定六步顺序编排，带任务台账 |
| 专家角色 | WebSurfer / FileSurfer / Coder / ComputerTerminal | Planner / CaseDesigner / Responder / Evaluator / Analyst / Reporter |
| 终止条件 | 进度检查 + 任务完成判断 | 六步完成即结束；失败即终止 |
| 输出 | 任务结果 | 选型报告 + CSV + JSON |

保留的共同点：**角色分工、任务台账、每一步可追溯**。这正是本项目从上游借鉴的核心，而不是复制具体实现。

## 10. 失败模式与排查

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| `plan dimension weights must sum to 1.0` | YAML 权重没归一化 | 调整权重或改 `PlannerAgent` 的归一化逻辑 |
| `sum(category_mix) must equal n_cases` | 用例配比与总数不一致 | 改 YAML 的 `category_mix` 或 `n_cases` |
| `real mode requires LLM_BASE_URL...` | 环境变量缺失 | 设三个 env，或改用 `--mode mock` |
| `candidate model X is missing base_url/api_key/model_id` | 候选端点没配 | 按提示设置 YAML 中 `base_url_env` / `api_key_env` 指向的变量，或把 `model_id` 写成 `env:NAME` |
| `evaluations incomplete: N of M ... missing` | judge 漏给某个模型的评分 | 已自动重问一次；仍缺就换 judge 或收紧提示词 |
| `evaluation ... is missing dimension 'x'` | judge 改写了维度 key | 代码不做静默补 0；检查 plan 的 key 与提示词 |
| `Remote end closed connection` / 超时 | 模型思考时间长、连接被远端重置 | 设 `LLM_THINKING=disabled`；超时已设 180 s；代码会重试 2 次 |
| 真实模式 JSON 解析失败 | 端点不支持 `response_format`，或返回带 Markdown 围栏 | 先删 `response_format`，在 prompt 中强调「只输出 JSON」；查看 `task_ledger.jsonl` 定位步骤 |
| 报告通过率显示 `10000%` | LLM 把通过率返回成 0–100 而不是 0–1 | `AnalystAgent._normalize_units` 已归一化；新增单位时保持该契约 |
| 图表中文乱码 | matplotlib 未配置中文字体 | 当前图表用英文标签；如需中文，设置 `font.sans-serif` 为 `SimHei` |
