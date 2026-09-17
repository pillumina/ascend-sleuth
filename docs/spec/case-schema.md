# case schema（`knowledge/<ns>/` 的 case 字段定义）

> **给谁读**：写或改 case 的人（`to-postmortem` 产出、groom 升格/合并/退休、诊断时读候选本体的人）。
> **什么时候读**：你要新增一条 case、改一条 case 的字段、或要解释某个字段的口径时。
> **读完能做什么**：知道每个字段是给谁用的、哪个口径只承载一种证据、以及哪些内容不允许进库。

> **权威处说明**：本文是 case schema 的权威处（原先这段写在 `CLAUDE.md` 里）。常驻指令只保留
> "每次都要遵守"的约束与指路，字段级细节属于"写/改 case 那一刻才需要"的内容，按
> `CLAUDE.md` 的取舍规则移到这里。canonical 示例见 `examples/sample-case.yaml`。

Each case file has: `id`, `title`, `category` (interrupt|precision|performance), `tags`, `platforms`, `compat` (multi-dimensional: framework/CANN/HDK version ranges), `confidence` (hits/misdiagnoses/score managed by groom — **只承载 S1 现场 resolve 口径**), `symptoms`, `quickly_check` (primary + fallback regex), `diagnosis` steps with `command_template`/`expected`/`fix_on_mismatch`/`rollback`, `severity` (benign|service-affecting|data-loss-risk), `fix_type` (env-var|config-change|code-patch|pending-investigation), `root_cause`, `fix`. Canonical sample: `examples/sample-case.yaml`.

Optional field — `source_session`: 该 case 由哪个诊断 session 沉淀而来（如 `2026-09-16-12430-dsv4pro-mc2`）。用途只有一个：**反馈结算时判定「自证」**——来源 session 自己回报的 resolve 记入 `confidence.self_resolved`（见下），不计入 `hits`。缺该字段时结算退回原行为（计入 hits），这是刻意的保守取舍：宁可少识别自证，不误判独立命中。

`confidence.self_resolved`: {count, last, examples} — **来源 session 自己的 resolve 累积**（自证）。与 `hits` 分开的理由：`hits` 的口径是「这条知识的**消费者**环境是否解决」，而来源 session 是产地——同一份证据不能数两次（`docs/spec/design-theory.md` 的「独立性假设过强」即指此）。与 S2 的 `validation_record.self_consistent` 同一条纪律：如实标注、不虚增。由 `scripts/settle_trace_feedback.py` 结算。

Optional field — `validation_record`: {consistent, inconsistent, self_consistent, last_verified} — 内容被**外部验证**的累积记录（由 `scripts/settle_s2_feedback.py` 结算，非人设定）。与 confidence 分开：S2 issue-replay 对照的是外部 ground truth（issue resolution / 维护者 fix PR / committer 确认）。`consistent`=外部验证一致（同等 score 下排序优先）——语义是「该 issue 既不是它的来源、也未在正文被引用」，**不是**「信息独立」（case 与样本出自同一族判词/同一 fix PR 的关联无法机械识别，这点是半硬的）；`self_consistent`=非独立命中，两种：replay issue 即 case 来源（自证），或 replay issue 在 case 正文里被引用（是该 case 的撰写依据——命中结论就是写 case 时从它那儿读来的，记 consistent 等于一份证据数两次）；`inconsistent`=命中但结论与 resolution 不符（复审信号）。无 S2 验证不填。

Optional field — `source_ref`: {repo, ref, file, line} — 根因定位到源码时的代码位置。**「源码不落库」= 源码不随仓库提交、也不写进知识库**——`.gitignore` 已忽略 `src-code/`（本地分析缓存，**按版本平铺**为 `src-code/<org>/<repo>/<tag>/`：版本目录自包含、互不干扰，多 agent 并发可各读各版本；缓存根锚到**主检出**，同一克隆的所有 worktree 共读共写，worktree 清理不丢；统一走 `scripts/src_fetch.py <repo> --ref <tag>` 按需拉取、同版本复用）。知识库只记结论 + `source_ref` 指针。「不落库」≠ 分析不需要源码，深入排查**仍要 clone**。ref 用触发版本对应的 commit/tag（与版本目录名同 token）。

Optional field — `ref_knowledge`: 指向前验层词条的结构化关联，每条是 `ref: <reference-id>` + `role: signature-source | fix-methodology | root-cause-context`。`ref` 必须存在、`role` 必须合法，由 `scripts/verify_references.py` 校验。反向视图（哪些 case 引用了某词条）由该脚本派生，绝不存到词条侧——一条关系只存一次。

Version matching is **soft**: compat mismatch downgrades confidence but never hard-excludes a case. Undefined dimensions are skipped.
