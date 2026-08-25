# Ascend Sleuth 术语表

昇腾训练/推理问题的诊断知识体系。把问题定位从个人经验沉淀为结构化、可检索、可演化的团队知识资产。本文件是项目的领域术语表（ubiquitous language）：文档、skill、issue、PR 中的用词以此为准，避免同义漂移。

## Language

**Case（案例）**:
存储在 `knowledge/<namespace>/`（Tier 2）的结构化诊断规则，可被机器执行：症状、quickly_check 匹配模式、diagnosis 验证步骤、root cause、fix。由 groom 从一条或多条 postmortem 提炼而来。
_避免_：Rule、entry、record、规则、条目

**Postmortem（复盘记录）**:
存储在 `postmortems/`（Tier 3）的原始（或轻结构化）调查记录：发生了什么、试过什么、root cause 是什么。是 case 的提取来源，可以是完整成文，也可以是指向外部调查文档的指针。
_避免_：事故报告、RCA 文档、case

**Case ID（案例标识）**:
case 与其来源 postmortem 共用的稳定标识（如 `SGL-PD-HEAP-001`）。在 postmortem 生成时分配，升格进 Tier 2 后保持不变。
_避免_：工单号、issue 编号

**Groom（例行维护）**:
每周执行的维护流程（`/skill:knowledge-groom`）：把 postmortem 升格为 case、校验引用、去重、重算置信度、软退休过期 case。
_避免_：整理、策展、curate

**Triage Tree（分诊树）**:
Tier 1 路由表（`triage-tree.yaml`）。把症状模式映射到搜索命名空间与问题类别。始终加载，不超过 30 个分支。
_避免_：决策树、路由表

**Namespace（命名空间）**:
`knowledge/` 下按 训练/推理 × 框架 划分的目录（如 `training/mindspeed-llm/`、`inference/sglang/`），诊断时的主检索维度。
_避免_：category、文件夹、模块

**Category（问题类别）**:
与 namespace 正交的问题性质维度：`interrupt`（中断：hang/crash/OOM）、`precision`（精度：NaN/发散）、`performance`（性能：吞吐/延迟）。决定 quickly_check 的形态与深度排查的默认工具。
_避免_：type、severity、类型

**Dispatch Axes（分发维度）**:
三个正交维度合称：Platform（A2/A3/A5）、Workload（训/推 × 框架 → namespace）、Category（interrupt/precision/performance），共同决定加载哪些 case。
_避免_：路由维度

**Confidence Score（置信度）**:
由 groom 维护、按时间衰减的指标（hits / (hits + misdiagnoses)）。校准：>0.8 高可信（可直接应用）、0.5-0.8 中（准备 plan B）、<0.5 低（仅作提示）。
_避免_：priority、weight、优先级

**Trace（诊断轨迹）**:
诊断 session 期间写入 `diagnosis_state-<session_id>.yaml` 的分步审计记录。误诊归因的唯一依据：区分 case 错（改知识库 YAML）与执行错（改 skill 流程）。
_避免_：log、transcript、历史

**Skill（技能）**:
遵循 Agent Skills 规范、由 `SKILL.md` 定义的 agent 可调用工作流。本体系共四个：diagnose、to-postmortem、knowledge-groom、resume-diagnosis。
_避免_：command、plugin、tool

**Severity（严重度闸门）**:
决定修复建议的交付方式：`benign`（直接给 fix）、`service-affecting`（给 fix 但标注副作用，如 requires-restart）、`data-loss-risk`（不给 fix，输出停机保现场指令）。
_避免_：priority、urgency、影响

**Soft Match（软匹配）**:
版本兼容的判定方式：case 的 `compat` 区间与客户环境对照，不匹配只下调置信度、不把 case 排除出候选集。这是刻意设计——在 A5 上验证过的 case 可能同样适用于 A3。
_避免_：strict match、精确匹配
