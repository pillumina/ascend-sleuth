# ascend-sleuth 诊断面板（DSH 插件）

诊断可视化操作台，对话视图提供两个 tab：

- **诊断**：会话列表（状态/时间/搜索/过滤）→ 展开轨迹（summary/evidence/reason/reference）→ 证据文件打开
- **指标**：知识库健康 / 流程闭环 / timeline 快照 / 实时计算

## 加载方式

本插件是动态 Cordis 插件，定义只存在于当前 DSH 进程，重启后需重新加载。

### 快速开始

在 DSH 对话中粘贴（或直接 `/skill:preload-panel`）：

```
请加载 ascend-sleuth 诊断面板：读 dsh-plugins/ascend-panel/panel-host.js 作为 code.host、
panel-client.js 作为 code.client，用 cordis_define（kind: new）创建动态 Cordis 插件并 cordis_run 激活。
完成后对话视图应出现「诊断」「指标」两个 tab。
```

agent 读本目录文件 → `cordis_define` → `cordis_run` 激活，无需手动复制代码。`/skill:preload-panel` 是同一流程的 skill 封装（仅 DSH）。

前置条件：agent 具备 `cordis_define` / `cordis_run` 工具；工作区为 ascend-sleuth 仓库（面板读 `traces/`、`knowledge/`、`references/`、`metrics/`）。

### 手动加载

1. `cordis_define`（kind: new，idPrefix 如 `sleu`）：
   - `code.host` ← [panel-host.js](panel-host.js) 全文
   - `code.client` ← [panel-client.js](panel-client.js) 全文
2. `cordis_run`（mode: run）激活 → 出现「诊断」「指标」两个 tab

**形态约束**：文件是 `cordis_define` 需要的函数体（`return { apply(ctx) {...} }`），直接粘贴。不要改成 `export default` / `import`——动态插件代码不经过打包器，ESM 语法无法加载（此前因此失败过一次）。

## 依赖

- Host：`fs` / `sessions` / `shell`。`shell` 缺失时证据文件打开与实时计算降级，其余正常。
- 工作区：ascend-sleuth 仓库（Host 从 session.header.cwd 解析）。

## 功能

| 能力 | 说明 |
|---|---|
| 会话列表 | 状态徽章/更新时间/计数；搜索（session/状态/框架/定位 case）；过滤（全部/库中已有/新形态/未定位） |
| 轨迹展开 | summary 问题背景；每步 output/reason；evidence（inline 原文折叠/文件点击打开/缺口标记）；reference 参考层徽章 |
| 续接 | 未解决会话生成 resume 指令（复制→对话触发） |
| 沉淀 | 四状态呈现 + 沉淀指令 copy + 双标记操作（Tier2/Tier3 回写） |
| 指标 tab | 知识库健康（case/reference 聚合）+ 流程闭环（沉淀漏斗/续接/参考参与）+ timeline 快照（live 置顶 + 小样本标注）+ 实时计算 |
| 学习环提示 | 反馈未回报警示 + 回报指令生成（复制→对话触发 feedback 动作） |

## 版本

- 2026-09-01：以运行验证版本重新沉淀（等价原 pkg-48）。此前沉淀因改成 ESM 形态导致加载失败，废弃重建。
