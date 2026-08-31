---
name: knowledge-groom
description: >
  昇腾知识库的周期性维护引擎。批处理 postmortems/inbox/ 待审队列（预分诊 new/variant/covered 三分类），
  结构化升格到 Tier 2、校验 references 完整性、检测值重复、重算 confidence_score、
  软退休过期 case、重建生成索引；并行维护先验知识层（references/）——
  审核 references/ 的 draft 草稿、校验引用、失效降级信号、引用发现建议。建议每周运行。
  产出**变更摘要 + 待审项**交领域 owner 审；提交由 owner 自己来（不自动开 PR）。
disable-model-invocation: true
---

# Knowledge Groom

> **本地执行说明**：本 skill 标记 `disable-model-invocation`（防 agent 自发启动批量改库）——skill 工具加载会报 "not available for model invocation"，这是预期。用户明确要求 groom 时，agent 直接 `read` 本文件手动遵循流程即可，流程完整性不受影响；或用户输入 `/skill:knowledge-groom` 直接触发。

体系的演化引擎。不加控制的增长会摧毁检索效率——这个 skill 是知识库的"免疫系统 + 清道夫"。

## 触发

手动运行，建议每周一次（连续四周无新 postmortem 则自动切双周）。

## 流程（一次 groom 产出一个变更摘要）

1. **intake 队列处理（升格的前置）**：处理 `postmortems/inbox/`（`/skill:to-postmortem` / `/skill:issue-ingest` 的产出都落这里）：
   - **节律**：单仓集中可周批；**分布式（成员本地 inbox，远程仓不存）在提交主仓时处理**——产出时已做 pre-triage（见下），groom 复核确认而非重判；
   - 逐条**预分诊**（agent 判断，给证据；当前不引入 embedding，论证见 docs/adr/0002——可选论证层）：`new_pattern` / `variant_of:<case-id>` / `covered_by:<case-id>` + 置信度。比对对象：命中 namespace + `common/` 的现有 case——用 `knowledge/_index.yaml` 按 symptoms/tags 定位候选，全量读比对 root_cause 与 fix。**draft 头注释已带 to-postmortem/issue-ingest 产出的分诊建议 → 复核证据是否成立，不重判**（建议与决定分离：判断在产出时做，groom 是审核者）；
   - 产出**批审清单**交 owner 处理（像清 PR inbox，~30 秒/条）：
     - `covered_by` → 建议关闭升格；postmortem 转正 `postmortems/YYYY-QN/`（Tier 3 语料，**不是丢弃**）
     - `variant_of` → 建议并入已有 case（扩 compat 区间、补 symptoms）；若要动 `expected`/`fix_on_mismatch` 按高风险变更走双签
     - `new_pattern` → 结构化 + 语义校验 → 升格 `knowledge/<ns>/`。校验失败标 `needs-structurer-review`，语义不明标 `needs-human-review`
   - **转正后回写来源 trace 的沉淀状态（闭环，动作发生时写）**：每条被 accept 的草稿，若来源是诊断 trace（头注释记了 `traces/<session_id>.yaml`），转正落位后**回写该 trace 的 `sedimented.state`**——`new_pattern`/`variant_of` 升格 Tier 2 → `{state: knowledge, caseId: <case-id>}`；`covered_by` 仅 postmortem 转正 → `{state: archived, caseId: <case-id>}`。2026-08-31 教训：groom 转正后未回写，trace 停留 `submitted`，诊断面板"沉淀漏斗"显示 4 沉淀 → 0 转正（数据滞后于实际入库）——零推断纪律同样约束转正侧：**转正是动作，发生时必须写**。
   - inbox 停留 >2 周的条目在摘要里标红（队列不是档案）
   - **建议与决定分离**：预分诊只排序注意力，accept / adjust / reject 由人
