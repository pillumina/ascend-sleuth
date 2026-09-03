# VLLM-ASC-8808: PD 分离 + KV Pool 请求卡 waiting——0.18.0rc1 spec decode 路径 KV 从不 Put 入池

> 源是结构化 GitHub issue 线程（10 条评论），按 to-postmortem 优化——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/8808
**fix 跟踪**：PR #7874（https://github.com/vllm-project/vllm-ascend/pull/7874，[BugFix][0.18.0][KV Pool]，merged 2026-04-02 releases/v0.18.0；`vllm_ascend/worker/model_runner_v1.py`）
**时间**：2026-04-29（报）～ 2026-05-14（closed completed）
**框架**：vllm-ascend 0.18.0rc1（官方镜像）；GLM-5.1-w4a8，`--quantization ascend`
**平台**：A2-910B，1P1D PD 分离；KV Pool = MooncakeConnectorV1 + AscendStoreConnector(backend=mooncake)
**category**：interrupt
**investigation_quality**：medium（现象 + master 指标确认无 Put；维护者指认缺 PR；cherry-pick 后实测恢复）
**批量导入**：sed-g3（2026-09）
**pre-triage**：variant_of VLLM-ASC-11459（父 case 已入库；同族="PD 分离 + KV Pool 未 Put → 请求阻塞"）

## 结构化 case

`postmortems/inbox/VLLM-ASC-8808.case.yaml`（Tier 2 候选，待 groom 审）

## 现象摘要

A2 1P1D PD 分离部署 GLM-5.1-w4a8 + KV Pool + deepseek_mtp（spec decode）于 0.18.0rc1：请求打进后 P 节点 KV cache 一直上涨不释放，后续请求长时间 `waiting`。mooncake master service 周期日志显示 `Mem Storage: 0 B / 32.00 GB`、`PutStart=0/0, PutEnd=0/0`——KV 从未写入池（只收到 ExistKey/Get 查询）。删 `VLLM_ASCEND_BALANCE_SCHEDULING=1`、调 `VLLM_NIXL_ABORT_REQUEST_TIMEOUT` 均无效。

## 一句话根因

上游 vLLM v0.18 在投机解码启用时把 KV connector finalization 推迟到 target-model forward 之后，vllm-ascend 升级 v0.18 时漏了适配（未补 `finalize_kv_connector`）→ KV Pool 的 Put 从不触发（master PutStart=0/0）→ P 节点 KV 只涨不释放、请求阻塞 waiting。

## fix

cherry-pick PR #7874（draft model 运行后调 `finalize_kv_connector()`）或升级含该 PR 的镜像；报者实测 waiting 消失，issue closed completed。附：修复后 0.18.0 池化 TTFT 劣化（40s→150s）是另一性能问题（报者开 FlashComm1 缓解），未在本 issue 闭环。

## verification

**upstream-fix-merged**（fix PR #7874，merged releases/v0.18.0 2026-04-02）
