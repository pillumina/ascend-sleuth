# VLLM-ASC-10303: 310P 部署 Qwen3-TTS（vllm-omni）——无 310P 现成镜像，需源码安装版本组合 + qwen3_tts.yaml dtype 全改 fp16

> 源是结构化 GitHub issue 线程 + vllm-omni 修复 PR（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest sed-g1 批次 1 产出（人工筛出的高质量 closed issues），进 inbox 待 groom 分诊。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/10303
**修复 PR**：https://github.com/vllm-project/vllm-omni/pull/4283（[Hardware][Ascend] Adapt Qwen3 TTS for 310P，merged 2026-06-12）；vllm-ascend 侧无 fix PR
**框架/平台**：vllm-omni（配套 vllm 0.22.0 + vllm-ascend dde19f7 + vllm-omni main）/ 310P（Atlas 300I，310P3；**310P 不支持 bf16**）
**category**：interrupt
**investigation_quality**：medium（维护者给出版本矩阵 + 用户源码部署实测成功闭环；线程内无失败日志，未做系统对照）
**verification**：upstream-fix-merged（vllm-omni PR#4283 已合入）
**novelty**：new_pattern——库内无 qwen3-tts/vllm-omni 族；310P 存量 case（10122/12983/12989/13050）均为算子/CANN/资源机制，与本条"部署镜像与 dtype 平台兼容"机制无重叠

## 现象摘要

Qwen3-TTS-12Hz（0.6B/1.7B-Base）需 vllm-omni 跑。quay.io/ascend/vllm-omni:v0.18.0 镜像是 **910B 适配**，310P 未测试/不可用；310P 又不支持 bf16。用户问 310P 能否用该镜像部署。

- 线程尾部：维护者（zyz111222）给出 310P 源码安装版本组合；用户按此 + fp16 配置实测**部署成功、310P 调 NPU 正常**，并回贴完整 Dockerfile（CANN 9.1.0-beta.1-310p 基础镜像）与 qwen3_tts_310p.yaml。
- 910B 场景另有一个镜像内小 bug"权重没加载到 NPU"（vllm-omni#2323，fix #2353）——与本条 310P 部署问题不同，勿混淆。

## 一句话根因

vllm-omni 官方镜像/代码按 910B 适配、310P 无现成可部署产物，且 Qwen3-TTS 部署配置 qwen3_tts.yaml 默认 dtype 为 bf16 系——310P 芯片不支持 bf16，按 910B 路径在 310P 上无法部署；需 310P 源码安装特定版本组合 + qwen3_tts.yaml 各 stage dtype 全改 float16。

## fix

- 版本组合（310P）：vllm **0.22.0** + vllm-ascend commit **dde19f7b06ed24d9e3cc9fed45595408424364a4** + vllm-omni main（已含 PR#4283 的 `_310p` patch，2026-06-12 合入）。
- 配置：qwen3_tts.yaml 所有 stage `dtype: float16`；`vllm serve ... --dtype float16 --omni`。
- 部署脚本/镜像参考 issue#10303 评论（issuecomment-4686471586 起）。

## 建议 triage 路由症状

现有 triage-tree 无 Qwen3-TTS/omni 正则——若 triage 命中失败，建议给 inference 分支加 `qwen3-tts|vllm-omni` 症状正则（随 case PR 一并提交，needs-review 由 groom 定夺）。
