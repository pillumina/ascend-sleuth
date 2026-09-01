---
name: preload-panel
description: >
  在 DSH 会话中热加载 ascend-sleuth 诊断面板插件：读取
  dsh-plugins/ascend-panel/panel-host.js 与 panel-client.js，
  用 cordis_define 创建动态 Cordis 插件并 cordis_run 激活，
  对话视图出现「诊断」「指标」两个 tab。
  仅 DSH 可用——依赖 DSH 的 cordis_define / cordis_run 工具
  与 conversation.view 插槽；其他 agent（Claude Code / Codex / pi）无此机制。
---

# Preload Panel

DSH 会话中加载诊断可视化面板（会话列表 / 轨迹展开 / 证据打开 / 指标视图）。

## 触发

用户需要面板但当前会话没有「诊断」「指标」tab 时，用本 skill 加载。

## 流程

1. **读插件代码**：读 `dsh-plugins/ascend-panel/panel-host.js`（Host 半）与 `dsh-plugins/ascend-panel/panel-client.js`（Client 半）。文件是 `cordis_define` 需要的函数体形态（`return { apply(ctx) {...} }`），**原样粘贴，不要改形态**——动态插件代码不经过打包器，`export default` / `import` 等 ESM 语法无法加载。

2. **创建插件**：`cordis_define`（kind: new，idPrefix 用 `sleu`）：
   - `code.host` ← panel-host.js 全文
   - `code.client` ← panel-client.js 全文

3. **激活**：`cordis_run`（mode: run）。若返回 awaiting-approval，告知用户需在 UI 允许（Client 半需授权）；授权后插件激活，对话视图出现「诊断」「指标」两个 tab。

4. **验证**：确认插件 running 且无 waitingFor（`cordis_inspect_self`）；tab 出现在对话视图（conversation.view 插槽，id `ascend-diagnose` / `ascend-metrics`）。

## 交互原则

面板是**指令生成器**——复制指令 → 粘贴对话 → agent 执行。面板自身不做决策：续接/沉淀/回报都生成指令供用户触发，最终交互在 agent 与用户之间。

## 依赖

- DSH 会话（`cordis_define` / `cordis_run` / `cordis_inspect_self` 工具）
- 工作区为 ascend-sleuth 仓库（面板 Host 从 session.header.cwd 解析 `traces/`、`knowledge/`、`references/`、`metrics/`）
- Host 服务：`fs` / `sessions` / `shell`（`shell` 缺失时证据文件打开与实时计算降级，其余正常）

## 说明

- 动态插件定义只存在于当前 DSH 进程，重启后需重新加载（本 skill 即为此设计）。
- 仓库内 `dsh-plugins/ascend-panel/` 是代码的权威版本（含 README 使用说明）；本 skill 是加载入口，两者分离——改代码走仓库，加载走这里。
