# 评估批次计划：vllm-ascend 真实闭环 issue 导入（0001）

> 本文档是 Phase A 的产出：筛选标准的首次应用记录。数据源：GitHub `vllm-project/vllm-ascend`（用户指定）。

## 1. 目的

一石三鸟（依据 `docs/eval.md`："真实 fixture 是已解决 postmortem 的投影"）：

1. Phase 0 播种：~20 条真实 case 入 `knowledge/inference/vllm-ascend/`
2. Golden 套件 2 → 20+，解锁 roadmap M2 闸门（真实 fixture ≥5）
3. 框架首次效果评估：六指标实测，`docs/metrics.md` 第一批真实数据

## 2. 数据面

- 拉取范围：vllm-ascend 全部 closed issue（REST API 分页，排除 PR）
- 总量：**189 个纯 issue**；其中 ≥3 评论（具备排查线程的可能性）：**64 个**
- 拉取深度：64 个候选的完整主帖 + 全部评论线程（本地缓存 `/tmp/vllm-ascend-issues/threads/`）

## 3. 筛选标准（理论依据：知识价值 = P(再现) × 排查节约 − 维护成本）

### 硬门槛（任一不满足即排除）

| # | 门槛 | 理论依据 | 核验方式 |
|---|---|---|---|
| G1 | 已闭环：root cause 明确 + fix merged / 验证过的 workaround / 官方确认修复版本 | §4.1 investigation_quality 分层的前提 | 评论线程结论性评论 |
| G2 | 昇腾特有：根因在 NPU 适配层 / CANN / HCCL / 驱动 / torch_npu，非 vllm 主仓通用 bug | 通用 bug 复用价值坍塌（fix 不适用本域） | 根因归属判定 |
| G3 | 可检索信号：可 grep 错误签名 / 可断言数值 / 可比对指标 | §2 似然项——quickly_check 建不起来的 case 是死资产 | 主帖/评论中的信号定位 |
| G4 | 证据可获得：日志片段在帖内 + 版本组合可获得 | §2 推论三——验证需要弹药 | body 内容核验 |

### 加分项（门槛全过后排序）

排查弯路（+3，直路节约的最直接证据）> duplicate/关联 issue（+2，再现概率的实证）> 平台差异涉及（+2）> severity（crash/OOM/精度污染 +2）> 日志详尽（+1）

### 明确排除形态

无回复关闭 / 用户环境配错（根因无复用性）/ 仅指向别处的重复关闭 / how-to 咨询 / 功能请求

## 4. 评估过程（Phase A 执行记录）

- 评估方式：agent 逐线程阅读（主帖 + 结论性评论），按门槛四项核验 + 加分评分
- 评估产出：`assessment.jsonl`（64 条全量记录，含失败原因——被排除的也留痕，保证筛选可审计）
- 本文档 §5 填入选定清单

## 5. 选定清单（Phase A 评估结果）

**评估结果：64 个候选线程全量评估，21 个通过全部硬门槛（33%）**。排除记录见 `/tmp/vllm-ascend-issues/assessment.jsonl`（含失败原因，可审计）。

**按 category**：interrupt 12 / precision 3 / performance 2 / other 4——真实分布（interrupt 为主）+ 三类均非零，符合决策。
**按 investigation_quality**：high 13 / medium 4 / low 4——高分项根因普遍到代码级（pcp_utils、mooncake_connector、sfa_v1、triton rope 等具体文件）。

