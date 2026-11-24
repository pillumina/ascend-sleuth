---
name: self-evolve
description: >
  全库自演进归类轮：聚合 trace、回放、指标与信号记录，把发现归成可做的事，并给出一份
  用户能直接选的清单——每条写清现在能不能做、缺什么、入口与成本。用户说「看看全库有
  什么可改进 / 做一轮深度自演进」时用，由用户输入 `/skill:self-evolve` 触发。
disable-model-invocation: true
---

# Self-Evolve（归类与选择轮）

> **本地执行说明**：本 skill 标记 `disable-model-invocation`（深度轮只由用户显式发起）——skill 工具加载会报 "not available for model invocation"，这是预期。用户明确说「看看全库有什么可改进 / 做一轮深度自演进」时，agent 直接 `read` 本文件按流程走即可；或用户输入 `/skill:self-evolve` 直接触发。

## 这是什么

这轮做三件事：读记录、把发现归成可做的事、给用户一份能直接选的清单。它不诊断、不评估、不跑实验、不改知识。

输出不是「发现清单」，是「选择清单」：用户看完要知道「现在做不做、做了会怎样、要花什么」。

一条可做的事如果用户看完还要问「那能跑吗、缺什么」，这条就没写完。

## 何时触发

只在用户显式说「看看全库有什么可改进 / 做一轮深度自演进」时执行。普通内容流程收尾走 `evolve-check`，不进入本 skill。

## 第 0 步：读部署角色

```bash
python3 scripts/evolve_mode.py --json
```

- `maintainer`：可做观测、归类、生成受控实验候选；
- `signal-only`：只读本地信号与执行记录，不生成受控实验候选；无信号时报 role 与 0 条并停；
- `off`：不做深度轮，报告一行跳过。

## 第 1 步：聚合信号

按目标选数据源，不重扫全库：

| 信号源 | 命令 | 看什么 |
|---|---|---|
| 维护者入口 | `python3 scripts/evolve.py run` | 样本队列的下一步：候选样本待复核、终判样本未跑、缺结论 |
| 演进体检 | `python3 scripts/evolution_health.py --check` | 判据未执行、外部验证停滞、失效卡 |
| 信号记录 | `python3 scripts/evolve_signals.py list` | 跨轮重复出现、未归类的信号 |
| 执行记录 | `python3 scripts/tail_exec_log.py --n 20` | 反复动作、miss、流程摩擦 |
| 归因聚合 | `python3 scripts/component_tally.py` | 失败簇集中在哪个组件 |
| 外部回放缺口 | `python3 scripts/s2_replay.py --todo` | 未回放的外部 issue、未覆盖的样本族 |
| 容量/健康 | `python3 scripts/metrics_health.py --json` | 结构治理项 |
| 候选溢出 | `python3 scripts/capacity_health.py --json` | 各格候选溢出率（>20% 触发拆分评估） |
| 指标趋势 | `metrics/timeline.yaml` | 命中率、回滚、成本漂移 |

`evolve run` 给的是流水线的下一步，不是实验结论；把它翻译成用户能选的动作。

需要独立视角时，可以让 subagent 只读信号记录与候选样本队列做一次归类，避免同上下文盲区。

## 第 2 步：归类

每条信号只归入一类：

| 类别 | 判定 | 下一步 |
|---|---|---|
| 确定性 bug | 可复现、结果可机械判定 | 复现 + 回归测试 → PR |
| 内容缺口 | 缺 case / reference / 词条 / 样本 | 内容 skill 或补样本 |
| 行为质量 | 结果没有唯一标准答案，需要样本对照 | 对照实验 |
| 高风险授权 | 规范文档、评估协议、权限、自动合并边界 | 轻量授权记录卡（EV 卡） |
| 观察 | 只有现象，没有可执行方案 | 留记录，不升级 |

归类结论写回记录：

```bash
python3 scripts/evolve_signals.py mark <id> --status triaged|dropped|promoted \
  --note "一句话说明为什么"
```

归类的目的是选入口。行为类可做的事还要再算一次就绪度（第 3 步），不能只写「需要实验」。

## 第 3 步：把可做的事写成可执行选项

每条可做的事要能让用户判断做不做，至少写清六件事：

- **做什么**：一句话，用用户能懂的说法；
- **为什么现在做**：数值、现象或缺口；
- **做完会看到什么**：结果，不是过程；
- **现在能不能做**：能，或缺什么；
- **入口**：一条命令，或「我来跑」；
- **成本与风险**：时间、会不会改工作区、失败后怎么退。

### 行为类可做的事先算实验就绪度

三条入口，别混：

| 入口 | 用什么样本 | 现在能跑的条件 | 命令 |
|---|---|---|---|
| 固定样本回放 | 外部 issue 回放集（S2 校准集）或基准样本（golden） | 有现成 issue 或夹具，不需要提案与判分器 | S2：`scripts/s2_replay.py`、`scripts/eval_arena.py`；golden：`scripts/replay_golden.py`（账本 `scripts/eval_scorecard.py`） |
| 终判/回归 | 终判样本（core test / regression） | 样本已抽好 | `evolve.py stage plan` → `run` → `judge` → `report` |
| 行为对照 | 内部诊断样本（active/field evaluation） | 有复核过的样本、提案、执行器、判分器 | `evolve.py experiment request` → 写 draft → `evolve.py experiment flow --proposal <draft.json>` |

就绪度检查（缺一项就写进「要先补东西」，不要放「现在就能做」）：

- **样本**：`evolve.py run` 看候选样本、内部诊断样本、终判样本的计数；候选样本不等于可用样本，缺答案或未复核的要先补、先审；
- **提案**：`experiment request` 的输出里有没有候选改动；没有候选改动的提案会被实验流程拒绝；
- **执行器**（runner）：外部命令，或会话内的 subagent；
- **判分器**（judge）：已校准的判分器，或 `judge.subagent`；
- **结论强度**：小池只能记「证据不足」，不能当通过。

