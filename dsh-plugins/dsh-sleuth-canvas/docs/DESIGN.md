# Sleuth Canvas — 视觉与交互设计

一句话：把一次昇腾诊断的轨迹，渲染成一张**可以漫游、回放、点开的旅程画布**。读者进来 3 秒要能回答：这单在问什么、走过了哪几步、卡在哪、结论是什么、证据够不够。

## 1. 定位

- 载体：DSH Web GUI 左侧栏一个图标 → 主区整页（`main` keyed `sleuth-canvas`）。
- 数据：ascend-sleuth 仓库 `traces/*.yaml`，**离线只读**，不联网、不写仓库、不启动子进程。
- 三块界面：左侧会话列表 / 中间画布 / 右侧节点洞察。画布是主角，列表与洞察是两翼。
- 主题：完全跟随宿主（`--dsw-alias-*`），亮/暗都要好看。画布颜色由 `SC.theme` 解析令牌后绘制。

## 2. 视觉语言

### 2.1 质感

- 背景：宿主 `bg-base` 上叠一层极淡的径向渐晕（画布中心偏亮）+ 点阵。不要纯色大白板。
- 卡片：圆角 14，1px 细描边，表面用 `bg-layer-1`/`bg-layer-2` 的轻微渐变；阴影很克制（选中才明显）。
- 颜色只承担**语义**：动作家族、结论、警示。装饰用透明度与描边，不用大面积色块。
- 动效原则：短、准、有因果。入场按列依次；hover 只动 1–2px；相机移动可被肉眼跟踪（260–420ms），不眩晕。

### 2.2 调色板（画布与 DOM 共用）

基础色（`--sc-*`，定义在 `40-css.js`；canvas 由主题模块微调）：

| 语义 | 键 | 亮色 | 说明 |
|---|---|---|---|
| 现场/输入 | `intake` | `#D9902F` | 用户贴来的现象与证据 |
| 分诊/路由 | `route` | `#4A7DFF` | triage / triage_semantic |
| 检索/索引 | `index` | `#2AA7B8` | load_index |
| 核验 | `check` | `#8A6CF0` | quickly_check |
| 先验/参考 | `book` | `#3C9A78` | reference_lookup |
| 源码/分析 | `code` | `#E07A3F` | source_analysis |
| 结论·命中 | `hit` | `#3FA46A` | hit |
| 结论·未覆盖 | `miss` | `#6E7C93` | miss / tier3 miss |
| 归因/输出 | `flag` | `#C9A227` | attribution / output |
| 收尾 | `feedback` | `#7C8698` | report / feedback / resume / 其它 |
| 警示 | `warn` | `#D9822B` | 缺证据、待回报 |
| 风险 | `risk` | `#D65454` | 数据风险、先停 |

暗色模式：所有色相不变，明度 +6%、饱和度 -6%（由主题模块算），保证在深底上不脏。

### 2.3 字体与字号

字体栈：`ui-sans-serif, system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`；等宽：`ui-monospace, "SF Mono", Menlo, Consolas, monospace`。

| 用途 | 字号/字重 |
|---|---|
| 页面标题 | 20 / 650 |
| 区块标题 | 13.5 / 650 |
| 正文 | 13 / 400，行高 1.65 |
| 辅助 | 11.5 / 400，`text2` |
| 微标签 | 10.5 / 550，大写英文间距 +0.4 |
| 节点标题 | 13 / 600 |
| 节点副文 | 11.5 / 400 |
| case id / 数字 | 等宽 11 |

中文行高不低于 1.6。任何文字不写裸 `<br>` 堆叠；段落 ≤ 200 字，超出分条。

## 3. 动作分类表（`20-model.js`）

| action | 家族键 | 色彩 | glyph | 中文标签 | 节点三元组（title / subtitle / meta） |
|---|---|---|---|---|---|
| *(user 事件)* | `intake` | intake | intake | 现场 | 「现场输入」/ content 首句（60 字）/ `step N · 用户`；badges：证据字数、文件数、sources 数 |
| `triage` | `route` | route | route | 分诊 | 「分诊 → {branch}」/ category / `step N · 路由 {routed}` |
| `triage_semantic` | `route` | route | route | 语义分诊 | 「语义分诊 → {namespace}」/ rationale / meta |
| `load_index` | `index` | index | index | 检索 | 「检索候选」/ `{n_cases} 条 case · {namespaces}` / meta |
| `quickly_check` | `check` | check | check | 核验 | 「核验 {case}」/ output 首句（64 字）/ meta；badges：primary pass/fail、marked excluded |
| `tier3` | `check` | check | cross | Tier 3 | 「深度回退」/ output 首句 / meta |
| `reference_lookup` | `book` | book | book | 查先验 | 「查先验」/ purpose 或 reference / meta |
| `source_analysis` | `code` | code | code | 源码分析 | 「源码分析」/ repo/ref + files / meta；badges：tool_calls 数 |
| `hit` | `hit` | hit | hit | 命中 | 「命中 {case}」/ output 首句 / meta；emphasis conclusion |
| `miss` | `miss` | miss | miss | 未覆盖 | 「知识库未覆盖」/ output 首句 / meta；emphasis conclusion |
| `attribution` | `flag` | flag | flag | 归因 | 「归因 · {component}」/ output 首句 / meta |
| `output` | `flag` | flag | doc | 输出结论 | 「给出结论」/ output 首句 / meta；emphasis conclusion |
| `resume` | `feedback` | feedback | loop | 续接 | 「续接诊断」/ output 首句 / meta |
| `report` | `feedback` | feedback | doc | 报告 | 「写报告」/ output 首句 / meta |
| `feedback` | `feedback` | feedback | feedback | 回报 | 「回报结果 · {outcome}」/ output 首句 / meta |
| *其它 action* | `feedback` | feedback | dot | action 原值 | action / output 首句 / meta |

