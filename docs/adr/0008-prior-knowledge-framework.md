# ADR-0008: 先验知识框架——reference 类型、组织形态与审核机制

## Status

Adopted（2026-08-27 合入后随使用修订，见下"修订记录"）

## Date

2026-08-27（首次）；2026-08-28（修订 1：组织形态校准）

## 修订记录

| 修订 | 日期 | 内容 |
|---|---|---|
| 1 | 2026-08-28 | 组织形态校准（基于 38 条 case 提炼测试 + PR review）：①去掉 `references/_inbox/` 中间态——草稿以 `status: draft` 直接进正式目录，PR review 即审核闸门（postmortems/inbox 的高频队列逻辑不适用于低频的 reference 沉淀，且 draft 状态已承担"未审内容不进诊断上下文"的隔离）；②引入**组织单元 = 验证单元**第一性原理——错误码等结构化数据集按族成表（`error-code` 类型从单条改为表形态），不再一码一文件平铺 |
| 2 | 2026-08-28 | 演化机制校准（基于知识聚类/追加/检索的 review）：①**聚类规则**——族划分跟随来源（官方错误码参考怎么分章，errors/ 就怎么建文件）、追加不新建（新错误码先查族归属再追加到现有表，仅族文件不存在才新建）、关联不合并（独立词条不动态聚类成新文件，主题聚合由 tags + related_references 承担，聚合是检索层职责非文件层职责）；②**检索渐进**——目录+grep 现状，触发条件（文件数 >50 或 diagnose trace 显示 reference 检索退化）时生成 `references/_index.yaml`（`build_references_index.py`，与 case 层同构）；③明确**不引入图存储**——知识关联是轻量单跳、词法可表达（字段/标签/ref id），图的多跳遍历是 v2 离线分析工具的内存算法，永不成为持久存储形态（原则三 + ADR-0002 同一逻辑） |
| 3 | 2026-08-28 | 修订机制校准（基于"沉淀的 reference 有误如何更新"的 review）：补全 reference 生命周期缺失的一环——**内容修订**。新增 §1.7：发现（观测性 resolve 率低 / groom 信号 / maintainer 复查）→ 降级（pending-review/draft）→ 修订（维护者直接改 YAML + PR，或 `to-reference --update` agent 辅助）→ 验证（CI + review）→ 回 active。**修订 active 内容 = 修改已生效知识 → kb/high-risk 双签**（对齐 case 层 knowledge_modification 逻辑）；修订中 status 保持降级态，diagnose 只读 active 天然隔离修订中的词条 |
| 4 | 2026-08-29 | 源码知识边界校准（基于"开源仓库源码是否应沉淀进 reference"的 review）：新增 §1.8——**源码是证据源，不是独立输入通道**（不新增 source type；源码知识经三条现有通道进入，源码作为证据升级器）；按"版本稳定性 × 事故独立性 × 验证成本"把源码知识拆成四形态（稳定结构事实 / 易腐行为事实 / 事故绑定知识 / 诊断方法论），各自落点不同；稳定结构事实（仓库架构/文件布局/框架自定义 env var/版本兼容矩阵）是唯一值得主动沉淀的形态，定位为**导航辅助**（不参与路由、不解决冷启动——冷启动是 case 问题，issue-ingest 已部分覆盖）；源码提炼的验证故事是"版本 pin + verification 词表"而非 grill；结构事实从真实使用进入（diagnose 源码分析步骤顺手沉淀，演进由数据触发） |

## Deciders

待补（需体系维护人 + 至少一位领域 owner）

## Tags

knowledge-substrate, reference, prior-knowledge, verification, schema, meta-process, organization-form

## Replaces

无正式 ADR 被取代。编号 "ADR-0007" 曾在 2026-08 的设计会话中非正式使用（为 `knowledge/platforms/*.md` 设计的三态机制 verified / unverified / pending），**但从未成文、从未合入**——`docs/adr/` 目录不存在 0007 文件。该讨论的全部有效结论（status 词表、sources 字段、验证与 CI 机制）已被本 ADR 的 reference 框架吸收并扩展。

注意：已合入 main 的 PR #11 在 `CLAUDE.md`（platform facts 段）与 `skills/diagnose/references/platform-dispatch.md`（callout）中留下了 "ADR-0007 work item" 字样，指向这个从未存在的文档——阶段 1b 的清理 PR 将其改指向本 ADR。

---

## Context

### 1. 知识资产的边界问题

仓库当前的知识资产只有两种形态：

| 形态 | 例子 | 性质 |
|---|---|---|
| **case** | 38 条 vllm-ascend | 诊断原料——具体事故的定位闭环 |
| **principles / docs** | `docs/design-principles.md` | 体系元规则——理论推导 + 设计约束 |

但**两种形态都不能覆盖一类知识**：**先验知识**——独立于任何具体事故、可被多次复用的领域事实与方法论。

具体表现：

- **`knowledge/platforms/{a2,a3,a5}.md`**（当前仍在 main，本 ADR 阶段 1b 废弃）：承载"A2 无 HCCL_BUFFSIZE"等平台事实——但内容是 agent 初始生成、零外部源、PR #11 标 `[unverified]`；
- **plog 错误码表 / `npu-smi info` 字段含义 / `HCCL_BUFFSIZE` 是否需重启**：这些是 agent 诊断时需要的辅助查询，但**仓库里没有承载位置**——目前散落在工程师个人经验中；
- **诊断流程（如 AMP 配置排查）**：工程师多次遇到同一类问题，但每次都重新摸索，**没有沉淀为可复用方法论**。

### 2. 已有讨论沉淀

本 ADR 是以下讨论的最终落地：

