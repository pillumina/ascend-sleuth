# 最终 HTML 报告模板规范（P7 report_generator.py）

> 本规范适用于 P7 总报告及其配套 HTML。双卡比对子报告的模板、样式和交互脚本位于 `scripts/prof_compare/`。

卡级 Prof 和已有集群输出共用 P7 主报告模板。首页分别显示用于出报的集群 Rank × Step 覆盖与可用卡级 Prof 覆盖，缺少证据的卡级章节和导航项按需省略。

## 布局硬性要求

1. **左侧固定导航栏**（`position: fixed`），不放在文档开头；右侧内容区滚动时导航高亮跟随（scrollspy）。
2. **分区顺序**（严格）：信息概览（最前）→ 结论与建议 → 集群总览（多卡）→ 进阶分析 → 性能比对 → 泳道算子统计 → prof-compare 子报告（有结果时）→ 数据说明。
3. **可折叠**：信息概览之外的所有主要分区用 `<details open>` 包裹（`<summary>` 为分区标题），用户可一键收起。
4. **禁止"卡片清单（cluster 模式）"分区**：不要罗列全部 rank 卡片清单。
5. **集群总览按 Step 区分**：Step × Rank 矩阵/分组展示，同名 rank 多 step 不得合并。
6. **进阶分析集中展示**：按拆解对比、计算、通信、Host 下发、其他特性分小节。无精选图表的分类直接展示已有结果的行数和明细链接。各类可展开查看适用条件或采集限制，完整能力清单见 `recipes_summary.md`。
7. **子报告嵌入**：有 P5 结果时，用 iframe 嵌入 `reports/compare_analysis_report.html`，同时提供新窗口链接。导航项随报告出现。
8. 时间单位统一 ms；百分数保留 1 位小数；中文字体栈 `Noto Sans CJK SC, WenQuanYi Micro Hei, Microsoft YaHei`。
9. Rank 耗时走势使用内联 Canvas。通用图表从宿主的 `data-spec` 属性直接解析内联 JSON，ECharts（CDN）不可用或图表初始化失败时展示同一份数据表。报告交互脚本和样式随 HTML 交付。`rank_timing_panel()` 片段自带作用域样式，嵌入时保留 `<style>` 并使用 `class="card rank-timing-card"`。
10. **原结论章节增强**：保留“结论与建议”的导航、锚点和章节顺序，内部增加“瓶颈定位与解决”，先给主导问题，再按通信、计算、Free 各列最多三个关键点。其他章节不以新增定位摘要取代。
11. 数据概览先展示「采集窗口与 Stage 时间构成」的指标，紧接着用一张计算、通信、Free 组合卡显示归一化严重度，之后展示概览小结。结论与建议用双栏证据工作台复用这组三类百分比。候选索引支持切换，右栏展示主指标、图表和排查线索。Free 用青色表示整步空闲覆盖，以橙色描框及箭头标出候选。计算实例参数与 PMU 默认收起。精确位置展开后保留 ms/us/ns 精度。正文不展示取证路径。
12. 附加 `insight_bottlenecks.html` 是离线定位摘要，使用内联样式且无 CDN/iframe；默认主交付仍是原完整报告。内容约束见 insight_localization.md。
13. **正文区自适应全宽**：`.main` 以 `margin-left:var(--sb-w)` 为侧边栏让位，不设宽度上限（`max-width:none`），左右内边距用 `clamp(16px,2.2vw,44px)`；仅段落/列表限制阅读宽度 `max-width:118ch`。导航收起时 `.main` 的 `margin-left` 归零。
14. **宽表统一容器 `.tw`**：`.tw { overflow:auto; max-width:100% }` 包裹 `table.tbl`；表头 `th` sticky（`top:0`）、首列 `td:first-child` sticky（`left:0`），长文本 `overflow-wrap:anywhere`，配斑马纹（`tbody tr:nth-child(even)`）+ hover 高亮。表内含热力背景色单元格时，首列吸附必须写成 `td:first-child:not([class*="heatmap"])`，避免覆盖 `.heatmap-*` 底色。
15. **阅读进度条**：页面顶部固定 `.progress`（随滚动改 `width`），窄屏（≤900px）与打印时隐藏。
16. **子报告 iframe** 统一用 `.sub-frame`（`width:100%`、`height:min(72vh,900px)`）而不是内联样式；精简版洞察报告的 `main` 同样为自适应全宽 + `clamp` 内边距。
17. **数据概览 KPI 卡片按最小宽度换行**：容器统一写 `class="kpi-row"`，禁止用 Tailwind 视口断点网格（`grid-cols-2 md:grid-cols-3 lg:grid-cols-6`）——断点按视口换行会导致中等宽度下明明放得下却被压成多行。`.kpi-row` 为 `display:flex; flex-wrap:wrap; gap:16px`，子卡片 `flex:1 1 var(--kpi-min-w); min-width:0`；默认一行平铺并等分整行，放不下时溢出卡片换行、每行各自平分本行宽度（末行落单卡片同样拉伸铺满，不设 `max-width`）。`--kpi-min-w` 取 `145px`：最长标签「未掩盖通信占比」≈98px + `p-5` 左右内边距 40px ≈ 理论下限 138px，取 145px 使「6 卡一行」的门槛（`6×145+5×16=950px` 容器）刚好覆盖 1024px 视口；不要再为窄屏加 `@media` 覆写，flex-grow 已保证每行铺满。

## 模板交互规范

任何含 `<details>` 折叠分区或 ECharts 图表的 HTML 模板，包含以下五组交互能力：

