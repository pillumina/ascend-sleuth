---
name: evolve-drive
description: >
  驱动自演进实验循环：按流水线预设的 stage 组合，在「取动作 → subagent 执行 →
  回写状态」之间循环，直到预算耗尽或达到停止条件。用户说「跑一轮自演进实验 /
  用 GEPA 跑这个 skill 的实验 / 继续上一轮实验」时用。需要能起 subagent 的会话。
---

# RSI-Drive（实验循环驱动器）

本 skill 是算法无关的执行循环：它不认识具体算法，只认识 stage 组合与动作分派。
算法的差异全部在流水线预设（`config/rsi/pipelines.yaml`）与状态机实现里。

## 前置

1. 读流水线预设确认 stage 组合。预设名来自实验命令的 `--pipeline <名>`（主入口，
   预设清单在 `config/rsi/pipelines.yaml`）；部署级默认是 sleuth.config.yaml 的
   `evolution.pipeline`，profile 可再覆盖，三者优先级依次升高：

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "scripts")
import sleuth_config as SC
print(SC.pipeline_for(SC.load_config(), "gepa")["stages"])
PY
```

六个 stage 点的算法名以 `scripts/evolve/stages.py` 的 `STAGES` 为准，正文不复述。
`select_candidate` / `propose` 这类 `manual` / `library` 标注的 stage，其逻辑在
驱动命令组的状态机内部执行，不产生 subagent 调用；subagent 只用于下面循环里
`evaluate` / `reflect` 两种动作。

2. 状态目录锚到主检出的运行时件，用绝对路径：

```bash
STATE=$(python3 scripts/shared_dir.py evolve | tail -1)/<实验名>/state.json
```

`evolve` 锚在主检出的 `.s2-replay/evolve/`，所有 worktree 共读共写；`tail -1`
取路径行——命令输出含说明行，直接用整段输出会带进换行与说明文字。

## 循环

每轮做三步，直到动作是停止信号：

1. **取动作**：

```bash
python3 scripts/evolve.py gepa next --state "$STATE"
```

返回一个 JSON 动作。按 `kind` 分派：

- `evaluate`：对待评估的候选 × 样本，起 task subagent 按样本输入运行候选文本，
  再起 judge subagent 按评分标准打分（0 到 1）。分数与失败反馈拿到后回写。
- `reflect`：先取提案契约，再起 reflect subagent：

```bash
python3 scripts/evolve.py experiment request --target <target_kind> \
  --component <区域名>
```

返回里的 `prompt` 字段含该 target 的允许/禁止路径与行为规则（`prompt_rules`），
与动作里的 `failures` 一起给 reflect subagent——变异文本受同一份改动边界约束，
不是只看失败反馈自由发挥。产出变异后的候选文本，写入文件后回写。
- `stop`：循环结束，跳到收尾。
- 其他 kind：**不要猜**。向用户报告动作内容并停下——未知动作说明驱动协议
  与 skill 版本不匹配，硬跑会写出状态机不认的记录。

2. **执行 subagent**：起 subagent 时只给它完成该动作所需的最小材料——task
   只看样本输入，judge 只看评分标准与输出，reflect 只看失败反馈。不把整份
   状态或历史轮次塞进 subagent。

3. **回写**：

```bash
python3 scripts/evolve.py gepa apply --state "$STATE" --kind evaluate \
  --candidate-id <id> --sample-id <sid> --score <0..1> --feedback "<失败反馈>"
python3 scripts/evolve.py gepa apply --state "$STATE" --kind reflect \
  --skill-file <变异后的候选文本文件>
```

预算（剩余评估次数）以 `next` 返回与 `apply` 输出的 `calls` 字段为准，不在
对话里自记。

## 新实验的建立

```bash
python3 scripts/evolve.py gepa init --state "$STATE" \
  --seed-file <seed 可变异区文本> --samples <s1,s2,...> \
  --max-metric-calls <预算> --population <候选上限>
```

驱动命令组按算法入口区分：本版走 `evolve gepa` 命令组（GEPA 是第一个实例）。
第二个算法接入时新增自己的命令组，并在本节增补「预设名 → 命令组」映射；
分派规则与收尾流程不变。

断点续跑：状态全在 `$STATE`，新会话直接从「取动作」一步继续，不需要回放历史。

## 收尾

动作是 `stop` 后，取结果并向用户报告：

```bash
python3 scripts/evolve.py gepa result --state "$STATE"
```

报告里写清：最优候选与得分、Pareto 前沿、用了多少预算、停在哪条原因上。
候选文本只是实验产物，合入走正常的知识 PR 流程，本 skill 不改知识文件。
