---
name: self-evolve
description: >
  自演进深度轮（显式触发）+ 攒批聚合器。用户下内容目标（补 case / reference 沉淀 /
  诊断 / 拉取）时，由对应内容 skill 执行，**收尾自动跑 evolve-check**（/skill:evolve-check，
  伴随评估：有信号产卡、agent 自验证并判断采纳——用户不需要另说"改进系统"）。
  本 skill 只管两件事：①用户显式说"跑一轮自演进/看看有什么可改进"时的**全库深度
  观测轮**（跨轮聚合信号：组件台账 / 容量 / S2 校准集 / timeline → 产候选卡）；
  ②把 evolve-check 与深度轮产出的卡**攒批聚合为一个 PR** 供人审。演进由数据触发
  ——不是用户为"改进"单独立目标，而是系统做事时自动校准；本文自包含执行参数。
disable-model-invocation: true
---

# Self-Evolve（深度轮 + 攒批聚合）

> **本地执行说明**：本 skill 标记 `disable-model-invocation`（防 agent 自发启动批量改库/批量自演进）——skill 工具加载会报 "not available for model invocation"，这是预期。用户明确要求时，agent 直接 `read` 本文件手动遵循流程即可；或用户输入 `/skill:self-evolve` 直接触发。**内容流程收尾的伴随评估不经过本文件**——那是 `/skill:evolve-check`（轻量收尾协议，无 disable）。

> **定位修正**：演进不是"另一类用户目标"，而是任何流程执行中自动校准的维度（像人学习）。本文件不再把"流程/skill 改进"列为用户可选目标态——改进由 **evolve-check 伴随产出**（内容流程收尾）+ **本 skill 深度轮**（用户显式要求全库体检时）承载。

## 触发

1. **深度轮（显式）**：用户说"跑一轮自演进""看看有什么可改进""持续改进 X 的命中率"——全库观测找演进点（不是执行内容任务）；
2. **攒批聚合**：evolve-check / 深度轮产出攒够批边界（轮末 / 10 卡 / 任务目标完成）→ 聚合 PR 交人审；
3. **resume**：被打断的深度轮（session state 续跑）。

用户下**内容目标**（"沉淀 vllm-ascend 的 closed issue""做 reference 沉淀"）→ **不触发本 skill**：路由到 issue-ingest / to-reference / to-postmortem 执行，其收尾自动 evolve-check。

## 一、入口分流（先分清用户要什么，再决定跑不跑本 skill）

| 用户说 | 路由 | 演进如何发生 |
|---|---|---|
| "沉淀 vllm-ascend 的 closed issue" / "做 reference 沉淀" / "诊断这个" | 内容 skill（issue-ingest / to-reference / to-postmortem / diagnose） | issue-ingest/to-reference/to-postmortem 收尾自动 evolve-check（无需用户另说）；diagnose 有内建 evolving（候选 case 起草/顺手 to-reference），其 L2/L3 缺口由 S2 replay 与深度轮覆盖 |
| "跑一轮自演进" / "看看有什么可改进" | **本 skill 深度轮** | 全库观测 → 候选卡 |
| "持续改进 X 命中率"（跨多轮） | 长期任务层（任务状态文件 proposals/tasks/）→ 每轮内容执行 + evolve-check | 任务轮内自动伴随 |

**grill 只在对齐深度轮/任务时用**（至多 2-3 问、说用户语言）：目标态（要达成什么可判定结果）、scope（哪个 namespace/层）、数据源（用户指定）、运行模式（hands-off / 关键人审）。对齐后回显理解，用户确认才执行。

## 二、深度轮：观测什么（跨轮聚合信号 → 候选）

深度轮不做内容执行，只把**已积累的观测数据**转成候选卡。信号源（先跑脚本读聚合，不读 case 全文——原则九）：

| 信号 | 数据源 | 候选动作 |
|---|---|---|
| 容量超 soft_cap / 健康指标恶化 | `knowledge/_index.yaml` 头注（build_index.py 生成） | L1 拆分评估卡（ev_proposal） |
| 组件台账浮出失败簇（反复执行错） | `scripts/component_tally.py` | L2 修订该组件所在 skill 步骤 / triage 分支 |
| S2 校准集未测条目 / replay miss | `scripts/s2_replay.py --todo` | L1 补 case 卡（S2 佐证缺口） |
| 指标漂移（命中率/回滚/token 趋势） | `metrics/timeline.yaml` + trace_metrics | 诊断式候选轮 |
| 长期任务轮间信号 | task/session state | 下一轮范围决策 |

**深度轮不做的事**：不抓新数据、不沉淀内容（那属内容 skill + evolve-check）、不每轮全做——按对齐目标选信号源。

## 三、产卡 + 验证（深度轮与 evolve-check 共用同一条产卡链）