1. **左侧固定导航栏 + 锚点**：
   - P7 最终报告（page.css / page.js）：`.sidebar` 宽 `var(--sb-w)`（244px，≤1280px 降为 216px），`#nav-toggle` 收起、`#nav-open` 展开，状态落在 `body.nav-collapsed` 上并持久化到 localStorage 键 `ca-nav-collapsed`（仅在 ≥901px 时恢复）；≤900px 侧边栏自动退化为顶部块且不再隐藏（`transform:none`、`.main` 无左偏移）。
   - 窄屏（≤1023px）侧边栏退化为顶部横条（`@media` 内改 static 布局）。
   - 锚点 href 必须与对应 `<details>` 的 id 一致；侧边栏每项点击时自动展开目标 details。
2. **主要分区可折叠**：每个主要章节使用 `<details class="sec" id="sec-*" open><summary><h3>标题</h3></summary>…</details>`；**所有 details 默认带 `open` 属性**；CSS 用 `details.sec:not([open]) > summary h3::before` 渲染 ▾/▸ 指示符；`scroll-margin-top` 预留锚点定位余量。
3. **折叠容器内 ECharts 懒初始化（关键，防空白图）**：在 `<body>` 顶部 monkey-patch `echarts.init`——当图表宿主位于收起的 `<details>` 内时，不真正 init，而是返回代理对象并把 `setOption` 等调用压入 pending 队列；待该 details 首次 toggle 展开 + `requestAnimationFrame` 后再真正 init 并重放队列。任何在 details 内 init 的图表若缺少此机制，收起状态下渲染将得到零尺寸画布、展开后仍是空白（本次修复的根因）。
4. **hash 展开与定位**：页面加载与 `hashchange` 时读取 `location.hash`，若目标元素是 DETAILS 或位于某 DETAILS 内部，则展开全部祖先 details，并在 `requestAnimationFrame` 后 `scrollIntoView` 重新定位（原生锚点滚动发生在展开之前，必须补一次）。
5. **全部展开/收起 + 全局 resize**：
   - 侧边栏按钮统计所有 `details.sec`的开合状态，统一置为同一状态并交换文案"全部展开/全部收起"；**因所有 details 默认展开，按钮初始文案必须为"全部收起"**；页面无 details 时隐藏按钮。
   - 每个 details 的 toggle 事件后，在 `requestAnimationFrame` 内 `window.dispatchEvent(new Event('resize'))`，让所有已初始化图表实例适配新容器尺寸（懒加载图表 flush 时也会自身 resize）。
   - ECharts 实例统一挂在宿主元素的 `div.__chart` 上且不会自动 resize：page.js 监听 `window.resize` 做 160ms 防抖，遍历所有 `div.__chart` 调 `resize()`；导航折叠/展开与 details toggle 都会派发 `window.resize`。Canvas 版 Rank 耗时走势自带 ResizeObserver，不在此列。

## 模板工程纪律

1. **占位符**：`scripts/report_assets/template.html` 通过 `str.format` 填充，模板中的字面花括号使用双写。
2. **脚本顺序**：懒初始化 monkey-patch 必须是 `<body>` 内第一个脚本（先于所有 `echarts.init` 调用）；导航交互脚本紧跟其后；图表脚本保持在正文末尾。
3. **自包含**：所有交互 JS 内联在单文件内，不依赖外部 JS 文件；ECharts 走 CDN（与图表库同一来源）。

## 分区与导航对应表

| 导航项 | 分区 | 数据来源 |
|--------|------|----------|
| 信息概览 | 模式/卡数/step 数/耗时总览/健康徽章 | P0 + P2 |
| 结论与建议 | 总体判定 + 通信、计算、Free 的精确瓶颈；P6a 缺失时使用原汇总结论 | P1 advisor.json + P6a insight_bottlenecks.json |
| 集群总览（多卡） | Rank 耗时走势、跨 rank 的各 Step 平均耗时柱状图、短通信耗时候选 | P2/P3 |
| 专家建议 | 调优建议和各通信类型的累计耗时 Top 10 | P1 advisor.json |
| 进阶分析 | 五大类 23 recipe | P3 recipes_summary |
| 性能比对（多卡） | 最大/最小通信占比卡对比要点 | P4 |
| 泳道算子统计 | **Process（host算子）/Ascend Hardware（npu算子）/Communication 三类汇总（持续时间/自用时间/平均/最大/最小持续时间、发生次数）+ 每类持续耗时 Top10 算子表（跨卡聚合）**；P6 逐卡 md 仍含最长算子 + 全算子七列 | P6 |
| prof-compare 子报告 | 双卡比对 HTML | P5 |
| 数据说明 | 数据格式、单位、局限性 | P0 |

## Rank 耗时走势和通信榜单

- 总报告的集群总览展示 Rank 耗时走势图。横轴是排序后的卡号，纵轴是毫秒。默认显示首个 Step 的总耗时，Step 和指标均支持多选，每组组合对应一条线。
- 六个指标为总耗时（Stage）、总通信、总 Free、通算重合、纯通信（未重叠通信）和纯计算（计算减去通算重合，最小取 0）。缺少重叠字段时，可用总通信减纯通信推算。数据仍缺失时留空，并在悬停中显示 `—`。
- 卡号和前五个指标各支持升降序。多 Step 叠加时，按同一张卡在所选 Step 的可用样本均值排序，所有曲线使用同一套卡序。缺失值排最后，同值按卡号排列。
- 全量视图用 Canvas 绘制并保留每个像素列的极值。可切换显示范围，用滑块移动或按卡号直接定位。悬停读取原始 Rank 与 Step 对应的六项指标。
- 通信榜按 AllReduce、AllGather、Send、Receive 等算子类型分别取前 10 项。专家建议按全部卡累计耗时（毫秒）排名。

## 单卡模式裁剪

单卡报告展示数据概览、结论与建议、专家建议、泳道算子和附录。
