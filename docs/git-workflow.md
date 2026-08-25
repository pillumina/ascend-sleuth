# Git 工作流：审核、门控与合入（落地版）

> 目标：**不预设具体 owner 也让 gating / 审核 / 分发 / 合入闭环可跑**。用 git 原生机制（分支保护、PR、CODEOWNERS、标签、CI）承载，平台可移植（GitHub / GitCode / GitLab 对应关系见文末）。
>
> 诚实边界：git 能**硬强制**的只有"谁批了、YAML 合不合法、索引新不新鲜"；语义闸门（脱敏彻底吗、root cause 对吗、severity 标对了吗）永远是流程约定 + 人审抽查。下表对每道闸门标注强度，别把约定当成已被强制的。

## 分支模型

- `main` 受保护：禁止直接 push，一切 KB 变更走 PR（groom 的周批次也是一个 PR）
- 冷启动/单人阶段可先不开保护（机制先行，权限后紧）；kb-checks CI 第一天就开——它是唯一不依赖人的硬门

## 部署形态（两种皆可，机制不变）

| 模式 | 形态 | 适用 |
|---|---|---|
| **集中式** | 训/推两团队共用一个 repo，`CODEOWNERS` 按 namespace 划审批权 | 团队小、问题域重叠多 |
| **框架式（fork）** | 团队 fork 本仓库，知识自己积累/导入；上游只同步方法论目录 | 团队自治、知识含敏感数据 |

fork 模式的目录归属：

- **上游（方法论）**：`skills/ scripts/ docs/ examples/ eval/ README.md CLAUDE.md CONTEXT.md triage-tree.yaml`（triage-tree 是共享资产，改它=高风险）
- **fork 自有（知识）**：`knowledge/ postmortems/`（含 `inbox/`）——不参与上游合并，无冲突面
- 同步：`git fetch upstream && git merge upstream/main`；框架改进反向提上游 PR，知识不回流（脱敏后的构造示例除外）

## inbox 条目状态机与标签集

```
draft(inbox/) ─► triaged(三分类标签) ─► reviewed(人审) ─► merged(升格/转正)
                                          └► rejected(关闭，留痕)
```

| 标签 | 打在哪 | 含义 |
|---|---|---|
| `kb/new-pattern` | inbox 条目 / PR | 预分诊：新根因，建议升格 Tier 2 |
| `kb/variant` | 同上 | 预分诊：已有 case 变体，建议并入（扩 compat） |
| `kb/covered` | 同上 | 预分诊：已覆盖，仅 postmortem 转正 Tier 3 |
| `kb/needs-structurer-review` | 条目 | 语义/格式可疑（校验失败） |
| `kb/needs-human-review` | 条目 | 语义不明 |
| `kb/high-risk` | PR | 高风险变更，需双签（见下） |
| `kb/groom-report` | issue | 周 groom 变更摘要（通知与留档载体） |
| `kb/stale` | issue / 条目 | inbox 停留 >2 周，标红催办 |

## 门控映射表

| 闸门 | 机制 | 强度 |
|---|---|---|
| YAML 语法 + 索引新鲜度 | CI：`scripts/build_index.py --check`（顺带解析全部 case YAML） | **硬**（红即挡 merge） |
| namespace 变更审批 | `CODEOWNERS` + 分支保护 required review | **硬** |
| 高风险双签 | `kb/high-risk` 标签 + CODEOWNERS 双组路径（每组至少一人批） | **半硬**（"恰好两个 approval"需人核验，见下） |
| 脱敏 / severity 纪律 | to-postmortem 流程 + groom 周批审抽查 | 约定 |
| eval 回归（改 skill 时） | `docs/eval.md` 手动 replay（v1.5 脚本化后并入 CI） | 约定 → 半硬 |

## 高风险双签落地

高风险清单（与 `skills/knowledge-groom/SKILL.md` 一致）：新建 `common/` 权威记录、改 `expected`、改 `fix_on_mismatch`、改 `compat` 区间、手动覆盖 `confidence.score`。

1. groom 在变更 PR 上打 `kb/high-risk`，PR 描述列出触发的条款
2. `CODEOWNERS` 把 `knowledge/common/` 与 `triage-tree.yaml` 指到两组 reviewer（领域 owner 组 + 体系维护人组），分支保护要求 required review → 两组各至少一人批
3. 平台限制（诚实标注）：GitHub/GitLab 原生不强制"不同组的两个人"——CODEOWNERS 多组可逼近，最终数量核验写进 groom-report 检查单，由开 PR 的人自查勾选

owner 未定怎么办：`CODEOWNERS.example` 留 TODO 占位，CI 与标签流程先跑通；owner 落实后复制为 `.github/CODEOWNERS` 填真实账号，硬门即生效。**机制先行，权限后紧。**

## 通知机制

- **周 groom 摘要** = 变更 PR 描述（@对应 owner，即时）+ 同步开 issue 打 `kb/groom-report`（留档、不打扰）
- **inbox 积压**：groom 摘要中标红；可选为 >2 周条目开 `kb/stale` issue
- **feedback_pending 不走 git**：它在 `diagnosis_state-*.yaml`（含客户信息，已被 `.gitignore` 挡在仓库外），通知靠任何 diagnose/resume 启动时扫描——这是刻意设计，不要把它搬进 issue

## CI（`.github/workflows/kb-checks.yml` 已提供）

```bash
pip install pyyaml
python3 scripts/build_index.py --check
```

两条命令，任何平台都能等价配置：GitLab CI（`.gitlab-ci.yml`）、GitCode 流水线同理。索引过期 = 变更不完整（改了 case 忘了重建）= 红。

## 平台对应表

| 机制 | GitHub | GitLab | GitCode |
|---|---|---|---|
| 分支保护 | branch protection rule | protected branches | 保护分支 |
| 属主审批 | CODEOWNERS + require review | approval rules / CODEOWNERS | 评审规则 |
| 标签 | labels | labels | 标签 |
| CI | Actions | GitLab CI | 流水线 |
