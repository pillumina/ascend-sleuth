# ascend-sleuth Roadmap

> Roadmap 采用闸门驱动而非日期驱动：每个事项定义入口条件（数据或事件触发）与验收标准，解锁与否由 metrics 和 trace 数据判定，不按日历排期。这与 [ADR-0002](adr/0002-retrieval-no-rag-lightweight-index.md) 的原则一致：升级由数据触发，而非由技术趋势触发。全部事项的立项依据与闸门设计派生自[设计原则](design-principles.md)第八、十一条。
>
> 阅读方式：五个维度回答"哪类改进"（架构 / 可演进性 / 可维护性 / 可观测性 / 流程合理性），阶段视图回答"何时做"（Phase 0 → 1 → 2，由闸门衔接）。事项 ID 稳定，供 groom 报告和 issue 引用。

## 现状基线（v1，已就绪）

| 维度 | 已就绪 |
|---|---|
| 架构 | 三层检索、生成索引 `_index.yaml`、triage-tree 路由、字段级平台分发、软版本匹配、双部署模式 |
| 可演进性 | confidence 反馈闭环（`feedback_pending` 结构化捕获）、intake 队列、三分类预分诊 |
| 可维护性 | groom 周批处理、git 门控（标签/CODEOWNERS/双签）、kb-checks CI、golden eval 框架 |
| 可观测性 | trace 词表、`trace_metrics.py`、`metrics/timeline.yaml` 数据、`docs/metrics.md` 指标定义、容量表 |
| 流程 | severity 闸门、串联保护（两次未解决转人工）、日志裁剪、脱敏、随机审序 |

---

## 一、架构

本维度关注系统结构在规模与时间压力下是否持续成立。

| ID | 事项 | 需求 / 验收标准 | 入口闸门 | 阶段 |
|---|---|---|---|---|
| A1 | Tier 3 postmortem frontmatter 结构化 | `postmortems/**/*.md` 加 frontmatter（framework / category / platform / case-id / keywords）；诊断 Tier 3 检索先按字段过滤再 grep；to-postmortem 产出自动带 frontmatter；存量文件一次性补齐 | Tier 3 语料 >300 篇，或 tier3 检索频繁但挽救率指标偏低 | v1.5 |
| A2 | 格子容量治理与拆分（ADR-0004 已落地 category 分层） | cap 按 (framework×category) 格子计：soft_cap 30 触发评估 + 健康指标（候选溢出/重复率/维护时长）；hard_cap 60 强制拆。拆分建议 → 人确认；目录迁移、`_index.yaml` 重建、fixture namespace 断言同步，**同一 PR 完成**。**触发实例**：inference/vllm-ascend interrupt 81/30 **已超 hard_cap 60**（2026-W36/37 多轮沉淀与补 case：36→50→76→81）。可拆分子族实测：moe 13 / startup-failure 12 / mtp(spec-decode) 11 / mooncake+kv 9 / patch-layer 5 / 310P 4 / cudagraph 3。**健康指标（EV-2026-006 定，capacity_health.py 精确 regex 口径，EV-008 后复测仍适用）**：interrupt 候选溢出率 25%（8/32 输入 >5 候选，中位数 3、max 12），略超 20% 阈值但非检索崩坏，precision/performance 0% 健康。结论：**暂不强制拆**（ADR-0004 拒目录深度+2；真问题是阶段一全读 token，非目录结构），脚本保留持续复测（沉淀后重跑，升破 30% 再评估阶段一加载协议优化）；**soft_cap/hard_cap 阈值与拆分轴是执行参数（待 metrics 复核，见 docs/metrics.md），数据齐后 owner 确认固化，不自动执行** | 格子超 soft_cap 且健康指标恶化 / 超 hard_cap | 按闸门 |
| A3 | 第二拆分轴（platform）ADR | 若 category 拆分后仍超限，写 ADR-0003 论证 platform 轴或索引分片的取舍 | category 拆分后单 namespace 仍 >100 条 | v2 前置 |
| A4 | 非单调版本兼容实测 | 真实非单调 case（如 2.7 失效、2.8 恢复）出现时，groom 的 `_archive/` 复活检查跑通全流程，结论记录进 ADR | 首个真实非单调 case 被 groom 处理 | 按事件 |
| A5 | 容量推演重算 | 用实测过滤率、退休率、增速重算 ADR-0002 的稳态规模与容量结论；确认或修订"不上 RAG"决策及触发条件 | 第 6 个月，或 metrics 首次给出完整过滤/退休数据 | 常设检查点 |

