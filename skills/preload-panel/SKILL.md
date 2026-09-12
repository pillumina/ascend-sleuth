---
name: preload-panel
description: >
  在 DSH 会话中热加载 ascend-sleuth 面板插件：先确保 panel_from_file 工具可用（一次性
  加载 dsh-plugins/loader/panel-from-file.js，~1.5KB，host-only 免审批），再用它按路径
  加载 dsh-plugins/<panel>/ 下的 panel-host.js 与 panel-client.js——**只发两个路径，
  不转写 ~70KB 源码**，最后 cordis_run 激活，对话视图出现对应 tab。面板选择：
  - ascend-panel →「诊断」「指标」两个 tab（诊断会话/轨迹/证据 + **指标闭环判决**：首屏列要处理的判据、容量逐格、不可解读标记）
  - ev-panel →「自演进」tab（EV 卡状态机 / 容量热力 / 归因与 S2 反馈 / timeline）
  仅 DSH 可用——依赖 DSH 的 cordis_define / cordis_run 工具
  与 conversation.view 插槽；其他 agent（Claude Code / Codex / pi）无此机制。
---

# Preload Panel

DSH 会话中加载可视化面板（诊断 / 指标 / 自演进）。每个面板是独立动态插件，各占
conversation.view 一个 tab（list 插槽，按 order 排列，可共存）。

## 触发

用户需要面板但当前会话没有对应 tab 时，用本 skill 加载。

## 面板清单

| 面板 | 目录 | tab id / label | 视图 |
|---|---|---|---|
| 诊断面板 | `dsh-plugins/ascend-panel/` | `ascend-diagnose`(20) / `ascend-metrics`(21) | 会话列表/轨迹/证据 + 指标闭环判决（判据→结论/证据/下一步）/容量逐格/趋势 |
| 自演进看板 | `dsh-plugins/ev-panel/` | `ascend-evolve`(22) | EV 卡状态机 / 容量热力 / 归因与 S2 反馈 / timeline |

## 依赖预检（激活前跑，避免面板加载后白屏/报错）

面板 host 已做优雅退化（自演进 JSON 不截断、无 traces/ 显示空态、缺 pyyaml 给提示），
但 loader 在激活前跑一次预检，能把"依赖缺失"改成**主动告知**而不是面板里一条报错：

- **通用**：确认会话工作区是 ascend-sleuth 仓库（Host 从 `session.header.cwd` 解析数据目录）。
- **ev-panel（自演进）**：确认 Python 3 + PyYAML 可用——面板 host 会自动探测解释器
  （`python3` → `python` → `py -3`，取第一个能打印 Python 3.x 的；Windows 上 `python3` 常不存在），
  预检照探测结果来：
  ```bash
  python3 -c "import yaml; print('pyyaml ok')" # 失败 → 试 python / py -3；再失败 → pip install pyyaml
  ```
  若失败，先告知用户"自演进看板需要 PyYAML，请 `pip install pyyaml`"，再决定是否仍加载
  （host 也会给同样提示，但 loader 提前讲更友好）。
- **ascend-panel（诊断）**：`traces/` 可能不存在（gitignored、按需生成）——host 已把
  "目录不存在"当空态处理，无需预建；但如果用户预期有历史诊断却显示为空，提示
  "运行 /skill:diagnose 后生成 traces/"。指标 tab 需要 Python 3 + **PyYAML**：
  「闭环判决」跑 `scripts/metrics_health.py --json`（判据读 `metrics/gates.yaml`），
  「实时计算」跑 `scripts/trace_metrics.py`；缺依赖时面板会显示「体检不可用」并给出
  安装/路径提示，**不会**假装闭环正常——所以预检失败仍可加载，只是首屏没有判决条。

## 流程

1. **确定要加载的面板**：用户要诊断可视化 → ascend-panel；要自演进状态（EV 卡/
   容量/归因）→ ev-panel；两者可同时加载（不同 tab id，互不冲突）。

2. **确保 `panel_from_file` 工具可用**（一个会话一次）：
   - 已有（工具目录里能查到 `panel_from_file`，本会话之前加载过）→ 跳到第 3 步。
   - 没有 → 加载 loader：读 `dsh-plugins/loader/panel-from-file.js`（~1.5KB），
     `cordis_define`（kind: new，idPrefix `ldr`，`code.host` ← 该文件全文）→
     `cordis_run`（mode: run）。**host-only 包，免审批**，几秒完成。
     该 loader 只用 `harness.registerTool` + `ctx.get('dynamicCordisRunner')` 两个
     公开机制，不依赖任何 DSH 补丁；若 DSH 支持 `cordis_define` 的 `codeFile`，
     也可以用 `codeFile.host` 指路径来加载 loader（更省 token）。

