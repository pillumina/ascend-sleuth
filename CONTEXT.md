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
遵循 Agent Skills 规范、由 `SKILL.md` 定义的 agent 可调用工作流。本体系共六个：diagnose、to-postmortem、to-reference、issue-ingest、knowledge-groom、resume-diagnosis。
_避免_：command、plugin、tool

**Severity（严重度闸门）**:
决定修复建议的交付方式：`benign`（直接给 fix）、`service-affecting`（给 fix 但标注副作用，如 requires-restart）、`data-loss-risk`（不给 fix，输出停机保现场指令）。
_避免_：priority、urgency、影响

**Soft Match（软匹配）**:
版本兼容的判定方式：case 的 `compat` 区间与客户环境对照，不匹配只下调置信度、不把 case 排除出候选集。这是刻意设计——在 A5 上验证过的 case 可能同样适用于 A3。
_避免_：strict match、精确匹配

**Reference（先验知识词条）**:
存储在 `references/`（ADR-0008）的独立事实或通用方法论，**独立于任何具体事故**。区别于 case（事故定位闭环）。两种组织形态（组织单元 = 验证单元）：**表形态**（一个族/域/模块一个文件——error-code / fault-pattern / env-var-table）与**独立词条**（fact：tool / platform-fact / software-fact / command-side-effect；flow：methodology）。来源类型：official-doc / engineer-input / case-derived（决定初始置信度与审核深度）；状态：draft / active / pending-review / deprecated。
_避免_：entry、wiki 段落、先验条目

**ref_knowledge（case 侧知识引用）**:
case YAML 的可选字段，结构化引用 reference 词条（`ref: <reference-id>` + `role: signature-source / fix-methodology / root-cause-context`）。反向视图（哪些 case 引用了某 reference）是派生的、不存储——一条关系只存一处（ADR-0008 §7）。
_避免_：references（那是 case 的事故溯源 URL 列表，两回事）

## 理论术语（design-theory.md 用词标准）

理论文档的中文学术用词以此为准：正文用中文标准译名，首次出现括注英文。同物异名在此处统一。

**信念（belief）**:
对假设持有的概率分布 $P(h)$。区别于置信度——置信度（confidence）是 case 属性的点估计，信念是推断过程的分布态。
_避免_：相信程度、可信度

**证据（evidence）**:
用于更新信念的观测——症状、日志片段、版本组合、验证输出。日常语境的"信息/材料"不套用此词。
_避免_：资料、素材

**先验（prior）/ 后验（posterior）/ 似然（likelihood）**:
Bayes 推断三件套的标准译名：证据到来前/后的信念分布；假设成立时看到该证据的可能性。
_避免_：验前/验后、可能性（指 likelihood 时）

**期望损失（expected loss）**:
行动的损失按信念加权的平均，决策准则的最小化目标。utility 理论的 loss 对偶。
_避免_：期望代价、平均损失

**止损（halt）**:
发现无界损失风险时的行动：停止自主决策，保全现场，交还人。操作上对应"停机保现场、通知 owner"。
_避免_：停机（单独使用）、熔断

**升级（escalation）**:
低层组件能力不足以覆盖当前扰动时，控制权移交更高多样性层级——最终是移交给人。
_避免_：上报（不含移交控制权语义）

**泛化（generalization）**:
理论对同类系统（四公理成立者）的适用性。
_避免_：外推（extrapolation 是数值数学术语，语义不符）

**影子价格（shadow price）**:
约束优化中资源的边际价值：一单位预算折合多少期望损失。一切权衡的兑换率。
_避免_：隐含价格、机会成本（语义近但不等）
