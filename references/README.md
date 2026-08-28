# references/ — 先验知识层（ADR-0008）

先验知识的统一载体，与 `knowledge/`（case）并列。reference 词条是**独立于任何具体事故**的领域事实与方法论，诊断时由 agent 按需查询。

设计决策、schema 定义、状态机与审核机制见 [ADR-0008](../docs/adr/0008-prior-knowledge-framework.md)。本 README 只做快速导航。

## 目录结构

```
references/
├── _types.yaml               # type 注册表（渐进登记；CI 强校验的 schema 依据）
├── _inbox/                   # to-reference 产出待审（maintainer 审核后落正式目录）
├── errors/                   # type: error-code
├── tools/                    # type: tool
├── platform-facts/           # type: platform-fact
├── command-side-effects/     # type: command-side-effect
├── methodologies/            # type: methodology（深审）
└── _archive/                 # deprecated 保留（版本 obsolete 不删除）
```

## 词条最小形态（所有 type 必填）

```yaml
id: <unique-id>
type: <registered-type>        # 见 _types.yaml
title: <short>
summary: <one-liner>
sources:                       # 至少 1 条，带来源类型
  - type: official-doc | engineer-input | case-derived
    # ... 按来源类型的必填子字段
last_verified: <YYYY-MM-DD>    # 人审日期
status: draft | active | pending-review | deprecated
```

## 来源类型（trust ladder）

| source type | 初始 confidence | 审核 |
|---|---|---|
| `official-doc` | 0.6 | 标准双签 |
| `engineer-input` | 0.3 | 标准双签 |
| `case-derived` | 0.3–0.6 | 深审（+ methodology 需 ≥3 条 case 引用才可 active） |

## 当前状态

**23 条 A5 950 platform-fact 已入库（全部 `status: active`，2026-08-28）**：来源为《昇腾950 NPU 架构白皮书》（华为）。**核验约定**：本批发出的词条均以 `verification: cross-checked-source` 声明——即 agent 已用 pymupdf 直接提取 PDF 原文、逐字核验过（每条的 evidence 只保留独特的章节/页码引用，核验方式不再逐条重复）；reviewer 抽查即可。inbox 队列当前为空。平台背景知识文档（`knowledge/platforms/*.md`）已按 ADR-0008 废弃且**未转化**入库（内容为 agent 生成、零外部源）——本批词条与旧 platform doc 不同：从第一天就带权威来源、已对 PDF 原文核验。后续填充优先级：plog 错误码表 / CANN 兼容矩阵（见 ADR-0008 §Consequences 2）。

## 校验

`python3 scripts/verify_references.py --check`（CI 中随 kb-checks 运行）：
- 基础元信息强校验（id/type/title/summary/sources/last_verified/status）；
- type 必须已登记（`_types.yaml`）；
- 按 type 强校验 `schema_required` 字段；
- 按来源类型强校验子字段；`sources[].verification`（可选）填了必须合法（`auto-extracted` / `cross-checked-source`，ADR-0008 §4.2）；
- 深审：case-derived + methodology 从全库 case 的 `ref_knowledge` 派生计数，<3 不允许 `status: active`。

**维护约定——词条零注释**：词条 YAML 是给 agent 消费的数据，**不得含任何 `#` 注释行**（语义解释只在本 README / ADR-0008 / SKILL.md 文档层）。新增词条后 `grep -c "#" <file>` 应为 0。
