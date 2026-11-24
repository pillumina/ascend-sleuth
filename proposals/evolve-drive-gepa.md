# 提案：evolve-drive 驱动 skill + GEPA 状态机的命令行接入

状态：提议（2026-11-24）

本文提出给自演进实验补一层「agent 驱动的执行循环」：新建 `evolve-drive` skill，配一组薄 CLI 命令（`evolve gepa ...`），让任何有 subagent 编排能力的会话（含 DSH desktop）都能按 `config/rsi/pipelines.yaml` 的 stage 组合跑算法循环，GEPA 是第一个实例。范围覆盖命令行接入、skill 正文、流水线预设；诊断流程与知识内容不在本文范围。读者是评审这项改动的人。

## 要解决什么问题

`scripts/evolve/agent_gepa.py` 的 GEPA 状态机不调用模型、不派 agent，只产出 `next_action`；但仓库里没有任何东西消费这个接口——循环没人驱动，`select.pareto` / `propose.reflection` 两个 stage 注册了却组合不起来。同时 `propose.agent` 的默认路径每轮提案互相独立，judge 的失败反馈回不到下一轮 prompt，反思变异无从发生。结果：算法逻辑在库里，实验跑不起来，只能靠外部 harness 临时手拼。

## 选哪条路

候选有三条。**内嵌模型调用**（状态机里直接调 LLM）被否：确定性决策要可单测、可复现，且执行方就不能换了。**DSH 插件**被否：插件暴露的仍是给 agent 调的工具，驱动逻辑写进 harness 配置就脱离了本仓的 PR 评审与实验复跑链路。**选定的路径**是 agent-in-the-loop：状态全落盘，每轮由会话执行「CLI 取动作 → subagent 执行 → CLI 回写」。放弃的是单脚本一键跑完的便利（会话可中断、可 compact、可续跑是换来的收益）；可能坏在反馈契约上——judge 分数字段与状态机的约定没有 schema 强制，靠 skill 正文约束与 `GepaError` 的顺序校验兜底。

具体改动四件：

1. `scripts/evolve/cli/gepa.py`：`gepa init / next / apply / result` 四个命令。状态是 `GepaSession.to_dict()` 的纯 JSON，进出全走命令，进程间不驻留内存。这是最小驱动协议的第一个实现：`next` 返回 `{kind, payload}`，`apply` 按 kind 回写。
2. `scripts/evolve/policy.py`：`load_config_policy` 接受预设名直传（CLI `--pipeline`），优先级高于全局 `evolution.pipeline` 与 profile 携带的 `pipeline` 键。预设清单只在 `config/rsi/pipelines.yaml` 维护，新增算法不改 sleuth.config.yaml。
3. `skills/evolve-drive/SKILL.md`：算法无关的驱动循环。正文只描述六个 stage 点的通用分派规则（按 plan 的 stages 字段与 stage 的 execution 字段），不写 GEPA 专名的行为；未知的 action kind 报错停下。
4. `config/rsi/pipelines.yaml`：登记 `gepa` 预设（`select.pareto` + `propose.reflection`，judge/gate 同默认）。
5. `docs/_manifest.yaml`：登记新 skill。

## 怎么算完成

- 单测：`python3 -m unittest tests.self_evolution.test_gepa_cli` 通过，覆盖 init → evaluate × samples → reflect → 再 evaluate → 预算耗尽 stop → result 全链，以及未知 kind、超预算回写、reflect 缺文件、overwrite 守卫、状态与核心类往返五条例外路径。
- 配置：`--pipeline` 直传与 profile 通路各验一条——`load_config_policy(cfg, pipeline="gepa")` 与 `load_config_policy(cfg, profile="gepa")` 的 stages 都变为 `select.pareto` + `propose.reflection`，全局默认不变；预设解析本身用 `python3 -c "import sys; sys.path.insert(0, 'scripts'); import sleuth_config as SC; print(SC.pipeline_for(SC.load_config(), 'gepa')['stages'])"` 确认 extends 链可解析、六个点全落到已注册 stage。
- 生成物：不改任何生成文件；skill 名单由合入后的主干 job 重建。
- 手工演练：用两个假样本跑一遍 `gepa init/next/apply` 循环，`next` 在预算耗尽后返回 `{"kind": "stop"}`。

## 不做会怎样

反思变异（GEPA 的核心机制）停留在注册表里的两个名字上，`agent_gepa.py` 是没有调用方的死代码；后续每个新 RSI 算法都要重造一遍「怎么驱动 subagent、怎么落盘、怎么续跑」，而本可以只写一个状态机类加一个流水线预设。
