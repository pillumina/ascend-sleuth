#!/usr/bin/env python3
"""重建全部生成物。

PR 只交源文件；本脚本是"生成物由谁写"的唯一实现：
  - 主干重建 job：合入后跑 `--check`，有 diff 就提交；
  - PR CI：跑默认模式，让后续检查读到一份与源一致的工作树；
  - 手动同步（没有合入后 job 的部署）：`--sync` 一条命令完成拉取、重建、提交、推送；
  - 本地复现：`python3 scripts/rebuild_generated.py --check`。

为什么用 `sys.executable` 而不是写死 `python3`：Windows 上 `python3` 常不存在
（装的是 `python` / `py -3`），CI 与本地跑同一个解释器可以少一类环境差异。
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

from _stdio import pin_utf8_stdio
from generated_plane import GENERATED_PATHS, is_generated

ROOT = Path(__file__).resolve().parent.parent

# 顺序按依赖从少到多：索引与 reference 索引互相独立，路由聚合最后。
BUILDERS = (
    "scripts/build_index.py",
    "scripts/build_ref_summary_index.py",
    "scripts/build_procedure_index.py",
    "scripts/build_error_gap_index.py",
    "scripts/build_triage_tree.py",
    "scripts/build_timeline.py",
    "scripts/build_entry_activity.py",
)

CHECKS = (
    ("scripts/build_index.py", ("--check",)),
    ("scripts/build_ref_summary_index.py", ("--check",)),
    ("scripts/build_procedure_index.py", ("--check",)),
    ("scripts/build_error_gap_index.py", ("--check",)),
    ("scripts/build_triage_tree.py", ("--check-sources",)),
    ("scripts/build_triage_tree.py", ("--check-coverage",)),
    ("scripts/build_triage_tree.py", ("--check",)),
    ("scripts/build_timeline.py", ("--check",)),
    ("scripts/build_entry_activity.py", ("--check",)),
)

COMMIT_MESSAGE = "chore: rebuild generated views"


def run(script: str, args: tuple[str, ...] = ()) -> None:
    cmd = [sys.executable, str(ROOT / script), *args]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        print(f"失败：{' '.join(cmd)}", file=sys.stderr)
        if p.stdout:
            print(p.stdout, file=sys.stderr)
        if p.stderr:
            print(p.stderr, file=sys.stderr)
        raise SystemExit(p.returncode)


def rebuild(with_checks: bool) -> None:
    for script in BUILDERS:
        run(script)
        print(f"生成 {script}")
    if with_checks:
        for script, extra in CHECKS:
            run(script, extra)
            print(f"检查 {script} {' '.join(extra)}")


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
    )
    if check and p.returncode != 0:
        print(f"失败：git {' '.join(args)}", file=sys.stderr)
        if p.stdout:
            print(p.stdout, file=sys.stderr)
        if p.stderr:
            print(p.stderr, file=sys.stderr)
        raise SystemExit(p.returncode)
    return p


def status_paths() -> list[tuple[str, str]]:
    """`-z`：路径含空格/非 ASCII 时不会被 git 加引号或转义。"""
    out = []
    chunks = git("status", "--porcelain", "-z").stdout.split("\0")
    i = 0
    while i < len(chunks):
        chunk = chunks[i]
        i += 1
        if len(chunk) < 4:
            continue
        code, path = chunk[:2], chunk[3:]
        if code[0] in ("R", "C"):
            i += 1  # 改名/复制在 -z 里还跟一条原路径
        out.append((code, path))
    return out


def fail(message: str) -> int:
    print(message)
    return 2


def sync(remote: str, main_branch: str, pr_branch: str, dry_run: bool) -> int:
    """手动同步：在 main 上拉取、重建、提交、推送。"""
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != main_branch:
        return fail(f"当前分支是 {branch}；手动同步要在 {main_branch} 上跑。先 git switch {main_branch}。")

    entries = status_paths()
    dirty = [(code, path) for code, path in entries if not is_generated(path)]
    generated = [(code, path) for code, path in entries if is_generated(path)]

    if dirty:
        print("工作区有未提交的非生成物改动；同步只提交生成物，先提交或 stash：")
        for code, path in dirty:
            print(f"  {code} {path}")
        return 2

    staged = [(code, path) for code, path in generated if code[0] not in (" ", "?")]
    if staged:
        print("生成物有已暂存的改动；先 git reset 这些路径，再重跑同步：")
        for code, path in staged:
            print(f"  {code} {path}")
        return 2

    untracked = [(code, path) for code, path in generated if code == "??"]
    if untracked:
        print("生成物目录有未跟踪文件；先确认它们可以删，再手动清理：")
        paths = []
        for code, path in untracked:
            print(f"  {code} {path}")
            paths.append(path)
        print("  git clean -fd -- " + shlex.join(paths))
        return 2

    if generated:
        print(f"丢弃本地已跟踪生成物的改动（共 {len(generated)} 个，之后会重建）：")
        for code, path in generated:
            print(f"  {code} {path}")
            git("checkout", "--", path)

    print(f"拉取 {remote}/{main_branch} ...")
    git("fetch", remote, main_branch)
    p = git("merge", "--ff-only", f"{remote}/{main_branch}", check=False)
    if p.returncode != 0:
        print("无法快进：本地分支与远端分叉，或还有未处理改动。先解决后再同步。")
        if p.stderr.strip():
            print(p.stderr.strip(), file=sys.stderr)
        return 2

    ahead = int(git("rev-list", "--count", f"{remote}/{main_branch}..HEAD").stdout.strip() or 0)
    if ahead:
        return fail(
            f"本地 {main_branch} 有 {ahead} 个未推送提交；先 git push 或处理这些提交，再跑同步。"
        )

    print("重建生成物 ...")
    rebuild(with_checks=True)

    changed = [path for _, path in status_paths()]
    if not changed:
        print("生成物与远端一致，无需提交。")
        return 0

    print("本次生成物变更：")
    for path in changed:
        print(f"  {path}")

    if dry_run:
        print("--dry-run：已拉取并重建，但不提交、不推送。")
        return 0

    if not pr_branch:
        # 先探一次远端可达与快进。分支保护/服务端规则只有真实 push 才会暴露；
        # 真 push 失败时提交已在本地，按错误信息里的恢复命令挪到分支。
        p = git("push", "--dry-run", remote, f"HEAD:{main_branch}", check=False)
        if p.returncode != 0:
            err = p.stderr or ""
            if "non-fast-forward" in err or "fetch first" in err:
                return fail("远端 main 在同步期间更新了；重跑一次同步即可。")
            return fail(
                f"{main_branch} 推不上去（连不上远端、没有权限，或不在快进位置）。加 --pr-branch <新分支名> 重跑，"
                "改成推一个只含生成物的分支，再在平台上开 PR（仅用于没有 generated-guard 的部署）。"
            )

    if pr_branch:
        p = git("switch", "-c", pr_branch, check=False)
        if p.returncode != 0:
            return fail(f"建分支 {pr_branch} 失败：可能已存在。换一个名字后重跑。")

    # 不在 `git add` 里逐条列路径：生成器可能产出一个当前不存在的目录（如某部署没有
    # entry-activity），逐条列会 pathspec 报错。先全加，再核对暂存内容只有生成物。
    git("add", "-A")
    staged = [path for path in git("diff", "--cached", "--name-only", "-z").stdout.split("\0") if path]
    not_generated = [path for path in staged if not is_generated(path)]
    if not_generated:
        git("reset", "-q")
        return fail("提交前发现非生成物被暂存（已撤销暂存）：" + "、".join(not_generated))

    git("commit", "-m", COMMIT_MESSAGE)
    print(f"已提交 {COMMIT_MESSAGE}")

    if pr_branch:
        p = git("push", "-u", remote, "HEAD", check=False)
        if p.returncode != 0:
            print("推送分支失败：检查网络/权限；提交已在本地分支上，可稍后重试 git push。", file=sys.stderr)
            if p.stderr.strip():
                print(p.stderr.strip(), file=sys.stderr)
            return 1
        print(f"已推送分支 {pr_branch}；在平台上开 PR 合入。")
        return 0

    p = git("push", remote, f"HEAD:{main_branch}", check=False)
    if p.returncode != 0:
        print("推送失败：远端在同步期间更新，或权限被拒。提交已在本地，先重试：", file=sys.stderr)
        print(f"  git push {remote} HEAD:{main_branch}", file=sys.stderr)
        print(f"若 {main_branch} 受保护，把这次提交挪到分支：", file=sys.stderr)
        print(f"  git fetch {remote} {main_branch}", file=sys.stderr)
        print("  git branch -f chore/rebuild-generated", file=sys.stderr)
        print(f"  git reset --hard {remote}/{main_branch}", file=sys.stderr)
        print(f"  git push -u {remote} chore/rebuild-generated", file=sys.stderr)
        print("  然后在平台上开 PR（仅用于没有 generated-guard 的部署）。", file=sys.stderr)
        if p.stderr.strip():
            print(p.stderr.strip(), file=sys.stderr)
        return 1

    print(f"已推送到 {remote}/{main_branch}。")
    return 0


def _identity_remote() -> str:
    """settings 的归属仓远端名；没有 settings 或读不出时回退 origin。"""
    try:
        import kb_sync
        settings, _config, _problem = kb_sync.load_settings(ROOT)
        return str((settings.get("identity") or {}).get("remote") or "origin")
    except Exception:
        return "origin"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="重建全部生成物（PR 不提交它们；主干 job 用 --check 后提交；无 job 的部署用 --sync）"
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="生成后再跑各生成器的覆盖/一致性检查（主干 job 用这个；失败即退出）",
    )
    ap.add_argument(
        "--sync",
        action="store_true",
        help="手动同步：拉取 main、重建、提交、推送（没有合入后 job 的部署用）",
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help="只打印生成物路径，不生成（守卫 / 文档 / 测试取清单用）",
    )
    ap.add_argument("--remote", default=None,
                    help="--sync 用的远端名（默认读 settings 的归属仓，取不到用 origin）")
    ap.add_argument("--main-branch", default="main", help="--sync 用的主分支名（默认 main）")
    ap.add_argument(
        "--pr-branch",
        default="",
        help="--sync 不直接推 main，改为新建并推送这个分支，再由人在平台上开 PR（仅用于没有 generated-guard 的部署）",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="配合 --sync：拉取并重建，但不提交、不推送",
    )
    args = ap.parse_args()

    if args.list:
        print("\n".join(GENERATED_PATHS))
        return 0

    if args.sync:
        return sync(args.remote or _identity_remote(), args.main_branch, args.pr_branch,
                    args.dry_run)

    rebuild(args.check)
    return 0


if __name__ == "__main__":
    pin_utf8_stdio()
    raise SystemExit(main())
