# VLLM-ASC-11924: 未启用 FlashComm1/SP 时 AllGather EP 的 MXFP4(W4A4) MoE dispatch 无预量化 scale，路由 op 按 BF16 形状推断 FP4 packed 触发 MoeInitRoutingV3 tiling 错误

> 源是结构化 GitHub PR 线程（5 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/pull/11924
**fix 跟踪**：PR #11924（merged 2026-07-14，main；cherry-pick 到 releases/v0.23.0 两次失败，0.23.x 是否含修复需验证）
**时间**：2026-07-13 ~ 2026-07-14
**框架**：vllm-ascend v0.23.0（main 目标版本），MoE W4A4/MXFP4 + AllGather EP
**平台**：A5-950（Ascend950）
**category**：interrupt
**investigation_quality**：high（PR 给 root cause + 逐路径 fix 语义 + 3 组单测）
**批量导入**：批次 2 组 2（2026-08）

## 结构化 case

`postmortems/inbox/VLLM-ASC-11924.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

未启用 FlashComm1/SP 时 AllGather prepare 路径不预量化 hidden_states、不产 pertoken_scale，但 token dispatcher 仍按 dispatch 时量化处理 MXFP4，把 dtype 信息传给 `npu_moe_init_routing_v2` → 路由 op 从未量化 BF16/FP16 张量推断 FP4 packed 激活形状（形状差 2 倍），触发 MoeInitRoutingV3 tiling 错误（`expanded_x dim1 should be 7168, current is 14336`）。

## 弯路与级联

- **触发条件关键在"未启用 FlashComm1/SP"**：启用时 prepare 阶段产 pertoken_scale，走预量化路径正常——排查时先确认部署是否启用 FlashComm1/SP。
- **级联形态**：根因是 tiling 形状推断错误，报错落在 MoeInitRoutingV3（`npu_moe_init_routing_v2`）tiling 上，抓 `expanded_x dim1 should be ...` 这条签名即可，不必追路由逻辑本身。
- **fix 语义**：无 prepare-stage scale 时 dispatch 保持 MXFP4 未量化、量化推迟到 MLP 路径；pre-quantized 路径保留；同时兼容新旧 MXFP4 quant-type 枚举名。
- cherry-pick 到 releases/v0.23.0 两次失败（线程评论），回传状态需验证——升级前确认目标版本是否含该修复。
