---
name: to-reference
description: >
  把昇腾先验知识沉淀成 reference 词条。输入支持内联粘贴、单个文件、URL 爬取、或从已有 case 集合归纳共性。提取事实/方法论，按 references/_types.yaml 归类（error-code / tool / platform-fact / command-side-effect / methodology），标来源类型（official-doc / engineer-input / case-derived）与验证状态，经 grill 阶段与用户反复确认意图后，产出结构化 YAML 草稿（status: draft 直进正式 type 目录，PR review 即审核闸门）。这是先验知识的统一入口——与 to-postmortem（案例）并列，先验知识从这里汇入，不从 diagnose 自动生成。
---

# To Reference

先验知识注入入口，与案例知识（`/skill:to-postmortem`）并列。**reference 是独立于任何具体事故的领域事实与方法论**——不是 case，不携带 symptoms/diagnosis/fix 闭环。本 skill 的产物以 `status: draft` 直接落入正式 type 目录（`references/<type-dir>/`），PR review 即审核闸门——review 通过翻 active 才生效；draft 状态保证未审内容不进诊断上下文。

> ⚠️ **质量原则（比 case 更严）**：reference 是知识库的浓缩资产，一旦错误，污染的是所有引用它的诊断。**本 skill 的产出不是"录进去"，是"提交审核"**——先与用户反复确认意图（grill），再进 inbox，最后由 maintainer 审核。三个环节缺一不可。

## 输入方式

接受四种输入，来源类型决定信任基础与后续审核深度：

**1. 内联粘贴**（工程师经验 / 手册片段，`engineer-input`）：

```
/skill:to-reference "在 A2 上排查通信问题，别查 HCCL_BUFFSIZE，查 NPU 驱动版本：cat /proc/driver/npu/version，期望 >= 23.0"
```

**2. 单个文件路径**（来源类型由 `--source` 指定，不默认绑定）：

```
/skill:to-reference --file ~/notes/npu-smi-fields.md --source engineer-input
/skill:to-reference --file ~/ascend/昇腾950_NPU架构白皮书.md --source official-doc
```

`--source` 是**必填判断项**（engineer-input / official-doc）：来源类型由**内容权威性**决定，不由输入通道决定——同一份文件可能是工程师笔记（engineer-input）也可能是官方文档（official-doc）。本地 PDF 也可处理：用工具提取文本（如 `pymupdf`）后再走本模式，`verification` 状态见 §1。

**3. URL 爬取**（官方文档，`official-doc`）：

```
/skill:to-reference --ingest https://www.hiascend.com/document/.../plog-error-codes
```

**4. 从 case 集合归纳**（`case-derived`，最常见——工程师没有专门写先验知识的习惯，但案例里反复出现共性）：

```
/skill:to-reference --ingest-cases "[VLLM-ASC-9596, VLLM-ASC-12989, VLLM-ASC-9507]"
```

**5. 修订已有 reference**（`--update <ref-id>`——内容有误/过时/不完整时更新，**不是新增**）：

```
/skill:to-reference --update cann-runtime-error-codes --ingest <新来源 url>
```

- agent 读现有词条 + 新材料，产出**修订 diff 建议**（改了什么/为什么），人确认后落 PR；
- 修订 active 内容 = 修改已生效知识 → **kb/high-risk 双签**（对齐 case 层 knowledge_modification）；
- 修订前先确认该 ref 已被标 `pending-review` 或 `draft`（降级中修订；diagnose 只读 active 天然隔离）；
- 小修（错别字/补一句/改一个错误码含义）→ 不启动 --update，维护者直接改 YAML + PR 更轻（git diff 可追溯）；--update 留给大修（methodology 流程重写/错误码表按新官方文档整体更新）。

## 流程

### 0. 识别来源类型（决定流程分支）

| 输入 | 来源类型 | grill 强度 | 审核深度 |
|---|---|---|---|
| URL 爬取 | `official-doc` | 弱（来源明确；标注 `verification` 交 reviewer） | 标准双签 |
| `--file --source official-doc` | `official-doc` | 弱（本地官方文档，来源明确） | 标准双签 |
| `--file --source engineer-input` / 内联 | `engineer-input` | **强**（必须反复确认意图） | 标准双签 |
| case 归纳 | `case-derived` | **强**（必须确认归纳不失真） | 深审 |

### 1. 提取（按来源类型）

