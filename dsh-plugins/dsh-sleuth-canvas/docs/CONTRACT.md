# Sleuth Canvas — 技术契约（host ↔ client ↔ 画布引擎）

本文件是插件 `dsh-sleuth-canvas` 的实现契约。并行开发时以本文件为准；视觉细则见 `docs/DESIGN.md`。

## 0. 身份与目录

- 包名 / bundle 行 id / 客户端产物 id：`dsh-sleuth-canvas`
- 侧栏座位：`sidebar.panellist` id `sleuth-canvas`，`order: 40`，label「诊断画布」
- 整页座位：`main` keyed key `sleuth-canvas`
- RPC 通道：`/sleuth-canvas`
- 版本：`0.2.1`

```
dsh-plugins/dsh-sleuth-canvas/
├── package.json            # 我（Lead）维护
├── cordis.patch.yml        # Lead
├── icon.svg                # Lead
├── locale/{en,zh}.json     # Lead
├── build.mjs               # Lead：把 client-src/*.js 拼成 lib/client.js
├── lib/client.js           # 生成物，勿手改
├── host/index.js           # ← host-data 负责（可再拆 host/*.js，自己安排）
├── client-src/05-util.js   # Lead
├── client-src/06-theme.js  # Lead
├── client-src/10-engine.js # ← canvas-engine 负责
├── client-src/20-model.js  # ← ui-shell 负责
├── client-src/30-page.js   # ← ui-shell 负责
├── client-src/40-css.js    # ← ui-shell 负责
├── client-src/90-plugin.js # Lead
├── fixtures/               # 合成测试数据：traces/*.yaml 与宿主归一化后的 JSON
├── test/                   # node 测试
├── docs/CONTRACT.md, docs/DESIGN.md
└── README.md
```

**ascend-sleuth 仓库是数据源，只读**；本插件不修改它。

## 1. 客户端产物的加载形态

`lib/client.js` 由 `node build.mjs` 生成，结构固定：

```js
window.__ModuleLoader__.load({
  id: 'dsh-sleuth-canvas',
  factory(require) {
    const React = require('react')
    const SC = { React, h: React.createElement }
    ;(function (SC) { /* client-src/05-util.js 原文 */ })(SC)
    ;(function (SC) { /* client-src/06-theme.js 原文 */ })(SC)
    ...按文件名排序全部拼接...
    return SC.plugin
  },
})
```

因此每个 `client-src/*.js` 必须是 **纯脚本函数体**：

- 不能出现 `import` / `export` / `require`（React 从 `SC.React` 取）。
- 只能通过参数 `SC` 与外部世界交互；文件之间**不要互相引用顶层变量**，一律挂到 `SC` 上。
- 浏览器全局可直接用：`window`、`document`、`requestAnimationFrame`、`setTimeout`、`ResizeObserver`、`matchMedia`、`getComputedStyle`、`performance`。
- 每个文件都可以被测试用 `vm.runInNewContext(src, { SC, window, document... })` 单独求值，所以**求值阶段不要碰 DOM**（只在函数调用时碰）。

## 2. Host 半（`host/index.js`）

入口形态：

```js
export function apply(ctx) { ... }
```

**不要写任何静态 import**（`@deepseek-ai/*` 在 profile 里解析不到，整个 host 半会 import 失败）。本地相对 import 可以，但为降低风险，host 半写成**单文件**。

需要的服务（都用 `ctx.get` 取，缺失时优雅退化）：

- `fs`：`resolve(path, {cwd})`、`readText(target)`、`listDir(target)`（条目含 `name`、`version`）、`stat(target)`。
- `sessions`：`list()`、`get(sessionId)`；会话对象形状 `{ header: { cwd } }`。
- `webServer` + `connection`：注册一条 prefix RPC 路由，模板照抄 `dsh-plugins/ascend-panel` 的适配层（见 sleuth 仓 `dsh-plugins/dsh-sleuth-panels/lib/index.js` 末尾的 route handler）。

