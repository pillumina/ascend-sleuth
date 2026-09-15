# 文档语料 → reference 的导入管道

上游**文档仓**里有大量真正专业的昇腾知识（分级故障诊断手册、错误码参考、FAQ、调优指南），而它们不在案例库也不在先验库里。本管道把它们批量吸收成 `references/` 词条，与 `docs/issue-ingest-pipeline.md`（issue → case）并列。

- **执行规则**在 `skills/reference-ingest/SKILL.md`（何时扫、怎么筛、token 怎么省、批怎么收尾）——本文件只讲**机制**：状态文件为什么长这样、成本结构、失败模式。
- **产出规则**在 `skills/to-reference/SKILL.md`（归类、schema、grill、深审）——本文件不重复。

## 为什么独立于 `ingest-state.json`

两者的幂等单位不同，混在一份文件里会让两边的语义都变模糊：

| | issue 面（`ingest-state.json`） | 文档面（`reference-ingest-state.json`） |
|---|---|---|
| 单位 | 一条 issue（`number`） | 一个文件路径（`path`） |
| 幂等键 | issue 号（判过即封，永不重评） | **path × blob sha**（文件会变，变了就要重评） |
| 未沉淀的记账 | 没有这一半 | **必须有**：`skipped` + 理由 |

两条差异都是实测后果：只用 `path` 当键，上游改了一篇已经沉淀过的文档，第二轮既不会重抓也不会重判——**改动静默丢失**；不记 `skipped`，一个文档仓里 80% 的导航页/API 页每一轮都会被重新拿出来评估，重复烧 token（这正是 `skipped` 必须带 `--note` 的原因）。

## 两级判定：仓级 + 文档级

台账有**两个层级**的判定，各自回答不同的问题：

| 层级 | 字段 | 回答的问题 | 成本 |
|---|---|---|---|
| **仓级** | `sources[...].triage = {decision, note, at}` | 这个仓整体纳不纳入？（`selected` / `candidate` / `rejected`） | **零网络**——`triage` 子命令只写一行记录 |
| **文档级** | `sources[...].docs[path] = {sha, decision, refs}` | 这一篇沉不沉？（`harvested` / `skipped` / `pending`） | 需先 `scan`（拉全树）再逐篇判定 |

为什么要仓级：对**整仓不纳入**的仓（算子库/模板库、治理与竞赛、行业 SIG、agent 知识仓、框架适配仓），扫全树再逐文档标记是纯浪费——一个 500 篇文档的教学仓，扫+标记要几分钟，而结论早由仓的类别确定。仓级判定把"这个仓不纳入，理由是什么"变成一条**可审计**记录：下一轮选源时直接读它，不必再扫、不必再判。

两级**并存且互不覆盖**：仓级说"要不要看这个仓"，文档级说"这一篇沉不沉"。一个仓可以是 `selected`（纳入）而其中多数文档是 `skipped`（导航页/API 参考），这是常态。

## 状态文件 schema

```jsonc
{
  "version": 1,
  "sources": {
    "gitcode/cann/hccl": {
      "triage": {                          // 仓级判定（零网络，一次写完不再变）
        "decision": "selected",            // selected | candidate | rejected
        "note": "已按价值优先级纳入并完成沉淀",
        "at": "2026-09-15T17:52:11"
      },
      "branch": "master",
      "head_sha": "8cbf54d35a6d…",       // 最近一次扫描时的 commit（不是分支名）
      "last_scan": "2026-09-15T15:27:16",
      "docs": {
        "docs/zh/user_guide/fault_diagnosis/link_timeout_EI0006.md": {
          "sha": "826b0ffcc2…",           // git blob sha（内容哈希，用来判"变没变"）
          "decision": "harvested",         // pending | harvested | skipped
          "at": "2026-09-15T15:33:53",
          "refs": ["hccl-comm-init-and-link-faults"]   // 哪条词条消费了它
        }
      }
    }
  }
}
```

