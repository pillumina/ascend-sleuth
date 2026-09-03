# VLLM-ASC-7993: A2 + MiniMax-M2.5-w8a8-QuaRot 图模式偶现 fftsplus FIA 算子越界/内存访问错误——CANN runtime graph 下 attention update_param 的 args copy 保序缺失（CANN 9.0 修复）

> 源是结构化 GitHub issue 线程（9 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/7993
**fix 跟踪**：无 vllm-ascend repo PR；根因（评论#8，报者 coder-fny runtime 级定位）为图模式下 attention update_param kernel launch 的 args copy 保序 bug，修复合入 **CANN 9.0**（runtime）；issue 由报者关闭（completed 2026-04-23）。同族 #7593（SparrowMu 关联）
**时间**：2026-04-06 ~ 2026-04-23（completed）
**框架**：vllm-ascend 0.18（VLLM_VERSION=0.18.0）+ minimax-m2.5-w8a8-quarot（--tool-call-parser minimax_m2）+ FULL_DECODE_ONLY 图模式；0.14 不触发（评论#0：0.18 遇类似、0.14 没有）
**平台**：Ascend 910B（A2-910B）；x86 更易触发（见根因）
**category**：interrupt（运行期 aicore/runtime 崩溃，偶现）
**investigation_quality**：medium（报者提供完整 runtime plog + 定位到 launch args copy 机制并说明 ARM/x86 阈值差异；但无官方代码级确认，CANN 侧修复不可在 repo 核验）
**verification**：investigation（无 vllm-ascend PR；修复合入闭源 CANN 9.0 runtime，thread 自述，无外部 repo 证据可核）
**pre-triage**：new_pattern（现库无 FIA/graph args copy runtime bug case；邻近 VLLM-ASC-12983 是 310P 图模式缺 free-mask 算子另一根因）

## 现象摘要

- A2 上 minimax-m2.5-w8a8-quarot 权重 + vllm-ascend 0.18 + FULL_DECODE_ONLY 图模式 + --enable-auto-tool-choice/--tool-call-parser minimax_m2，推理偶现崩溃。
- runtime plog 特征：`there is an exception of fftsplus aicore error` / `fftsplus aivector error`（core dump，MTE error info 非零，extend info subErrType=4 "D-cache 读写 UB 时总线返回值非零"）、`Task run failed ... sqe_type=7(notify wait), errType=0x20(sq sw status error)`、`the model stream execute failed`。
- 0.18 触发、0.14 不触发（Hutonm 同环境对照）；TP2_EP2 加载期 WorkerProc failed to start 为 thread 中另一现象（fourierr，未定论是否同因）。

## 一句话根因

CANN runtime 图模式（ACL graph）下，attention 的 update_param 在 kernel launch 环节执行 args copy：按 arg size 选择拷贝方式，size 超过阈值（x86 >1k，ARM >4k）走**异步拷贝分支且未做保序**，FIA 算子拿到错误（旧）地址 → 偶现越界/内存访问错误崩溃。x86 阈值更低故更易触发。修复合入 CANN 9.0。

## fix

升级 CANN ≥9.0（runtime 修复合入 CANN 9.0）。无配置 workaround；0.14 对照仅说明回归引入面，不作为规避。

## 弯路与级联

- thread 中 fourierr 的 TP2_EP2 模型加载期 WorkerProc failed to start 与运行期 FIA 崩溃是不同现象，未与根因合并（勿混判）。
- 级联：runtime aicore 异常后的多行 [ERROR] RUNTIME stars_engine/device_error_core_proc 日志都是同一崩溃的登记输出，判型以首错 fftsplus error + sq sw status error 为准。