固定样本回放不需要提案与判分器：一条 issue 跑一次诊断、写结果、汇总评分。这条通道现在能不能跑，只看有没有待回放的 issue。

要让外部 issue 进行为对照，先 `evolve.py sample import-s2 --source eval/s2/<文件>.yaml` 导进候选队列，复核成 active 后再走行为对照。

选错入口会白跑：先看要回答的是「没改坏」「更好」还是「终判」，再对到上表那一行。

## 第 4 步：给用户一份选择清单

给用户看的是一份能直接选的选择清单。模板：

```text
这轮看到 <N> 条线索，归成 <X> 条可做的事、<Y> 条观察。建议先选 <编号>。

现在就能做
1. <做什么>
   为什么：<数值或现象>
   做完看到：<结果>
   入口：<我来跑 / 命令>
   成本与风险：<...>

2. ...

要先补东西
3. <做什么>
   为什么：<数值或现象>
   现在缺：<评测样本 / 改动方案（提案）/ 执行器 / 判分器>
   补法：<命令或动作>
   补完看到：<结果>
   补完入口：<入口>
   成本与风险：<补要多久 / 会不会改工作区 / 失败后怎么退>

观察
- <现象>：<为什么现在不升级>

要你选：回复编号；说「都不做」就停，本轮不改任何东西。
```

写法要求（这条只管给用户的那份清单；本文件其余部分是 agent 执行用的）：

- 开头一句话给结论，不写「本轮观测」「归类」这类内部标题；
- 每条只写用户要判断的信息：做什么、为什么、现在能不能、要花什么、做完看到什么；
- 「现在就能做」只放能跑的；缺东西的放「要先补东西」，并写清缺哪项；
- 不用内部代号；必须用时第一次给中文含义；
- 必译的词：外部 issue 回放集（S2 校准集）、内部诊断样本（field）、终判样本（core test）、改动方案（提案）、执行器（runner）、判分器（judge）、授权记录卡（EV 卡）；
- 给用户的清单里不写「分诊」「候选队列」「measure」这些词；
- 用「归类」「可做的事」「怎么验证」；
- 不拿「建议先做」代替「现在能不能做」；两者是两件事，都要写；
- 没有可做的事就写「本轮无动作」并停；不凑数；
- 只给一条推荐，附一句理由；其余让用户选。

## 用户选完以后

1. **确定性 bug** → 复现步骤 + 回归测试 + PR；
2. **内容缺口** → 内容 skill（补 case / reference / 样本）；
3. **行为质量** → 按第 3 步选中的入口跑实验；缺东西的先补样本或提案；
4. **高风险** → 授权记录卡（EV 卡）+ 人审。

深度轮自己不执行这些动作。用户回复编号就是触发；没有回复就停。

## 显式实验路径

只有用户选中行为类可做的事后才执行，不自动运行。

**固定样本回放**（现在就能跑的那类）：

```bash
# 在部署的主检出里跑；worktree 里的 .s2-replay 主检出的 --collect 看不到
python3 scripts/s2_replay.py --todo          # 列待回放 issue
# 逐条按 diagnose 流程跑，结论写主检出的 .s2-replay/<issue>.result.yaml（worktree 里用绝对路径）
python3 scripts/s2_replay.py --collect       # 汇总评分
python3 scripts/eval_arena.py --build-pool   # 需要出分与门控时再接 --stats / --gate
```

**行为对照**（需要提案、执行器、判分器）：

```bash
# 1. 拿提案请求与输出 schema
python3 scripts/evolve.py experiment request --component <组件> --target skill

# 2. agent 按 schema 写 draft，直接交给 flow（flow 会落提案并打印提案 id）
python3 scripts/evolve.py experiment flow \
  --proposal <draft.json> --samples <样本文件...> \
  --judge <judge.json> --runner-command '<JSON argv>' --output <目录>

# 3. 读结论（用 flow 打印的提案 id）
python3 scripts/evolve.py experiment show --proposal <提案 id>
```

规则：

- 没有复核过的样本、执行器、判分器，不进入实验；先补，不跑空实验；
- 小池只能记「证据不足」（`insufficient`），不能写成通过；
- 只有接受（`accept`）才进入 PR；拒绝（`reject`）或证据不足（`insufficient`）保留结论，不再另写一份记录；
- `experiment propose --draft` 只把提案记进实验存储，不是 flow 的前置；flow 自己落提案；
- 实验用哪个 stage 组合由 `evolution.pipeline` 预设决定，不手工改 stage；
- 固定样本回放不需要提案；行为对照才需要。

## 高风险授权卡（EV 卡）

EV 卡只用于授权与历史，不是行为改动的默认前置：

- 规范文档、评估协议、权限、自动合并边界等高风险改动；
- 需要人明确授权，或需要留授权/回滚记录；
- 不替代受控实验，也不替代 PR；
- 历史卡只读，不再作为新行为改动的全量门；
- 卡标 `validated` 前必须跑一次 `python3 scripts/ev_measure.py <卡号> --run --record`，通过写进 `measure_evidence`。

## 边界

- 深度轮不自动执行实验，不自动产卡，不写实验结论；结论只由实验的 decision 产出；
- 不把内容缺口和行为质量混成同一类；
- 不为「有信号」强行造方案；
- 不越过部署角色；
- 不把 EV 卡当成实验提案或实验；
- 每条可做的事都要带就绪度；只给「建议顺序」而不给可执行入口，这份选择清单没写完；
- 不要把能现在跑的固定样本回放写成「先补样本」，也不要把没就绪的行为实验写成「现在能跑」。
