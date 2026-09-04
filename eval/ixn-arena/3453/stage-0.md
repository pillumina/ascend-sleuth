# S0（首报版）
## 症状
自定义加载脚本跑 Qwen3-32B：rotary_embedding 曾加载失败（按 #3414 规避后继续）；
现遇 torch.ops._C_ascend 相关算子（weak_ref_tensor 等）不受 NPU 后端支持告警/回退；
环境 torch 2.8.0 / torch_npu 2.8.0rc1。
## （未提供：版本选择是否异常、官方建议）
