# Issue → Case 导入管道

把上游 GitHub issue（如 vllm-ascend 的 closed bug）筛选、评估、沉淀为 case 的半自动管道。自动化止步于"产 draft"，升格分场景（原则五：自动化产出建议，人做决定）。draft 默认进 inbox 批量审；owner 预授权的自动化源（本管道即配置的持续管道）产出的草稿 verification 链完整，可直接调 groom 升格，不等周批。知识生效点（draft → active）默认由人，自动化源的直接升格是 owner 预授权的例外。

## 管道流程

```
[拉取] fetch_issues.py（GitHub 专用，精简字段）
    ↓ 缓存 JSON（number/title/comments/closed_at/labels/state_reason，不含 body）
[硬过滤] issue_filter.py（已处理排除 / label 池 / 评论数 / 标题规则）+ 启发式排序
    ↓ 候选 JSON（--report）
[评估] subagent 按需 gh api issues/<n> 取 body，判断"可否沉淀 + 是否与现有 case 重复"
    ↓ 通过的
[沉淀] to-postmortem / to-reference（自动路径产 draft → postmortems/inbox/ 或 references/<type-dir>/）
    ↓
[标记] issue_filter.py --mark-imported <n1,n2>（追加 ingest-state.json 的 processed，幂等）
    ↓
[转正] 升格分场景：draft 默认进 inbox，owner 批量审（groom，人工按周批）→ active；owner 预授权源（本管道）的 draft 可直接 groom 升格 → active
```

## Token 节省设计（分层）

| 层 | 做法 | Token 成本 |
|---|---|---|
| 拉取 | `fetch_issues.py` 精简字段（不含 body），重定向文件 | ≈0（不进 context）|
| 硬过滤+排序 | 纯机械：label 池 / 评论数 / 标题 / 启发式（triaged>bug、state_reason=completed、评论数）| 0 |
| 评估 | 只对候选按需取单条 body，判断价值 | ~1-2K/条（花小钱过滤）|
| 沉淀 | 判断通过的才提炼 | ~3-5K/条（产资产，值得花）|

## 幂等与可重复

- `ingest-state.json`：`processed` 记录已导入编号（硬排除，重复跑不重导）；`last_fetch_*_closed` 是拉取游标（增量参考）；**`config` 固化用户确认过的源配置**（labels/min_comments/limit，同一仓库下次不重问）
- `--mark-imported`：沉淀完成后自动追加 processed（脚本化，不靠手工）
- 拉取无状态、过滤纯本地，管道可重复执行，结果稳定

## 交互分级（skill 实践）

| 用户给到什么 | agent 行为 |
|---|---|
| 完整参数 | 直接执行（不打扰）|
| 框架名/仓库 | 查 config 复用；无 config 调查（label 体系/规模）→ 建议 → 确认 → 固化 config |
| 不明确 | 引导问框架 → 走半明确路径 |

config 固化：首次确认过的源配置写入 `ingest-state.json` 的 `sources.<source>.config`，同一仓库下次不再问同样的问题（与 case/先验沉淀同一哲学）。

## 定时任务设计（未落地，方案）

自动化的正确边界：**拉取 + 硬过滤 + 候选报告**是机械的（检查准入判据 ✓），**评估与沉淀是判断性的**（不进自动化）。

候选载体（GitHub Actions schedule，如每周一 08:00）：
1. `schedule: cron('0 8 * * 1')` 触发 workflow
2. `gh api "repos/vllm-project/vllm-ascend/issues?state=closed&labels=triaged&since=<游标>"`（GITHUB_TOKEN 可读公开 repo）
3. `scripts/fetch_issues.py` 拉取精简字段 → `scripts/issue_filter.py` 硬过滤 → 候选列表
4. 候选写入 issue 注释或 PR（如 `docs/ingest-candidates.md` 更新 + PR），人看候选后触发评估+沉淀

不做的是：自动评估价值（读 body 判断）、自动沉淀（draft 前的判断环节留给 agent + 人）。转正例外：owner 预授权的自动化源产出的 draft（verification 链完整 + pre-triage 判别完成）可直接调 groom 升格，是预授权下的批量执行，非绕过人审（聚合 PR 仍人审合入）。

启用条件（按需）：管道经人工跑通 ≥2 轮且候选质量稳定后，再落地定时任务。

## 常用命令

```bash
# 拉取 triaged 池（增量：--since 用上次游标）
python3 scripts/fetch_issues.py --repo vllm-project/vllm-ascend --state closed \
  --labels triaged --since 2026-08-27T00:00:00Z --output /tmp/issues.json

# 硬过滤 + 启发式排序 + 候选报告
python3 scripts/issue_filter.py --cached /tmp/issues.json \
  --state ingest-state.json --source "github/vllm-project/vllm-ascend" \
  --labels triaged --min-comments 3 --limit 20 --report /tmp/candidates.json

# 评估通过、沉淀完成后标记已导入（幂等）
python3 scripts/issue_filter.py --state ingest-state.json \
  --source "github/vllm-project/vllm-ascend" --mark-imported 14660,14655
```

## 池选择

| 池 | 信号 | 建议 |
|---|---|---|
| `triaged` | 维护者确认过（555 条 closed）| **主池**，信噪比最高 |
| `bug` | 全 bug（1581 条 closed）| triaged 不够时扩展 |
| 全部 closed | 含 feature/question | 不推荐（噪音）|
