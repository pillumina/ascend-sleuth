# to-reference dogfood 2：环境变量数据集导入（ascend-log-triage）

> 测试日期：2026-08-28。材料：`~/ascend/ascend-log-triage/knowledge/04_envvar/`（CANN 环境变量参考，envref 系列 + envvar.tsv 索引，108 个变量、21 个模块）。
> 方法：按 `skills/to-reference/SKILL.md` 的 official-doc 文件导入流程，提炼环境变量为**数据集（表）**形态。
> 目的：①检验数据集形态扩展到新 type（env-var-table）；②检验 skill 的文件导入模式；③发现提炼质量问题。

## 一、产出（2 个表草稿 → `references/env-vars/`，draft）

| 表 | 变量数 | 内容 |
|---|---|---|
| `hccl-debug-env.yaml` | 4 | HCCL 调试：HCCL_DEBUG_CONFIG / HCCL_DFS_CONFIG / HCCL_DIAGNOSE_ENABLE / HCCL_ENTRY_LOG_ENABLE |
| `hccl-network-env.yaml` | 10 | HCCL 网络：网卡选择（SOCKET_IFNAME）/ RDMA 配置 / 端口范围 |

来源：CANN 环境变量参考（official-doc，envref URL 有来源）；全部 `status: draft`，`verify_references.py` 通过（28 词条）。

## 二、type 渐进登记机制验证 ✅

- `_types.yaml` 登记 `env-var-table`（kind: table）——**复用 error-code 的表形态模式**（同一 kind: table，只是内容字段不同：errors vs variables）；
- `verify_references.py` 支持 env-var-table 校验（variables 非空、name 唯一、每变量 name/description 必填）——与 error-code 校验同构；
- **验证了"组织单元 = 验证单元"对数据集形态的通用性**：错误码和环境变量都是"同源同验证、按族成表"，同一套机制扩展。

## 三、skill 效果评估

### 能做什么（验证成立）

| 能力 | 证据 |
|---|---|
| 结构化数据源导入 | envvar.tsv（tsv）→ yaml 表，name/description/example 完整转换 |
| 数据集聚类 | 按模块（category）成表——同源同验证 → 一个模块一个表 |
| 零注释纪律 | 产出零注释行 ✓ |
| skill 自包含 | 产出零 ADR 编号 ✓ |
| schema 合规 | env-var-table 一次通过强校验 |

### 发现的提炼质量问题（2 个，已修）

| 问题 | 后果 | 修复 |
|---|---|---|
| **applies_to 平台靠 agent 猜** | 我初版写 A2/A3/A5 是推断——来源（tsv models 字段）只确认 A2/A3 + Atlas 350 加速卡，A5 是"HCCL 跨代"的经验判断 | **数据集类 applies_to 应从来源结构化字段（models/support）映射，不靠猜**——已写进 to-reference 归类节 |
| **长字段硬截断** | description 截到 400 字符产生"在第一…"不完整句子；example 截到 120 字符"task_" | **长字段不硬截断，语义完整性优先**——已写进 to-reference 提取节；产出重新生成 |

## 四、结论

**数据集形态 + type 渐进登记机制成立**——error-code 的表模式干净复用到 env-var，机制无需新造。skill 的 official-doc 文件导入模式可用（tsv → yaml 表一次成功）。

**2 个提炼质量问题暴露了 skill 的真实盲区**：①applies_to 的出处纪律（该从来源映射而非 agent 推断）；②长字段的语义完整性（硬截断制造残缺信息）。都已固化进 SKILL.md——这印证了 dogfood 的价值：**真实材料导入比构造测试更能暴露提炼质量问题**。

**局限（诚实）**：只提炼了 108 个变量中的 14 个（2 个模块）——剩余 19 个模块可后续按需分批导入（表形态支持增量追加，符合"追加不新建"）。310P 是否适用 HCCL 变量未在 sources 确认，未写入 applies_to（诚实）。

## 五、审阅建议

2 个表草稿待 maintainer 审核（accept → active）：优先审 `hccl-debug-env`（HCCL 调试与诊断最相关）；`verified_by_testing` 对 env-var 表不适用（官方文档事实，非方法论）。