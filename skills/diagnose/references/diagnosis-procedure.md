# Diagnosis Procedure（核心循环展开）

`/diagnose` 的 SKILL.md 写主干，这里展开每步的判断细节。agent 在执行复杂分支时按需加载本文件。

## 步骤 1：收集症状 + 检测框架

```
必收：错误信息、HCCL_*/ASCEND_*/NPU_* 环境变量、框架版本、硬件平台（A2/A3/A5）
框架检测：
  pip list | grep -i 'mindspeed|vllm|sglang|verl'
  env | grep -i 'MINDSPEED|VLLM|SGLANG'
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

**阶段一（索引）**：对每个命中 namespace，只读每条 case 的 `id/title/symptoms/quickly_check/category/confidence`（~70 token/条）。跑 `quickly_check`：
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

**阶段二（全量）**：候选 ≤5 条，全量加载 body，按 `confidence.score` **降序**验证（最可靠的先试）。

trace 记：
```yaml
- {step: 2, action: load_index, namespaces: [...], n_cases: 34}
- {step: 3, action: quickly_check, case: MSLLM-EP-HANG-001, primary: pass}
- {step: 3, action: load_full, candidates: [...], order: by_confidence_score}
```

## 步骤 4：验证 diagnosis checks

顺序执行候选 case 的 `diagnosis` 步骤，**不跳步**。每步：
- 跑 `command_template`（按 `rank_selector` 展开）
- 比对 `expected`
- mismatch 且有 `fix_on_mismatch` → 提示 fix（**先看 severity**）
- mismatch 且无 `fix_on_mismatch` → 该 case 不匹配，标 `excluded_cases`，试下一个

**severity 闸门**（命中后）：
- `benign` → 给 fix
- `service-affecting` → 给 fix + 标 `fix_side_effects`（如 requires-restart）
- `data-loss-risk` → **不给 fix**，输出"先停训练、保留现场、通知 owner"

**串联保护**（误诊保护）：连续两个 case 都 fix 了但没解决 → 强制转人工，不试第三个。

命中 → 步骤 5。所有候选未命中 → 深度排查。

## 步骤 5：深度排查（Tier 2 未命中）

按 category 选默认 Script（见 script-integration.md）：
- interrupt → 日志分析 / core dump
- precision → `mem-analyze`（tensor 对比基线）
- performance → `ascend-profile-analyze` / `bench-run`

Tier 3 关键词检索：
```bash
rg -l '<症状关键词>' postmortems/    # top-3，读片段
```

人 + agent 联合分析。

## 步骤 6：产出

- `resolution: resolved | escalated | unknown`
- 写 `diagnosis_state.yaml`（含完整 trace），case resolved/escalated 后移入 `postmortems/history/`
- **Tier-2 命中**：常规 postmortem 草稿
- **Tier-2 未命中但最终解决**：postmortem 含一段 agent 起草的候选 case（标 `confidence.score` 初始低值），交 groom 验证。人的角色从“结构化”上移到“验证草案”。
- **解决后主动建议沉淀**：尤其 Tier-2 未命中的新问题——主动问“要把这次沉淀成 case 吗？”并建议 `/skill:to-postmortem`。这是知识库增长的主要来源，别让工程师忘了沉淀。

## 误诊归因（每次误诊必做）

误诊发生时（命中了但 fix 没解决），**先读 trace 判断 case 错还是执行错**：
- trace 显示 quickly_check 顺序对、check 执行结果对、但 root cause 判断错 → **case 错**，改库
- trace 显示 agent 跳过 fallback、加载错 namespace、没标 low_confidence → **执行错**，改 skill body 或本文件

混在一起会让 groom 改一个本来正确的 case——主动污染 KB。trace 是堵这个洞的唯一手段。