- **`head_sha` 必须是 commit**：GitCode 的 trees API 顶层 `sha` 字段返回的是 ref 名（实测 `{"sha": "master"}`），照抄会让"扫的是哪一版"不可判定、抓取缓存目录随分支漂移。取 commit 走 `/repos/{owner}/{repo}/commits?sha=<ref>`。
- **完整性判据是 git blob sha，不是目录树的 `md5`**：树的 `md5` 字段与文件内容对不上（同一文件三个 md5 互不相等），拿它校验会把每一篇都判成"抓到了页壳"。blob sha 可在本地重算（`sha1("blob <len>\0" + content)`），对"上游改过"与"抓到 HTML 页壳"两种真实事故都敏感。
- **写侧收口**：条目只保留 `sha/decision/at/refs/note` 五个字段；早期版本写过的废弃字段（如 `md5`）在下次写入时被自动清掉——让"状态里出现的字段"恒等于"当前有语义的字段"。
- 写入用临时文件 + `os.replace` 原子替换；`fetch`/`mark` 是 read-modify-write，**同一克隆内必须串行**（与 `ingest-state.json` 同一纪律）。

## 成本结构（token 节省是设计目标）

| 层 | 动作 | 成本 |
|---|---|---|
| ① 扫描 | `scan`：只拉目录树（路径 + blob sha），打印增量表 | 网络请求，**零模型 token** |
| ② 筛选 | 按路径判该页有没有判据，不要的 `mark skipped` | 一次决策，且只发生一次 |
| ③ 抓取 | `fetch`：只抓筛过的候选正文到 `ref-docs/` | 网络 + 磁盘；重跑复用缓存、不重抓 |
| ④ 抽取 | 剥日志码块后读正文；超大文档按标题跳读 | 本管道的主要 token 支出 |

第 ④ 层是唯一真正花模型 token 的地方，因此文档面的"省"来自前三层：**没价值的不读**（②）、**读过的不重读**（①③）、**读的时候把日志 dump 剥掉**（④）。正文缓存锚到主检出（`scripts/exec_log_path.py` 的 `resolve_ref_docs`，与 `src-code/` 同一条语义），多个 worktree 共读一份。

## 已知坑（都踩过）

| 现象 | 成因与处置 |
|---|---|
| 抓下来的"正文"通篇是导航与脚本 | `gitcode.com/<org>/<repo>/raw/<ref>/<path>` 返回 HTML 页壳；正文主机是 `raw.gitcode.com/<org>/<repo>/raw/<ref>/<path>`（脚本已用后者，并对页壳直接报错） |
| 目录树只返回 20 条 | trees API 默认每页 20，必须显式 `per_page=100` 并翻页（脚本已处理） |
| 每篇都报"内容 sha 不符" | 用了树的 `md5` 字段而非 blob sha（见上） |
| 缓存目录名叫 `master` | 把 trees API 顶层的 `sha` 当成了 commit |
| `scan` 之后候选表把同一批文件又列一遍 | 上一轮没有 `mark`（扫描游标更新不等于判定落账）——`pending` 会一直在；要么产出，要么 `skipped` + 理由 |
| 内嵌图（`figures/*.png`）内容丢失 | 文本通道只出文字；已提取的图要在 PR body 里如实声明未提取，评审者按需补 |
| 整族文档被静默漏掉（如英文独有的一族） | 按语言目录一刀切排除（曾默认排除 `docs/en/`）会把"只在 en 下"的文档全漏——实测 cann/runtime 的错误码参考就是这样；语言目录不是"重复内容"的同义词，真正的双语重复由**每源 config.exclude** 逐仓判定 |

## 与其他机制的关系

- **诊断消费**：词条落 `references/`（`status: active`）后进诊断阶段 2.5 的两个缺口点，与 case 层并列；本管道不改诊断流程。
- **演进**：批次收尾走 `/skill:evolve-check`；本管道自身的摩擦（筛不准、主题切分差、缓存失效）作为信号进 EV 卡。
- **人审**：与 issue 面不同，文档面的产出**没有 draft 中间态**——`status: active` 随 PR 提交，PR 合入即生效（`docs/adr/0008`）。因此 `verification` 要如实标：逐字核验过源才写 `cross-checked-source`，只做了一次性抽取就写 `auto-extracted`。