1.5. **case 分类校验（三分类强制，废弃 other）**：审核/升格 case 时校验 `category` ∈ {interrupt, precision, performance}——**不存在 other**。发现 other 的 case → 重新分类（按症状性质归入三分类：启动失败/崩溃/资源→interrupt，输出错误/乱码/数值异常→precision，吞吐/延迟→performance）；分不进去 → 标 `needs-human-review`，由 owner 定夺，不静默保留 other。reason：other 是分类残余，实践表明残余全部可归入三分类（2026-08 重分类 5 条验证）；保留 other 会让路由层永远无法到达这些 case（triage-tree 无 other 分支）。
2. **引用完整性校验**:扫所有 case 的 `references`,检查指向真实存在的文件和锚点。悬挂引用进变更摘要（自演化系统的“坏账”，不校验会静默累积）。
3. **值重复检测**：框架 case 的 `expected`/`fix_on_mismatch` 是否硬编码了 `common/` 权威记录拥有的值？是 → 标 must-fix，要求改成引用。
4. **置信度重算**：从 `hits`/`misdiagnoses`/`last_hit` 重算每条 case 的 `confidence.score`（按时间衰减）。**新升格的 case 初始 score 不设 0**——按 to-postmortem 标的 `confidence`（人的调查质量判断）设初始值：**high→0.6、medium→0.3、low→0.1**（Beta 先验超参 $(\alpha,\beta)$ 的实例化；参数治理见 roadmap 待定池，理论推导见 docs/design-theory.md §4.1——该文档为可选论证层，本参数为执行值）。score=0 意味着新 case 永远排候选最后，对 5 天详查的高质量 case 不合理。
5. **软退休**：区分两种"未命中"——
   - **cold**（从未被 quickly_check 选中）→ **不退**（正确但罕见的 case 占索引成本极低，误删是静默损失）
   - **tried-and-failed**（被选中但近 12 周未解决）且 `score` 低 → 移入 `_archive/`
   - `compat` 版本过期 → 移入 `_archive/`（与命中无关）
   - 检查 `_archive/` 中 case 是否因新 `compat` 区间该复活（2.7 退休、2.8 恢复）
6. **容量治理与拆分建议**：cap 按 **(framework × category) 格子**计，执行参数：**soft_cap=30**（触发拆分评估）、**hard_cap=60**（信道物理上限，强制拆）；健康指标阈值：候选溢出率 >20%、同根因重复率连续两轮上升、维护时长 >30 分钟/周。每次 groom 附**容量表**：各格子条数 / soft_cap、三项健康指标。任一格子超 soft_cap 即**触发拆分评估**（不是立即拆）：查健康指标，任一恶化 → 报告内容分布 + 拆分建议（首选 category 轴深化或按 platform 轴）；超 hard_cap 无论健康指标**强制拆**。拆分被数据预告，不被卡住才想起（论证见 docs/adr/0004——可选论证层，上述数值为执行值，参数待 metrics 复核）。
7. **同 namespace 合并建议**：相似 case 对自动提示。
8. **索引维护（收尾必做）**：所有 KB 变更（升格/合并/退休/改 confidence）完成后，运行 `python3 scripts/build_index.py` 重新生成 `knowledge/_index.yaml` 并随变更摘要一起提交。`--check` 报过期 = 变更不完整（忘了重建索引）。软退休的 case 移 `_archive/` 后自动从活跃索引消失。

## reference 维护（先验知识层——与 case 流程并行）

先验知识层（`references/`）是独立资产，维护动作与 case 平行：

**R1. reference 草稿审核**（`/skill:to-reference` 的产出以 draft 直进正式目录——无 _inbox，PR review 即审核闸门）：
- 逐条审：accept → 移入 `references/<type-dir>/`；adjust / reject / defer；
- **深审门槛**：case-derived + methodology 词条需 ≥3 条 case 引用（派生计数，`verify_references.py` 强制）才可 `active`，否则留 `draft`；
- draft 词条停留 >2 周标红提醒（队列不是档案）。

**R2. 引用完整性校验**：case 的 `ref_knowledge.ref` 必须真实存在于 `references/`（`verify_references.py` 已强校验悬挂引用与非法 role——groom 把结果带进变更摘要，不重复计算）。

