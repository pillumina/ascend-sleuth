# VLLM-ASC-12430: 4×A2 多节点 DSV4-Pro-w4a8（EP=32）profile_run 阶段 MoeDistributeDispatchV2 AICore 超时 507014——HDK 低于 CANN 9.0.1 配套

> 源是结构化 GitHub issue 线程（4 条评论，issue 仍 OPEN），按 to-postmortem 优化——只写指针，不重写。
> 本次沉淀起点是**一次本地诊断会话**（`traces/2026-09-16-12430-dsv4pro-mc2.yaml`），人给的输入是 issue URL。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/12430
**fix 跟踪**：无代码 PR；环境级修复 = 升级 firmware + npu driver 到 CANN 9.0.1 配套版本（25.5.1 / 25.5.2 / 26.0.RC1），CANN 9.0.1 不动。issue 仍 OPEN，维护者尚无根因结论。
**时间**：2026-07-20（报）～ 至今 OPEN；本地诊断 2026-09-16
**框架**：vllm-ascend v0.23.0rc1（亦有 v0.22.1rc1 复现）；vLLM 0.23.0；torch-npu 2.10.0.post2
**CANN / HDK**：CANN 9.0.1（亦测 9.0.0 / 8.5.1）；**npu driver 24.1.0.3、firmware 7.5.0.5.220**（判据所在）
**平台**：A2-910B（Atlas A2 aarch64，8×64GB × 4 节点 = 32 卡）
**category**：interrupt
**investigation_quality**：medium（现场排除矩阵完整且质量高；但根因为三方证据收敛的推断，非代码级定位，案未闭环）
**pre-triage**：`variant_of:VLLM-ASC-9005`（详见下方）

## 结构化 case

`postmortems/inbox/VLLM-ASC-12430.case.yaml`（Tier 2 候选，待 groom 审）

## 现象摘要

4×A2 以 dp4/tp8 + `--enable-expert-parallel`（EP=32，12 专家/卡）拉起 DeepSeek-V4-Pro-w4a8-mtp，32 个 rank 权重加载全部成功，然后**固定死在** `determine_available_memory → profile_run`（KV-cache 显存探测）阶段，不是运行期：

```
RuntimeError: ACL stream synchronize failed, error code:507014
[Error]: The aicore execution times out.
device error: fftsplus aivector error ... [aicore timeout], subErrType:4
```

plog 定位 fault kernel = `MoeDistributeDispatchV2`（MC2 融合 MoE 分发）。现场已自证：纯 HCCL 脚本（`all_reduce` + `all_to_all`）跨 4 节点 32 卡正常（约 16 GB/s、数据正确）；`--load-format dummy --enforce-eager` 仍复现；单节点少层数 dummy 可通过 profiling；CANN 8.5.1 / 9.0.0 / 9.0.1 三版同样崩溃且 fault kernel hash 一致。四项环境变量消融（`HCCL_OP_EXPANSION_MODE=AIV`、`enable_mc2_hierarchy_comm`、`HCCL_INTRA_PCIE_ENABLE`/`HCCL_INTRA_ROCE_ENABLE`、`ASCEND_LAUNCH_BLOCKING`）全部无效。

## 一句话根因

现场 host HDK（**npu driver 24.1.0.3 / firmware 7.5.0.5.220**）低于 CANN 9.0.1 的官方配套要求——CANN 9.0.1 配套 HDK 为 **26.0.RC3 / 26.0.RC1 / 25.5.2 / 25.5.1**，24.1.x 不在表内，且低于整表最小值 25.0.X。MC2 融合分发算子把跨卡通信织进 AIV 核内执行，在该驱动上任务不返回，看门狗按超时上报 AICore timeout（507014，plog `retCode=0x25`）。**机制为推断**：本案未拿到驱动层失败的直接日志，也未在本案闭环。

## fix

升级 HDK：firmware + npu driver 升到 CANN 9.0.1 的配套版本（**25.5.1 / 25.5.2 / 26.0.RC1**，建议 25.5.2 或 26.0.RC1）；上层 CANN 9.0.1 无需变动。升级需节点级操作并重启，前后各跑一次 `npu-smi info` 留档。验证：4×A2 多节点 EP=32 重新拉起，走过 `profile_run` 进入正常服务。

**诊断要点**：多节点 EP 拉起在 profile_run 报 aicore 超时、fault kernel 是 `MoeDistributeDispatchV2`，且**纯 HCCL 正常 + 单节点可过**时，先查 HDK 与 CANN 的配套关系，不要按组网 / batchsize / 显存方向查（那三个方向的报错码分别落在 507057 / 561002 / 显存类）。

**判别边界**：`507014`（aicore timeout，`retCode=0x25`、`subErrType:4`）与 `507057`（SUSPECT REMOTE ERROR / MTE DDR 越界，`errCode 0x800000`）是**两种物理事件**，修复方向不同。`--enable-expert-parallel` 虽可让 A2 落回 AllGather 从而绕开 MC2，但每卡需持有全部专家权重，384 专家的 DSV4-Pro 在 64GB A2 上很可能 OOM——该动作只作判别实验，**不作部署建议**。