## 二、可演进性

本维度关注学习闭环是否随使用持续变准。

| ID | 事项 | 需求 / 验收标准 | 入口闸门 | 阶段 |
|---|---|---|---|---|
| E1 | agent 自起草候选 case | Tier-2 未命中但最终解决的 session，diagnose 产出含候选 case 的 postmortem 落 inbox（confidence 初始低值）；groom 按正常三分类验证；采纳率进 metrics | 首次发生"Tier-2 未命中但最终解决" | v1.5 |
| E2 | router 从 trace 错例演进 | groom 从 trace 提取路由错例（`triage.routed` 集合 vs 命中 case 实际 namespace），产出 triage-tree 修订建议（diff 形式），走 `kb/high-risk` 双签合入；修订后用 `trace_metrics.py` 复测路由准确率并记入 metrics | trace ≥20 个可归因 session（`hit.case` 与 `triage.routed` 齐全；**计数口径 = 真实 diagnose trace，S2 replay result 不计入**——与 S2 池独立，防同池自我优化，见 evolution-pipeline §11.2） | v1.5 |
| E3 | embedding intake 预分诊 | 按 ADR-0002 既定设计落地：`semantics.text_hash` + `model` 字段 + `.embeddings/` sidecar（人审文件 diff 保持干净），embedding 经 API 生成、本地暴力余弦，**不引入向量库**；预分诊输出三分类 + 相似度证据，人审环节不变 | inbox 周均 ≥4 条持续 4 周，或 covered/variant 占比可观测地 >50% | 推迟项 |
| E4 | trusted auto-promotion | 近重复 + quickly_check 通过 + 连续 N 次兄弟命中未误诊的新 case 可自动升格，标 `auto_promoted: true`，进月度抽审 | v2 入口条件（见阶段视图） | v2 |
| E5 | trace 结构挖掘 | 从 trace 语料报告低判别力 quickly_check、噪声 triage 分支、高验证耗时 case，产出结构改进建议 | v2 入口条件 | v2 |
| E6 | proposal 影响视图（skill-impact 语义） | `ev_proposal.py` 增 `--impact`：按 target_component 聚合历史尝试（提案×diff×eval 结果×decision 结局），evolve-check/self-evolve 产卡前必查，防同组件重提被拒方案（来源：WikiSkill skill-impact.md 咨询语义，arXiv 2608.27454；机制决议见 evolution-pipeline §12a，EV-2026-009） | 首个真实 L2 rejected/回滚簇出现（此前以手工"查同组件先例"步骤运行，见 evolve-check/self-evolve） | 按闸门 |
| E7 | 成功模式提取信号 | evolve-check T 表加成功向信号 T8：本轮某流程/组件多次成功且成功路径可复述（对照成功 vs 失败执行差在哪）→ 产 L2 卡固化成功模式（来源：WikiSkill maintainer 成败对照分析 §3.2.2/E.2；机制决议见 evolution-pipeline §12a，EV-2026-009） | 常态运行中首次出现可复述成功模式（无信号即止，不预设轮次） | 按闸门 |

## 三、可维护性

本维度关注例行维护的成本上界，目标始终低于一人每周一小时的量级。

| ID | 事项 | 需求 / 验收标准 | 入口闸门 | 阶段 |
|---|---|---|---|---|
| M1 | CODEOWNERS 转正 + 分支保护 | `CODEOWNERS.example` 复制为 `.github/CODEOWNERS` 填真实账号；main 开分支保护 + required review；验证一次硬门生效（越权直推被拒） | owner 人名确定 | Phase 0 出口 |
| M2 | fixture replay 半自动化 | 脚本以 replay 模式喂 `eval/golden/*.yaml` 给 /skill:diagnose，比对 expected（top-3 命中断言，容忍 LLM 非确定性），产出改前/改后报告；报告随变更摘要交 owner | 真实 golden fixture ≥5 条 | v1.5 |
| M3 | fixture 自动生成 | `replay_trace.py --emit-fixtures` 从 resolved+feedback 确认的 trace 派生 fixture 候选（输入=user 原文，期望=实际命中）；groom 人确认入库；覆盖报告同步更新（见 O4）。断言分层：未确认 trace 只做弱断言回归，不作正确性基准 | 首个 resolved+feedback 确认的 trace | v1.5+ |
| M4 | groom 报告留档规范 | 每周 groom-report issue 固定模板：变更摘要 / 高风险项 / 容量表 / 标红项；季度回顾可直接回溯 | 首轮真实 groom 完成后固化模板 | Phase 1 初 |
| M5 | groom token 预算（结构性减负） | 现状 groom 每次全量扫 knowledge（~47K）与 references（~82K），随库线性涨，职责重、token 大（实测核算）。修法：①确定性环节脚本化（引用校验/值重复/置信度重算/容量统计由脚本算完，agent 只读 diff 摘要，不读全量）②按信号触发（R3/R8 可选建议不全量默认扫）③references 维护按触发而非每轮全跑。验收：groom 单次 token 降至可读摘要量级（目标 <30K），且功能不缺失 | 实测单次 groom >150K token，或库规模到 60 case | v1.5 |

