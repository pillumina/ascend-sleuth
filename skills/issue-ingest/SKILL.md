---
name: issue-ingest
description: >
  从外部 issue 源（GitHub 等）批量导入案例知识。编排上游 issue 拉取、硬过滤、价值评估、沉淀与状态标记：拉取精简元数据（fetch_issues.py，不含 body），硬过滤+启发式排序（issue_filter.py：label 池/评论数/标题规则/已处理排除），对候选按需评估（subagent 读 body 判断可否沉淀），通过的走 to-postmortem 沉淀为 case 草稿（进 inbox 待审），完成后标记已导入（幂等）。框架差异（repo、label 体系）参数化配置。前置环境：gh CLI 已安装并登录（未登录引导 gh auth login）。这是外部 issue 源 → case 的统一批量注入入口，与 to-postmortem（人工笔记等异构来源）互补。
---

# Issue Ingest

从上游仓库的 closed issue 批量沉淀 case。适合：团队想吸收某框架（vllm-ascend / vllm / mindspeed-llm…）的 issue 里的排障知识，而不想逐条手工翻 issue。

**自动化边界（默认自动，转正留人）**：本 skill 自动完成"拉取 → 过滤 → 评估 → 沉淀草稿 → 标记已导入"，产出 `status: draft` 的 case 草稿进 `postmortems/inbox/`——**不进诊断上下文**，由维护者批量审后转正。知识生效点（draft → active）始终是人。

## 前置环境（不满足先处理，不跳过）

1. **gh CLI**：`gh --version` 检查；未安装 → 提示用户安装（`curl -fsSL https://cli.github.com/ | sh` 或包管理），装完重查；
2. **gh 登录**：`gh auth status` 检查；未登录 → 引导用户 `gh auth login`（选 GitHub.com → HTTPS → **Login with a web browser**，用户浏览器完成授权）——不要替用户输入凭据，等 auth status 通过；
3. 其他源（GitCode 等）：确认对应 CLI（如 `gitcode-cli`）已装已登录，本 skill 流程以 GitHub 为例，其他源换 CLI 命令即可（缓存格式保持一致：number/title/comments/closed_at/labels/state_reason）。

## 输入方式（按需交互：给得越全，问得越少）

```
/skill:issue-ingest --repo vllm-project/vllm-ascend --labels triaged [--since <ISO时间>] [--min-comments 3] [--limit 20] [--mode auto|confirm]
/skill:issue-ingest vllm-ascend                        # 半明确：调查后给建议
/skill:issue-ingest "我想导入些昇腾训练框架的 issue"    # 不明确：引导问框架，再走半明确
```

| 用户给到什么 | agent 行为 |
|---|---|
| 完整参数（`--repo --labels ...`）| 直接执行（不打扰）|
| 半明确（框架名或仓库）| 查 `ingest-state.json` 该源有无 config → 有则复用（显示给用户，可改）；无则**调查 + 建议 + 确认**（见步骤 0）|
| 不明确 | 引导问框架 → 走半明确路径 |

- `--repo`：上游仓库（必填；半明确时 agent 从框架名映射，映射不了就问）
- `--labels`：issue 池（可覆盖 config / 映射表；默认按下表）
- `--since`：增量游标（从 `ingest-state.json` 的 `last_fetch_oldest_closed` 续拉，或用户指定）
- `--min-comments`：最少评论数（默认 3，有排查过程的信号）
- `--limit`：候选上限（默认 20）
- `--mode`：`auto`（默认，批量自动评估沉淀）| `confirm`（候选列表给用户过目后再评估）

## 源配置固化（ingest-state.json 的 sources.<source>.config）

**交互中确认过的配置固化下来，同一仓库下次不再问同样的问题**——与 case/先验沉淀同一哲学。

- **生命周期**：首次导入某仓库 → 调查（label 体系/规模）→ 给建议 → 用户确认 → **写入 `config`**（labels / min_comments / limit / strategy 说明）；再次导入同仓库 → 读 `config` 直接执行（显示配置，用户可改）；用户改参数 → 覆盖 `config`
- **config 位置**：`ingest-state.json` → `sources.<source>.config`（与 processed/游标同处）
- **更新**：仓库 label 体系演进或策略变化 → 用户主动改参数时覆盖；无需显式清理

## 框架 label 映射（初始猜测；半明确路径先查 config，无 config 再调查确认）

| 框架 | 主池 | 说明 |
|---|---|---|
| vllm-ascend | `triaged` | 维护者确认过，信噪比最高；不够再扩 `bug` |
| vllm（上游）| `bug` | 无 triaged 体系时用 bug |
| 其他框架 | 调查后确认 | 先 `gh api repos/<repo>/labels` 看实际 label 体系再定，**不猜** |

## 流程

### 0. 配置（仅半明确/不明确路径；有 config 或无参数冲突时跳过）

