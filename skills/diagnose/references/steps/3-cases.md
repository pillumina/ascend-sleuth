# 步骤 3：两阶段加载 Tier 2

> **何时读**：每次诊断，路由之后（必读）。
> **完成判据**：候选 ≤5 且逐条有 `quickly_check` 结论；阶段 2.5 按 `ref_knowledge` 取过修复依据或记 `skipped` 加理由；数据缺口按 `../collect-gates.yaml` 走过。
> **本步产出**：`load_index` / `quickly_check` / `load_full` / `reference_lookup` 事件。

**阶段一（索引）**：读**命中 (namespace × category) 的读侧视图** `knowledge/_index/<ns>__<category>.list`（`scripts/build_index.py` 生成；category 未定 → 回退该 namespace 的 `<ns>.list`——**这条路更贵**（vllm-ascend 2.4 万 token，超硬线；两类视图成本都现算：`python3 scripts/index_read_cost.py`），先按标题/标签收敛到候选再看，别逐条通读）。它是**一行一条 case** 的文本，字段按序为 `id / category / title / symptoms 首条 / sig / tok / compat / tags / score`——`sig` 是该 case 的报错字面量（输入里逐字命中即强候选）、`tok` 是关键词集合，两者是判断的**证据**；行内没有 `quickly_check`，判定式在 case 本体、阶段二才读。
**排序仍由你按相关性判断**：`score` 只作破平（它 calibrate 的是现场解决率，不是本次相关性——实测按 score 单独排序会把期望 case 压到中位第 20 名）。**不要用机械计数替代你的判断**：历史回放里 agent 的相关性判断把期望 case 放进 top-3 的比例（19/19）高于任何机械排序键。需要机械序做对照时可跑 `python3 scripts/rank_candidates.py`（工具，不是规定动作）。

**这个视图就是本步的预算上限**：条目每条约 150–250 token，意味着百余条的格子约 1.5–2 万 token——顶得上整个常驻指令面，所以既不要退化成读全库总表 `knowledge/_index.yaml`（机器面、嵌套 YAML、随库线性涨），也不要在这一格上反复重读。**要看准确数字**：`python3 scripts/index_read_cost.py`（逐格现算，含"如果换更省的行宽能省多少"）。
**为什么不是 YAML**：阶段一是人/agent 在读它，YAML 的缩进、引号、字段名、嵌套在百余条规模上要多花四成 token，而信息与旧形态一一对应（只少了 `file`——可由 id 推出——与 `hash`——只服务索引新鲜度门）。判据：**每一条都要看到，但每条只花一行**。
两阶段加载由**结构**保证，不靠逐文件打开的自觉：**读侧视图里没有 `quickly_check`**（字段就是上面那九个，`file` 与 `hash` 也不在里面），判定式在 case 本体、到阶段二才读。索引缺失或 `build_index.py --check` 报过期 → 先跑 `python3 scripts/rebuild_generated.py --check` 重建（有合入后重建 job 的部署由主干 job 负责；没有这个 job 的部署要由人跑同一条命令并提交）；仍失败再兜底逐文件只读上述索引字段。**筛候选时同步扫 `tags`**（与 title/symptom 并查）：同族 case 常只靠 tag 表达（如 `balance-scheduling` / `patch-layer`），只按 title/symptom 词面 grep 会把"同文件族"整片漏掉（静默停滞类尤其如此——真实故障常是调度/控制循环层，而它的 tag 不在症状词面里）。

**空库提示（冷启动）**：若命中 namespace 为空（还没 case），**不要静默退化**——告诉用户“当前 `knowledge/<ns>/` 还没有验证过的 case，你可以：①继续深度排查（步骤 5）②诊断完跑 `/skill:to-postmortem` 沉淀成第一条 case ③转人工”。空库的体感不该是“啥也不会”。

**category 决定 quickly_check 形态**（最容易踩的坑）：
- interrupt → grep 错误签名/栈
- precision → 数值阈值断言（`loss>1e3`、`has_nan`、`loss_slope`）
- performance → profiler 指标阈值（`comm_ratio>0.4`）

拿 interrupt 的 grep 思路建 precision case，匹配不上。

**阶段二（全量）**：候选 ≤5 条，全量加载 body，按索引行里的 `score` **降序**验证（最可靠的先试）——单条全文的中位与最贵 5 条合计都现算（`python3 scripts/index_read_cost.py`），与最贵的索引格子同量级，所以"够了就停"，不要凑满 5 条。**先跑候选的 `quickly_check` 对照已提供的信息**：
- 先 primary（精确）
- primary 不匹配 → 跑 fallback（更模糊）
- primary 不匹配但 fallback 匹配 → 仍进验证，标 `low_confidence`
- 都不匹配 → 跳过该 case（它不是候选）

