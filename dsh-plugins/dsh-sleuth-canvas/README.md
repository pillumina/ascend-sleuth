# Sleuth Canvas · 诊断画布

一个**独立安装/卸载**的 DSH 插件：把 [ascend-sleuth](https://github.com/pillumina/ascend-sleuth) 仓库 `traces/*.yaml` 里的诊断过程，离线渲染成一张可漫游的旅程画布。左侧栏多一个「诊断画布」图标，主区打开整页；分诊、检索、候选核验、源码分析、结论与证据都摆在画布上，点开任一节点看它的输出、理由与证据。

- **离线只读**：只读本机 `traces/` 目录，不联网、不起子进程、不写仓库。
- **独立安装/卸载**：装在 DSH profile 里，与本仓其它面板包分开登记，卸载即消失。
- **画布**：阶段列 + 节点卡 + 贝塞尔边 + 流动粒子 + 迷你地图 + 相机平滑缩放/平移。
- **过程洞察**：候选漏斗、并行展开、证据体量、欠回报、未沉淀——规则从 trace 数据现算，不编造。
- **可回放**：按事件顺序聚光、相机跟随、检查器同步；空格暂停、Esc 退出。

## 安装

本包在 ascend-sleuth 仓库的 `dsh-plugins/dsh-sleuth-canvas/`，与另外三个包一起由 `/skill:preload-panel`
装载（`panel_status.js` 快检、`panel_install.js --all` 一次装四个包、路由三/四/五都覆盖它）。也可单独装本目录的绝对路径：

```
plugin_manager install_bundle(target: "<本目录绝对路径>")
```

或桌面版自带 CLI（`<profile>` 用当前 profile 名，通常是 `desktop`）：

```
<DSH 安装目录>/runtime/cli/bin/dsh plugin --profile desktop add "<本目录绝对路径>"
```

新装包一般会热生效；如果侧栏没出现图标，刷新页面；如果刷新后仍没有，重启 DSH Desktop（host 半的路由在进程启动时装载）。

## 版本迭代

改了 `client-src/**` 就跑 `node build.mjs` 重建 `lib/client.js`（`--check` 判产物是否最新）；改了
`host/index.js` 要重启宿主进程。快照安装（插件页 / 插件管理器）按 `package.json` 的 version 判
「已装」：换版本时 bump version、重建产物、按原路重装；同版本重装不换产物。页面右下脚注的
`v<version>` 是构建时写进 `lib/client.js` 的版本串，用来判断浏览器半拿到的是哪一版。

1. 改源码 → `node build.mjs`。
2. bump `package.json` 的 version。
3. 重装（`plugin_manager install_bundle` / 插件页 / `panel_install.js --all --sync`）。
4. link 安装只需刷新页面（host 改动另加重启）。

## 卸载

```
plugin_manager remove_bundle(target: "dsh-sleuth-canvas")
```

或在侧栏「插件」页移除，然后刷新页面。

## 用法

1. 左侧栏点「诊断画布」。
2. 左栏选一次诊断（按更新时间倒序，可搜索）。
3. 中间画布：滚轮缩放、拖拽平移、双击适配；点节点看右侧详情；`Esc` 取消选中。
4. 底部「▶ 回放」按时间顺序走一遍；`←/→` 逐个节点，`f` 适配，`+/-` 缩放。

数据从当前工作区（或最近一次 DSH 会话所在目录）的 ascend-sleuth 检出里找 `traces/`。找不到时页面会说明。

## 开发

```
node build.mjs          # client-src/*.js → lib/client.js
node build.mjs --check  # 校验产物是否最新
node --check lib/client.js
node test/host.test.mjs
node test/engine.test.mjs
node test/ui.test.mjs
node test/artifact.test.mjs
```

目录：

```
host/             host 半：离线读 traces、list/detail RPC、insights（ESM）
client-src/       页面源码，按文件名拼接成 lib/client.js（纯脚本函数体，只通过 SC 通信）
lib/client.js     生成物，勿手改
fixtures/         合成测试数据：trace-samples/*.yaml 源 + 归一化后的 JSON 样例
docs/CONTRACT.md  host ↔ client ↔ 引擎 的接口契约
docs/DESIGN.md    视觉与交互设计
```

## 验证状态

- host：YAML 解析、仓库定位（含向上 6 级）、list/detail、insights 规则、RPC 信封、缓存、路径穿越拒绝——`node test/host.test.mjs` 30/30。
- 引擎：布局数学、初始相机、LOD 总览、相机/命中/聚光/生命周期——`node test/engine.test.mjs` 25/25。
- 页面：数据映射 + 迷你 React 渲染冒烟——`node test/ui.test.mjs` 16/16。
- 产物形态与注册面——`node test/artifact.test.mjs`。
- 开发机另跑过真实 React 19 + jsdom 整页冒烟（list→detail→切单→点节点→空态→错误态，43 项断言）；该工具不入仓、CI 不跑。
- 画布视觉用 headless Chrome 在亮/暗、620/1000 宽、初始相机/总览两态下核过；**真实 DSH 宿主里的像素表现仍需安装后目检**（宿主令牌、字体回退、浮层位置）。

## 依赖

DSH Web 宿主（`slots` / `connection` / `fs` / `sessions` / `webServer` 服务），无第三方运行时依赖。画布用原生 Canvas 2D 绘制。
