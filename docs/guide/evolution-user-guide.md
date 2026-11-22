# 自演进用户指南

本文写给使用这套系统的工程师：你用什么语言下目标、系统在什么时候只记录、什么时候会变重、怎么进入 RSI、怎么读结果。机制设计与判定细节见 [rsi-mechanism.md](../mechanism/rsi-mechanism.md)、[evaluation.md](../mechanism/evaluation.md) 与 [evolution-config.md](../mechanism/evolution-config.md)。

## 1 先看边界

日常内容流程（诊断、补 case、reference 沉淀、issue 拉取、groom）收尾只做**信号记录**：

```text
内容流程完成
  → evolve-check 扫一遍现场
  → 有信号写 proposals/signals/
  → 报告一行“信号 N 条 / 无信号”
  → 结束
```

不产 EV 卡，不跑 RSI 实验，不跑验证门。这是默认行为，不需要你额外说“别跑重的”。

真正会改系统行为的三条路是分开的：

| 改动性质 | 谁来做 | 何时做 |
|---|---|---|
| 确定性代码 bug | 回归测试 + PR | 现场发现即可修 |
| 内容缺口 | to-reference / to-postmortem / issue-ingest | 内容流程 |
| 行为质量（无确定 oracle） | RSI proposal → experiment → decision → PR | 你显式发起 |
| 高风险授权 | 轻量 EV 卡 | 人审触发 |

## 2 日常：只记信号

你下内容目标后，系统在收尾执行 `evolve-check`，只做三件事：

1. 读部署角色；
2. 对照触发条件扫本轮现场；
3. 把信号写进 `proposals/signals/`。

信号是观察，不是方案：

```text
signal: mechanism-gap
target: skills/diagnose/SKILL.md
evidence: 本轮两次走同一兜底路径
trajectory: trace / 命令 / 产出 id
occurrences: 2
```

没有出处不写；没有方案不写预测；`signal-only` 与 `maintainer` 在收尾都只记信号。

查看与导出：

```bash
python3 scripts/evolve_signals.py list
python3 scripts/evolve_signals.py export
python3 scripts/evolve_signals.py mark <id> --status triaged|dropped|promoted --note "..."
```

## 3 深度轮：只分诊，不执行

你说“跑一轮自演进 / 看看有什么可改进的”，进入 `self-evolve`。深度轮做观测与分诊，不自动跑实验：

```text
聚合信号
  → 分诊：确定性 bug / 内容缺口 / 行为候选 / 高风险 / 观察
  → 输出候选队列
  → 停，等你选择
```

行为候选至少写清：

```text
source_signal
target_component
hypothesis
measure（命令 + 期望，或“暂不可度量”）
risk
samples（够不够）
```

样本不够时先补样本，不跑空实验。

## 4 显式 RSI

只有你选中行为候选后，才进入重型流程：

```bash
# 1. 生成 proposal
python3 scripts/evolve.py experiment request --component <组件> --target skill

# 2. 准备真实样本与 judge，跑 pilot
python3 scripts/evolve.py experiment flow \
  --proposal <proposal.json> --samples <samples.json> \
  --judge <judge.json> --runner-command "<命令>" --output <目录>

# 3. 读结论
python3 scripts/evolve.py experiment show --proposal <id>
```

规则：

- 没有真实样本、runner、judge，不进入 RSI；
- 小池只能 `insufficient`，不得用 `weak_accept` 冒充通过；
- `accept` 才进入 PR；`reject` / `insufficient` 保留结论；
- stage 组合由 `evolution.pipeline` 预设决定，不手工改 stage；
- 实验记录写 RSIStore，不写进 PR 数据。

## 5 EV 卡只用于高风险

EV 卡不是行为改动的默认前置，也不是实验结果的别名。它只用于：

- 规范文档、评估协议、权限、自动合并边界；
- 需要人明确授权或留授权/回滚记录的高风险改动。

EV 卡不替代 RSI，也不替代 PR。历史 EV 卡只读。

## 6 部署角色

```yaml
# sleuth.config.yaml
evolution:
  role: maintainer   # maintainer | signal-only | off
```

| role | 收尾 | 深度轮 | RSI |
|---|---|---|---|
| `maintainer` | 记信号 | 可分诊行为候选 | 可显式跑 |
| `signal-only` | 记信号 | 只读本地观察 | 不跑 |
| `off` | 跳过记录 | 不跑 | 不跑 |

切换：

```bash
python3 scripts/evolve_mode.py --set signal-only
```

写的是仓库根 `sleuth.config.yaml`；提交后对该仓所有检出生效。

## 7 干预与回滚

- 想停：让 agent 停止当前轮；已写信号保留。
- 想换方向：改本轮目标，已分诊的候选可标 `dropped`。
- 想回滚：代码改动走 revert；RSI 结论保留原 decision，不篡改历史。
- 想关演进：设 `role: off`，只留跳过记录。

## 8 常见误解

- “收尾没产卡 = 演进失败”：不是，收尾只记录信号。
- “深度轮会自动改系统”：不会，只给候选。
- “行为改动必须先产 EV 卡”：不是，行为质量走 RSI；EV 卡只用于高风险授权。
- “EV 卡就是 RSI 结论”：不是，EV 卡是授权/历史记录，实验结论在 RSIStore。