路由约定（必须逐字对齐，client 适配层按它解析）：

- `POST <channel>/<endpoint>`，body `{ rpcId, method, payload }`。
- 应答 `{ type: 'server-response', rpcId, result }`，`result` 为 `{ ok: true, value }` 或 `{ ok: false, error: { code, message, details } }`。
- 先做 `connection.requestRejection(req)` 鉴权（返回数字则直接写该状态码）。
- 单次请求体上限 1 MiB。

### 2.1 数据目录解析

目标：找到 ascend-sleuth 仓库根（含 `traces/` 与 `scripts/metrics_health.py`）。

1. 若 `sessions` 可用：本会话 id 的 `header.cwd`（客户端会把当前 sessionId 传给 `list`，host 用它）。
2. 逐个试 `sessions.list()` 的 `header.cwd`，优先 `scripts/metrics_health.py` 存在的目录。
3. 退回第一个带 `cwd` 的会话。
4. 都拿不到：返回 `repo.detected: false`，`sessions: []`，`warning` 一条（页面显示空态说明）。

### 2.2 YAML 解析

trace 是手写 YAML，必须能解析：块映射/序列、行内流集合 `{a: 1, b: [x, y]}`（含跨行折行）、单双引号与转义、`>-` / `|-` 块标量（块内 `#` 是正文）、数字、布尔、null、注释、BOM。

**直接移植** sleuth 仓 `dsh-plugins/ascend-panel/panel-host.js` 里 `parseYaml` 那一组函数（约 2197–2560 行，含 `splitYamlLine` / `yamlScalar` / `flowStartIndex` / `flowBalance` / `readYamlMap` / `readYamlValue` / `readYamlSeq` / `parseInlineMap`），保留其容错语义（丢弃行统计）。文件头注明来源。

### 2.3 RPC：`list`

payload：`{ sessionId?: string }` → 返回：

```jsonc
{
  "repo": { "path": "/abs/ascend-sleuth" | null, "detected": true },
  "generatedAt": "2026-11-03T22:00:00+08:00",
  "warnings": ["..."],
  "sessions": [ SessionSummary ]
}
```

`SessionSummary`：

```jsonc
{
  "file": "2026-01-02-demo-a3-w8a8-garble.yaml",
  "id": "2026-01-02-demo-a3-w8a8-garble",
  "status": "in_progress",              // 原值，不改写
  "summary": "……",                       // 原文
  "createdAt": "2026-01-02T09:12:00+08:00" | null,
  "updatedAt": "..." | null,
  "framework": "vllm-ascend" | null,
  "platform": "A3-910C" | null,
  "category": "interrupt" | null,
  "resolvedAt": null,
  "currentStep": 6 | null,
  "harnessSession": "ds-…" | null,  // 产生这条 trace 的 DSH 会话号（harness_session）
  "lastAction": "……" | null,
  "activeCase": "REF-QUANT-9001" | null,
  "sedimented": { "state": "none" | null, "caseId": null },
  "feedback": { "case": null, "outcome": "pending" | null },
  "excludedCases": ["VLLM-ASC-9002"],
  "eventCount": 9,
  "stepCount": 6,
  "hasConclusion": true,
  "sizeBytes": 6655,
  "version": "123456" | null
}
```

`stepCount` = `trace[].step` 去重后的个数；`hasConclusion` = 存在 `hit` / `miss` / `output` / `attribution` 之一的事件。

缓存：按 `fs.listDir` 的 `version` 令牌缓存“文件 → SessionSummary”。500 个 trace 也应在 1 秒内返回（不含首次解析）。

### 2.4 RPC：`detail`

payload：`{ sessionId?: string, file: string }` → 返回：