**R3. 引用发现（可选建议，不强制——case 不"应该"连 reference）**：扫描 case 的 `diagnosis`/`fix` 内容，发现**隐式依赖**某 active reference（如 fix 提到"HCCL_BUFFSIZE 需重启生效"而该事实是独立词条）但未填 `ref_knowledge` → 变更摘要建议"该 case 可补 ref_knowledge"，由 owner 决定。**大多数 case 是自包含闭环（quickly_check/diagnosis/fix 都在体内），不需要连**——只有依赖命令副作用 / 平台硬事实 / 错误码含义等独立先验事实的少数 case 值得连；强制连接只会增加维护负担和脆弱引用。

**R4. 失效与降级信号**：见下方信号表新增行。

**R5. 校验**：改动 reference 后运行 `python3 scripts/verify_references.py --check`（与 build_index 并列，CI 同样强制）。

**R5.5. 修订中的 reference（内容修订机制）**：`pending-review` / `draft` 词条在变更摘要里列出并标注**修订中/待修订**，提示 owner 安排：
- 有修订 PR 在走 → 摘要注明"修订中"（status 保持降级态，diagnose 不加载）；
- 无修订 PR 但已标降级 → 提示"待修订"，owner 决定：小修直接改 YAML + PR，大修用 `/skill:to-reference --update <ref-id>`；
- 修订走 PR 时按 **kb/high-risk** 处理（改 active 内容 = 修改已生效知识，双签）。

**R6. reference 可观测性回写**：跑 `python3 scripts/trace_metrics.py` 提取 reference 指标（hits / 引用后 resolve 率 / 平台分布），把结果带进变更摘要：
- **有数据才回写**：某 ref 被引用（hits ≥1）→ 更新其 `hits`/`last_hit` 字段（trace 数据积累后才有）；引用后 resolve 率异常低 → 触发降级信号（见信号表）；
- **无数据如实显示**：reference 刚建立时 trace 无 `reference_lookup` 事件 → 如实报 0，不编造指标（诚实退化）。

**R7. reference 索引触发检测（修订 2 渐进式）**：每次 groom 检查——
- `references/` 下文件数 >50，**或** metrics 显示 reference 检索退化（漏检增多 / 平台匹配耗时长）；
- 达到 → 变更摘要**建议**生成 `references/_index.yaml`（`build_references_index.py`，与 case 层 `build_index.py` 同构）——**只建议不自动生成**（建议与决定分离）；未达到 → 不提及（目录 + grep 足够，不为不存在的规模购置基础设施）。

**R8. case 共性提炼候选（case-derived reference 触发信号）**：每次 groom 扫 `knowledge/_index.yaml` 的 tags——**同 tag 的 case ≥3 条** → 变更摘要列出该组（case id + tag + root_cause 摘要），**建议**走 `/skill:to-reference --ingest-cases "[id1, id2...]"` 提炼共性（methodology / error-code 表追加）——只建议不自动提炼（建议与决定分离；同 tag 是弱信号，是否提炼由 owner 定）。**排除已覆盖 case（2026-08-31 教训）**：聚类前先汇总 `references/**` 词条的 `sources[].cases` 与 `content.*.source_cases` 中已出现的 case id，从候选中剔除——已被 reference 收录的 case 不再重复建议提炼（例：glm5 组 9 条中 6 条已在 `glm-quantized-startup-triage`，原 R8 重复建议）。理由：共性识别靠人工不可持续（2026-08 从 42 条 case 人工发现 MoE 通信算子族，4 条同 tag）；tag 聚类是零 token 的机械信号，先把候选端到人眼前——但已覆盖排除同样是机械可查的（grep `source_cases`/`cases:` 汇总），建议前必须做。

