# 知识消费的分层拉取：安装层可选、仓库层 sparse-checkout

## Context

- 用户通过 Agent Skills 安装 skill 时，存在两层"知识获取"选择，README 未说明、机制未明文化
- 安装层：`npx skills add -s diagnose` 只装 `skills/`（方法论），知识库是仓库附带的可选资产——是否拉取已可选，但未成文
- 仓库层：拉取后，用户可能只想消费部分知识（自己框架的格子），git sparse-checkout 机制存在，但会打破"全库一致"的索引不变量（`_index.yaml` 是全量索引，稀疏 checkout 后阶段二按 `file` 读不到未拉文件 → 悬挂引用）
- 框架式 fork 模式（git-workflow.md）定义了团队级"自积累/自维护"，但用户级"消费 vs 自积累"的选择未成文

## Decision

**一、知识获取的两层选择，成文为 README 的「知识从哪来」**

| 层 | 机制 | 语义 |
|---|---|---|
| 安装层：要不要知识库 | `npx skills add -s diagnose`（只装 skill）/ 默认（装仓库含 knowledge/） | 自积累 vs 消费 |
| 仓库层：拉哪部分 | git sparse-checkout 按目录白名单 | 定制知识面 |

两者正交：只装 skill = 自己生成维护知识（框架式自积累，原则四）；拉仓库 = 消费现成知识（+ 可继续沉淀 + 可脱敏回馈上游）。

**二、sparse-checkout 是仓库层唯一采用机制**（submodule / 分支镜像否决，见下）

```bash
git sparse-checkout init --cone
git sparse-checkout set skills/ docs/ examples/ eval/ \
  knowledge/_index.yaml knowledge/common/ knowledge/inference/vllm-ascend/
```

- cone 模式粒度即目录——对齐 ADR-0004 格子结构，可精确到 `(framework × category)` 格子
- **common/ 必拉**（triage 的 fallback 命名空间 + 跨框架权威记录），不可从白名单省略

**三、稀疏拉取后的索引重建规则（防悬挂引用的硬要求）**

- `_index.yaml` 是生成物，稀疏 checkout 后**必须重跑 `build_index.py`**——它从现存文件生成，自然只索引拉到的格子
- 两个用户拉不同子集 → 各自索引不同 → **"定制知识面"是特性不是缺陷**：检索只在子集内进行，无需额外机制
- 此规则写进 README「知识从哪来」节 + git-workflow（若实现时）

**四、只装 skill（不自带知识）的完整路径**

```
只装 skill（knowledge/ 空或不存在）
  → /skill:diagnose 空库提示（诚实退化，SKILL.md 已实现）
  → 自己诊断 → /skill:to-postmortem 沉淀 → 自己的 knowledge/
  → 可选：脱敏后回馈上游（fork PR），公开库渐厚
```

## Rejected / Deferred

- **submodule 按 namespace 拆**：粒度太碎（格子数×框架数个子模块），语义是"固定版本依赖"而知识要持续跟进上游，维护成本高——否决
- **分支镜像（training-only 等）**：知识生产侧双份维护——否决
- **本 ADR 的实现**：当前仓库小，全量 clone 零负担；sparse 为规模设计。触发闸门：知识库体积可感知影响 clone 时长，或真实出现"只要某框架格子"的带宽/存储需求

## 参数治理

common/ 必拉、稀疏粒度（框架级 vs 格子级）为初始决策，随真实消费模式复核——若用户普遍要"整个框架"而非单格子，README 示例可改为框架级白名单。
