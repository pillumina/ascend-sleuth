# ADR-0008: 先验知识框架——reference 类型与审核机制

## Status

Proposed

## Date

2026-08-27

## Deciders

待补（需体系维护人 + 至少一位领域 owner）

## Tags

knowledge-substrate, reference, prior-knowledge, verification, schema, meta-process

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

### 2. reference 仓库结构

```
references/
├── _types.yaml                       # type 注册表（渐进登记）
├── _index.yaml                       # 检索索引（按 type + 字段，可选——见 Open Questions）
├── _inbox/                           # to-reference 产出待审
├── errors/                           # type: error-code
├── tools/                            # type: tool
├── platform-facts/                   # type: platform-fact
├── command-side-effects/             # type: command-side-effect
├── methodologies/                    # type: methodology
└── _archive/                         # deprecated 保留
```

物理按 type 分目录——agent 按 type 过滤时直接进入对应子目录。type 之间无 namespace 维度（reference 的检索是**按 type + 内容字段**的组合，不是 framework × category）。

### 3. reference type 清单

5 种 type，各有不同的 content 字段集合：

| type | 含义 | 典型例子 |
|---|---|---|
| `error-code` | 错误码 / 异常代码的含义解读 | plog 507903 = capture event failed |
| `tool` | 工具 / 命令的使用方法与输出解读 | `npu-smi info` 字段含义、`cat /proc/driver/npu/version` 期望值 |
| `platform-fact` | 平台硬事实（可独立验证的客观事实） | "A2 不支持 FP8"、"A5 HBM 64GB" |
| `command-side-effect` | 命令 / 环境变量的副作用与回滚方式 | "导出 HCCL_BUFFSIZE 需重启训练进程" |
| `methodology` | 流程 / 方法论（多步骤诊断或调优） | "AMP 配置错误排查步骤" |

**type 注册表**（`_types.yaml`）：

```yaml
types:
  error-code:
    kind: fact
    schema_required: [code, meaning]
    schema_optional: [related_signatures, applies_to_versions]
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

- `kind: fact` 是平铺字段；`kind: flow` 是嵌套结构（`content.flow[].step/action/check`）；
- `kind` 是元分类，避免加新 type 时重复决定；
- type 字段是 open vocabulary——后续可扩展（`retired` 状态迁移到新 type）。

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
# type: error-code
content:
  code: <string>                      # 错误码本身
  meaning: <string>                   # 含义解释
  related_signatures: [<string>]      # 相关日志签名（grep 用）
  applies_to_versions:                # 错误码可能在不同版本下含义不同
    - version: <string>
      meaning: <string>

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
| `error-code` | `content.code`, `content.meaning` |
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

四阶段流程：
1. 输入（用户粘贴 / 文件 / URL / case 集合）；
2. **grill 阶段**（如果是工程师输入或 case 归纳）—— agent 反复追问"你指的是不是这个意思"，确保产物符合用户意图；
3. 草稿落入 `references/_inbox/`；
4. maintainer 审 → accept 落正式目录 / adjust / reject / defer。

**关键设计原则**：
- **入口与入库解耦**——to-reference 产出在 inbox，maintainer 审核后才正式入库；
- **grill 阶段去噪**——避免一切材料堆到 maintainer ；
- **来源类型决定审核深度**——maintainer 审 inbox 时按 source type 决定 spot-check 深度。

to-reference skill 设计与 to-postmortem 对称——to-postmortem 产出 case，to-reference 产出 reference。

---

## Consequences

### 1. 短期（合并本 ADR 后立即生效）

- 删除 `knowledge/platforms/a2-910b.md`、`a3-910c.md`、`a5-950.md`（PR #11 引入的 `[unverified]` 标注随之移除，PR #11 body 需更新说明）；
- 建立 `references/` 目录结构（5 个 type 子目录 + `_inbox/` + `_archive/` + `.gitkeep` 占位）；
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
| ADR-0005（知识消费 split） | reference 目录对 sparse-checkout 用户透明——`_inbox/` 与正式目录都跟随仓库 |
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

---

## Open Questions

### Q1. `_index.yaml` 是否需要？

reference 量小时（< 50 条），grep 全目录可能比维护索引更轻量。但量上来后（数百条），全量索引能加速 agent 检索。

**当前倾向**：暂不生成 `_index.yaml`，靠物理目录 + grep 检索；reference 量超过 50 条时再生成。这是参数治理事项。

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

1. 建立 `references/` 目录结构（5 个 type 子目录 + `_inbox/` + `_archive/`，每个含 `.gitkeep`）；
2. 创建 `references/_types.yaml` 注册表（5 个 type）；
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
