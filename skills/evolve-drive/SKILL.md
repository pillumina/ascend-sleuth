---
name: evolve-drive
description: >
  驱动自演进搜索循环、多臂组合实验或留一效用审计：读取搜索循环注册表与实验描述
  文件，在「取动作 → subagent 执行 → 回写状态」之间推进，直到预算耗尽或达到停止
  条件。用户说「跑一轮自演进实验 / 用 GEPA 或 SkillOpt 跑这个 skill 的实验 /
  继续上一轮实验 / 跑一次多臂对照 / 审计知识冗余 / 哪些 case 或条目可以删」时用。
  需要能起 subagent 的会话。
---

# RSI-Drive（搜索循环与组合实验驱动）

本 skill 不按算法写分支。它读取搜索循环注册表和实验描述文件（spec），把搜索循环产出的动作分派给 subagent，再执行结果回写到状态文件。

算法的差异在 `scripts/evolve/loops/` 与 `config/rsi/pipelines.yaml`。流水线预设只决定六个节点（归因、选点、选候选、提案、judge、门禁）；搜索循环决定批次、epoch、候选池与审计怎么走。

## 前置

1. 查看搜索循环与它要求的样本角色、动作：

```bash
python3 scripts/evolve.py loop list
python3 scripts/evolve.py loop show --loop <搜索循环名>
```

当前登记 GEPA、LOO（留一审计）、baseline（对照）与 SkillOpt（快更新）。需要节点组合时另看 `python3 scripts/sleuth_config.py --pipelines`；搜索循环与预设互不替代。
未给 `--loop` 或 `--recipe` 时读 `evolution.policy.experiment.recipe`；recipe 的 `params` 与 `budget` 作为默认，CLI 或 spec 的显式值覆盖。参数与说明在 `config/rsi/recipes/<名>.yaml`。

2. 状态与决策记录锚到主检出的运行时件，使用绝对路径：

```bash
STATE=$(python3 scripts/shared_dir.py evolve | tail -1)/<实验名>/state.json
DECISIONS=$(python3 scripts/shared_dir.py evolve | tail -1)/<实验名>/decisions.jsonl
```

`tail -1` 取路径行；命令输出前面还有说明行。

## 单搜索循环

建立状态：

```bash
python3 scripts/evolve.py loop init --loop <搜索循环名> --state "$STATE" \
  --config <配置.yaml> --records "$DECISIONS"
```

配置是 YAML：`seed_text` 或 `seed_file`；`data` 按搜索循环要求的样本角色给 id 列表；`params` 放搜索循环参数；`target_runs` 与 `worker_calls` 是预算。角色要求随循环不同：GEPA 与 baseline 要 `eval`，SkillOpt 要 `train` 与 `dev`，LOO 要 `audit`。

每轮执行三步。

1. 取动作：

```bash
python3 scripts/evolve.py loop next --state "$STATE"
```

2. 按动作的 `actor` 分派 subagent。

- `target`：按样本输入运行动作里的 `skill`，按评分标准打分，回写 `score` 与 `feedback`。
  - GEPA：`evaluate` 一次一个样本。
  - SkillOpt：`evaluate` 带 `phase`；`train` 用当前批次，`dev` 用全量验证集。
  - LOO：`evaluate` 带 `unit_id` 与 `variant`；按动作原值回写。
- `worker`：按动作给的材料写提案。GEPA 的 `reflect` 用失败样例；SkillOpt 的 `reflect` 用 `group`（成功或失败）与 `items`，`merge` 用 `proposals`。需要 target 边界时先跑 `experiment request --target <t> --component <区>`，把 prompt 规则一并交给 subagent。只给完成该动作所需的材料，不要给整份状态或历史。

3. 回写：

```bash
python3 scripts/evolve.py loop apply --state "$STATE" --kind evaluate \
  --score <0..1> --feedback "<失败反馈>"
python3 scripts/evolve.py loop apply --state "$STATE" --kind reflect \
  --text-file <提案文本>
python3 scripts/evolve.py loop apply --state "$STATE" --kind merge \
  --text-file <合并后的文本>
```

动作是 `stop` 时结束，读取结果：

```bash
python3 scripts/evolve.py loop result --state "$STATE"
```

报告写明最优候选与得分、接受与拒绝次数、目标执行与 worker 调用次数、停止原因。SkillOpt 的停止原因可能是 `complete`、`target_runs_budget`、`worker_calls_budget` 或 `max_steps`。

## 多臂与顺序链

一个 spec 描述多个臂或一条链：

```yaml
id: <实验名>
target: skill
component: <可变异区>
composition: parallel        # parallel | sequential
primary_arm: <主臂名>         # 进入最终判定的臂；多臂比较时预先声明，顺序链不填
eval_role: dev               # 每臂结束后共同复评的样本角色
seed_text: <seed 文本>
samples:
  train: [<训练样本 id>]
  dev: [<验证样本 id>]
  eval: [<评测样本 id>]
arms:
  - name: <臂名>
    loop: skillopt
    roles: {train: train, dev: dev}
    params: {epochs: 2, batch_size: 3}
    budget: {target_runs: 30, worker_calls: 12}
```

```bash
python3 scripts/evolve.py experiment arms init --spec <spec.yaml> --state "$STATE"
python3 scripts/evolve.py experiment arms next --state "$STATE"
python3 scripts/evolve.py experiment arms apply --state "$STATE" --kind evaluate \
  --score <0..1>
python3 scripts/evolve.py experiment arms result --state "$STATE"
```

`next` 通常返回 `{arm, loop, action}`，按 `action.actor` 分派；实验终止时返回 `{"kind": "stop"}`，先判 `kind` 再取 `action`。多臂按顺序执行，每臂有独立的目标执行预算；一臂结束后在 `eval_role` 上复评一次，得到可横向比较的读数。顺序链把前一臂的最优快照作文本 seed 交给下一臂。

`primary_arm` 在运行前声明，不在测试集上选。臂间均分差只作读数；合入前把主臂候选生成提案，走 `experiment flow` 或 pilot 的配对门出 `Conclusion`。多臂都在同一测试集上比较会累积假接受，不能用 `result` 的均分替代配对结论。

## 旧命令组

`gepa` 与 `loo` 两个命令组保留兼容，读旧格式状态文件，协议与上面相同。新实验使用 `loop` 与 `experiment arms`；旧命令组不再新增能力。

## 收尾

搜索循环的产物是候选文本或快照，不是合入。合入走正常知识 PR；审计循环的收缩队列只输出建议。报告给出状态路径、决策记录路径、每臂读数与停止原因，供下一轮或评审复核。

断点续跑：状态全在 `$STATE`（单搜索循环另有动作文件），新会话直接从取动作继续。
