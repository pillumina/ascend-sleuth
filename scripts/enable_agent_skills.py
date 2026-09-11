#!/usr/bin/env python3
"""enable_agent_skills.py —— 关联 agent 与本仓库 skills/（项目级目录链接）

跨平台、幂等可重跑。替代原 enable-agent-skills.sh：`.sh` 在 Windows 上只有 Git Bash
能跑，且 `core.autocrlf=true`（Git for Windows 默认）会让 CRLF 进 shebang / `set -euo
pipefail` 直接报错；即使跑起来，Git Bash 的 `ln -s` 默认退化成**复制**——建出的是
skills/ 的目录副本而非链接，之后 git pull 更新 SKILL.md 不再同步。Python 三平台统一，
Windows 分支先试真 symlink（需 Developer Mode），失败退到 `mklink /J`（junction，免管理员）。

检测策略（双检测，覆盖主流场景）：
  - 配置目录存在（~/.dsh ~/.claude ~/.cursor ~/.trae ~/.codebuddy ~/.codex）——
    装了 agent 并用过即有目录，是最可靠的信号；
  - 或命令可执行（dsh/claude/cursor/trae/codebuddy/codex）——CLI 版即使目录不在
    默认位置也能命中。
  两者皆无 → 该 agent 未检测到（不建；可用 --agents 手动指定）。
只建项目级配置，不碰 agent 全局配置。

用法：
  python3 scripts/enable_agent_skills.py                        # 自动检测已安装 agent
  python3 scripts/enable_agent_skills.py --agents claude,codex  # 手动指定
  python3 scripts/enable_agent_skills.py --all                  # 全部建（不管装没装）
  python3 scripts/enable_agent_skills.py --no-git-adjust      # 不自动做 git 侧适配
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_DIR / "skills"
REL_TARGET = "../skills"  # 相对链接：仓库整体挪位置也不失效

# label / 仓库内目录 / 命令
AGENTS: list[tuple[str, str, str]] = [
    ("DeepSeek Harness", ".dsh", "dsh"),
    ("Claude Code", ".claude", "claude"),
    ("Cursor", ".cursor", "cursor"),
    ("Trae", ".trae", "trae"),
    ("CodeBuddy", ".codebuddy", "codebuddy"),
    ("Codex", ".codex", "codex"),
]

IO_REPARSE_TAG_MOUNT_POINT = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)


def is_link(path: Path) -> bool:
    """symlink 或 Windows junction（两者都是 reparse point）。"""
    try:
        info = path.lstat()
    except OSError:
        return False
    if path.is_symlink():
        return True
    # Windows junction 未必被 is_symlink 认出来，按 reparse tag 兜底
    return getattr(info, "st_reparse_tag", 0) == IO_REPARSE_TAG_MOUNT_POINT


def points_to(path: Path, target: Path) -> bool:
    """链接/目录最终是否落在 target（symlink、junction、真实目录都适用）。"""
    try:
        return path.resolve() == target.resolve()
    except OSError:
        return False


def link_kind(path: Path) -> str:
    return "symlink" if path.is_symlink() else "junction"


def make_link(link: Path, target: Path) -> str:
    """建目录链接，返回实际用上的类型（'symlink' / 'junction'）。"""
    relative = os.path.relpath(target, link.parent)
    if os.name == "nt":
        try:
            os.symlink(relative, link, target_is_directory=True)  # 需 Developer Mode / 建链接权限
            return "symlink"
        except OSError:
            pass  # WinError 1314 等：无 symlink 权限 → 退到 junction
        # junction 目标必须是绝对本地路径；mklink 是 cmd 内建命令，免管理员
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        return "junction"
    os.symlink(relative, link)
    return "symlink"


def ensure_link(agent_dir: Path, label: str, target: Path) -> tuple[str, str | None]:
    """保证 <agent_dir>/skills 指向 target。返回 (报告行, 链接类型)。"""
    link = agent_dir / "skills"

    if is_link(link):
        if points_to(link, target):
            return f"[{label}] 已配置：{link} -> {REL_TARGET}（{link_kind(link)}）", link_kind(link)
        return (
            f"[{label}] ⚠️  {link} 是指向别处的链接（仓库挪过位置？）——跳过；"
            f"确认后手动删除再重跑",
            None,
        )

    if link.is_file():
        # Windows core.symlinks=false clone 残留：内容为目标路径的普通文本文件
        try:
            content = link.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            content = ""
        if content in (REL_TARGET, str(target)):
            link.unlink()
            agent_dir.mkdir(parents=True, exist_ok=True)
            kind = make_link(link, target)
            return (
                f"[{label}] ✅ 已修正：{link} 原为文本文件（Windows clone 残留）→ 重建为 {kind}",
                kind,
            )
        return f"[{label}] ⚠️  {link} 是普通文件（内容不是 {REL_TARGET}）——跳过，请手动处理", None

    if link.exists():
        # 真实目录：可能是 Git Bash `ln -s` 退化成副本的结果，也可能是用户自己放的，删不得
        return (
            f"[{label}] ⚠️  {link} 已存在且不是链接（ln -s 退化成副本？）——跳过，"
            f"确认后可手动删除再重跑",
            None,
        )

    agent_dir.mkdir(parents=True, exist_ok=True)
    kind = make_link(link, target)
    return f"[{label}] ✅ 已配置：{link} -> {REL_TARGET}（{kind}）", kind


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace")


def ensure_core_symlinks(repo: Path) -> str | None:
    """Windows 上仓库里已有真 symlink 时，让 git 也按 symlink 比对，避免"类型变更"脏状态。"""
    if os.name != "nt":
        return None
    try:
        current = git(repo, "config", "--local", "--get", "core.symlinks").stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        current = ""  # 未设置（git 默认在 Windows 上是 false）
    if current.lower() == "true":
        return None
    try:
        git(repo, "config", "--local", "core.symlinks", "true")
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"⚠️  设置 core.symlinks=true 失败：{exc}"
    return "✅ 已设置 core.symlinks=true（git 按 symlink 比对 .dsh/skills，保持 status 干净）"


def ensure_skip_worktree(repo: Path, rel_path: str) -> str | None:
    """Windows 上 .dsh/skills 被建成 junction 时，git 会永久显示 ` D .dsh/skills`，
    且 `git pull --rebase` 每次都失败（cannot pull with rebase: You have unstaged changes）。
    该路径在仓库里是 mode 120000 的 symlink 条目，内容不会变，用 skip-worktree 让 git
    忽略它的工作区状态即可；万一上游真的改了这个链接，git 会拒绝合并并提示
    `git update-index --no-skip-worktree .dsh/skills` 后再来。"""
    if os.name != "nt":
        return None
    try:
        tracked = git(repo, "ls-files", "-s", "--", rel_path).stdout
    except (OSError, subprocess.CalledProcessError):
        return None  # 不是 git 仓库 / 无 git：与本脚本无关
    if not tracked.startswith("120000"):
        return None  # 该路径未被跟踪为 symlink（如已取消跟踪）→ 无需处理
    try:
        git(repo, "update-index", "--skip-worktree", "--", rel_path)
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"⚠️  {rel_path} 设置 skip-worktree 失败：{exc}"
    return (
        f"✅ 已对 {rel_path} 设置 skip-worktree"
        f"（消除永久 ` D` 脏状态与 pull --rebase 失败；上游改该链接时 git 会提示撤销）"
    )


def detected(conf_dir: str, cmd: str) -> bool:
    return (Path.home() / conf_dir).is_dir() or shutil.which(cmd) is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="为已安装的 agent 建项目级 skills 链接（指向本仓库 skills/）",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--agents", metavar="LIST", help="逗号分隔手动指定，如 claude,codex")
    group.add_argument("--all", action="store_true", help="全部建（不管装没装）")
    parser.add_argument(
        "--no-git-adjust", action="store_true",
        help="Windows 上不自动做 git 侧适配（junction 的 skip-worktree / 真 symlink 的 core.symlinks）",
    )
    args = parser.parse_args(argv)

    if not SKILLS_DIR.is_dir():
        print(f"错误：{SKILLS_DIR} 不存在（请确认在 ascend-sleuth 仓库内运行）", file=sys.stderr)
        return 1

    if args.agents:
        wanted = {item.strip().lstrip(".") for item in args.agents.split(",") if item.strip()}
        mode = "manual"
    else:
        wanted = set()
        mode = "all" if args.all else "auto"

    configured = 0
    for label, conf_dir, cmd in AGENTS:
        if mode == "manual":
            want = conf_dir.lstrip(".") in wanted
        elif mode == "all":
            want = True
        else:
            want = detected(conf_dir, cmd)
        if not want:
            continue
        report, _ = ensure_link(REPO_DIR / conf_dir, label, SKILLS_DIR)
        print(report)
        configured += 1

    if configured == 0:
        print("未检测到已安装 agent（~/.dsh ~/.claude ~/.cursor ~/.trae ~/.codebuddy ~/.codex 或对应命令均无）。")
        print("确定要用的 agent 不在默认路径 → 手动指定：python3 scripts/enable_agent_skills.py --agents claude")
        return 0

    if os.name == "nt" and not args.no_git_adjust:
        link = REPO_DIR / ".dsh" / "skills"
        if link.is_symlink():  # 真 symlink（Developer Mode 生效）→ 让 git 也按 symlink 比对
            note = ensure_core_symlinks(REPO_DIR)
        elif link.exists():  # junction → git 侧需 skip-worktree
            note = ensure_skip_worktree(REPO_DIR, ".dsh/skills")
        else:
            note = None
        if note:
            print(note)

    print()
    print("完成。在仓库目录内启动 agent 即自动发现 skills/（各 agent 项目 roots 扫描）。")
    print("仓库 git pull 更新 SKILL.md 后：DSH 热刷新即时生效；其余 agent 重新加载会话即可。")
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    raise SystemExit(main())