```bash
# 查实际 label 体系（零 token）
gh api repos/<repo>/labels --jq '.[].name'
# 数候选池规模（可选，按 label 逐个数）
gh api "search/issues?q=repo:<repo>+is:issue+is:closed+label:<候选label>&per_page=1" --jq '.total_count'
```

给用户建议（主池 label、min_comments、limit、预计候选数），用户确认或调整 → **写入 `config`**；用户给了完整参数 → 跳过本步，直接执行（并把参数记入 config 供下次复用）。

```bash
python3 scripts/fetch_issues.py --repo <repo> --state closed --labels <labels> \
  [--since <游标>] --output /tmp/issues-<repo>.json
```

只拉元数据（不含 body）。输出重定向文件，不进 context。

### 2. 硬过滤 + 启发式排序（0 token）

```bash
python3 scripts/issue_filter.py --cached /tmp/issues-<repo>.json \
  --state ingest-state.json --source "github/<repo>" \
  [--labels <labels>] [--min-comments 3] [--limit 20] [--report /tmp/candidates.json]
```

已处理编号排除（幂等）、label 池、评论数、标题规则；候选按 label 优先级（triaged>bug）/ 已解决 / 评论数排序。读候选列表。

**增量缓存同样走本步统一过滤**——`--since` 拉出的新缓存也过 `issue_filter.py`（标题规则/评论数/已处理排除都要应用），**勿直接读增量文件跳过过滤**（增量里的 `[Doc]`/`[Feature]` 等标题规则条目会被滤掉，直接读会混进评估）。

### 3. 评估（~1-2K token/条，只花在候选上）

对候选逐条：`gh api repos/<repo>/issues/<n>` 取 **body + 评论**（issue 的 body 多为环境信息+现象，**根因和 fix 通常沉淀在评论里**——至少读最后 2-3 条评论，结论常在尾部；body 只读现象段落），判断：
- **可否沉淀**：症状→根因→fix 是否闭环（根因有定论、fix 有方向即可，不必等社区验证）、是否昇腾相关、是否与现有 case 重复（对照 `knowledge/` 与 `postmortems/`）；
- 评论数多的不等于可沉淀（可能多问题未定论）——以"根因是否定论 + fix 是否明确"为判据，不只看评论热度；
- 不可沉淀（feature/讨论/无结论）→ 跳过，但记录到 `ingest-state.json` 的 `processed`（`--mark-imported` 一并标记，防反复评估）。

`--mode confirm`：先展示候选列表（编号/标题/评论数）给用户确认取舍，再评估。

### 4. 沉淀 + 同步 pre-triage（~3-5K token/条，产资产）

评估通过的 → 走 `/skill:to-postmortem` 逐条提炼（症状/根因/fix/命名空间建议），产出 case 草稿 + postmortem 进 `postmortems/inbox/`。批量时逐条执行，不合并多 issue 为一条 case。

**产出时同步 pre-triage**（省去提交时重复判断）：用 `knowledge/_index.yaml` 按 symptoms/tags 定位现有 case 候选，全量读比对 root_cause 与 fix，给 `new_pattern` / `variant_of:<case-id>` / `covered_by:<case-id>` + 证据（简要），写入 draft 头注释（如 `# pre-triage: variant_of VLLM-ASC-XXXX（同算子×同网络，增量=维护者确认升级修复）`）。groom 复核该标签而非重判。

### 5. 标记已导入（幂等闭环）

```bash
python3 scripts/issue_filter.py --state ingest-state.json \
  --source "github/<repo>" --mark-imported <n1,n2,...>
```

把本次处理过的编号（含评估跳过与已沉淀）追加 `processed`——下次拉取不重导。评估跳过的不反复评估。

### 6. 报告落点

```
拉取 N 条 → 候选 M 条 → 评估通过 K 条 → 沉淀 case 草稿 K 条 → postmortems/inbox/（待审）
已标记 J 条编号（含跳过）→ ingest-state.json（幂等）
转正：维护者批量审 inbox（/skill:knowledge-groom）
```

## 与既有 skill 的关系

- **to-postmortem**：issue 提炼复用其沉淀逻辑（本 skill 只做"外部源的预过滤与编排"，不重复提炼）；
- **knowledge-groom**：inbox 批量审、转正、索引重建在 groom 轮；
- **诊断**（diagnose）：沉淀的 case 转正后进入 Tier 2，下次诊断命中。

## 幂等与可重复

- `ingest-state.json`：`processed`（已处理编号，硬排除）+ `last_fetch_*_closed`（游标）+ `config`（用户确认过的源配置）——重复运行不重导、不重评估、不重问配置；
- 拉取无状态、过滤纯本地——管道可重复执行，结果稳定。

## 为什么需要专门入口

工程师不会为了"把 issue 翻一遍"写 postmortem；但上游 issue 里躺着大量已验证的排障知识（triaged = 维护者确认过）。专门的批量入口把门槛降到一条命令：拉取、过滤、评估、沉淀全自动，人只审转正。
