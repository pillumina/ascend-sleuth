---
name: preload-panel
description: >
  在 DSH 会话中加载 ascend-sleuth 面板。先查工具目录里有没有 cordis_define / cordis_run：
  有就用 dsh-plugins/loader/panel-from-file.js 热加载面板（只发两个路径，不转写源码）；
  没有（新版 DSH 删了这两件模型工具）就把 dsh-plugins/dsh-sleuth-panels/ 作为常驻插件包
  用 plugin_manager install_bundle 装进 profile，装一次每个会话都在。面板：ascend-panel
  →「诊断」「指标」两个 tab；ev-panel →「自演进」tab。仅 DSH 可用——依赖
  conversation.view 插槽；其他 agent（Claude Code / Codex / pi）无此机制。
---

# Preload Panel

DSH 会话中加载可视化面板（诊断 / 指标 / 自演进）。每个面板占 conversation.view 一个
tab（list 插槽，按 order 排列，可共存）。

面板源码只有一份（`dsh-plugins/<面板>/panel-host.js` 与 `panel-client.js`，动态插件
方言的函数体）。装载有两条路，看本机 DSH 有没有模型侧的动态定义工具：

| 路 | 适用 | 怎么装 | 生效范围 |
|---|---|---|---|
| A 热加载 | DSH 有 `cordis_define` / `cordis_run` | 装 loader，再 `panel_from_file` 发两个路径 | 本会话 |
| B 常驻插件包 | DSH 没有这两件工具 | `plugin_manager install_bundle` 装 `dsh-plugins/dsh-sleuth-panels/` | 本 profile 的每个会话 |

两条路读的是同一份面板源码。B 路的两个产物是生成物，改面板源码后要重跑生成器。

## 触发

用户需要面板但当前视图没有对应 tab 时，用本 skill 加载。

## 面板清单

| 面板 | 目录 | tab id / label | 视图 |
|---|---|---|---|
| 诊断面板 | `dsh-plugins/ascend-panel/` | `ascend-diagnose`(20) / `ascend-metrics`(21) | 会话列表/轨迹/证据 + 指标闭环判决（判据→结论/证据/下一步）/容量逐格/趋势 |
| 自演进看板 | `dsh-plugins/ev-panel/` | `ascend-evolve`(22) | 首屏是体检判决（要处理的判据 + 下一步动作）与触及面；卡收在默认收起的抽屉里作为 diff 日志 |

## 第 0 步：判本机 DSH 走哪条路

查工具目录里有没有 `cordis_define` 与 `cordis_run`（不必查别的）：

- **有** → 走 A 路（热加载）。
- **没有** → 走 B 路（常驻插件包）。新版 DSH 把模型侧定义与运行的入口删掉了，动态
  定义只由程序侧调用方与浏览器面板驱动；`dsh-cordis-host-runner` 的说明里写着本包
  不注册工具、内置模型工具无法创建或更新动态定义。这时 A 路的 loader 装不上——
  不要反复试 `cordis_define`。

## A 路：热加载（本机 DSH 有这两件工具）

1. **确保 `panel_from_file` 工具可用**：先查它在不在（它按进程全局注册，通常已在；
   DSH 重启后第一次才缺）。缺则装 loader：
   1. `read dsh-plugins/loader/panel-from-file.js`（全文）
   2. `cordis_define`：kind: new，idPrefix `ldr`，`code.host` ← 刚读到的全文
   3. `cordis_run`（mode: run）——host-only 包，免审批

   loader 只用 `harness.registerTool` 与 `ctx.get('dynamicCordisRunner')` 两个公开机制。
   若本机 `cordis_define` 的参数表里有 `codeFile`，可省掉第 1 步，直接用它指向该文件。

2. **加载面板**：调 `panel_from_file`（不要用 `cordis_define` 转写源码）：

   ```
   panel_from_file(
     host:   dsh-plugins/<面板>/panel-host.js,
     client: dsh-plugins/<面板>/panel-client.js,
     idPrefix: ascend-panel 用 sleu / ev-panel 用 evbd,
     name, purpose)
   ```

   它读盘 → `dynamicCordisRunner.define()` → `run()`，源码原样进不可变 Package。
   返回 awaiting-approval 时告知用户在 UI 允许（Client 半需授权）；授权后 tab 出现。
   面板两个文件合计约 70KB，发路径即可，别把全文重新输出一遍。

