# ev-panel —— 自演进看板（DSH 插件）

对话视图第三个 tab「自演进」：把 evolve-check / self-evolve 产出的演进状态可视化，
让"看到系统在自演进"成为可能。

## 设计取向（2026-09 重做）

旧版把 EV 卡当**实时看板**画——9 个状态分组 + 卡片平铺。实测失效：

1. **状态词表过期**：分组用的是 v1 词表（`candidate/proposed/pending_merge/adopted/rolled_back`），
   而 schema v5（`scripts/verify_proposals.py` 的 `VALID_STATUS`）只有
   `in_experiment / validated / rejected / superseded`——9 个状态里 5 个永不会出现，
   `rejected/superseded` 反而漏渲染。
2. **数据被丢**：host 只取 14 个字段，`hypothesis / validation / gate / cost / 决策链全文` 全没传；
   client 再把仅剩的 `decisions` 截成「最后一条前 70 字」。实测每张卡平均 4 条 decision、
   conclusion 合计约 840 字（最长 698 字）——面板展示约 0.5%。
3. **只增不减的墙**：31/36 张卡落在 `validated`，看板退化成不动、只增长的档案墙。

新版按三层重排，回答三个问题：

| 层 | 回答的问题 | 组件 |
|---|---|---|
| ① 待办/待审优先 | 现在该看哪张卡 | `FocusStrip`：实验中 / 审计缺口 / 最近采纳（可点进筛选）+ 采纳率、成本中位、最久未闭合 |
| ② 可展开决策流 | 到底是什么、优化了什么 | `DecisionFeed` + `IdeaCard`：收起一行（状态/层/授权/缺口/PR 指针 + 结论摘要），点开显示假设 → 预期效果 → 验证与门控 → 触发信号 → 决策链全文（时间轴）→ 设计原则 |
| ③ 自演进度量 | 系统在往哪走 | `StatsPanel`（状态分布/采纳率/验证方式/信号来源）+ timeline sparkline + 容量压力 + 归因信号 |
| ④ 执行现场（exec-log） | **每次内容流程收尾，evolve-check 到底跑没跑** | `ExecLogSection`：收尾次数 / 其中无信号次数 / 最近执行的 skill·产出·理由；本地件（`.gitignore` 运行时件，跨 worktree 不聚合，区块内显式标注） |

**归档折叠**：已采纳且无缺口的卡默认收进「归档 N 张」，不再占满首屏。
**诚实退化**：归因/S2 无数据时只留一行说明，不占位。
**④ 为什么必须有**（2026-09-10 审计）：exec-log 此前只被 evolve-check 第 1 步读，面板与 metrics
都不看它，且 evolve-check 自己不落记录 → "收尾跑了但无演进信号"与"根本没跑"在数据上完全不可区分，
机制是否在运作无法证伪。现在内容流程（含 groom）与 evolve-check 各自收尾都落一条（无信号也落），
面板把这份本地现场端到人眼前；一次都没跑时给琥珀色提示而不是空白。

### 卡自审（`gaps`）

面板按 `docs/evolution-pipeline.md` §7「生命周期完整性规则」自审每张卡，报出机制缺口：

| gap | 判据 |
|---|---|
| `no_decision` | 终态卡无 `decision` 记录（审计缺口） |
| `no_cost` | `validated` 卡 `actual_cost.tokens` 为空（成本审计缺口） |
| `status_lag` | 已记 `decision` 但状态仍 `in_experiment`（状态未推进） |
| `stale` | `in_experiment` 超过 `STALE_DAYS`（14 天）未闭合 |

**注意**：这些缺口该由**机制推进**修，不是等人逐卡审批——EV 卡是 agent 决策档案，
人审发生在聚合 PR 上（审整个自演进过程是否 solid）。

**与 CI 同口径**（2026-09-10）：上表判据与 `scripts/verify_proposals.py`（kb-checks 的
`proposal-audit` job）**逐条对齐**——面板报的缺口和 CI 拦的错是同一件事，不允许"CI 绿但面板
报缺口"（此前 CI 只校验终态卡、且根本不在 CI 里跑；面板比它严，两者长期各说各话）。
面板是提示面，CI 是硬门；口径一份。


## 视觉层（精密仪器感，2026-09）

信息架构不动，视觉与交互全部重做。样式走 `styles.insert(css)` 的 class 体系——内联 style
做不到 hover / focus / 过渡，这是旧版"看起来平"的根因。

**修掉的三个结构性视觉缺陷**（都是实测发现的，不是审美偏好）：

