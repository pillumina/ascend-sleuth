## 背景与动机

- 触发：2026-11-26 诊断会话（traces/2026-11-26-jiukun-moe-dispatch-v3-aicore-timeout）里 `src_fetch.py --find "MoeDistributeDispatchV3" --offline` 零候选、exit 3，被写成「算子实现在 CANN 侧，本地查不到」进了报告缺口表；同一会话里首次取 cann/ops-transformer 因 Windows 超长路径失败只报「无法创建文件」；本轮把三条信号入库时 `evolve_signals.py add` 子命令报 TypeError。
- 不做的代价：同一签名换会话、换机器会重复走「零候选 → 判上游没有」；「拿不到源码」分不清是长路径（一条配置即好）还是网络；信号入库命令在所有部署上都跑不通。
- 做完的变化：MC2 分发/聚合词族签名唯一命中 cann/ops-transformer；零候选后有强制的结算步骤，没做完只能写「未核对（工具零候选）」；取回失败归类成因（环境限制/网络/凭据/其他）；`add` 子命令可用。

## 变更内容

```text
source-catalog.d/cann.yaml            # discover 去掉 all_of[aclnn]、any_of 补 MC2 词；self_test 加 1 条
scripts/src_fetch.py                  # 失败成因归类 classify_fetch_failure；clone_into 返回输出原文；删失去调用者的 run()
skills/diagnose/references/src-fetch.md  # 零候选结算规则 + exit 4 成因归类说明
scripts/evolve_signals.py             # add() 补 local 参数（修 CLI 接线 TypeError）
```

- 对象：source-catalog.d 数据、scripts/src_fetch.py、scripts/evolve_signals.py、skills/diagnose/references/src-fetch.md
- 新增或改名的名字（无则写「无」）：新增函数 `classify_fetch_failure`、`_capture`（src_fetch.py 内部）；其余无

## 证据（改前 → 改后，成对给；一条改动一行）

- `python3 scripts/src_fetch.py --find "MoeDistributeDispatchV3" --offline`：改前 `签名没命中任何候选仓` + exit 3 → 改后 `唯一命中 cann/ops-transformer`（离线不拉取，仍 exit 3 但候选已定）
- `python3 scripts/src_fetch.py --self-test`：改前 15 条真实签名 → 改后 `✓ …（16 条真实签名）`，含新钉的 `MoeDistributeDispatchV3`
- `python3 scripts/src_fetch.py --find "task dispatch failed" --offline`（泛词反例）：改前（中途版本，any_of 含 dispatch）误唯一候选 ops-transformer → 改后零候选，走发现顺序
- `python3 -m unittest tests.test_src_fetch tests.test_src_fetch_scenarios tests.test_source_catalog tests.test_evolve_signals`：60 用例 OK（3 skip 为平台专有用例），含 classify_fetch_failure 归类断言（长路径→环境限制、DNS→网络、认证→凭据、permission denied→本地权限、其他→其他）
- `python3 scripts/evolve_signals.py add --signal T10 --signal-text "x" --target f --evidence "x"`：改前 `TypeError: add() got an unexpected keyword argument 'local'`（exit 1）→ 改后正常落文件

## 原则追溯（原则文件的元规则：不可追溯的变更是可疑的）

- 本变更服务哪条设计原则：诚实退化（「工具没问到」不得写成「上游没有」）与退出码契约（失败出口要给可执行的下一步，成因可判）；数据面/引擎面分离——补词族只改 source-catalog.d，不改 src_fetch.py 的取用流程。
- 是否修改了原则/理论本身的语义：否

## 回归检查（改 skill 本身必做，docs/guide/eval.md）

- [ ] 改动前跑了 golden 套件，基线：N 条通过
- [ ] 改动后重跑，原通过项无一变为失败
- [ ] **若改动了 `eval/golden/**` 或它指向的 case**：未改动，不适用
- [ ] **本改动对应的记录**：现象与出处写在「背景与动机」第一行；三条信号的完整记录在主检出 `proposals/signals/ascend-sleuth-{6d4d13c5,7729a8c0,e275cae0}.yaml`（随下一次周批入库，本 PR 不带信号文件）；无 EV 卡，效果判据即上节「证据」的命令对照
- [ ] **若触及输出契约 / 交互形态**：不触及诊断输出模板与追问链，不适用；本 PR 改的是工具脚本的失败出口文案与 skill 参考文件的方法论条目
- [ ] **若改动交接包链路**：不涉及 export_trace / import_trace / handoff，不适用
- 对照结论见上节「证据」

golden 两项如实说明：`replay_golden.py` 是编排骨架（prepare/collect 需 agent 逐条执行，机械 collect 为 0/0），本机无现成回归门；且按 docs/guide/eval.md 的改动面分表，本 PR 不在检索/路由/候选选择面（改的是取源码引擎、源码仓目录数据与流程参考文本），golden 对口子集不适用——覆盖由 CI `unit-tests`（含 windows 4 分片）与上面的命令对照承担。

## Agent 预核意见（由独立 agent 产出）

- 结论（`MERGE_READY: yes/no`）：`MERGE_READY: yes`——四个修复点核实有效、60 用例与自测全过、失败路径端到端可复现正确归类；仅建议级改进项。
- 核对的版本：`ad5591f6`（diff 基准 `344a567c`）
- 问题（预核时点，均在后续提交处理）：
  - 建议级 1：`classify_fetch_failure` 把 `permission denied` 归「凭据」，本地缓存目录权限不足会同串误导——已拆成独立「本地权限」类
  - 建议级 2：`dispatch`/`combine` 是泛词，`task dispatch failed` 由零候选变为误唯一候选——已换成族词（`moe`/`mc2`/`alltoall`），实测泛词反例回到零候选
  - 建议级 3：「结算规则」首现无中文含义——已加括注（结算 = 给结论前必须做完的步骤）
- 覆盖清单：读全 diff 与相关上下文（source_catalog.py / src_fetch.py / evolve_signals.py）；`--self-test` 通过；4 个测试模块 60 用例 OK；失败路径对不可达地址端到端归类「网络」正确；skill 卫生门 grep 干净；`evolve_signals.py --local add` CLI 冒烟成功
- 反例与可复跑命令：`--find "MoeDistributeDispatchV3" --offline` 唯一候选 ops-transformer；`--find "MC2 alltoall timeout"` 双候选交回人选；`--find "aclnnFlashAttentionScore failed"` 等既有签名无回归；`--find "aclnnMoeDistributeCombineV3 execute failed"` 命中（同族新算子免费覆盖）
- 人读文本三项判定：可读性合格（两段各一件事、低于 200 字）；逻辑性合格（结算规则与脚本打印的下一步一致）；黑话基本合格（仅「结算规则」一词，已修）
- 预核报告：本 PR 对话内的独立 agent 评审记录（agent-1）

## 影响面与合入风险

- 涉及的 skill / 流程步骤：diagnose 步骤 5（源码分析）的 src-fetch 契约；evolve-check / 沉淀流程的信号入库命令
- 对 CLAUDE.md / README / CONTEXT.md 术语表的同步：不涉及（无新对外代号）
- 回退：可 revert 单提交
- 生效时点：合入即生效（skill 参考文件诊断时按需读；数据目录下次 src_fetch 加载即用）
- 读数变化：无
- 留作后续：`any_of` 放开 `all_of` 后，同含 MC2 词与 HCCL 词的签名可能给出 ≥2 候选（如 `alltoall` 同时命中 cann/hccl 与 cann/ops-transformer）→ exit 3 交回候选表，不会误选；若现场反复出现可再收词族信号