| 议题 | 共识 |
|---|---|
| reference 是否独立 type | ✓ 与 case 并列，不混淆 |
| reference 在仓库的位置 | ✓ 独立目录 `references/`，与 `knowledge/`、`postmortems/` 并列 |
| reference 与 case 的关系 | ✓ 单向检索关系（case 诊断时查 reference；不形成自动升格） |
| reference 的来源类型 | ✓ 3 种（official-doc / engineer-input / case-derived） |
| reference 的内容类型 | ✓ 5 种（error-code / tool / platform-fact / command-side-effect / methodology） |
| 状态机 | ✓ 4 态（draft / active / pending-review / deprecated） |
| 审核深度 | ✓ 标准双签（普通 reference）+ 深审（methodology + case-derived） |
| 失败降级 | ✓ methodology 类更激进——单次失败直接降级 + 30 天禁用 |
| platform doc 处置 | ✓ 整体废弃，不转化为 reference（agent 初始生成、零外部源、无保留价值） |

### 3. 触发本 ADR 的关键判断

| 判断 | 理由 |
|---|---|
| **reference 必须独立 type** | case 是"事故定位闭环"，reference 是"独立事实 + 通用方法论"——性质不同、检索路径不同、审核机制不同 |
| **必须分 type 而非单一"知识"类型** | error-code / tool / platform-fact / command-side-effect / methodology 的 schema 不同——按 type 强校验 content 字段才能保证词条质量 |
| **必须有 status 而非单一布尔** | 知识有生命周期（待审 → 生效 → 被挑战 → 失效）——4 态机反映这种演化 |
| **来源类型决定初始 confidence + 审核深度** | 官方文档 vs 工程师输入 vs case 归纳，信任基础不同——不能一刀切 |
| **methodology 单独一类 + 深审** | 流程类知识错的影响面比单条事实大——单次失败直接降级 + 多重证据门槛 |

---

## Decision

### 1. reference 的本质定位

reference 是先验知识的**统一载体**，与 case 并列：

- **case**——诊断原料。具体事故的定位闭环（含 symptoms / diagnosis / fix / references 等 case 专属字段）。
- **reference**——诊断浓缩知识。独立事实 + 通用方法论，**独立于任何具体事故**。

两者关系：

- case 是 reference 的**潜在来源**（通过 `to-reference --ingest-cases` 归纳）；
- reference 是 case 诊断时的**辅助查询**（agent 在 phase-two 检索 reference 词条）；
- 单向检索关系，不形成自动升格机制。

### 1.5 组织形态的第一性原理：组织单元 = 验证单元（修订 1 引入）

先验知识的组织粒度**不由文件粒度习惯决定，而由"什么一起被验证、一起被引用、一起过时"决定**。据此分两种形态：

| 形态 | 判据 | 例子 | 组织方式 |
|---|---|---|---|
| **数据集（表）** | 高数量、强族关系、同源同验证同生命周期 | 错误码表（CANN Runtime 507xxx 系列同源同版同验证）、环境变量参考、版本兼容矩阵 | **一个族一个文件**，元信息（sources/status/applies_to）表级共享，族内条目共享验证 |
| **独立词条** | 低数量、高单条价值、各自独立验证与生命周期 | 平台事实（A5 内存规格）、方法论（GLM 排查流程）、工具用法 | 单文件，独立验证 |

**反模式**（本修订纠正）：一码一文件平铺。错误码天然成族（Runtime/HCCL/aicpu/Driver 各成体系），每个码与族共享来源、版本、验证与排查语境——切成单文件既降低信息密度（元信息逐条重复）、又割裂族上下文、还使检索退化为扫几百个文件（违反原则九资源显式预算）。

**组织单元与验证单元的映射**：官方错误码参考整表同源同验证 → 表级 sources/status/verification；case 提炼的条目逐条验证 → 条目可带可选 `source_cases` 标明证据。验证粒度随来源落在正确层级，不做一刀切。

### 1.6 聚类规则与关联机制（修订 2 引入）

知识库动态生长时，聚类必须由规则约束而非 agent 自觉（原则二）：

**聚类三规则**：

| 规则 | 内容 | 机制 |
|---|---|---|
| **族划分跟随来源** | 族的划分不由我们发明，**跟随官方来源的组织方式**——CANN 错误码参考怎么分章（Runtime/HCCL/aicpu/Driver），`errors/` 就怎么建文件 | 导入官方文档时按章节建表；to-reference 分族时参考来源章节 |
| **追加不新建** | 提炼到某族的新错误码 → **先查 `errors/` 现有文件判定组件归属 → 追加到现有表的 `errors` 列表**（标新 `source_cases`）；**仅该族文件不存在才新建** | to-reference 显式步骤（见 §9）；PR review 抽查归属（归属判定是语义判断，CI 不硬判） |
| **关联不合并** | 独立词条**不动态聚类成新文件**——独立性（各自验证/生命周期）是价值，强行合并破坏它。主题聚合由 `tags`（主题标签）+ `related_references`（互链）承担；聚合是**检索层的职责，不是文件层的职责** | `tags` / `related_references` 可选字段；diagnose 检索按标签聚合 |

**不引入图存储（明确否决）**：知识关联（错误码→族、case→reference、同主题互链）都是**轻量单跳、词法可表达**的（字段/标签/ref id），YAML + 词法检索完全承载。图的价值在多跳遍历（A→B→C 传导），而诊断是线性确认 + 辅助定位，不需要多跳。图的形态（语义存储）失去 git 审计链——与 ADR-0002 否决向量检索的同一逻辑。**v2 的 trace 结构挖掘若需图算法，作为离线分析工具的内存数据，永不成为持久存储形态。**

### 1.7 reference 修订机制（修订 3 引入）

