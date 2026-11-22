---
name: self-evolve
description: >
  用户显式发起的全库自演进深度轮：聚合 trace、replay、指标、信号台账，分诊出
  内容缺口、确定性 bug、流程/行为质量候选与高风险授权需求。深度轮只做观测与分诊，
  不自动跑 RSI 实验、不自动产 EV 卡；行为质量改动由用户选中候选后显式进入
  RSI proposal → experiment → decision → PR。
---

# Self-Evolve（深度分诊轮）

## 何时触发

只在用户显式说“看看全库有什么可改进 / 做一轮深度自演进”时执行。普通内容流程收尾走 `evolve-check`，不进入本 skill。

## 第 0 步：读部署角色

```bash
python3 scripts/evolve_mode.py --json
```

- `maintainer`：可做观测、分诊、生成 RSI 候选；
- `signal-only`：只读本地信号与执行记录，不生成 RSI 候选；
- `off`：不做深度轮，报告一行跳过。

## 第 1 步：聚合信号

按对齐目标选数据源，不重扫全库：

| 信号源 | 命令 | 看什么 |
|---|---|---|
| 信号台账 | `python3 scripts/evolve_signals.py list` | 跨轮重复出现、未分诊的信号 |
| 执行记录 | `python3 scripts/tail_exec_log.py --n 20` | 反复动作、miss、流程摩擦 |
| 归因聚合 | `python3 scripts/component_tally.py` | 失败簇集中在哪个组件 |
| replay 缺口 | `python3 scripts/s2_replay.py --todo` | 未覆盖的样本族 |
| 容量/健康 | `python3 scripts/metrics_health.py --json` | 结构治理项 |
| 指标趋势 | `metrics/timeline.yaml` | 命中率、回滚、成本漂移 |

需要独立视角时，可以让 subagent 只读信号台账与本仓候选队列做一次分诊，避免同上下文盲区。

## 第 2 步：分诊

每条信号只归入一类：

| 类别 | 判定 | 输出 |
|---|---|---|
| 确定性 bug | 可复现、有确定 oracle | 回归测试 + PR；不产 EV 卡、不跑 RSI |
| 内容缺口 | 缺 case / reference / 词条 | 内容 skill 的输入 |
| 行为质量 | 无确定 oracle，需要样本对照 | RSI 候选（仅候选，不执行） |
| 高风险授权 | 规范文档、评估协议、权限、自动合并边界 | 轻量 EV 卡，作为授权记录 |
| 观察 | 只有现象，没有可执行方案 | 留台账，不升级 |

分诊结论写回台账：

```bash
python3 scripts/evolve_signals.py mark <id> --status triaged|dropped|promoted \
  --note "一句话说明为什么"
```

## 第 3 步：生成候选队列

深度轮只生产候选，不生产结论。

- **确定性 bug**：写清复现步骤、最小回归测试、影响面；可直接进入修复 PR。
- **内容缺口**：写明缺哪类知识、建议走哪个内容 skill。
- **行为质量**：写 RSI 候选，至少包含：
  - `source_signal`：来自哪条信号；
  - `target_component`：要改的组件；
  - `hypothesis`：改什么、为什么可能有效；
  - `measure`：怎么验证，命令 + 期望，或如实写“暂不可度量”；
  - `risk`：失败/回滚代价；
  - `samples`：现有样本是否足够；不足时先补样本，不跑空实验。
- **高风险**：写清为什么必须授权、授权人是谁、回滚路径。

候选写入 `proposals/` 或用户指定的评审目录，不写 `.s2-replay/` 的运行时记录。

## 第 4 步：报告与选择

报告给用户：

```text
本轮观测：N 条信号
分诊：确定性 bug A / 内容缺口 B / 行为候选 C / 高风险 D / 观察 E
建议先做：...
未执行：RSI 实验、EV 卡、PR（等用户选定）
```

由用户选择是否进入：

1. **确定性 bug** → 回归测试 + PR；
2. **内容缺口** → 内容 skill；
3. **行为质量** → 显式 RSI；
4. **高风险** → 轻量 EV 卡 + 人审。

## 显式 RSI 路径

只有用户选中行为候选后才执行，不自动运行：

```bash
# 1. 生成 proposal 草稿
python3 scripts/evolve.py experiment request --component <组件> --target skill

# 2. 准备候选与 judge，跑真实 pilot
python3 scripts/evolve.py experiment flow \
  --proposal <proposal.json> --samples <samples.json> \
  --judge <judge.json> --runner-command "<命令>" --output <目录>

# 3. 读结论
python3 scripts/evolve.py experiment show --proposal <id>
```

规则：

- 没有真实样本、runner、judge，不进入 RSI；
- 小池只能 `insufficient`，不得用 `weak_accept` 冒充通过；
- accept 才进入 PR；reject / insufficient 保留结论，不补仪式记录；
- 实验用哪个 stage 组合由 `evolution.pipeline` 预设决定，不手工改 stage。

## 高风险 EV 卡

EV 卡只用于授权与历史，不是行为改动的默认前置：

- 规范文档、评估协议、权限、自动合并边界等高风险改动；
- 需要人明确授权，或需要留授权/回滚记录；
- 不替代 RSI 实验，也不替代 PR；
- 历史 EV 卡只读，不再作为新行为改动的全量门。

## 边界

- 深度轮不自动执行 RSI，不自动产 EV 卡；
- 不把内容缺口和行为质量混成同一类；
- 不为“有信号”强行造方案；
- 不越过部署角色；
- 不把 EV 卡当成 RSI 的 proposal 或 experiment。
