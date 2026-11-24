#!/usr/bin/env python3
"""kb_sync.py —— 知识库读侧的同步入口（fetch / 条件合并 / 只读状态）。

诊断读的是本机检出的 `knowledge/`，而它可能落后上游几个提交。开单前同步一次，能把
候选集与 case 内容拉到较新的版本；是否合并另判，因为合并会改当前检出的 HEAD。

配置在主检出的 `.local/settings.json`（schema `ascend-sleuth-settings/1`，不进 git）：

    {"schema": "ascend-sleuth-settings/1",
     "sync": {"remote": "origin", "branch": "main", "enabled": true, "auto_merge": true,
              "check_enabled": true, "check_minutes": 30, "check_full_access": true},
     "identity": {"remote": "origin"},
     "target": {...}}

`identity.remote` 是归属仓（默认 origin）：同源比较拿它的 URL，写侧的比较基准也按它的默认
分支算，`sync.remote` 未显式配置时跟随它。归属仓显式配置却在本机解析不到时，合并前拦下
（reason `identity-unresolved`）。

配置文件缺失或读不出时用默认值（远端 origin、分支取当前分支上游（取不到则 main）、同步开），
结果里 `config: "default"`。失败结果缓存在 `.local/kb-sync-state.json`：自动同步在 10 分钟内
不重试，避免每次开单都等满超时。手动同步加 `--force` 跳过窗口立即重试（面板「立即同步」走这条），
否则刚失败过的网络在 10 分钟内点几次都只会拿回同一份缓存。

`sync.enabled` 只拦自动路径（开单时的自动 fetch 与自动合并）：`--check` 只 fetch、不合并，
也不看它；带 `--force` 的手动路径（`--merge --force`）同样不看它。后台提醒检查用 `--check`，
它的开关与间隔是 `sync.check_enabled`（默认 true）与 `sync.check_minutes`（默认 30，
夹在 5..720 之间）。后台检查的沙箱档位是 `sync.check_full_access`（默认 true）：true 时以
完全权限跑 `--check`（这条检查只 fetch、不改检出，但要读 git 凭据）；false 时跟随部署默认档。

`--check` 的 fetch 被权限拒绝（沙箱或文件权限写不进检出）时改用只读探测：`git ls-remote`
问远端分支的 sha，再用 `git merge-base --is-ancestor` 判它是否从本地 HEAD 可达，只能判出
远端有没有本地 HEAD 未包含的提交。结果里 `degraded` 非空、`degraded_error` 是 fetch 的
原始一行错误、`surface_known` 为 false。

`--no-write-fetch-head` 让权限失败从写 `FETCH_HEAD` 后移到对象写入：stderr 变成
`insufficient permission for adding an object` 与 `failed to write object`，归类要覆盖这条
路径，否则探测不会触发。该选项要 git 2.29 才有；老 git 报 unknown / unrecognized option
时去掉它重试一次（全仓没有 `FETCH_HEAD` 消费点）。

探测成功也把本次核对记为成功（`reason` 清空、`last_ok_at` 前移）；探测失败按
`permission-denied` 记失败。落后数、领先数与改动面都要先把提交取回本地才算得出，这一路
一律未知。

凭据类失败（认不出凭据，见 `reason` 的 `credential`）不算写权限拒绝，不做只读探测。
探测同样要凭据，重试只会再失败一次。它按 `credential` 记失败，`fetch_error` 取 ssh / git
的原因行；面板据此说"拿不到 git 凭据"而不是笼统的"fetch 失败"。

自动合并只在这些条件同时成立时发生：当前分支 = 配置 `branch`、HEAD 是远端分支的祖先、
`git status --porcelain -uno` 为空、无进行中 merge / rebase / cherry-pick。worktree 与
detached HEAD 不自动合并——合并会改当前检出的 HEAD，而 worktree 可能正被另一单使用。
同步源与归属仓不同源时同样只 fetch、不合并（reason `same-repo`）：合并会把另一个仓的
提交带进当前检出。归属仓显式配置却解析不到时也不合并（reason `identity-unresolved`）。

用法：
  python3 scripts/kb_sync.py --show          # 只读，不联网：配置、HEAD、本地远端 ref、上次核对
  python3 scripts/kb_sync.py --sync          # fetch；不合并
  python3 scripts/kb_sync.py --check         # 只 fetch、不合并；不看 sync.enabled（后台提醒检查用）
  python3 scripts/kb_sync.py --merge         # fetch，条件满足时试 ff-only
  python3 scripts/kb_sync.py --merge --force # 跳过失败缓存立即重试（手动同步用；也不看 sync.enabled）
  python3 scripts/kb_sync.py --show --json   # 所有子命令都可加 --json
  python3 scripts/kb_sync.py --sync --timeout 3 --root <检出>

结果里的稳定取值（文档与测试可直接断言）：
  ok       true / false
  reason   "" | timeout | network | credential | permission-denied | no-remote |
           not-a-repo | lock | exit-<n> | offline | disabled | dirty |
           branch-mismatch | not-ancestor | merge-in-progress | auto-merge-off |
           not-ff | same-repo | identity-unresolved
           credential = 认不出凭据：https 的 401/403 / Authentication failed、
           SSH 的 `Permission denied (publickey)` / `Host key verification failed.`
  fetch_error  本次 fetch 失败时 git 原始输出的一行（凭据类取 ssh / git 的原因行，其余取末条
           fatal / error 行；已抹掉 URL 里的凭据）；成功与 --show 时为空
  last_error   --show 时上次失败留下的同一条原文；没有失败记录时为空
  last_source  --show 时上次 fetch 的来源：check（后台提醒检查，含 `--check --force`）/
           manual（`--merge` / `--sync` 带 `--force` 的路径）/ auto（自动路径）；
           没有记录时为空
  merge    ff-only | none
  surface  各键计数：knowledge / routing / reference / methodology / panel / other；
           ff-only 合并成功时表示本次合并带进来的改动面，没有合并时表示本地落后于远端的改动面
  surface_known  false 表示 surface 计数不可用（只在 degraded 时出现）
  degraded  "" | permission-denied；--check 的 fetch 被权限拒绝并完成只读探测时非空
  degraded_error  fetch 的原始一行错误（degraded 非空时）
  update_available  true / false（degraded 时只读探测的结论：远端有没有本地 HEAD 未包含的提交）
  config   file | default
  enabled  true / false（settings 的 sync.enabled；--show 也照实给）
          只拦自动路径：--check 与带 --force 的手动路径不看它，结果里仍照实上报
  offline  true / false（sleuth.config.yaml 声明 sync.mode: offline）
  identity_remote     归属仓远端名（默认 origin）
  identity_url        归属仓解析到的 URL；取不到为空串
  identity_explicit   settings 里是否显式写了 identity.remote
  identity_resolved   归属仓在本机解析得到 URL
  same_repo           同步源与归属仓的 host+path 是否一致；取不到 null

退出码：0 = 已执行（含 fetch 失败、跳过、离线等降级）；2 = 参数不合法。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _kb_sync  # noqa: E402
from _kb_sync import *  # noqa: E402,F401,F403
from _kb_sync import DEFAULT_TIMEOUT, load_settings, local_snapshot, sync  # noqa: E402
from _cli import main_entry  # noqa: E402


def _positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"需要一个正数：{text}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError(f"需要一个正数：{text}")
    return value


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="知识库读侧同步：fetch / 条件合并 / 只读状态")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--show", action="store_const", const="show", dest="mode",
                      help="只读，不联网（默认）")
    mode.add_argument("--sync", action="store_const", const="sync", dest="mode",
                      help="fetch 远端分支")
    mode.add_argument("--check", action="store_const", const="check", dest="mode",
                      help="只 fetch、不合并；不看 sync.enabled（后台提醒检查用）")
    mode.add_argument("--merge", action="store_const", const="merge", dest="mode",
                      help="fetch 后按条件试 ff-only")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--force", action="store_true",
                    help="跳过失败缓存立即重试（手动路径；也不看 sync.enabled）")
    ap.add_argument("--timeout", type=_positive_float, default=DEFAULT_TIMEOUT,
                    help=f"单条 git 命令的超时秒数（默认 {DEFAULT_TIMEOUT:g}）")
    ap.add_argument("--root", default=None, help="仓库根（默认脚本上一级）")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    if not root.is_dir():
        print(f"kb_sync: 目录不存在 {root}", file=sys.stderr)
        return 2
    mode = args.mode or "show"
    if mode == "show":
        settings, config, config_error = load_settings(root)
        sync_cfg = settings["sync"]
        result = local_snapshot(root, sync_cfg["remote"], sync_cfg["branch"],
                                timeout=args.timeout, config=config,
                                config_error=config_error, enabled=sync_cfg["enabled"],
                                identity=settings.get("identity"))
    else:
        # 来源只服务"谁发起的这次 fetch"：面板据此分辨后台提醒检查与用户同步。
        source = "check" if mode == "check" else ("manual" if args.force else "auto")
        result = sync(root, do_fetch=True, do_merge=(mode == "merge"),
                      ignore_enabled=(mode == "check"), timeout=args.timeout,
                      force=args.force, probe_on_denied=(mode == "check"),
                      source=source)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_show(result) if mode == "show" else render_sync(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main_entry(main))

if __name__ == "kb_sync":
    # 兼容层：`import kb_sync` 与拆分前是同一个命名空间。调用方（含测试）会
    # `mock.patch.object(kb_sync, "run_git", ...)`，补丁必须打在库函数真正查的全局名上；
    # 只做 `from _kb_sync import *` 会复制一份绑定，补丁打不到库内部。
    _kb_sync.main = main
    _kb_sync.build_parser = build_parser
    _kb_sync._positive_float = _positive_float
    sys.modules[__name__] = _kb_sync