reference 内容有误/过时/不完整时的更新路径——补全生命周期缺失的一环（新增有 to-reference、状态降级有 groom 信号，内容修订此前无机制）：

**完整闭环**：发现 → 降级 → 修订 → 验证 → 回 active

| 环 | 机制 |
|---|---|
| **发现** | 引用后 resolve 率低（trace_metrics 观测）、engineer 反馈失败、sources 失效、last_verified 超 90 天、maintainer 复查——观测与信号表驱动，不靠人翻 |
| **降级** | active → `pending-review`（普通）/ `draft` + 禁用 30 天（methodology）——groom 信号表已有 |
| **修订** | 两条路径：**A. 维护者直接改 YAML + PR**（小修：错别字/补一句/改一个错误码含义）——git diff 可追溯、review 即审核；**B. `to-reference --update <ref-id>`**（大修：methodology 流程重写/错误码表按新官方文档整体更新）——agent 读现有 + 新材料产修订 diff 建议，人确认 |
| **验证** | 修订走 PR + `verify_references.py` CI + review |
| **回 active** | review 通过后回 active（methodology 需重新实测 `verified_by_testing`） |

**风险分级（对齐 case 层 knowledge_modification）**：新增 draft 从未生效 → 单审足够；**修订 active 内容 = 修改已生效的诊断事实 → `kb/high-risk` 双签**。修订期间 status 保持降级态——diagnose 只读 active 天然隔离修订中的词条（status 机制的额外价值）。

**误伤防护**：引用后 resolve 率低可能是 ref 错（该修），也可能是 case 匹配错（不该修 ref）——**先 trace 归因**（原则八：引用后验证环节失败 vs 引用本身误导），归因清楚再动，观测性不能变成"冤案制造机"。

### 1.8 源码知识边界：证据源，不是独立输入通道（修订 4 引入）

客户常用昇腾开源仓库（vllm-ascend / mindspeed-llm / verl / torch-npu 等）的源码是诊断的重要材料。**源码知识不构成第四条输入通道**（trust ladder 保持三源：official-doc / engineer-input / case-derived），而是作为**证据升级器**经三条现有通道进入：

| 通道 | 源码扮演的角色 |
|---|---|
| case（to-postmortem） | `source_ref: {repo, ref, file, line}`——事故绑定知识的代码证据链（源码不落库，只记指针，CLAUDE.md 同源） |
| case-derived reference（--ingest-cases） | 归纳时以 `source_cases` + 代码指针佐证共性（≥3 条 case 才能 active） |
| engineer-input / official-doc reference | 结构事实草稿的 evidence 字段可引 `repo + ref + file + line`（grill 确认意图 + 版本 pin） |

**源码知识按"版本稳定性 × 事故独立性 × 验证成本"拆成四形态，落点不同**：

| 形态 | 稳定性 | 事故独立性 | 落点 | 条件 |
|---|---|---|---|---|
| **稳定结构事实**（仓库架构/文件布局/框架自定义 env var/版本兼容矩阵） | 高 | 高 | reference（software-fact / env-var-table；版本矩阵复用 table 形态） | 版本 pin 到 major 粒度；`verification` 如实标注 |
| **易腐行为事实**（"vllm-ascend 0.21.x 的 async engine 会先编译"） | 低 | 高 | 谨慎进 reference | 必须 `applies_to.versions` 精确标注，否则腐烂；或等 case 共现走 case-derived |
| **事故绑定知识**（"这个报错是这个 bug，升到 X 修复"） | 低 | 低 | **case**（带 `source_ref`），不进 reference 独立词条 | 现有设计已覆盖 |
| **诊断方法论**（"vllm-ascend 量化报错按什么顺序查哪些文件"） | 中 | 高 | reference（methodology） | 只能 case-derived 且 ≥3 条 case 引用（§8.4 深审） |

**三个性质判定**：

1. **稳定结构事实是唯一值得主动沉淀的形态，定位是"导航辅助"不是"诊断能力"**——reference 是 2.5 层、不参与候选路由（见 diagnose SKILL 阶段 2.5），主动源码 reference 只压缩"已决定走源码分析的诊断"的定位时间，**不解决空 namespace 冷启动**（冷启动是 case 问题，issue-ingest 从上游 issue 导入 case 已部分覆盖）。反模式：全量提炼源码行为 → 一堆无症状接线的词条，诊断时永不触发，违反信噪比守恒（原则三）。
2. **源码提炼的验证故事是"版本 pin + verification 词表"，不是 grill**——`repo + ref + file + line` 是完整的自验证证据指针（比 engineer-input 强），但 agent 读代码可能读错、可能把单版本行为推断成跨版本成立；所以验证靠 pin 到 commit/tag + 现有 `auto-extracted` / `cross-checked-source` 声明（ADR-0008 §4.2），不新增 grill 档位。
3. **结构事实从真实使用进入，演进由数据触发（原则十一）**——diagnose 源码分析步骤（SKILL 5.7）在定位到稳定结构事实时**顺手**走 to-reference，而不是预先纯挖掘：结构事实在 ≥3 次诊断中被反复 grep 到，才是它进 reference 的数据闸门。反模式：为"提前备好"对三个仓库做一轮全量源码梳理——产出大量永不触发的词条，groom 的 `last_verified` 退化信号变成每周报警。

**填充优先级**（对齐 §Consequences 2 的价值密度排序）：版本兼容矩阵按**传导链分层**（§1.8 的 compat-matrix 形态）——base（昇腾底座 CANN↔HDK/驱动，来源昇腾官方兼容页）/ adapter（torch-npu↔CANN+torch，来源 Ascend/pytorch 官方 COMPATIBILITY.en.md，官方本就维护此表）/ framework（vllm-ascend、verl 等上层框架↔torch-npu+torch，来源各仓库 pyproject.toml）；每层独立验证、独立腐化节奏、层间 related_references 互链，**上层不重复声明底层内容**（vllm-ascend 的 CANN 兼容由 adapter 层传导）。试点从 adapter（torch-npu-cann）+ framework（vllm-ascend-torch-npu）两层开始，均为 draft。