列（step）标签取该 step 第一个事件的家族标签；若同 step ≥2 个事件，列头显示 `×N` 与「并行」形态。

## 4. 页面布局

```
┌──────────────────────────────────────────────────────────────────────────┐
│  ◇ 诊断画布   Sleuth Canvas · 离线渲染            [状态] [框架] [平台] [刷新] │ 48px
├──────────────┬───────────────────────────────────────────┬───────────────┤
│ 搜索框        │  画布                                       │ 洞察检查器     │
│ 会话卡片 ×N   │  · 列/节点/边/粒子/迷你地图                  │ · 概览(insights)│
│ （可滚动）     │  · 顶部悬浮：会话标题 + 摘要                 │ · 或节点详情    │
│              │  · 底部停靠区：提示 / 图例 / 回放条            │               │
│ 264px        │  flex                                       │ 336px         │
└──────────────┴───────────────────────────────────────────┴───────────────┘
```

窄容器（<1080px）：隐藏右侧 inspector（选中节点时以底部抽屉出现）；<900px：左侧列表收成 56px 图标条（点击展开浮层）。用 **容器查询**（`container-type: inline-size`）实现，不要监听 window 宽度。

### 4.1 页头

- 左：一个 26px 的图形标记（与 icon.svg 同形的内联 SVG）+ 标题「诊断画布」，副标 `Sleuth Canvas · 离线渲染`。
- 右：状态徽标（in_progress 蓝 / resolved 绿 / 其它灰）、framework、platform、category 四个 chip，最后是刷新按钮（图标 + 「刷新」）。
- 下方一行摘要：当前会话的 `summary`，最多 2 行，超出「展开」。左边一条 3px 强调色竖条。

### 4.2 左侧会话列表

- 搜索框：placeholder「搜索会话 / 框架 / 结论」。
- 卡片：12px 圆角，1px 描边；三行：
  1. 状态圆点 + 会话 id（等宽、省略）+ 右侧相对时间（「3 天前」）；
  2. summary 两行（11.5px，`text2`）；
  3. 元信息行：`vllm-ascend` chip · `A3-910C` · `6 步` · 排除 3。
- 选中：左侧 2px accent 竖条 + 背景 `bg-layer-2` + 描边 accent@30%。
- 悬停：背景微亮，时间换「打开 →」。
- 列表头：「诊断记录 · N」，排序切换（按更新时间 / 按步骤数）。默认更新时间倒序。

### 4.3 画布

- 顶部左侧悬浮小条（DOM，叠在 canvas 上）：`S4` 圆标 + 「当前被选中：核验 VLLM-ASC-9002」或回放时「回放 4/9」。背景 blur + 半透明。
- 画布内右下：引擎绘制的迷你地图 + 三个圆形按钮（+ / − / 适配）？按钮做成 DOM 更好点击，放右下角竖排三枚玻璃圆钮，位于迷你地图上方。
- 画布底部：提示、图例、回放条共处一个停靠区（§4.6），右侧永久留出迷你地图的宽度。
- 边：按时间顺序的主链 + 同 step 的竖向串珠。所有边用源节点 accent 的 35% 渐变到目标 accent 的 20%。

### 4.4 右侧检查器

**未选中（概览态）**

- 标题「旅程读法」+ 一句「按顺序读，或点任一节点看细节」。
- insights 列表：每条一个 tone 圆点 + 标题（12px/600）+ 正文（12px，`text2`）。
- 分隔线 + 「图例」：家族色点 + 中文名 + 数量。
- 底部小字：「数据来自 traces/{file} · 只读」。

**选中节点**

- 头部：40px 圆形 icon（accent 16% 底）+ 家族标签 + title；下面一行 `step N · role · 并行组`。
- 正文分区（可折叠，默认展开前两个）：
  - 「做了什么」：output（保留换行，段落 ≤200 字自动分段）
  - 「为什么」：reason
  - 「现场证据」：inline（默认折叠，显示「展开 N 字」）、files（等宽行 + 复制路径）、sources（链接样式但 `target=_blank`？离线环境不保证；用可复制文本）、missing（warn 色）
  - 「关联」：case / candidates / excluded / refs / ref_id，chip 形式
  - 「工具调用」：等宽列表
  - 「其余字段」：`fields` 的键值，折叠在最后