```jsonc
{
  "file": "...",
  "session": SessionSummary,          // 同上
  "summary": "……",
  "lastAction": "……" | null,
  "excludedCases": ["..."],
  "activeCase": "..." | null,
  "sedimented": { "state": "...", "caseId": "..." },
  "feedback": { "case": "...", "outcome": "..." },
  "conclusionIndex": 8 | null,
  "insights": [ Insight ],
  "evidenceFiles": [ { "name": "x.log", "bytes": 12345 } ],
  "warnings": ["..."],
  "events": [ TraceEvent ]
}
```

安全：`file` 只允许 `[A-Za-z0-9._-]+\.yaml`，否则 `ok:false, code:'bad-request'`。

`TraceEvent`（客户端不再二次解析 YAML）：

```jsonc
{
  "idx": 0,
  "step": 1,
  "role": "user" | "agent",
  "action": null | "triage" | "load_index" | "quickly_check" | "tier3" | "source_analysis"
           | "reference_lookup" | "triage_semantic" | "hit" | "miss" | "attribution" | "output"
           | "resume" | "report" | "feedback" | "...",   // 原值
  "content": "……" | null,                 // user 事件正文
  "output": "……" | null,
  "reason": "……" | null,
  "note": "……" | null,
  "purpose": "……" | null,
  "evidence": {                            // 只有 user 事件有，归一化后
    "inline": "……", "inlineChars": 40000,
    "files": ["traces/evidence/.../x.log"],
    "sources": ["https://..."],
    "missing": "……"
  } | null,
  "case": "VLLM-ASC-9002" | null,
  "candidates": ["..."],
  "considered": ["..."],
  "excluded": ["..."],
  "refs": ["..."],
  "parallelGroup": null | "g1",
  "verdict": { "primary": "pass", "fallback": "pass", "marked": "excluded",
               "result": null, "confidence": null, "check": null },
  "toolCalls": ["..."],                   // 每项截 400 字
  "sources": ["https://..."],             // 顶层 sources + evidence.sources 合并去重
  "fields": {                             // 其余所有标量/数组字段原样（字符串截 1200 字）
    "branch": "inference_interrupt",
    "routed": ["inference/vllm-ascend/"],
    "n_cases": 83
  },
  "chars": { "output": 1200, "reason": 300, "content": 800 }
}
```

`output` / `reason` / `content` 每人截 8000 字（`chars` 记原文长度）；`evidence.inline` 截 4000 字并给 `inlineChars`。

`Insight`（host 用规则生成，不编造）：

```jsonc
{ "id": "funnel", "tone": "info|good|warn|risk|neutral", "title": "候选漏斗", "text": "看 6 验 6 排 6，无命中" }
```

至少实现这些规则（数据不足就跳过，不写空话）：

1. **结论**：`hit` 给「命中 case + confidence」；`miss` 给「知识库未覆盖」；没有结论给「仍在进行」。
2. **候选漏斗**：`quickly_check` 条数、排除数、命中数。
3. **并行**：同一 step 内事件数最多的一组 → 「第 N 步并行展开 K 个动作」。
4. **证据体量**：inline 总字数 + 文件数；`missing` 非空 → warn 提示缺什么。
5. **工作量**：`tool_calls` 条数、`source_analysis` 步数、`reference_lookup` 步数。
6. **时间**：`created_at`→`updated_at` 跨度（<1 分钟写「不到 1 分钟」）。
7. **闭环**：`feedback.outcome: pending` → 「给了 fix，等待回报」；`sedimented.state: none` → 「尚未沉淀」。
8. **回退/续接**：`resume` 事件 → 「被打断后在此续接」。
9. **风险**：输出文本含「data-loss / 先停 / 数据风险」等词时 tone=risk（按原文子串判断，不推断）。

### 2.5 健壮性

- `traces/` 不存在 → `sessions: []` + warning「没有 traces 目录：先跑一次诊断」。
- 单个文件解析失败 → 跳过它，warning 记文件名；不拖垮整个列表。
- 未知字段原样进 `fields`，不要丢——前端展示靠它。
- 所有 host 代码 `node --check host/index.js` 必须通过；`test/host.test.mjs` 用假 fs/sessions 直接调内部函数（导出 debug 入口 `export const __test = { ... }` 亦可）。