### 2. reference 仓库结构（修订 1 更新）

```
references/
├── _types.yaml                       # type 注册表（渐进登记）
├── _index.yaml                       # 检索索引（按 type + 字段，可选——见 Open Questions）
├── errors/                           # type: error-code（表形态，按组件分族）
│   ├── cann-runtime.yaml             #   CANN Runtime 错误码（507xxx 系列）
│   ├── hccl.yaml                     #   HCCL 错误码
│   ├── aicpu.yaml                    #   aicpu errorCode
│   └── driver.yaml                   #   驱动错误码
├── tools/                            # type: tool（独立词条）
├── platform-facts/                   # type: platform-fact（独立词条）
├── command-side-effects/             # type: command-side-effect（独立词条）
├── methodologies/                    # type: methodology（独立词条）
└── _archive/                         # deprecated 保留
```

物理按 type 分目录——agent 按 type 过滤时直接进入对应子目录。type 之间无 namespace 维度（reference 的检索是**按 type + 内容字段**的组合，不是 framework × category）。

**无 `_inbox/` 目录（修订 1 移除）**：草稿以 `status: draft` **直接进正式 type 目录**，PR review 即审核闸门（原则五：建议与决定分离由 PR review 承担，不需要持久中间目录）。`status: draft` 已承担"未审内容不进诊断上下文"的隔离（diagnose 阶段 2.5 只读 active）——目录隔离是冗余。postmortems/inbox 保留（高频事故沉淀需要集中批审，其队列逻辑在本层不成立）。

### 3. reference type 清单（修订 1 更新）

5 种 type，各有不同的 content 字段集合。**error-code 是数据集形态（表），其余四种是独立词条**（见 §1.5 两分法）：

| type | 形态 | 含义 | 典型例子 |
|---|---|---|---|
| `error-code` | **表**（errors 列表） | 错误码 / 异常代码的含义解读，**按组件分族成表** | `cann-runtime.yaml` 承载 507xxx 系列（507903/507018/507057...） |
| `tool` | 词条 | 工具 / 命令的使用方法与输出解读 | `npu-smi info` 字段含义 |
| `platform-fact` | 词条 | 平台硬事实（可独立验证的客观事实） | "A5 HBM 64GB" |
| `command-side-effect` | 词条 | 命令 / 环境变量的副作用与回滚方式 | "导出 HCCL_BUFFSIZE 需重启" |
| `methodology` | 词条 | 流程 / 方法论（多步骤诊断或调优） | "GLM 量化启动失败排查" |

**type 注册表**（`_types.yaml`）：

```yaml
types:
  error-code:
    kind: table                      # 数据集形态：errors 列表，族内共享表级元信息
    schema_required: [errors]
    schema_optional: [title, summary]
  tool:
    kind: fact
    schema_required: [tool_name, invocation]
    schema_optional: [output_meaning, pitfalls]
  platform-fact:
    kind: fact
    schema_required: [claim, evidence]
    schema_optional: [applies_to_platforms]
  command-side-effect:
    kind: fact
    schema_required: [command, side_effects]
    schema_optional: [rollback, version_dependent]
  methodology:
    kind: flow
    schema_required: [flow]
    schema_optional: [verified_by_testing, test_scenarios]
```

- `kind: fact` 平铺字段、`kind: flow` 嵌套流程、`kind: table` 列表数据集——三种元分类，避免加新 type 时重复决定；
- type 字段是 open vocabulary——后续可扩展（如环境变量表 `env-var-table`、版本矩阵 `compat-matrix` 复用 table 形态，`retired` 状态迁移到新 type）。

### 4. reference schema（完整版）

#### 4.1 核心元信息（所有 reference 必填）

```yaml
id: <string>                          # 词条唯一 ID（如 "plog-error-507903"）
type: <enum>                          # 5 个注册 type 之一
title: <string>                       # 简短标题
summary: <string>                     # 一两句话概括（agent 检索时优先看）

# 来源（必填，至少 1 条）
sources:
  - type: <source-type>               # 见第 5 节
    # ... source-specific 字段

# 适用性（可选——普适 reference 可不填）
applies_to:
  platforms: [<platform>]             # A2-910B | A3-910C | A5-950 | cross
  frameworks: [<framework>]           # vllm-ascend | mindspeed-llm | sglang
  versions:
    cann: <string>
    torch_npu: <string>
    hdk: <string>
  categories: [<category>]            # interrupt | precision | performance

# 状态（自动维护）
status: <enum>                        # draft | active | pending-review | deprecated
last_verified: <date>                 # 人审日期
hits: <int>                           # 被引用次数（trace.reference_lookup 计数）
last_hit: <date>                      # 最后引用时间

# 反向关系不存储：哪些 case 引用了本词条，由 groom / 校验脚本从
# case 侧 ref_knowledge 字段计算派生视图（见 §7）——一条关系只存一处
```

#### 4.2 source type 三选一

```yaml
# 来源 1：官方文档爬取
sources:
  - type: official-doc
    url: <string>
    version: <string>                 # CANN 9.0 / torch-npu 2.10.x 等
    fetched_at: <date>

# 来源 2：工程师输入
sources:
  - type: engineer-input
    engineer: <id 或 hash>            # 工程师标识（脱敏后）
    input_session: <session-id>       # to-reference 的 session id（可回溯 grill 对话）
    confirmed_at: <date>

# 来源 3：从 case 集合归纳
sources:
  - type: case-derived
    cases: [<case-id>, ...]           # 至少 1 条（深审需 ≥3 条才能标 active）
    extracted_at: <date>
    extraction_method: to-reference --ingest-cases
```

