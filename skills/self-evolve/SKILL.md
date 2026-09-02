---
name: self-evolve
description: >
  自演进执行引擎（目标驱动版）。用户说一个目标（可能模糊），先通过 grill
  对齐"目标态"（要达成什么、scope 哪层/哪个仓、数据源由用户指定），再按目标
  装载对应能力（拉用户指定源的 issue / 按用户给的具体来源做 reference 沉淀 /
  S2 replay 测试 / 补 case / skill 流程改进——**不是每轮全做**），执行中可沉淀可复用流程、可提议
  改进 skill 本身，产出带轨迹依据的 idea 卡 → 校验 → 攒批 → 聚合 PR 给人审。
  机制设计见 docs/evolution-orchestration.md §1.2（目标→对齐→装载→执行，
  可选论证层）；本文件自包含执行参数。触发语义同 knowledge-groom
  （disable-model-invocation，人显式触发）。
disable-model-invocation: true
---

# Self-Evolve

> **本地执行说明**：本 skill 标记 `disable-model-invocation`（防 agent 自发启动批量改库/批量自演进）——skill 工具加载会报 "not available for model invocation"，这是预期。用户明确要求跑一轮自演进时，agent 直接 `read` 本文件手动遵循流程即可；或用户输入 `/skill:self-evolve` 直接触发。

让系统改进自己。一轮 = 一次有状态会话（目标对齐 → 按目标执行 → 验证 → 人审合入 → 报告）。**核心：先对齐目标态，再选能力——不是固定管道。**

## 触发

手动运行。用户说"跑一轮自演进""我想做 reference 沉淀""持续改进 X"（目标可以模糊）时触发。产出**候选 idea 卡 / 沉淀草稿 / 流程改进 + 聚合 PR** 交人审，不自动合入结构级改动。

## 一、目标对齐（grill——先澄清，不猜着跑）

用户的目标**常是模糊的**（"做 reference 沉淀""看看怎么改进"）。对齐目标态是关键步——**对齐不是让用户补机制描述**（机制是默认的），是确认目标本身（orchestration §1.2 ③）。逐项澄清（至多 2-3 问，说用户语言不用术语）：

1. **目标态（要达成什么可判定的结果）**：
   - "做 reference 沉淀" → 澄清：沉淀哪类？错误码/环境变量/故障模式/平台事实？从哪个源（官方文档 URL / case 归纳 / 你提供材料）？产出几条？
   - "持续改进 vllm-ascend 命中率" → 澄清：改进对象是检索命中还是补 case？预算？
   - "看看有什么可改进的" → 给 2-3 个候选目标让用户选（容量拆分 / S2 缺口补 case / 流程改进），不代用户决定。
2. **scope**：哪个仓库/namespace/层（L1 知识 / L2 流程 skill / L3 机制）？
3. **数据源（用户指定，不默认全拉）**：拉哪些仓的 issue？爬哪个官方文档 URL？用户说"就用 vllm-ascend"就只处理它；没说清 → 问，不擅自全跑。
4. **运行模式**（介入度）：全自动 hands-off（做完给 PR）/ 关键人审 default。

对齐后回显理解："我理解为：目标是 <X>，范围 <Y>，数据源 <Z>，将用 <能力列表>，约 <N> token。"用户确认才继续。

## 二、目标 → 能力映射（能力库，按需装载）

能力**不是每轮全做**——按对齐后的目标选。以下是能力清单与适用目标：

| 目标态 | 装载的能力 | 工具/入口 |
|---|---|---|
| **reference 沉淀** | 用户给具体来源（URL/文档/案例）→ to-reference 提炼草稿（to-reference 自带 URL 爬取；**不做预置通用文档抓取器**——抓哪个源、抓什么由用户具体要求驱动） | /skill:to-reference |
| **补 case / 提命中** | 拉指定仓 issue（用户指定源）→ 扩 S2 → replay 测缺口 → 补 case | auto_fetch.py + s2_calibration + s2_replay + /skill:to-postmortem |
| **覆盖发现（不问源）** | S2 replay 测试已有校准集 → miss = 覆盖缺口 | s2_replay.py --todo |
| **流程/skill 改进** | 组件台账/归因信号 → skill 改动提议（走验证门）→ 或沉淀新流程 | component_tally.py + 本 skill §四 |
| **容量/结构治理** | 观测容量 → 拆分评估候选 | ev_proposal.py |
| **token 效率** | （蓝图：token 记账未落地） | — |

**调用纪律**：
- 用户没指定数据源 → **问**，不默认全拉（你批评的对：auto_fetch 拉全部已配源是死板）；
- 目标是 reference 沉淀 → **不拉 issue**（拉 issue 与 reference 目标无关）；
- 目标是补 case → 才拉该仓 issue + replay；
- 观测（容量/台账/指标）是**低成本的默认前置**，任何目标都先扫一眼（不读 case 全文）。

