# ascend-sleuth

[![skills.sh](https://skills.sh/b/pillumina/ascend-sleuth)](https://skills.sh/pillumina/ascend-sleuth)

昇腾（Ascend）训练与推理支持的诊断 skill 套件。把问题定位从个人经验沉淀为团队可复用、可持续演进的知识资产。

遵循 [Agent Skills](https://agentskills.io/) 标准，可在 pi、Claude Code、Codex 等任意支持该标准的 agent 中使用。

## 为什么需要它

昇腾支持工程师每天面对三类问题：训练/推理中断（hang、crash、OOM）、精度异常（loss 发散、FP8 衰减）、性能退化（吞吐下降、通信占比过高）。这些问题的根因高度重复，但知识分散在个人笔记、IM 聊天、各处 wiki 里——新 case 每周新增，A2/A3/A5 平台差异持续扩大，任何依赖单个人手工维护的方案都会在三周内腐化。

ascend-sleuth 用一套可演化的知识库把这些经验结构化：诊断时按症状路由到已验证的 case，定位完自动沉淀成新知识，每周有人维护知识库的去重、退休、置信度。知识越用越准，不依赖任何单个人持续手工维护。

## 安装

```bash
npx skills@latest add pillumina/ascend-sleuth
```

选择要装的 skill 和目标 agent 即可。或在 pi / Claude Code 里手动把 `skills/` 目录加入 skill 搜索路径。

挑核心的装：

```bash
npx skills@latest add pillumina/ascend-sleuth -g -a pi -a claude-code \
  -s diagnose -s to-postmortem -s knowledge-groom
```

加载后在 agent 里以 `/skill:<name>` 调用。

## 包含的 Skills

### diagnose

核心诊断循环。收集症状，按 triage-tree 路由到命名空间，两阶段加载并验证知识库中的 case，命中给出修复建议（高危根因改为提示先停服务），未命中转入深度排查。全程写过程日志用于误诊归因。

**适用场景：**

- 训练或推理出现 hang / crash / OOM / 精度异常 / 性能退化
- 你在能执行命令的 agent 中（Claude Code、Codex、pi）
- 想按团队已验证的经验快速定位根因

### to-postmortem

把一次问题定位沉淀成知识。输入可以是 Claude Code/Codex 的对话、Kimi/DeepSeek 网页版对话，或纯手工排查笔记。自动提取症状和根因，给出命名空间建议，人确认后生成结构化 YAML，过语义校验和脱敏。这是整个体系中唯一对所有人开放的环节——无论问题在哪定位的，都能在这里沉淀。

**适用场景：**

- 一次定位结束后，把过程变成可复用的 case
- 团队成员用了不同的 agent 或纯手工排查，需要统一沉淀入口

### knowledge-groom

知识库的周期性维护引擎。扫描新增的定位记录（含 agent 自动起草的候选 case），结构化升格到知识库，校验引用完整性，检测重复，重算置信度，软退休过期 case，重新生成人读速查表。建议每周运行。

**适用场景：**

- 领域 owner 每周维护知识库质量
- 知识库增长后需要去重、拆分、退休

### emergency-triage

生产中断时的紧急排查。跳过完整诊断流程，直接给出带风险标注的人类可读排查清单，不改配置、不记录。事后用 to-postmortem 补。

**适用场景：**

- 客户明确说生产中断、需要先恢复服务
- 没有时间走 15 到 30 分钟的完整诊断

### resume-diagnosis

续接一个被打断的诊断 session。读取状态文件和过程日志，复述上次停在哪一步、排除了哪些 case，等人贴回命令输出后继续。

**适用场景：**

- 诊断被会议或上下文压缩打断
- 多人协作同一个问题，需要交接现场

## 工作原理

知识分三个层次，按需加载，控制上下文消耗：

| 层 | 内容 | 加载时机 |
|---|---|---|
| Tier 1 | `triage-tree.yaml`，症状到命名空间的路由，不超过 30 个分支 | 始终加载 |
| Tier 2 | `knowledge/` 下结构化的 case 规则 | 症状匹配后两阶段加载 |
| Tier 3 | `postmortems/` 原始定位记录 | 前两层未命中时关键词检索兜底 |

问题有两个正交维度，分别由不同机制承载：

- **在哪查**：训推 × 框架，决定加载哪个命名空间（`training/mindspeed-llm/` 等）。这是知识库的目录结构。
- **什么性质**：问题类型（中断 / 精度 / 性能），决定诊断路径和工具。三类各有独立的 quickly_check 形态和默认排查脚本——中断用错误签名 grep，精度用数值阈值断言，性能用 profiler 指标比对。

诊断过程全程记 trace（加载了哪些命名空间、按什么顺序跑了哪些检查），用于事后归因：一次误诊是知识库里的 case 错了，还是 agent 执行流程错了，两者修复路径不同。

## 知识库结构

```
knowledge/
├── training/{mindspeed-llm,mindspeed-mm,verl}/
├── inference/{vllm-ascend,sglang}/
├── common/                  多框架共用的权威记录（由 groom 提升）
├── _archive/                软退休的过期 case
└── platforms/{a2,a3,a5}.md  平台背景知识
triage-tree.yaml             Tier 1 路由
postmortems/                 Tier 3 原始记录
```

**公私分离**：`skills/`、`references/`、`examples/` 是方法论，可以公开。`knowledge/` 和 `postmortems/` 的真实内容含客户日志和集群信息，必须私有。本仓库只含方法论和空脚手架，真实案例应放团队私有仓库。`.gitignore` 已配置好这条边界——即使把真实 case 写进 `knowledge/`，也不会被推到这个公开仓库。

## 日常工作流

```
接到问题
  ├─ 紧急（生产中断）→ /skill:emergency-triage
  └─ 否 → /skill:diagnose（本地 agent 诊断 + 知识匹配）
定位完 → /skill:to-postmortem 沉淀
  （无论这次是 /diagnose 诊断的、还是之前用 Kimi/手工查的，都从这里汇入）
被打断 → /skill:resume-diagnosis
领域 owner 每周 → /skill:knowledge-groom
```

诊断时 fix 是 agent 给的建议，由人手动应用到客户环境，agent 不自动改生产。

## 路线图

**v1（已实现）**：trace 与误诊归因、学出的置信度、语义校验、分布式命令参数化、triage 优雅退化、severity 字段。

**v1.5**：非单调版本兼容、agent 自起草候选 case、批量导入历史案例（`/bootstrap-from-corpus`）。

**v2**：从 trace 挖掘结构改进分类器、可信自动晋升、跨团队联邦。

## 状态

这是 v1 骨架。结构、schema、triage-tree、一个完整字段的样例 case（`examples/sample-case.yaml`）都已就绪，但 `knowledge/` 是空的——这是诚实的冷启动状态。

下一步：照样例模板手工播种 10 条高频 case（按三类问题覆盖），或批量导入内网 wiki 的历史案例。灌完第一批、跑过一轮真实的 to-postmortem 和 knowledge-groom，再用数据决定 v1.5 机制的上线顺序。
