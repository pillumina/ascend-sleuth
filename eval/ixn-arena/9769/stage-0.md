# S0（首报版）
## 症状
Qwen3-8B-w8a8s-310（310P，vllm serve，FULL_DECODE_ONLY 图模式）首个推理请求 AICore
exception：QuantBatchMatmulV3 期望 ND 收到 FRACTAL_NZ；加 --enforce-eager 可避免。
## （未提供：CANN/框架版本、复现命令）
