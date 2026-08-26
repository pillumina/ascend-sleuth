# VLLM-ASC-13050: 310P 推理触发 IndexPut aicpu exception（0x2a/507018），0.23.0 正式版修复

> 源是结构化 GitHub issue 线程（10 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/13050
**fix 跟踪**：确认版本 v0.23.0 正式版（用户评论#8 "0.23.0正式版上述问题全部解决"）；驱动 24.x→25.x 亦可
**时间**：2026-07-29 ~ 2026-08-03
**框架**：vllm-ascend nightly-releases-v0.23.0-310p-openeuler + Qwen3.6-35B-A3B-w8a8，TP=2，310P 双芯（300I Duo）
**平台**：310P
**category**：interrupt
**investigation_quality**：high（多用户复现 + POC 镜像同参对照 + workaround 验证 + 官方确认修复版本）
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md

## 结构化 case

`postmortems/inbox/VLLM-ASC-13050.case.yaml`（Tier 2 候选，待 groom 审）

## 一句话根因

310P 上 Qwen3.6-35B-A3B-w8a8 的推理请求触发 aicpu kernel `IndexPut` 执行异常（errorCode=0x2a，runtime 507018，stream phase=SCHEDULE）→ 服务崩溃。根因位于 310P aicpu 内核与 vllm_ascend/_310p 路径（`gdn_310.py` 多模态 embedding 写入）的兼容性：0.23.0 rc/夜间镜像复现、POC 镜像正常、**0.23.0 正式版修复**；maintainer 倾向驱动兼容问题（24.x 驱动下多发，升 25.x 可解）。

## 弯路与级联

- **弯路（先排除后确认）**：先怀疑启动参数（多组参数均能启动、首请求即崩）→ 排除；POC 镜像（dev-26.0.0.poc）同参数可正常推理 → 指向镜像/版本差异；AI 协助修改 `gdn_310.py` 两行可稳定（workaround）→ 定位到 _310p 写入路径；maintainer 定性驱动问题（24.1.t29 用户复现）；最终 0.23.0 正式版验证修复。
- **误导性报错**：日志先出现的 `CopyKernelOpApi.cpp:58 E39999 Warning` 是同一 aicpu 异常的伴随输出，不必单独排查（diagnosis 列为忽略项）。注意：驱动 25.2 的另一用户（jpyjpr）仍复现且 gdn_310.py 修改后图片/超长输入仍报错 → workaround 不完整，版本升级是正解。