## 四、可观测性

本维度关注每个机制是否可评估、每个升级决策是否有数据依据。其中多数为常态化动作，没有完成态。

| ID | 事项 | 需求 / 验收标准 | 入口闸门 | 阶段 |
|---|---|---|---|---|
| O1 | 指标常态化 | 每两周 `trace_metrics.py` 输出经人复核 append `metrics/timeline.yaml`（数据）；所有比例必须带分母；小样本（分母 <10）显式标注 | Phase 0 出口后即常态 | 常设 |
| O2 | 指标按团队分账 | state 文件记 workload（training/inference）；`trace_metrics.py` 按组输出命中率与误诊率，两组各自复盘 | 首次真实使用后的小改动 | v1.5 |
| O3 | 反馈捕获率监测 | feedback 捕获率（回报 session / 给出 fix 的 session）进 metrics；连续两期 <50% 触发流程检查（追问话术、nag 时机） | O1 常态化后 | 常设 + 阈值 |
| O4 | eval 覆盖报告 | groom 每轮输出覆盖矩阵：有 case 的 `(namespace × category × platform)` 格子 vs 有 fixture 的格子，缺口列表（"inference/sglang 0 条"、"precision 类偏弱"） | M2 完成后并入 groom | v1.5+ |
| O5 | 容量趋势预测 | 容量表增加近 4 周增速与"预计达 80% 日期"，拆分预告由数据给出而非事后发现 | A2 首次触发前后 | v1.5 |
| O6 | 诊断报告（trace 派生视图） | diagnose 收尾渲染人读报告：症状→路由→候选→验证→根因→fix 的推理叙事 + 证据回溯（每判断指回 trace step）+ 强度标注（已验证/推测/未知）。trace 为唯一数据源、零数据模型改动；默认本地留档，分享前脱敏；1-2 分钟读完（证据链折叠可展开）。质量基准见历史讨论 | 首次真实诊断后 | v1.5 |
| O7 | 健康报表（groom R10 标准产出） | groom 产出自包含 HTML 数据报表（离线生成，`health_report.py` 脚本 + 必要时 agent 美化样式，数据不变）：①知识库结构视图（容量/覆盖/缺口，git 数据，本地=中心一致；知识结构图可用 archify）②系统运作视图（命中/误诊/趋势，traces 汇总，头部诚实标注〔中心全量 N sessions〕或〔本地视角 M sessions〕）。**只读聚合数据**（timeline.yaml + _index 头注 + trace_metrics/replay 脚本输出），不读 case 全文（token 预算，呼应 M5）。**职责划分**：本地 groom 也产（个人视角），中心 owner groom 产全量，同一指令、数据范围不同，如实标注。服务"改进知识库/改进系统流程"的决策（原则八决策端） | 任一 live 指标期积累后 | v1.5 |
| O8 | 交互型 replay 评测（ixn-replay） | 分期披露脚本驱动 diagnose 交互，按"追问召回 + 决定性字段在链 + 过早结论"评分（机制决议 EV-2026-012；设计 docs/evolution-ixn-replay.md；工具 `scripts/ixn_replay.py`）。落地形态分两级：harness v1（prepare/score/aggregate + 样本库筛选制入库）→ 常态化（评分阈值固化、交互面分数进 timeline，须分母标注）。**归因型 replay（PR 引用为 gold）为兄弟维度，蓝图** | harness v1 + ≥3 条真实 staged 运行（含 held-out/self 分流）后校准；常态化的分数进 timeline 前提 = 样本 ≥10 带分母 | v1.5 |

## 五、流程合理性

本维度关注人工环节的成本：每个动作应当足够轻，轻到不会被跳过。