**多条候选时明示**：“匹配到 N 条，先验证最可能的 `<id>`（索引里的 score `<score>`）”，工程师可说“跳过这条试下一条”。

**阶段二.5：候选自带回链与修复依据（「判断缺口 · 修复依据」消费点）**——**候选命中后固定执行，不写成"按需"**：命中只说明"这条 case 像"，不说明"该补的先验已经在手上了"。把"需不需要先验"交给当场自评，等于让最顺的那条路径永远不读先验。执行顺序（**只读 `status: active`**）：

1. **候选带 `ref_knowledge` → 读它**：按每条 `role` 用——`signature-source`（签名的含义与判别面）、`fix-methodology`（修复路径的方法依据）、`root-cause-context`（根因成立的背景）。这是最精准的入口：关系是沉淀时写下的，不需要当场猜。**只有少数 case 有这条手写回链**，没有它不等于没有先验可补——背景那一半已在步骤 2 收尾查过，此处不重复查。
2. **按需补修复依据（`purpose: fix`）**：`command-side-effect` / 工具解读这类"修复路径的依据"词条，在候选命中、要给修复建议时按 `ref_knowledge.role: fix-methodology` 或工具名直接读单文件。
3. **查表类（error-code / fault-pattern / env-var-table / compat-matrix）不在这里**：它们是码 / 签名 / 名 / 版本检索键，键来自证据而不是来自候选，已在步骤 2 收尾的键触发里按检索键取过，此处不重复查。
4. **流程类（methodology）也不在这里**：它要的是"选中一条读全文"，走步骤 5 的流程选择器；摘要行承载不了判据。

- **只读 `status: active`**——draft / pending-review / deprecated 一律不加载（未验证知识不进上下文——这是"agent 不引用错误先验"的机制化，不是自觉）；
- **trace 三态必记**：`{action: reference_lookup, purpose: fix, outcome: hit|miss|skipped, ref_id, platform, output, reason}`——`hit` 读到并用了、`miss` 查了没有相关词条、`skipped` 没查（**写明为什么**，例："本次修复路径不依赖工具解读，候选也未带 `ref_knowledge`"）。**候选全未命中时**这一步不适用，但**步骤 2 的背景查询照做**（它不依赖候选），别把两件事写成同一条 `skipped`。

**数据资产探询（「数据缺口」消费点——时点：候选加载后）**：候选读完、**发现某个具体测量值（或产物）不在手上、而它决定下一步能不能走**时，按 `../collect-gates.yaml`（本 skill 的 references/，**不是仓库根 references/**）执行闸门——问句、分支动作、词条绑定都在表里（id 受 CI 校验），本文不重复：

- `kind: probe`（precision / performance）→ 先问一句，按回答走「已有 → 分析路径」「没有 → 采集指引」；
- `kind: conditional`（interrupt）→ 不预先问，缺口出现（现有日志不足以定位）才给采集指引。

**探询锚点**：问句要落到这个具体缺口上（「这条 case 要确认 X，你手上有 dump 吗？」），不是开放式的「你有没有数据」——后者逼工程师先猜类别再猜产物，答错了还得第二轮。**边界（别混淆）**：锚点是"这次缺的这个值叫什么"，**不是把问句形态改成体检式的清单**；闸门表里 `question` 的措辞照旧，只是补上这次要确认的字段名或产物名。

三条纪律（只问一次 / 区分改谁 / 命令以客户环境为准 + 先排除采集副作用）见 `../reference-gaps.md` 的「三条纪律」。**采集面被消费时记 trace**：`{action: reference_lookup, ref_id, purpose: collect, outcome: hit|miss}`——采集面此前无 purpose 可记，等于零观测。精度 / 性能单无论如何留一条：给了采集指引记 `hit`，探询后对方已有数据（不需要采集面）记 `miss`。interrupt 单不记（本触发点不在该路径上）。

trace 记：
```yaml
- {step: 3, action: reference_lookup, ref_id: msprobe-data-dump, purpose: collect, outcome: hit}
- {step: 2, action: reference_lookup, purpose: signature, outcome: hit, ref_id: runtime-resource-fault-patterns, platform: A3-910C}
- {step: 2, action: reference_lookup, purpose: signature, outcome: skipped, ref_id: null, reason: "报错是框架自定义断言文本，无错误码 / event_id / env 名可作检索键"}
- {step: 2, action: load_index, namespaces: [...], n_cases: 34}
- {step: 3, action: quickly_check, case: MSLLM-EP-HANG-001, primary: pass}
- {step: 3, action: load_full, candidates: [...], order: by_index_score}
- {step: 3, action: reference_lookup, purpose: background, outcome: hit, ref_id: aclnn-two-phase-contract, platform: A3-910C}
- {step: 3, action: reference_lookup, purpose: background, outcome: miss, ref_id: null, reason: "背景层按平台+组件词取 5 行，无与本签名相关的词条"}
```