**official-doc（URL 爬取 / 本地官方文档文件）**：
- 抓取/读取目标章节（只读相关部分，不全量载入——日志裁剪原则的翻版；本地 PDF 用工具提取文本如 `pymupdf`）；
- **长字段（description/meaning）不硬截断**——截断到字符数会产生不完整句子（"在第一…"式残缺），语义完整性优先于体积；需要精简时提炼要点而非截断原文；
- 抽取为 reference 草稿，**保留原文出处**：`url`（来源定位符——公开 URL 优先；本地文档无公开 URL 时用**可移植文档引用**如"昇腾950 NPU 架构白皮书（华为技术有限公司）"，**禁止写 `~/` 或绝对路径**，CI 会红）+ `version`（文档版本 / CANN 版本，从页面元数据或内容推断，拿不准就标 unknown）+ `fetched_at`；
- **必须标注 `sources[].verification`，二选一**：
  - `auto-extracted`——模型从源材料抽取、**未经 agent 对源逐字核验**（如一次 URL 抓取后直接归纳），reviewer 必须 spot-check 语义是否被扭曲；
  - `cross-checked-source`——agent 已直接对源原文（如 PDF 文本提取）逐字核验，reviewer 抽查即可。**只有当你真的逐字对照过源才标这个**；拿不准一律标 `auto-extracted`（诚实退化，宁低估不高估）。

**内联 / 文件（engineer-input）**：
- 从工程师描述中抽取事实/方法论，判断 type（见 §2）；
- 判断它**独立于具体事故**（是 reference）还是**绑定事故**（是 case，引导走 `/skill:to-postmortem`）；
- 缺失的信息（适用平台？适用版本？出处？）记下来，grill 阶段逐项问。

**case 归纳（case-derived）**：
- 读取指定 case 的 `root_cause` / `diagnosis` / `fix`；
- 找**共性模式**——重复出现的根因对象、相似的诊断步骤、相似的 fix 模板；
- 归纳为 reference 草稿，**保留证据**：`cases: [<case-id>, ...]` + `extracted_at`；
- 区分两类产物：事实共性 → `platform-fact`/`error-code`/`tool`；流程共性 → `methodology`。

### 2. 归类（type 判定）

按 `references/_types.yaml` 注册表判定 type：

| 信号 | type |
|---|---|
| 错误码/异常代码的含义 | `error-code`（**表形态**——按组件分族成表，一个族一个文件；多个码合入同一表，不逐码建文件） |
| 工具/命令的用法与输出解读 | `tool` |
| 平台硬事实（可独立验证的客观事实） | `platform-fact` |
| 软件栈/运行时系统硬事实（日志路径与格式、机制、进程行为；不绑定硬件平台） | `software-fact` |
| 故障模式对照（现象→根因→处理，按主题域成表） | `fault-pattern`（**表形态**——一个域一个文件，条目 `pattern/symptoms/cause/fix`） |
| 命令/环境变量的副作用与回滚 | `command-side-effect` |
| 多步骤诊断/调优流程 | `methodology` |

区分 `platform-fact` 与 `software-fact`：绑定具体硬件平台/芯片规格（如 "A5 HBM 64GB"）→ `platform-fact`；CANN 软件栈或运行时系统的可验证事实（如日志路径、格式、机制，跨平台成立）→ `software-fact`。

**fault-pattern 表形态（组织单元 = 验证单元）**：官方手册的"现象→根因→处理"排障条目（非多步流程、非事故闭环）→ 按主题域成表（如 `references/fault-patterns/dvpp-decode.yaml` 承载 VDEC/JPEGD 解码故障）。`symptoms` 是可直接 grep 的日志签名/错误码（诊断时按签名命中根因），`cause`/`fix` 提炼自来源。

**error-code 表形态（组织单元 = 验证单元）**：错误码天然成族（CANN Runtime 507xxx / HCCL / aicpu / Driver），同族同源同验证——**一个族一个文件**（如 `references/errors/cann-runtime.yaml` 承载 507903/507018/507057...），表级共享 sources/status/applies_to，不逐码建文件。case 提炼的条目逐条验证 → 条目带可选 `source_cases`。检索时 agent 按族定位文件，表内 grep code 一次命中。**数据集类的 `applies_to` 平台/版本应从来源的结构化字段映射（如官方文档的 models/support 字段），不靠 agent 猜测**——来源没声明的平台不写。

拿不准 type → 按最贴近的登记 type 落草稿，并在草稿里标注 `type_uncertain: true` 交 maintainer 定夺。**不要自行发明未登记 type**（CI 会红；登记是 maintainer 的动作，见 `_types.yaml`）。