| ID | 事项 | 需求 / 验收标准 | 入口闸门 | 阶段 |
|---|---|---|---|---|
| P2 | 双签核验自查单 | `kb/high-risk` PR 模板带核验清单（两组各至少一人批），merge 前勾选；groom-report 汇总本期高风险项及签署情况 | M1 完成后 | Phase 1 初 |
| P3 | fork 模式同步演练 | 首个团队 fork 时 dry-run 上游同步：方法论目录 merge 无冲突、知识目录零触碰，产出简短记录 | 首个 fork 发生 | 按事件 |
| P4 | 紧急路径实测复盘 | 首个真实紧急 session 走完 stabilize 路径后，复盘 stabilize ↔ 深度排查的切换点是否清晰，必要时修订 SKILL.md 紧急节 | 首个真实紧急事件 | 按事件 |

> **P1 已移除**：原"data-loss-risk 通知链路落地"是过度设计。诊断系统只输出建议（severity 三档 + halt 语义），**不接管通知行为**（对接 on-call/IM 是把诊断工具扩张成事故响应系统）。severity 三档（benign / service-affecting / data-loss-risk）是输出策略（SKILL.md 一行），保留；"通知 owner"是给工程师的一句话建议，不是系统链路。

---

## 阶段视图（闸门 → 解锁）

**Phase 0 · 冷启动（当前）**：目标是让所有机制吃进第一批真实知识。

事项：播种 10-30 条高频 case（或 wiki 批量导入进 inbox）、M1、O1 启动。

出口条件（全部满足）：
- [ ] 在库 case ≥20 条
- [ ] 完成 ≥1 轮真实 to-postmortem + knowledge-groom 全流程
- [ ] 分支保护与 CODEOWNERS 硬门生效（M1）
- [ ] 指标双周节奏建立（O1）

**Phase 1 · v1.5 池**：各事项由自身闸门独立解锁，无统一开始时间：E1（事件）、E2（trace ≥20）、M2（fixture ≥5）、O2、A1、A2、A4、M3、M4、O4、O5、P2。建议顺序：先 E1/M2（学习与安全网），后 A2（容量到了才拆）。

**Phase 2 · v2 池**：入口条件：trace ≥100 个 session，且 Phase 1 完成 ≥3 项，且指标趋势稳定（连续两个季度可解读）。事项：E4、E5、A3。

**推迟项**：E3（embedding 预分诊），闸门见事项表；落地设计已锁在 ADR-0002，届时直接实施不重新论证。

## 常设检查点

| 频率 | 动作 | 载体 |
|---|---|---|
| 每周 | 容量表 + inbox 标红 + groom-report | groom 变更摘要 / issue |
| 每两周 | trace → 指标，人复核追加 | `trace_metrics.py` → `metrics/timeline.yaml` |
| 每月 | `needs-structurer-review` 超 14 天提醒；inbox >2 周催办 | groom-report |
| 第 6 个月 | 容量推演重算（A5） | ADR-0002 修订或确认 |
| 持续 | ADR-0002 三条重评触发条件监控（namespace >100 且路由劣化 / Tier 3 >5K 篇且挽救率不足 / 真联邦出现） | metrics + groom |
| 季度 | 用 metrics 校准本 roadmap 的闸门数值；回顾"三层架构是否真的在变好用" | 本文件 + `metrics/timeline.yaml` |
| 季度 | **L3 自演进季度自评**（evolution-pipeline §6.6 六项审视：信号质量/授权/产出/腐化/参数/流程 → 结论落参数或结构提案） | `proposals/reviews/<YYYY-Qn>.md`（首次真实自评：2026-Q4，数据前提 = ≥1 季度运行 + S1 反馈 >0；预演 dry-run 见 2026-Q3-selfreview-preview） |

## 明确不做

向量检索 / RAG 基础设施、ANN 索引、跨组织联邦协议：论证与重评触发条件见 [ADR-0002](adr/0002-retrieval-no-rag-lightweight-index.md)。触发条件命中前不进任何阶段池。

## 待定的人事决策（阻塞 Phase 0 出口）

1. 部署模式确认：集中式 or 框架式 fork（机制已兼容两者，确认后 P3 才有演练对象）
2. 领域 owner 人名（每 namespace 一人，groom 批审收件人）
3. 体系维护人（高风险变更第二签）

## 本 roadmap 自身的演化

- 新增事项必须带：所属维度、需求/验收标准、入口闸门；无闸门的事项默认进"待定"而非阶段池
- 废弃事项移入下方"不再做"并留一行理由，不删除记录
- 闸门数值每季度用 metrics 复核，数值是假设的量化形态，同样服从数据修正

