# Diagnosis Procedure（核心循环展开）

`/diagnose` 的 SKILL.md 写主干，这里展开每步的判断细节。agent 在执行复杂分支时按需加载本文件。

## 步骤 1：收集症状 + 确认框架（全部来自工程师提供的信息）

> 你不访问任何环境。所有信息（日志、版本、报错、环境变量值）由工程师从客户那提供。信息不够时，明确提示需要向客户要什么。case 里的 `command` 是“要确认的检查”——对照已提供信息判断，或让客户跑后贴回，不是你执行 pip/env/grep。

```
本步的工作是一张**覆盖表**：行固定、值按他提交的材料填——**先提取，再问缺口**，顺序不能反。

固定行（每行一个值，别合并、别省略行）：
  1) 错误原文（字面，不转述）        2) 触发位置（启动 / 第 N 步 / 训练中 / 推理请求中）
  3) 引擎版本                      4) CANN 版本
  5) HDK / 驱动版本                6) 平台（A2/A3/A5 + 具体型号）
  7) 必现还是偶发（复现率）          8) 单机还是多机（哪些 rank / 节点）
  9) 已经试过什么（改过什么、报错有没有变）
  另收环境变量值（HCCL_*/ASCEND_*/NPU_*）——同样先提取。

怎么填：
  a) 先在他已经贴进来的日志 / 报错 / 配置 / 命令输出里找：栈尾常带框架版本，启动横幅带
     CANN 与 HDK 版本，plog 与 npu-smi 输出带平台，启动脚本带环境变量——**别整份索要**
  b) 提取到的行填值；**提取不到的行留空**——空行本身就是待问项，不靠"我觉得还缺什么"
  c) 只问空着的那几行，一次问全（别挤牙膏式一轮一项）
  d) 把提取到的值列给他核对一次（日志里的版本可能被容器覆盖，提出来不等于事实）

框架：从提供的信息/报错判断（日志里 mindspeed/vllm 字样等）；判断不了就问工程师
  “客户跑的什么框架”——不要跑 pip list（那是你本地环境，跟客户无关）
```

**输出契约：只报确认行与待补项**——已提取到的行一行带过（`✓ 平台 A3-910C   ✓ CANN 8.0.RC2`），
不把原文复述回去（让他重看自己的日志等于没提）；空行凑成一条问句问出去，编号让他回数字或直接补。
形态举例（行按上面固定顺序，⚠ 即待问项）：

```
信息核对（从你贴的日志里提的，⚠ 的要你补）：
✓ 平台 A3-910C   ✓ CANN 8.0.RC2 / HDK 24.1   ✓ 框架 vllm-ascend 0.9.0
⚠ 触发位置：启动即挂，还是跑起来第几步挂？
⚠ 影响面：必现还是偶发？单机还是多机？
⚠ 已经试过什么？（避免我给你试过的方案）
```

**这张表同时是 trace 的 user 事件 `evidence` 的骨架**：提取值与缺口（`missing`）都落进去，
续接的人不必重问一遍已经给过的信息。

**日志裁剪（硬要求）**：诊断 session 的 context 八成是日志/profiler，不是 KB。一份 128 卡全量 profiler 灌进来直接滑出 smart zone（~120K token 推理最锐利），推理质量暴跌。裁剪规则：
- 只贴**失败 rank**的日志（`rank_selector` 指定的：coordinator / all_failed / by_topology）
- 只贴报错**栈尾**（最后 N 行，含第一个 ERROR）
- profiler 数据先过 `ascend-profile-analyze` 出 `report.md`，只读报告不读原始数据

**数据资产探询不在这里**——时点在**步骤 3 候选加载之后**（缺哪个具体值要看过候选才知道）。本步只把"他手上可能有什么测量产物"记一笔到 user 事件。

## 步骤 2：分类 → triage-tree

加载 `triage-tree.yaml`。症状匹配分支（正则兼容的模糊匹配）。每个分支带 `category`（interrupt / precision / performance）。

**triage 决策必记 trace**：
```yaml
- {step: 1, action: triage, branch: training_interrupt, category: interrupt, routed: [training/mindspeed-llm/, common/]}
```

