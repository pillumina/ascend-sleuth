# 自演进实验协议

maintainer 只调用 `/skill:self-evolve`；本文件是内部执行参考，不是独立 skill。

## 先选目标

- 先跑 `python3 scripts/evolve.py traces sync`，再跑 `python3 scripts/evolve.py rsi plan`；有 replay 结果时加 `--replay .s2-replay`；
- RSI plan 合并 trace/metrics/replay 信号，推荐 region，并标记 `actionable` / `needs_agent_attribution` / `needs_agent_selection`；
- 规则不确定时，让 agent 产出带 evidence 的 region 结论，用 `rsi attribute/select --state` 写回；不要在 skill 里手改 plan；
- 目标必须是具体 skill 的可变异区；骨架、phase、工具、schema、trace 字段、severity、halt 条件冻结；
- holdout issue 不进候选池；没有可变异区或归因不明确就停，记 `insufficient`。

## 执行

以 `rsi plan` 输出的 `stages` 为准；不要在本文件里手选算法或固定模式。

默认组合是：

- 归因、选 region 先走规则；规则不确定时才让 agent 补证据/在注册区中选；
- 提案默认由 agent 从失败反馈写可变异区；写之前用 `experiment request --target <t> --component <region>` 取 target-specific prompt、允许路径和输出 schema。`propose.agent` 是启发式提案节点，不是 GEPA；GEPA 是 `select.pareto + propose.agent` 的组合。baseline 只评估 seed，不产生候选。
- 候选选择默认单候选；只有 plan 里选择搜索策略时才进入候选池/Pareto；
- judge 独立于 proposer；
- gate 确定性/人工，不交给 agent；
- baseline 只评估 seed，不产生候选。

candidate 只能作为单个 region 的 Patch，在隔离 worktree 应用；apply/rollback/diff 走 `candidate` 命令，不改主检出，不写真实 traces。

执行顺序：

```text
task subagents → judge subagents
  → reflection/proposer（若 stages 需要）
  → candidate task/judge
  → gate → experiment record
```

DSH Desktop 的提案/实验由会话内 subagent 编排，不走 `agent_adapter --agent dsh`；Claude/Codex 只有在 CLI 是标准做法时才走外部命令，结果仍写回 ProposalPort/RSIStore。具体算法实现、state 命令和可选组合看机制文档与 `rsi plan` 的 `stages`；需要跨进程状态机时用对应 CLI 的 `--help`，不要把某个算法写成固定模式。

结果至少写 `target_kind`、`target_component`、`algorithm`、`algorithm_version`、`execution`、`decision`、`samples`、baseline/candidate 分数；subagent 模式写 `execution=subagent`、`eval_profile_id=subagent_judge`、`eval_ready=false`。同时保存实际 `stages`。

agent 归因只能给候选，不能写成 hard；agent 选点只能在注册区里选。

如果目标是 `diagnose.knowledge_usage`，记录命中、首命中步、候选数、全文读取、reference 查询、wrong_cases、token/时间；用 `knowledge-usage compare` 做准确率不降、效率不降的门禁，不能只看速度。

如果目标是 `diagnose.source_usage`，记录 repo/ref、files_read、tool_calls、fetch/grep、elapsed；用 `source-usage compare` 要求源码结论 correctness 不降、访问效率不降。演进评估 trace 只写 `.s2-replay/evolve/usage-traces/`，不写真实 `traces/`。

## 停点

- 预算用尽、种群满、没有未反射候选：停；
- baseline 全对：记 `insufficient`；
- 有回归：`reject`；
- 候选格式漂移/无法拼回完整 skill：`reject`；
- 记录后停；合入走 review、CODEOWNERS、分支保护，不自动合并。
