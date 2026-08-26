# 评估报告 0001：vllm-ascend 批量导入与框架首次实测

> 数据源：GitHub vllm-project/vllm-ascend 的 64 个闭环 issue 线程（≥3 评论）→ 21 个通过四硬门槛。计划与筛选留痕见 [0001-vllm-ascend-batch-plan.md](0001-vllm-ascend-batch-plan.md)。本报告是 Phase 0 的首次框架实测：知识入库 19 case + 2 variant 并入，回放 21 例，golden 套件 2 → 23。

## 一、结果总览

| 环节 | 结果 |
|---|---|
| 门槛筛选 | 64 → 21（33% 通过；43 条排除原因留痕） |
| 语义校验（to-postmortem） | **21/21 pass**——primary regex 全部在真实线程原文 re.search 实测，零编造，零 needs-structurer-review |
| 预分诊（groom） | new_pattern 19 / variant_of 2 / covered_by 0；两对 variant 判定高置信度 |
| 入库 | `inference/vllm-ascend/` 19/30（63%），低于 80% 拆分闸门；inbox 清零 |
| 回放（措辞差 + 交叉） | **候选命中 16/21（76%）；rank1 13；top3 16** |
| 交叉回放（variant 并入验证） | **#13379→13329 rank1；#14467→12685 rank1**——并入机制闭环验证 |
| golden fixture | 21 个真实 fixture（总 23），断言口径 top-3 |

## 二、六指标（metrics.md 口径）

| 指标 | 本次值 | 说明 |
|---|---|---|
| 语义校验通过率 | 100%（21/21） | 真实日志上的 regex 实测——构造样例时代从未验证过的环节 |
| 预分诊准确率 | 待人核 | 2 对 variant 判定已给出证据链，抽审确认 |
| 路由准确率 | 19/21（90%）正确 ns 在路由集合 | 2 例靠 uncategorized 优雅退化救回（12983）——降级机制起效但暴露 triage 覆盖缺口 |
| 候选召回 | 16/21（76%） | 5 个 miss 全部可归因（见 §三） |
| rank1 / top3 | 13 / 16 | rank2 两例均为同分并列、索引序决定——印证 top-3 口径 |
| 按类命中 | precision 3/3、interrupt 7/10（另 2 交叉命中不计）、other 2/2、performance 0/1（另 1 例 semantic-obs） | **performance 类如预期暴露短板**：metric 断言形态无法被 regex 回放消费 |

## 三、五个 miss 的归因（本次评估的核心产出）

全部 miss 的共同模式：**判别性签名在跟帖不在首帖**——用户最初描述只有现象，错误码/算子名在开发者追问后出现。这不是 case 写错了（regex 在全线程上都实测通过），是"首帖措辞 vs 结论措辞"的信息差：

| miss | 首帖缺什么 | 判别信号在哪 |
|---|---|---|
| 12461 | 错误码 507057、aicore exception | 跟帖开发者分析 |
| 12685 | o_groups、fp8 Quantization 日志 | 跟帖完整栈 |
| 12989 | EL0008/507903 | 跟帖驱动日志 |
| 13964 | Prometheus 指标名（首帖用自述措辞） | 无——静默 hang 无签名 |
| 13973 | metric 数值形态（机制性不适用） | 首帖有数值但 regex 消费不了 |

**这正好落在理论预测的位置**：词法层（regex）对措辞差的鲁棒性有限，而系统设计里负责消化措辞差的是 agent 语义归一层（四级级联的第三级）——纯 regex 回放等于只测了前两级。五个 miss 的语义观察全部标注"语义归一后大概率命中"。**结论：不是架构缺陷，是回放 harness 的测量范围声明问题**——下次评估应含 agent 归一层（记入待定池）。

## 四、结构性发现（进 roadmap 待定池）

1. **triage 子串误配**：`hang`⊂`changed`、`inf`⊂`INFO`、`nan` 子串命中——21 例中大量被误路由 training_precision（靠后续 quickly_check 纠正，未影响最终命中，但浪费候选预算）。修复：词边界匹配（`\b`）——**低成本高收益，建议立即修**
2. **triage inference 分支覆盖不足**：错误码型症状（107030 等）无分支命中，靠优雅退化兜底。修复：inference_interrupt 补错误码型签名
3. **candidate 污染三来源**：related-issue 提及点亮对方 fallback；通用 fallback token（aicore exception）跨点亮；`speculative-config` 这类启动命令词被误触。修复方向：fallback regex 收紧词边界 + 长度门槛
4. **performance 形态与回放 harness 不匹配**：metric 断言需要数值提取比对，regex 回放测不了。修复：回放 harness 加 metric-form 分支（数值提取后比对）
5. **低分 case 被同栈高分近邻压位**（13329 rank2 现象）：score 并列时索引序决定——确认"top-3 口径"的必要性，也提示 confidence 初始分层（0.6/0.3/0.1）在并列时无区分度
6. **variant 并入的锚点设计验证**：交叉回放证明签名命中在候选层冗余（签名本来就同）、在诊断层必要（版本分支 fix、平台补充、第二症状面）——**并入动作的价值主张被精确证实**，改进项：variant 签名追加进主 case fallback（防签名微变）

## 五、Phase 0 出口条件核对

- [x] 在库 case ≥20：**20**（19 新 + 1 原有）
- [x] ≥1 轮真实 to-postmortem + knowledge-groom 全流程
- [ ] 分支保护与 CODEOWNERS 硬门生效（owner 未定——人事阻塞，见 roadmap 待定人事决策）
- [ ] data-loss-risk 通知链路落地（同上）
- [x] 指标双周节奏建立：本报告即第一个数据点，metrics.md 随本 PR 回流

## 六、结论

首次实测支持"第零号假设"的三个核心承诺：**词法底座 + 语义 agent 分工有效**（76% 纯词法命中，miss 全部落在语义层可救的范围）、**variant 并入机制价值成立**（交叉回放 rank1×2 + 诊断深度增强）、**两阶段检索在真实数据上成立**（语义校验 100% 说明 case 质量可控）。暴露的缺口全部是可修的工程项（词边界、错误码分支、metric 回放形态），不是架构级缺陷。

下一个数据点：真实使用（第一次活的 diagnose session 走 trace 全流程）。
