# 搜索算法 recipe

本文写给要换演进算法或调算法参数的工程师。recipe 是一个命名的完整包：搜索循环、参数、预算和样本角色都写在一个文件里。用户只在 `sleuth.config.yaml` 选名字；要调参数或派生新算法，改 recipe 文件。

## 1 选哪一个

| recipe | 搜索循环 | 什么时候用 | 需要的样本角色 | 默认预算 |
|---|---|---|---|---|
| `control` | baseline | 先拿基线读数，或核对样本与 judge 能否跑通 | `eval` | 4 次目标执行 |
| `gepa-default` | GEPA | 只有一组评估样本，先跑候选池搜索 | `eval` | 12 次目标执行 |
| `skillopt-fast` | SkillOpt 快更新 | 有 train/dev 划分，目标是稳定小步提升 | `train` 与 `dev` | 30 次目标执行、12 次 worker 调用 |

recipe 只管搜索循环与参数。六点节点组合仍由 `config/rsi/pipelines.yaml` 的预设决定，两者不互相替代。

## 2 怎么选

在 `sleuth.config.yaml` 改一行：

```yaml
evolution:
  policy:
    experiment:
      recipe: skillopt-fast
```

`recipe` 的值等于 `config/rsi/recipes/` 下的文件名去掉 `.yaml`。不用 `recipe` 时，才用 `experiment.loop` 直接指定算法。

实验 spec 里也可以按臂选：

```yaml
arms:
  - name: candidate
    recipe: skillopt-fast
  - name: control
    recipe: control
```

实验 spec 存在时，`arms[].recipe` 优先于 `experiment.recipe`。

## 3 调参数

参数写在你选中的 recipe 文件里，注释就在参数旁边：

```text
config/rsi/recipes/skillopt-fast.yaml
```

例如把 `batch_size` 从 4 调到 2，直接改这个文件。不要改 `sleuth.config.yaml` 来放算法参数，那个文件只负责选 recipe。

要临时覆盖、不想改 recipe，可以在实验 spec 的臂里写同名字段：

```yaml
arms:
  - name: candidate
    recipe: skillopt-fast
    params: {batch_size: 2}
    budget: {target_runs: 20}
```

`params` 与 `budget` 按字段合并，spec 的显式值优先；recipe 里没写的字段继续用循环默认。

## 4 复制一份新 recipe

1. 复制一个现有文件，例如 `skillopt-fast.yaml` 复制成 `skillopt-small.yaml`。
2. 文件里的 `id` 可省略（会自动取文件名）；若保留旧 `id`，改成 `skillopt-small`。
3. 改 `params`、`budget`、`description`、`use_when`，保留 `loop`。
4. 在 `sleuth.config.yaml` 把 `recipe` 改成 `skillopt-small`。

新文件随仓库提交，评审时能看到算法与预算的变化。不要只改 `id` 不改文件名，加载会报错。

## 5 校验与边界

- `loop`、`description`、`use_when`、`roles`、`source` 必填；`params` 与 `budget` 可为空。`id` 可省略（取文件名），写了必须与文件名一致；`version` 可省略（取 1）。
- `roles` 必须与该循环要求的样本角色集合一致，不能多也不能少；`params` 的键必须在该循环的 `LoopSpec.params` 里；`budget` 只收 `target_runs`、`worker_calls`、`tokens`，值必须是正整数或 null。
- 加载失败会给出文件名与字段；用户不需要跑校验命令，配置加载或实验启动时会报。
- 用户不通过命令行管理 recipe；改配置与 recipe 文件即可。`experiment.loop` / `experiment.loops` 是专家逃生口，日常不用。