## 3. 画布引擎（`client-src/10-engine.js`）

纯 canvas 引擎，不碰 React。挂到 `SC`：

```js
SC.createEngine = function createEngine(opts) { ... }
```

`opts`：

```js
{
  canvas,                  // HTMLCanvasElement
  palette: () => Palette,  // SC.theme.currentPalette()（SC.theme 由 Lead 提供，见 §4）
  reducedMotion: boolean,
  onSelect: (idx|null) => void,   // 画布点击空白 → null
  onHover: (idx|null) => void,
}
```

返回：

```js
{
  setGraph(graph),          // 换整张图；自动 fit（带入场动画）
  setSelected(idx|null),
  setHovered(idx|null),
  setReplay(active),        // true 时进入聚光模式
  setReplayFocus(idx|null), // 聚光某个节点（不触发相机；由 page 决定何时 flyTo）
  flyTo(idx, { duration }?),// 相机平滑移动到节点
  fit({ animate }?),
  zoomBy(factor),
  resize(),                 // 容器尺寸变化时调用（内部也挂 ResizeObserver）
  nodeRect(idx),            // 节点在屏幕坐标的矩形（给 DOM tooltip 用）
  exportImage(),            // 当前视图的 PNG dataURL（含主题底色）；画布未就绪时 null
  destroy(),
}
```

`graph`（由 page 构造，见 §5）：

```js
{
  columns: [ { col: 0, step: 1, label: '现场', count: 1, accent: '#...', parallel: false } ],
  nodes: [ NodeDescriptor ],
  edges: [ { from: 0, to: 1, kind: 'main'|'return' } ],
}
```

`NodeDescriptor`：

```js
{
  idx: 0, col: 0, lane: 0,
  role: 'user'|'agent',
  accent: '#E8A33D',        // 主色（左侧色条/图标/边框）
  glyph: 'intake',          // 见 §3.3
  title: '现场输入',          // 标题（最多 16 个汉字视觉宽，engine 负责省略）
  subtitle: 'w8a8 首批输出乱码', // 副标题，1 行
  meta: 'step 1 · 用户输入', // 第三行小字
  badges: [ { text: '2 文件', tone: 'neutral' } ],
  emphasis: 'normal'|'conclusion',  // conclusion 稍大/更强
}
```

### 3.1 布局（引擎负责，确定性可测）

常量：`NODE_W=236`，`NODE_H=84`（`emphasis:'conclusion'` 时为 92），`COL_GAP=88`，`ROW_GAP=18`，`PAD_X=120`，`PAD_Y=110`。

- 列 x = `PAD_X + col * (NODE_W + COL_GAP) + NODE_W/2`（列内水平居中）。
- 列内 y：以该列中轴为基准，`lane` 从 0 起，`y = centerY + (lane - (count-1)/2) * (NODE_H + ROW_GAP)`；`centerY = PAD_Y + maxColumnHeight/2`，让整张图垂直居中。
- 画布逻辑坐标原点左上；相机变换 `screen = (world * zoom) + pan`（旋转 0）。
- 提供纯函数 `SC.engineInternals.layout(graph)` 便于 node 侧测试（返回 `{ x, y, w, h }[]`）。

### 3.2 渲染要求

