# S2（源码线索）
维护者指向 vllm_ascend/sample/sampler.py 的 npu_top_k_top_p：该优化要求 CANN 8.2rc1，
版本低时此路径 aivec 崩溃（升级 CANN 或 env=0 兜底）。
