# VLLM-ASC-10700: GLM5.1 + MTP 未设 enforce_eager 时推理十余次请求后崩溃——507011 + MTE DDR 越界（加 enforce_eager 后稳定，指向图模式路径）

> 源是结构化 GitHub issue（现场给出完整 device 侧报错 + enforce_eager 的 A/B 对照），按 to-postmortem 的
> 「只写指针 + 不重写」口径记录；issue 仍 OPEN、无维护者根因结论。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/10700
**框架/平台**：vllm-ascend v0.21.0rc1 / A2-910B 双节点 16 卡，GLM5.1 + MTP（`num_speculative_tokens=3, method=mtp`）
**category**：interrupt
**investigation_quality**：medium（现场 A/B 指明方向；无代码级定位、无 fix PR）
**verification**：investigation（issue OPEN）
**novelty**：variant_of VLLM-ASC-9887 —— 同族「GLM5.1 + MoE/MTP 路径运行期崩溃 + MTE DDR 越界」，
触发面不同：9887 是 **MC2 容量不足**（`num_batch_tokens` > 容量，FusedMC2=1）；本条是**图模式捕获/回放**（未 enforce_eager）下运行多次后越界 → fix 面不同（容量/参数 vs 图模式开关）。

## 现象摘要

- 启用 MTP 投机解码、**未设 `enforce_eager`**：推理十余次请求后 vLLM 进程崩溃（非启动即失败）；
- 框架侧：`NPU function error: call failed, error code is 507011` → `aclrtLaunchKernelWithHostArgs failed: 507011` → `Kernel launch from cache failed`（走算子缓存/图路径）；
- device 侧：fftsplus aivector error，`errorStr: The DDR address of the MTE instruction is out of range`，`fixp_error0 info: 0x600005f`，`subErrType:4`；
- **同配置把 `enforce_eager` 置 true（放在 `--speculative-config` 内）后稳定运行**——只是变慢，崩溃消失。

## 一句话方向（未闭环）

MTP 在图模式（ACLGraph 捕获/回放）下运行若干次请求后触发 device 侧 MTE 访存越界，kernel 从缓存启动失败（507011）；改走 eager 执行即不复现 → 触发面在图捕获/回放路径，而非算子本身。

## fix（止损 + 定位）

- **止损**：`--speculative-config '{"num_speculative_tokens":3,"method":"mtp","enforce_eager":true}'`（现场已验证稳定，代价是推理变慢）；
- **定位**：在正式版上复测确认版本差异；仍复现则收集崩溃前最后一次图回放的输入规模 + plog，交维护者（上游 OPEN）。

## 未闭环与残余风险（如实标注）

- 根因未到代码级：图回放路径上的哪一处索引/地址越界，本 case 不含结论；
- `enforce_eager` 是**回避**不是修复——上线用它等于放弃图模式性能，需与业务确认；
- 若报的是 MoE 分发算子错误码（507034 / 561000）→ 转 MC2 容量/分发族（VLLM-ASC-9887 / 10944）。