## 与 VLLM-ASC-9005 的 variant 关系（pre-triage）

**判 `variant_of` 而非 `new_pattern`**，理由是根因机制同源：都是「HDK 版本低于 CANN 配套要求」在多节点大通信量 MoE 场景下暴露。相同面：平台 A2-910B、≥4 机多节点 + DeepSeek-V4-Pro、修复动作同为升级 firmware + npu driver 且不动 CANN。

不同面（决定两者不可互相替代）：

| 维度 | VLLM-ASC-9005 | VLLM-ASC-12430（本案） |
|---|---|---|
| 报错形态 | `Memory resources are exhausted`（显存耗尽误报，显存实际余 20+G） | AICore timeout `507014`（kernel 卡死） |
| 触发位置 | 显存探测 / 拉起阶段 | 固定 `profile_run`（KV-cache profiling） |
| 涉及算子 | 未点名 | plog fault kernel = `MoeDistributeDispatchV2`（MC2 融合分发） |
| 判别入口 | 显存误报 grep（`Memory resources are exhausted`） | 错误码 + fault kernel grep（`507014`/`MoeDistributeDispatchV2`） |
| 现场 HDK | firmware 7.0.1.3.220 / driver 23.0.7 | firmware 7.5.0.5.220 / driver 24.1.0.3 |

两者 `quickly_check` 不通用，故即便并入 9005 也需扩 symptoms 与 `hdk` 区间；groom 的二选一（并入 vs 独立成条）见 case 文件头部注释。

## verification

**investigation**（本地诊断 + 上游先例查证，**无上游确认、无 fix PR、案未闭环**）
根因证据三方收敛：① CANN 9.0.1 ↔ HDK 官方配套矩阵（`references/compat-matrices/cann-hdk.yaml`，引 CANN release-note）显示 24.1.x 越界；② 同 driver 24.1.0.3 存在完全同签名先例 [#4914](https://github.com/vllm-project/vllm-ascend/issues/4914)（同 507014、同 `subErrType:4`、同 `retCode=0x25`，其 plog 含 `rtMemcpy execute failed, reason=[driver error:internal error]`，发帖人判为驱动问题）；③ [#5468](https://github.com/vllm-project/vllm-ascend/issues/5468) 维护者口径「CANN 8.5.0 即要求 driver >= 25.0」，而现场 CANN 更高（9.0.1）驱动更低（24.1.x）。另有 [#6875](https://github.com/vllm-project/vllm-ascend/issues/6875)（4×A2、同 507014）为同错误码旁证。

**反证（已如实记入 case）**：[#8960](https://github.com/vllm-project/vllm-ascend/issues/8960) 在 driver 25.5.2 上仍出现同族 MC2/AIV 超时，维护者开的 [#15985](https://github.com/vllm-project/vllm-ascend/issues/15985) 把 A3 侧 `MoeDistributeDispatchV2` 超时列为 v0.26.0rc1 已知问题。故「MC2 超时」是一族问题，本 case 只覆盖「HDK 低于 CANN 配套」这一支。

## 未提取 / 待补的证据

- **本案 plog 全文未获取**（issue 正文只给摘要）。要把机制从推断变实证，需在 plog 里 grep `driver error`（对应 #4914 的 `rtMemcpy ... [driver error:internal error]`）。
- **`npu-smi info` 原始输出未获取**，driver 24.1.0.3 取自 issue 正文自述。
- **升级后重跑结果未获取**，故本案未闭环。

## 闭环（2026-09-16）

工程师回报本问题闭环，诊断 trace 的 `feedback.outcome` 置 `resolved`（session `2026-09-16-12430-dsv4pro-mc2`），由 `scripts/settle_trace_feedback.py` 结算 → `confidence.hits: 0→1`。

沉淀与演进均已合入：case 与 postmortem 经 PR [#230](https://github.com/pillumina/ascend-sleuth/pull/230) 进 main；本次诊断顺带产出的两条流程改进（版本组合键点明先验层具体文件、case 草稿结构校验进 CI）走 EV-2026-094 / EV-2026-095，经 PR [#231](https://github.com/pillumina/ascend-sleuth/pull/231) 与 [#232](https://github.com/pillumina/ascend-sleuth/pull/232) 落位。

**闭环口径的强度如实标注**：现场给出的是「本问题闭环」，**未附带「升级 HDK 后 507014 消失」的直接实测对照**。因此本条的 `verification` 仍为 `investigation`，`root_cause` 仍是三方证据收敛的推断。若日后拿到升级前后对照、或 plog 里的 `driver error` 行，再据此升 `verification` 档并考虑记 `validation_record`。

## 修订记录

- 2026-09-16 初稿（据 issue #12430 与上游先例 #4914/#5468/#6875/#8960/#15985 + 本库 `cann-hdk` 配套矩阵 + vllm-ascend `v0.23.0rc1` 源码）
- 2026-09-16 补「闭环」节与修订记录：记现场闭环回报、结算结果与合入落点，并标注闭环口径未含升级实测
