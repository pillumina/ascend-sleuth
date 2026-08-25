# ascend-sleuth

[![platform: Ascend NPU](https://img.shields.io/badge/platform-Ascend%20NPU-CC0000?logo=huawei&logoColor=white)](https://www.hiascend.com/)

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

| Skill | 作用 | 何时用 | 触发 |
|---|---|---|---|
| `diagnose` | 核心诊断循环：症状路由 → 匹配 case → 给 fix（高危根因提示先停服务）或转深度排查；fix 交付后标记 `feedback_pending` 待回报；全程写 trace | 训练/推理出现中断、精度、性能问题 | 显式 `/skill:diagnose` |
| `to-postmortem` | 把一次定位沉淀成知识；任意来源（本地 session / Kimi 对话 / 手工笔记）汇入，过语义校验 + 脱敏，产出到待审队列 | 定位完，无论在哪查的都来这沉淀 | 可自动触发 |
| `knowledge-groom` | 周期维护：批处理待审队列（预分诊 new/variant/covered 三分类）、升格、校验引用、去重、重算置信度、软退休、重建索引、容量预告 | 领域 owner 每周 | 显式 `/skill:knowledge-groom` |
| `resume-diagnosis` | 续接被打断的诊断，读状态文件 + trace 复述现场 | 诊断被会议/上下文压缩打断；多人交接 | 显式 `/skill:resume-diagnosis` |

各 skill 的完整细节（severity 闸门、trace 规则、语义校验等）见对应 `skills/<name>/SKILL.md`。诊断类 skill 设为 user-only——诊断决策要人触发，不让模型自动跑；`to-postmortem` 可自动触发，鼓励沉淀。

## 用法示例

**`diagnose`** — 把客户提供的症状、框架、日志片段告诉 agent（agent 不访问客户环境，信息都你来提供）：

```
/skill:diagnose

客户 A5 (950) 训练在 step ~3000 hang，all_to_all timeout，world_size=128。
框架 mindspeed-llm 2.5.0。报错栈尾：[粘贴相关 rank 的日志片段]
```

agent 路由到 `training/mindspeed-llm/` → 匹配 case → 给结构化结果（CASE-ID + confidence + fix + rollback）或转深度排查。信息不够时主动问你需要向客户要什么。全程写 trace。

**`to-postmortem`** — 沉淀一次定位，输入方式灵活（粘贴 / 文件 / 多文件 / 目录）：

```
/skill:to-postmortem "[粘贴对话或笔记]"                       # 内联
/skill:to-postmortem ~/cases/custA/notes.md                    # 单个文件
/skill:to-postmortem ~/cases/custA/ ~/cases/custB/hang.md      # 多文件
/skill:to-postmortem ~/cases/wiki-export/                      # 目录（批量导入）
```

agent 提取症状/根因 → 给命名空间建议（`[1] training/mindspeed-llm` / `[2] common`），你确认 → 生成 YAML + 脱敏。多文件/目录时批量确认命名空间（一次过），语义校验逐个跑。
也可以不显式调用：`/diagnose` 结束后直接说“沉淀一下这次”，agent 自动触发。

**`resume-diagnosis`** — 诊断被打断后续接：

```
/skill:resume-diagnosis
```

读活跃的 `diagnosis_state-*.yaml`（每个并发诊断一个文件；多个时列出让选），复述上次停在哪步、排除了哪些 case、当前 active case，等你贴回命令输出后继续。

**`knowledge-groom`** — 领域 owner 每周维护知识库：

```
/skill:knowledge-groom
```

扫 `postmortems/` 新增记录 → 升格、校验 references、去重、重算置信度、软退休 → 产出变更摘要交 owner 审（提交由 owner 自己来，不自动开 PR）。当前版本的批处理流程：批处理 `postmortems/inbox/` 待审队列（预分诊三分类 + 人审）→ 变更走 PR + 标签 + 双签（见 [docs/git-workflow.md](docs/git-workflow.md)）→ merge 后重建索引。

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
             ├ 人审 accept / adjust / reject（~30 秒/条）
             ├ 高风险变更 → kb/high-risk → 双 owner 签字
             └ 变更 PR（受保护分支 + CODEOWNERS + CI: build_index --check）→ merge
                  ├ new     → 升格 knowledge/<ns>/ + 重建 _index.yaml
                  ├ variant → 并入已有 case（扩 compat 区间）
                  └ covered → postmortem 转正 Tier 3（不丢弃）
                              └──► 下次诊断直接命中 —— 学习闭环
```

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

## 核心设计原则

1. **结构优先于纪律**——能写进文件结构的规则不依赖 prompt 自觉：阶段一加载是读 `_index.yaml`（不是逐文件自律），反馈捕获是 `feedback_pending` 文件标记（不是记性），索引新鲜度是 `--check` 硬校验（不是提醒）。
2. **检索只提名，验证放行**——匹配到 case 不等于给 fix：diagnosis checks 对照真实信息验证后才输出，`data-loss-risk` 只给 halt。误诊代价远高于多问一轮。
3. **agent 是语义层，底座是词法层**——模糊表述由 agent 归一成可 grep 的签名；知识库保持 YAML + git（可 diff、可审计、可回滚）。不上向量库，论证与重评触发条件见 [ADR-0002](docs/adr/0002-retrieval-no-rag-lightweight-index.md)。
4. **上限是承重设计**——30 case/namespace 的 cap 保证全量索引一次加载、暴力过滤永远成立。cap 先于任何检索基础设施。
5. **建议与决定分离**——预分诊、agent 自起草、置信度重算都只产出"建议 + 证据"，accept/adjust/reject 永远是人；人只做判定不做结构化（20 分钟 → 30 秒）。
6. **人审环节批处理化**——持续汇入下"顺手审"反工程师节律：inbox 队列 + 周批处理 + 停留标红。队列不是档案。
7. **trace 先于指标**——没有 trace 就没有误诊归因（case 错 vs 执行错）、路由准确率、反馈捕获率。不可观测的机制等于不存在。
8. **方法论与知识解耦**——`skills/`/`scripts/`/`docs/` 是可公开可 fork 的框架；`knowledge/`/`postmortems/` 是团队资产，入库前脱敏。集中运作或 fork 自积累皆可。

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
scripts/                     build_index.py（索引生成/新鲜度校验）、trace_metrics.py（trace→指标）
eval/golden/                 回归测试夹具（公开仓放构造示例；真实 fixture 放私有仓）
docs/eval.md                 skill 改动评估流程
docs/git-workflow.md         git 门控/审核/合入闭环（标签集、CODEOWNERS、CI、双签）
docs/adr/                    设计决策记录（0002：检索为何不上 RAG、容量论证）
CODEOWNERS.example           owner 落实后启用（配合分支保护做硬门控）
.github/workflows/           kb-checks CI（索引新鲜度 + YAML 语法）
```

**改 skill 本身前**，照 [`docs/eval.md`](docs/eval.md) 跑 golden 回归套件——别把原来能查的查坏了。

**公私分离**：`skills/`、`references/`、`examples/` 是方法论，可公开。`knowledge/` 与 `postmortems/` 的 case 内容跟踪进仓库（含已播种的 `SGL-PD-HEAP-001`），边界前移为**入库前脱敏**（to-postmortem 的 redact 步骤）：新知识必须脱敏后才能进 `knowledge/` 与 `postmortems/` 正式目录，`postmortems/inbox/` 草稿同样过脱敏。含不可公开客户数据的条目标 `scope: internal_only` 并移团队私有仓。运行时状态文件 `diagnosis_state*.yaml` 由 `.gitignore` 挡在仓库外。

## 部署模式

两种皆可，机制不变（inbox / groom / 索引 / CI 在两种模式下同样工作）：

- **集中式**：训/推团队共用一个 repo。`CODEOWNERS` 按 namespace 划审批权，`common/` 与 `triage-tree.yaml` 双 owner 签。
- **框架式（fork 自积累）**：团队 fork 本仓库，知识自己积累或导入；上游只同步方法论目录（`skills/ scripts/ docs/ examples/ eval/`），知识目录不参与上游合并。

gating / 审核 / 分发 / 合入的 git 落地细节（标签集、双签、通知、平台移植）见 [docs/git-workflow.md](docs/git-workflow.md)。

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

诊断时 fix 是 agent 给的建议，由人手动应用到客户环境，agent 不自动改生产。

## 路线图

**v1（已实现）**：trace 与误诊归因、学出的置信度、语义校验、分布式命令参数化、triage 优雅退化、severity 字段、生成式 Tier 2 索引（`knowledge/_index.yaml`）、intake 待审队列 + groom 三分类批处理、反馈捕获结构化（`feedback_pending`）、trace→metrics 脚本。

**v1.5**：router 从 trace 错例自动建议修订、fixture replay 半自动化、非单调版本兼容、agent 自起草候选 case。

**v2**：从 trace 挖掘结构改进分类器、可信自动晋升。

**明确不做**（论证见 [docs/adr/0002](docs/adr/0002-retrieval-no-rag-lightweight-index.md)）：向量检索/RAG 基础设施、ANN、跨组织联邦协议。embedding 字段化（intake 语义去重）**推迟而非否决**——重评触发条件写在 ADR 里，升级由数据触发，不时尚驱动。

## 状态

v1 骨架 + 首条播种 case（`knowledge/inference/sglang/SGL-PD-HEAP-001.yaml`，已进 `_index.yaml`）。结构、schema、triage-tree、intake 队列、生成索引、两个维护脚本（索引/指标）都已就绪。

下一步：照样例模板手工播种 10-30 条高频 case（按三类问题覆盖），或批量导入内网 wiki 历史案例（`/skill:to-postmortem <dir>` 进 inbox 队列）。灌完第一批、跑过一轮真实的 to-postmortem 和 knowledge-groom，用 `scripts/trace_metrics.py` 的实测数据（过滤率/退休率/路由准确率）重算 [ADR-0002](docs/adr/0002-retrieval-no-rag-lightweight-index.md) 的容量推演，再决定 v1.5 机制的上线顺序。
