# S2 Replay 评分报告 — vllm-ascend 校准集（2026-09-02 全自动轮）

> 4 条 high confidence + fix PR 的未测校准条目完成盲测 diagnose replay。
> 盲测纪律：仅读 .md 现象 + knowledge/references/postmortems（Tier-2/3），
> 未读 eval 期望、未读目标 issue 的 inbox 草稿（防泄题）。

| issue | res_conf | rc_match | 路由 | 根因方向 vs resolution | 评估 |
|---|---|---|---|---|---|
| 14363 | high | ✅ True | ok | DeepseekV4MoE routed FusedMoE 漏传 swiglu_limit（命中！） | 诊断正确——inbox 已有草稿（EV-2026-002）待升格 |
| 13639 | high | ✅ True | ok | FullGraph × spec-decode 动态 draft 冲突 → hang（方向正确） | 诊断正确——证据缺口大（trace 裁剪） |
| 14871 | high | ❌ False | ok | recompute 读缺失 async_tokens_to_discard（方向对，自动匹配弱） | 方向一致（PR #14504 即 recompute 同步），需补 case |
| 13446 | high | ❌ False | ok | config 类型错配（Qwen3VLConfig vs Qwen3Config） | 方向正确，缺 config.json 证据 |

**结论**：
- 2/4 自动 rc_match=True；2/4 False 但人工复核方向均与 resolution 一致（弱信号局限，如实标注）
- 4 条全部 Tier-2 未命中 → **覆盖缺口信号**：#14871/#13446（评估已 pass 入沉淀清单）、#14363（inbox 草稿已有）、#13639（同族 VLLM-ASC-9507/13688 部分覆盖，值得后续补）
- 路由全部正确（无 triage 归因事件——台账不产生误报，如实）
