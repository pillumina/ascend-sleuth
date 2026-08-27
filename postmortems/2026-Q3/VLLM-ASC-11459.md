# VLLM-ASC-11459: MooncakeBackend lazy_init 时 _setup_store() 在 KV 传输线程调无参 get_global_rank() 抛 AssertionError，store 永不初始化

> 源是结构化 GitHub PR 线程（2 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/pull/11459
**fix 跟踪**：PR #11459（merged 2026-07-06；上游 PR #9731）；文件 `vllm_ascend/distributed/kv_transfer/kv_pool/ascend_store/backend/mooncake_backend.py`
**时间**：2026-07-06（同日创建并合并）
**框架**：vllm-ascend v0.23.0；DSV4-Flash-w8a8-mtp，`ASCEND_ENABLE_USE_FABRIC_MEM=1`，`enable_multithread_load=true`
**平台**：未声明（Ascend fabric memory 卸载路径）
**category**：interrupt
**investigation_quality**：high（before/after 复现 + 根因链完整 + 已合并）
**批量导入**：批次 2 组 2（2026-08）

## 结构化 case

`postmortems/inbox/VLLM-ASC-11459.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

MooncakeBackend `lazy_init=True`（DSV4 压缩模型 + `ASCEND_ENABLE_USE_FABRIC_MEM=1`）时 `_setup_store()` 从 `__init__` 推迟到首次 `put()`，运行在 KV 传输发送线程；无参 `get_global_rank()` 回退读主线程 process-global vllm config（该线程上为 None）→ `AssertionError: Current vLLM config is not set`（x43），store 永不初始化，后续每次 `put()` 失败。

## 弯路与级联

- **跨线程配置可见性**：process-global `_current_vllm_config` 只由主线程 `set_current_vllm_config()` 设置，任何后台线程直接读都会是 None——排查 KV 传输/后台线程里偶发 AssertionError 时先怀疑这个。
- **引入点**：per-DP-rank SSD 子目录改动在 `_setup_store()` 里加了 `get_global_rank()` 调用，才把该依赖暴露到跨线程路径。
- **fix**：`__init__` 缓存 `parallel_config`，`_setup_store()` 显式传 `get_global_rank(self.parallel_config)`，不再依赖线程本地 process-global config。