**每条 source 可带可选字段 `verification`**（判定审核深度，不填则按 source type 默认）：

| verification | 含义 | 默认适用 |
|---|---|---|
| `auto-extracted` | 模型从源材料抽取，**未经 agent 对源逐字核验**——reviewer 必须 spot-check 语义 | URL 爬取等一次性抓取 |
| `cross-checked-source` | agent 已直接对源原文（如 PDF 文本提取）逐字核验——reviewer 抽查即可 | 本地文档在手、agent 直接读原文的场景 |

skill 的 official-doc 路径必须显式声明二者之一：拿不准标 `auto-extracted`（诚实退化——宁低估不高估）。`verify_references.py` 对已填的 verification 做合法性校验，未填不报错。

**`official-doc.url` 语义：来源定位符，不一定是字面 URL**。公开 URL 优先；无公开 URL 时（如内部白皮书 PDF）用**可移植的文档引用**（标题 + 出品方 + 版本，版本放 `version` 字段）。**禁止机器特定路径**（`~/`、绝对路径、盘符）——仓库读者没有该路径，且违反 ADR-0003 知识随仓库迁移的可移植性；`verify_references.py` 对机器路径报错。

#### 4.3 type-specific content 字段

```yaml
# type: error-code（表形态，修订 1：按组件分族成表，一码不再一文件）
content:
  errors:
    - code: <string>                    # 错误码（表内唯一）
      meaning: <string>                 # 含义解释
      related_signatures: [<string>]    # 相关日志签名（grep 用）
      applies_to_versions:              # 该码在不同版本含义不同（可选）
        - version: <string>
          meaning: <string>
      source_cases: [<case-id>]         # case 提炼的证据（可选——逐条验证粒度，见 §1.5）

# type: tool
content:
  tool_name: <string>                 # 工具名称
  invocation: <string>                # 调用命令/方式
  output_meaning: <string>            # 输出字段解读
  pitfalls: [<string>]                # 常见误区/坑

# type: platform-fact
content:
  claim: <string>                     # 事实陈述
  evidence: <string>                  # 证据/出处说明
  applies_to_platforms: [<platform>] # 适用平台

# type: command-side-effect
content:
  command: <string>                   # 命令或环境变量
  side_effects: [<string>]            # 副作用列表
  rollback: <string>                  # 回滚方式
  version_dependent: <boolean>        # 是否依赖特定版本

# type: methodology（流程类）
content:
  flow:
    - step: <int>                     # 步骤序号
      name: <string>                  # 步骤名
      action: <string>                # 动作描述
      check: <string>                 # 验证方法
      when_to_use: <string>           # 适用场景
      references:                     # 引用其他 reference（可选）
        - <ref-id>
  verified_by_testing: <boolean>      # maintainer 显式声明是否实测
  test_scenarios: [<string>]          # 实测场景描述
```

#### 4.4 可选元数据

```yaml
aliases: [<string>]                   # 别名（检索增强）
related_references: [<ref-id>]        # 关联 reference（不强制）
tags: [<string>]                      # 标签（检索/分类）
supersedes: [<ref-id>]                # 取代的旧版本词条
superseded_by: <ref-id>               # 取代本条的新版本词条
```

### 5. 来源与信任机制

3 种 source type，对应不同的信任基础与审核深度：

| source type | 信任基础 | 初始 confidence | 审核深度 |
|---|---|---|---|
| `official-doc` | 文档权威性 + 模型抽取需校验 | 0.6 | 标准双签 |
| `engineer-input` | 经验可信度因人而异 | 0.3 | 标准双签 |
| `case-derived` | 多 case 模式支持 | 0.3-0.6 | 深审（双签 + 实测声明 + ≥3 条 case 印证才能 active） |

**置信度与命中次数**：

- `hits` 是**被引用次数**（trace.reference_lookup 计数），不是"被验证次数"；
- `outcome_after_use` 是**引用后诊断 outcome 分布**——通过 trace 关联 `resolution: resolved/escalated/unknown`；
- `confidence.score` 是多维聚合（来源质量 + 引用频率 + 引用后成功率），由 groom 维护；
- **不照搬 case 的 Beta 后验**——reference 引用没有直接 ground truth，"被引用"和"被验证"是两件事。

### 6. 状态机

4 个 status，反映 reference 的生命周期：

| status | 含义 | 触发 |
|---|---|---|
| `draft` | 待审或证据不足 | 新建 / 被 case 引用数 < 3（派生计算；case-derived + methodology） |
| `active` | 已审核生效 | 标准审核通过 / 深审 + 证据齐备 |
| `pending-review` | 被挑战待重审 | 工程师反馈"按这条查的不对" / `outcome_after_use` 失败率上升 |
| `deprecated` | 失效但保留 | version obsolete / 长期未用 |

**methodology 类的失败降级更激进**：

| 失败情形 | 普通 reference | methodology 类 |
|---|---|---|
| 单次工程师反馈"按这条查的不对" | `active` → `pending-review` | **直接 `active` → `draft` + 触发强制重审** |
| `outcome_after_use` 失败率持续上升 | `pending-review` 等人工审 | **直接 `draft` + 自动禁用 30 天** |
| 被 case 引用数下降（派生视图；曾 5 条剩 1 条） | 不强制降级 | **`active` → `draft`**（失去多 case 印证） |

### 7. 与 case 的关系

**case YAML 增加可选字段**：

