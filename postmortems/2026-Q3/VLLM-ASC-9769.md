# VLLM-ASC-9769 —— 310P 图模式 W8A8 QuantBatchmatmulV3 NZ/ND 格式错位（507015，EngineDead 500）

- **来源**：[vllm-ascend issue #9769](https://github.com/vllm-project/vllm-ascend/issues/9769)（closed，state_reason=COMPLETED）
- **fix**：PR #9104（310P 图模式 fused-ops 覆盖；0.19.1 cherry-pick / POC 镜像）——框架侧修复，非升 CANN
- **导入管道**：S2 replay 覆盖缺口（`.s2-replay/9769.md` + `.s2-replay/9769.result.yaml`，知识库无覆盖 + root_cause 与 resolution 一致）→ to-postmortem 草稿
- **状态**：draft（postmortems/inbox/ 待审，groom 周批三分类）
- **原文见**（结构化源，不重写）：
  - `.s2-replay/9769.md`（issue 完整现象/日志栈尾）
  - `.s2-replay/9769.result.yaml`（subagent 分层归因：root_cause_ok=true，evidence_gap_class=B）
  - 校准 resolution：`eval/s2/vllm-ascend.yaml` #9769 `expected.resolution` = "310P 图模式缺 fused ops 支持——cherry-pick PR #9104 或换 POC 镜像"

## 根因摘要

vllm-ascend 0.19.1 的 **310P 分支图模式（cudagraph）执行路径缺 fused ops 覆盖**：W8A8 量化 batch matmul 在图路径上 **QuantBatchmatmulV3 收 FRACTAL_NZ 布局、期望 ND**（NZ/ND 格式期望不匹配）→ 图执行在同步点报 `ACL stream synchronize failed, error code:507015`（栈落 `_310p/block_table.py:76 _to_numpy`）→ EngineCore 崩溃 EngineDeadError → 服务 500 关闭。**eager 模式（--enforce-eager）正常出文**——崩溃仅图模式触发，判别为图模式专属的框架侧覆盖缺口。

- **处理/规避**：治本 = 升级/换镜像到含 PR #9104 的版本；临时规避 = `--enforce-eager`（eager 正常，牺牲图模式性能）
- **fix_type**：code-patch；**category**：interrupt（运行期 EngineCore 崩溃/服务中断）；**tags**：310p / w8a8 / quantization / graph-mode / cudagraph / fused-ops / nz-format / 507015

## ⚠️ 与 VLLM-ASC-10122 的判别（同签名面、不同根因——必读）

| 维度 | #9769（本 case） | #10122（近邻 case） |
|---|---|---|
| 签名面 | 310P + QuantBatchmatmulV3 + 507015 | 310P + QuantBatchMatMulV3 + 507015（同） |
| 触发模式 | **仅图模式崩**，`--enforce-eager` 正常 | eager/图模式均崩（推理即触发） |
| 根因 | **310P 图模式 fused-ops 覆盖缺口**（NZ/ND 格式期望不匹配，框架侧缺陷） | **CANN 量化算子本体 bug** |
| fix | **cherry-pick PR #9104 / 换 POC 镜像**（框架侧代码修复） | **升级 CANN ≥9.1.0.beta2** + 镜像 |
| 判别动作 | eager 对照实验：eager 正常 → 本 case；eager 也崩 → 10122 | 同左 |

**结论：后人遇到 310P + QuantBatchmatmulV3 + 507015，先做 eager 对照再定 fix**——#9769 环境 CANN 9.0.0 并非根因，按 10122 升级 CANN 对本 issue 无效（会给错 fix）。另与 W4A8 group_size 限制（VLLM-ASC-10834，910B/EZ1001/非图模式）等 310P 量化族根因亦不同。

## 评估

- 沉淀判定：**可沉淀**（issue COMPLETED + fix PR #9104 merged + S2 replay root_cause 与 resolution 一致）→ new_pattern
- 覆盖缺口本体：S2 replay 暴露 knowledge 无 310P 图模式 fused-ops 覆盖 case（grep 无 PR #9104/fused-ops 记录）——本草稿即该缺口的闭环
- 草稿纪律：未加 confidence / validation_record（待 groom 分诊后按口径写入）
