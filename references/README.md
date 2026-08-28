# references/ — 先验知识层（ADR-0008）

先验知识的统一载体，与 `knowledge/`（case）并列。reference 词条是**独立于任何具体事故**的领域事实与方法论，诊断时由 agent 按需查询。

设计决策、schema 定义、状态机与审核机制见 [ADR-0008](../docs/adr/0008-prior-knowledge-framework.md)。本 README 只做快速导航。

## 目录结构

```
references/
├── _types.yaml               # type 注册表（渐进登记；CI 强校验的 schema 依据）

├── errors/                   # type: error-code（表形态，按组件分族：cann-runtime/hccl/aicpu/driver）
├── fault-patterns/           # type: fault-pattern（表形态，按主题域成表：现象→根因→处理）
├── tools/                    # type: tool
├── platform-facts/           # type: platform-fact（硬件平台/芯片规格）
├── software-facts/           # type: software-fact（软件栈/运行时系统事实，不绑定硬件平台）
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

**76 条词条（2026-08-29）**：active 27 + draft 49。draft 均为 to-reference 导入待审（审核走 PR/groom，转正前不进诊断上下文）：日志收集 7（批 A）、故障处理工具与专题 8（批 B1-B3）、错误码 17 族 306 码（批 C，族划分跟随官方模块，小族合并 operator/misc）、故障案例 14 域 99 条（批 B4，fault-pattern 表）、模块字典与码结构 2（批 C）、env-var 2 表（批 D 先行）。**核验约定**：白皮书批次（26 active）以 `verification: cross-checked-source` 声明——agent 已用 pymupdf 直接提取 PDF 原文逐字核验；官方文档批次（日志/故障处理/错误码）同为 cross-checked-source——对官方 markdown 转录逐字核验、未逐字核对原始 HTML 页面，reviewer 抽查。平台背景知识文档（`knowledge/platforms/*.md`）已按 ADR-0008 废弃且**未转化**入库。

## 校验

`python3 scripts/verify_references.py --check`（CI 中随 kb-checks 运行）：
- 基础元信息强校验（id/type/title/summary/sources/last_verified/status）；
- type 必须已登记（`_types.yaml`）；
- 按 type 强校验 `schema_required` 字段；
- 按来源类型强校验子字段；`sources[].verification`（可选）填了必须合法（`auto-extracted` / `cross-checked-source`，ADR-0008 §4.2）；
- 深审：case-derived + methodology 的提炼来源 case 数（`sources[].cases` 长度）<3 不允许 `status: active`。

**修订走 PR**（ADR-0008 §1.7）：内容修订 active 词条 = 修改已生效知识 → **methodology 模板 + `kb/high-risk` 双签**（小修直接改 YAML + PR；大修用 `/skill:to-reference --update <ref-id>`）。

**维护约定——词条零注释**：词条 YAML 是给 agent 消费的数据，**不得含任何 `#` 注释行**（语义解释只在本 README / ADR-0008 / SKILL.md 文档层）。新增词条后 `grep -c "#" <file>` 应为 0。