- 背景：静态点阵（间距 26，颜色取 palette.grid，透明度随主题），随 pan 视差但缩放不放大点。
- 列：顶部 step 徽标（圆形描边 + 数字）、列标签（label）、并行时显示「×6」；一条竖直虚线导引从上到下，低透明度。
- 节点：圆角 14 矩形，底色 `palette.nodeBg`（可由 palette.nodeBgTop/nodeBgBottom 做线性渐变），描边 1px `accent@22%`；左侧 3px 色条（圆角内）；左上 24px 圆形图标底 `accent@16%` + glyph 描边 `accent`；标题 13px/600 `palette.text`，副标题 11.5px `palette.text2`，省略号；右侧 step 小字；底部 badges 行（若空间不足省略）；hover 上浮 1.5px + 阴影 + 边框亮；选中加重描边 1.5px + 外发光（径向渐变）+ 轻微脉冲。
- 边：三次贝塞尔（水平控制点），`main` 宽 1.6、低透明渐变；`return` 虚线。默认 `palette.edge`，参与选中/聚光时高亮为 accent。入场时按顺序“生长”动画（用贝塞尔弧长采样截断绘制）。
- 流动粒子：沿 `main` 边周期性移动的 2px 光点，颜色 accent@40%，低密度（每条边每 3.2s 一颗），`reducedMotion` 时关闭。
- 列导引：同一步内节点之间画竖向“串珠”连接（低透明）。
- 聚光（replay / selected）：非相关节点 alpha 0.22、相关边保留；选中节点外发光脉冲两次。
- 相机：滚轮以指针为锚缩放（0.35–2.2，平滑），拖拽平移（pointer capture），双击 fit；`fit()` 用缓动（260ms cubic-bezier(.22,.61,.36,1)）。
- 迷你地图：引擎负责在右下角绘制 168×112 的面板（节点缩略块 + 视口框），并支持点击/拖拽移动视口；不占用 page 的 DOM。画布 CSS 宽 <560 或高 <360 时不画；空闲时半透明（0.55），指针进入面板才完全显现。
- 命中测试：节点矩形（世界坐标反变换）。hover 时调用 `onHover`，点击调用 `onSelect`；空白点击 `onSelect(null)`。
- 渲染循环：单个 rAF；无交互且无动画时降频（30fps 上限）；页面隐藏时暂停（`document.visibilitychange`）。
- DPR：`canvas.width = cssW * dpr`，`ctx.setTransform(dpr,0,0,dpr,0,0)`；`ResizeObserver` 监听父容器。
- 绘制文字用 `ctx.font = '600 13px ...'`，字体栈 `ui-sans-serif, system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`。
- 圆角矩形优先用 `ctx.roundRect`（可用则用），否则自绘。

### 3.3 glyph 键与图形（24×24 线性图标，stroke 1.7，无填充）

`intake`（输入/箭头入框）、`route`（分叉）、`index`（层叠列表）、`check`（对勾圆）、`spark`（四角星）、`book`（打开的书）、`code`（尖括号）、`hit`（靶心/圆点）、`miss`（斜线圆）、`flag`（旗）、`doc`（文档）、`loop`（回环箭头）、`resume`（播放三角）、`feedback`（气泡）、`cross`（叉）、`dot`（圆点）。

实现：`const GLYPHS = { intake: [['M...', ...]], ... }`，用 Path2D/`ctx.beginPath()` 按命令画；路径数据自定，要求视觉统一、粗细一致。

## 4. 主题（`client-src/06-theme.js`，Lead 提供）

```js
SC.theme.currentPalette() -> {
  mode: 'light'|'dark',
  surface, surfaceAlt, overlay, border, borderStrong, text, text2, text3, grid, edge,
  accent: '#4a7dff',            // 主品牌色
  nodeBgTop, nodeBgBottom,
  introBg,                      // 画布底部渐晕
  tones: { intake, route, index, check, spark, book, code, hit, miss, flag, doc, loop, resume, feedback, cross, neutral },
  alpha(hex, a) -> 'rgba(...)',
  adjust(hex, dl) -> '#...'
}
```
实现方式：从根元素 `getComputedStyle` 读 `--dsw-*` 与 `--sc-*` 变量；mode 由 surface 亮度判断；缓存 2s 并在 `document.documentElement` 属性变化时失效。**不要**在每帧重新读 style。

## 5. 页面（`client-src/30-page.js` + `20-model.js` + `40-css.js`）

### 5.1 数据流

