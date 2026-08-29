# Diagnosis Procedure（核心循环展开）

`/diagnose` 的 SKILL.md 写主干，这里展开每步的判断细节。agent 在执行复杂分支时按需加载本文件。

## 步骤 1：收集症状 + 确认框架（全部来自工程师提供的信息）

> 你不访问任何环境。所有信息（日志、版本、报错、环境变量值）由工程师从客户那提供。信息不够时，明确提示需要向客户要什么。case 里的 `command` 是“要确认的检查”——对照已提供信息判断，或让客户跑后贴回，不是你执行 pip/env/grep。

```
必收（都从客户那要来）：错误信息、HCCL_*/ASCEND_*/NPU_* 环境变量的值、版本组合
  （引擎版本 + CANN 版本 + HDK/驱动版本 + 架构 A2/A3/A5）
框架：从提供的信息/报错判断（日志里 mindspeed/vllm 字样等）；判断不了就问工程师
  “客户跑的什么框架”——不要跑 pip list（那是你本地环境，跟客户无关）
```

**日志裁剪（硬要求）**：诊断 session 的 context 八成是日志/profiler，不是 KB。一份 128 卡全量 profiler 灌进来直接滑出 smart zone（~120K token 推理最锐利），推理质量暴跌。裁剪规则：
- 只贴**失败 rank**的日志（`rank_selector` 指定的：coordinator / all_failed / by_topology）
- 只贴报错**栈尾**（最后 N 行，含第一个 ERROR）
- profiler 数据先过 `ascend-profile-analyze` 出 `report.md`，只读报告不读原始数据

## 步骤 2：分类 → triage-tree

加载 `triage-tree.yaml`。症状匹配分支（正则兼容的模糊匹配）。每个分支带 `category`（interrupt / precision / performance）。

**triage 决策必记 trace**：
```yaml
- {step: 1, action: triage, branch: training_interrupt, category: interrupt, routed: [training/mindspeed-llm/, common/]}
```

路由规则：
- 框架检测到 → `search_namespaces` 先 `training|inference/<framework>/`，再 `common/`
- 框架未检测到 → 只 `common/`
- **优雅退化**：多个分支弱匹配 / 置信度低 → 加载**所有 namespace 的索引**让 quickly_check 筛（索引便宜，退化最坏 ~20K token 仍可控）。这救冷启动——triage-tree 第一周是猜的。
- 无法分类 → 直接 Tier 3 关键词检索

**路由准确率**依赖这步的 trace：最终 root cause 所在 namespace 是否在被加载集合里（指标定义见 docs/metrics.md）。路由错（分错桶）和 KB 空（分对了没 case）修复动作相反，必须分开测。

## 步骤 3：两阶段加载 Tier 2

**阶段一（索引）**：读 `knowledge/_index.yaml`（`scripts/build_index.py` 生成的结构化索引，已含每条 case 的 `id/title/symptoms/quickly_check/category/confidence` + `file` 定位，~70 token/条），取命中 namespace 的条目——两阶段加载由**结构**保证，不靠逐文件打开的自觉。索引缺失或 `build_index.py --check` 报过期 → 兜底：逐文件只读上述索引字段，并提醒重建索引。用 `quickly_check` **对照已提供的信息**：
- 先 primary（精确）
- primary 不匹配 → 跑 fallback（更模糊）
- primary 不匹配但 fallback 匹配 → 仍进阶段二，标 `low_confidence`
- 都不匹配 → 跳过该 case

**空库提示（冷启动）**：若命中 namespace 为空（还没 case），**不要静默退化**——告诉用户“当前 `knowledge/<ns>/` 还没有验证过的 case，你可以：①继续深度排查（步骤 5）②诊断完跑 `/skill:to-postmortem` 沉淀成第一条 case ③转人工”。空库的体感不该是“啥也不会”。

**category 决定 quickly_check 形态**（最容易踩的坑）：
- interrupt → grep 错误签名/栈
- precision → 数值阈值断言（`loss>1e3`、`has_nan`、`loss_slope`）
- performance → profiler 指标阈值（`comm_ratio>0.4`）

拿 interrupt 的 grep 思路建 precision case，匹配不上。

**阶段二（全量）**：候选 ≤5 条，全量加载 body，按 `confidence.score` **降序**验证（最可靠的先试）。**多条候选时明示**：“匹配到 N 条，先验证最可能的 `<id>`（confidence `<score>`）”，工程师可说“跳过这条试下一条”。

**阶段二.5：reference 辅助查询（先验知识层）**——候选加载后、验证前，按需取先验知识辅助诊断：