路由规则：
- 框架检测到 → `search_namespaces` 先 `training|inference/<framework>/`，再 `common/`
- 框架未检测到 → 只 `common/`
- **冲突时先单选，不要求工程师表态**：日志签名与症状性质指向不同 category 时（详见 SKILL「始终要避的坑」），**自动单选**并在一句话里说清两条线——先走症状那条，日志那条写明它需要什么信息才走得通；给一句覆盖点让他能改向。**不要把"你觉得这是哪类问题"抛回去**：那是要他做他做不了的判断。两条线的按需参考入口各走各的（精度 / 性能走数据探询闸门，中断走条件型闸门），不因为先走一条就跳过另一条的记录。
- **优雅退化**：多个分支弱匹配 / 置信度低 → 加载**所有 namespace 的索引**让 quickly_check 筛（索引便宜，退化最坏 ~20K token 仍可控）。这救冷启动——triage-tree 第一周是猜的。
- 无法分类 → 直接 Tier 3 关键词检索

**路由准确率**依赖这步的 trace：最终 root cause 所在 namespace 是否在被加载集合里（指标定义见 docs/guide/metrics.md）。路由错（分错桶）和 KB 空（分对了没 case）修复动作相反，必须分开测。

**先验键触发（本步骤收尾，先于候选加载）**：把证据里**能当检索键的东西**当场查掉——错误码（`E1xxxx` / `EIxxxx` / `507xxx` / `0x……`）、可 grep 的故障签名（`fault kernel_name=`、`event_id`）、具体环境变量名、要核对的版本组合。查法与阶段 2.5 的查表路径同形态，只是**时点提前到这里**：

- 错误码 → 读 `ascend-error-code-structure` 的 `module_files` 前缀映射定位族文件（`references/errors/<族>.yaml`），族内 grep code 读 meaning / solution。**族文件里查不到这个码时不要就此收场**——`references/errors/_code-gaps.yaml` 是"错误表缺行但库里有事实"的索引：按 code 查一行，`seen_in` 直接指出该码在哪个故障模式词条里有症状→根因→修法（实测有十余个码属于这种：官方表没有行，隔壁表有答案）。也没有 → 才是真的没有，把码写进 `_code-gaps.yaml` 的 `no_home` 段（覆盖缺口要留痕，下次遇到能省一次全库翻找）；
- 故障签名 → 按域定位 `references/fault-patterns/<域>.yaml`，域内 grep symptoms 读 cause / fix；
- 环境变量 → `references/env-vars/<表>.yaml` 内 grep name；
- 版本组合 → `references/compat-matrices/` 按传导链分层，按要核对的层直接读该层文件：framework 层 `references/compat-matrices/vllm-ascend-torch-npu.yaml` / `references/compat-matrices/verl-npu.yaml`、adapter 层 `references/compat-matrices/torch-npu-cann.yaml`、base 层 `references/compat-matrices/cann-hdk.yaml`（CANN↔驱动/固件，如 `cann: 9.0.1` 一行直接给配套 `hdk` 列表）——**先落本库矩阵，再考虑联网查证**（厂商文档站多为 JS 渲染，正文表格常取不到）。

**命中了不等于能套用**：故障模式表按**域**组织，同一个码可以在不同病因下出现（如 `507035` 一家讲 UB 对齐违例、现场那单是索引 buffer 取值越界）。读到词条后先核对它的症状面与**本次证据**是否同一病因，不同就写明"命中但不作根因依据"再继续——把命中当结论是把检索当确诊（原则一）。

**为什么提前到这里**：码 / 签名 / 名的**语义**与"命中哪条 case"无关——不知道 `507903` 是什么意思时，case 层给不出解释，而这个解释正是判断候选真假的输入。排在候选加载之后，等于让判断先于理解。

**为什么必须有负记录**：这个触发点的价值一半在"查到了什么"，另一半在"**没有可查的键**"。证据里没有可检索键（报错是框架自定义断言文本、Python traceback、业务日志）时记 `outcome: skipped` 并写明理由——不记的话，"库不覆盖这个键"与"根本没查"在数据上完全同形。

trace 记：`{step: 2, action: reference_lookup, purpose: signature, outcome: hit|miss|skipped, ref_id, platform, output, reason}`（`outcome` 三态词表见 `diagnosis-trace.md`）。**每次诊断都留一条**（含 `skipped`）——它是"这一单到底有没有可查的键"的唯一数据源。

