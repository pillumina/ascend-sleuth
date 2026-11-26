# 步骤 4：验证 diagnosis checks

> **何时读**：候选加载后逐条验证时。
> **完成判据**：每条候选有 pass / fail / conflict 结论；不匹配的进 `excluded_cases`；命中进入步骤 6，全部排除进入步骤 5。
> **本步产出**：`run_check` / `hit` / `miss` 事件与 `excluded_cases`。

顺序验证候选 case 的 `diagnosis` 检查项（**对照已提供的信息**，不跳步）。每步：
- 把 `command_template`（按 `rank_selector` 指的 rank）当作“要确认的检查”——在已提供的日志/输出里找；没有就让客户跑这条 command 并贴回输出
- 比对 `expected`
- mismatch 且有 `fix_on_mismatch` → 提示 fix（**先看 severity**）
- mismatch 且无 `fix_on_mismatch` → 该 case 不匹配，标 `excluded_cases`，试下一个
- **版本软匹配**：把候选 case 的 `compat`（framework/cann/hdk，**填了的维度**）逐维对照客户版本组合——任一维不匹配 → 标 `version_mismatch`、排序分数临时下调，**case 仍是候选**（不硬排除）；没填的维度跳过

**severity 闸门**（命中后）：按 SKILL 的「severity 闸门」一节判，命中 `data-loss-risk` 不给 fix。

**串联保护**（误诊保护）：连续两个 case 都 fix 了但没解决 → 强制转人工，不试第三个。

**命中时的输出**：按 `6-deliver.md` 的「命中时的输出格式」给结果，别只甩 fix。

命中 → 步骤 6（产出）。所有候选未命中 → 步骤 5（深度排查）。

**读日志验证时顺手写故障过程**：材料里有日志、且能读出状态转折（从什么状态转到什么、哪一行开始、重复多久）→ 按 `../diagnosis-trace.md` 的「顶层 `failure_process`」写进 trace；只贴一行原文不够。没有日志材料就不写。