# VLLM-ASC-12241: v0.23.0 图模式（cudagraph）+ MTP 下 profiling 采不到 kernel 信息（无 kernel_details.csv）——CANN 9.0.0 与图模式交互 bug，升级 9.1.0 恢复

> 源是 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/12241
**fix 跟踪**：无代码修复 PR——官方建议升级 CANN 9.1.0 复测；用户确认"现在可以采集了"（评论#6）；workaround 为 `--enforce-eager` 关闭图模式
**时间**：2026-07-17 ~ 2026-08-25（stale 关闭）
**框架**：vllm-ascend v0.23.0（releases/v0.23.0 分支）+ CANN 9.0.0（失败）→ CANN 9.1.0（恢复）；GLM-5.2，TP16/CP16，MTP/投机推理 + cudagraph 图模式
**平台**：Ascend NPU（线程未标注具体型号）
**category**：performance（profiling 观测能力缺失，非服务故障）
**investigation_quality**：low（无复现日志/采集目录；结论依赖官方建议 + 用户一句确认；weiguihua2 曾提出误导性假说）
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（batch 2）

## 结构化 case

`postmortems/inbox/VLLM-ASC-12241.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

CANN 9.0.0 下开启 NPU 图模式（cudagraph/npugraph，本 case 与 MTP 投机推理组合）后，torch profiler 采集不到 kernel 信息（解析无 kernel_details.csv）；根因在 CANN profiling 与图模式执行的交互，非框架特性——升级 CANN 9.1.0 后恢复，workaround 为 `--enforce-eager` 关闭图模式。

## 弯路与级联

- **弯路（误导性假说）**：weiguihua2 提出"可能是采集窗口内没有算子下发"——用户反驳：同配置关闭 cudagraph 即可采集，开 cudagraph 必现，确认是 bug 而非负载窗口问题（评论#4）。排查时勿被"无 NPU 负载"方向带走。
- **级联**：PD 分离场景 P 节点单独采集正常、混部（图模式+MTP）采集不到——同一套 profiling 流程，差异只在图模式/投机开关，直接对照该开关消融即可收敛。
- performance 类 + 版本差异：quickly_check 用 CANN 版本断言形态（primary）+ 行为词 grep（fallback），不依赖错误签名。