- **只读 `status: active` 词条**——draft / pending-review / deprecated 一律不加载（未验证知识不进上下文——这是"agent 不引用错误先验"的机制化，不是自觉）；
- **两条加载路径**：
  1. 候选 case 有 `ref_knowledge` → 加载引用的 reference 全文（最精准；当前 case 尚无此字段，未来路径）；
  2. 否则/同时：按客户平台扫 `references/<type-dir>/*.yaml` 中 `applies_to.platforms` 匹配且 active 的词条，**只读 `summary` + `applies_to`**（每条一行；A5 全量 ~700 token 内）；
- **按需全文**：验证具体事实需要细节（如 950DT 内存规格、HiF8 指数范围）才读全文；
- **token 纪律**：只在命中候选后查询，summary 层先于全文层，平台不匹配不加载（当前仅 A5 有词条，A2/A3 场景自然跳过）；
- **trace 必记**：每次查询记 `{action: reference_lookup, ref_id, platform, purpose: signature|fix|background}`——reference 命中统计（hits/last_hit）的数据源。

trace 记：
```yaml
- {step: 2, action: load_index, namespaces: [...], n_cases: 34}
- {step: 3, action: quickly_check, case: MSLLM-EP-HANG-001, primary: pass}
- {step: 3, action: load_full, candidates: [...], order: by_confidence_score}
- {step: 3, action: reference_lookup, ref_id: a5-950dt-memory-spec, platform: A5-950DT, purpose: background}
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

**若 Script 工具已接入**（见 script-integration.md），按 category 用：interrupt→日志/core dump、precision→`mem-analyze`、performance→`ascend-profile-analyze`/`bench-run`。**当前骨架阶段多半还没接**——别假装能调，诚实告诉工程师。

Tier 3 关键词检索（骨架阶段真正能用的兜底）：
```bash
rg -l '<症状关键词>' postmortems/    # top-3，读片段；含 inbox/ 未审草稿（标注未经人审）
```

trace 记 `{action: tier3, keyword: <kw>, files_read: [...]}`——Tier 3 挽救率（docs/metrics.md）靠这条统计。

都没有 → 诚实说“知识库没覆盖，需手动排查；定位完用 `/skill:to-postmortem` 沉淀”。人 + agent 联合分析。

## 步骤 6：产出

- `resolution: resolved | escalated | unknown`
- 写 `diagnosis_state-<session_id>.yaml`（每并发诊断一文件，含完整 trace），case resolved/escalated 后移入 `postmortems/history/`
- **Tier-2 命中**：常规 postmortem 草稿
- **Tier-2 未命中但最终解决**：postmortem 含一段 agent 起草的候选 case（标 `confidence.score` 初始低值），交 groom 验证。人的角色从“结构化”上移到“验证草案”。
- **结果反馈闭环（闭合学习环，关键）**：给完 fix 后，**等工程师应用并回来报告结果**——问“应用后解决了吗？（解决 / 没解决 / 部分解决）”。解决 → 该 case `hits += 1`；没解决 → `misdiagnoses += 1`、更新 `last_hit`。不问这步，confidence 永远是初始值、学习机制空转。
- **反馈捕获结构化**：给完 fix、session 收尾前往 state 文件写 `feedback_pending: <case-id>`；**任何 diagnose/resume 启动先扫活跃 state 的该标记**，有就先追问结果——回写 confidence、trace 记 `{action: feedback, case, outcome: resolved|not_resolved|partial}`、清标记。反馈捕获是学习环的吞吐上限，靠文件标记而非记性。
- **沉淀已含在本步骤**：命中=常规 postmortem、未命中=含候选 case 的 postmortem，已生成。只有非 /diagnose 定位的（Kimi/手工、或没配 session-end hook 导致没生成）才需 `/skill:to-postmortem` 手动沉淀。

## 误诊归因（每次误诊必做）

误诊发生时（命中了但 fix 没解决），**先读 trace 判断 case 错还是执行错**：
- trace 显示 quickly_check 顺序对、check 执行结果对、但 root cause 判断错 → **case 错**，改库
- trace 显示 agent 跳过 fallback、加载错 namespace、没标 low_confidence → **执行错**，改 skill body 或本文件

混在一起会让 groom 改一个本来正确的 case——主动污染 KB。trace 是堵这个洞的唯一手段。

**归因的结构化落点**：归因结论记入 trace `{action: attribution, verdict: case_error|execution_error, evidence: <trace 证据摘要>}`——与 SKILL.md 反馈闭环的误诊归因要求一致。该事件是「执行-误诊归因比」指标（metrics.md）与 roadmap E2（router 从 trace 错例演进）、E5（trace 结构挖掘）的数据源。**触发不依赖用户主动报告"这个 case 不对"**——反馈闭环中答复 not_resolved/partial 即自动进入归因（SKILL.md 已内联该步骤）。
