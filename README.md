# ascend-sleuth

[![platform: Ascend NPU](https://img.shields.io/badge/platform-Ascend%20NPU-CC0000?logo=huawei&logoColor=white)](https://www.hiascend.com/)

中文 · [English](README.en.md)

面向昇腾（Ascend）训练与推理支持的诊断 skill 套件，把问题定位经验沉淀为结构化、可检索、可演化的团队知识资产。遵循 [Agent Skills](https://agentskills.io/) 标准，可在 pi、Claude Code、Codex 等任意支持该标准的 agent 中使用。

## 如何使用本文档

按角色选择入口，其余章节按需查阅：

- **支持工程师（用诊断）**：读「安装」和「用法示例」即可上手，约十分钟。想了解匹配为什么可信，再看「工作原理」与「核心设计原则」。
- **知识库维护者（每周例行维护）**：在上述基础上读「日常工作流」「部署模式」，然后是 [docs/git-workflow.md](docs/git-workflow.md)。
- **框架开发者 / 评估者**：通读本文档后，读 [docs/design-principles.md](docs/design-principles.md)（设计原则——约束一切设计、实现与演进的规范性基础），再看 [docs/evolution.md](docs/evolution.md)（自演进设计——系统如何随使用改进、为什么不会改坏），然后是 [docs/roadmap.md](docs/roadmap.md) 与 [ADR](docs/adr/0001-soft-version-matching.md)，最后读 `skills/<name>/SKILL.md`（各 skill 的操作细节）。

文中术语（case、postmortem、namespace、groom、trace 等）的规范定义见 [CONTEXT.md](CONTEXT.md)。

## 为什么需要它

昇腾支持工程师日常面对三类问题：训练或推理中断（hang、crash、OOM）、精度异常（loss 发散、FP8 衰减）、性能退化（吞吐下降、通信占比过高）。这些问题的根因高度重复，相关知识却分散在个人笔记、IM 聊天和各处 wiki 里。新 case 每周都在出现，A2/A3/A5 平台差异还在扩大，任何依赖个人手工维护的方案都难以长期维持。

ascend-sleuth 把这些经验沉淀为结构化知识库。诊断时按症状路由到已验证的 case；问题定位结束后，新知识进入待审队列，由每周一次的例行维护完成去重、升格与退休。知识随着使用不断校准，不依赖任何个人的持续投入。

## 安装

```bash
npx skills@latest add pillumina/ascend-sleuth
```

选择要安装的 skill 和目标 agent 即可，也可以在 pi 或 Claude Code 中手动把 `skills/` 目录加入 skill 搜索路径。只装核心的：

```bash
npx skills@latest add pillumina/ascend-sleuth -g -a pi -a claude-code \
  -s diagnose -s to-postmortem -s knowledge-groom
```

加载后在 agent 里以 `/skill:<name>` 调用。

## 包含的 Skills

| Skill | 作用 | 何时使用 | 触发方式 |
|---|---|---|---|
| `diagnose` | 核心诊断循环：按症状路由，匹配并验证 case，给出修复建议或转深度排查，全程记录 trace | 训练或推理出现中断、精度、性能问题 | 显式 `/skill:diagnose` |
| `to-postmortem` | 把一次定位沉淀为知识，任意来源均可汇入，经校验和脱敏进入待审队列 | 问题定位结束之后，无论在哪里定位的 | 可自动触发 |
| `knowledge-groom` | 周期维护：批处理待审队列、升格、去重、置信度重算、软退休、索引重建 | 领域 owner 每周 | 显式 `/skill:knowledge-groom` |
| `resume-diagnosis` | 续接被打断的诊断：读取状态文件与 trace，复述现场后继续 | 诊断被会议或上下文压缩打断 | 显式 `/skill:resume-diagnosis` |

各 skill 的完整细节（severity 闸门、trace 规则、语义校验等）见对应 `skills/<name>/SKILL.md`。三个诊断类 skill 均设为 user-only，诊断决策由人触发；`to-postmortem` 允许自动触发，以降低沉淀门槛。

## 用法示例

**diagnose** — 把客户提供的症状、框架、日志片段告诉 agent。agent 不访问客户环境，所有信息由你提供：

```
/skill:diagnose

客户 A5 (950) 训练在 step ~3000 hang，all_to_all timeout，world_size=128。
框架 mindspeed-llm 2.5.0。报错栈尾：[粘贴相关 rank 的日志片段]
```

agent 路由到 `training/mindspeed-llm/` 并匹配 case：命中时给出结构化结果（CASE-ID、confidence、fix、rollback），未命中时转入深度排查。信息不足时，agent 会明确提示需要向客户补充什么。全程记录 trace。

**to-postmortem** — 沉淀一次定位，支持四种输入方式：

```
/skill:to-postmortem "[粘贴对话或笔记]"                       # 内联
/skill:to-postmortem ~/cases/custA/notes.md                    # 单个文件
/skill:to-postmortem ~/cases/custA/ ~/cases/custB/hang.md      # 多文件
/skill:to-postmortem ~/cases/wiki-export/                      # 目录（批量导入）
```

agent 提取症状与根因，给出命名空间建议供你确认，然后生成 YAML 草稿与 postmortem 并完成脱敏，产出到 `postmortems/inbox/` 待审队列。多文件或目录输入时命名空间一次批量确认，语义校验逐条执行。也可以在 `/skill:diagnose` 结束后直接说“沉淀一下这次”，agent 会自动触发。

**resume-diagnosis** — 诊断被打断后续接。读取活跃的 `diagnosis_state-*.yaml`（每个并发诊断一个文件，存在多个时列出让选），复述上次停在哪一步、排除了哪些 case、当前候选是什么，等你贴回命令输出后继续。

**knowledge-groom** — 领域 owner 每周维护知识库。先批处理 `postmortems/inbox/` 待审队列（预分诊三分类加人审），随后校验引用、检测重复、重算置信度、软退休过期 case，产出变更摘要。变更经 PR 与标签门控合入（流程见 [docs/git-workflow.md](docs/git-workflow.md)），merge 后重建索引。

## 工作原理

知识按三个层次组织，按需加载以控制上下文消耗：

| 层 | 内容 | 加载时机 |
|---|---|---|
| Tier 1 | `triage-tree.yaml`：症状到命名空间的路由，不超过 30 个分支 | 始终加载 |
| Tier 2 | `knowledge/` 下结构化的 case 规则 | 症状匹配后两阶段加载：先读生成索引 `knowledge/_index.yaml` 过滤候选，再加载全量验证 |
| Tier 3 | `postmortems/` 下的原始定位记录 | 前两层未命中时关键词检索兜底 |

问题沿两个正交维度展开。**在哪查**由训练/推理与框架决定，对应加载哪个命名空间（如 `training/mindspeed-llm/`），这是知识库的目录结构。**什么性质**由问题类型决定：中断、精度、性能三类各有独立的 quickly_check 形态和默认排查脚本——中断用错误签名 grep，精度用数值阈值断言，性能用 profiler 指标比对，三者不混用。

诊断过程全程记录 trace：加载了哪些命名空间、按什么顺序执行了哪些检查。trace 用于事后归因。一次误诊究竟是知识库里的 case 写错了，还是 agent 执行流程走偏了，两者的修复路径完全不同，混在一起会改坏本来正确的东西。

两个循环驱动整个系统。下图是完整全景，涉及的机制在后文与各专项文档中展开，初次阅读不必逐行理解，需要时再回来对照。

```
【诊断循环 · 每次问题 · 分钟级】

 工程师（客户症状 / 日志栈尾 / 版本组合）
   └► /skill:diagnose
        ├► Tier 1  triage-tree.yaml 症状路由
        ├► Tier 2  _index.yaml 阶段一过滤 → 候选 ≤5 全量验证
        │           ├─ 命中 → severity 闸门 → fix（data-loss-risk 只给 halt）
        │           │          └► feedback_pending 标记 → 工程师回报
        │           │                → confidence 回写（hits/misdiagnoses）
        │           └─ 未命中 → Tier 3 postmortems/ 检索 → 人 + agent 深度排查
        └► 全程 trace → diagnosis_state-<session_id>.yaml

【演化循环 · 每周 · git 门控】

 /skill:to-postmortem（任意来源：session / Kimi / 手工 / wiki）
   └► postmortems/inbox/（待审队列，脱敏后入库）
        └► /skill:knowledge-groom 周批审
             ├ 预分诊 new_pattern / variant_of / covered_by（建议 + 证据）
             ├ 人审 accept / adjust / reject（约 30 秒/条）
             ├ 高风险变更 → kb/high-risk → 双 owner 签字
             └ 变更 PR（受保护分支 + CODEOWNERS + CI: build_index --check）→ merge
                  ├ new     → 升格 knowledge/<ns>/ + 重建 _index.yaml
                  ├ variant → 并入已有 case（扩 compat 区间）
                  └ covered → postmortem 转正 Tier 3（不丢弃）
                              └──► 下次诊断直接命中 —— 学习闭环
```

这套系统如何随使用自我改进、每个演化机制配什么护栏防止越学越错，完整设计见 [docs/evolution.md](docs/evolution.md)。

## 核心设计原则

以下是面向使用者的节选；完整的规范性原文（十一条，各含推导与禁止项）见 [docs/design-principles.md](docs/design-principles.md)。

**用结构承载规则，不依赖执行自觉。** 凡是能写进文件结构的约定，就不放在 prompt 里靠模型遵守：阶段一加载固定为读生成的索引文件，反馈追踪落在状态文件的标记位上，索引新鲜度由脚本硬校验。写进结构的规则不会随执行质量波动。

**检索只负责提名，验证决定放行。** 症状匹配只产生候选，诊断检查项对照客户环境的真实信息验证通过后，才输出修复建议；标记为 data-loss-risk 的根因只输出停机保现场的指令。多问一轮的代价，远低于一次误诊。

**语义判断交给 agent，知识底座保持词法。** 工程师的模糊描述由 agent 归一为可检索的错误签名；知识库本身始终是 YAML 和 git，可 diff、可审计、可回滚。这是不引入向量检索的直接原因，完整论证与重评条件见 [ADR-0002](docs/adr/0002-retrieval-no-rag-lightweight-index.md)。

**规模上限是一项架构承诺。** 每个命名空间 30 条 case 的上限并非洁癖：正是这个上限保证了全量索引可以单次加载、暴力过滤永远成立。上限先于任何检索基础设施存在。

**自动化产出建议，人做决定。** 预分诊、候选 case 起草、置信度重算都只给出建议和依据，采纳、调整或驳回由维护者判定。人的工作从结构化整理上移为快速审批，单条成本从二十分钟降到半分钟以内。

**人工审核按批处理组织。** 持续汇入的场景下，逐条即时审核违背工程师的工作节律。待审内容进入 inbox 队列，owner 每周集中处理一次，停留过久的条目自动标红催办。

**先保证可观测，再谈改进。** 误诊归因（该改知识还是改流程）、路由准确率、反馈捕获率，全部来自 trace 记录。没有 trace，这些机制既无法评估，也无从改进。

**方法论与知识资产分离。** `skills/`、`scripts/`、`docs/` 是可公开、可复用的框架；`knowledge/` 与 `postmortems/` 是团队自有资产，入库前脱敏。团队既可以集中维护一个仓库，也可以 fork 后自行积累知识，两种方式共用同一套机制。

## 知识库结构

```
knowledge/
├── _index.yaml              Tier 2 生成索引（scripts/build_index.py 生成；阶段一直读，变更后重建）
├── training/{mindspeed-llm,mindspeed-mm,verl}/
├── inference/{vllm-ascend,sglang}/
├── common/                  多框架共用的权威记录（由 groom 提升）
├── _archive/                软退休的过期 case
└── platforms/{a2,a3,a5}.md  平台背景知识
triage-tree.yaml             Tier 1 路由
postmortems/                 Tier 3 原始记录
└── inbox/                   待审知识队列（groom 周批处理三分类后转正/升格）
examples/sample-case.yaml    canonical 样例（全 schema 演示）
CONTEXT.md                   领域术语表（中英对照）
scripts/                     build_index.py（索引生成/新鲜度校验）、trace_metrics.py（trace→指标）
eval/golden/                 回归测试夹具（真实 fixture 脱敏后入库；无法脱敏的放私有仓）
docs/eval.md                 skill 改动评估流程
docs/design-principles.md    设计原则（规范性基础，约束全部设计与演进）
docs/evolution.md            自演进设计（演化机制、护栏、数据回路）
docs/git-workflow.md         git 门控/审核/合入闭环（标签集、CODEOWNERS、CI、双签）
docs/roadmap.md              闸门驱动路线图（五维度事项、验收标准、入口闸门、检查点）
docs/adr/                    设计决策记录（0002：检索为何不上 RAG、容量论证）
CODEOWNERS.example           owner 落实后启用（配合分支保护做硬门控）
.github/workflows/           kb-checks CI（索引新鲜度 + YAML 语法）
```

修改 skill 本身之前，先按 [docs/eval.md](docs/eval.md) 跑一遍 golden 回归套件，确认原本能正确命中的场景没有被改坏。

**公私分离**：`skills/`、`references/`、`examples/` 是方法论，可公开。`knowledge/` 与 `postmortems/` 的内容跟踪进仓库（含已播种的 `SGL-PD-HEAP-001`），边界设在入库前脱敏：新知识必须脱敏后才能进入正式目录，`postmortems/inbox/` 草稿同样执行脱敏；含不可公开客户数据的条目标记 `scope: internal_only` 并移入团队私有仓库。运行时状态文件 `diagnosis_state*.yaml` 由 `.gitignore` 挡在仓库之外。

## 部署模式

两种部署方式都支持，inbox、groom、索引与 CI 机制在两种模式下同样工作：

- **集中式**：训练与推理团队共用一个仓库，`CODEOWNERS` 按命名空间划分审批权，`common/` 与 `triage-tree.yaml` 的变更需要双 owner 签署。
- **框架式**：团队 fork 本仓库后自行积累或导入知识，上游只同步方法论目录（`skills/ scripts/ docs/ examples/ eval/`），知识目录不参与上游合并，因此没有冲突面。

gating、审核、分发与合入的 git 落地细节（标签集、双签、通知、平台移植）见 [docs/git-workflow.md](docs/git-workflow.md)。

## 日常工作流

```
接到问题 → /skill:diagnose（本地 agent 诊断 + 知识匹配）
  紧急时告诉 agent“这是紧急情况”→ 它先给 stabilize 建议、不钻深度排查
定位完 → /skill:to-postmortem 沉淀 → postmortems/inbox/（待审队列）
  （无论这次是 /diagnose 诊断的、还是之前用 Kimi/手工查的，都从这里汇入）
被打断 → /skill:resume-diagnosis
领域 owner 每周 → /skill:knowledge-groom 批处理 inbox
  → 变更 PR（三分类标签 + 高风险双签 + kb-checks CI）→ merge（索引随批重建）
fix 应用后 → 回报结果（diagnose/resume 启动时会主动追问）→ confidence 回写
```

诊断给出的 fix 是 agent 的建议，由人手动应用到客户环境，agent 不自动改生产。

## 路线图

Roadmap 采用闸门驱动：每个事项定义入口条件（数据或事件触发）与验收标准，不按日期排期。

- **v1（已实现）**：三层检索与生成索引、intake 队列与 groom 批处理、trace 与反馈闭环、git 门控与 CI。
- **v1.5（按闸门解锁）**：router 从 trace 错例演进、fixture replay 半自动化、agent 自起草候选 case、指标分账与容量预测。
- **v2**：trace 结构挖掘、可信自动晋升。
- **明确不做**：向量检索/RAG、ANN、跨组织联邦（论证见 [ADR-0002](docs/adr/0002-retrieval-no-rag-lightweight-index.md)）。

各事项按架构、可演进性、可维护性、可观测性、流程合理性五维度组织，需求、验收标准、入口闸门与常设检查点见 [docs/roadmap.md](docs/roadmap.md)。

## 状态

当前是 v1 骨架加首条播种 case（`knowledge/inference/sglang/SGL-PD-HEAP-001.yaml`，已进入 `_index.yaml`）。结构、schema、triage-tree、待审队列、生成索引和两个维护脚本均已就绪。

下一步是照样例模板播种 10-30 条高频 case（覆盖三类问题），或批量导入内网 wiki 历史案例（`/skill:to-postmortem <dir>` 会进入 inbox 队列）。第一批知识灌入并跑过一轮真实的 to-postmortem 与 knowledge-groom 之后，用 `scripts/trace_metrics.py` 的实测数据（过滤率、退休率、路由准确率）重算 [ADR-0002](docs/adr/0002-retrieval-no-rag-lightweight-index.md) 的容量推演，再决定 v1.5 各机制的上线顺序。
