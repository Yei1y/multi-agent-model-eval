# results.md — 运行记录

> 本文件记录可复现的运行结果。**当前所有结果均为 mock 模式**：候选模型的画像与分数是
> 合成数据，只用于验证流水线，**不代表任何真实模型的性能**。真实结论必须用 `--mode real`
> 重新评测，并保留原始响应与人工抽检记录。

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
- `docs/assets/model_scores.png`：电商场景维度分与综合分图（README 引用）

## 说明

1. 上述分数由 `src/mock_engine.py` 根据 YAML 中的 `profile` 与固定随机种子生成，
   不是任何真实模型（豆包、DeepSeek、GPT 等）的实测结果。
2. 通过率、失败聚类与推荐都依赖 `PASS_THRESHOLD = 3.8`；改动该常量会改变结论。
3. 真实模式代码路径存在（`src/llm.py::OpenAICompatibleLLM`），但因本机无 API key，
   尚未进行端到端验证；不在 `results.md` 中声称真实结果。