3. **验证**：确认插件 running 且无 waitingFor；tab 出现在对话视图（按上表 id 核对）。
   自演进看板首次打开会调 `scripts/ev_board_data.py` 汇总数据，确认数据区渲染。

改完面板代码再调一次同一条 `panel_from_file` 即重载（同 `idPrefix` 复用本会话的插件，
返回 `reused: true`，不会堆出重复 tab）。

## B 路：常驻插件包（本机 DSH 没有这两件工具）

1. **确认包与产物存在**：`dsh-plugins/dsh-sleuth-panels/`，含 `package.json`、
   `cordis.patch.yml`、`lib/index.js`、`lib/client.js`。两个 `lib/` 文件是生成物：
   面板源码改了就跑 `node scripts/build_panel_bundle.js`，用
   `node scripts/build_panel_bundle.js --check` 核对产物与源文件一致，
   `node scripts/check_panel_bundle.js` 做一次可加载性冒烟（路由、端点、工具、
   三个 tab、样式标签、卸载）。**不要手改 `lib/`**。同一条命令还会判本机 DSH 走哪条装载路，
   并核对常驻包依赖的三处接缝（connection RPC 的注册接口、路由注册要注入 webServer、
   client 沙箱给的 `styles.insert`）还在不在——**装之前跑它**，找不到 DSH 时会如实跳过；
   `--selftest-dsh` 用临时假 DSH 自测这条判据，`--dsh-root <目录>` 指到别的安装处。

2. **装**：`plugin_manager install_bundle(target: <仓库绝对路径>/dsh-plugins/dsh-sleuth-panels)`。
   包会复制进 profile 的 generation，所以仓库被移动或 worktree 被清掉都不影响已装的那份；
   会影响该 profile 的每个会话，这是它的用途。

3. **读安装结果**（`application` 与 `warnings` 决定是否已生效，不要拿日志或进程列表代替）：
   - `applied` → 已生效。
   - `restart-required` → 替换已装包时会出现（运行时把先前的模块路径钉住了）。让用户重启
     DSH Desktop，重启后再验证。
   - `failed` → 读诊断；`webServer` 一类的报错说明适配层没把路由注册在
     `ctx.inject(['webServer'])` 里。

4. **验证**：`cordis_inspect_query`（client, `Slots`, `listSubTree`, root
   `conversation.view`）看三个 tab id 是否出现在占位列表里；再请用户点开一页，确认读到
   真数据（这一条只有页面能验，插槽占位不等于数据能取到）。
   浏览器代码是页面启动时装载的，刚装完要刷新页面。

5. **卸载**：`plugin_manager remove_bundle(target: 'dsh-sleuth-panels')`。

## 依赖预检（激活前跑，避免面板加载后白屏/报错）

面板 host 已做优雅退化（自演进 JSON 不截断、无 traces/ 显示空态、缺 pyyaml 给提示），
但装载前跑一次预检，能把"依赖缺失"改成主动告知，而不是面板里一条报错：

- **通用**：确认会话工作区是 ascend-sleuth 仓库（Host 从 `session.header.cwd` 解析数据目录）。
- **ev-panel（自演进）**：确认 Python 3 + PyYAML 可用。面板 host 自动探测解释器
  （`python3` → `python` → `py -3`，取第一个能打印 Python 3.x 的；Windows 上 `python3`
  常是应用商店的空壳，不打印任何东西）：
  ```bash
  python -c "import yaml; print('pyyaml ok')"   # 失败 → 试 py -3；再失败 → pip install pyyaml
  ```
  失败就告诉用户"自演进看板需要 PyYAML，请 `pip install pyyaml`"，再决定是否仍加载。
