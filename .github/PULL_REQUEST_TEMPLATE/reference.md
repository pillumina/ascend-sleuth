---
name: Reference 知识变更（导入 / 转正 / 修订）
about: 先验知识层（references/）的词条导入、转正或修订
labels: []
---

## 变更类型

- [ ] **导入**：to-reference 产出的新词条（`status: active` 直进正式 type 目录）→ 本 PR review 通过合入即生效
- [ ] **遗留 draft 转正**：历史 draft → active（修订 3 前产出；审核通过，无内容改动）
- [ ] **修订**：修改 active 词条内容（= 修改已生效知识 → **kb/high-risk 双签**，见下）

## 词条清单（机器可填）

| id | type | 内容 | 状态变更 |
|---|---|---|---|
| `ascend-xxx` | software-fact | 一句话摘要 | 导入（active，合入即生效） |
| ... | | | |

## 来源与验证状态

- 来源类型：`official-doc` / `engineer-input` / `case-derived`
- `verification`：`cross-checked-source`（说明核验范围）/ `auto-extracted`（reviewer 需 spot-check）
- 词条间 `related_references` 互链情况（关联不合并）

## Agent 预核意见（机器可填，可选——非 agent 链路提交可留空）

<!-- 基于事实的独立意见，供 reviewer 对齐判断——不替代人审 -->

- 事实依据（来源类型 / 引用数据 / 与现有词条的聚类比对）：
- 期望正确性（来源可信度：official-doc 高 / engineer-input 中 / case-derived 视案例数）：
- 风险标注（需 spot-check 项 / 修订场景的高风险点）：

## 聚类检查（机器可填）

- [ ] 去重：无现有词条完全覆盖本次内容
- [ ] 数据集类（error-code / fault-pattern / env-var-table）：族/域/模块归属正确，**追加不新建**（已有族则追加条目，不新建文件）
- [ ] `applies_to` 从来源结构化字段映射，未超出来源声明

## 完整性（机器校验）

- [ ] CI 绿：`verify_references.py --check`（id 唯一、schema 强校验、深审门槛——active 词条产出时即达标）
- [ ] 词条零注释行（`grep -c "#"` = 0）
- [ ] `status` 与生命周期规则一致（导入即 active；遗留 draft 转正除外）

## 高风险检查（修订场景必填）

修订 active 词条内容 → 按知识修改规则 **kb/high-risk 双签**（methodology 模板 + 双 owner 签署）；仅导入（新词条即 active）与遗留 draft 转正不触发。小修（错别字/补一句）可直接改 YAML + 本 PR，大修用 `/skill:to-reference --update <ref-id>`。
