# 推广就绪度评估（Rollout Assessment）

> 评估日期：2026-08-28。评估基线：main HEAD（ADR-0008 全阶段 + 修订 1 形态校准 + 修订 2 演化机制 + reference 可观测性已合入）。
> 方法：对照 `docs/design-principles.md` 十一条原则逐条核对实现证据；按"机制 / 内容 / 数据 / 运维"四层评估。
> 本文是向团队交付前的依据文档，不是一次性报告——每次重大演进后应重估（原则十一：数据触发演进）。

## 结论（TL;DR）

**机制层：满足推广要求。内容/数据/运维层：不满足——需要第一个团队作为种子用户跑起来。**

这套系统可以交付给第一个团队开始使用，但它交付的是"机制完备 + 少量已验证内容"，不是"开箱即用的知识库"。第一个团队的诊断会大量触发诚实退化路径（空库提示、Tier 3 兜底）——这正是设计预期，但要接受它。

## 一、逐条对照十一条原则

| 原则 | 实现证据 | 状态 |
|---|---|---|
| 一 验证先于交付 | severity 闸门、fix 是建议不动生产、2 次失败转人工、diagnosis checks 验证后才给 fix | ✅ 完整 |
| 二 不变量写进结构 | `build_index.py --check` CI、`verify_references.py` 强校验（含 error-code 表形态：非空/码唯一/逐条必填）、`feedback_pending` 标记、机器路径 CI 挡、词条零注释 | ✅ 完整 |
| 三 底座保持词法 | 无向量检索（ADR-0002）、YAML/git 底座、quickly_check 双 regex、**不引入图存储（ADR-0008 §1.6 明确否决）** | ✅ 完整 |
| 四 知识库有界 | soft_cap 30 / hard_cap 60 + 容量表、`_archive/` 软退休复活、方法论/资产分目录、聚类规则（追加不新建、关联不合并） | ⚠️ case 层完整；**reference 层容量治理参数仍是开放项**（ADR-0008 Open Question） |
| 五 建议与决定分离 | 预分诊三分类 + 人审、高风险双签 + 随机审序、to-reference grill→draft 直进→**PR review 即审核闸门** | ✅ 完整 |
| 六 闸门硬度匹配 | compat 软匹配（ADR-0001）、severity 硬闸、CI 硬门、语义闸门保持约定强度 | ✅ 完整 |
| 七 变更可逆 | fix 带 rollback、`_archive/` 可复活、索引可重建 | ⚠️ case 层完整；自动变更可逆性在 roadmap v2 未实现 |
| 八 可观测先于改进 | trace 硬要求 + 固定词表（含 reference_lookup）、`trace_metrics.py`（case + reference 指标）、`docs/metrics.md` | ⚠️ **机制完整（reference 观测管道已通）但数据只有 W35 一期** |
| 九 稀缺资源显式预算 | 三层加载 + 日志裁剪、inbox 批处理 30 秒/条、reference summary 层先于全文、词条零注释、skill 去 ADR 锚定 | ✅ 完整且精细 |
| 十 诚实退化 | 空库提示三出路、Script 未接明说、机制强度如实标注、reference 只读 active、verification 状态、来源链诚实、无数据如实显示 | ✅ **体系最强项** |
| 十一 数据触发演进 | roadmap 闸门驱动、8 个 ADR 留痕、索引触发检测（groom R7）、参考线留待实测 | ⚠️ 机制完整，**实测数据不足以支撑闸门** |

**机制层判断**：原则一~十的实现基本完整，十一的机制完整。在"结构承载规则"（二）、"诚实退化"（十）、"资源预算"（九）上尤其扎实——这是区别于一般知识库的核心竞争力。

## 二、四层就绪度

### 机制层（就绪 ✅）

| 组件 | 状态 |
|---|---|
| 三层知识加载 + 生成索引 + `--check` CI | ✅ 运行中（case 层） |
| reference 层（类型/表词条形态/状态/校验/CI） | ✅ **完整闭环**：沉淀（to-reference）→ 校验（verify）→ 审核（PR review）→ 演化规则（聚类/索引触发）→ 加载（diagnose 2.5）→ 观测（trace_metrics）→ 回写（groom R6）→ 信号（降级/索引） |
| 5 个 skill | ✅ 全部有实现，to-reference 经 dogfood 修复 + 两轮架构校准 |
| trace + 反馈闭环 + 误诊归因 + reference 观测 | ✅ 机制完整（reference_lookup 已入词表与指标） |
| git 门控（4 类 PR 模板 / kb/high-risk / 双签） | ✅ 模板齐全，双签机制待 owner 落实 |
| ADR 体系（1-8） | ✅ 决策可追溯（含 0008 修订 1/2 记录） |

