# results.md — 运行记录

> 本文件记录可复现的运行结果。当前包含两组 **mock** 结果和一组 **真实 API smoke**：
> mock 分数由 YAML 画像 + 固定 seed 生成，只验证流水线，**不代表真实模型性能**；
> real smoke 只验证端到端调用，样本小、单模型，**不能当作横向选型结论**。
> 所有真实调用都通过环境变量传 key，key 不写入仓库。实际账单以服务商控制台为准。

## 环境

- Python 3.11（conda 环境 `python31111`）
- PyYAML 6.0.3、matplotlib 3.11.0
- Windows 11

## 2026-10-24｜电商客服场景（mock）

```bash
python scripts/run_demo.py --scenario data/scenarios/ecommerce_customer_service.yaml --mode mock
```

- 运行目录：`runs/20261024-114913-ecommerce-customer-service/`
- 输入：3 个候选模型 × 24 条用例（normal/edge/adversarial/multi_turn 各 6 条）× 5 个维度
- 通过线：3.8 / 5；约束：延迟 ≤ 2000 ms，成本 ≤ 0.010 / 千 token
- 随机种子：42

| 模型 | 综合分（0–100） | 通过率 | 延迟（ms） | 成本（/千 token） | 满足约束 |
| --- | ---: | ---: | ---: | ---: | :---: |
| mock-fast | 77.2 | 62.5% | 800 | 0.001 | 是 |
| mock-balanced | 83.7 | 100.0% | 1200 | 0.004 | 是 |
| mock-quality | 86.1 | 100.0% | 2600 | 0.012 | 否 |

主要失败聚类（均来自 mock-fast，各 1 条）：`ambiguous`（edge-01）、`privacy`（adversarial-01）、
`pricing_promise`（adversarial-02）、`compliance`（adversarial-04）、`fraud`（adversarial-05）。

推荐结果：**mock-balanced**。mock-quality 的原始分更高（86.1 vs 83.7），但延迟 2600 ms、
成本 0.012 / 千 token 均超过约束，因此被排除。

## 2026-10-24｜金融客服场景（mock）

```bash
python scripts/run_demo.py --scenario data/scenarios/finance_customer_service.yaml --mode mock
```

- 运行目录：`runs/20261024-114915-finance-customer-service/`
- 输入：3 个候选模型 × 16 条用例（每类 4 条）× 5 个维度
- 通过线：3.8 / 5；约束：延迟 ≤ 1500 ms，成本 ≤ 0.008 / 千 token
- 随机种子：43

| 模型 | 综合分（0–100） | 通过率 | 延迟（ms） | 成本（/千 token） | 满足约束 |
| --- | ---: | ---: | ---: | ---: | :---: |
| mock-fast | 76.2 | 43.8% | 800 | 0.001 | 是 |
| mock-balanced | 85.8 | 100.0% | 1200 | 0.004 | 是 |
| mock-quality | 86.8 | 100.0% | 2600 | 0.012 | 否 |

主要失败聚类（均来自 mock-fast，各 1 条）：`multi_condition`（edge-02）、`cross_bank`（edge-04）、
`privacy`（adversarial-01）、`guarantee`（adversarial-02）、`regulatory`（adversarial-03）。

推荐结果：**mock-balanced**。mock-quality 的原始分更高（86.8 vs 85.8），但超过更严格的
1500 ms / 0.008 约束，因此被排除。

## 2026-10-24｜真实 API smoke（火山方舟 doubao-seed-2-1-lite）

目的：验证 `--mode real` 端到端能跑通（Planner / Case Designer / Evaluator / Analyst 四次模型调用 + 模板 Reporter），**不做横向选型**。

```bash
export LLM_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
export LLM_API_KEY="<your-key>"          # 仅环境变量，不写入仓库
export LLM_MODEL="doubao-seed-2-1-lite-260915"
export LLM_THINKING="disabled"           # Ark 可选：关闭思考，降低延迟与费用
python scripts/run_demo.py --scenario data/scenarios/ecommerce_smoke.yaml --mode real \
  --chart runs/real_smoke_chart.png
```

- 运行目录：`runs/20261024-173215-ecommerce-smoke/`
- 输入：1 个模型 × 8 条用例（normal/edge/adversarial/multi_turn 各 2 条）× 5 个维度
- 通过线：3.0 / 5；模型延迟/成本字段为**占位值**，真实耗时见下方调用日志
- `thinking = disabled`（否则单次调用可能超过 60 s，曾在 Case Designer 步骤被远端断连）

| 模型 | 综合分（0–100） | 通过率 | 准确性 | 安全性 | 有用性 | 简洁性 | 成本效率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| doubao-seed-2-1-lite | 83.0 | 100.0% | 4.25 | 5.00 | 4.00 | 4.38 | 3.00 |

主要失败聚类：无（8 条全部过线）。报告：`runs/20261024-173215-ecommerce-smoke/report.md`。

**token 与耗时**（来自 `runs/.../llm_usage.json`）：

| Agent | total tokens | 耗时 |
| --- | ---: | ---: |
| Planner | 997 | 6.6 s |
| Case Designer | 1,979 | 19.2 s |
| Evaluator | 2,882 | 14.6 s |
| Analyst | 3,197 | 6.3 s |
| **合计** | **9,055**（prompt 6,551 / completion 2,504） | **46.7 s** |

**说明**：

1. 这是**单模型、8 条用例的 smoke**，不是多模型横向 benchmark；mock 的 3 模型 × 24 用例仍是主演示。
2. `summary.csv` 里的延迟/成本来自 YAML 占位值（0），不是实测；真实每次调用耗时在 `llm_usage.json`，实际扣费以火山方舟控制台为准。
3. 首次 real 尝试在 Case Designer 60 s 超时后 `RemoteDisconnected`；已把超时调到 180 s、补 `ConnectionError` 重试，并改用 `thinking=disabled`，之后稳定在约 47 s。
4. 本次总 token 约 9 千；即使按 lite 模型计价，5 元预算下余量也很大（具体金额以账单为准）。

## 测试

```bash
python -m unittest discover -s tests -v
```

结果：5 项测试全部通过（约 3 s）。覆盖场景权重校验、端到端产物、同 seed 可复现、
约束筛选与任务台账顺序。

## 产物

- `runs/<run_id>/report.md`：选型报告（结论、汇总表、维度分、失败聚类、局限）
- `runs/<run_id>/summary.csv`：模型级汇总（上表数字来源）
- `runs/<run_id>/evaluations.csv`：用例 × 模型明细
- `runs/<run_id>/run.json`：完整运行快照
- `runs/<run_id>/task_ledger.jsonl`：5 个 Agent 的步骤、耗时与摘要
- `runs/<run_id>/llm_usage.json`：真实模式的逐次 token / 耗时（mock 模式为空）
- `docs/assets/model_scores.png`：电商 mock 场景维度分与综合分图（README 引用）
- `docs/assets/model_scores_real.png`：真实 API smoke 的维度分图（README 引用）

## 说明

1. 两组 mock 分数由 `src/mock_engine.py` 根据 YAML 中的 `profile` 与固定随机种子生成，
   不是任何真实模型（豆包、DeepSeek、GPT 等）的实测结果。
2. 通过率、失败聚类与推荐都依赖 `PASS_THRESHOLD = 3.8`（mock）；改动该常量会改变 mock 结论。
3. 真实模式已用 1 个模型 × 8 条用例跑通（9,055 tokens，46.7 s），但**尚未做多模型/全量真实评测**；
   `summary.csv` 中的延迟/成本为占位值，真实耗时见 `llm_usage.json`，实际账单以服务商控制台为准。
