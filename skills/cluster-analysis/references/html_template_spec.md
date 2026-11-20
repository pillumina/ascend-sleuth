# 最终 HTML 报告模板规范（P7 report_generator.py）

> 本规范同时适用于 skill 产出的**所有 HTML 模板**：P7 最终报告（report_generator.py 内嵌模板）、vendor/cluster-output-analysis 的 2 个集群模板、vendor/prof-compare 的 HTML 报告。任何新增/修改 HTML 模板时必须遵守下述"模板交互规范"。

## 布局硬性要求

1. **左侧固定导航栏**（`position: fixed`），不放在文档开头；右侧内容区滚动时导航高亮跟随（scrollspy）。
2. **分区顺序**（严格）：信息概览（最前）→ 结论与建议 → 集群总览（多卡）→ 进阶分析 → 性能比对 → 泳道算子统计 → 子报告 → 数据说明。
3. **可折叠**：信息概览之外的所有主要分区用 `<details open>` 包裹（`<summary>` 为分区标题），用户可一键收起。
4. **禁止"卡片清单（cluster 模式）"分区**：不要罗列全部 rank 卡片清单。
5. **集群总览按 Step 区分**：Step × Rank 矩阵/分组展示，同名 rank 多 step 不得合并。
6. **进阶分析集中展示**：单一"进阶分析"分区内按五大类（拆解对比类/计算类/通信类/Host下发类/其他特性）分小节，每小节直接展示分析结果（表格化摘要或链接）；**不展示"能力执行状态"矩阵**（不罗列哪些能力已执行/未执行），完整能力清单见文末 recipes_summary.md。
7. **子报告嵌入**：vendor 产出的 `cluster_analysis_report.html`、`compare_analysis_report.html` 复制进 `reports/` 同目录，最终报告中以"子报告"分区 iframe 嵌入 + 新窗口打开链接双通道提供。
8. 时间单位统一 ms；百分数保留 1 位小数；中文字体栈 `Noto Sans CJK SC, WenQuanYi Micro Hei, Microsoft YaHei`。
9. 图表用 ECharts（CDN + 内联降级）；单文件自包含（内联 CSS/JS），除 iframe 引用的子报告外不依赖外部文件。
10. **原结论章节增强**：保留“结论与建议”的导航、锚点和章节顺序，内部增加“瓶颈定位与解决”，先给主导问题，再按通信、计算、Free 各列最多三个关键点。其他章节不以新增定位摘要取代。
11. 瓶颈表使用中文四列：Insight 定位、主要问题、影响程度、可能原因与处理方向。精确位置保留 ms/us/ns 精度；内部机器字段保持兼容。正文不展示取证路径。
12. 附加 `insight_bottlenecks.html` 是离线定位摘要，使用内联样式且无 CDN/iframe；默认主交付仍是原完整报告。内容约束见 insight_localization.md。

## 模板交互规范（所有 HTML 模板统一执行）

任何含 `<details>` 折叠分区或 ECharts 图表的 HTML 模板，必须包含以下五组交互能力（cluster-analysis 2 个模板已内置同款实现，可作为标准参考实现；prof-compare 为悬浮卡片式导航 + 通用 details 版本）：

1. **左侧固定导航栏 + 锚点**：
   - cluster-analysis 模板：`.sidebar`（fixed、宽 200px、`#0b1220`），主内容区加 `lg:ml-52` 偏移；含标题、分区锚点列表、`#toggle-all` 全部展开/收起按钮、底部标识（如 `{{PATH_A}}` / `Rank {{RANK_ID}}`）。
   - prof-compare：`.nav-sidebar` 悬浮卡片（宽 168px），目录锚点 + `#toggle-details` 按钮。
   - 窄屏（≤1023px）侧边栏退化为顶部横条（`@media` 内改 static 布局）。
   - 锚点 href 必须与对应 `<details>` 的 id 一致；侧边栏每项点击时自动展开目标 details。
