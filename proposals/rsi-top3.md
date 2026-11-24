# 提案：落地自演进优化算法 top-3（定向批评 / 提案摘要 / 留一审计）

状态：提议（2026-11-24）

本文落地 `docs/research/rsi-algorithms.md` §5.3 修订后推荐排序的前三名。三项都不引入新的评测循环框架：①②落在提案契约层（`proposals.request()` 的输入构造），③落为独立的审计状态机。读者是评审这项改动的人。

## 要解决什么问题

GEPA 已实现，但它的 propose 是「整体反思」——把候选在全部样本上的表现笼统交给 reflect subagent，批评没有落点。三个缺口：一是失败样例的具体差异（期望什么、实际什么）进不了提案 prompt；二是提案 agent 看不到「候选池里已有什么、数据长什么样」，容易重复提出已有方向；三是知识与候选只增不减，冗余条目稀释检索排序，没有机制发现它们。

## 选哪条路

三项分别对应三个缺口，都选「机制来自广泛认可的工作、实现走已有协议」：

1. **定向批评改写（ProTeGi，EMNLP 2023 Main）**：`request()` 增加可选 `failures` 输入（逐样例的期望/实际/反馈），prompt 拼装出「对具体失败样例的定向批评」节；`stages.py` 登记 `propose.critique`，`pipelines.yaml` 登记 `critique` 预设（`select.pareto` + `propose.critique`）。放弃的替代：完整 beam search + minibatch 调度（ProTeGi 原文设计）——那是面向千级评测的，本仓几十样本下 minibatch 常无失败可提，先落批评机制，调度待失败样例供给验证后再加。
2. **提案摘要输入（MIPROv2 的做法，第三方 EACL 2026 Findings 验证）**：`request()` 增加可选 `digest` 输入（data_digest：样本/数据的结构化摘要；program_digest：候选池现状摘要），拼进 prompt 的上下文节。不搬 MIPROv2 的贝叶斯搜索——几十样本下组合数受限，只吸收输入构造。
3. **留一效用审计（SkillProx 的机制，设计参考 + 自证）**：新建 `scripts/evolve/loo.py` 审计状态机（纯 Python，与 `GepaSession` 同款协议：`next_action` 返回 `{kind, payload}`）+ `evolve loo init/next/apply/result` CLI 组。基线全量评测一遍，逐单元消融一遍，`效用(u) = 基线 − 去掉 u`，负效用进收缩队列（附证据），收缩执行走正常知识 PR，不在审计循环内。出处未经广泛认可，故审计集与训练集分离（holdout 方向取）、低频执行写进 skill 约束。

三项共用 evolve-drive 的驱动循环——命令组按算法入口区分是已声明的扩展点，本 PR 增补 `loo` 映射。

## 怎么算完成

- `python3 -m unittest tests.self_evolution.test_loo tests.self_evolution.test_proposal_request` 全部通过：LOO 覆盖全消融 → 效用计算 → 收缩队列排序 → 预算耗尽 stop → 超预算回写报错；request 覆盖 failures/digest 拼装、与既有契约并存。
- 预设可解析：`pipeline_for(cfg, "critique")` 六点全落到已注册 stage。
- skill 正文增补 `loo` 命令组映射，自包含检查过（无 ADR 号/日期/EV 卡号）。

## 不做会怎样

提案质量继续受「无落点的整体反思」限制；候选池重复方向无人拦截；知识库冗余堆积到检索排序被稀释后才被人工发现，届时已无法归因是哪条条目的问题。
