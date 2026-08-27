# VLLM-ASC-13329: DSV4-Flash-0731 是 DSpark 模型无 MTP head（mtp 模式启动报 KeyError 'mtp.0.head.weight'，应改用 dspark）

> 源是 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/13329
**fix 跟踪**：无 PR；作者自证改用 `--speculative-config '{"method": "dspark", "num_speculative_tokens": 7, ...}'` 正常加速
**时间**：2026-08-02 ~ 2026-08-02
**框架**：vllm-ascend nightly-releases-v0.25.1rc-openeuler
**平台**：A2 (910B)，模型 DeepSeek-V4-Flash-0731-w8a8
**category**：other
**investigation_quality**：low
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（Phase B 批量 to-postmortem）

## 结构化 case

草稿：`postmortems/inbox/VLLM-ASC-13329.case.yaml`（Tier 2 入库前待 groom 分诊；同根因对 #13379 预期被预分诊为 variant_of:#13329）。

## 一句话根因

DeepSeek-V4-Flash-0731（w8a8）是 DSpark 模型、权重中不含 MTP head；用 `--speculative-config '{"method": "mtp", ...}'` 启动时模型加载按 `mtp.0.head.weight` 查量化描述抛 KeyError。应改用 dspark speculative method（该版本已支持）。

## 弯路与级联

- 作者先自我怀疑"是我启动脚本有问题还是镜像问题"，随后自答改用 dspark 成功，闭环很快（当天关闭）。
- 后续评论追问 dspark 接受率与固件版本，作者给出"接受率 10%~80% 不平均"——属于 dspark 本身的正常波动，非本 issue 的问题。
