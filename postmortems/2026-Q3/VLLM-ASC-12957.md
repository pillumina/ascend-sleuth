# VLLM-ASC-12957: PD 分离 P 侧 k_pe 未同步 NPU 流，D 侧 RDMA pull 读到陈旧值致首请求乱码

> 源是结构化 GitHub issue 线程（5 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/12957
**fix 跟踪**：PR #14269（https://github.com/vllm-project/vllm-ascend/pull/14269，`sfa_v1.py` 加 `torch.npu.current_stream().synchronize()`）
**时间**：2026-07-28 ~ 2026-08-25
**框架**：vllm-ascend 0.20.2 + glm-5.1-w8a8，PP=4/TP=8/DP=1（P 侧），DP=8/TP=4（D 侧），use_ascend_direct=true（RDMA/ADXL）
**平台**：A3-910C（4 台 16 卡 pod）
**category**：precision
**investigation_quality**：high（kvcache 逐层数值比对定位 PP stage 边界突变 + 代码级根因 + 修复实测验证 + 官方落地）
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md

## 结构化 case

`postmortems/inbox/VLLM-ASC-12957.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

PD 分离 + PP4 下，P 侧 prefill 每层把 k_pe 写入 V cache 后经 `kv_ag_handle.wait()` 等待 all-gather 完成，但**未同步 NPU 当前流**；D 侧 ascend_direct RDMA pull 在 prefill forward 返回后立即读取，读到未落盘的陈旧 k_pe，每个 PP stage 边界（layer 20→21、40→41、60→61）引入一次偏差 → 首请求乱码。修复：`sfa_v1.py` 在 `kv_ag_handle.wait()` 后加 `torch.npu.current_stream().synchronize()`。

## 弯路与级联

- **弯路（先排除后确认）**：先后关闭 MTP、prefix cache、reasoning parser、kvcache 清零（dummy run 后覆盖赋值）、slot mapping=-1（claudecode 偶现乱码修复 PR）、drafter slot mapping=-1、图模式（enforce_eager）——**全部无法消除乱码**；P 节点改 DP=4（无 PP）不乱码 → 缩小到 PP 时序问题；再以 kvcache 逐层求和比对，V cache 在 layer 21/41/61（PP 分区 20,20,20,18 的 stage 边界）突变甚至正负翻转 → 定位到跨 stage KV 传输的流同步缺失。
- **误导性报错**：无显式报错——本 case 是"无报错的错误输出"，判别靠 badcase 复现模式（首请求乱码、先普通后 badcase 不乱码、P 改 DP4 不乱码）。
