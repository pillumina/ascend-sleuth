---
name: evolve-check
description: >
  任何内容流程收尾的伴随演进评估（数据驱动的 self-evolving，非独立目标轮）。
  用户下内容目标（补 case / reference 沉淀 / 诊断 / 拉取 / replay）后，执行中产生
  的数据（新沉淀、miss、重复动作、流程摩擦）本身就是 evolving 信号——本协议在
  流程收尾低成本检查：对照触发条件表 → 有信号才产 idea 卡并自行验证执行
  （agent 自产卡 + 自验证 + 攒批聚合 PR 人审），无信号一行即止。演进不是"跑一轮
  自演进"才发生，而是系统做事时自动校准——像人学习。深度全库观测轮（用户说
  "看看有什么可改进"）见 /skill:self-evolve；本文件是被内容流程收尾引用的轻量协议。
---

# Evolve-Check（收尾评估协议）

> **定位**：self-evolve 的伴随形态。self-evolve = 用户显式发起的深度轮（全库观测/
> 攒批/聚合）；本协议 = **任何内容流程收尾自动执行的轻量检查**——用户说"沉淀
> vllm-ascend 的 closed issue"，issue-ingest 跑完收尾即触发本协议，不看用户是否
> 另说"改进系统"。演进是隐形执行策略的一部分；本文自包含执行参数。
>
> **本地执行说明**：本 skill 是收尾协议，非独立用户入口。内容流程（issue-ingest /
> to-reference / to-postmortem / diagnose / knowledge-groom）收尾时，agent
> `read` 本文件并遵循下方流程；用户说"这次做完有什么可改进的/值得沉淀的"也可直接触发。

## 何时触发（收尾钩子）

任何内容流程**完成主体目标后、出最终报告前**执行一次，成本目标近零（无信号即止）：

- issue-ingest：沉淀与标记完成后；
- to-reference / to-postmortem：草稿产出、落盘后；
- diagnose：**不强制每次收尾跑本协议**（高频 + 已有内建 evolving：未命中起草候选
  case、源码揭示稳定结构事实顺手走 to-reference、反馈捕获写 feedback_pending）——
  其 L2/L3 视角（反复 miss 同族、流程摩擦）由 S2 replay（`s2_replay.py --todo`）
  与深度轮归因事件信号覆盖，见 /skill:self-evolve §二；
- knowledge-groom：批审产出后。

触发**不需要用户说"跑自演进"**——它是流程的默认收尾步骤（同 diagnose 写 trace 的
地位）。如果一轮内容执行本身就是自演进深度轮的一部分（self-evolve 驱动），跳过本
协议（深度轮已含观测）。

## 评估步骤（先扫信号，无信号即止）

**第 1 步：读本轮执行现场**（不重扫全库、不读 case 全文——token 预算，原则九）：

- **优先读统一执行记录**：内容 skill 收尾时已由 `log_skill_exec.py` 落一条到
  `metrics/skill-exec-log.yaml`（skill/时间/产出 id/decision_reason）。本步读最近几条：
  `python3 -c "import yaml;d=yaml.safe_load(open('metrics/skill-exec-log.yaml'));print('\n'.join(f\"{r['seq']} {r['skill']} {r.get('at','')[:16]} {r.get('products','')} {r.get('decision_reason','')[:40]}\" for r in (d.get('records') or [])[-3:]))"`
  ——拿"本轮做了什么"（替代凭 agent 记忆）：
- 产出：本轮新增 case/reference/卡 id（从记录 products 提取，不重扫全库）；
- 过程中有没有：miss（diagnose/replay 未命中）、重复手动动作、流程摩擦、执行错、
  新数据源/新 issue 类型首次出现——这些在 decision_reason 未提及时由 agent 现场补判断；
- **无执行记录时**（历史流程/外部动作）：如实标注"无执行记录，基于现场判断"——不假装
  有数据（诚实退化）；内容 skill 收尾应落记录（见各 skill「收尾」节）。

**第 2 步：对照触发条件表**——命中的信号才继续，无命中直接出报告（加一行
"evolve-check：无演进信号"），**不为产卡而产卡**（原则四/十）。

