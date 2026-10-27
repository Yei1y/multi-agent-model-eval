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

## 2026-10-27｜补齐 Responder：候选模型真实作答 + 依据回答判分

**背景**：复查 2026-10-24 的 real smoke 发现设计缺口——`llm_usage.json` 只有 4 条调用（Planner / Case Designer / Evaluator / Analyst），**候选模型一次都没被调用**；Evaluator 只拿到用例与模型名，分数是对模型名的先验印象，报告里"未出现违规响应"这类断言没有事实来源。

**改动**：

1. 新增 `Responder` 步骤：real 模式下把每条用例分别发给每个候选端点，记录回答、耗时、token；mock 模式下生成合成回答，只为让链路形状完整。
2. Evaluator 改为逐条用例判分，只依据回答正文，禁止按模型名推断；分数覆盖不全、维度 key 不符一律报错。
3. 延迟与 token 由 `src/measurements.py` 从真实调用统计；约束判定（是否超限）由代码计算，不采信模型自报数字。
4. 报告新增「证据来源」与「回答摘录」两节，并区分实测值与配置值。

**mock 复跑（验证改动没有动既有结论）**：

```bash
python scripts/run_demo.py --scenario data/scenarios/ecommerce_customer_service.yaml --mode mock
python scripts/run_demo.py --scenario data/scenarios/finance_customer_service.yaml --mode mock
```

- 运行目录：`runs/20261027-160933-ecommerce-customer-service/`、`runs/20261027-160950-finance-customer-service/`
- 电商：mock-fast 77.2 / mock-balanced 83.7 / mock-quality 86.1，推荐 mock-balanced，72 条回答，与 2026-10-24 完全一致
- 金融：mock-fast 76.2 / mock-balanced 85.8 / mock-quality 86.8，推荐 mock-balanced，48 条回答，与 2026-10-24 完全一致
- `task_ledger.jsonl` 现为 6 行，新增 `responder`（"72 answers, models=3, measured=0"）；mock 下 `measured=0` 是刻意的：合成回答不产生可用的耗时/token

**real 链路验证（未花钱）**：`tests/test_real_path.py` 用假传输层跑通整条 real 链路——候选模型被真实逐个调用（每模型每用例一次）、judge 只看到回答正文、缺维度报错、端点环境变量解析、以及一次完整的六步编排（8 条回答 / 8 条评分 / 实测延迟 / 报告含"实测"）。

**尚未做**：`data/scenarios/ecommerce_real_compare.yaml`（2 候选 × 8 条）需要 `LLM_MODEL_B` / `LLM_MODEL_C` 两个候选模型 id，本机未配置 key，**真实横向对比尚未运行**，因此本文件没有新的 real 数字。

## 2026-10-27｜首次真实跨厂商对比（4 用例 × 2 候选）+ 裁判审计

**目的**：Responder 补齐后第一次让候选模型真实作答，并检验 LLM-as-judge 的可信度（自偏好偏差、位置偏差）。

**配置**：

- 候选 A：`doubao-seed-2-1-lite-260915`（火山方舟，`temperature=1.0`，`thinking=disabled`）
- 候选 B：`kimi-k2.6`（Kimi 官方端点，该模型只接受 `temperature=1.0`）
- 裁判：`doubao-seed-2-1-lite-260915` —— **与候选 A 同模型**，这是账号只开通少量模型时的已知偏差
- 4 条用例（normal / edge / adversarial / multi_turn 各 1），候选名匿名 `candidate-a` / `candidate-b`

```bash
python scripts/run_demo.py --scenario data/scenarios/ecommerce_real_mini.yaml --mode real \
  --chart runs/real_mini_chart.png
```

- 运行目录：`runs/20261027-163342-ecommerce-real-mini/`
- 调用规模：15 次（Planner / Case Designer / 4×候选 A / 4×候选 B / 4×裁判 / Analyst），**20,724 tokens，167.3 s**
- 实测延迟（每条约）：候选 A **12,244 ms**，候选 B **16,684 ms**
- 报告数字（重算后）：候选 A **89.8**、候选 B **80.0**，推荐 candidate-a
- token 拆分（每条平均）：候选 A 输入 142 / 输出 585 / 合计 **728**；候选 B 输入 103 / 输出 520 / 合计 **624**

**发现一：报告里的整体分不是算出来的。** 首次生成的报告写候选 A **87.0**、候选 B **78.0**，而用 `evaluations.csv` 重算应为 A **89.8**、B **80.0**，差 **2.8 分**——整体分、维度分、通过率在 real 模式下仍由 Analyst 模型"写"出来。已修复：`AnalystAgent._recompute_from_evaluations` 用逐条评分重算这三项，`_rewrite_numeric_prose` 再用重算值重写结论与权衡文字（否则会出现"表格 89.8、结论 87.0"的自相矛盾）。该历史运行已用 `scripts/rerender_report.py` 就地重算（**不调用任何模型**），报告与 CSV 现在与数据一致。