3. **加载面板**：调 `panel_from_file`（不要用 `cordis_define` 转写源码）：

   ```
   panel_from_file(
     host:   dsh-plugins/<面板>/panel-host.js,
     client: dsh-plugins/<面板>/panel-client.js,
     idPrefix: ascend-panel 用 sleu / ev-panel 用 evbd,
     name, purpose)
   ```

   它读盘 → `dynamicCordisRunner.define()` → `run()`，源码**原样进不可变 Package**
   （可被 `cordis_inspect_self` 审计），审批流与 `cordis_run` 一致。返回
   awaiting-approval 时告知用户在 UI 允许（Client 半需授权）；授权后 tab 出现。
   面板两个文件合计 ~70KB——**别把全文重新输出一遍**（几千 token、几分钟），
   发路径只要几十 token。

4. **验证**：确认插件 running 且无 waitingFor（`cordis_inspect_self`）；tab 出现在
   对话视图（conversation.view 插槽，按上表 id 核对）。自演进看板首次打开会调
   `scripts/ev_board_data.py` 汇总数据——确认数据区渲染（EV 卡/容量有真实数据，
   归因/S2 反馈可能显示"数据积累中"，如实）。若见"数据加载失败"，按顶部
   「依赖预检」逐条排查（pyyaml / traces / 工作区）。

## 回退（DSH 版本差异）

- **有 `codeFile` 参数**（`cordis_define` 支持）→ 可跳过第 2 步，直接
  `cordis_define(codeFile.host, codeFile.client)` + `cordis_run`，最少一次调用。
- **没有 `cordis_define` 的 `codeFile`，且 loader 也注册不了工具**（`harness.registerTool`
  缺失）→ 退回内联：读两个文件全文 → `code.host` / `code.client` 原样粘贴。
  文件是函数体形态（`return { apply(ctx) {...} }`），别改形态——动态插件不经过
  打包器，`export default` / `import` 等 ESM 语法无法加载。
- **改完面板代码**：`panel_from_file` 传 `pluginId` + `mode: 'update'` 追加新 Package
  再切换（读入的是定义时快照，改文件不会自动生效）。

## 交互原则

**跨 session（实测）**：工具 `panel_from_file` 是**进程全局**的——新 session 不必再加载
loader，直接就有它可用；重复加载 loader 会撞名但不报错（工具仍可用），只有要更新 loader
自身代码时才需重启 DSH。面板插件则是 **per-session** 的：新 session 认领不了旧 session
的插件（DSH 的 `define(kind:'existing')` 要求同 session 拥有），所以会新建一个同 tab id 的
插件——新 tab 覆盖旧 tab 的显示，旧插件仍在跑（RPC 还在、仍读它自己 session 的工作目录）。
彻底清理需重启 DSH，或在各 session 内对自己的插件 `cordis_stop`。

**重复加载 = 重载（幂等）**：面板代码改了就再调一次同一条 `panel_from_file`——
同 `idPrefix` 会复用本 session 的已有插件并切到新 Package（返回 `reused: true`），
不会堆出重复 tab；无需手工传 `pluginId`/`mode`。跨 session（DSH 重启）会新建同 tab id
的插件覆盖显示。

面板是**只读可视化 + 指令生成器**——展示状态、生成续接/沉淀指令供用户触发，
面板自身不做决策与写入（唯一例外：诊断面板的沉淀状态标记由用户在面板确认后
更新）。自演进看板纯只读：展示 EV 卡状态与演进信号，产卡/验证走 agent + 攒批。

## 依赖

- DSH 会话（`cordis_define` / `cordis_run` / `cordis_inspect_self` 工具；loader 额外用
  `harness.registerTool` + `ctx.get('dynamicCordisRunner')`——DSH 内置机制，无需补丁）
- 工作区为 ascend-sleuth 仓库（Host 从 session.header.cwd 解析数据目录）
- Host 服务：`fs` / `sessions` / `shell`
- **ev-panel（自演进）**：Python 3 + **PyYAML**（`scripts/ev_board_data.py` 聚合数据）——
  host 自动探测解释器（`python3` → `python` → `py -3`）；缺 pyyaml 时 host 会提示安装；
  loader 侧建议激活前预检（见「依赖预检」）。
- **ascend-panel（指标）**：`shell` + Python 3 + PyYAML——
  「闭环判决」跑 `scripts/metrics_health.py --json`、「实时计算」跑 `scripts/trace_metrics.py`；
  解释器同样自动探测（`python3` → `python` → `py -3`）。缺依赖时判决条退化为
  「体检不可用」+ 可执行提示（不是空面板、也不谎报正常）。
- 诊断「打开证据」依赖 `open`/`xdg-open`（macOS/Linux 均可用；Windows 未覆盖）。

## 说明

- 动态插件定义只存在于当前 DSH 进程，重启后需重新加载（本 skill 即为此设计）。
- 仓库内 `dsh-plugins/<面板>/` 是代码的权威版本（含 README 使用说明）；
  `dsh-plugins/loader/` 是加载入口的一次性加载器；本 skill 负责串起两者——
  改代码走仓库，加载走这里。
