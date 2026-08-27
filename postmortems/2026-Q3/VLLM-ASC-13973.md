# VLLM-ASC-13973: v0.26 P 节点 prefill 吞吐回归（dsa-cp 与共享专家 DP 解耦 + SFA DCP block table 宽度用错）

> 源是 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/13973
**fix 跟踪**：config workaround `"shared_expert_dp_enabled": true`（评论#3 官方确认）；SFA DCP block table 宽度已改回 local（随版本落地）
**时间**：2026-08-11 ~ 2026-08-25
**框架/平台**：vllm-ascend v0.26.0rc（对比 v0.23 5e1467062）+ torch-npu 2.10.0.post2 + CANN 9.0.1；硬件报告为 "Ascend 910 × 16 卡"（未明确 910B/910C），GLM-5.2 w4a8 PD 分离 P 节点
**category**：performance
**investigation_quality**：high
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（Phase B，第 2 批）

## 结构化 case

草稿：`postmortems/inbox/VLLM-ASC-13973.case.yaml`（Tier 2 入库前待 groom 分诊）。

## 一句话根因

v0.26 将 dsa-cp 与共享专家 DP 特性解耦，未显式开启 `shared_expert_dp_enabled` 时共享专家走 fc1 引入额外两次通信（DCP collective 通信量 ~5-6x、非重叠通信占比 1.58%→8.19%）；叠加开 prefix cache 时 SFA DCP metadata 构造用错 block table 宽度（父类 `_build_with_metadata_view()` 下 DCP 子类 super().build() 二次 `_build()` 拿到 replicated 宽表，invalid tail id 被 unique() 扫入 kv_gather_ids），TTFT P50 7617ms→54296ms（~7.1x）、prefill 吞吐 38811→29911 tok/s。

## 弯路与级联

- bench 对齐坑：v0.23 用 output-len=700（prefill+decode）、v0.26 用 output-len=1（纯 prefill），QPS/TPOT 不可直接比；TTFT 与 profiler 指标不受影响，是可靠判别量。
- 先做 git diff 对比（worker/pcp_utils.py 删除、dcp_utils.py 新增、attention/context_parallel 5 文件重写等）但明确不当作因果断言——profiler 数据才是客观证据。
- `enable_sparse_sfa_c8=false` 两边相同，排除 C8 开关；#13934 是同环境 D 节点不同 bug，不混淆。
- 注：assessment 判定为 performance；quickly_check 按指标阈值形态设计（非 grep 错误签名）。
