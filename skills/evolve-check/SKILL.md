---
name: evolve-check
description: >
  内容流程收尾的轻量信号检查。用户完成补 case / reference 沉淀 / 诊断 / 拉取 / replay
  后，本协议只做一件事：对照触发条件扫一遍现场，把值得后续处理的信号写进
  proposals/signals/ 台账。不产 EV 卡、不跑 RSI 实验、不跑验证门；行为质量改动需要
  显式 RSI，深度分诊由用户显式发起的 /skill:self-evolve 承担。
---

# Evolve-Check（收尾信号检查）

## 定位

`evolve-check` 是**轻量收尾钩子**，不是自演进执行轮。内容流程完成主体目标后、出最终报告前执行一次；无信号即止。

它只负责记录，不负责决定。EV 卡、RSI 提案、实验、判定、PR 都不在这里自动发生。

## 第 0 步：读部署角色

```bash
python3 scripts/evolve_mode.py --json
# → {"role": "maintainer" | "signal-only" | "off", "source": "..."}
```

| role | 本协议行为 |
|---|---|
| `maintainer` | 扫信号并写台账；不产 EV 卡、不跑 RSI |
| `signal-only` | 扫信号并写台账 |
| `off` | 只写一行跳过记录，不扫信号 |

配置写坏时脚本退出 2：把错误原文交给用户，不要自行选一档继续。

## 第 1 步：读取本轮现场

优先读统一执行记录，不重扫全库：

```bash
python3 scripts/tail_exec_log.py
```

看本轮新增内容、miss、重复动作、流程摩擦、执行错。无记录时按“无执行记录，基于现场判断”如实标注，不假装有数据。

## 第 2 步：扫描触发条件

命中才继续；不命中直接写“无演进信号”。

| # | 现场信号 | 后续归属 |
|---|---|---|
| 同族归纳 | 同族 case 已沉淀到足够归纳 reference | 内容：走 to-reference |
| 反复 miss | diagnose / replay 反复 miss 同一族 | 内容：补 case；若指向路由/加载行为，记行为信号 |
| 重复动作 | 同一手动动作重复 ≥2 次 | 流程：可固化脚本/skill |
| 执行错 | 执行错反复出现且无归属组件 | 流程：归因到 skill/路由 |
| 新覆盖 | 新数据源 / 新错误码 / 新 issue 类型首次出现 | 内容：扩 reference 家族 |
| 容量越界 | 容量或健康指标越界 | 结构：拆分评估 |
| 可复用链路 | 本轮跑通可复用链路 | 流程：沉淀候选 |
| 体验质量 | 体验/质量问题（问得多、结论难读、交互摩擦） | 体验：累积到 skill-review |
| 人的反馈 | 人给的反馈反复出现 | 判断偏差：改结构或流程 |
| 自审缺口 | 自审发现机制/设计/可观测性缺口 | 机制：候选修正 |
| 审计腐化 | 审计发现口径漂移、断言过期、数据反常 | 存量腐化：修正 |
| 源码取用失败 | 同一源码仓取用失败 ≥2 次 | 覆盖：补 source-catalog |

触发条件表是扫描清单，不是卡类型；命中后只记录信号，不在本协议里决定实现方案。

## 第 3 步：写信号台账

统一走入口脚本，不直接调 `ev_proposal.py --new`：

```bash
python3 scripts/evolve_intake.py record \
  --signal mechanism-gap --signal-text "机制缺口的一句话" \
  --target "<仓库内路径或组件名>" \
  --evidence "<本轮可复核的现象>" \
  --trajectory "<trace / 产出 id / 命令结果>" \
  --source <上游 skill>
```

- 结果写 `proposals/signals/`，同内容自动累加 `occurrences`。
- 不写预测，不写未跑过的验证。
- `trajectory` 必须能回放；没有出处不写信号。
- `off` 下不落盘，只写跳过记录。

## 第 4 步：收尾报告

报告只写四行：

```text
role: maintainer / signal-only / off（来源：...）
信号：<N> 条（或“无”）
去向：内容 / 确定性 bug / 行为质量 / 高风险 / 观察
未做：EV 卡、RSI 实验、验证门（按目标态不自动执行）
```

## 去向矩阵（给下一棒看，不在本协议执行）

| 信号性质 | 下一棒 | 入口 |
|---|---|---|
| 确定性代码 bug | 回归测试 + PR | 直接修，不产 EV 卡、不跑 RSI |
| 内容缺口 | to-reference / to-postmortem / issue-ingest | 内容 skill |
| 行为质量 | RSI proposal → experiment → decision → PR | 用户显式发起，见 /skill:self-evolve |
| 高风险改动 | 轻量 EV 卡作为授权记录 | 人审触发，不替代 RSI/PR |
| 体验/质量反馈 | skill-review 的输入 | 累积观察 |

## 不做什么

- 不在收尾时产 EV 卡；
- 不自动跑 RSI 实验、不自动判定；
- 不把信号当方案，不写预测；
- 不因“没有产卡”而认为演进失败——本协议的目标就是只记录。