1. 查重：`scripts/ev_proposal.py --list`——同 trajectory/同 target 已有在池卡 → 合并；
2. 产骨架：`scripts/ev_proposal.py --new` → 填字段（layer / title / source_signals 带
   trajectory / hypothesis / predicted_effect / validation / risk / principle_refs）；
3. **agent 自行验证执行**：能即时判定的（检索/路由/脚本/补 case）直接跑 golden 前后
   对照或 S2 replay（replay_golden.py / s2_replay.py）；真实反馈类完成实现 + S2 佐证、
   标"待真实确认"（现场有效性进观察窗，事后结算）；
4. **agent 判断**（EV 卡 = agent 决策档案，不含 git 合入态/待办态）：产卡即执行（方案成形
   才产卡，状态 in_experiment）；eval solid → validated（采纳）；eval 不成立 → rejected
   （不采纳，留结论）；发现更好方向 → superseded（新卡替代）。执行/验证完成而卡仍停
   in_experiment = 卡不完整。

**生命周期完整性（卡 = proposal→action→eval→decision 的 agent 决策档案）**：每步
decisions 记 type（proposal/action/eval/decision）；**status 随执行推进不靠自觉**——
方案成形 → 产卡（in_experiment，开始执行）、agent 判断采纳 → validated / 不采纳 →
rejected / 换方向 → superseded。执行/验证完成而卡停 in_experiment = 卡不完整
（verify_proposals 报）。终态卡（validated/rejected/superseded）必须有 agent 判断的
decision 记录 + validated 补 actual_cost。仅信号无方案不产卡（信号记报告/任务状态，
方案成形才产）。

## 四、skill 自我演进（L2：被数据信号触发，不是用户目标）

skill/流程改进**由信号驱动**，两条来源：

1. **evolve-check T4/T7**（内容流程收尾发现：执行错反复无归属 / 可复用链路跑通）→ 产 L2 候选卡：修订指定 skill 步骤 / 沉淀新 skill 候选（弱信号，新 skill 立项走双签）；
2. **深度轮台账信号**（组件失败簇）→ 同上产卡。

**验证门（改 skill 强制）**：skill 改动合入前必须过 golden 前后对照（eval/golden + S2
replay 校准）——改 skill 影响所有下游，验证不可省；结构级（骨架/新 skill 立项）走
dual 双签 + kb/high-risk，步骤级小调 review。

## 五、攒批 / 聚合 PR（evolve-check 与深度轮的共同出口）

- **批边界**（任一触发即提聚合 PR，防无限攒批）：目标态完成 / 降级完成（如"沉淀 100 条
  实际只有 60 条"）/ 深度轮停止条件触发 / 攒够 10 卡；
- **聚合 PR**：每卡独立 commit（可逐卡 revert）；PR body 按卡列 EV id + 验证 + 授权
  级别，dual 标 kb/high-risk；模板按批内最高风险选；
- 人审可整体合入或按卡打回（打回卡 revert 其 commit，其余照常）。

## 验证先于判断

- **即时判定类**（检索/路由/skill 流程/脚本）：eval 完成（S2 replay / golden）——solid 才判
  validated（采纳），不采纳则 rejected；
- **真实反馈类**（content/fix）：判 validated 前完成实现 + S2 佐证，现场有效性合入后进
  观察窗等真实场景——如实标注"已实现待真实确认"（观察窗结果作为追加 decision，不改卡状态）。

## 停止条件（深度轮，任一满足即停出报告）

预算耗尽（对齐时确认）/ 产出达标（validated/候选达 N，默认 3）/ 目标态达成 /
无新信号 / 人中断。

## 报告

本轮产出汇总：目标态 → 结果对照、产了几张卡（标注来源：evolve-check 伴随 vs 深度轮）、
验证依据、成本、下一步建议。报告落 `proposals/reviews/`（运行时 gitignore）。

## 边界（不做）

- 内容目标不进本 skill（路由到内容 skill + evolve-check）；
- 指标口径只有人能改（agent 不自改评分定义）；
- 不碰客户现场；蓝图态（长期任务层跨轮自动/超时降级/stale/策略记忆/稳态降频）触发条件出现才启用。

## 依赖的能力/工具

| 能力 | 工具/入口 | 何时用 |
|---|---|---|
| 伴随评估（内容流程收尾） | /skill:evolve-check | 内容 skill 收尾自动（用户下内容目标时隐含） |
| 观测（深度轮信号） | `scripts/component_tally.py` / `s2_replay.py --todo` / `_index.yaml` 头注 | 深度轮 |
| 查重/产卡 | `scripts/ev_proposal.py --list / --new` | 产卡时 |
| 卡校验 | `scripts/verify_proposals.py` | 产卡后必跑 |
| 验证门 | `scripts/replay_golden.py` / `scripts/s2_replay.py` | skill/case 改动验证 |
| 内容沉淀（evolve-check 落点） | /skill:to-reference / /skill:to-postmortem | 伴随评估产出指向 |
