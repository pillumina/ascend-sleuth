# 平台可移植性：流程语义与平台执行器分离

知识库的 git 流程语义（PR、评审、双签、标签、保护分支、CI 门控）定义在文档层，不绑定任何代码托管平台；平台只充当执行器。当前实现基于 GitHub，可迁移至 GitCode / Gitee，迁移只替换执行器，不动流程语义与仓库内容。

## Context

- 团队生态现实：GitCode 是华为系平台，昇腾支持工作若回归内网生态，最终归宿可能是 GitCode；保留迁移自由是战略需求
- 部署模式已支持框架式 fork（见 git-workflow.md），多平台是同一自由在托管层的表现
- 本 ADR 的原则来源：设计原则二（不变量写进结构——逻辑进脚本与文档，不进平台专有配置）与原则九（诚实退化——迁移后门控强度如实改标，不假装仍有硬门）

## Decision

**逻辑分层规则**（迁移成本的结构性保证）：

| 层 | 归属 | 迁移时 |
|---|---|---|
| 设计原则 / 理论 / ADR / SKILL.md / 知识 schema / trace 协议 | 平台无关（纯文件） | 原样带走 |
| scripts/（build_index、trace_metrics） | 平台无关（纯 Python + PyYAML） | 原样带走 |
| 流程语义（PR 评审、双签、标签集、分支保护规则） | 文档定义（git-workflow.md） | 语义不变 |
| CI 触发与流水线 yml | **平台专有** | 重写（~10 分钟，逻辑在 scripts/ 里） |
| CODEOWNERS 自动路由 | **平台专有**（GitHub 特性） | 降级方案（见下） |
| PR 模板格式 | 半平台专有 | 内容保留，格式适配 |
| Wiki | 平台专有形态 | 内容策略：进 docs/ 不进 wiki |

**CODEOWNERS 降级预案**（最大实质差异）：Gitee/GitCode 无 CODEOWNERS 文件等价物。审批路由降两级：

- v1（降级可用）：CODEOWNERS.example 转为**人读的路由表**；提交者按表手动 request reviewer；分支保护设"需 1 人审批"覆盖普通变更；`kb/high-risk` 的第二签从结构强制降为模板勾选 + 审计留痕
- v2（对等恢复）：若目标平台有 webhook/机器人生态，复刻 `kb/high-risk → 自动 request 第二审核人`（与 GitHub Actions 方案同逻辑，约 20 行）
- **诚实改标**：git-workflow.md 门控映射表中"CODEOWNERS 审批：硬"在迁移后改为"半硬（路由表 + 流程 + 留痕）"，文档强度跟随实际强度

**Wiki 内容策略**：GitHub wiki 底层是独立 git 仓库；Gitee wiki 为数据库存储（API 不同）。结论：**一切内容进 `docs/`，wiki 至多做导航页**——docs/ 是普通文件，迁移零成本。

**分支保护与权限**：各平台均有保护分支 + 审批数设置，语义对应见 git-workflow.md 平台对应表。GitHub Org 的 team 细粒度权限在个人仓库/其他平台的对应物需按平台确认；权限分阶段收紧策略不变（见 git-workflow.md）。

## 迁移清单（半天以内）

1. git push 仓库本体至新平台（全部文件随行）
2. 重写 CI yml（kb-checks 三条命令不变：pyyaml 安装、build_index --check、triage-tree 解析）
3. CODEOWNERS.example 加注"手动执行的路由表"，git-workflow.md 门控强度改标
4. PR 模板搬迁适配（Gitee `.gitee/` 目录或 GitCode 等价物；内容原样）
5. 分支保护 / 标签 / issue 模板手工配置（~1 小时网页设置）
6. wiki 若有内容，迁回 docs/
7. 验证：跑一轮 demo 流程（提交 → CI 红/绿 → 评审 → 合并），确认门控语义完整落地

## 战略注记

迁移成本随平台专有配置的积累而上涨。规则：**平台专有配置控制在最小面（CI yml + 分支保护设置），一切逻辑留在 scripts/ 与文档**。若 GitCode 是预期最终归宿，早迁比晚迁便宜——现在约半天，Actions 生态（自动指派、groom 自动化）长起来之后再迁则成本倍增。
