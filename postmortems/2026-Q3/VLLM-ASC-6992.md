# VLLM-ASC-6992: 中文语言环境（非英文 OS）下 CPU binding 解析失败——子进程输出本地化，需强制 C locale（PR #8251）

> 源是结构化 GitHub issue 线程（结构化外部文档，issue 本体薄、由 PR review 转来），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest r2-sed-g1（2026-09）产出，进 inbox 待 groom 分诊；不改正式 knowledge/ 目录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/6992
**fix 跟踪**：PR #8251 [BugFix] Enforce C locale for CPU binding subprocess parsing（merged 2026-04-16 wangxiyuan，Fixes #6992；承接未合入的 #7274 并吸收 review 意见）；issue 同日 wangxiyuan 关闭 completed
**时间**：2026-03-04（报）~ 2026-04-16（关）
**框架/平台**：vllm-ascend（CPU binding 功能，`vllm_ascend/cpu_binding.py`）；OS 语言非英文（中文）环境
**category**：interrupt
**investigation_quality**：low-medium（issue 无复现日志/错误签名，机制由 merged PR 的代码改动说明支撑；无 before/after 现场闭环）
**verification**：upstream-fix-merged（fix PR #8251）
**novelty**：new_pattern——库内无 CPU binding/locale 相关 case

## 现象摘要

操作系统语言为中文等非英文时，开启 CPU binding（`--additional-config '{"enable_cpu_binding": true}'`）可能失败：`vllm_ascend.cpu_binding.execute_command()` 用 `subprocess.Popen()` 执行并解析 `ps` 等命令的输出，非英文 OS 下输出被本地化 → 解析不稳定/失败（issue 未附具体报错日志，标题即"may fail"）。

## 一句话根因

CPU binding 的子进程命令解析依赖英文输出，但只设 `LANG=C` 不够——继承的 `LC_ALL`/`LC_MESSAGES` 会覆盖它；中文等本地化环境解析失败。fix 在 spawn 前把 `LC_ALL/LANG/LC_MESSAGES` 三者都强制为 `C`（PR #8251）。

## fix

- 升级 vllm-ascend 到含 PR #8251 的版本（main 2026-04-16 合入；后续发布版，groom 回填首版号）。
- 旧版本 workaround：启动前 `export LC_ALL=C LANG=C LC_MESSAGES=C`（三个都要设，只设 LANG 会被 LC_ALL/LC_MESSAGES 覆盖——这正是 #7274 被 review 打回的原因）。
- 判别：OS locale 非 C/英文 + 开启 cpu binding → 先按本 case 处理，勿查核心绑定逻辑。

## 弯路与级联

- 只设 `LANG=C` 无效：`LC_ALL`/`LC_MESSAGES` 优先级更高（#7274 的教训）。
- issue 无报错日志：这是"中文 OS + 新功能"类用法坑，靠环境判别而非错误签名。

## 建议 triage 路由症状

无特有错误签名，启动失败已被 inference_interrupt 正则覆盖；可选补 `cpu binding`（needs-review）。
