# ascend-sleuth v1.0.0

发布：2026-11-12。tag：`v1.0.0`，指向发布时的 `main`。版本语义：机制完备，可交付首批种子团队试用。

这是首个正式版本，覆盖当前已落地的机制与知识内容；缺口见「已知限制」。

训练或推理在昇腾 NPU 上出现中断、精度异常、性能退化。把日志、版本与报错交给 agent。系统按症状路由到已验证的案例（case），给出定位结论与修复建议。

定位结束后，新知识进入待审队列。例行维护负责去重、升格为 case。未命中与执行偏差进入演进流程。诊断、沉淀、演进三个环节共用知识层与诊断轨迹（trace）。改动经由 git 与 pull request（PR）审核。

## 诊断

`triage-tree.yaml` 分两层。负载类型决定查哪个命名空间，问题性质（中断、精度、性能）决定匹配形态。性质词表训推共用。

诊断按三层加载（Tier 1/2/3）。Tier 2 命中命名空间与问题类别的组合后，先读该类别的读侧视图。清单一行一条 case，按标题、标签与症状摘要过滤到 5 条以内。再加载全文，用 `quickly_check` 验证。Tier 3 `postmortems/` 在前两层未命中时按关键词兜底。

先验词条（`references/`）放与具体事故无关的事实与方法论。它不参与候选路由，只在诊断的五个固定时点被读取：缺测量数据时给采集面；证据含错误码、签名、环境变量或版本组合时查表族；证据含平台、组件或版本词时给背景事实；候选命中后给修复依据；候选全未命中时给排查流程。

平台差异按字段分发（A2-910B / A3-910C / A5-950）。版本兼容字段（`compat`）是软匹配，不匹配只降置信度，不排除 case。

命中时输出结论、依据链、修复与回滚（rollback）、可靠度。严重度闸门（`severity`）处理 `data-loss-risk` 时不提供修复方案。此时输出停机、保留现场、通知负责人。

诊断全程写 `traces/<session_id>.yaml`。`resume-diagnosis` 续接被打断的诊断。跨机交接见 `docs/guide/handoff.md`。建单时记录知识库版本坐标，续接时检查知识是否漂移。

Tier 2 未命中可继续做源码级分析。源码按版本缓存在 `src-code/`。知识库只记结论与 `source_ref` 指针。

## 知识内容

截至发布时：

| 资产 | 总量 | 构成 |
|---|---|---|
| case | 171 条 | inference/vllm-ascend 127（interrupt 96、precision 23、performance 8）、common 21、training/mindspeed-llm 15、training/verl 7、inference/sglang 1 |
| 先验词条（reference） | 268 条 | software-facts 65、tools 50、methodologies 43、platform-facts 33、fault-patterns 31、errors 21、env-vars 19、compat-matrices 4、command-side-effects 2 |

`knowledge/_index.yaml` 与读侧视图由合入 main 后的自动任务重建。读侧视图按命名空间与问题类别切分。PR 只交源文件。

## 沉淀与演进

沉淀入口有四个：

- `issue-ingest` 导入上游 issue。
- `reference-ingest` 导入官方文档仓。
- `to-postmortem` 接收内联、文件或目录来源。
- `to-reference` 沉淀先验词条。

草稿进 `postmortems/inbox/`。例行维护（groom）做预分诊、升格与去重。置信度按时间衰减，过期 case 软退休。`agent-groom` 做语义比对与合入前复核。

`evolve-check` 在内容流程收尾做伴随评估。`self-evolve` 做全库深度轮。`skill-review` 审视 skill 质量。改进项卡（`proposals/ideas/EV-*.yaml`）有 184 张。判定分为符合、被证伪、无法判定三态。预测要么带一条可复跑命令，要么声明不可度量。创建时间在 2026-09-11 之前的卡按当时规则豁免。

`eval/golden` 有 28 条回归夹具。`eval/holdout.yaml` 按内容哈希封存 11 条对照样本。另有校准集、流程池、交互面样本与观测账本。元层评测台做配对检验，`ev_measure.py --run` 复核单张卡。

`metrics/timeline.yaml` 有 8 期读数。范围是 2026-W35 至 W37。阈值与可解读性下限在 `metrics/gates.yaml`，由脚本读取。

## 交互与工程

系统有 13 个面向使用者的 skill。按场景分四组：日常问答、日常诊断、知识沉淀、维护与演进。`doc-standards` 为内部使用，不计入 13 个。

DeepSeek Harness（DSH）界面提供以下内容。面板包、诊断状态条、诊断画布与 vllm-kb 四个包分开装卸。

- 会话内「诊断」tab 显示本次诊断的轨迹、证据与成本。
- 侧栏整页「Ascend Sleuth」承载知识库、指标与自演进。
- 诊断状态条与「诊断工作台」给出下一步可执行指令。
- 诊断画布把一次诊断按阶段展开成事件图。
- vllm-kb 接入插件提供检索与截图转文字。

仓库有 3 个 GitHub workflow。`kb-checks` 有 16 个 job，覆盖索引、知识校验、指标与面板检查。测试文件 69 个（`tests/test_*.py`）。Python 脚本 108 个。

部署支持集中式或作为框架 fork，知识目录不随上游合并。Windows 上由安装脚本修复 `.dsh/skills` 符号链接。修法见 `docs/guide/windows-setup.md`。

## 已知限制

- 最近一期指标快照是 2026-W37-live（2026-09-10）。该期反馈捕获（`feedback_capture`）为 0。命中率、误诊率与归因比不可解读。之后没有新的周批读数入库。
- `training/mindspeed-mm` 仍为空。部分命名空间、问题类别与平台组合的 case 数少。未覆盖处走空库提示与 Tier 3 兜底，属设计预期。
- `CODEOWNERS` 仍是示例文件，分支保护未启用。例行维护尚未形成持续周批。这是冷启动阶段（Phase 0）剩余的出口条件。
- reference 层容量治理参数未定，自动变更的可逆性未实现。
- prompt 纪律是概率性的。换 agent 或换会话，诊断结论与 trace 质量可能不同。团队内建议统一 agent。

## 安装

```bash
git clone https://github.com/pillumina/ascend-sleuth.git
cd ascend-sleuth
python3 scripts/enable_agent_skills.py
```

仓库已跟踪 `.dsh/skills` 符号链接。clone 后 DSH 可直接发现 skills。环境自检：`python3 scripts/doctor.py`。Windows 安装见 `docs/guide/windows-setup.md`。
