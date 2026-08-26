# Git 工作流：审核、门控与合入

目标是在不预设具体 owner 的前提下，让门控、审核、分发与合入的闭环可以运转。全部机制用 git 原生能力承载：分支保护、PR、CODEOWNERS、标签、CI，并可移植到不同平台（GitHub / GitLab / GitCode 的对应关系见文末）。

需要说明各道闸门的实际强度。git 能够硬性强制的是三件事：谁审批过、YAML 是否合法、索引是否新鲜。语义层面的闸门——脱敏是否彻底、root cause 是否正确、severity 标注是否恰当——只能依靠流程约定与人工抽查。下表对每道闸门标注强度，避免把约定误认为已被强制。

## 分支模型

- `main` 受保护、禁止直接 push：所有知识库变更（包括 groom 的周批次）都走 PR。
- 冷启动或单人阶段可以先不开分支保护，机制先行、权限后收紧；kb-checks CI 从第一天就启用，它是唯一不依赖人的硬门。

## 部署形态

两种形态都支持，inbox、groom、索引与 CI 机制在两种形态下的工作方式相同：

| 模式 | 形态 | 适用场景 |
|---|---|---|
| 集中式 | 训练与推理团队共用一个仓库，`CODEOWNERS` 按命名空间划分审批权 | 团队规模小，问题域重叠多 |
| 框架式（fork） | 团队 fork 本仓库，自行积累或导入知识；上游只同步方法论目录 | 团队自治，知识含敏感数据 |

fork 模式下的目录归属：

- 上游（方法论）：`skills/ scripts/ docs/ examples/ eval/ .github/ README.md CLAUDE.md CONTEXT.md triage-tree.yaml`。triage-tree 是共享资产，修改它属于高风险变更；`.github/` 含 CI 与 PR 模板，随方法论同步。
- fork 自有（知识）：`knowledge/ postmortems/`（含 `inbox/`），不参与上游合并，因此不存在冲突面。

同步方式为 `git fetch upstream && git merge upstream/main`。对框架的改进以 PR 形式反提上游；知识内容不回流，脱敏后的构造示例除外。

## inbox 条目状态机与标签集

```
draft(inbox/) ─► triaged(三分类标签) ─► reviewed(人审) ─► merged(升格/转正)
                                          └► rejected(关闭，留痕)
```

| 标签 | 打在哪 | 含义 |
|---|---|---|
| `kb/new-pattern` | inbox 条目 / PR | 预分诊：新根因，建议升格 Tier 2 |
| `kb/variant` | 同上 | 预分诊：已有 case 的变体，建议并入（扩 compat） |
| `kb/covered` | 同上 | 预分诊：已被覆盖，仅 postmortem 转正 Tier 3 |
| `kb/needs-structurer-review` | 条目 | 语义或格式可疑（校验失败） |
| `kb/needs-human-review` | 条目 | 语义不明 |
| `kb/high-risk` | PR | 高风险变更，需双签（见下） |
| `kb/groom-report` | issue | 周 groom 变更摘要（通知与留档载体） |
| `kb/stale` | issue / 条目 | inbox 停留超过两周，标红催办 |

## 门控映射表

| 闸门 | 机制 | 强度 |
|---|---|---|
| YAML 语法 + 索引新鲜度 | CI：`scripts/build_index.py --check`（顺带解析全部 case YAML） | 硬（红即挡 merge） |
| 命名空间变更审批 | `CODEOWNERS` + 分支保护 required review | 硬 |
| 高风险双签 | `kb/high-risk` 标签 + CODEOWNERS 双组路径（每组至少一人批） | 半硬（"恰好两个 approval"需人核验，见下） |
| 脱敏 / severity 纪律 | to-postmortem 流程 + groom 周批审抽查 | 约定 |
| eval 回归（改 skill 时） | 按 [eval.md](eval.md) 手动 replay，M2 脚本化后并入 CI | 约定 → 半硬 |

## PR 模板

`.github/PULL_REQUEST_TEMPLATE/` 下按变更对象分四类（创建 PR 时选择，或 `?template=` 直链）：**knowledge_intake**（新知识升格：预分诊+证据+脱敏自查）、**knowledge_modification**（改 expected/fix/compat 等高风险字段：触发条款+依据+双签）、**methodology**（skill/脚本/文档：原则追溯+golden 回归对照）、**structure**（triage-tree/namespace：数据依据+迁移完整性检查单）。模板里的"机器可填"字段当前手工填写，自动生成在 roadmap 待定池（PR 描述机器层生成）。模板目录属上游方法论，随 fork 同步。

## 高风险双签

高风险清单与 `skills/knowledge-groom/SKILL.md` 保持一致：新建 `common/` 权威记录、修改 `expected`、修改 `fix_on_mismatch`、修改 `compat` 区间、手动覆盖 `confidence.score`。

落地步骤：

1. groom 在变更 PR 上打 `kb/high-risk` 标签，PR 描述列出触发的条款；
2. `CODEOWNERS` 将 `knowledge/common/` 与 `triage-tree.yaml` 指向两组评审人（领域 owner 组与体系维护人组），配合分支保护的 required review，使两组各至少一人批准；
3. 平台限制：GitHub 与 GitLab 原生不强制"批准者来自不同小组"。CODEOWNERS 的多组配置可以逼近这一要求，最终的数量核验写入 groom-report 检查单，由开 PR 的人自查勾选。

owner 尚未确定时，`CODEOWNERS.example` 保留 TODO 占位，CI 与标签流程照常运转；owner 落实后将占位文件复制为 `.github/CODEOWNERS` 并填入真实账号，硬门随即生效。

## 通知机制

- 周 groom 摘要：写入变更 PR 的描述（@ 对应 owner，即时触达），同时开一个打 `kb/groom-report` 标签的 issue 留档，避免重复打扰；
- inbox 积压：groom 摘要中标红；停留超过两周的条目可以开 `kb/stale` issue 催办；
- `feedback_pending` 不走 git：它记录在 `diagnosis_state-*.yaml` 中，可能包含客户信息，已被 `.gitignore` 挡在仓库之外，通知依靠任何一次 diagnose 或 resume 启动时的扫描。这是刻意设计，不要把它搬进 issue。

## CI

`.github/workflows/kb-checks.yml` 已提供，内容等价于：

```bash
pip install pyyaml
python3 scripts/build_index.py --check
```

两条命令在任何平台都能等价配置（GitLab CI 的 `.gitlab-ci.yml`、GitCode 流水线同理）。索引过期意味着变更不完整——修改了 case 却忘记重建索引——CI 直接置红。

## 平台对应表

| 机制 | GitHub | GitLab | GitCode |
|---|---|---|---|
| 分支保护 | branch protection rule | protected branches | 保护分支 |
| 属主审批 | CODEOWNERS + require review | approval rules / CODEOWNERS | 评审规则 |
| 标签 | labels | labels | 标签 |
| CI | Actions | GitLab CI | 流水线 |
