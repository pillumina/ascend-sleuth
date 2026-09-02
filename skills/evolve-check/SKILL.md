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
> 另说"改进系统"。机制推导见 docs/evolution-pipeline.md §4/§6 与
> docs/evolution-orchestration.md §1.2（演进 = 隐形执行策略的一部分，非用户负担）。
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
  与深度轮台账信号覆盖，见 /skill:self-evolve §二；
- knowledge-groom：批审产出后。

触发**不需要用户说"跑自演进"**——它是流程的默认收尾步骤（同 diagnose 写 trace 的
地位）。如果一轮内容执行本身就是自演进深度轮的一部分（self-evolve 驱动），跳过本
协议（深度轮已含观测）。

## 评估步骤（先扫信号，无信号即止）

**第 1 步：读本轮执行现场**（不重扫全库、不读 case 全文——token 预算，原则九）：

- 本轮产出了什么（case/reference/卡/草稿的 id 与内容摘要）；
- 过程中有没有：miss（diagnose 无命中 / replay 未命中）、重复手动动作、
  流程摩擦（来回确认、缺信息重跑）、执行错、新数据源/新 issue 类型首次出现。

**第 2 步：对照触发条件表**——命中的信号才继续，无命中直接出报告（加一行
"evolve-check：无演进信号"），**不为产卡而产卡**（原则四/十）。

| # | 信号（本轮执行现场） | 含义 | 候选动作 |
|---|---|---|---|
| T1 | 沉淀 ≥3 条同根因/同族 case，或发现可跨 case 归纳的共性 | 有 methodology/reference 可提炼 | 产 L2 卡：归纳 reference（走 /skill:to-reference --ingest-cases） |
| T2 | diagnose/replay miss 某 issue 族，或 Tier 3 兜底反复走同路径 | 覆盖缺口 | 产 L1 卡：补 case（S2 replay 佐证缺口） |
| T3 | 同一手动动作重复 ≥2 次（如反复拼同一查询、反复等同一命令输出） | 可固化流程/脚本 | 产 L2 卡：沉淀脚本/skill 步骤或 reference |
| T4 | 执行错反复出现且无归属组件 / 组件台账浮出失败簇 | 流程缺陷（pipeline §4.2） | 产 L2 卡：修订该组件所在 skill 步骤 / triage 分支 |
| T5 | 新数据源/新 issue 类型/新错误码首次出现且无配置 | 覆盖扩展 | 产 L1/L2 卡：扩配置 / 补 reference 家族 |
| T6 | 容量超 soft_cap 或健康指标恶化（_index 头注） | 结构治理 | 产 L1 卡：拆分评估（ev_proposal） |
| T7 | 本轮跑通一个可复用链路（拉取→评测→沉淀→验证全通） | 新流程资产 | 产 L2 卡：沉淀为 skill/脚本候选（§4.4 弱信号） |

**第 3 步：产卡 + 自行验证（有信号时，agent 自动完成，不等用户）**：

1. 查重：`python3 scripts/ev_proposal.py --list`——同 trajectory/同 target 已有在池卡
   → 合并不新建（orchestration §2.4）；
2. 产骨架：`python3 scripts/ev_proposal.py --new` → 填字段（layer / title /
   source_signals 带 trajectory / hypothesis / predicted_effect / validation /
   risk / principle_refs），trajectory 必须指到本轮执行出处（产出文件 id / replay
   结果 / trace）；
3. **自行验证执行**（评估自动化的核心——agent 自己验证，不把验证推给人）：
   - 能即时判定的（检索/路由/脚本/补 case）：直接跑 golden 前后对照或 S2 replay
     （`scripts/replay_golden.py` / `scripts/s2_replay.py`），数据通过才进批；
   - 不能即时判定的（真实反馈类 content/fix）：完成实现 + S2 佐证，如实标注
     "已实现待真实确认"，进观察窗（execution §5）；
4. 验证通过 → 卡进攒批（status → proposed → in_experiment → pending_merge）；
   验证失败 → 卡 rejected（留结论）或 re-iterate，**不推进**（§6.5 无实验证据不合入）。

**第 4 步：出收尾说明**（并入流程报告，不单独打扰用户）：

```
evolve-check：产出 EV-xxxx（补 case，S2 replay 佐证缺口）→ 已自行验证 → 进攒批
或：evolve-check：无演进信号（本轮无新增数据/无流程摩擦/无覆盖缺口）
```

## 与 self-evolve 的分工

| | evolve-check（本协议） | self-evolve（深度轮） |
|---|---|---|
| 触发 | 内容流程收尾自动（用户下内容目标即隐含） | 用户显式"跑一轮自演进/看看有什么可改进" |
| 范围 | 本轮执行现场（一流程一查） | 全库观测（台账/容量/覆盖/指标） |
| 信号源 | 本次产出的数据 + 摩擦 | 跨轮聚合（组件台账、S2 校准集、timeline） |
| 共用 | idea 卡 schema / 验证门 / 三级授权 / 攒批聚合 PR（pipeline §6） | 同左 |

两者产出同一批池（`proposals/ideas/`），攒批聚合 PR 人审时合并处理，不区分来源。

## 授权与合入（沿用 pipeline §6，本协议不另立）

- **产卡与验证是 agent 自动的**（本协议第 3 步）；**合入仍走攒批 PR 人审**——
  内容级 auto（合入后抽审）/ 判断性 review / 结构级 dual 双签，按卡 authorization 字段；
- 指标口径红线保留：产卡不得改评分/指标定义（系统不改自己考卷，orchestration §4）；
- 结构级（triage/skill 骨架/新 skill 立项）走 kb/high-risk 双签，本协议只产候选不直改。

## 边界（不做）

- 不为产卡而产卡：无信号即止；候选水位超限时只记信号不产卡（orchestration §2.4）；
- 不代替用户下内容目标：本协议只回答"这次做完能否更好"，不决定"下次做什么"；
- 不碰客户现场、不做批量改库（那是 self-evolve 深度轮 + 人审的范围）。

## 依赖的能力/工具

| 能力 | 工具/入口 |
|---|---|
| 查重/产卡骨架 | `scripts/ev_proposal.py --list / --new` |
| 卡校验 | `scripts/verify_proposals.py` |
| 验证门（即时判定） | `scripts/replay_golden.py` / `scripts/s2_replay.py` |
| 组件台账（T4 信号） | `scripts/component_tally.py` |
| 内容沉淀（T1/T2 落到执行） | /skill:to-reference / /skill:to-postmortem |
