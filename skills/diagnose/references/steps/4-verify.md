# 步骤 4：验证 diagnosis checks

> **何时读**：候选加载后逐条验证时。
> **完成判据**：每条候选有 pass / fail / conflict / 先验否决 结论；不匹配的进 `excluded_cases`；命中进入步骤 6，全部排除（含被先验否决）进入步骤 5。
> **本步产出**：`run_check` / `hit` / `miss` 事件与 `excluded_cases`。

顺序验证候选 case 的 `diagnosis` 检查项（**对照已提供的信息**，不跳步）。每步：
- 把 `command_template`（按 `rank_selector` 指的 rank）当作“要确认的检查”——在已提供的日志/输出里找；没有就让客户跑这条 command 并贴回输出
- 比对 `expected`
- mismatch 且有 `fix_on_mismatch` → 提示 fix（**先看 severity**）
- mismatch 且无 `fix_on_mismatch` → 该 case 不匹配，标 `excluded_cases`，试下一个
- **版本软匹配**：把候选 case 的 `compat`（framework/cann/hdk，**填了的维度**）逐维对照客户版本组合——任一维不匹配 → 标 `version_mismatch`、排序分数临时下调，**case 仍是候选**（不硬排除）；没填的维度跳过

**severity 闸门**（命中后）：按 SKILL 的「severity 闸门」一节判，命中 `data-loss-risk` 不给 fix。

**串联保护**（误诊保护）：连续两个 case 都 fix 了但没解决 → 强制转人工，不试第三个。

**命中前做一次先验约束检查（有可对照事实时才做）**：拿这次诊断已查到的背景事实（步骤 2 的 `background` 命中、平台 / 软件事实、compat 矩阵里的「不兼容」信号）反证候选的修复前提：

- 事实明确排除修复的前提（该平台不支持这个开关、该组件在这个版本不存在、compat 写着不兼容），且事实的适用面与现场一致 → `verdict: contradicted`：这个候选不记 `hit`，把候选 id 写在 `run_check` 的 `candidate` 字段（**不写进 `excluded_cases`**，它是 case id 列表，混进说明会被当 case 记账），然后继续验证下一个候选；全部候选都被先验否决 → 进入步骤 5。之后若证据推翻该事实，重跑一次检查、`consistent` 即可 hit；
- 事实相关但适用面对不上（平台不同、版本没记录、事实没写适用面）→ `verdict: unknown`：可以 hit，但把这条事实写成修复的第 0 步核验；
- 不矛盾 → `verdict: consistent`。

**版本不同不算矛盾**：compat 只给「未列出 / 不匹配」时仍按软匹配降分、候选照常保留；只有矩阵明确写「不兼容」才进上面第一条。

trace 记 `{step: 4, action: run_check, check: prior_constraint, verdict: consistent|contradicted|unknown, ref_id, candidate}`。这次诊断没有可对照的事实就不做这一步，也不记空的 `unknown`。快路同样做：有可对照事实施行，没有就跳过。

**`hit` 事件记 `ref_ids`**：把支撑这条 fix 的 `fix` / `background` 词条 id 写进 hit 事件的 `ref_ids`（没有就写空列表）。误诊归因按它落到具体词条；不写，这条 fix 的依据就断了线，先验层的问题也记不成 `fix_basis`。

**出现新检索键时补查一次背景**：验证中看到步骤 2 时还不存在的检索键（新组件名 / 新版本 / 新平台词），且这个词在这一次诊断此前的查询里没用过 → 补查一次背景层，记一条 `reference_lookup`，`purpose: background`，`reason: "new-evidence: <新词>"`。这一次诊断最多补查一次；同一个词不重复查。

**命中时的输出**：按 `6-deliver.md` 的「命中时的输出格式」给结果，别只甩 fix。

命中 → 步骤 6（产出）。所有候选未命中 → 步骤 5（深度排查）。

**读日志验证时顺手写故障过程**：材料里有日志、且能读出状态转折（从什么状态转到什么、哪一行开始、重复多久）→ 按 `../diagnosis-trace.md` 的「顶层 `failure_process`」写进 trace；只贴一行原文不够。没有日志材料就不写。