## 步骤 3：两阶段加载 Tier 2

**阶段一（索引）**：读**命中 (namespace × category) 的索引分片** `knowledge/_index/<ns>__<category>.yaml`（`scripts/build_index.py` 生成；category 未定 → 回退该 namespace 的分片 `<ns>.yaml`），用条目里的 `title` / `tags` / `symptoms` 首条摘要 / `confidence.score` 筛候选（≤5）。条目每条约 0.7KB（≈210 token），**这个分片就是本步的预算上限**——不要退化成读全库总表 `knowledge/_index.yaml`（它随库线性涨，且不增加本步需要的判别信息）。
两阶段加载由**结构**保证，不靠逐文件打开的自觉：**索引条目里没有 `quickly_check`**（行已瘦身成 id/title/tags/symptoms 首条摘要/category/score + `file` 定位），判定式在 case 本体、到阶段二才读。索引缺失或 `build_index.py --check` 报过期 → 兜底：逐文件只读上述索引字段，并提醒重建索引。**筛候选时同步扫 `tags`**（与 title/symptom 并查）：同族 case 常只靠 tag 表达（如 `balance-scheduling` / `patch-layer`），只按 title/symptom 词面 grep 会把"同文件族"整片漏掉（静默停滞类尤其如此——真实故障常是调度/控制循环层，而它的 tag 不在症状词面里）。

**空库提示（冷启动）**：若命中 namespace 为空（还没 case），**不要静默退化**——告诉用户“当前 `knowledge/<ns>/` 还没有验证过的 case，你可以：①继续深度排查（步骤 5）②诊断完跑 `/skill:to-postmortem` 沉淀成第一条 case ③转人工”。空库的体感不该是“啥也不会”。

**category 决定 quickly_check 形态**（最容易踩的坑）：
- interrupt → grep 错误签名/栈
- precision → 数值阈值断言（`loss>1e3`、`has_nan`、`loss_slope`）
- performance → profiler 指标阈值（`comm_ratio>0.4`）

拿 interrupt 的 grep 思路建 precision case，匹配不上。

**阶段二（全量）**：候选 ≤5 条，全量加载 body，按 `confidence.score` **降序**验证（最可靠的先试）。**先跑候选的 `quickly_check` 对照已提供的信息**：
- 先 primary（精确）
- primary 不匹配 → 跑 fallback（更模糊）
- primary 不匹配但 fallback 匹配 → 仍进验证，标 `low_confidence`
- 都不匹配 → 跳过该 case（它不是候选）

**多条候选时明示**：“匹配到 N 条，先验证最可能的 `<id>`（confidence `<score>`）”，工程师可说“跳过这条试下一条”。

**阶段二.5：reference 辅助查询（「判断缺口」消费点）**——**候选命中后固定执行，不写成"按需"**：命中只说明"这条 case 像"，不说明"该补的先验已经在手上了"。把"需不需要先验"交给当场自评，等于让最顺的那条路径永远不读先验。执行顺序（**只读 `status: active`**）：

1. **候选带 `ref_knowledge` → 先读它**：按每条 `role` 用——`signature-source`（签名的含义与判别面）、`fix-methodology`（修复路径的方法依据）、`root-cause-context`（根因成立的背景）。这是最精准的入口：关系是沉淀时写下的，不需要当场猜。
2. **然后一律取背景 summary 层**（**不是"没有 `ref_knowledge` 才取"，两者并列，不是二选一**）：`references/_summary-index.yaml`（生成索引，背景类 + active）按 `applies_to.platforms` 匹配客户平台（含 `cross` 或未填 platforms 视为跨平台），该行 `applies_to.categories` 有值时再按本轮 category 收窄；**再用本次症状里的组件 / 工具 / 平台 / 版本词在 `title` 上收窄**，取最相关的 **≤5 行**，行内 `summary` 即背景提示（不读全文），确需细节再按 `id` 读单文件。
   **为什么并列而不是"否则"**：`ref_knowledge` 是少数 case 才有的手写回链，绝大多数候选没有它——写成"否则"时，这一分支在多数单子上就被读到的人当作可省，而它恰恰是**唯一**能覆盖背景类的入口（背景类词条不参与候选路由，没有别的路径能读进来）。代价侧有界：grep 一次 + ≤5 行。**查了没有相关词条就记 `miss`**——`miss` 是覆盖缺口的信号（说明库缺这一族背景），比不查有信息。
   **用 grep 取行，别整读索引**：索引随词条数增长，整读等于把全库背景一次性注入上下文——本触发点的成本上限就是这 5 行加一次 grep。
