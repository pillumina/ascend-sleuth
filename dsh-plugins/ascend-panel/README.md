# ascend-sleuth DSH 诊断面板插件（可复用资产）

诊断可视化操作台：会话列表（状态/时间/搜索/过滤）→ 展开轨迹（summary/evidence/reason/reference）→ 证据文件打开；指标 tab（知识库健康 / 流程闭环 / timeline 快照 / 实时计算）。

## 使用方式（DSH 动态 Cordis 插件）

本插件是**动态 Cordis 插件**（会话级，定义不持久——DSH 重启后需重新定义，这是平台特性）。

**在任意 session 重新加载：**

1. 用 `cordis_define`（kind: new，idPrefix 随意如 `sleu`）创建插件：
   - `code.host` ← 粘贴 [panel-host.js](panel-host.js) 全文
   - `code.client` ← 粘贴 [panel-client.js](panel-client.js) 全文
2. `cordis_run`（mode: run）激活 → 对话视图出现「诊断」「指标」两个 tab

**为什么直接用这份而不是改形态**：本目录文件就是 `cordis_define` 需要的**函数体形态**（`return { apply(ctx) {...} }`），粘贴即用。**不要**改成 `export default {...}` 或加 `import`——动态插件代码不经过打包器，`import`/`export` 语法会直接失败（历史教训：另一 session 改成 ESM 形态后加载失败）。

## 依赖（运行环境需具备）

- Host：`fs` / `sessions` / `shell` 服务（可选——缺 `shell` 时证据文件打开与实时计算降级，其余正常）
- 面板读取仓库的 `traces/`、`knowledge/_index.yaml`、`references/`、`metrics/timeline.yaml`——工作区必须是 ascend-sleuth 仓库（Host 从 session.header.cwd 解析）

## 功能清单

| 能力 | 说明 |
|---|---|
| 会话列表 | 状态徽章/更新时间/计数；搜索（session/状态/框架/定位 case）；过滤（全部/库中已有/新形态/未定位） |
| 轨迹展开 | summary 问题背景 + 每步 output/reason + evidence（inline 原文折叠/文件点击打开/缺口标记）+ reference 参考层徽章 |
| 续接 | 未解决会话生成 resume 指令（复制→对话触发） |
| 沉淀 | 四状态呈现 + 沉淀指令 copy + 双标记操作（Tier2/Tier3 回写） |
| 指标 tab | 知识库健康（case/reference 聚合）+ 流程闭环（沉淀漏斗/续接/参考参与）+ timeline 快照（live 置顶 + 小样本标注）+ 实时计算 |
| 学习环提示 | 反馈未回报警示 + 回报指令生成（复制→对话触发 feedback 动作） |

## 版本

- 2026-09-01：以运行验证版本重新沉淀（等价原 pkg-48：布局优化 + 简洁文案 + 回报指令 + 知识库健康/流程闭环/小样本/欠账说明）。此前沉淀因 ESM 形态改动导致另一 session 加载失败，已废弃重建。
