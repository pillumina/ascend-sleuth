#!/usr/bin/env python3
# pr_status.py —— 提 PR 的目标（target）与每份草稿的 PR 记录（prs），带平台适配器派发
#
# 为什么需要它：队列停在「已提 PR · 合入未确认」之后，界面要回答两个问题——「提到哪」
# 与「合入没有」——而这两件事实都有多个写侧（agent 开完 PR 写记录、人手动确认、平台查询）。
# 让每个写侧各自手编 JSON 会漂移：字段名不一致、状态被推断、丢 checked_at。所以记录只有
# 这一个读写入口：原子写 + 文件字节 sha256 CAS，agent 不手编 JSON（设计 5.6、5.7）。
#
# 它做什么：
#   1. 记录读写（`<inbox>/.groom/pr-state.json`，共享 inbox，同一克隆的 worktree 共用）；
#   2. 列远端并识别平台（`--list-targets`，不探测网络）；
#   3. 写目标与 PR 记录（`--set-target` / `--set` / `--mark`）；删掉一条已关闭的
#      PR 记录（`--forget`，只有 `closed` 可以删，撤销沉淀时用）；
#   4. 按 PR URL 的 host 查状态（`--check` / `--check-all`）。状态只由平台查询或人手确认
#      更新，不由「分支是否存在」「commit 是否在 main」推断（设计 5.6）。`--check-all`
#      把记录里同一 PR 的多份草稿合并成一次查询，查到的状态分发给组内每份。
#
# 平台适配两层（加平台不改本文件，设计 5.8）：
#   - 声明式：`scripts/platforms/<id>.yaml`，REST + token；本文件用 urllib 执行；
#   - 可执行：`scripts/platforms/<id>.py`，暴露 ID/NAME/HOSTS/REQUIRES/check()/create_hint()/
#     可选 selftest()。本文件用 importlib 加载，**import 时不跑子进程**——只有 check() 跑 CLI。
#
# 输出纪律：每条命令都往 stdout 写一份 UTF-8 JSON（--json-lines 除外；末尾一个换行）。
# 业务失败（无适配器、无 token、网络错、CAS 冲突）`ok:false` 且退出 0（调用方只看 ok）；
# 参数错误退出 2。**任何路径都不打印 token**：HTTP 错误信息里的 query 值一律打码。
#
# --json-lines 契约（只给 --check-all 用，与 --json 互斥；默认输出不变）：
#   1. 每查完一条立刻打一行并 flush：
#      {"type":"row","draft":…,"ok":bool,"state":…,"checked_at":…,"error"?:<code>,"message"?:<失败原文>}
#   2. 全部查完并落盘后打最后一行，与 --json 的最终载荷同形、只多一个 type：
#      {"type":"done","ok":bool,"checked":[…],"ledger"?:{…},"sha256"?:"…","error"?:{"code","message"},
#       "write_failed"?:true}
#      成功时 sha256 是字符串；E_CHECK_PARTIAL / E_CAS / E_LEDGER 都在 error 里给 code 与 message；
#      write_failed 只在落盘被系统拒绝（E_LEDGER）时出现，面板据此给可复制指令。
#   3. row 的行序是查询完成序；done 里 checked[] 仍是草稿键序（与 --json 相同），面板以 done 为准。
#   4. 未预期异常（E_INTERNAL）与参数错误（E_ARGS）不在 done 行里。E_ARGS 出现在任何 row 之前；
#      E_INTERNAL 可能出现在已打出的 row 之后。两者都是**一行 compact JSON**（不含 type，退出码不变），
#      读端按「最后一段行首 { 到末尾」整体解析一次即可还原 error.code / message。
#
# 用法：
#   python3 scripts/pr_status.py --root <repo> --json
#   python3 scripts/pr_status.py --root <repo> --list-targets
#   python3 scripts/pr_status.py --root <repo> --set-target --remote origin --base main
#   python3 scripts/pr_status.py --root <repo> --set-identity --remote team
#   python3 scripts/pr_status.py --root <repo> --set --draft <key> --url <url> [--remote origin]
#       （平台、仓库、编号从链接解析；显式给 --platform / --repo / --number 时以给出的为准）
#   python3 scripts/pr_status.py --root <repo> --mark --draft <key> --state merged
#   python3 scripts/pr_status.py --root <repo> --forget --draft <key>
#   python3 scripts/pr_status.py --root <repo> --check --draft <key>
#   python3 scripts/pr_status.py --root <repo> --check-all
#   python3 scripts/pr_status.py --root <repo> --list-platforms
#   python3 scripts/pr_status.py --root <repo> --selftest gitcode
#
# 退出码：0 正常（含业务失败）；2 参数错误；1 未预期异常。

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _pr_status  # noqa: E402
from _pr_status import *  # noqa: E402,F401,F403
import kb_sync  # noqa: E402  （build_parser 的 help 读提醒检查区间）
from _pr_status import (  # noqa: E402  （CLI 自己的错误路径与兼容层要用的私有名）
    EXIT_ERROR, EXIT_OK, LedgerError, _arg_fail, _fail, _print_json_line, _resolve_root,
)
from _cli import main_entry  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="提 PR 目标与 PR 状态记录（只写本地 PR 记录）")
    ap.add_argument("--root", default=None, help="ascend-sleuth 检出根；默认当前目录")
    ap.add_argument("--json", action="store_true", help="输出 JSON（所有命令都输出 JSON，保留兼容）")
    ap.add_argument("--json-lines", action="store_true", dest="json_lines",
                    help="配合 --check-all：每查完一条输出一行 JSON，最后输出汇总行（契约见文件头）")
    ap.add_argument("--only-draft", action="append", default=None, metavar="KEY",
                    help="配合 --check-all：只查这些草稿键（可重复）；不传则查全部")
    ap.add_argument("--expect-sha256", default=None,
                    help="写前 CAS 令牌：--set-target / --set / --mark / --forget / --check 用记录 sha256，"
                         "--migrate / --set-sync / --set-identity 用 settings 的 sha256")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--list-targets", action="store_true", help="列远端、平台与推荐目标")
    group.add_argument("--set-target", action="store_true", help="写 target 段")
    group.add_argument("--migrate", action="store_true", help="把旧记录的 target 搬进 settings")
    group.add_argument("--set-sync", action="store_true", dest="set_sync",
                       help="写 settings 的 sync 段")
    group.add_argument("--set-identity", action="store_true", dest="set_identity",
                       help="写 settings 的归属仓（identity.remote）")
    group.add_argument("--set", action="store_true", dest="set_pr", help="写/覆盖一份草稿的 PR 记录")
    group.add_argument("--mark", action="store_true", help="人手确认 PR 状态")
    group.add_argument("--forget", action="store_true", help="删掉一份已关闭的 PR 记录（其余状态拒绝）")
    group.add_argument("--check", action="store_true", help="按平台查一份 PR 的状态")
    group.add_argument("--check-all", action="store_true", dest="check_all", help="查所有 open/unknown 的 PR")
    group.add_argument("--list-platforms", action="store_true", dest="list_platforms",
                       help="列平台适配器与依赖状态")
    group.add_argument("--selftest", default=None, metavar="PLATFORM",
                       help="适配器自检（不联网）")
    # --set-target / --set-sync
    ap.add_argument("--remote", default=None)
    ap.add_argument("--branch", default=None)
    ap.add_argument("--base", default=None)
    enable_group = ap.add_mutually_exclusive_group()
    enable_group.add_argument("--enable", action="store_true", help="sync.enabled = true")
    enable_group.add_argument("--disable", action="store_true", help="sync.enabled = false")
    ap.add_argument("--auto-merge", choices=("on", "off"), default=None,
                    help="sync.auto_merge 开关")
    ap.add_argument("--check-reminders", choices=("on", "off"), default=None,
                    dest="check_reminders", help="sync.check_enabled 开关（后台提醒检查）")
    ap.add_argument("--check-full-access", choices=("on", "off"), default=None,
                    dest="check_full_access",
                    help="后台提醒检查是否以完全权限运行（on 默认 / off 跟随部署默认档）")
    ap.add_argument("--check-minutes", type=int, default=None, dest="check_minutes",
                    help=f"sync.check_minutes：提醒检查间隔（分钟，"
                         f"{kb_sync.CHECK_MINUTES_MIN}..{kb_sync.CHECK_MINUTES_MAX}）")
    ap.add_argument("--note", default="")
    ap.add_argument("--labels", default=None, help="目标标签映射，JSON 对象")
    # --set
    ap.add_argument("--draft", default=None)
    ap.add_argument("--platform", default=None)
    ap.add_argument("--repo", default=None)
    ap.add_argument("--number", default=None)
    ap.add_argument("--url", default=None)
    ap.add_argument("--state", default=None)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.json and args.json_lines:
        return _arg_fail("--json 与 --json-lines 互斥")
    if args.json_lines and not args.check_all:
        return _arg_fail("--json-lines 只配合 --check-all 使用")
    try:
        root = _resolve_root(args.root)
    except NotADirectoryError as exc:
        return _arg_fail(str(exc))
    try:
        if args.list_platforms:
            return cmd_list_platforms(root)
        if args.selftest:
            return cmd_selftest(root, args.selftest)
        if args.list_targets:
            return cmd_list_targets(root)
        if args.set_target:
            return cmd_set_target(root, args)
        if args.migrate:
            return cmd_migrate(root, args)
        if args.set_sync:
            return cmd_set_sync(root, args)
        if args.set_identity:
            return cmd_set_identity(root, args)
        if args.set_pr:
            return cmd_set(root, args)
        if args.mark:
            return cmd_mark(root, args)
        if args.forget:
            return cmd_forget(root, args)
        if args.check:
            return cmd_check(root, args)
        if args.check_all:
            return cmd_check_all(root, args)
        return cmd_status(root)
    except LedgerError as exc:
        if args.json_lines:
            # 记录读坏发生在任何 row 之前；仍折成一行 compact JSON，与 E_INTERNAL 同形。
            _print_json_line({"ok": False, "error": {"code": "E_LEDGER", "message": str(exc)}})
            return EXIT_OK
        return _fail("E_LEDGER", str(exc))
    except Exception as exc:  # 未预期异常也走 JSON，调用方不用解析 traceback
        message = f"{type(exc).__name__}: {exc}"
        if args.json_lines:
            # 可能已经打过若干 row：这里必须是一行 compact JSON，面板才能从行尾整段还原。
            _print_json_line({"ok": False, "error": {"code": "E_INTERNAL", "message": message}})
            return EXIT_ERROR
        return _fail("E_INTERNAL", message, exit_code=EXIT_ERROR)


if __name__ == "__main__":
    raise SystemExit(main_entry(main))

if __name__ == "pr_status":
    # 兼容层：`import pr_status` 与拆分前是同一个命名空间。调用方（含测试）会
    # `mock.patch.object(pr_status, "PLATFORMS_DIR"/"save_ledger"/"_run_check", ...)`，
    # 补丁必须打在库函数真正查的全局名上；只做 `from _pr_status import *` 会复制一份绑定，
    # 补丁打不到库内部。
    _pr_status.main = main
    _pr_status.build_parser = build_parser
    sys.modules[__name__] = _pr_status
