---
name: diagnose
description: >
  昇腾训练/推理问题的核心诊断循环：收集症状、按 triage-tree 路由、两阶段加载
  并验证 Tier 2 case、命中给 fix（高危 root cause 改提示 halt）或转深度排查。
  Tier-2 未命中但最终解决时起草候选 case。全程写 trace。
  仅在能执行命令的 agent（Claude Code / Codex / pi）中可用。
disable-model-invocation: true
---

# Diagnose

昇腾问题的核心诊断循环。你是辅助定位工具——**fix 是你给的建议，由人手动应用到客户环境，你不自动改生产**。

## 何时用

出现训练或推理问题（中断 / 精度 / 性能），且你在能执行 bash 的 agent 中。被打断后续接 → `/skill:resume-diagnosis`。

## 紧急情况（生产中断）

客户说“紧急 / 生产挂了 / 先恢复”时，诊断目标从“查根因”变成“**先 stabilize**”：

1. **还是先查知识库**——如果有匹配的 case（比如已知的安全回滚），直接给，这最快。知识库里的具体解药永远优于通用急救口诀。
2. **没有快速匹配时**，根据客户已提供的信息，一步步给 stabilize 建议：
   - 问客户最近 24-48h 改过什么（脚本/配置、框架版本、驱动/固件/CANN、数据、模型代码）——事故多半源于最近的改动
   - 基础健康检查：`npu-smi info`（卡活着吗）、`hccl top`（通信拓扑正常吗）
   - 看日志栈尾，定位哪层炸的
   - 能否先恢复：回滚上个 checkpoint 重启 / 降配（关 EP、降 batch）/ 重启 daemon
3. **不钻深度排查、不写 postmortem**——事后用 `/skill:to-postmortem` 补。

## 流程（核心循环详见 references/diagnosis-procedure.md）

> **执行模型**：你不访问任何环境。所有信息——日志、版本、报错、环境变量——都由工程师从客户那提供（粘贴进来）。你的主动角色是**信息不够时，明确提示工程师需要向客户要什么**。case 里的 `command` 是“要确认的检查”：对照已提供的信息判断，或让客户跑后把输出贴回来——不是你直接执行 `pip`/`env`/`grep`。
>
> **续接**：若存在未完成的 `diagnosis_state.yaml`，先问“上次有个诊断没做完，要 `/skill:resume-diagnosis` 续接吗？”——别让工程师自己记着跑 resume。

1. **收集症状 + 确认框架**（全部来自工程师提供的信息）
   - 错误信息、`HCCL_*`/`ASCEND_*`/`NPU_*` 环境变量值、框架版本、硬件平台（A2/A3/A5）——都从客户那要来
   - **框架从提供的信息/报错判断**（日志里 mindspeed/vllm 字样等）；判断不了就直接问工程师“客户跑的什么框架”，**不要跑 `pip list`**（那是你本地环境，跟客户无关）
   - **主动裁剪日志**：让工程师只贴失败 rank + 报错栈尾，绝不灌全量 profiler——诊断 session 的 context 八成是日志，全量灌进来会滑出 smart zone（~120K token 推理最锐利），推理质量暴跌

2. **分类 → 加载 `triage-tree.yaml`（Tier 1）**
   - 症状匹配分支 → 路由到 namespace（先 `training|inference/<framework>/`，再 `common/`）
   - **triage 决策记进 trace**（命中哪个分支、路由到哪些 namespace、category）
   - triage 多分支弱匹配/置信度低 → **优雅退化**：加载所有 namespace 索引让 quickly_check 筛（索引便宜，退化成本可控）
   - 框架未检测到 → 只搜 `common/`；无法分类 → 直接 Tier 3