### 3. Grill 阶段（关键——确保产物符合用户意图）

**工程师输入（内联/文件）必须逐项确认，不是一次性"对吗"**：

1. **意图确认**：把你提取的核心事实/方法论用自己的话复述给用户："我理解你说的是：……，对吗？"——用户纠正就更新，直到用户明确认可；
2. **边界确认**：适用平台？适用框架/版本？适用范围之外的情况是不是也成立？逐维问（platforms / frameworks / versions / categories），确认 `applies_to` 字段；
3. **出处确认**："这条经验的来源是？——某次客户案例 / 某份内部文档 / 官方手册哪一章？"出处含糊 → 草稿标 `source_vague: true`，仍可进 inbox 但 maintainer 审时会重点查；
4. **排除确认**："这条在什么情况下**不**成立？"——工程师最常漏掉反例，这是 reference 区别于 case 的关键（reference 是断言，必须有适用范围）。

**case 归纳必须确认不失真**：

1. **共性确认**："这三条 case 的共同点是 X，我归纳为 Y，对吗？"——用户认可才继续；
2. **差异确认**："这三条里有没有哪条是特例（根因不同但现象相似）？"——有特例就剔出，避免把偶然共性当规律；
3. **覆盖确认**："这个归纳覆盖了你要沉淀的东西吗？还是你心里还有第 4 种场景？"

**official-doc**：不逐项 grill（来源明确），但**必须在报告里显式告诉用户验证状态**——`auto-extracted` 要说明"这是模型抽取的摘要，建议打开原文核对语义"；`cross-checked-source` 要说明"已对源原文核验，可抽查"。把 `verification` 写进草稿 `sources[]`。

**grill 分级（体验瘦身——反复对齐是置信度增加过程，但按需分级，不是无差别多轮）**：

- **高置信（默认）**：来源明确（official-doc）、内容自包含、无歧义 → **单次确认**——一次复述"我理解你说的是：……，对吗？"，用户认可即过，不逐项追问；
- **中置信**：工程师输入但表述清晰 → 确认意图 + 出处，边界/反例顺带一问；
- **低置信**（必须多轮）：表述含糊、来源不明、边界不清 → 完整四轮（意图/边界/出处/反例）逐项确认。

判据：**agent 自评置信度决定 grill 深度**——高置信单次、低置信多轮；拿不准往高一档走（宁可多确认一次，不因省事产出歧义词条）。

grill 是**人审的第一道过滤**——确认过程中用户放弃/否认的条目，直接丢弃，不进 inbox。宁可少而准，不要多而疑。

### 4. 去重与聚类归属检查（进正式目录前）

扫 `references/` 现有词条，分三种关系：

- **完全覆盖**（现有词条已含本条全部内容）→ **不产草稿**，告诉用户"这条已被 `<ref-id>` 覆盖"，列出比对；
- **变体**（同主题不同平台/版本）→ 提示用户："现有 `<ref-id>` 覆盖 A3，你这条是 A5 场景——是要并进现有词条的 applies_to，还是独立词条？"按用户回答处理；
- **层级**（现有词条是总览、本条是细节，或反之——如现有 `a5-l2-cache` 总览 vs 本条 `a5-l2-cache-detail`）→ 提示用户："现有 `<ref-id>` 是总览，你这条是同一主题的细节——建议独立词条并在两边 `related_references` 互指；或并进现有词条。哪种？"按用户回答处理。层级关系本身是**合法结构**（不是重复），但要显式互链，避免检索时只见其一；
- 查不到 → 新词条，继续。

**聚类归属（追加不新建）**——数据集类（error-code）在去重之外还要判定族归属：

- 提炼到错误码 → **先查 `references/errors/` 现有文件**，按组件判定归属（族划分跟随来源——CANN 错误码参考怎么分章，文件就怎么建）；
- 归属已有族（如 507xxx 进 `cann-runtime.yaml`）→ **追加到该表 `errors` 列表**，标新 `source_cases`——**不新建文件**；
- 仅无对应族文件时才新建（如第一个 HCCL 错误码 → 建 `references/errors/hccl.yaml`）；
- 独立词条类：查 `tags` / `related_references` 是否可关联现有词条，**不合并**（关联不合并——主题聚合由标签承担，不是文件合并）。

### 5. 产出草稿 → `references/<type-dir>/`（draft，无 _inbox）

