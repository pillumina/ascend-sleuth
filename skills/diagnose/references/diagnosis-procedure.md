# Diagnosis Procedure（核心循环展开）

`/diagnose` 的 SKILL.md 写主干，这里展开每步的判断细节。agent 在执行复杂分支时按需加载本文件。

## 步骤 1：收集症状 + 确认框架（全部来自工程师提供的信息）

> 你不访问任何环境。所有信息（日志、版本、报错、环境变量值）由工程师从客户那提供。信息不够时，明确提示需要向客户要什么。case 里的 `command` 是“要确认的检查”——对照已提供信息判断，或让客户跑后贴回，不是你执行 pip/env/grep。

```
必收（都从客户那要来）：错误信息、HCCL_*/ASCEND_*/NPU_* 环境变量的值、框架版本、硬件平台（A2/A3/A5）
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

**阶段一（索引）**：对每个命中 namespace，只读每条 case 的 `id/title/symptoms/quickly_check/category/confidence`（~70 token/条）。用 `quickly_check` **对照已提供的信息**：
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

trace 记：
```yaml
- {step: 2, action: load_index, namespaces: [...], n_cases: 34}
- {step: 3, action: quickly_check, case: MSLLM-EP-HANG-001, primary: pass}
- {step: 3, action: load_full, candidates: [...], order: by_confidence_score}
```

## 步骤 4：验证 diagnosis checks

顺序验证候选 case 的 `diagnosis` 检查项（**对照已提供的信息**，不跳步）。每步：
- 把 `command_template`（按 `rank_selector` 指的 rank）当作“要确认的检查”——在已提供的日志/输出里找；没有就让客户跑这条 command 并贴回输出
- 比对 `expected`
- mismatch 且有 `fix_on_mismatch` → 提示 fix（**先看 severity**）
- mismatch 且无 `fix_on_mismatch` → 该 case 不匹配，标 `excluded_cases`，试下一个

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
rg -l '<症状关键词>' postmortems/    # top-3，读片段
```

都没有 → 诚实说“知识库没覆盖，需手动排查；定位完用 `/skill:to-postmortem` 沉淀”。人 + agent 联合分析。

## 步骤 6：产出

- `resolution: resolved | escalated | unknown`
- 写 `diagnosis_state-<session_id>.yaml`（每并发诊断一文件，含完整 trace），case resolved/escalated 后移入 `postmortems/history/`
- **Tier-2 命中**：常规 postmortem 草稿
- **Tier-2 未命中但最终解决**：postmortem 含一段 agent 起草的候选 case（标 `confidence.score` 初始低值），交 groom 验证。人的角色从“结构化”上移到“验证草案”。
- **结果反馈闭环（闭合学习环，关键）**：给完 fix 后，**等工程师应用并回来报告结果**——问“应用后解决了吗？（解决 / 没解决 / 部分解决）”。解决 → 该 case `hits += 1`；没解决 → `misdiagnoses += 1`、更新 `last_hit`。不问这步，confidence 永远是初始值、学习机制空转。
- **沉淀已含在本步骤**：命中=常规 postmortem、未命中=含候选 case 的 postmortem，已生成。只有非 /diagnose 定位的（Kimi/手工、或没配 session-end hook 导致没生成）才需 `/skill:to-postmortem` 手动沉淀。

## 误诊归因（每次误诊必做）

误诊发生时（命中了但 fix 没解决），**先读 trace 判断 case 错还是执行错**：
- trace 显示 quickly_check 顺序对、check 执行结果对、但 root cause 判断错 → **case 错**，改库
- trace 显示 agent 跳过 fallback、加载错 namespace、没标 low_confidence → **执行错**，改 skill body 或本文件

混在一起会让 groom 改一个本来正确的 case——主动污染 KB。trace 是堵这个洞的唯一手段。
