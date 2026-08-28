# groom 提炼 reference 测试报告

> 测试日期：2026-08-28。方法：对 `knowledge/` 现有 38 条 case 运行 to-reference 的 case 归纳路径（`--ingest-cases`），提炼共性为 reference，评估提炼质量与 skill 能力。
> 工具链：`skills/to-reference/SKILL.md`（case-derived 流程）+ `scripts/verify_references.py`（schema 校验）。
> **修订 1 后版本**：应用 ADR-0008 组织形态校准（组织单元 = 验证单元）——错误码按族成表，草稿无 _inbox 直进正式目录（draft）。

## 一、提炼结果（3 个文件，全部 `status: draft` 直进正式目录）

| 文件 | type | case 证据 | 共性 |
|---|---|---|---|
| `references/errors/cann-runtime.yaml` | error-code（**表**） | 8 条 case | 7 个运行时错误码（507903/207005/507018/507057/561000/107030/161002） |
| `references/methodologies/glm-quantized-startup-triage.yaml` | methodology | 7 条 | GLM 系量化模型启动失败，按报错形态分类定位 |
| `references/platform-facts/ascend-310p-known-limits.yaml` | platform-fact | 3 条 | 310P 平台特有限制 |

**组织形态对比（修订 1 验证）**：旧形态 2 个 error-code 文件各 1 条 + 重复元信息；新形态 **1 个表文件承载 7 条错误码**，表级共享 sources/status/applies_to，条目级带 `source_cases` 证据——信息密度、族上下文、检索（按族定位 + 表内 grep）三者同时改善。

## 二、提炼质量评估（四维）

### 1. 忠实度（不引入幻觉）——通过

每条草稿的 claim 均可回溯到具体 case 的 `root_cause`（证据链在 sources.cases + content.evidence）。**无一条声称 case 未提供的根因**。例：`ascend-cudagraph-event-resource` 的"NPU event/SQ-CQ 硬预算"直接来自 9596 的 RC（"官方 ACL_Graph 文档 stream-budget 章节"）与 12989 的 RC（"310P 硬件/驱动的 event 资源有限"）。

### 2. 价值（提炼的是高频问题域）——通过

38 条 case 中，GLM 量化启动占 7 条（18%）、图模式资源问题 2 条、310P 特有 3 条——提炼出的正是重复出现的模式，非偶然个案。

### 3. 差异处理（不把偶然共性当规律）——通过，且发现两个关键差异

- **MoeInitRoutingV3 两型拆开**：14166（缺二进制，torch-npu 版本）vs 11924（tiling 形状推断，MXFP4 量化路径）——**同算子名 ≠ 同根因**，`moe-init-routing-missing-binary` 的 meaning 里显式写了区分说明，未合并；
- **GLM 簇是"诊断入口"而非"单一根因"**：7 条 case 根因各异（modelslim 描述缺失 ×2、版本错配、pybind 绑定、量化路由、backend patch）——提炼为**分类决策树**（methodology flow 按报错形态分 5 步），而不是谎称"同一根因"。这是 case 归纳最容易犯的幻觉（把共性入口说成共同根因），本次正确处理。

### 4. 阈值纪律——通过

- case-derived 草稿全部 `draft` 起步（不产出 active）；
- 1 条 case 的 `moe-init-routing-missing-binary` 诚实标低证据量（1 条），未因"有价值"而虚高；
- 深审门槛（methodology 需 ≥3 条）由 CI 强制——`glm-quantized-startup-triage` 有 7 条满足，但草稿仍 draft（active 需 maintainer 审核）。

## 三、skill 能力测试结论

### 能做什么（验证成立）

| 能力 | 证据 |
|---|---|
| 识别真实共性簇 | 从 38 条标题/RC 交叉验证出 4 个簇，非随机 |
| 忠实提炼（无幻觉） | claim 全部可回溯 case RC |
| 差异确认 | MoeInitRoutingV3 两型、GLM 簇多根因——都正确处理 |
| schema 合规 | 4 条一次通过强校验（1 处 YAML 语法错被校验抓住并修复） |
| 零注释纪律 | 产出零注释行（#21 规则生效） |

### 局限（诚实声明）

| 局限 | 说明 |
|---|---|
| **单框架单平台样本** | 38 条全 vllm-ascend inference——提炼的 methodology 是框架特定（`applies_to.frameworks: vllm-ascend`），**不是跨框架 common/**（groom 信号表的"两框架 namespace 同 root cause → common/"条件未触发） |
| **提炼依赖 case 质量** | 若 case 的 root_cause 本身有误/缺失，提炼会继承该错误——提炼前应先跑误诊归因（原则八） |
| **无独立验证** | 提炼的 methodology（如 GLM 分类树）未经真实诊断使用检验——`verified_by_testing: false`，诚实标注 |
| **LLM 归纳本质** | 归纳是概率性的，样本越多越稳；38 条是下限，覆盖矩阵扩大后应重提炼 |

## 四、对推广的意义

- **证明 to-reference case 归纳路径可用**——这是"从案例知识提炼先验知识"的第一次真实运行（你最初的假设成立）；
- **为 rollout-assessment 的 P1"error-code 填充"提供了方法**：本次 2 条 error-code 草稿证明该路径可产出真实错误码知识；
- **但 38 条样本只够证明方法**，不够支撑"通用方法论库"——跨框架共性（common/ 权威记录）仍需第二个框架的数据（与 rollout-assessment 的差距 1 一致）。

## 五、审阅建议

4 条草稿待 maintainer 审核（accept → 移入正式目录 + methodology 需实测后标 verified；adjust / reject / defer 均可）。建议优先审 `glm-quantized-startup-triage`（7 条证据、价值最高）——先由熟悉 GLM 量化的 owner 验证分类树是否覆盖真实场景。
