# VLLM-ASC-8646: 0.18.0rc1 A2 双机 GLM-5.1-W4A8 拉起报 rtMemcpy capture 模式不支持（107030/107027）——EP MoE 量化分发（QuantBatchMatmulV3）与图模式冲突，moe_comm_type 切 ALLGATHER 规避

> 源是结构化 GitHub issue 线程（5 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/8646
**fix 跟踪**：无独立 fix PR；解决=维护者 weijinqian0 给 workaround `moe_comm_type=MoECommType.ALLGATHER`（MoE 专家通信切 ALLGATHER）并关闭（completed 2026-06-15）；thread 另有 A3 双机 ROCE tp16dp2 经 3ms 配置调整可拉起、tp8dp4 仍相似报错（同族佐证）
**时间**：2026-04-24 ~ 2026-06-15（completed）
**框架**：vllm-ascend v0.18.0rc1（--quantization ascend）+ GLM-5.1-W4A8 + deepseek_mtp
**平台**：Ascend 910B（A2-910B，双机背靠背，node0/node1 直连组网）
**category**：interrupt（启动/拉起期崩溃）
**investigation_quality**：medium（完整报错链 107030/107027 + plog 定位 QuantBatchMatmulV3 NULL aclTensor + 维护者 workaround；无代码级根因说明）
**verification**：upstream-maintainer-confirmed（维护者 weijinqian0 提供 workaround 并关闭 completed）
**pre-triage**：new_pattern（现库无 EP MoE 量化分发×图模式 107030 case；与 8587 同 rtMemcpy-107030-in-capture 家族但触发面/规避不同——8587=layer_sharding 混用规避升级+去 layer_sharding，本条=量化分发规避 ALLGATHER；邻近 12983 为 310P 图模式 107030 另一根因）

## 现象摘要

- A2 双机背靠背组网（node0/node1），GLM-5.1-W4A8（--quantization ascend），DP2×TP8（各 8 卡）+ EP + FULL_DECODE_ONLY（cudagraph_capture_sizes 1..96）+ deepseek_mtp + `--additional-config '{"multistream_overlap_shared_expert":true, "fuse_qknorm_rope": false, ...}'` + VLLM_ASCEND_BALANCE_SCHEDULING=1。
- 拉起报错链：`RuntimeError: ... AclrtSynchronizeStreamWithTimeout(copy_stream), error code is 107027` → `EE9999: rtMemcpy execution failed, reason=the current capture mode does not support this operation` → `synchronized memcpy failed, kind = 1, runtime result = 107030` → `Not allow to synchronize captured-stream, stream_id=15`（同步 captured stream 不允许）。
- plog 首错：`OpName:[aclnnQuantMatmulWeightNz_..._QuantBatchMatmulV3] Append Launch NULL aclTensor（placeholder）`——MoE 量化 matmul 分发算子在 graph capture 内 launch 参数含 NULL aclTensor。
- A3 双机 ROCE 同配置：tp16dp2 经 3ms 内部文档调整可拉起，tp8dp4 仍相似报错（同族佐证）。
- 解决：moe_comm_type=MoECommType.ALLGATHER（MoE 专家通信切 ALLGATHER）规避。

## 一句话根因

EP 场景默认 MoE expert 通信走量化分发路径（aclnnQuantMatmulWeightNz/QuantBatchMatmulV3 量化 matmul 分发），该路径在 ACL graph capture 内 launch 参数含 NULL aclTensor placeholder 并伴随同步 memcpy/stream 同步操作，ACL graph capture 模式不支持 → rtMemcpy 107030 / captured-stream 同步 107027，服务拉起崩溃。把 MoE 专家通信切到 ALLGATHER（moe_comm_type=MoECommType.ALLGATHER）绕过该量化分发组合即可规避（维护者 weijinqian0）。

## fix

- workaround：把 MoE 专家通信方式设为 ALLGATHER（thread 中为 moe_comm_type=MoECommType.ALLGATHER；vllm-ascend 侧对应开关在不同版本形态不同——env/config 名以所装版本为准），重启服务。
- 官方代码修复未见（issue 关闭于 workaround）；升级方向可跟踪后续版本对 MoE 通信选择策略的治理。

## 弯路与级联

- 弯路：thread 无；A3 ROCE tp16dp2 经 3ms 文档调整可拉起但 tp8dp4 仍报（说明该配置面不是单节点形态问题）。
- 级联：107027（同步 captured stream 不允许）与 107030 是同一次 graph-capture 内违规操作的两层 runtime 报错，判型以 plog 首错 QuantBatchMatmulV3 NULL aclTensor 为准。