| # | 信号（本轮执行现场） | 含义 | 候选动作 |
|---|---|---|---|
| T1 | 沉淀 ≥3 条同根因/同族 case，或发现可跨 case 归纳的共性 | 有 methodology/reference 可提炼 | 产 L2 卡：归纳 reference（走 /skill:to-reference --ingest-cases） |
| T2 | diagnose/replay miss 某 issue 族，或 Tier 3 兜底反复走同路径 | 覆盖缺口 | 产 L1 卡：补 case（S2 replay 佐证缺口） |
| T3 | 同一手动动作重复 ≥2 次（如反复拼同一查询、反复等同一命令输出） | 可固化流程/脚本 | 产 L2 卡：沉淀脚本/skill 步骤或 reference |
| T4 | 执行错反复出现且无归属组件 / 归因事件聚合浮出失败簇 | 流程缺陷 | 产 L2 卡：修订该组件所在 skill 步骤 / triage 分支 |
| T5 | 新数据源/新 issue 类型/新错误码首次出现且无配置 | 覆盖扩展 | 产 L1/L2 卡：扩配置 / 补 reference 家族 |
| T6 | 容量超 soft_cap 或健康指标恶化（_index 头注） | 结构治理 | 产 L1 卡：拆分评估（ev_proposal） |
| T7 | 本轮跑通一个可复用链路（拉取→评测→沉淀→验证全通） | 新流程资产 | 产 L2 卡：沉淀为 skill/脚本候选（弱信号，新 skill 立项走双签） |

**第 3 步：产卡 + 自行验证（有信号时，agent 自动完成，不等用户）**：

1. 查重 + **同组件先例咨询**（防重提被拒方案——skill-impact 咨询语义，2026-09；
   论证可选层 docs/evolution-pipeline.md §12a）：`python3 scripts/ev_proposal.py --list`
   ——同 trajectory/同 target 已有在池卡 → 合并不新建（候选水位超限时只记信号不产卡）；
   同时查本卡要改的组件（skill 步骤 / triage 分支 / script）在历史卡里的结局：
   `--list` 定位同组件卡 → 读其 decisions——该组件被改过 / 回滚过 / 有 rejected 结论 =
   该方向已试过 → 不重复方案（改提新方向，或记信号不产卡）；E6 落地后改用
   `scripts/ev_proposal.py --impact` 聚合视图（组件×尝试×结局）一次查全；
2. 产骨架：`python3 scripts/ev_proposal.py --new` → 填字段（layer / title /
   source_signals 带 trajectory / hypothesis / predicted_effect / validation /
   risk / principle_refs），trajectory 必须指到本轮执行出处（产出文件 id / replay
   结果 / trace）；
3. **自行验证执行**（评估自动化的核心——agent 自己验证，不把验证推给人）：
   - 能即时判定的（检索/路由/脚本/补 case）：直接跑 golden 前后对照或 S2 replay
     （`scripts/replay_golden.py` / `scripts/s2_replay.py`），数据通过才算 eval solid；
   - 不能即时判定的（真实反馈类 content/fix）：完成实现 + S2 佐证，如实标注
     "已实现待真实确认"（现场有效性进观察窗，事后结算）；
4. **agent 判断（EV 卡 = agent 决策档案，不含 git 合入态/待办态）**：
   - eval solid → `validated`（采纳：改动保留，进流程层攒批/PR 供人审）；
   - eval 不成立 / 实验失败 → `rejected`（不采纳：留结论，改动不保留）；
   - 发现更好方向 → 新卡 supersede 本卡（`superseded`）；
   - **产卡即执行（无 candidate 待办态）**——方案成形才产卡，产卡状态 in_experiment
     开始执行；执行或验证完成而卡仍停 in_experiment = 卡不完整（见第 3.5 步）。

**第 3.5 步：生命周期完整性（卡 = proposal→action→eval→decision 的 agent 决策档案）**：

- **每步 decisions 记 type**：产卡记 `{type: proposal}`、执行记 `{type: action, conclusion: <做了什么/commit/产物>}`、
  验证记 `{type: eval, conclusion: <验证数据/通过与否>}`、最终判断记 `{type: decision, conclusion: <采纳/不采纳/换方向+依据>}`——
  卡能看出生命周期走到哪、凭什么判断；
