---
name: to-reference
description: >
  把昇腾先验知识沉淀成 reference 词条（ADR-0008）。输入支持内联粘贴、单个文件、URL 爬取、或从已有 case 集合归纳共性。提取事实/方法论，按 references/_types.yaml 归类（error-code / tool / platform-fact / command-side-effect / methodology），标来源类型（official-doc / engineer-input / case-derived）与验证状态，经 grill 阶段与用户反复确认意图后，产出结构化 YAML 草稿到 references/_inbox/ 待审队列。这是先验知识的统一入口——与 to-postmortem（案例）并列，先验知识从这里汇入，不从 diagnose 自动生成。
---

# To Reference

先验知识注入入口，与案例知识（`/skill:to-postmortem`）并列。**reference 是独立于任何具体事故的领域事实与方法论**——不是 case，不携带 symptoms/diagnosis/fix 闭环。本 skill 的产物落在 `references/_inbox/` 待审队列，由 maintainer 审核后才转正。

> ⚠️ **质量原则（比 case 更严）**：reference 是知识库的浓缩资产，一旦错误，污染的是所有引用它的诊断。**本 skill 的产出不是"录进去"，是"提交审核"**——先与用户反复确认意图（grill），再进 inbox，最后由 maintainer 审核。三个环节缺一不可。

## 输入方式

接受四种输入，来源类型决定信任基础与后续审核深度：

**1. 内联粘贴**（工程师经验 / 手册片段，`engineer-input`）：

```
/skill:to-reference "在 A2 上排查通信问题，别查 HCCL_BUFFSIZE，查 NPU 驱动版本：cat /proc/driver/npu/version，期望 >= 23.0"
```

**2. 单个文件路径**（笔记 / 内部文档，`engineer-input`）：

```
/skill:to-reference --file ~/notes/npu-smi-fields.md
```

**3. URL 爬取**（官方文档，`official-doc`）：

```
/skill:to-reference --ingest https://www.hiascend.com/document/.../plog-error-codes
```

**4. 从 case 集合归纳**（`case-derived`，最常见——工程师没有专门写先验知识的习惯，但案例里反复出现共性）：

```
/skill:to-reference --ingest-cases "[VLLM-ASC-9596, VLLM-ASC-12989, VLLM-ASC-9507]"
```

## 流程

### 0. 识别来源类型（决定流程分支）

| 输入 | 来源类型 | grill 强度 | 审核深度 |
|---|---|---|---|
| URL 爬取 | `official-doc` | 弱（来源明确；标注 auto-extracted 交 reviewer spot-check） | 标准双签 |
| 内联 / 文件 | `engineer-input` | **强**（必须反复确认意图） | 标准双签 |
| case 归纳 | `case-derived` | **强**（必须确认归纳不失真） | 深审 |

### 1. 提取（按来源类型）

**URL 爬取（official-doc）**：
- 抓取页面正文（只抓目标章节，不全量载入——日志裁剪原则的翻版）；
- 抽取为 reference 草稿，**保留原文出处**：`url` + `version`（文档版本 / CANN 版本，从页面元数据或内容推断，拿不准就标 unknown）+ `fetched_at`；
- 标注 `verification: auto-extracted`——**这是模型抽取，不是人核**，reviewer 必须 spot-check 语义是否被扭曲。

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
| 错误码/异常代码的含义 | `error-code` |
| 工具/命令的用法与输出解读 | `tool` |
| 平台硬事实（可独立验证的客观事实） | `platform-fact` |
| 命令/环境变量的副作用与回滚 | `command-side-effect` |
| 多步骤诊断/调优流程 | `methodology` |

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

**URL 爬取**：不逐项 grill（来源明确），但**必须**在报告里显式告诉用户"这是模型抽取的摘要，建议打开原文核对语义"，并把 `verification: auto-extracted` 写进草稿。

grill 是**人审的第一道过滤**——确认过程中用户放弃/否认的条目，直接丢弃，不进 inbox。宁可少而准，不要多而疑。