- **ascend-panel（诊断）**：`traces/` 可能不存在（gitignored、按需生成），host 把
  "目录不存在"当空态处理；用户预期有历史诊断却显示为空时，提示运行 `/skill:diagnose`
  生成 `traces/`。指标 tab 需要 Python 3 + PyYAML：「闭环判决」跑
  `scripts/metrics_health.py --json`（判据读 `metrics/gates.yaml`），「实时计算」跑
  `scripts/trace_metrics.py`；缺依赖时面板显示「体检不可用」并给出可执行提示，
  所以预检失败仍可加载，只是首屏没有判决条。

## 回退（A 路的版本差异）

- **loader 注册不了工具**（`harness.registerTool` 缺失）→ 内联面板本身：读两个文件全文，
  `code.host` / `code.client` 原样粘贴。文件是函数体形态
  （`return { apply(ctx) {...} }`），别改形态——动态插件不经过打包器，
  `export default` / `import` 等 ESM 语法无法加载。
- **A 路整条不可用**（没有 `cordis_define`）→ 走 B 路。

## 交互原则

- **A 路跨 session**：工具 `panel_from_file` 是进程全局的，新 session 不必再装 loader
  （重复装载会撞名但不报错，工具照常可用）；面板插件是 per-session 的，新 session 认领不了
  旧 session 的插件，会新建一个同 tab id 的插件覆盖显示，旧插件仍在跑。要清理就重启
  DSH，或在各 session 内对自己的插件 `cordis_stop`。
- **B 路跨 session**：插件装在 profile 层，每个会话共用一份，重启不丢；换版本用同一条
  `install_bundle` 重装，重装后按安装结果决定是否要让用户重启。
- 面板是只读可视化 + 指令生成器：展示状态、生成续接/沉淀指令供用户触发，面板自身不做
  决策与写入（唯一例外：诊断面板的沉淀状态标记由用户在面板确认后更新）。自演进看板纯
  只读：展示卡状态与演进信号，产卡/验证走 agent 与攒批。

## 依赖

- DSH 会话。A 路另需 `cordis_define` / `cordis_run` / `cordis_inspect_self` 工具；
  B 路另需 `plugin_manager` 工具与在需要时重启 DSH Desktop 的能力。
- 工作区为 ascend-sleuth 仓库（Host 从 `session.header.cwd` 解析数据目录）。
- Host 服务：`fs` / `sessions` / `shell` / `connection`。
- **ev-panel（自演进）**：Python 3 + PyYAML，两个脚本 `scripts/ev_board_data.py`
  （卡库/触及面/现场聚合）与 `scripts/evolution_health.py --json`（体检判决，判据在
  `proposals/gates.yaml`）。判决是一次独立调用：它失败时面板不渲染结论条（不拿卡数冒充
  "没有越界"），其余区块照常。
- **ascend-panel（指标）**：`shell` + Python 3 + PyYAML：「闭环判决」跑
  `scripts/metrics_health.py --json`、「实时计算」跑 `scripts/trace_metrics.py`；
  缺依赖时判决条退化为「体检不可用」加可执行提示。
- 诊断「打开证据 / 打开报告」按方言阶梯探测：Windows 先试 `Start-Process`，再
  `open`、`xdg-open`、`explorer.exe`，按退出码判定并回报用了哪一路（Windows 上
  `ctx.shell` 接的是 PowerShell，不是 bash）。四种都不行时界面给原因。
- 「看报告」不需要外部程序：报告正文由 host 只读读入后在面板内渲染（章节跳转 + 复制全文），
  「打开文件」才依赖上面的阶梯。

## 说明

- 仓库内 `dsh-plugins/<面板>/` 是代码的权威版本（含各面板 README）；
  `dsh-plugins/loader/` 是 A 路的加载入口；`dsh-plugins/dsh-sleuth-panels/` 是 B 路的
  插件包（`lib/` 为生成物）。跨面板的颜色、字号、复用窗口与文案约定见
  `dsh-plugins/README.md`。
- A 路的动态定义只存在于当前 DSH 进程，重启后需重新加载；B 路装在 profile 层，
  重启后仍在。
- 改面板代码走仓库，装载走本 skill；两份产物由生成器保持一致。