| # | issue | score | category | quality | 根因摘要 |
|---|---|---|---|---|---|
| 1 | #12723 | 10 | precision | high | vllm_ascend Triton rope 的 sin 缓存偏移用了 past KV 长度而非绝对位置，rotary 路径损坏 Q/K 范数（PR #12963） |
| 2 | #12957 | 10 | precision | high | PD 分离 P 侧 sfa_v1.py 的 k_pe 经 kv_ag_handler 传输时缺流同步，RDMA 首请求乱码（PR #14269） |
| 3 | #13934 | 10 | interrupt | high | v0.26 新增 AscendSFAIndexerCacheSpec 使 1P3D 配置下 spec 拆分错乱，Mooncake block_ids 越界+乱码（PR #13968/#13965） |
| 4 | #12461 | 9 | interrupt | high | 多节点 EP + MoECommType.MC2 在 ROCE 上触发 HCOM 报错（RuntimeError: SUSPECT REMOTE ERROR） |
| 5 | #12642 | 9 | precision | high | triton-ascend 3.1.0 ceil_div+tan 实现 bf16 sin/cos 溢出致 logits 异常（官方确认 3.2.2 修复） |
| 6 | #13050 | 9 | interrupt | high | 310P 上 NPU graph capture 与 EPLB 冲突致推理服务崩溃（0.23.0 正式版修复） |
| 7 | #13710 | 9 | interrupt | high | （见 assessment：多轮排查弯路 + 平台提及） |
| 8 | #13964 | 9 | interrupt | high | （见 assessment） |
| 9 | #14320 | 9 | interrupt | high | （见 assessment） |
| 10 | #13973 | 8 | performance | high | （见 assessment） |
| 11 | #12685 | 7 | interrupt | medium | 非 quant 模型走 DS v4 专有属性路径致拉起失败 |
| 12 | #12989 | 7 | interrupt | medium | （见 assessment） |
| 13 | #13508 | 7 | interrupt | medium | （见 assessment） |
| 14 | #14467 | 7 | interrupt | low | （见 assessment） |
| 15 | #12901 | 6 | interrupt | low | （见 assessment） |
| 16 | #14166 | 6 | interrupt | low | torch-npu post4 修复（官方确认） |
| 17 | #13329 | 5 | other | medium | DSV4-Flash-0731 无 MTP head 须用 dspark |
| 18 | #13356 | 5 | performance | medium | （见 assessment） |
| 19 | #13379 | 5 | other | medium | 与 #13329 同根因 |
| 20 | #13329 | — | — | — | **variant 对标记：#13379 入库时预期被预分诊判为 variant_of:#13329** |
| 21 | #13086 | 4 | other | low | A5(950) 需新版本 vllm-ascend |
| 22 | #12983 | 4 | other | low | 310P 镜像缺 free-mask 算子 |

**关键发现**：
1. **第一对真实 variant**：#13329/#13379 同根因（DSpark MTP）——groom 预分诊三分类的天然考题。计划：#13329 入库，#13379 做 Phase D 交叉回放输入
2. performance 类仅 2 条且预期测试表现差（定性描述为主）——schema 短板预期将获实证
3. other 类 4 条是有可检索签名的"版本/模型兼容矩阵"知识（错误签名→支持差异），有沉淀价值但 category 体系外——按原样入库标 other，观察是否触发 schema 演进讨论

**盲测 holdout 决策依据**：真实 variant 对仅 1 对（不足 ≥4 的预设闸门）→ **不做模式 3 盲测**，全部 21 条入库，交叉回放用 #13379。

### 筛选判例（从严执行的记录）

- stale/无回复关闭：32 个 fail（闭环从严）
- 用户自解配置问题不计数；但**官方确认的版本/模型兼容矩阵**按 other 通过（错误签名可沉淀）
- upstream 根因（vllm 主仓/transformers/模型自身）：fail——本域 fix 不适用
- 纯文档/咨询无日志证据：fail（G4）

## 6. 后续阶段（本计划批准的执行范围）

| 阶段 | 内容 | 用户参与点 |
|---|---|---|
| B | 批量 to-postmortem：全线程提取 + 语义校验（regex 在原始日志上实测）+ 脱敏 | — |
| C | groom 预分诊三分类 + 30-cap 容量决策 + PR 门控入库 | 抽审 5 条 + PR review |
| D | 回放测试：措辞差（全部）+ 交叉（duplicate 对）+ 盲测 holdout（若 ≥4 对）；3 次取多数 | — |
| E | 评估报告 + metrics.md 回流 + fixture 入库 + 短板发现进待定池 | 报告确认 |

## 7. 诚实边界

- 实际合格量不足 20 时如实降量（原则九），不硬凑
- performance 类预期暴露 schema 短板（定性描述无 profiler 数据），如实记录不粉饰
- 语义校验若大量失败，本身即重要发现（构造样例 vs 真实日志差距），计入报告
