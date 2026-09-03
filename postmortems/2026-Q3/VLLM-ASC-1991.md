# VLLM-ASC-1991: Qwen3-Embedding-4B 在 300I Duo/310P 上跑不起来——310P 平台 pooling 模型支持缺失（PR #8846 后 main 可用）

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest r2-sed-g1（2026-09）产出，进 inbox 待 groom 分诊；不改正式 knowledge/ 目录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/1991
**fix 跟踪**：PR #8846 [Feature] Support pooling models on 310P platform（merged 2026-05-27 realliujiaxu，附 310P E2E：embedding/classification/scoring）；issue 同一天由维护者 yiz-liu 关闭（completed）
**时间**：2025-07-24（报）~ 2026-05-27（关，跨度近 10 个月）
**框架/平台**：vllm-ascend v0.9.2rc1-310p 镜像 + CANN 8.1.RC1 + torch-npu 2.5.1；Atlas 300I Duo（芯片 310P3）；Qwen3-Embedding-4B（TP2，pooling_type=LAST）
**category**：interrupt
**investigation_quality**：medium（上游 PR 给出代码级支持补全 + E2E 测试；issue 线程本身早期是"未支持"回复、无逐层排查记录）
**verification**：upstream-fix-merged（fix PR #8846）
**novelty**：variant_of VLLM-ASC-15086——同"模型/功能 not-supported 启动失败 → 查上游 registry/平台支持合入版本 → 升级修复"诊断族（15086=K3 架构 registry 版本错位；本条=310P 平台 pooling 支持缺失）；增量=缺失对象不同（310P pooling 非因果 attention 路径 vs K3 架构注册）、修复 PR 不同；相似在诊断路径不在根因层，groom 复核是否该归 new_pattern

## 现象摘要

300I Duo（310P3）上 `vllm serve Qwen3-Embedding-4B --tensor-parallel-size 2` 起服务，rank1 worker `init_device` 即崩：

```
RuntimeError: SetPrecisionMode: ... NPU function error: at_npu::native::AclSetCompileopt(
    aclCompileOpt::ACL_PRECISION_MODE, precision_mode), error code is 500001
[Init][Compiler]Init compiler failed ... OpCompileProcessor init failed!
```

维护者 310P3 复现同一模型，报模型加载失败（不同签名）：

```
ValueError: There is no module or parameter named 'layers' in CustomQwen3ForCausalLM
（vllm_ascend/models/qwen3.py load_weights → 权重名映射失败）
```

## 一句话根因

310P/300I 平台的 pooling（embedding/classify/scoring，非因果 attention）模型支持缺失：vllm-ascend 在该平台的 qwen3 路径无法正确加载/运行 pooling 模型（叠加 300I 仅 eager 模式约束），直到 PR #8846 补上 310P 的非因果 attention mask 生成与 flash attention forward 才可用。

## fix

- 升级 vllm-ascend 到含 PR #8846 的版本（main 2026-05-27 合入；用 main 或下一发布版验证），310P 上即可跑 embedding/classification/scoring 等 pooling 模型。
- 300I 系列另需 `--enforce-eager`（300I 不支持图模式）。
- 旧版本无代码级 workaround——不是 CANN/驱动/权限问题（报错里的 ACL/GE init 报错是平台支持缺失的级联表现，勿按环境问题排查）。

## 弯路与级联

- 首报错误（SetPrecisionMode 500001 / GE init failed）看起来像环境/CANN 问题，实际是 310P pooling 支持缺失在不同子路径的表现（另一表现 = CustomQwen3 权重加载 ValueError 'layers'）——两条签名都指向"该模型形态在 310P 未适配"。
- issue 停摆近 10 个月到 PR #8846 才闭合；groom 跟踪含 #8846 的正式发布版回填 compat。

## 建议 triage 路由症状

`not supported`/启动失败已被 inference_interrupt 现有正则覆盖；本 case 特有签名 `no module or parameter named 'layers' in CustomQwen3`（+310P）可不追加，靠 symptoms 文本匹配即可。
