# references/_inbox/ —— 待审先验知识队列

`/skill:to-reference` 的新产出落这里（`<ref-id>.yaml` 草稿）。
不直接进正式 type 目录——那是 maintainer 审核后的事（accept → 移入 `references/<type-dir>/`）。

## 语义

- **本目录是队列，不是档案**：由 maintainer 审核清空（accept / adjust / reject / defer）；可与 `/skill:knowledge-groom` 周批合并处理，也可独立审核
- **草稿必须 schema 完整**：`verify_references.py` 对本目录同样校验（基础元信息 + content 全填齐）——reference 的 CI 入口门槛比 case 草稿更严（ADR-0008 §8）
- **`status: draft` 是硬约束**：没有任何草稿以 active 进入本目录；active 需要 maintainer 审核 + 深审条件（case-derived + methodology 需 ≥3 条 case 引用）
- **深审标注**：来源 `case-derived` 或 type `methodology` 的草稿，审核时必须核对其证据（case 引用真实性 / 归纳不失真），这是本队列里唯一需要深审的一类

## 审核深度（按来源类型，ADR-0008 trust ladder）

| 来源类型 | 审核动作 |
|---|---|
| `official-doc` | spot-check 模型抽取的语义是否被扭曲（`verification: auto-extracted`） |
| `engineer-input` | 核对 grill 记录（`input_session` 可回溯）；抽查边界/反例是否齐全 |
| `case-derived` | 深审：核对 case 引用真实性、归纳是否覆盖差异、是否 ≥3 条 case 印证 |

## 为什么是队列而不是即时审

与 postmortem inbox 同理：先验知识持续汇入时，逐条即时审核反工程师节律。to-reference 的 grill 阶段已经做了第一道过滤（意图确认），inbox 审核是第二道（质量闸门）——两道都过才转正。
