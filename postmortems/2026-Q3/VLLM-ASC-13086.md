# VLLM-ASC-13086: vllm-ascend 0.14.0rc1 不支持 A5(950)（check_ascend_device_type 断言失败，需升级最新/rc 版本）

> 源是 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/13086
**fix 跟踪**：无 PR；官方确认"早期版本不支持 Ascend 950，请使用最新版本或 rc 版本"，issue 标 wontfix
**时间**：2026-07-29 ~ 2026-07-31
**框架**：vllm-ascend 0.14.0rc1（失败）
**平台**：A5-950
**category**：other
**investigation_quality**：low
**批量导入**：docs/eval-reports/0001-vllm-ascend-batch-plan.md（Phase B 批量 to-postmortem）

## 结构化 case

草稿：`postmortems/inbox/VLLM-ASC-13086.case.yaml`（Tier 2 入库前待 groom 分诊）。

## 一句话根因

vllm-ascend 早期版本（实测 0.14.0rc1）不支持 A5(950) 芯片：worker 初始化时 `check_ascend_device_type` 断言当前设备类型 A5 与安装包声明类型 A3 不匹配而失败（`AssertionError: Current device type: AscendDeviceType.A5 does not match ...`，另一处报 `ValueError: Unsupported soc_version: AscendDeviceType.A5`）；A5 支持自后续版本/rc 起，升级即可。

## 弯路与级联

- 报错1 是 AssertionError（device type 不匹配），报错2 是 ValueError（Unsupported soc_version）——同一根因的两个出口，两个签名都可 grep。
- 官方确认 A5 后用户话题偏离到 conda/容器部署咨询（官方建议 Docker、A5 镜像当时未发布）——注意不要把部署形态问题与支持矩阵问题混在一起。