**发现二：换裁判、换顺序的敏感性（裁判审计）**。同一批回答，只改裁判或回答顺序：

| 裁判 / 顺序 | 候选 A | 候选 B | 差距 |
| --- | ---: | ---: | ---: |
| doubao-lite（原裁判，与 A 同源） | 89.8 | 80.0 | 9.8 |
| doubao-pro（更强调裁判，正常顺序） | 87.8 | 78.5 | 9.3 |
| doubao-pro（**回答顺序颠倒**） | 81.8 | 73.2 | 8.6 |

- 换裁判后两边各降约 2 分，排序与差距几乎不动 → **本次自偏好偏差不是主因**
- 仅颠倒顺序，两边同时掉 **5–8 分** → **位置效应大于裁判身份效应**
- 结论：单次 LLM 评测的**绝对分不可复用**，只有"多次换序后的均值/区间"才有解释力

审计工具：`python scripts/judge_audit.py --run runs/20261027-163342-ecommerce-real-mini --judge doubao-seed-2-1-pro-260915 --base-url-env ARK_BASE_URL --api-key-env ARK_API_KEY --both-orders`（7,333 + 7,310 tokens），结果落在该运行目录的 `judge_audit_*.json`。

**成本核算（待填单价）**。脚本已支持按"实测 token × 配置单价"计算成本，字段为 `price_input_per_1k` / `price_output_per_1k`（元/千 token）。本次运行未填单价，因此成本列显示 `—`，**没有臆造价格**。填好后一条命令即可重算，不产生调用：

```bash
python scripts/rerender_report.py --run runs/20261027-163342-ecommerce-real-mini \
  --set-price candidate-a=<输入单价>/<输出单价> \
  --set-price candidate-b=<输入单价>/<输出单价>
```

以 token 量看：候选 A 每条 **728**、候选 B 每条 **624**，A 多用 **16.7%**。因此只有当豆包单价低于 Kimi 的 **1.17 倍**时，豆包才更便宜——这正是需要控制变量、按输入/输出分别计价的原因（输出通常贵 2–4 倍，A 的输出占比更高）。

**本次实验总消耗**：约 35.4k tokens（主运行 20.7k + 审计 14.6k）。端点探测与失败重试另计约 3k。

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

结果：11 项测试全部通过（约 4 s）。`test_pipeline.py` 覆盖场景权重校验、端到端产物、同 seed 可复现、
约束筛选、六步台账顺序；`test_real_path.py` 用假传输层覆盖候选模型真实调用、judge 只依据回答打分、
缺维度报错、候选端点环境变量解析、以及完整的 real 模式编排。

## 产物

- `runs/<run_id>/report.md`：选型报告（结论、汇总表、维度分、证据来源、回答摘录、失败聚类、局限）
- `runs/<run_id>/summary.csv`：模型级汇总（上表数字来源，含 `tokens_per_case`）
- `runs/<run_id>/answers.csv`：候选模型逐条回答原文 + 耗时 + token
- `runs/<run_id>/evaluations.csv`：用例 × 模型明细
- `runs/<run_id>/run.json`：完整运行快照（含 answers 与 measurements）
- `runs/<run_id>/task_ledger.jsonl`：6 个 Agent 的步骤、耗时与摘要
- `runs/<run_id>/llm_usage.json`：逐次 token / 耗时（real 模式含候选模型调用；mock 模式为空）
- `docs/assets/model_scores.png`：电商 mock 场景维度分与综合分图（README 引用）
- `docs/assets/model_scores_real.png`：真实 API smoke 的维度分图（README 引用）

## 说明

1. 两组 mock 分数由 `src/mock_engine.py` 根据 YAML 中的 `profile` 与固定随机种子生成，
   不是任何真实模型（豆包、DeepSeek、GPT 等）的实测结果。
2. 通过率、失败聚类与推荐都依赖 `PASS_THRESHOLD = 3.8`（mock）；改动该常量会改变 mock 结论。
3. 2026-10-24 的真实 smoke 只有 1 个模型 × 8 条用例，且发生在 Responder 补丁之前，
   候选模型未被调用；它的 83.0 分不能当作该模型的实测成绩。
4. mock 模式下的 `answers` 是合成文本，**不参与打分**（分数仍由 profile 生成），
   因此补上 Responder 后 mock 的分数与结论逐位不变；真实模式才由 judge 依据回答正文打分。
5. `summary.csv` 的延迟在 real 模式下是实测均值（`latency_source = measured`），
   在 mock 模式下是 YAML 配置值；`cost_per_1k` 始终是配置值，需要自己填真实单价，
   否则成本约束形同虚设。