2. **主要分区可折叠**：每个主要章节使用 `<details class="sec" id="sec-*" open><summary><h3>标题</h3></summary>…</details>`；**所有 details 默认带 `open` 属性（全部默认展开，含 vendor 子报告模板）**；CSS 用 `details.sec:not([open]) > summary h3::before` 渲染 ▾/▸ 指示符；`scroll-margin-top` 预留锚点定位余量。
3. **折叠容器内 ECharts 懒初始化（关键，防空白图）**：在 `<body>` 顶部 monkey-patch `echarts.init`——当图表宿主位于收起的 `<details>` 内时，不真正 init，而是返回代理对象并把 `setOption` 等调用压入 pending 队列；待该 details 首次 toggle 展开 + `requestAnimationFrame` 后再真正 init 并重放队列。任何在 details 内 init 的图表若缺少此机制，收起状态下渲染将得到零尺寸画布、展开后仍是空白（本次修复的根因）。
4. **hash 展开与定位**：页面加载与 `hashchange` 时读取 `location.hash`，若目标元素是 DETAILS 或位于某 DETAILS 内部，则展开全部祖先 details，并在 `requestAnimationFrame` 后 `scrollIntoView` 重新定位（原生锚点滚动发生在展开之前，必须补一次）。
5. **全部展开/收起 + 全局 resize**：
   - 侧边栏按钮统计所有 `details.sec`（prof-compare 为所有 `details`）的开合状态，统一置为同一状态并交换文案"全部展开/全部收起"；**因所有 details 默认展开，按钮初始文案必须为"全部收起"**；页面无 details 时隐藏按钮。
   - 每个 details 的 toggle 事件后，在 `requestAnimationFrame` 内 `window.dispatchEvent(new Event('resize'))`，让所有已初始化图表实例适配新容器尺寸（懒加载图表 flush 时也会自身 resize）。

## 模板工程纪律

1. **占位符复用**：cluster-analysis 模板由 `generate_cluster_report.py` 以全局 `str.replace` 填充，同一占位符可在导航与正文多处出现（如 `{{PATH_A}}`）；改模板时不得增删占位符拼写。
2. **f-string 转义**：prof-compare 的 `html_generator.py` 用 Python f-string 拼 HTML，注入的 JS/CSS 大括号必须双写 `{{ }}`，否则 KeyError/语法错。
3. **脚本顺序**：懒初始化 monkey-patch 必须是 `<body>` 内第一个脚本（先于所有 `echarts.init` 调用）；导航交互脚本紧跟其后；图表脚本保持在正文末尾。
4. **自包含**：所有交互 JS 内联在单文件内，不依赖外部 JS 文件；ECharts 走 CDN（与图表库同一来源）。

## 分区与导航对应表

| 导航项 | 分区 | 数据来源 |
|--------|------|----------|
| 信息概览 | 模式/卡数/step 数/耗时总览/健康徽章 | P0 + P2 |
| 结论与建议 | 总体判定 + 通信、计算、Free 的精确瓶颈；P6a 缺失时使用原汇总结论 | P1 advisor.json + P6a insight_bottlenecks.json |
| 集群总览（多卡） | Step×Rank 耗时拆解 + **计算/通信/free 三部分 × Step 差异柱状图**（横轴为计算、通信、free 三部分，纵轴为时间；每部分内每个 step 一根柱子，取跨 rank 平均，展现各部分耗时在不同 step 间的差异）+ Step×Step 分组柱状图、通信域、快慢卡 | P2/P3 |
| 进阶分析 | 五大类 23 recipe | P3 recipes_summary |
| 性能比对（多卡） | 最大/最小通信占比卡对比要点 | P4 |
| 泳道算子统计 | **Process（host算子）/Ascend Hardware（npu算子）/Communication 三类汇总（持续时间/自用时间/平均/最大/最小持续时间、发生次数）+ 每类持续耗时 Top10 算子表（跨卡聚合）**；P6 逐卡 md 仍含最长算子 + 全算子七列 | P6 |
| 子报告 | vendor cluster / compare HTML | P5 |
| 数据说明 | 数据格式、单位、局限性 | P0 |

## 单卡模式裁剪

省略"集群总览/性能比对/子报告(集群)"分区与导航项，其余保持。