### 内容层（未就绪 ⚠️，但缺口在收窄）

| 资产 | 现状 | 推广需求 |
|---|---|---|
| knowledge/ | 38 条 vllm-ascend inference；**training（mindspeed-llm/mm/verl）全空**；common/ 空 | 团队诊断的第一个问题可能落在空 namespace |
| references/ | 23 条 active A5 platform-fact + error-code 表（cann-runtime 7 码，draft）+ methodology（GLM 分类树，draft）+ 310P platform-fact（draft）——**error-code/tool/methodology 从全空到首批填充**；**tool 仍空**、A2/A3 platform-fact 仍缺 | 错误码表按官方分族补齐、tool 类（npu-smi/hccn_tool）填充 |
| 覆盖矩阵 | (namespace × category × platform) 仍大面积空缺 | 覆盖报告（roadmap O4）尚未产出 |

### 数据层（未就绪 ⚠️，管道已通）

| 项 | 现状 |
|---|---|
| metrics.md | 仅 W35 一期（vllm-ascend 批量回放），之后未更新 |
| golden 套件 | 23 条 fixture，**无自动 replay**（docs/eval.md 自承依赖人手动） |
| 闸门数值 | 路由准确率/命中率/过滤率仍是假设值（诚实标注"待 metrics 复核"） |
| reference 命中统计 | **观测管道已通**（trace_metrics 支持 reference_lookup，groom R6 回写），数据待 trace 积累（当前如实 0） |

### 运维层（未就绪 ⚠️）

| 项 | 现状 |
|---|---|
| groom 周批 | 机制完整（R1-R7），**无任何实际运行记录** |
| 双签 owner | CODEOWNERS.example 占位，领域 owner / 体系维护人角色未落实 |
| 反馈闭环 | 机制在，但 38 条 case confidence 全是初始值——**没人回报过 fix 结果**；reference hits 如实 0 |
| to-reference 使用 | 仅 dogfood 一次（提炼测试），无真实工程师使用 |

## 三、推广最小动作清单（按依赖排序）

| 优先级 | 动作 | 补的差距 |
|---|---|---|
| P0 | 定 owner + 启用 CODEOWNERS | 运维（决策权落实） |
| P0 | groom 实际跑 2-3 轮（含 reference draft 审核 R1 + 指标回写 R6），产出 metrics 二期 | 数据 + 运维（机制首次通电） |
| P1 | 补一个 training namespace 种子（mindspeed-llm 或 verl，10-20 条） | 内容（否则 training 团队无法使用） |
| P1 | **错误码表按官方分族补齐**（cann-runtime 已有 7 码草稿 → 导入官方错误码参考分族扩展，验证聚类"追加不新建"）+ tool 类（npu-smi/hccn_tool）填充 | 内容（最常用先验知识） |
| P1 | golden replay 半自动化（roadmap M2） | 数据（回归防护缺实证） |
| P2 | 覆盖矩阵报告（groom 输出 O4） | 内容可观测性 |
| P2 | 3 阶段推广路径（种子库 → 小队试运行 → 全面推广） | 组织路径 |

## 四、推广的正确姿态（诚实退化）

向团队交付时表述建议：

> 机制已就绪：这套系统把"理论（四公理）→ 原则（十一）→ 实现（skill + CI + 校验）"的链走通了。内容待积累：当前 38 条 vllm-ascend case + 23 条 A5 平台事实只够证明机制能用、够支撑 vllm-ascend inference 场景的部分诊断，不够支撑全场景日常诊断。第一个团队的诊断会频繁触发"空库提示 / Tier 3 兜底"——这是设计预期，每次兜底后沉淀（`/skill:to-postmortem`、`/skill:to-reference`），知识库随使用变厚。

## 重估条件

以下任一发生时重新执行本评估：

- groom 连续运行 ≥4 周且 metrics 积累 ≥3 期；
- 任一 training namespace 首次填充；
- reference 层 **tool 类型首次填充**，或 error-code 表首次按官方参考分族扩展（验证聚类"追加不新建"在真实导入下成立）；
- reference 观测数据积累 ≥2-3 期（可按实测设 hits/resolve 率参考线）；
- CODEOWNERS 实际启用且双签机制生效；
- 覆盖矩阵报告（O4）首次产出。