### 不再做

（暂无）

### 待定（理论预言、未达立项条件）

由 [设计理论](design-theory.md) §8 生成的设计标准（依设计原则修订门槛，需先有使用检验）：

- **VPI 序提问**：信息不全时按期望信息价值/成本比排序提问
- **校准度量**：confidence 的 reliability 式校准指标进 metrics
- **先验超参显式化**：investigation_quality → 初始 score 作为 Beta 超参管理
- **多样性审计**：triage/quickly_check 判别力对照症状空间的定期审计
- **参数治理**：设计常数（串联保护 n=2、批审 30 秒上限、每 ns 30 条 cap）按理论 §7 的限定属参数估计，纳入 metrics 实测复核，数据足够时重校（n=2 可由误诊级联率复核，30 秒由批审实际耗时复核）
- **PR 描述机器层生成**（**部分落地**）：to-postmortem / groom 直接产出符合 `.github/PULL_REQUEST_TEMPLATE/` 的 PR body 草稿（预分诊、证据、CI 链接、置信变化由系统数据自动填充，人只补脱敏自查与动机）。**已落地**：5 模板加"Agent 预核意见（可选）"区块、`pr-template` CI 校验模板结构与关键区块（不拦 agent 意见缺失，内网/手动链路体验约束）。**剩余**：各 skill 产出时自动填充预分诊/证据/置信字段的完整 body 草稿。闸门：E1 落地后或团队 PR 量周均 ≥3

由首次真实数据评估（eval-reports/0001，git 历史可查）产出的工程项（按收益排序）：

- **triage 词边界匹配**：`hang`⊂`changed`、`inf`⊂`INFO` 等子串误配浪费候选预算，修复为 `\b` 词边界，低成本高收益
- **inference_interrupt 补错误码型症状**：107030 等 error-code 型无分支命中，靠优雅退化兜底
- **fallback regex 收紧**：related-issue 提及、启动命令词、通用 token 三类候选污染源
- **回放 harness 的 metric-form 分支**：performance 类 metric 断言需数值提取比对，regex 回放测不了
- **variant 签名追加进主 case fallback**：防签名微变（交叉回放改进项）

由 [设计理论](design-theory.md) §10（选型与规模推演）生成的工程预备项（带触发闸门）：

- **索引分片**：`_index.yaml` 拆为每命名空间一个（单文件在 ~60 个命名空间时逼近上下文预算）。闸门：活跃命名空间 ≥40，或优雅退化触发频率连续两月上升
- **分层 triage**：两级路由（category → framework），路由容量 30×30。闸门：单级分支触及 30 上限且路由准确率开始下降（配合 E2 错例数据）
- **动态闸门收紧**：成熟区域（区域命中率持续高）的软匹配收紧为区间内匹配。闸门：metrics 首次产出按区域的命中率分布（依赖 O2 分账）

### 明确不做（设计讨论结论，防过度设计）

**使用/协作/KPI 类观测指标，不设计、不采集**。讨论结论（指标消费方三问 + 部署模式约束）：

- **部署模式多样，无统一采集面**：可能同时存在"内网私有沉淀 + GitHub 开源消费"（内网案例拿不出仓，只在内部 git 平台沉淀）、"全开源集中维护"（问题全从 issue 来）、"个人 fork 私有沉淀不协作"。跨形态的 KPI 统计无统一数据源，设计必为过度工程
- **身份维度与体系隐私约束冲突**：支撑 KPI 需工程师 ID，但知识层含客户数据、诊断 trace 本地 gitignored；引入身份采集引入灌水激励（为 KPI 沉淀低质内容），违背知识质量原则
- **沉淀环观测（产出数/采纳率，不按人）**：机制上有价值（to-postmortem/to-reference 产出无观测是当前盲区），但受部署模式影响（fork 式产出不进主仓）；若集中式部署成为主流，可复用 groom 三分类结果（new/variant/covered 分布）记入 metrics。**触发条件：首个集中式多用户部署出现**
- **协作指标（PR review 时长/驳回率/双签执行度）**：场景未发生（当前单人协作）；**触发条件：首个真实双人协作 PR 或 fork 出现时**再评估，与 rollout-assessment 重估条件对齐
- **agent 协作观测**：唯一已预留点是 triage_semantic trace（E2 数据源）；未来 agent 协作的可归因性（agent_id 维度）**在 trace schema 变更时顺带加可选字段即可，不单独设计**
