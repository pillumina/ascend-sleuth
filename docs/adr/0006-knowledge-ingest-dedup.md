# 知识摄入：增量抓取、硬去重与分层分工

## Context

- 知识库主要从框架仓库（vllm-ascend 起步，后续 mindspeed-llm、verl 等）的闭环 issue 批量导入。批式持续导入是知识增长的主要模式（评估 0001 验证）
- 批量导入面临重复劳动风险：跨批次重复（同一 issue 被再次抓取评估）、同根因不同 issue（variant 软重复）、低价值 issue 占用评估注意力
- 平台多样性：GitHub 起步，后续可能 GitCode / Gitee；各平台认证与 API 不同
- 决策过程（2026-08 讨论）：拉取不脚本化（避免多平台认证负担）、过滤脚本化（可复现防重复）、价值判断交给 agent

## Decision

**一、三层去重分工**

| 重复形态 | 防线 | 层 |
|---|---|---|
| 跨批次硬重复（同一 issue 重抓） | processed 编号清单，抓取即排除 | 过滤脚本 |
| 同根因不同 issue（variant 软重复） | groom 预分诊三分类 + 交叉回放验证 | 评估/groom 层 |
| 低价值 issue 抢占注意力 | 评论数门槛 + 标题规则 | 过滤脚本 |

抓取层挡硬重复（零成本、可复现）；groom 层消化软重复（本就是它的设计职责）。

**二、分层分工（原则二 + 五）**

| 环节 | 谁 | 理由 |
|---|---|---|
| 拉取 + 认证 + 线程缓存 | agent（gh/curl 现成工具） | 平台认证各异，脚本化要维护 N 套；拉取是无状态动作 |
| 硬过滤（processed 排除 / 评论数 / 标题规则 / 增量游标） | `scripts/issue_filter.py` | 可复现、可审计、跨框架/平台复用 |
| 四门槛价值评估 + 评分 | agent subagent | 语义判断，脚本做不了 |
| to-postmortem / groom | agent | 既有流程 |

拉取手段与过滤逻辑解耦：换平台只换拉取工具（agent 用对应 CLI），过滤脚本只吃 JSON 缓存 + 状态文件。

**三、状态文件 `ingest-state.json`（全局、跨源）**

- 顶层 `sources`，每源一条：`github/vllm-project/vllm-ascend`、`gitee/...`、`gitcode/...`
- 每源记录：`processed`（已评估/已沉淀的编号——含全部评估过的，不只入选的）、`selected`（沉淀数）、`last_fetch_*_closed`（游标参考）
- **processed 在拉取时排除**（避免重复拉取浪费 API）；评估后放弃的单独记 `skipped`（待扩展）
- 进 git：审计价值（谁处理过什么可追溯），与 metrics.md 同级

**四、增量口径**

- 拉取按 closed_at 倒序（最新优先），配合 processed 排除实现增量：每次只处理新增
- 游标参考记录 last_fetch_oldest_closed，下次可从该处继续（避免全量翻页）

## Rejected / Deferred

- 拉取脚本化（含认证管理）：否决——多平台认证负担 > 收益；agent 现成工具已解决认证
- 全量重筛（不记录 processed）：否决——必然重复劳动
- 自动价值判断（脚本评分代替 agent 评估）：否决——四门槛需读线程语义，脚本做不了（原则五）
- skipped 清单精细化（记录每条被排除原因）：推迟——当前 processed 已含全部评估过编号，足够防重

## 参数治理

评论数门槛（默认 3）、标题排除规则为初始估计，随真实评估反馈复核（若候选过少可降门槛，过多可升）。