```yaml
cases:
  - id: VLLM-ASC-XXXX
    title: "..."
    
    # 已有：事故溯源（URL）
    references:
      - url: https://github.com/vllm-project/vllm-ascend/issues/1234
    
    # 新增（可选）：结构化引用 reference 词条
    ref_knowledge:
      - ref: plog-error-507903          # reference 词条 ID
        role: signature-source          # case 的 quickly_check 引用此 reference
      - ref: amp-config-triage          # 另一个 reference
        role: fix-methodology           # case 的 fix 步骤基于此 reference
```

`ref_knowledge` 规则：
- **可选**，不强校验非空；
- `ref` 必须指向真实存在的 reference 词条；
- `role` 是 enum：`signature-source` | `fix-methodology` | `root-cause-context`。

**反向视图是派生的，不是存储的**——一条关系只存一处（case 侧 `ref_knowledge`）。groom 与 `verify_references.py` 扫描全库 case 的 `ref_knowledge` 字段，运行时计算"每个 reference 被哪些 case、以什么 role 引用"的派生视图。这消除双向维护的同步 bug，与 ADR-0004 的既有决策同构（学习环动态字段留在本体，检索视图只放必要字段）。

**reference 不存储对 case 的引用**——case 是 reference 的潜在来源，但不形成自动升格机制。

### 8. CI 校验

新增 `scripts/verify_references.py`：

#### 8.1 强校验（缺失则 CI 红）

| 字段 | 校验 |
|---|---|
| `id` | 必须存在，在 `_index.yaml` 中唯一 |
| `type` | 必须是 `_types.yaml` 注册表中的合法 type |
| `title`, `summary` | 必须存在 |
| `sources` | **至少 1 条** |
| `sources[].type` | 必须是 3 种合法来源类型之一 |
| `last_verified` | 必须存在 |
| `status` | 必须是 4 个合法 status 之一 |

#### 8.2 按 type 的强校验

| type | 必填字段 |
|---|---|
| `error-code` | `content.errors`（非空列表，表内 `code` 唯一） |
| `tool` | `content.tool_name`, `content.invocation` |
| `platform-fact` | `content.claim`, `content.evidence` |
| `command-side-effect` | `content.command`, `content.side_effects` |
| `methodology` | `content.flow[]`（≥1 个 step），`applies_to.categories` |

#### 8.3 按 source type 的强校验

| sources[].type | 必填字段 |
|---|---|
| `official-doc` | `url`, `version`, `fetched_at` |
| `engineer-input` | `engineer`, `input_session`, `confirmed_at` |
| `case-derived` | `cases`（≥1 条），`extracted_at` |

#### 8.4 深审校验（methodology + case-derived）

- source type 为 `case-derived` 且 type 为 `methodology`：校验脚本从全库 case 的 `ref_knowledge` 派生计算本词条被引用数，**< 3 时不允许 `status: active`**（引用数不存储于 reference 本体）；
- `verified_by_testing` 字段缺失时降 confidence（不强制 active 阻断）。

集成进 `.github/workflows/kb-checks.yml`——与 `build_index.py --check` 同一 CI 流程。

### 9. to-reference skill（后续 PR）

四种输入模式：

```
/skill:to-reference "<text>"                       # 内联输入
/skill:to-reference --file <path>                  # 文件
/skill:to-reference --ingest <url>                 # 官方文档爬取
/skill:to-reference --ingest-cases "[case-ids]"    # 从 case 集合归纳
```

四阶段流程（修订 1：草稿直接进正式目录，无 _inbox 中间态）：
1. 输入（用户粘贴 / 文件 / URL / case 集合）；
2. **grill 阶段**（如果是工程师输入或 case 归纳）—— agent 反复追问"你指的是不是这个意思"，确保产物符合用户意图；
3. **聚类归属判定（修订 2：追加不新建）**——数据集类（error-code）先查 `references/errors/` 现有文件，按组件归属判定：归属已有族 → **追加到该表 `errors` 列表**（标新 `source_cases`）；仅无对应族文件才新建文件。独立词条类：查 `tags`/`related_references` 是否可关联现有词条，不合并；
4. 草稿以 `status: draft` 落入正式 type 目录（`references/<type-dir>/`）；
5. maintainer 通过 **PR review 审核** → accept（合并时或合并后翻 active）/ adjust / reject / defer。

**关键设计原则**：
- **PR review 即审核闸门**（修订 1：去 _inbox 后，审核由 PR review 承担——草稿以 draft 进正式目录，draft 状态保证不进诊断上下文，review 通过翻 active 即生效）；
- **grill 阶段去噪**——避免一切材料堆到 maintainer ；
- **来源类型决定审核深度**——maintainer 审时按 source type 决定 spot-check 深度（整表审核 vs 逐条审核：官方错误码参考整表同源 → 表级审；case 提炼条目带 source_cases → 逐条抽审）；
- **聚类归属抽查**（修订 2）——reviewer 检查新错误码是否进对族（归属判定是语义判断，CI 不硬判，PR review 承担）。

to-reference skill 设计与 to-postmortem 对称——to-postmortem 产出 case，to-reference 产出 reference。

---

## Consequences

### 1. 短期（合并本 ADR 后立即生效）

- 删除 `knowledge/platforms/a2-910b.md`、`a3-910c.md`、`a5-950.md`（PR #11 引入的 `[unverified]` 标注随之移除，PR #11 body 需更新说明）；
- 建立 `references/` 目录结构（5 个 type 子目录 + `_archive/` + `.gitkeep` 占位；修订 1：无 `_inbox/`）；
- 创建 `references/_types.yaml` 注册表（5 个 type）；
- 创建 `scripts/verify_references.py` 校验脚本；
- 集成进 `.github/workflows/kb-checks.yml`。

