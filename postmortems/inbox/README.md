# inbox/ —— 待审知识队列（intake）

`/skill:to-postmortem` 的新产出落这里（`<case-id>.md` + `<case-id>.case.yaml` 草稿）。
不直接进正式季度目录——那是审完后的事。

## 语义

- **本目录是队列，不是档案**：每周 `/skill:knowledge-groom` 批处理清空（三分类 new_pattern / variant_of / covered_by，见其 SKILL.md）
- 停留 >2 周的条目在 groom 变更摘要里标红提醒
- **covered ≠ 丢弃**：postmortem 照样转正到 `../YYYY-QN/`（Tier 3 语料），只是不升格 Tier 2
- 诊断时 Tier 3 的 `rg` 检索会自然扫到本目录（可用，但内容未经人审，引用时标注）

## 为什么是队列而不是即时审

持续汇入（200~400 篇/年）下，"定位完顺手审知识"反工程师节律。批处理 + 周节律才可持续：
预分诊（agent）负责排序注意力，人只做 accept / adjust / reject，~30 秒/条。
设计论证见 [docs/adr/0002](../../docs/adr/0002-retrieval-no-rag-lightweight-index.md)。