> ⚠️ **词条零注释（硬规则）**：下面模板中的 `#` 注释是**给作者看的写作指引**，产出 YAML 时必须**删除全部注释行**——词条是给 agent 消费的数据，不是带元说明的文档；重复注释是 token 浪费（23 条 × 同一注释的教训）。语义解释（url 定位符规则、verification 含义、status 规则、字段含义）只存在于 SKILL.md / references/README.md 文档层，**不进词条**。值自解释就不加注释。

按 reference schema 产出完整 YAML（字段定义见 `references/_types.yaml` 与 `references/README.md`；基础元信息 + content 全部填齐，CI 对 inbox 同样校验——草稿也必须 schema 完整，这是与 to-postmortem 草稿可残缺的差异）：

```yaml
id: <kebab-case-slug>              # 唯一；如 plog-error-507903、a3-hccl-buffsize-check
type: <registered-type>            # 见 references/_types.yaml
title: <short>
summary: <one-liner>

sources:
  - type: <official-doc | engineer-input | case-derived>
    # official-doc: url + version + fetched_at [+ verification]
    # engineer-input: engineer + input_session + confirmed_at
    # case-derived: cases + extracted_at
    # verification（official-doc 必填，其余可选）:
    #   auto-extracted | cross-checked-source

applies_to:                        # 能确定就填，确定不了留待 grill 后补
  platforms: [...]                 # A2-910B | A3-910C | A5-950 | cross
  frameworks: [...]
  versions: {...}
  categories: [...]                # methodology 必填

status: draft                      # 永远从 draft 起步——active 是审核后的状态
last_verified: <今天>              # 人确认的日期（grill 认可即视为一次人核）
# 观测字段（可选；产出时**不填**，由 groom 在 reference 观测回写时有数据才填）：
#   hits: <int>                    # 被引用次数（trace.reference_lookup 计数）
#   last_hit: <date>               # 最后引用时间

content:
  # 按 type 的 schema_required 字段（见 _types.yaml / references/README.md）
  # error-code 是表形态：content.errors 列表，一个族一个文件，不逐码建文件
  #   errors:
  #     - code: "507903"
  #       meaning: "..."
  #       related_signatures: [...]
  #       source_cases: [<case-id>]   # case 提炼的证据（可选）
```

- `status` **永远写 `draft`**——没有任何途径在本 skill 里产出 active（active 需要 maintainer 审核 + 深审条件）；
- 初始 confidence 按来源类型（写进草稿注释，供审核参考）：`official-doc` 0.6 / `engineer-input` 0.3 / `case-derived` 0.3–0.6（case 数与一致性越高越靠近 0.6）；
- `last_verified` 填今天——grill 阶段用户认可即视为一次人工确认，但**这不替代 maintainer 审核**；
- **产出前检查：词条文件里不得有任何 `#` 注释行**（上模板中的注释全部删掉）——`grep -c "#" <file>` 应为 0。

### 6. 报告落点（生成后必须明确告知）

```
草稿 → references/<type-dir>/<ref-id>.yaml（status: draft）
来源类型：<engineer-input | official-doc | case-derived>
状态：draft（待 maintainer 审核转正；case-derived + methodology 需 ≥3 条 case 引用才可 active）
审核建议：<按来源类型的审核深度提示>
```

别让用户去找自己的产出——报出具体路径，说明"maintainer 审后转正，审核走 PR"。

## 产出落点

- `references/<type-dir>/<ref-id>.yaml`——草稿（status: draft；PR review 即审核闸门，accept 后翻 active）
- maintainer 审核（`/skill:knowledge-groom` 或独立 review）后：accept → 移入 `references/<type-dir>/`、按需改 status；reject → 归档说明原因；defer → 留在 inbox

**与 to-postmortem 的分工**：案例（事故闭环）→ `/skill:to-postmortem` → `knowledge/`；先验知识（独立事实/方法论）→ `/skill:to-reference` → `references/`。两条入口不互相覆盖——to-postmortem 不自动产 reference，to-reference 不反向产 case。

## 为什么先验知识要专门入口

案例沉淀（to-postmortem）解决"同类问题下次直接命中"；但工程师的**通用经验**（怎么查 plog、哪个命令看什么、这个错误码意味着什么）不绑定任何具体事故，散在个人脑子里，每次诊断都重新摸索。没有专门入口，这些知识永远进不了仓库——因为工程师不会为了沉淀"我知道怎么查设备日志"去写一份 postmortem。to-reference 把这个门槛降下来：**工程师随口一句话，agent 提取 + grill 确认，30 秒进待审队列**。