1. mount → `SC.host.call('list', { sessionId })` → 选 `updatedAt` 最新的会话。
2. 选中会话 → `SC.host.call('detail', { sessionId, file })`。
3. `20-model.js` 把 `detail` 映射为 `graph` + `sections`（taxonomy 表见 DESIGN.md §3）。
4. 渲染三栏：左 session 列表（264px）／中 canvas（flex）／右 inspector（336px）。
5. 刷新按钮重拉（`refresh: true` 语义由 host 每次全量返回，client 不做长缓存）。

### 5.2 交互清单（必须全做）

- 点击节点 → 选中 + 右侧 inspector + 引擎聚光；`Esc` 取消选中。
- 点击列表行 → 换单（保留画布位置重置）。
- hover 节点 → 高亮 + DOM tooltip（标题 + 一行副文），tooltip 位置来自 `engine.nodeRect(idx)`。
- 滚轮缩放、拖拽平移、双击适配；右下迷你地图。
- 回放：底部停靠区主格的「▶ 回放」条 → 按事件顺序聚光 + 相机跟随 + inspector 跟随 + 进度条（每个 step 一个刻度）；空格播放/暂停，`Esc` 退出；速度 0.5×/1×/2×。
- 底部停靠区：快捷键提示、图例、回放条同处 `.sc-canvas-dock`（左格 `.sc-dock-side` 是提示 + 图例，主格 `.sc-dock-main` 是回放条），右侧平时留出迷你地图宽度、画布窄到不画迷你地图时收回；回放活动态占满主格，否则进度轨道会塌到最小宽度。三者**不得**各自 `position:absolute` 到同一个底角，那是重叠的成因。
- 键盘：`←/→` 上/下一个事件，`f` 适配，`+/-` 缩放，`Esc` 取消。
- 搜索：左侧列表按 id/summary/framework 过滤。
- 空态：无 traces 时给一条说明 + 可复制的命令 `/skill:diagnose`；加载态给骨架；错误态给错误原文 + 重试按钮。
- 结论卡：页头第三条网格行，显示结论动作、case、一句正文与徽标（置信 / 待回报 / 已沉淀 / 风险·先停）；可点击时定位到画布结论节点。没有结论事件时显示「结论未记录」和 `lastAction` 或一句说明。
- 导出：页头「导出」菜单两项——`导出 PNG（当前视图）`（经 `engine.exportImage()`，含主题底色，文件名 `sleuth-canvas-<trace>.png`）与 `复制旅程摘要`（Markdown：会话元信息、结论、洞察、过程、来源）。
- 打开会话：trace 有 `harness_session` 时按钮可用，调用 `SC.openSession(id)`（宿主 `sessions.open`）；失败或没有服务时给可见提示，不静默。
- 列表视图：`t` 或顶部「列表」切换事件表格（步骤 / 角色 / 动作 / 摘要 / 标记），行可点选定位回画布节点；画布保持挂载，切回时重算尺寸。
- 快捷键提示：首次进入画布时出现在停靠区左格、图例上方的可关闭提示条（localStorage 记住已关），由提示条自身的关闭按钮收起；`Esc` 先关导出菜单，再退回放/取消选中。
- 本地偏好：上次选中的 trace 文件、画布/列表视图存 localStorage；不可用时静默退化。

### 5.3 文案

中文为主，术语保留原文（case id、错误码、framework、`quickly_check` 这类 trace 字段值）。不要拟人、不要自我评价、不要「首先/其次/值得注意的是」。每条 insight 一句话说清「发生了什么、意味着什么」。

## 6. 验证

- `node build.mjs` 生成 `lib/client.js`；`node --check lib/client.js`。
- `node test/host.test.mjs`：把 `fixtures/trace-samples/` 复制成临时仓库，跑 list/detail/insight 断言。
- `node test/engine.test.mjs`：布局确定性、边界（并行列、单列、空图）。
- 安装：Lead 用 `plugin_manager install_bundle`；安装后 `cordis_inspect_query` 查 `sidebar.panellist` 与 `main` 的注册。
- 视觉核验由用户完成；不要把“安装成功”说成“看着对”。
