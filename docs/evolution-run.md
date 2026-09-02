# 持续运行：长期任务、issue 评测循环、执行记录与可视化

> 四份文档的分工：**[evolution-pipeline.md](evolution-pipeline.md)** 机制总览；**[evolution-execution.md](evolution-execution.md)** 单卡执行契约；**[evolution-orchestration.md](evolution-orchestration.md)** 单轮会话编排；**本文是运行视图**——回答"我下一条指令后，系统作为**持续自演进系统**怎么跑、跑到什么时候停、我怎么看到它在跑"。它把前三份的单轮/单卡机制装配成用户可下指令、可观察、可干预的长期运行形态。
> 推导依据：原则一/五/七/八/九/十/十一；理论见 design-theory §4.2–4.4 与 §6。**本文自身修订 = L3 结构（methodology PR + 体系维护人审）。**

## 1. 从一条指令到持续自演进（愿景总览）

用户的典型指令（示例）：

> "持续基于 vllm-ascend 仓库的 closed 高质量 issue 与 open 高质量 issue（先拉 200 个），对当前系统与知识库做沉淀和迭代；之后持续分批拉取，按 self-evolving 机制制定计划与角色任务；每次 diagnose 或调用其他 skill 都记录数据/trace/metrics，供 feedback loop 与 proposal → action → eval 闭环；我能看到 agent 的操作、执行、决策，并看到系统在自演进。"

系统把它翻译成四件事：

1. **建评测与沉淀源**（第 3 节）：拉取 issue → 分成"评测样本 + 沉淀素材 + 覆盖信号"三类用途；
2. **开一个长期任务**（第 2 节）：goal + scope + 预算策略 + 每轮循环（拉取 → 评测 → 沉淀 → 候选 → 实验 → 合入 → 报告）；
3. **全程留痕**（第 4/5 节）：每次 skill 调用记录执行数据，proposal 可替换可回滚；
4. **可观察**（第 6 节）：agent 操作/决策/状态流转渲染给人看。

## 2. 长期任务层（机制 A）：多轮循环，不是单轮会话

orchestration §1 的会话是**单轮**（意图→计划→执行→报告→停）。用户的指令是一个**长期任务**——一轮做完不结束，而是按数据增量继续下一轮。

```
长期任务（goal_id + scope + issue 源配置 + 预算策略 + 停止条件）
  ├─ 每轮 = 一次 orchestration 会话（复用 §1 协议）
  │    拉新批次 → S2 评测 + 沉淀评估 → 候选 → 授权 → 实验 → 合入 → 回测 → 报告
  ├─ 轮间调度器决定下一轮范围：
  │    新 closed issue？→ 评测/沉淀轮
  │    待观察窗结算的 adopted？→ 回测轮
  │    open issue 转 closed？→ 自动评测（见第 3 节——无需延迟等待，增量拉取自然捕获）
  │    metrics 漂移？→ 诊断式候选轮
  └─ 状态：active → paused（预算/人中断）→ steady（收敛降频）→ stopped（人终止）
```

任务状态落 `proposals/tasks/<TASK-ID>.yaml`（goal、scope、来源配置、每轮引用、预算账本、停止原因），**git 跟踪、只含聚合与引用**。任务是容器，会话是任务的一次执行——session state 与 task state 分离（task 记得目标与历史，session 记得本轮进度）。

**DSH 载体映射**：任务轮间调度（拉新批次 → 决定下一轮范围 → 分派轮内角色）可落到 DSH 的 **Agent Teams**（experimental：持久 roster + 共享任务 DAG + 持久 mailbox，含 blockedBy 依赖边——天然表达"回测轮依赖评测轮完成"）；轮内单步用 continuable subagent 即可。载体选项与启用条件见 evolution-pipeline.md §6.7，机制与载体解耦——无 DSH 环境时任务状态文件 + 手动/定时触发同样成立。

