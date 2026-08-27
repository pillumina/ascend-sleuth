# VLLM-ASC-11169: A2 双机 GLM-5.2 w8a8 推理乱码——外部 kv connector 传输路径相关，root cause 未确认（仅 workaround）

> 源是结构化 GitHub issue 线程（9 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/11169
**fix 跟踪**：无 PR；closed 为 stale（2026-08-07）；workaround 多人验证：`export VLLM_ASCEND_ENABLE_FLASHCOMM1=1` 或关闭 external kv connector
**时间**：2026-06-30 ~ 2026-08-07
**框架**：vllm-ascend nightly 20260616 + CANN 9.0.0，GLM-5.2 w8a8，DP=2 双节点 + UCMConnector
**平台**：A2-910B
**category**：other
**investigation_quality**：low（无根因定位、无 plog；仅 workaround 经验验证，issue 被 stale 关闭）
**批量导入**：批次 2 组 2（2026-08）

## 结构化 case

`postmortems/inbox/VLLM-ASC-11169.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

未确认（pending investigation）：A2 双机 GLM-5.2 乱码与外部 kv connector（UCMConnector/mooncake）KV 传输路径相关，具体缺陷未定位；已知 `export VLLM_ASCEND_ENABLE_FLASHCOMM1=1`（切换 flashcomm1 通信路径）或关闭 external kv connector 可恢复正确输出。

## 弯路与级联

- **这是 workaround-only case**：线程没有 plog、没有代码级定位，维护者要求关闭（评论#5），最终以 stale 自动关闭——不要把 workaround 当根因结论写进 fix。
- **两个等价 workaround**：`VLLM_ASCEND_ENABLE_FLASHCOMM1=1`（保留 external kv connector，评论#3 多人验证）vs 关闭 external kv connector（评论#2；prefix caching 不受影响）。
- **同类线索**：评论#3 标注"同 #11140"——同一批 external kv connector 问题的姊妹 issue，可互相参照。