### 2. 中期（reference 库逐步填充）

- to-reference skill 投入运行——工程师输入、官方文档爬取、case 归纳三种路径；
- 填充优先级（按价值密度）：
  1. **plog 错误码表**——高频查询，影响所有 interrupt 类 case；
  2. **CANN / 框架版本兼容矩阵**——所有 case 的 compat 字段依赖；
  3. **`npu-smi info` / `hccn_tool` 等工具解读**——工程师常用辅助；
  4. **诊断流程类 methodology**——从 case 归纳（≥3 条引用门槛）。
- 每个填充批次由 maintainer 决策触发，**不是自动化**。

### 3. 长期（reference 库成为体系核心资产）

- reference 与 case 形成**相互印证关系**：
  - case 命中 → 可能查 reference fact（解释签名、验证假设、补充 fix 上下文）；
  - reference 失效 → 触发对应 case 的 re-verification；
- 学习环延伸到 reference 层：
  - 快环：reference 命中次数 + 引用后 outcome 自动统计；
  - 慢环：trace 归因 → 改 reference 词条（增 / 改 / 降级）；
  - 最慢环：methodology 失效 → 触发 case 集合再扫描。

### 4. 与 "ADR-0007" 讨论的关系

- "ADR-0007" 是设计会话中的非正式编号，**从未成文为文件、从未合入**——不存在需要标记 Superseded 的文档；
- 该讨论的核心机制（status / sources / 验证字段、CI 校验设计）**被本 ADR 的 reference 框架继承并扩展**；
- 其遗留痕迹（PR #11 在 main 上留下的两处 "ADR-0007 work item" 字样）由阶段 1b 清理。

### 5. 与其他 ADR 的关系

| ADR | 关系 |
|---|---|
| ADR-0002（不引入向量 RAG） | reference 检索走词法（grep + 字段过滤），不引入向量——本 ADR 一致 |
| ADR-0003（平台可移植性） | reference 词条与 case 同样在仓库内，迁移时随仓库走 |
| ADR-0004（容量治理） | reference 不受 `(framework × category)` 30 条/格子 约束——reference 的检索维度不同 |
| ADR-0005（知识消费 split） | reference 目录对 sparse-checkout 用户透明——正式目录随仓库 |
| ADR-0006（知识 ingest dedup） | to-reference skill 与 to-postmortem 共享 grill 阶段的去重逻辑（去重原则同源） |

### 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| reference 词条质量参差不齐 | 强校验 + 双签 + 必有出处 |
| methodology 类失效影响面大 | 单次失败直接降级 + 30 天禁用 + 多重证据门槛 |
| 来源类型审核深度不均 | maintainer 培训 + spot-check 规则明确 |
| reference 与 case 内容重复 | ref_knowledge 字段显式标注；reference 不引用 case（避免双向维护） |
| reference 库膨胀失控 | 无 30 条硬上限，但 CI 校验 schema 严格性——质量门槛替代数量约束 |

---

## Alternatives Considered

### A. 维持 case 单类型（不分 reference）

**否决理由**：case 是"事故定位闭环"，承载不了"独立事实 + 通用方法论"。把 reference 强行塞进 case schema，会让 case 失去事故档案的属性。

### B. reference 是 case 的子类（`kind: case | reference`）

**否决理由**：case 与 reference 的 schema 不兼容（reference 没有 `quickly_check` / `diagnosis` / `fix`，case 不需要 `applies_to`）。混在一个 schema 里必然两败俱伤。

### C. reference 是 SKILL 的扩展（不进 KB）

**否决理由**：SKILL 是 prompt 层，reference 是数据层。SKILL 引用 reference 词条，但 reference 不应硬编码进 SKILL——这样失去独立性。

### D. reference 用 markdown 形式（与原 platform doc 类似）

**否决理由**：markdown 自由文本难以强校验 content 字段。YAML 词条 + schema 校验能保证每个 type 的必有字段——这是 reference 框架的核心质量保证。

### E. 自动从 case 升格 reference

**否决理由**：你之前的判断"信噪比高是因为人审"——自动升格会绕过人审。reference 的入口门槛必须由人守。

### F. 引入图存储（知识图谱）承载关联（修订 2 否决）

**否决理由**：知识关联（错误码→族、case→reference、同主题互链）都是轻量单跳、词法可表达的（字段/标签/ref id），YAML + 词法检索完全承载，不需要图的多跳遍历。图 = 语义形态存储，失去 git 审计链（不可 diff/回滚），与 ADR-0002 否决向量检索的同一逻辑。v2 trace 结构挖掘若需图算法，作为离线分析工具的内存数据，不成为持久形态（见 §1.6）。

---

## Open Questions

### Q1. `_index.yaml` 是否需要？（修订 2：渐进式，已定义触发条件与路径）

**渐进式设计**（原则十一数据触发演进 + 奥卡姆剃刀——不为不存在的规模购置基础设施）：

| 阶段 | 条件 | 检索方式 |
|---|---|---|
| 现在 | 文件数 <50 | 目录 + grep：错误码按族表内 grep code 一次命中；platform-fact 按平台匹配少数文件。**不需要 index** |
| 触发后 | 文件数 >50，**或** diagnose trace 显示 reference 检索耗时上升 / 漏检增多 | 生成 `references/_index.yaml`（新增 `build_references_index.py`，与 `build_index.py` 同构）：每文件一条 `id/type/title/summary/applies_to + file` 定位——阶段 2.5 平台匹配从"扫目录读 summary"变"读一个索引文件"（与 case 层同构，原则二：阶段一固定读索引） |