## 3. Issue 的三重角色与 S2 即时对照（机制 B 修正）

**修正**：早期讨论把 open issue 设计成"预诊断 → 等 closed → 对照"的延迟机制——**这是错的绕路**。高质量 issue（closed、maintainer 确认 resolution）本身就是"现象 → 根因"的带标注样本：拉取时**答案已在手上**，diagnose 评测 = 输入现象、对照维护者结论，**即时出分**，不需要等任何未来事件。issue 数据同时承担三重角色：

| 角色 | 用途 | 说明 |
|---|---|---|
| **评测数据集** | S2 即时对照（pipeline §2.1）：系统输出 vs issue resolution | 每批 closed issue = 一次可自动评分的诊断考试；分数进 feedback loop |
| **沉淀素材** | to-postmortem / to-reference 的案例来源 | 同一批 issue 在评测后仍是 case/reference 的知识来源（issue-ingest 已做） |
| **覆盖缺口信号** | open issue：系统对某 open issue 现象无法诊断/无 case 候选 → 缺覆盖 | open issue **无答案，只能作弱信号**（诚实退化：不做"诊断确诊"，只记"未覆盖"） |

**open issue 的正确处理**（替代"延迟对照"）：open 池只做**覆盖探测**——现象喂 diagnose，无命中/低置信 → 记"该现象族未覆盖"候选（进待定池），**不做结论判定**（无 resolution 可对照）。issue 转 closed 后自动进入评测池（增量拉取游标天然捕获 open→closed 转换），从那一刻起才有答案、才参与 S2。

**S2 校准集的 selection/test 分离（审查可补点 1）**：S2 池分两半——`selection`（gate 决策用，改 skill 前后对照打分）与 `test`（validated 终判用，防对校准集过拟合）。规则：**gate 决策只看 selection，validated 终判只看 test**；test 半不参与任何中间对照（对应 SkillOpt 的 held-out test，防系统"记住"校准集）。

## 4. 统一执行记录（机制 C）：每次 diagnose / skill 调用都留数据

现状：**只有 diagnose 写 trace**；to-postmortem / to-reference / issue-ingest / knowledge-groom / 自演进各 agent 动作不落执行数据——feedback loop 的数据源只有诊断一侧。扩展为**统一 skill 执行日志**：

```
每次 skill 调用写一条执行记录（traces/ 或 metrics/skill-exec-log.yaml）：
- 调用：skill 名 + 版本 + 时间 + 触发者（任务 id / 会话 id / 人）
- 输入摘要（脱敏纪律同 execution §2：原文留本地，日志只记引用与聚合）
- 产出：case/reference/卡 id、状态流转
- 命中与成本：命中组件、耗时、token
- decision reason：关键决策的一句话依据（agent 的 reason 字段）
```

用途：metrics 有全链路数据源（不只诊断命中率）；归因能定位到"沉淀环节"还是"诊断环节"错；token 账本能精确到每次调用（第 3.3 节 orchestration 的预算治理才有数据）。**边界**：记录对象是 skill 与动作、产物 id——**不是人**（不引入身份维度，roadmap「不做 KPI/身份/使用观测」红线不变，见 pipeline §5.3）。

## 5. 替换与回滚（机制 D）：新 idea 替换旧实现

当前 schema 只有单卡生命周期（rejected = 终态）。用户场景"发现 proposal 没效果、或有了更好的 idea 可回滚之前的"需要**卡间关系**：

- idea 卡加 `supersedes: [EV-xxx]` / `superseded_by: EV-yyy` 字段；
- 新卡合入且观察窗 validated 后，被替代旧卡若仍在 adopted 态 → 标 `superseded`（不是 rejected——它曾有效，是被更好方案替代，历史保留）；
- 回滚语义升级：rolled_back 时若该卡 supersedes 某旧卡 → **回滚到被替代版本**（git revert 到旧卡合入点），而不是回滚到空白；
- 追溯链：卡 → supersedes 链 → decisions → 实验记录 → 合入 commit，任何一点可回看"现在的实现是谁、替代了谁、为什么"。

