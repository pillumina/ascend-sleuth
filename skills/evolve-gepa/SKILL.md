---
name: evolve-gepa
description: >
  用当前 agent 的 subagent/agent team 跑 GEPA 核心循环：候选池、reflective mutation、Pareto 选择、预算停止。
  不依赖 gepa/Claude/Codex 库；状态由 JSON 文件驱动，task/judge/reflection 都由当前 agent 派 subagent。
  sleuth 场景只改 skill 可变异文本，不碰流程/ schema/工具/安全规则；记录后停，不自动合入。
---

# Evolve GEPA（agent-native）

这是 GEPA 的 agent-native 实现：算法在 `scripts/evolve/agent_gepa.py`，执行由当前 agent 的 subagent 承担。它不是官方 `gepa` 库结果，算法名写 `gepa-agent`。

## 触发

- subagent 模式的 smoke 已通过，要跑真正的候选池/Pareto 搜索；
- 用户要比较 baseline 与 GEPA 风格候选，但没有稳定模型 API/外部 CLI；
- 目标 skill 有可变异文本段、有样本、有 judge。

不触发：只补样本走 `eval-ingest`；只做一次 reflection 走 `evolve-experiment`。

## 硬边界（sleuth 适配）

- 只改允许的文本段：提示、追问策略、检查顺序、措辞；不改 phase、工具名、输出 schema、trace 字段、severity、halt 条件。
- 候选必须能拼回完整 skill 并通过 `skill-self-contained`、schema/golden 与人工 diff review。
- task subagent 只看样本输入，不看 expected；judge 只看 expected/rubric 与输出；reflection 只看失败反馈。
- 一次实验只优化一个 skill/组件；holdout/test 不参与候选生成。
- 没有 subagent/team 工具就停，不退化成外部 CLI。

## 状态机

```bash
python3 scripts/agent_gepa.py init \
  --seed-file seed-skill.md --samples S-1,S-2,S-3 \
  --state /tmp/gepa-state.json --max-metric-calls 12 --population 4
```

动作只有三种：

- `evaluate`：task subagent 生成诊断，judge subagent 打分，写回；
- `reflect`：reflection subagent 看 failures，产出候选 skill；
- `stop`：预算/种群/没有未反射的 Pareto 候选。

每步：

```bash
python3 scripts/agent_gepa.py next --state /tmp/gepa-state.json
python3 scripts/agent_gepa.py record --state /tmp/gepa-state.json \
  --candidate seed --sample S-1 --score 0 --feedback "..."
python3 scripts/agent_gepa.py candidate --state /tmp/gepa-state.json \
  --skill-file /tmp/candidate-skill.md
```

结束：

```bash
python3 scripts/agent_gepa.py result --state /tmp/gepa-state.json
```

`result` 给 `best_id`/`best_score`/`pareto`/`candidates`/`calls`；按它判 `accept/reject/insufficient`，不要自己另算一套。

## 执行拓扑

```text
next=evaluate → task subagent（只看输入）→ judge subagent（看 expected/rubric）
             → record
next=reflect  → reflection subagent（只看 failures/current skill）
             → candidate
             → 下一轮 evaluate
next=stop     → result → paired gate → experiment record
```

- task 与 judge 分开；不复用 task agent 自评。
- 每个 candidate × sample 只评一次；状态机拒绝重复。
- 候选池和 Pareto 由状态机维护，agent 不手改 `candidates`/`pareto`。
- 可并行派 task/judge，但 `record` 串行写状态文件；不要并发写同一个 state。

## 记录

完成后：

```bash
python3 scripts/evolve.py experiment record --file result.json
```

`result.json`：

- `target_kind`、`target_component`；
- `algorithm: gepa-agent`、`algorithm_version`；
- `execution: subagent`；
- `eval_profile_id: subagent_judge`、`eval_ready: false`；
- `decision`、`samples`、baseline/candidate 分数。

`eval_ready=false` 表示这是子 agent judge 的 smoke/实验，不是 arena/rubric 的正式门禁；不要拿它自动合入。

## 停止条件

| 条件 | 行为 |
|---|---|
| 预算用尽 | 停；用 `result.best` |
| 种群满 | 停；比较 Pareto |
| 没有未反射的 Pareto 候选 | 停；该轮无新候选 |
| baseline 全 1 | 无提升空间，记 insufficient |
| 候选有回归 | reject；保留失败反馈 |
| judge 分歧大 | 加第二 judge 或降 insufficient |
| 状态文件损坏/被并发写 | 停，重建 state；不手改分数 |
