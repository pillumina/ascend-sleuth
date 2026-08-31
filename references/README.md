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
status: active | pending-review | deprecated | draft   # 新产出即 active（PR review 即审核闸门，合入即生效）；draft 仅遗留旧态（修订 3 前产出），由 groom R1 清理
```

## 生命周期（修订 3：产出即 active，PR 合入即生效）

- to-reference 产出 `status: active` 词条 → 随 PR 提交 → **PR review 即审核闸门，合入即生效**（进入诊断上下文）；
- 未合入的 PR 分支不 main，天然不进诊断上下文——安全性由"合入动作"承担，无 draft 中间态；
- **深审门槛在产出时满足**：case-derived + methodology 需 ≥3 条 case 引用（`verify_references.py` 强制，CI 把关，产出时不达标 PR 直接红）；
- 遗留 draft（修订 3 前产出）：`/skill:knowledge-groom` R1 按需清理（accept 改 active / adjust / reject）；
- 修订 active 词条 = 修改已生效知识 → **kb/high-risk 双签**。

## 来源类型（trust ladder）

| source type | 初始 confidence | 审核 |
|---|---|---|
| `official-doc` | 0.6 | 标准双签 |
| `engineer-input` | 0.3 | 标准双签 |
| `case-derived` | 0.3–0.6 | 深审（+ methodology 需 ≥3 条 case 引用才可 active，产出时 CI 把关） |

## 核验约定

词条 `verification` 的两种声明（ADR-0008 §4.2）：
- `cross-checked-source`：agent 已对源逐字核验——白皮书批次用 pymupdf 提取 PDF 原文逐字核验；官方文档批次对官方 markdown 转录逐字核验、未逐字核对原始 HTML 页面，reviewer 可抽查；
- `auto-extracted`：模型从源材料抽取、未对源逐字核验，reviewer 必须 spot-check 语义是否被扭曲。

平台背景知识文档（`knowledge/platforms/*.md`）已按 ADR-0008 废弃且**未转化**入库（内容为 agent 生成、零外部源）——reference 词条从第一天带权威来源。

**词条数量是运行时状态**，不写进本 README（会随导入/转正腐烂）——用 `python3 scripts/verify_references.py` 实时查。

## 校验

`python3 scripts/verify_references.py --check`（CI 中随 kb-checks 运行）：
- 基础元信息强校验（id/type/title/summary/sources/last_verified/status）；
- type 必须已登记（`_types.yaml`）；
- 按 type 强校验 `schema_required` 字段；
- 按来源类型强校验子字段；`sources[].verification`（可选）填了必须合法（`auto-extracted` / `cross-checked-source`，ADR-0008 §4.2）；
- 深审：case-derived + methodology 的提炼来源 case 数（`sources[].cases` 长度）<3 不允许 `status: active`。

**修订走 PR**（ADR-0008 §1.7）：内容修订 active 词条 = 修改已生效知识 → **methodology 模板 + `kb/high-risk` 双签**（小修直接改 YAML + PR；大修用 `/skill:to-reference --update <ref-id>`）。

**维护约定——词条零注释**：词条 YAML 是给 agent 消费的数据，**不得含任何 `#` 注释行**（语义解释只在本 README / ADR-0008 / SKILL.md 文档层）。新增词条后 `grep -c "#" <file>` 应为 0。