## 6. 可视化（机制 E）：让"看到系统自演进"成为可能

数据**已经存在**（session state、trace、decisions、token 账本），缺的是渲染层。视图分四层：

| 视图 | 内容 | 数据源 |
|---|---|---|
| 任务总览 | 任务列表/状态（active/paused/steady）、每轮结果摘要、token 总账 | proposals/tasks/ |
| 会话直播 | 当前轮进度：进行到哪一步、在跑哪个 agent、下一步计划 | session state + 执行日志 |
| 卡流转 | 每卡状态机（candidate→…→validated/rolled_back/superseded）+ decisions 链 + 实验结论 | proposals/ideas/ |
| 指标 | 四层指标（execution §6）+ 回滚率 + 每 validated 卡 token | timeline + 台账 |

载体两档：**DSH 面板扩展**（仓库已有 ascend-panel 先例，诊断/指标 tab 加"自演进"tab）或**HTML 报告**（health_report 同款，离线生成）。诚实标注同 O7：〔中心全量〕或〔本地视角〕。agent 的操作序列与决策 reason 已随 trace 记录，渲染即"看到系统在自演进"。

## 7. 停止条件汇总（"跑到什么样停止"）

**每轮**（orchestration §2.2）：预算耗尽 / 产出达 N validated / 连续 M 否决（信号误报）/ 收敛（无新信号）/ 人中断——任一即停，出报告。

**任务级**（本层新增）：达到稳态（连续两轮无新信号且 validated 效果达标）→ `steady` 降频（第 2.3 节）；人随时 `paused`/`stopped`；预算策略（如每周 token 上限）耗尽 → `paused` 等下一周期。

**长期安全阀**：回滚率或抽审发现率超阈值 → 任务自动降授权级别（auto→review）并通知人（自我指涉治理，orchestration §4）。

## 8. 原则追溯

| 设计元素 | 服务的原则 | 说明 |
|---|---|---|
| issue 即带标注评测集、即时对照 | 八（可观测先于改进）、十 | 答案随拉取可得，无需延迟机制；open 只作弱信号不冒充结论 |
| selection/test 分离 | 一（验证先于交付） | 防对校准集过拟合，validated 终判用未见过的 test |
| 统一执行记录（对象是 skill 非人） | 八、九 | feedback loop 全链路数据；不碰身份红线 |
| supersede 关系与回滚到被替代版本 | 七（变更可逆） | 替换可追溯，回滚粒度到"上一个有效实现" |
| 可视化四层视图 | 八、十 | 让"人在看系统演进"成为可能而非宣称 |
| 任务级稳态降频与安全阀 | 九、十一 | 持续运行必须有资源与质量边界 |

## 9. 落地顺序

| 步骤 | 内容 | 入口闸门 |
|---|---|---|
| 1 | S2 校准集建立 + selection/test 划分（先 20 条验证，再扩 200） | issue 池可批量取（已具备） |
| 2 | 统一执行记录（先 diagnose + issue-ingest，再扩展到全部 skill） | 记录 schema 定稿 |
| 3 | 长期任务层试点一轮（手动触发，任务状态机 + 轮间调度跑通） | 步骤 1–2 有真实数据 |
| 4 | supersede 字段 + 回滚语义落地 | 出现首个"新 idea 替代旧实现"场景 |
| 5 | 可视化（DSH 面板扩展或 HTML 报告） | 任务层跑通 ≥1 轮 |

与用户指令的对应：这条指令即第一个长期任务——**先拉 200 个 issue（步骤 1 的扩池），前几轮的真实产出是"通电"（建 S2、接执行日志、跑通任务循环），之后才进入持续的沉淀与演进**。诚实边界不变：内容层（补 case/沉淀）可高度自动，结构层（triage/skill/指标口径）永远人审。