### 4. 去重检查（进 inbox 前）

扫 `references/` 现有词条（含 `_inbox/`）：
- 有完全覆盖的现有词条 → **不产草稿**，告诉用户"这条已被 `<ref-id>` 覆盖"，列出比对；
- 是变体（同主题不同平台/版本）→ 提示用户："现有 `<ref-id>` 覆盖 A3，你这条是 A5 场景——是要并进现有词条的 applies_to，还是独立词条？"按用户回答处理；
- 查不到 → 新词条，继续。

### 5. 产出草稿 → `references/_inbox/`

按 ADR-0008 schema 产出完整 YAML（基础元信息 + content 全部填齐，CI 对 inbox 同样校验——草稿也必须 schema 完整，这是与 to-postmortem 草稿可残缺的差异）：

```yaml
id: <kebab-case-slug>              # 唯一；如 plog-error-507903、a3-hccl-buffsize-check
type: <registered-type>            # 见 references/_types.yaml
title: <short>
summary: <one-liner>

sources:
  - type: <official-doc | engineer-input | case-derived>
    # official-doc: url + version + fetched_at
    # engineer-input: engineer + input_session + confirmed_at
    # case-derived: cases + extracted_at

applies_to:                        # 能确定就填，确定不了留待 grill 后补
  platforms: [...]                 # A2-910B | A3-910C | A5-950 | cross
  frameworks: [...]
  versions: {...}
  categories: [...]                # methodology 必填

status: draft                      # 永远从 draft 起步——active 是审核后的状态
last_verified: <今天>              # 人确认的日期（grill 认可即视为一次人核）

content:
  # 按 type 的 schema_required 字段（见 _types.yaml / references/README.md）
```

- `status` **永远写 `draft`**——没有任何途径在本 skill 里产出 active（active 需要 maintainer 审核 + 深审条件，见 ADR-0008 §6）；
- 初始 confidence 按来源类型（写进草稿注释，供审核参考）：`official-doc` 0.6 / `engineer-input` 0.3 / `case-derived` 0.3–0.6（case 数与一致性越高越靠近 0.6）；
- `last_verified` 填今天——grill 阶段用户认可即视为一次人工确认，但**这不替代 maintainer 审核**。

### 6. 报告落点（生成后必须明确告知）

```
草稿 → references/_inbox/<ref-id>.yaml
来源类型：<engineer-input | official-doc | case-derived>
状态：draft（待 maintainer 审核转正；case-derived + methodology 需 ≥3 条 case 引用才可 active）
审核建议：<按来源类型的审核深度提示>
```

别让用户去找自己的产出——报出具体路径，说明"maintainer 审后转正，审核走 PR"。

## 产出落点

- `references/_inbox/<ref-id>.yaml`——草稿（待审队列，见 `references/_inbox/README.md`）
- maintainer 审核（`/skill:knowledge-groom` 或独立 review）后：accept → 移入 `references/<type-dir>/`、按需改 status；reject → 归档说明原因；defer → 留在 inbox

**与 to-postmortem 的分工**：案例（事故闭环）→ `/skill:to-postmortem` → `knowledge/`；先验知识（独立事实/方法论）→ `/skill:to-reference` → `references/`。两条入口不互相覆盖——to-postmortem 不自动产 reference，to-reference 不反向产 case。

## 为什么先验知识要专门入口

案例沉淀（to-postmortem）解决"同类问题下次直接命中"；但工程师的**通用经验**（怎么查 plog、哪个命令看什么、这个错误码意味着什么）不绑定任何具体事故，散在个人脑子里，每次诊断都重新摸索。没有专门入口，这些知识永远进不了仓库——因为工程师不会为了沉淀"我知道怎么查设备日志"去写一份 postmortem。to-reference 把这个门槛降下来：**工程师随口一句话，agent 提取 + grill 确认，30 秒进待审队列**。
