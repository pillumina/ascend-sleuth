# 源码仓目录（source-catalog.d）

这里存"哪个仓在哪、怎么找到它"，是 `scripts/src_fetch.py` 的唯一数据来源。消费方与校验器是
`scripts/source_catalog.py`，按版本取源码、缓存与退出码契约仍在 `scripts/src_fetch.py`。

## 为什么是目录

一个层一个文件。补一个仓只改一个层文件，两个人同一天补不同层不会撞行；仓库根的
`.gitattributes` 给 `source-catalog.d/*.yaml` 配了 `merge=union`，同层各补一个仓时两边都留住。
放这里而不是 `references/`：这是工具读的配置，要被 schema 校验，不是先验知识词条。

## 补一个仓

1. 在对应层文件的 `repos` 加一条：canonical 名、`sources`（host 与 owner/repo，私有仓用
   `host: custom` 加 `url`）、可选 `aliases`、`why`。
2. 若报错签名会直接点到它，加 `discover`（`all_of` / `any_of` / `primary` / `discriminators` /
   `fallback`），并在 `self_test` 加一条真实签名到期望仓。`self_test` 里的组织必须在 `orgs`
   里声明（加载时跨层合并）。
3. 跑 `python3 scripts/src_fetch.py --self-test`。结构错与签名不命中都会在这里报红。

新增层的信号来自诊断：同一类"找不到仓"出现两次以上，再由演进记录成改进项补数据，不在诊断里
直接改。`discover` 写坏或缺失时的表现是**静默零候选**，看起来像上游没有这个仓；只有自测会
明确报错。

## 字段

| 字段 | 位置 | 含义 |
|---|---|---|
| `layer` / `title` | 文件顶 | 层名（也是 `--list` 的分组名）与一句说明 |
| `orgs[].name` / `host` / `enumerable` | 文件顶 | 组织、目标 host、公开仓清单能否匿名枚举（GitCode 可以） |
| `repos[].repo` | repos | canonical 名，`org/repo` |
| `repos[].sources` | repos | 有序候选源，前面的取不到才回退；`host` 取 `github` / `gitcode` / `gitee` / `custom` |
| `repos[].aliases` | repos | 额外可命中的写法（canonical 自动可命中，不用重复写） |
| `repos[].fast_path` | repos | 默认 `true`；`false` 表示只参与签名候选，不进已知表 |
| `repos[].why` | repos | 给人看的层说明，会出现在候选表里 |
| `repos[].discover` | repos | 签名规则：`all_of` 全中、`any_of` 任一、`primary` 整词命中才算主候选、`discriminators` 命中即非兜底、`fallback` 兜底标记 |
| `self_test[]` | 文件顶 | `{sig, expect}`；`expect` 必须是本层仓，组织的默认值取自 `expect` 的前缀 |

关键词一律小写（大写不会报错，只会静默不匹配，自测会拦）。规则里的 `all_of` 与 `any_of` 至少
写一个；写空等于不命中。