3. **查表类（error-code / fault-pattern / env-var-table / compat-matrix）不在这里**：它们是码 / 签名 / 名 / 版本检索键，键来自证据而不是来自候选，已在步骤 2 收尾的「先验键触发」按检索键取过，此处不重复查。
4. **流程类（methodology）也不在这里**：它要的是"选中一条读全文"，走步骤 5 的流程选择器；摘要行承载不了判据。

- **只读 `status: active`**——draft / pending-review / deprecated 一律不加载（未验证知识不进上下文——这是"agent 不引用错误先验"的机制化，不是自觉）；
- **trace 三态必记**：`{action: reference_lookup, purpose: background|fix, outcome: hit|miss|skipped, ref_id, platform, output, reason}`——`hit` 读到并用了、`miss` 查了没有相关词条、`skipped` 没查（**写明为什么**，例："候选全未命中，本触发点不适用"）。没走到这一步（无候选命中）就记一条 `skipped`，别假装查过。

**数据资产探询（「数据缺口」消费点——时点：候选加载后）**：候选读完、**发现某个具体测量值（或产物）不在手上、而它决定下一步能不能走**时，按本 skill 的 `references/collect-gates.yaml`（与本文同级，**不是仓库根 references/**）执行闸门——问句、分支动作、词条绑定都在表里（id 受 CI 校验），本文不重复：

- `kind: probe`（precision / performance）→ 先问一句，按回答走「已有 → 分析路径」「没有 → 采集指引」；
- `kind: conditional`（interrupt）→ 不预先问，缺口出现（现有日志不足以定位）才给采集指引。

**探询锚点**：问句要落到这个具体缺口上（「这条 case 要确认 X，你手上有 dump 吗？」），不是开放式的「你有没有数据」——后者逼工程师先猜类别再猜产物，答错了还得第二轮。**边界（别混淆）**：锚点是"这次缺的这个值叫什么"，**不是把问句形态改成体检式的清单**；闸门表里 `question` 的措辞照旧，只是补上这次要确认的字段名或产物名。

三条纪律（只问一次 / 区分改谁 / 命令以客户环境为准 + 先排除采集副作用）见 SKILL 同名节，不在此重复。**采集面被消费时记 trace**：`{action: reference_lookup, ref_id, purpose: collect, outcome: hit|miss}`——采集面此前无 purpose 可记，等于零观测。精度 / 性能单无论如何留一条：给了采集指引记 `hit`，探询后对方已有数据（不需要采集面）记 `miss`。interrupt 单不记（本触发点不在该路径上）。

trace 记：
```yaml
- {step: 3, action: reference_lookup, ref_id: msprobe-data-dump, purpose: collect, outcome: hit}
- {step: 2, action: reference_lookup, purpose: signature, outcome: hit, ref_id: runtime-resource-fault-patterns, platform: A3-910C}
- {step: 2, action: reference_lookup, purpose: signature, outcome: skipped, ref_id: null, reason: "报错是框架自定义断言文本，无错误码 / event_id / env 名可作检索键"}
- {step: 2, action: load_index, namespaces: [...], n_cases: 34}
- {step: 3, action: quickly_check, case: MSLLM-EP-HANG-001, primary: pass}
- {step: 3, action: load_full, candidates: [...], order: by_confidence_score}
- {step: 3, action: reference_lookup, purpose: background, outcome: hit, ref_id: aclnn-two-phase-contract, platform: A3-910C}
- {step: 3, action: reference_lookup, purpose: background, outcome: miss, ref_id: null, reason: "背景层按平台+组件词取 5 行，无与本签名相关的词条"}
```

## 步骤 4：验证 diagnosis checks

顺序验证候选 case 的 `diagnosis` 检查项（**对照已提供的信息**，不跳步）。每步：
- 把 `command_template`（按 `rank_selector` 指的 rank）当作“要确认的检查”——在已提供的日志/输出里找；没有就让客户跑这条 command 并贴回输出
- 比对 `expected`
- mismatch 且有 `fix_on_mismatch` → 提示 fix（**先看 severity**）
- mismatch 且无 `fix_on_mismatch` → 该 case 不匹配，标 `excluded_cases`，试下一个
- **版本软匹配**：把候选 case 的 `compat`（framework/cann/hdk，**填了的维度**）逐维对照客户版本组合——任一维不匹配 → 标 `version_mismatch`、confidence 临时下调，**case 仍是候选**（不硬排除）；没填的维度跳过

**severity 闸门**（命中后）：
- `benign` → 给 fix
- `service-affecting` → 给 fix + 标 `fix_side_effects`（如 requires-restart）
- `data-loss-risk` → **不给 fix**，输出"先停训练、保留现场、通知 owner"

**串联保护**（误诊保护）：连续两个 case 都 fix 了但没解决 → 强制转人工，不试第三个。

**命中时的输出**（结构化、可追溯，别只甩 fix）：报出 `<CASE-ID>` + confidence（含 hits/misdiagnoses）+ 匹配的症状 + root cause + fix（severity + side_effects）+ rollback + 应用后检查。confidence 校准：`>0.8` 高可信直接应用、`0.5–0.8` 中（备 plan B）、`<0.5` 仅提示。

命中 → 步骤 6（产出）。所有候选未命中 → 步骤 5（深度排查）。

## 步骤 5：深度排查（Tier 2 未命中）

**先取流程（方法缺口消费点）**：所有候选未命中、进入本步时，按 `references/procedure-gates.yaml` 的 `kind: procedure` 闸门取流程：

1. 读 `references/_procedure-index.yaml`（**选择器**：总条数 + `category → shard + 条数 + 成本`），找本轮 category 那一行，按 `shard` 打开该分片；选择器里若另有 `_cross` 片（不限定类别），任何 category 都要一并打开；用 `title`/`summary` 选**一条**最贴合的流程——**默认一条**（前提与现场证据明确矛盾时可换一条，受"连续失败 ≤2"约束并记冲突理由）。**本 category 无对应分片** → 打开选择器列出的全部分片再选并写明这一点；
2. 按该行的 `file` 打开词条，读 **`content.flow[]` 全文**（step / action / check / when_to_use）——**摘要行不算加载**：实测只读摘要与不读等效，决定性判据会被截断；
3. 按流程执行：用每步的 `check` 当判定口径（阈值、分流条件），跳步要说明理由；
4. 某步所需数据不在手上（如流程要看"逐卡计算耗时"而导出里没有）→ **如实记 `gap`**，不臆断分支结论；
5. 记 trace：`{action: reference_lookup, ref_id, purpose: procedure, outcome: hit|miss}` + `{action: procedure_follow, ref_id, steps_executed, branch_taken, gap, conflict}`（字段见 `diagnosis-trace.md`）。选择器里没有本 category 的流程 → `outcome: miss` 并写明"流程层无此类流程"，**不静默跳过**——静默跳过让"没有可用流程"与"忘了取流程"同形。

> **别把这一步与下面的 Tier 3 检索合成一次宽检索**：`rg '<症状词>' references/ postmortems/` 看着省事，但它把"按流程查"与"按关键词翻历史记录"压成一个动作——trace 里只剩一条 `tier3`，流程层看不见自己被加载过。**两件事、两条事件**：流程取用记 `reference_lookup`（purpose: `procedure`）+ `procedure_follow`，历史检索记 `tier3`。

> **为什么必须全文**：流程携带的是**反直觉判据**（例："等得最久的卡不是慢卡，等得最少的那张才是"）。摘要会把它压没，agent 于是回到直觉判断——实测 4/4 判错；给全文 2/2 判对。


**若 Script 工具已接入**（见 script-integration.md），按 category 用：interrupt→日志/core dump、precision→`mem-analyze`、performance→`ascend-profile-analyze`/`bench-run`。**当前骨架阶段多半还没接**——别假装能调，诚实告诉工程师。

**上游修复的落地实证（给「已修复 / 升级即可」结论前必做）**

上游检索只回答"有没有人报、有没有 PR"，**不回答"你的部署版本里有没有这个修复"**。给结论前走完这几步：

1. **不接受二手结论**：release note、issue 的 closed 状态、PR 标题都不是证据——issue 被 closed 可能是配置规避或未复现；PR 可能只合进主干而未 backport 到你的 release 分支。手上只有 release note 时，结论记为**未证**。
2. **提取修复特征行**：从修复 PR 的 diff / 正文 / 关联符号里挑出**可字符串检索**的特征（新增或删除的关键代码、新方法名、新参数、报错字面量的变化）——不是"语义相近的一段"。
3. **在你部署的那份代码里核对**：用特征行在**部署版本对应的源码**上核（按上面的 `src_fetch.py` 入口按版本取）。官方 tag 快照可按"落地版本 ≤ 部署版本"推断；**镜像内代码 / fork / 定制构建一律不能按 tag 推断**，必须读那份实际代码（镜像按其冻结 commit 取）。
   - 特征行**在** → 已含；**不在** → 未修复或 backport 不全（说清是哪一种）；**拿不到该版本源码** → 结论写"无法判定"。
4. **反证规则**：同文件、同类、同名前缀的**主题相邻命中不构成证据**——同一个文件里用别的方式算了同一个量，不等于这条修复在里面。
5. **静态存在 ≠ 运行时走到**：代码里有这段修复，不等于现场走到了它——实际生效的实现由注册点 / 工厂 / 选择器 / 配置开关决定。修复位于多个实现之一时，先确认现场配置走的是含修复的那条（查注册点、选择器、开关条件），否则只报"代码已含、运行时未证"。
6. **结论分档 + 给替代动作**：已含（特征行在且运行时路径能到）／未含（特征行缺，指出是未合入还是 backport 不全）／无法判定（拿不到源码）。**别只留一个"升级"建议**——同时给不升级时的规避方案。

trace 记 `{action: run_check, check: upstream_fix_landing, verdict: present|absent|unknown, evidence: <特征行 + 文件:行>}`——结论分档靠它可回看。

**跨机时间线：先核时钟，再排先后**

"哪个 rank 先挂""哪台先断"这类排序建立在**跨机时间戳可比**这个前提上，而它从来没人验证过。时钟漂移不会报错，它只会把"最早的那个"静默换成另一个节点——结论看起来一样硬。

1. 取各机都会记录的**同一个事件**当基准（任务启动广播 / HCCL 初始化 / 集群心跳），比对各机记下的时间差；
2. 秒级以内 → 可按时间排序；
3. 明显漂移（数十秒以上）、或同一对事件在各机的先后**相反** → 把"谁先"的结论降级为不确定，报告里写明时钟存疑，不要靠"多数节点都这样"倒推；
4. 时间戳整体差**整数小时** → 多半是单机时区配置（与漂移不同，先按配置错处理）。

trace 记 `{action: run_check, check: cross_host_clock, verdict: aligned|drifted|unknown, evidence: <基准事件 + 时间差>}`；现场根本没给多机日志时记 `unknown` 并写明缺什么——"没核"与"核过、对齐"不能同形。

Tier 3 关键词检索（骨架阶段真正能用的兜底）：
```bash
rg -l '<症状关键词>' postmortems/    # top-3，读片段；含 inbox/ 未审草稿（标注未经人审）
```

trace 记 `{action: tier3, keyword: <kw>, files_read: [...]}`——Tier 3 挽救率（docs/guide/metrics.md）靠这条统计。

都没有 → 诚实说“知识库没覆盖，需手动排查；定位完用 `/skill:to-postmortem` 沉淀”。人 + agent 联合分析。

## 步骤 6：产出

- `resolution: resolved | escalated | unknown`
- 写 `traces/<session_id>.yaml`（每并发诊断一文件，含完整 trace），case resolved/escalated 后留在 `traces/`（gitignored）
- **写人读定位报告 `traces/<session_id>.report.md`**（结构与行文见 `report-template.md`）：trace 管过程可回放，对话输出管现场能行动，报告管"结论可复述 + 证据可核对 + 沉淀可执行"。**一律按深度排查规格写**——读者要据此自行判断对错并从中学机制，不因已知根因而缩水。写完过一遍 `python3 scripts/report_lint.py <报告>`（结构自检，非 CI 门禁）。
- **报告是活件，不是一次性交付物**：它必须跟着诊断走，否则第一次交付之后就开始说谎。同一份文件改到底（不另起 `report-v2`），每次修订更新元信息的"最后更新"、在第 10 节追加一行修订记录，旧结论被推翻时**降级标注而不是删掉**（读者要看到判断怎么变的）。触发点与各改哪节见 `report-template.md` 第 2 节；本步骤最常见的两处是 **用户回报 fix 结果**（改 1/6/7/8 节）与 **resume 续接**（改 7/3 节）。
- **写 `sediment_candidates`**（顶层字段，与报告第 8 节同源）：把"这单能沉淀什么"结构化——报告给人读，trace 给机器与 resume 读；trace 记一条 `{action: report, report_file, sediment_candidates: N}` 事件。
- **Tier-2 命中**：常规 postmortem 草稿
- **Tier-2 未命中但最终解决**：postmortem 含一段 agent 起草的候选 case（标 `confidence.score` 初始低值），交 groom 验证。人的角色从“结构化”上移到“验证草案”。
- **结果反馈：挂账 + 回报指令，不在这里当场追问**：给完 fix 那一刻，工程师还没应用、也没跑验证命令，此时问"解决了吗"只会得到一句"还没试"——这一问把债的产生点当成清偿点。正确顺序是：
  1. **立刻写**：`feedback: {case: <真实 case id 或占位串 pending-investigation>, outcome: pending}` + `feedback_pending_since: <当天日期>`（顶层字段，口径见 `diagnosis_state.yaml.example` 与 `trace-status.yaml`；**不再写 `feedback_pending`**，那是面板口头沿用的旧说法，脚本读不到）。写账龄是为了让这笔债可排序、可催——没有它，"挂了两周的反馈"与"昨天刚挂的"在面板上一样。
  2. **对话里给一条可复制的回报指令**，三选一、话术照抄可用：「应用后解决了吗？回我一句就行——`解决` / `没解决` / `部分解决`」。
  3. **有人回来回报时才回写**：解决 → 该 case `hits += 1`；没解决 → `misdiagnoses += 1`；两者都更新 `last_hit`，trace 记 `{action: feedback, case, outcome: resolved|not_resolved|partial}`，清 `pending`。not_resolved / partial 自动进入误诊归因（见文末）。
- **这笔债谁追**：`/skill:resume-diagnosis` 续那一单时问得其所；`/diagnose` **不在新诊断的开屏逐单念**（新问题的第一屏只服务新问题，积压时那是审讯）；面板待办面承载其余（谁欠、哪一单、欠多久），人去清。
- **`case` 按是否命中填两种之一**：命中 → **真实 case id**（回报后能回写它的 confidence）；未命中但给了建议 → 占位串 `pending-investigation`，表示"**没有 case 可回写 confidence**"——后续追问这类单时问的是"上次要求的材料拿到了吗"，不是"那个 case 的 fix 生效了吗"。反馈捕获是学习环的吞吐上限，靠文件标记而非记性。
- **沉淀已含在本步骤**：命中=常规 postmortem、未命中=含候选 case 的 postmortem，已生成。只有非 /diagnose 定位的（Kimi/手工、或没配 session-end hook 导致没生成）才需 `/skill:to-postmortem` 手动沉淀。

## 误诊归因（每次误诊必做）

误诊发生时（命中了但 fix 没解决），**先读 trace 判断 case 错还是执行错**：
- trace 显示 quickly_check 顺序对、check 执行结果对、但 root cause 判断错 → **case 错**，改库
- trace 显示 agent 跳过 fallback、加载错 namespace、没标 low_confidence → **执行错**，改 skill body 或本文件

混在一起会让 groom 改一个本来正确的 case——主动污染 KB。trace 是堵这个洞的唯一手段。

**归因的结构化落点**：归因结论记入 trace `{action: attribution, verdict: case_error|execution_error, evidence: <trace 证据摘要>}`——与 SKILL.md 反馈闭环的误诊归因要求一致。该事件是「执行-误诊归因比」指标（metrics.md）与 roadmap E2（router 从 trace 错例演进）、E5（trace 结构挖掘）的数据源。**触发不依赖用户主动报告"这个 case 不对"**——反馈闭环中答复 not_resolved/partial 即自动进入归因（SKILL.md 已内联该步骤）。