3. **两阶段加载 Tier 2**
   - **阶段一**：加载命中 namespace 的索引（`id/title/symptoms/quickly_check/category/confidence`），用 `quickly_check`（primary→fallback）**对照已提供的信息**过滤候选 ≤5；检查项缺信息时，记下要向客户补要什么
   - **空库提示（冷启动）**：若命中 namespace 为空（还没 case），**不要静默退化**——告诉用户“当前 `knowledge/<ns>/` 还没有验证过的 case，你可以：①继续深度排查（步骤 5）②诊断完跑 `/skill:to-postmortem` 沉淀成第一条 case ③转人工”。别让空库的体感是“这玩意啥也不会”。
   - primary 不匹配但 fallback 匹配 → 仍进验证，标记 `low_confidence`
   - **category 决定 quickly_check 形态**：interrupt 用 grep 错误签名、precision 用数值阈值（`loss>1e3`、`has_nan`）、performance 用 profiler 指标（`comm_ratio>0.4`）——别混用
   - **阶段二**：全量加载候选，按 `confidence.score` **降序**进入验证

4. **验证 diagnosis checks**
   - 顺序验证候选 case 的 `diagnosis` 检查项（**对照已提供的信息**，不跳步）；某步缺信息 → 提示工程师向客户要（或让客户跑该 command 贴回输出）；mismatch 且有 `fix_on_mismatch` → 提示 fix（**先看 severity**，见下）
   - 命中 → 输出 root cause + fix，进入步骤 6
   - 所有候选未命中 → 深度排查（步骤 5）

5. **深度排查（Tier 2 未命中）**
   - 按 category 选默认 Script（见 references/script-integration.md）：interrupt→日志/core dump、precision→`mem-analyze`、performance→`ascend-profile-analyze`/`bench-run`
   - Tier 3 关键词检索 `postmortems/`（`rg -l '<keyword>' postmortems/`，top-3）
   - 人 + agent 联合分析

6. **产出**
   - `resolution: resolved | escalated | unknown`
   - **Tier-2 命中**：常规 postmortem 草稿
   - **Tier-2 未命中但最终解决**：postmortem 含一段你起草的**候选 case**（quickly_check + diagnosis + confidence 低），交 `/skill:knowledge-groom` 验证
   - 完整 trace 随 `diagnosis_state.yaml` 留存（模板见 `diagnosis_state.yaml.example`）
   - **解决后主动建议沉淀**：尤其 Tier-2 未命中的新问题——主动问“要把这次沉淀成 case 吗？”并建议 `/skill:to-postmortem`。这是知识库增长的主要来源，别让工程师忘了沉淀。

## severity 闸门（命中后先看这个）

读候选 case 的 `severity` 字段，决定输出策略：

- `benign` → 直接给 fix
- `service-affecting` → 给 fix，但标注 `fix_side_effects`（如 requires-restart），让人协调窗口
- `data-loss-risk`（如"checkpoint 可能被污染"）→ **不直接给 fix**，输出"先停训练、保留现场、通知 owner"。高危 root cause 的正确动作是 halt 不是 patch

每个 `fix_on_mismatch` 都带 `rollback`——人应用失败时能回退。

## 每步必写 trace（硬要求）

每个 step 后往 `diagnosis_state.yaml` 的 `trace` 数组追加一条：
```yaml
- {step: N, action: triage|load_index|quickly_check|load_full|run_check|hit|miss, ...}
```
trace 是误诊归因的唯一依据（见 references/diagnosis-procedure.md 末段"误诊归因"）：误诊时先读 trace 判断是 **case 错**（改库）还是**执行错**（改 skill）。不写 trace = 无法归因 = 可能改坏正确的 case。

## 不要做

- 不要替人决定 root cause——给结构化清单，人执行后贴回结果
- 不要连续尝试第三个 case——两次未解决即转人工（误诊保护的串联保护，见 references/diagnosis-procedure.md）
- 不要把全量 profiler 灌进 context——裁剪到相关 rank + 栈尾
- 不要用 interrupt 的 grep 思路建 precision 的 quickly_check（category 形态不同）
- 被打断 → `/skill:resume-diagnosis`
