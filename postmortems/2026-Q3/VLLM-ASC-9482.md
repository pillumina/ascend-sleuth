# VLLM-ASC-9482: --async-scheduling + MTP 崩溃——_copy_valid_sampled_token_count 多流不同步致 token 计数溢出（PR #9456 修复）

> 源是结构化 GitHub issue 线程（结构化外部文档，报错为截图），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest r2-sed-g4（2026-09）产出，进 inbox 待 groom 分诊；不改正式 knowledge/ 目录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/9482
**fix 跟踪**：PR #9456 "[BugFix]Fix Deepseek-V4 async scheduling with MTP"（base main，merged 2026-05-22，merge 7e817f291b）；维护者 lilinsiman（2026-05-27）确认 latest main 已解决；同族 issue #9024
**时间**：2026-05-23 ~ 2026-05-27
**框架**：vllm-ascend 0.19.0 与当时 main 均复现；Qwen3.5-APC + MTP；同族 #9024 = Qwen3.5-27B-w8a8-mtp + prefix caching
**category**：interrupt
**investigation_quality**：high（vllm-ascend 开发者源码级定位 + 本地删改验证 + 上游 merged PR 闭环）
**verification**：upstream-fix-merged（PR #9456）
**novelty**：variant_of VLLM-ASC-13964——同"async scheduling 下 runner 层 token 计数记账错误"族；13964 = num_computed_tokens 乐观计数→SWA KV 提前剪枝→静默停滞（PR #13518）；本条 = _copy_valid_sampled_token_count 多流不同步→valid_sampled_tokens_count 脏读→num_accepted/num_computed_tokens 溢出崩溃（PR #9456）

## 现象摘要

Qwen3.5-APC + MTP（spec decode）服务，开启 `--async-scheduling` 后崩溃（0.19.0 与 main 均复现，trace 在 issue 为截图）。开发者打印定位：

- 与 `--async-scheduling` 冲突：开启后 `num_accepted` 与 `num_computed_tokens` **溢出**导致后续崩溃；
- 定位到 model runner 的 `_copy_valid_sampled_token_count`：PR #8766 重写了该方法，把 `current_stream` 声明在 `with torch.npu.stream(self.valid_sampled_token_count_copy_stream)` **里面**（GPU 实现声明在 context 外）——多流未正确同步；
- 删除该改写本地自测可修复 apc+mtp+async-scheduling；但 #8766 声称有性能收益，需正式解法。

## 一句话根因

PR #8766 重写 `_copy_valid_sampled_token_count` 时把 `current_stream` 声明进 `with torch.npu.stream(...)` 作用域内（GPU 参考实现声明在 context 外）→ 拷贝所在流未被正确同步/记录 → async scheduling + MTP 路径下 `valid_sampled_tokens_count` **多流脏读写** → `num_accepted`/`num_computed_tokens` 被污染溢出 → 崩溃（同族 #9024 表现：`IndexError: list index out of range`，`get_temporal_copy_spec` 按 `num_accepted_tokens` 越界）。

## fix

- **升级/合入 PR #9456**（merged 2026-05-22，main）：修正 `_copy_valid_sampled_token_count` 多流同步，并给 deepseek-v4（attn backend 需 `positions_cpu`）加**专用 CPU tensor** 免同步。
- 临时规避（均有代价）：关 `--async-scheduling`，或移除 #8766 对 `_copy_valid_sampled_token_count` 的改写。
- 同族 #9024（MTP + prefix caching IndexError）由同一修复覆盖。

## 弯路与级联

- 现象初看像 spec-decode/prefix-caching 交互问题（#9024 单独报告）；实为 runner 层 token 计数拷贝的多流同步缺陷，与具体投机后端无关。
- 不要用关 async-scheduling 长期规避（功能/性能回归）。

## 建议 triage 路由症状

新组合签名（async-scheduling + MTP 崩溃）难以用单一错误串表达；`IndexError: list index out of range` 建议补入 inference_interrupt 异常类正则（当前缺 IndexError，ValueError 已补录）——可选，needs-review。