| 缺陷 | 实测 | 修法 |
|---|---|---|
| 亮色下表面零分层 | `bg-layer-1` 与 `-2` 是同一个白（design-platform.css），卡片与页面同色 | 引入 `--surf` 叠加层（`background-image` 叠在底色上），暗色置空 |
| 发丝线不可见 | 亮色 `border-l1` 只有 4% 黑 | 引入 `--hair = color-mix(tx 9%)`，暗色回落到 `border-l1` |
| 多处对比度不达 WCAG AA | 白字实心徽标 3.68:1、聚焦大数字 2.15:1、判断标签 3.29:1 | 颜色按角色分层：`--c-*` 文字色取深档、`--acc-*` 装饰色、`--fill-*` 实心底；暗色反相为亮而饱和的色值 |

**主题判定**跟随 DSH 的 `body[data-ds-dark-theme]`，**不用** `prefers-color-scheme`——
系统主题与 DSH 主题可以不一致（实测本机就是暗系统 + 亮 DSH）。

**动效**：120–260ms `cubic-bezier(.22,1,.36,1)`（ease-out-quart 族）——卡片 hover 抬升
1px、展开用 `grid-template-rows` 过渡（不动画 height，避免 layout 抖动）、chevron 旋转、
首屏六段依次浮现；`prefers-reduced-motion` 下全部关闭。键盘可达：卡头是 `<button>`，
带 `aria-expanded` 与 `:focus-visible` 环。


### 配色与性能（2026-09 二轮）

**配色不发暗沉**：旧做法是"品牌色混黑"来满足对比度——混黑把饱和度一起压掉了。
改为**手选色值**（逐色算过 WCAG）：亮色文字色 `#1d4ed8 / #15803d / #7c3aed / #92400e / #b91c1c / #64748b`，
暗色反相为 `#7db3fc / #5cd68f / #b39bfb / #fbbf24 / #fb8a8a / #a8b0bd`；
实心徽标底独立为 `--fill-*`（原色配白字只有 3.68:1）；徽标底色浓度独立成 `--tint`（9%）。

**展开不卡**：用真 React 预览实测帧间隔，修复前首开有 **49.9ms 尖峰**（平均 22.8ms，掉出 60fps）。
三个原因与修法：

| 原因 | 修法 |
|---|---|
| 父级 setState 让 36 张卡全部重渲染（319 个 DOM 节点重算） | `React.memo` 包 `IdeaCard`（带兜底：`React.memo` 不在 Builtin 声明里） |
| 异步 detail 到达时插入整块内容，高度在动画中途二次跳 | 加载期先渲染骨架占位（`--surf` 微光条），高度目标稳定 |
| 首帧才发起 RPC，点开后要等一轮 | **悬停/聚焦即预取**（`onPointerEnter` / `onFocus`），点开时数据已就绪 |

修复后：全部轮次稳定 **16.67ms**，0 个超 20ms 帧。展开时长 0.26s → 0.2s，内容淡入 0.16s 与高度过渡错开。


### 面板统一色语（2026-09 三轮）

同一界面里的面板必须是同一种风格，所以颜色按**角色**统一，不各写各的：

| 角色 | 用途 | 取值 |
|---|---|---|
| `--c-*` | 文字色（需过 WCAG AA） | 深一档同色相：亮 `#1d4ed8/#15803d/#7c3aed/#92400e/#b91c1c/#64748b` |
| `--acc-*` | 装饰色：点 / 条 / 边框 / 渐变（大块面，非文字） | **两面板逐色同值**：`#3b82f6/#22c55e/#8b5cf6/#f59e0b/#ef4444/#9ca3af` |
| `--fill-*` | 实心徽标底（白字或深字需过 AA） | 比 `--c-*` 再深一档 |
| `--btn-*` | 渐变按钮端色 | 与诊断面板同一组（压深一档过 AA） |

**为什么文字色不与装饰色同值**：诊断面板原先直接把亮色当文字用（绿 2.28:1、琥珀 2.15:1，
都不达 AA）。统一风格的正确做法是统一**角色**——同一角色同一色相、装饰色逐色一致，
文字色各自取能过 AA 的深档。

**标题色标**与诊断面板同渐变 `linear-gradient(180deg, var(--acc-blue), var(--acc-purple))`。

校验：`python3 scripts/check_panel_tokens.py` —— 断言两面板角色集合一致、装饰色同值。

## 回归校验

`scripts/panel_render_check.js`（Node，无浏览器依赖）用 mock React + 真实数据跑两个面板客户端，
断言关键信息确实渲染出来（决策链全文未被截断、v5 词表、变化对照、归档折叠、配色角色契约等）：

```
node scripts/panel_render_check.js      # 全绿退出码 0
PANEL_DEBUG=1 node scripts/panel_render_check.js   # 打印渲染片段
```

它是"渲染逻辑 + 数据契约"的离线闸门，不替代浏览器验证。视觉类指标（对比度、帧间隔、
像素分布）在改样式时用浏览器实测过一次即可，不留常驻脚本——真正需要机械兜住的是
"渲染没坏、配色角色没漂"，那两件事由本脚本 + `check_panel_tokens.py` 负责。
