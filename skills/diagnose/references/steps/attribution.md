# 误诊归因（每次误诊必做）

> **何时读**：回报 `not_resolved` / `partial`，或判断某个 case 的 fix 没生效时。
> **完成判据**：写出 `attribution` 事件（`verdict` = `case_error` / `execution_error`），并按 verdict 走对应修法。
> **本步产出**：一条 `attribution` 事件；`case_error` 进库改动，`execution_error` 进 skill 改动。

误诊发生时（命中了但 fix 没解决），**先读 trace 判断 case 错还是执行错**：
- trace 显示 quickly_check 顺序对、check 执行结果对、但 root cause 判断错 → **case 错**，改库
- trace 显示 agent 跳过 fallback、加载错 namespace、没标 low_confidence → **执行错**，改 skill body 或本文件

混在一起会让 groom 改一个本来正确的 case——主动污染 KB。trace 是堵这个洞的唯一手段。

**fix 依据过哪些先验也要归因**：命中单的 hit 事件里有 `ref_ids`（支撑 fix 的 `fix` / `background` 词条 id）。回报 `not_resolved` / `partial` 时，对每个 id 记一条 `{action: attribution, verdict, component: "reference:<id>", attribution_scope: fix_basis, evidence}`——只记结论明确引用过的 id，没引用不记。它进组件失败簇（`component_tally.py`）供人判，**不自动退役词条**：fix 失败常是环境或操作问题，不是先验错。

**归因的结构化位置**：归因结论记入 trace `{action: attribution, verdict: case_error|execution_error, evidence: <trace 证据摘要>}`——与 SKILL.md 的反馈记录与误诊归因要求一致。该事件是「执行-误诊归因比」指标（metrics.md）与两项后续工作的数据源：router 从 trace 错例演进、trace 结构挖掘。**触发不依赖用户主动报告"这个 case 不对"**——反馈记录中答复 not_resolved/partial 即自动进入归因（SKILL.md 已内联该步骤）。