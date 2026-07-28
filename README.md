# ascend-sleuth

> 昇腾（Ascend）训练与推理支持的**知识驱动诊断套件**：5 条 skill + 三层知识库 + 薄 Script 胶水。
> 把"问题定位"从个人经验变成团队可复用、可演化的资产。

## 为什么叫 sleuth

**sleuth** — 暗中调查的侦探，对应"问题定位 / 根因排查"。套件 5 条 skill 天然映射到一套调查流程：

| skill | 隐喻 |
|---|---|
| `diagnose` | 侦查（核心循环） |
| `emergency-triage` | 快速出警 |
| `resume-diagnosis` | 冷案续接 |
| `to-postmortem` | 结案归档 |
| `knowledge-groom` | 证据整理 |

## 核心认知：两个正交轴

整个体系建立在一个判断上——问题有两个独立维度，分别由不同机制承载，**不要混**：

```
轴 1（在哪查）：训推 × 框架  →  namespace        training/mindspeed-llm/  ...
轴 2（什么性质）：category  →  诊断路径 + 工具     interrupt | precision | performance
```

- **训推不是 category**——它已经是轴 1 的顶级分区（`training/` vs `inference/`）。
- **三类 category 各对应独立工具集**：interrupt → 日志/core dump；precision → 数值分析（`mem-analyze`）；performance → profiler（`ascend-profile-analyze`）。三类的 `quickly_check` 形态也不同（grep / 数值阈值 / 指标比对）。

## 目录结构

```
ascend-sleuth/
├── skills/                         5 条 skill（方法论，可公开）
│   ├── diagnose/                   核心诊断循环（旗舰）
│   │   ├── SKILL.md
│   │   └── references/             从 skill 目录解析的细节文档
│   │       ├── diagnosis-procedure.md
│   │       ├── platform-dispatch.md
│   │       └── script-integration.md
│   ├── emergency-triage/SKILL.md
│   ├── resume-diagnosis/SKILL.md
│   ├── to-postmortem/SKILL.md
│   └── knowledge-groom/SKILL.md
├── knowledge/                      ★ 知识库（含客户数据，必须私有）
│   ├── training/{mindspeed-llm,mindspeed-mm,verl}/
│   ├── inference/{vllm-ascend,sglang}/
│   ├── common/                     多框架共用的权威记录（groom 提升）
│   ├── _archive/                   软退休的过期 case
│   └── platforms/{a2-910a,a3-910b,a5-910c}.md
├── triage-tree.yaml                Tier 1 路由（3 category × 训推）
├── postmortems/                    Tier 3 原始记录
├── CHEATSHEET.md                   人读速查表（groom 重生成；路径 B 主入口）
├── examples/sample-case.yaml       canonical 样例（演示全 schema 字段，非真实知识）
├── docs/metrics.md                 量化指标日志
└── diagnosis_state.yaml.example    状态文件 + trace 模板
```

## 部署：方法论公开，知识私有

这是部署红线。两者**分两个 repo**：

- **方法论**（`skills/` + `references/` + `examples/`）——可公开，放 skills.sh 或公开 git。
- **知识库**（`knowledge/` + `postmortems/`）——含客户日志、集群信息、内部 IP，**必须私有**，放公司内网 git。

skill 的 `SKILL.md` 通过 cwd-相对路径指向 KB（`knowledge/`、`triage-tree.yaml`、`CHEATSHEET.md`、`postmortems/`）。**运行诊断时，cwd 应为包含这些 KB 文件的目录**（团队 KB repo 根，或本包根）。

## 安装

把 `skills/` 目录加入 agent 的 skill 搜索路径。示例（pi）：

```json
// .pi/settings.json
{ "skills": ["<path-to-ascend-sleuth>/skills"] }
```

其他 agent（Claude Code / Codex）同理，或用 [skills CLI](https://skills.sh) 装方法论到多 agent（KB 另放私有 repo）。

加载后在 agent 里调用：`/skill:diagnose`、`/skill:to-postmortem`、`/skill:knowledge-groom` 等。

## 日常工作流

```
接报 → 紧急？─是→ /skill:emergency-triage
       │否
       能跑命令？─是→ /skill:diagnose（路径 A）
                │否→ 查 CHEATSHEET.md（路径 B）
诊断完 → /skill:to-postmortem（A/B 都用，沉淀知识）
被打断 → /skill:resume-diagnosis
领域 owner 每周 → /skill:knowledge-groom
```

## v1 范围

已实现的 6 个 v1 机制：trace + 执行保真度归因、学出置信度、语义校验、`command_template` + `rank_selector`、优雅退化、severity 字段。
路线图（v1.5+）：compat 非单调区间、自起草候选 case、批量导入、结构挖掘、trusted auto-promotion、联邦 common/。

## 现状与下一步

这是**骨架**——结构、schema、triage-tree、一个 canonical 样例都齐了，但 `knowledge/` 是空的（诚实的冷启动状态）。下一步：

1. 照 `examples/sample-case.yaml` 模板，手工播种 10 条高频 case（**按 category 覆盖全 3 类**：如 4 interrupt + 3 precision + 3 performance）。
2. 或批量导入历史案例（v1.5 的 `/bootstrap-from-corpus` 实现前，先用 `/skill:to-postmortem` 一篇篇灌）。
3. 把 `knowledge/` + `postmortems/` 拆到私有内网 git repo。

灌完第一批 case、跑过一轮真实的 `/skill:to-postmortem` + `/skill:knowledge-groom`，再用数据决定 v1.5/v2 机制的上线顺序。
