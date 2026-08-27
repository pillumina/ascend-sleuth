# VLLM-ASC-9186: GLM5.1-w4a8 拉起报 RuntimeError：_C_ascend::dispatch_ffn_combine() bias1 类型不匹配（Parameter vs Optional[List[Tensor]]）

> 源是结构化 GitHub issue 线程（4 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/9186
**fix 跟踪**：PR #11701（merged，ZT-AIA 用 megamoe 算子整体替换 dispatch_ffn_combine）；中间方案 PR #9231（ACLNN 算子适配，用户实测 segfault，弃用）
**时间**：2026-05-15 ~ 2026-08-10（completed）
**框架**：vllm-ascend 0.19.1rc2.dev45 + vLLM 0.20.1（失败环境）；修复在 main
**平台**：未在 thread 内明确（昇腾 aarch64，CANN 8.5.1；关联单测目录 multicard_ops_a3）
**category**：interrupt
**investigation_quality**：high（维护者 ZT-AIA 直接定位 pybind 类型签名 + 最终 megamoe 替换 PR，闭环确认）
**批量导入**：批次 2 组 4（2026-08）

## 一句话根因

昇腾自定义算子 `_C_ascend::dispatch_ffn_combine` 的 pybind 签名要求 `bias1` 为 `Optional[List[Tensor]]`，vllm-ascend fused MoE w4a8 路径传入的是 `torch.nn.Parameter`，类型绑定不匹配抛 RuntimeError，服务启动失败；官方最终用 megamoe 算子替换 dispatch_ffn_combine（PR #11701）。

## 弯路与级联

- **中间方案 segfault**：MarinaMiao 尝试 PR #9231 用 ACLNN 算子适配 fused MoE w4a8，遭遇 `aclTensorList::operator[]` segfault（plog 见评论#3）——ACLNN 适配路径不可用，不要重复尝试。
- **忽略级联报错**：bias1 类型断言失败后的 WorkerProc 启动失败/EngineCore 初始化失败等一串多进程报错都是根因的 noise，只认 `dispatch_ffn_combine() ... 'bias1'` 一行。
- **修复方向**：官方选择整体替换算子（megamoe）而非修 pybind 绑定——升级含 PR #11701 的版本即可，不要本地改参数类型打补丁。