## 三、执行所选能力

按目标执行装载的能力，中间产出随目标而异：

- **reference 沉淀** → 草稿进 references 待审（official-doc 双签闸门，见 /skill:to-reference）；
- **补 case** → postmortem 草稿进 inbox（to-postmortem 路径）；
- **skill 流程改进** → 改动提议（不直接改——L2 验证门 + 人审）；
- **产 idea 卡**：需要形成候选卡时用 ev_proposal（--list 查重 → --new 产骨架 → 填字段）。

产卡填写：layer / title / status=candidate / authorization / dimension /
source_signals（带 trajectory）/ hypothesis / predicted_effect / validation /
risk / principle_refs / decisions。**只产建议与证据，不自行合入**（原则五）。

## 四、skill 自我演进（L2：流程沉淀 + skill 改进）

演进过程中**发现可复用流程 / 值得改的 skill** 时（这是 self-evolve 的核心维度之一，不只是知识）：

1. **可复用流程沉淀**：本轮做了个有效动作（如"拉 issue→S2→补 case"的完整链路跑通）→ 判断是否值得固化为 skill/脚本（§4.4 触发：同一执行错反复出现 / 同一动作反复手动做）→ 产**新 skill/脚本候选卡**（layer=L2/L3，走 methodology PR + 验证门）；
2. **改进现有 skill**：发现 diagnose/groom 某步骤该改（组件台账信号 / 归因指向）→ 产**skill 修改卡**（指定 target_component）；
3. **验证门（改 skill 强制）**：skill 改动合入前必须过 golden 前后对照（eval/golden + S2 replay 校准）——改 skill 影响所有下游，验证不可省（pipeline §4.3）；
4. **skill 改动授权**：结构级（骨架/新 skill 立项）走 dual 双签；步骤级小调 review。

## 五、校验 / 攒批 / 聚合 PR

- **校验**：产了卡 → `python3 scripts/verify_proposals.py`（失败修卡不跳过）；
- **攒批**：本轮多张卡攒到批边界（一轮结束 / 攒够 10 / 任务级攒批到目标完成）；
- **聚合 PR**：每卡独立 commit（可逐卡 revert）；PR body 按卡列 EV id + 验证 + 授权级别，dual 标 kb/high-risk；模板按批内最高风险选；
- 人审 PR 后合入；打回的卡 revert 其 commit，其余照常。

## 验证先于合入

- **即时判定类**（检索/路由/skill 流程）：eval 在合入前完成（S2 replay / golden）——通过才进批，PR 呈现已验证改动；
- **真实反馈类**（content/fix）：合入前实现 + S2 佐证，合入后观察窗等真实场景——如实标注"已实现待真实确认"。

## 停止条件（任一满足即停，出报告）

- 预算耗尽（对齐时确认）；- 产出达标（validated/候选达 N，默认 3）；- 目标态达成（对齐时定义的可判定结果已满足）；- 无新信号；- 人中断。

## 报告

本轮产出汇总：目标态 → 结果对照（达成/未达）、产了几张卡/草稿/改进、验证依据、成本、下一步建议。报告落 `proposals/reviews/`（运行时 gitignore）。

## 边界（不做）

- 指标口径只有人能改（agent 不自改评分定义）；- 不碰客户现场；
- 蓝图态（长期任务层跨轮自动/超时降级/stale/策略记忆/稳态降频）未实现——触发条件出现才启用（pipeline §11.1）。

## 依赖的能力/工具

| 能力 | 工具/入口 | 何时用（目标驱动） |
|---|---|---|
| issue 增量拉取 | `scripts/auto_fetch.py --source <用户指定>` | 目标=补 case/提命中 且用户指定源 |
| S2 校准集构建/扩展 | `scripts/s2_calibration.py --incremental` | 需要评测集时 |
| S2 replay 测试 | `scripts/s2_replay.py --prepare/--todo/--collect` | 用已闭环 issue 验证诊断（提命中/覆盖发现） |
| 产卡辅助 | `scripts/ev_proposal.py` | 形成候选卡时 |
| 卡校验 | `scripts/verify_proposals.py` | 产卡后必跑 |
| 组件台账 | `scripts/component_tally.py` | 流程/skill 改进目标 |
| golden 回放 | `scripts/replay_golden.py` | skill 改动验证门 |
| knowledge/reference 沉淀 | /skill:to-postmortem, /skill:to-reference（URL 爬取走 `--ingest`，无需预置抓取器） | 补 case / reference 目标 |
| proposals/ideas/ | 卡资产（入 git） | — |
