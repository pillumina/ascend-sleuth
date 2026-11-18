# 自演进实验协议

maintainer 只调用 `/skill:self-evolve`；本文件是它的内部执行参考，不是独立 skill。

## 先选目标

- 先跑 `python3 scripts/evolve.py traces sync`，再跑 `python3 scripts/evolve.py rsi plan`；有 S2 replay 结果时加 `--replay .s2-replay`；RSI plan 合并 trace/metrics/replay 信号，推荐 region，并标记 `actionable` / `needs_agent_attribution` / `needs_agent_selection`；
- 从推荐 region、`self-evolve run` 的 next_actions、或评测失败中选一个组件；
- 目标必须是具体 skill 的可变异区，例如 `diagnose` 的 `routing_hints`；
- 先从 `traces sync` 的 `experiment` 推荐拿 target/region；holdout issue 不进候选池；
- 不把整份 skill 当候选；骨架、phase、工具、schema、trace 字段、severity、halt 条件冻结；
- 没有可变异区或归因不明确就停，记 `insufficient`，不让用户逐次手选。

## 模式 A：一次 reflection 对照

适合 smoke/小改：

```text
baseline task subagents → judge subagents → baseline scores
reflection subagent（只看失败反馈）→ candidate 区文本
candidate task subagents → judge subagents → candidate scores
gate → experiment record
```

task 只看样本输入；judge 看 expected/rubric；reflection 不写仓库；一次只改一个区。

结果至少写 `target_kind`、`target_component`、`algorithm`、`algorithm_version`、`execution`、`decision`、`samples`、baseline/candidate 分数；subagent 模式写 `execution=subagent`、`eval_profile_id=subagent_judge`、`eval_ready=false`。

## RSI stage

不要手选或写死 stage id；以 `rsi plan` 输出的 `stages` 为准，注册表与当前实现见机制文档。默认组合是：

- 归因、选点先走规则；规则不确定时才让 agent 补证据/在注册区中选；
- 提案默认由 agent 从失败反馈写可变异区；
- judge 独立于 proposer；
- gate 确定性/人工，不交给 agent；
- baseline 只评估 seed，不产生候选；GEPA 是“Pareto 选择 + agent 提案”的可选组合。

agent 归因只能给候选，不能写成 hard；agent 选点只能在注册区里选。

## 模式 B：agent-native GEPA

适合候选池/Pareto/预算：

```bash
python3 scripts/agent_gepa.py init \
  --seed-file seed-region.md --target-skill diagnose --region routing_hints \
  --samples S-1,S-2 --state /tmp/gepa-state.json \
  --max-metric-calls 12 --population 4
```

循环：

```bash
python3 scripts/agent_gepa.py next --state /tmp/gepa-state.json
# evaluate → task subagent + judge subagent → record
# reflect   → reflection subagent → candidate
# stop      → result
```

- 候选池、Pareto、预算由状态机维护；不手改 state。
- 每个 candidate × sample 只评一次；task/judge 不复用同一 agent。
- `result` 给 target_skill/mutable_region/best/pareto/calls；按它判 accept/reject/insufficient。
- 算法名写 `gepa-agent`，不冒充官方 `gepa` 库。

## 模式 C：官方 GEPA 库（可选）

只有在 Python ≥3.10、稳定模型 endpoint、`task_lm`/`reflection_lm` 可用时才走 `GepaOptimizer`；否则不要接。官方库结果算法名写 `gepa`。

## 停点

- 预算用尽、种群满、没有未反射 Pareto：停；
- baseline 全对：记 `insufficient`；
- 有回归：`reject`；
- 候选格式漂移/无法拼回完整 skill：`reject`，不进入下一轮；
- 记录后停；合入走 review、CODEOWNERS、分支保护，不自动合并。