- 底部：`← 上一节点` `下一节点 →` 与「定位到画布」。

### 4.5 结论卡 / 导出 / 列表视图

- 结论卡在页头摘要下方：左侧 3px 结论色条、动作标签（命中 case / 知识库未覆盖 / 给出结论）、结论标题与一句正文、右侧徽标（置信、待回报、已沉淀、风险·先停）。整卡可点，定位到画布结论节点；没有结论时降低对比显示「结论未记录」。
- 「打开会话」只在 trace 带 `harness_session` 时可用；禁用时不弹说明，悬停 title 说原因。
- 「导出」是页头下拉菜单：导出 PNG（当前视图，含主题底色）与复制旅程摘要（Markdown）。导出后底部居中出现一条 2.6s 的提示，不挡操作。
- 列表视图盖住画布区：表头固定，行高 32–40px；选中行左侧 3px 主题色条、结论行标题加粗；选中态与画布节点共用；窄容器允许横向滚动（`min-width: 660px`）。
- 首次进入画布时，快捷键提示（滚轮 / 拖拽 / f / ←→ / t）出现在底部停靠区左格、图例上方，可关闭并记住；迷你地图空闲半透明，指针进入才完全显现。

### 4.6 底部停靠区（提示 / 图例 / 回放条）

- 三者同处画布底部一个停靠区，由同一套排布分出左格与主格，不再各自绝对定位到左下角或底部居中——那是它们互相压住的成因。
- 左格：快捷键提示在上、图例贴底（图例可折叠）；主格：回放条。
- 右侧恒定留出迷你地图的宽度（168 + 16 边距），回放条不会盖住迷你地图与缩放钮。
- 画布宽度 <980px 时停靠区改成两行：左格（提示 + 图例）在上，回放条贴底；<620px 隐藏倍速，<560px 收回迷你地图留白（此时引擎不画迷你地图）。
- 覆盖件的宽度、留白按**画布宽度**降级（`.sc-canvas-wrap` 是容器查询的容器），不按整页宽度。

### 4.7 回放条

- 停靠区主格：圆角胶囊，blur 背景，1px 描边。
- 内容：播放/暂停圆钮（36px）· 进度轨道（step 刻度 + 当前位置点）· 计数 `4 / 9` · 速度（0.5×/1×/2×）· 关闭。
- 播放时：轨道左侧填充 accent，当前节点聚光，相机 flyTo，inspector 同步滚动到该节点的详情。
- 每个节点停留时长 = clamp(900ms + 字符数×6, 1400, 4200) / speed。

## 5. 动效清单

| 场景 | 行为 | 时长 |
|---|---|---|
| 首次载入 | 画布淡入 → 列头依次出现（stagger 60ms）→ 节点按列 stagger 70ms 缩放 0.94→1 + 淡入 → 边生长 | 总计 ≤ 900ms |
| 换单 | 旧图 120ms 淡出，新图同上（时长减半） | ≤ 600ms |
| hover 节点 | 上浮 1.5px、阴影加深、边亮，tooltip 跟随 | 140ms |
| 选中 | 外发光脉冲 2 次后常驻，相机 320ms 居中 | 320ms |
| 回放聚光 | 非相关 220ms 降到 0.22，相关恢复 | 220ms |
| 相机 | cubic-bezier(.22,.61,.36,1) | 260–420ms |
| 列表切换 | 卡片背景/竖条过渡 | 140ms |
| 结论卡 hover / 定位 | 背景与描边加深；点击后相机跟到结论节点 | 140ms / 320ms |
| 导出菜单 | 淡入 + 8px 上移，点外部关闭 | 180ms |
| 切换列表视图 | 瞬时替换；行 hover/选中 140ms；回画布时引擎重算尺寸 | — |
| 底部提示条 | 淡入，2.6s 后淡出 | 180ms |
| 加载 | 三栏骨架 + 1.4s 微光扫过 | — |

全部动效在 `prefers-reduced-motion: reduce` 时：粒子/入场/脉冲关闭，相机瞬时，过渡 0ms。

## 6. 文案规则

- 一句话说结论；不做文学化修饰，不拟人。
- 术语第一次出现带中文：如「核验（quickly_check）」「先验查照（reference_lookup）」；case id、错误码、框架名保持原样。
- 数量能算就算，不写「多个」：`排除 3 个候选`、`6 步`、`4.2 万字符`。
- 缺数据就直说缺什么：`没有 traces 目录`、`还没给结论`。
- 可复制的东西（命令、路径、case id）必须能被复制。

## 7. 验收（人看）

1. 打开后 3 秒内能说出这单的框架、平台、走到第几步、结论是什么。
2. 画布在亮色与暗色下都清晰：文字对比度足够，节点可读，边不糊。
3. 缩放到 0.5× 仍能看出结构；2× 时节点文字不糊（canvas 按 DPR 绘制）。
4. 点一个 `quickly_check` 节点，右侧能看到判据、理由、被排除原因。
5. 回放完整走一遍不卡顿、不眩晕；`Esc` 随时可退。
6. 无 traces 的新机器上，界面给出下一步动作而不是空白。