- **status 随执行推进，不靠自觉**：方案成形 → 产卡（in_experiment，开始 action + eval）；
  agent 判断采纳 → validated / 不采纳 → rejected / 换方向 → superseded。**执行或验证完成
  而卡仍停 in_experiment = 卡不完整**（verify_proposals 会报，见下）；
- **终态卡必闭合**：validated/rejected/superseded 必须有 agent 判断的 decision 记录；
  validated 后补 `actual_cost`（成本审计）——缺了 verify_proposals 报审计缺口；
- 仅"观察到的信号"（数据前提未满足 / 无准备执行的具体方案）**不产卡**——信号记 session
  报告/任务状态，条件到（方案成形/数据齐）才产卡执行（防想法清单污染提案账本）。
- **改进动作必须先产 EV 卡（前置元流程，防绕过）**：T1 归纳（→ to-reference --ingest-cases）、
  T5 扩 reference 家族、以及任何"把执行结果固化为会进诊断上下文的资产"的动作——
  **必须先产卡（proposal）→ 执行（action）→ 验证（eval）→ 判断（decision）→ 才随 PR 合入**。
  禁止直接调 to-reference/to-postmortem 产出词条后无卡合入（教训：MTP/startup 归纳先执行
  后补卡——词条已 active 但决策链缺失，人审无据）。内容流程产出草稿进 inbox（待审队列）
  不在此列；凡 **status: active 直进上下文**的产出（reference 词条、triage 改动）必须有
  EV 卡决策链。

**第 4 步：出收尾说明**（并入流程报告，不单独打扰用户）：

```
evolve-check：产出 EV-xxxx（补 case，S2 replay 佐证缺口）→ agent 判断采纳（validated）
或：evolve-check：无演进信号（本轮无新增数据/无流程摩擦/无覆盖缺口）
```

## 与 self-evolve 的分工

| | evolve-check（本协议） | self-evolve（深度轮） |
|---|---|---|
| 触发 | 内容流程收尾自动（用户下内容目标即隐含） | 用户显式"跑一轮自演进/看看有什么可改进" |
| 范围 | 本轮执行现场（一流程一查） | 全库观测（归因聚合/容量/覆盖/指标） |
| 信号源 | 本次产出的数据 + 摩擦 | 跨轮聚合（归因事件、S2 校准集、timeline） |
| 共用 | idea 卡 schema / 验证门 / 攒批聚合 PR | 同左 |

两者产出同一批池（`proposals/ideas/`），攒批聚合 PR 供人审时合并处理，不区分来源。

## 授权边界

- **EV 决策是 agent 做的**（产卡 + 自验证 + 判采纳/不采纳——本协议第 3/3.5 步）；
  卡的 authorization 字段（auto/review/dual）标注的是**改动合入的知识层分级**（改动随 PR
  合入时按此送审），不是 EV 决策需要人逐卡审批；
- **人审发生在目标态完成/降级完成时提的聚合 PR**：审整个自演进过程是否 solid（含 rejected
  卡——agent 提了 EV、实验发现不行、不采纳，这是诚实记录，人审应接受），不是逐卡审批；
- 指标口径红线保留：产卡不得改评分/指标定义（系统不改自己考卷）；
- 结构级（triage/skill 骨架/新 skill 立项）走 kb/high-risk 双签，本协议只产候选不直改。

## 边界（不做）

- 不为产卡而产卡：无信号即止；候选水位超限时只记信号不产卡；
- 不代替用户下内容目标：本协议只回答"这次做完能否更好"，不决定"下次做什么"；
- 不碰客户现场、不做批量改库（那是 self-evolve 深度轮 + 人审的范围）。

## 依赖的能力/工具

| 能力 | 工具/入口 |
|---|---|
| 查重/产卡骨架 | `scripts/ev_proposal.py --list / --new` |
| 卡校验 | `scripts/verify_proposals.py` |
| 验证门（即时判定） | `scripts/replay_golden.py` / `scripts/s2_replay.py` |
| 归因事件聚合（T4 信号） | `scripts/component_tally.py` |
| 内容沉淀（T1/T2 落到执行） | /skill:to-reference / /skill:to-postmortem |