**R9. fixture 候选语义预核（agent 预核 → 人确认，A 的语义侧）**：跑 `python3 scripts/replay_trace.py --emit-fixtures` 产出 fixture 候选（`_candidate: true`，期望=实际命中 case，输入=多轮 user 原文折叠，已按覆盖去重）。**对每个候选做三项语义判断，填 `agent_review` 字段**（建议与决定分离——意见供人核，不替代人）：
- `expectation`：核对命中 case 的 `root_cause`/`fix` 与该 trace 的证据是否一致——`trustworthy`（证据一致，可信）/ `uncertain`（证据不足，需人重点核）/ `misdiagnosed`（命中 case 与证据矛盾，**建议不入 fixture**，并触发误诊归因）；
- `input_sufficient`：`true` / `false`——输入是否含判别信号（版本/错误码/配置），缺什么在 `redaction_notes` 旁补一句；
- `redaction_notes`：检查输入原文是否含客户敏感信息（内网 IP/路径/账号），含则标注需脱敏。
预核意见随候选交 owner，owner 确认后移除 `_candidate` 与 `agent_review` 字段入库 `eval/golden/`；`misdiagnosed` 的候选转误诊归因流程（trace 归因→case 错改库/执行错改 skill），不入 fixture。理由：脚本（确定性）只能保证结构正确，期望正确性与输入充分性是语义判断——agent 预核把人的核对负担从"从零核"降到"对齐意见判断"，与 E1（agent 自起草候选 case）同构。

## 变更摘要里的高风险变更标记（强制深审，不走 30 秒快通道）

- 新建 `common/` 权威记录
- 改 `expected` 值
- 改 `fix_on_mismatch`
- 改 `compat` 区间
- `confidence.score` 被手动覆盖

高风险变更要求两个 owner 签字（领域 owner + 体系维护人）。变更在 session 内**随机排序**审，对抗疲劳——一个 session 审 30 条变更，第 30 条得到的 scrutiny 远少于第 1 条，随机化缓解这个偏差。git 落地：变更走 PR 并打 `kb/high-risk` 标签，`CODEOWNERS` 双组路径强制对应 owner 审批（owner 未定前用 `CODEOWNERS.example` 占位，机制先跑；流程细节见 docs/git-workflow.md——可选论证层）。

## 信号 → 动作（演化信号表）

| 信号 | 动作 |
|---|---|
| 单 namespace 超 30 条 | 给拆分建议（首选 category 轴） |
| 两个框架 namespace 各有条 case 指向同 root cause | 在 `common/` 建权威记录，框架层加 `references` |
| Tier 2 未命中率 > 60% 持续两周 | **先看路由准确率**（见 docs/metrics.md）：路由准确率低→改 triage-tree；路由准但未命中→加 case |
| 某 case `score` 高且命中频繁 | 进候选优先验证队列 |
| 某 case `score` 低仍被加载 | 标待复审；命中一次失败即转人工 |
| 某案例 `needs-structurer-review` 超 14 天 | 提醒领域 owner |
| inbox 条目停留 >2 周 | 变更摘要标红，提醒 owner（队列不是档案） |
| 某 (framework×category) 格子超 soft_cap（30）且健康指标恶化 | 触发拆分评估（category 深化或 platform 轴），不等撞线 |
| 某格子超 hard_cap（60） | 强制拆分（信道物理上限） |
| `references/` 有 draft 草稿 | 审核 R1：accept 翻 active；case-derived methodology 未达 ≥3 引用禁止 active |
| 某 reference `last_verified` 超 90 天未刷新 | 标 `needs-review`，owner 季度审 |
| case-derived methodology 被引用数 < 3（派生计数） | 不允许 active（verify_references 强制；已 active 的降 draft） |
| 工程师反馈某 reference 引用后诊断失败（trace `outcome_after_use` 恶化） | methodology → `draft` + 禁用 30 天；普通 → `pending-review` |
| 某 case 的 `diagnosis`/`fix` 隐式依赖 active reference 但未填 `ref_knowledge` | **建议**补 ref_knowledge（R3，可选——case 不强制连 reference，owner 决定） |
| 某 reference sources 链接失效（spot-check 发现） | 立即标 `pending-review` |

## v2 职责（路线图，v1 不做）

8. **结构挖掘**：挖 trace 语料，报告低判别力 `quickly_check`、噪声 triage 分支、高验证耗时 case。让库学结构，不只 bump 分数。
9. **trusted auto-promotion 审计**：近重复 + quickly_check 通过 + 连续 N 次兄弟命中未误诊的新 case 可 auto-promote，标 `auto_promoted: true`，进月度抽审。
