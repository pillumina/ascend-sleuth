# RSI 真实数据验收记录

这篇记录一次真实数据验收：用了哪些数据、跑了哪些阶段、哪些通过、哪些还没通过。它不替代机制文档，只把证据和缺口放在一处。

## 1 数据与环境

- 环境：DSH Desktop 会话内；不使用 `DEEPSEEK_API_KEY`。
- 真实样本：`15866`，来自 `.s2-replay/evolve/samples/15866.yaml`。
- 真实轨迹：`pilot9k` 的 baseline/candidate trace 与 judge。
- 候选：DSH Desktop 会话内 subagent 生成 `C-REAL-A`、`C-REAL-B`，只改 `diagnose.knowledge_usage`。
- 当前限制：只有 1 条真实样本，不能据此证明泛化。

## 2 生产 gate 与探索 gate

同一组真实分数下：

| 候选 | 生产 gate | 探索 gate |
|---|---|---|
| A | reject（knowledge_usage insufficient） | reject |
| B | reject（efficiency_regressed） | accept（cost_ratio=0.950） |

生产 gate 没有放行；探索 gate 只用于验收流程，记录里带 `exploratory=true`，不能当作生产通过。

## 3 已跑通的链路

- `validate_rsi_replay.py`：用 `pilot9k` 真实轨迹重放 collect/decide，报告每个 stage 的状态。
- `validate_rsi_gepa.py --exploratory`：用两个真实 pilot 的候选与真实 judge 分数跑 GEPA 选择，选择 B，同时报告两个 gate 结果。
- `validate_rsi_full_flow.py --exploratory`：用真实 B 候选和真实 trace 走 candidate apply → pilot → judge → gate → archive/event。
- 结果：`P-0007 / EX-P-0007 accept (exploratory=true)`。

## 4 记录与面板

- 旧数据迁移：`store migrate`，真实结果 `events=76`，其中旧实验 6、旧提案 6、decision 10、rollout 54。
- A/B 与 full flow 写入后：`events=96`、`proposals=11`、`experiments=11`。
- `store verify` 仍报旧数据缺口：6 个实验无 conclusion、10 个 decision 孤儿、54 个 rollout 孤儿；A/B 没有新增缺口。
- `experiment show --proposal P-0007` 可回读 proposal/conclusion/experiments/history。
- 插件临时 profile 验证 5 个包：dump-config、client.js、host 路由都通过；临时实例没有仓库 cwd 时返回 `E_NO_REPO`，脚本明确写“路由存在、数据未读取”。

## 5 结论

- 真实数据上，proposal、candidate apply、pilot、judge、gate、store、readback 都能跑。
- agent heuristic 有真实候选与真实 trace；GEPA 只验证了选择层，没有多轮 reflection/Pareto。
- 生产 gate 仍拒绝所有候选；探索 gate 的接受不是质量证明。
- 插件尚未在当前宿主重启加载，真实浏览器渲染/UX 复查未做。
- 因此：全链路“能跑”已证明；全流程“solid”未证明。

## 6 复现

```bash
python3 scripts/validate_rsi_replay.py --pilot .s2-replay/evolve/pilot9k
python3 scripts/validate_rsi_gepa.py --exploratory --pilot <A> --pilot <B>
python3 scripts/validate_rsi_full_flow.py --exploratory \
  --pilot <B> --sample .s2-replay/evolve/samples/15866.yaml
node scripts/verify_panel_desktop.js --profile desktop
```
