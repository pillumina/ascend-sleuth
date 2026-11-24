# 方案：搜索循环层与组合实验

状态：已实现，待评审。

改之前，「算法」在三个地方各有一个定义。

`stages.py` 把 GEPA 写成 `select.pareto` 与 `propose.agent` 的节点组合。`algorithms/registry.py` 把算法限定为提案者，当前只有 `baseline`。

实际运行时用的是 `agent_gepa.py`、`loo.py`、`proposal_engine.py` 三个状态机。第三个算法接入时，调度、预算与决策记录要各写一遍，实验层也只能比较基线与单个候选。

## 要解决什么问题

三个状态机各自处理批次、候选池、预算和停止条件，共用部分没有契约。候选有两种表示：GEPA 用一段文本，提案层用 `Proposal`，两者不能直接交接。实验层没有多臂与链式的位置。

## 选哪条路

把职责分成三层。

- 节点层：`scripts/evolve/stages.py` 的六个点，决定一次改动怎么提、怎么选、怎么判。现有流水线预设只描述这一层。
- 搜索循环层：`scripts/evolve/loops/`，决定一次实验怎么走。搜索循环只产出动作（如 `evaluate`、`reflect`、`merge`）；模型调用、文件写入和知识库修改由驱动会话执行。
- 实验层：`scripts/evolve/experiment_spec.py` 与 `experiment_session.py`，声明用哪些搜索循环、哪些样本角色、多臂还是顺序链、哪个是主臂。实验描述文件下称 spec，主臂指进入最终判定的臂。

用户默认值在 `sleuth.config.yaml` 的 `evolution.policy.experiment.recipe` 选；算法与参数写在 `config/rsi/recipes/<名>.yaml`，复制改名即可派生。CLI 与 spec 的显式值覆盖 recipe。

搜索循环契约包含四个对象：

- `Snapshot`：候选。单文件用文本，多文件用路径到文本的映射。
- `ActionSpec`：声明动作与执行方（`target` 或 `worker`）。驱动按注册表分派，未登记动作直接报错。
- `Budget`：统一记录目标执行、worker 调用与 token。旧状态里的 `max_metric_calls` 和 `max_audit_calls` 映射到目标执行。
- `DecisionLog`：只追加搜索循环内的接受与拒绝，不写 `Conclusion`。合入仍由配对门判定。

迁移范围：GEPA、LOO、baseline 对照、`ProposalEngine.run` 的提案搜索。SkillOpt 作为第三个搜索循环实现快更新：按批次分成功与失败两组反思，合并后在全量验证集上比较，高于现任才采纳。慢更新、保护区与 meta-skill 未实现。群体演化与多保真分配只用测试里的最小实现验证契约可承载，未作为生产算法登记。

多臂比较先实现。每个臂使用同一批样本和独立的目标执行预算；一臂结束后在共同验证集上复评，主臂在 spec 中预先声明。顺序链把前一臂的最优快照作为文本 seed 交给下一臂。最终合入仍走 `experiment flow` 或 pilot 的配对门。

不采用的方案：把搜索循环写进六点预设。预设无法表达批次、epoch 与预算分配，写进去后「预设」会同时承担两种含义。也不做动态插件加载，新算法仍通过静态注册表登记。

这条路的边界：

- 搜索循环不读测试角色；`LoopSpec.validate` 拒绝 `test`。
- 顺序链按文本快照交接；多文件快照的链式组合未实现。
- 搜索循环内的接受不是统计结论。多臂都在同一测试集上比较会累积假接受；主臂规则与配对门限制这一点。
- SkillOpt 慢更新、保护区与 meta-skill 未实现。触发条件是采样池足够大且快更新对照有效。群体演化与多保真分配只有测试夹具，接入生产时再补注册与状态恢复。
- 在线策略选择与搜索循环生成样本不在这一层。前者属于诊断执行面，后者要经过样本复核与封存。

## 怎么算完成

- `python3 scripts/evolve.py loop list` 列出已登记搜索循环；`loop show --loop skillopt` 输出动作与样本角色。
- `python3 -m unittest tests.self_evolution.test_agent_gepa tests.self_evolution.test_loo` 证明旧状态与旧命令组可读。
- `python3 -m unittest tests.self_evolution.test_loop_contract tests.self_evolution.test_skillopt` 覆盖契约与 SkillOpt。
- `python3 -m unittest tests.self_evolution.test_experiment_arms tests.self_evolution.test_loop_cli` 覆盖多臂、顺序链与 CLI。
- `python3 -m unittest discover tests` 全量回归。

## 不做会怎样

第三个算法接入时，调度、预算与决策记录再写一份。多臂实验只能分两次跑脚本，再人工比较；主臂与测试集的选择留在会话里。SkillOpt 的批次反思与验证集比较无法进入现有循环，现在只有 GEPA 能跑完整搜索。`Conclusion` 与搜索循环内的接受混在同一条记录里，判定的统计语义会被混淆。

