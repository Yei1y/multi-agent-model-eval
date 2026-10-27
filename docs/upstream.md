# 上游项目、借鉴点与改造声明

本项目是一个**业务改造**，不是上游仓库的 fork。下面写清楚借鉴了什么、没有复制什么，以及许可证边界。这样做的目的有两个：一是避免把别人的架构说成自己的原创；二是让后续维护者知道该回哪里看原始设计。

## 1. 上游项目

### 1.1 Microsoft AutoGen / Magentic-One

- 仓库：<https://github.com/microsoft/autogen>
- 论文：Magentic-One: A Generalist Multi-Agent System for Solving Complex Tasks，<https://arxiv.org/abs/2411.04468>
- 许可证：MIT（以仓库 `LICENSE` 为准）
- 借鉴内容：
  - **Orchestrator + 专家 Agent** 的分层：一个协调者负责规划与推进，专家 Agent 各自负责一类子任务。
  - **任务台账（task ledger）**：记录已完成的事实、当前计划与下一步，让过程可追溯。
  - **角色隔离**：不同 Agent 有不同的系统提示与职责，不把全部能力塞进一个 prompt。

### 1.2 CrewAI Examples

- 仓库：<https://github.com/crewAIInc/crewAI-examples>
- 许可证：MIT（以仓库 `LICENSE` 为准）
- 借鉴内容：
  - **sequential process** 的「角色—任务—输出」组织方式：每个 Agent 有明确的 role、goal 与 expected output。
  - 把复杂流程拆成多个可检查的中间产物，而不是一次生成最终答案。

## 2. 改造点

| 维度 | 上游 | 本项目 |
| --- | --- | --- |
| 业务场景 | 通用网页/文件/代码任务（Magentic-One）；市场研究、股票分析等示例（CrewAI） | 企业大模型选型评测：场景 → 计划 → 用例 → 打分 → 归因 → 报告 |
| 角色 | WebSurfer / FileSurfer / Coder / ComputerTerminal | Planner / CaseDesigner / Responder / Evaluator / Analyst / Reporter |
| 编排 | 动态选择下一个 Agent + 进度台账 | 固定六步顺序编排 + 任务台账（可复现优先） |
| 执行 | 依赖 AutoGen / CrewAI 运行时 | 纯 Python 最小实现，无框架依赖；mock 可离线跑 |
| 输出 | 任务结果 | `report.md` + `answers.csv` + `summary.csv` + `evaluations.csv` + `run.json` + 图表 |
| 评测数据 | 无固定评测集 | YAML 场景 + 四类用例模板 + 可替换的真实 API |

## 3. 没有复制什么

- 本项目**没有**复制 AutoGen 或 CrewAI 的源代码、提示词模板或测试数据。
- 代码（`src/`、`scripts/`、`tests/`）为独立实现；场景 YAML、用例模板与报告模板为本项目原创。
- 因此本项目采用 MIT 许可证即可，不附带上游版权声明；但如果未来真正 fork 上游代码，必须保留上游 `LICENSE` 与版权声明，并在 README 顶部标注 upstream 链接。

## 4. 引用方式

如果要在报告或简历中描述本项目，建议写：

> 参考 Microsoft AutoGen 的 Magentic-One（Orchestrator + 任务台账 + 专家 Agent）与 CrewAI 的 sequential crew 分工模式，独立实现了一个面向企业大模型选型评测的六 Agent 流水线；业务场景、数据结构与实现均为自写，mock 模式可离线复现。

不要写「基于 AutoGen 开发」或「CrewAI 项目」——这会让人误以为是 fork 或二次开发。准确的说法是「借鉴编排思想，独立实现」。

## 5. 如果未来要 fork 上游

合规检查清单：

- [ ] 保留上游 `LICENSE` 与版权声明（MIT 要求保留许可与版权声明）。
- [ ] 在 README 顶部写清 upstream 仓库、commit/tag、fork 日期。
- [ ] 区分「上游原有代码」与「本项目修改」，避免把上游代码说成原创。
- [ ] 如果上游使用 Apache-2.0（部分 Agent 框架），还要保留 `NOTICE` 文件并标注修改。
- [ ] 检查上游是否包含第三方数据/模型许可，不能随代码一起再分发。

## 6. 参考链接

- AutoGen: <https://github.com/microsoft/autogen>
- Magentic-One 论文: <https://arxiv.org/abs/2411.04468>
- CrewAI Examples: <https://github.com/crewAIInc/crewAI-examples>
- 本项目架构说明: [`architecture.md`](architecture.md)
