# VLLM-ASC-11127: GLM-5.1 MTP + PD 分离 decode 多 DP 压测接受率退化 <1%、curl 输出精度错误

> 源是结构化 GitHub issue 线程 + 修复 PR，按 to-postmortem——只写指针，不重写。
> 批量流水线 sed-g3（2026-09）产出草稿（对应 case.yaml 同目录）；周审后转正。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/11127
**修复 PR**：https://github.com/vllm-project/vllm-ascend/pull/10117（merged 2026-06-08，main）
**框架**：vllm-ascend（推理侧，Ascend NPU，A3 PD 分离部署）
**category**：precision（接受率退化 <1% + 手工 curl 输出精度错误；无 hang/crash 主诉）
**investigation_quality**：medium（issue completed 关闭 + reporter/maintainer 确认 + merged fix PR；thread 内无代码级根因推导）
**verification**：upstream-fix-merged（thread 2026-07-03 “合入 pr10117 后问题修复”；PR #10117 merged）
**pre-triage**：variant_of VLLM-ASC-12723（见 case.yaml 头注释证据）

## 现象摘要

GLM-5.1（w8a8）在 A3 PD 分离部署、decode 开启 MTP（spec-decode），kv_pool 池化开/关均有问题；压测 1-2 小时后 decode 节点 DP 投机接受率逐渐退化到不足 1% 且无法恢复，手工 curl 出现精度问题。关闭 MTP 无精度问题（可规避）。

## 一句话根因

PD 分离 decode 多 DP 场景下 spec-decode drafter 输入判断 `input_fits_in_drafter` 处理不当，压测累积后 MTP 接受率崩到 <1% 不恢复并伴输出精度错误；修复（PR #10117）= 移除 drafter 侧该判断 + 投机掩码填充改 1。

## fix

升级到含 PR #10117（vllm-ascend main，merged 2026-06-08）的版本并重启服务。workaround：关闭 MTP（thread 确认可规避）。reporter 2026-07-03 主干验证修复，issue completed 关闭。

## 弯路与级联

- kv_pool 池化开/关均复现 → 排除池化路径（排除实验由 reporter 完成）
- 关闭 MTP 即规避 → 根因锁定 MTP/spec-decode 路径，不是 PD 分离架构本身
- PR #10117 title 是“moe multi-DP hanging”（关联 vllm#44185），与本 issue 症状标题不同；以 thread 评论（合入 pr10117 后修复）+ PR 内容（移除 input_fits_in_drafter、mask fill 1，同解 #9221 回归）为准