**index 结构**（触发后）：按 type 分节 + 平台索引 + 主题标签索引——阶段 2.5 按"平台 + 标签"一次过滤。触发条件的判定由 groom 每次运行检查（文件数 / trace 指标），达到即提建议，**不自动生成**（建议与决定分离）。

### Q2. methodology 深审的"3 条 case 印证"是否要按 type 细分？

比如：
- 诊断流程（"如何排查 X"）需要 ≥3 条 case 引用？
- 调优手段（"如何优化 Y"）可能不同——调优 case 不一定频繁升格。

**当前倾向**：统一 `≥3 条`，因为 case-derived 来源的统一标准有助于避免任意性。这是初始参数，groom metrics 实测后可调整。

### Q3. reference 与 case 的语义边界——"流程类"是不是一律归 reference？

`methodology` type 承载"多步骤诊断 / 调优流程"。但 case 也有 `diagnosis.steps`（多步骤）。

**当前边界**：
- methodology（reference）：**独立于事故**的通用流程——"AMP 配置错误排查步骤"无论哪次事故都适用；
- case 的 `diagnosis.steps`：**该次事故专属**——具体的诊断路径。

**潜在混淆**：methodology 的 `content.flow[]` 与 case 的 `diagnosis.steps[]` 字段形态相似。这是有意为之——methodology 是 case 诊断流程的"模板"，case 实例化模板时引用 methodology 的 step ID。

### Q4. reference 是否需要"版本快照"（`supersedes` 链）？

错误码含义可能随 CANN 版本变化——CANN 8.x 某错误码含义 A，CANN 9.x 含义 B。

**当前方案**：同一 reference 词条内 `content.applies_to_versions[]` 字段记录多个版本的含义；不强制拆词条。`supersedes` / `superseded_by` 字段是可选元数据，按需使用。

**潜在问题**：版本组合爆炸时（如 plog 507903 在 CANN 8.0 / 8.5 / 9.0 / 9.1 各有含义），单词条会膨胀。

**当前倾向**：单条 reference 容纳多版本含义，靠 `applies_to_versions` 字段结构化；不拆词条。如果实测发现单条膨胀失控，再回头拆。

---

## Implementation Plan

### 阶段 1a：本 ADR 成文合入（docs-only PR）

PR 走 methodology 模板——principle 追溯到原则一（用结构承载规则）、原则三（语义判断交给 agent）、原则十（诚实退化）。

### 阶段 1b：platform doc 废弃与引用清理（独立 PR）

删除不是删 3 个文件，是删一个概念——已知引用点如下（该 PR 必须 grep `platforms/` 全量核对，不可只依赖本清单）：

1. 删除 `knowledge/platforms/{a2,a3,a5}.md` 三份文档；
2. `CLAUDE.md`：Platform dispatch 节（"Platform background knowledge in `knowledge/platforms/*.md`"）、platform facts 段（含 PR #11 的 `[unverified]` 标注）、结构性状态中 platform doc 一条；
3. `skills/diagnose/SKILL.md`：platform 背景加载相关表述；
4. `skills/diagnose/references/platform-dispatch.md`：加载机制与速记表在删除后大半失效——重写（仅保留 case `platforms` 字段的分支分发机制本身）或整体删除，由该 PR 决定；
5. `README.md` / `README.en.md`：目录树 `platforms/{a2,a3,a5}.md` 行；
6. `examples/sample-case.yaml`：注释"平台差异在 platforms/*.md"；
7. main 上两处 "ADR-0007 work item" 字样（`CLAUDE.md`、`platform-dispatch.md`）改指向本 ADR。

索引不受影响：`build_index.py` 只扫 `*.yaml`，platform doc 是 markdown，从未入索引——CI 无需重建。该 PR 属 structure 模板的"平台目录调整"条款：打 `kb/high-risk` 标签 + 迁移完整性检查单 + 双签。

### 阶段 2：reference 目录骨架（独立 PR）

1. 建立 `references/` 目录结构（5 个 type 子目录 + `_archive/`，每个含 `.gitkeep`；修订 1 后无 `_inbox/`）；
2. 创建 `references/_types.yaml` 注册表（5 个 type，error-code 为表形态）；
3. 创建 `scripts/verify_references.py` 校验脚本；
4. 集成进 `.github/workflows/kb-checks.yml`。

### 阶段 3：to-reference skill（独立 PR）

1. 设计 `skills/to-reference/SKILL.md`（与 to-postmortem 对称）；
2. 设计 grill 阶段 prompt；
3. 设计四种输入模式的具体处理。

### 阶段 4：case schema 扩展（独立 PR）

1. case YAML 增加可选 `ref_knowledge` 字段；
2. CI 校验 `ref` 存在性 + `role` 合法性；
3. 38 条已有 case 不强制迁移（按需添加）。

### 阶段 5：reference 填充（独立 PR，按批次）

- 优先级参考 §Consequences 2；
- 每个填充批次由 maintainer 决策触发。

---

## Decision drivers

- `design-theory.md` 原则一（用结构承载规则，不依赖执行自觉）：reference schema + 强校验；
- `design-theory.md` 原则三（语义判断交给 agent，知识底座保持词法）：reference 检索走词法 + 字段过滤；
- `design-theory.md` 原则十（诚实退化）：methodology 失败更激进降级；
- ADR-0002（不引入向量 RAG）：reference 不引入嵌入空间；
- ADR-0003（平台可移植性）：reference 词条随仓库迁移；
- ADR-0004（容量治理）：reference 不受 30 条/格子 约束（检索维度不同）；
- ADR-0005（知识消费 split）：reference 与 case 同样在仓库内，sparse-checkout 一致；
- ADR-0006（知识 ingest dedup）：to-reference 与 to-postmortem 共享去重原则。
