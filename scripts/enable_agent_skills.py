#!/usr/bin/env python3
"""enable_agent_skills.py —— 关联 agent 与本仓库 skills/（项目级目录链接）

跨平台、幂等可重跑。替代原 enable-agent-skills.sh：`.sh` 在 Windows 上只有 Git Bash
能跑，且 `core.autocrlf=true`（Git for Windows 默认）会让 CRLF 进 shebang / `set -euo
pipefail` 直接报错；即使跑起来，Git Bash 的 `ln -s` 默认退化成**复制**——建出的是
skills/ 的目录副本而非链接，之后 git pull 更新 SKILL.md 不再同步。Python 三平台统一，
Windows 分支先试真 symlink（需 Developer Mode），失败退到 `mklink /J`（junction，免管理员）。

检测策略（两检测，覆盖主流场景）：
  - 配置目录存在（~/.dsh、~/.claude 等六家）——装了 agent 并用过即有目录，是最可靠的信号；
  - 或命令可执行（dsh、claude 等六家）——CLI 版即使目录不在默认位置也能命中。
  两者皆无 → 该 agent 未检测到（不建；可用 --all 或 --agents 手动指定），
  Windows 上逐个打印跳过的原因。
`.dsh` 是例外：`.dsh/skills` 是本仓自己跟踪的条目，任何模式（含 --agents）都修，不参与检测。
  DSH Desktop 的 home 不在 ~/.dsh、不装 dsh 命令，两条检测都不成立；而 Windows clone 下
  它落成内容为 `../skills` 的文本文件，正是必须修的那一个。

`<agent>/skills` 的既有状态按「是否 reparse point」+「解析到哪」判定，不按「是不是目录」。
目录副本与 junction 在 `PSIsContainer`、`is_dir()` 下同形，用「是不是目录」判会把副本当正常：

  ① 链接且解析到 skills/                      → 不动
  ② 链接但指向别处 / 解析不到内容             → 只报告，不替你删（可能是本机别的布局）
  ③ 内容为 ../skills 的普通文件（clone 残留） → 删除并重建
  ④ 目录副本（Git Bash `ln -s` 退化）         → 默认只报告：agent 现在读得到 skills，
                                                但内容不随 git pull 更新；加 --fix-copy
                                                且副本里没有 skills/ 之外的内容时才替换
  ⑤ 目录副本含 skills/ 之外的内容             → 只报告并列出外来条目，不删

`--check` 只读：逐条打印状态与原因，不写盘、不改 git 配置；出现 ① 以外的状态时以 1 退出。
reparse point 用 `GetFileAttributesW` 判定，不依赖 Python 3.8 才有的 `st_reparse_tag`；
symlink 与 junction 的区分依次用 `os.path.isjunction`（3.12+）、reparse tag（3.8+）、
`readlink` 返回的目标是否为绝对路径（更低版本）。
只建项目级配置，不碰 agent 全局配置。

用法：
  python3 scripts/enable_agent_skills.py                        # 自动检测已安装 agent
  python3 scripts/enable_agent_skills.py --check                # 只看状态，不写盘
  python3 scripts/enable_agent_skills.py --fix-copy             # 把纯副本的目录换成链接
  python3 scripts/enable_agent_skills.py --agents claude,codex  # 手动指定
  python3 scripts/enable_agent_skills.py --all                  # 全部建（不管装没装）
  python3 scripts/enable_agent_skills.py --no-git-adjust        # 不自动做 git 侧适配
"""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from _cli import main_entry

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

# 不参与检测的一家：`.dsh/skills` 是本仓自己跟踪的条目（index mode 120000），Windows clone 下
# 落成内容为 `../skills` 的文本文件，必须修好。它不取决于「检测到 DSH 装了」——DSH Desktop 的
# home 在 %APPDATA%\dsh-desktop\harness、不装 dsh 命令，人手动开的 PowerShell 里两条检测都不成立。
REPO_OWNED_DIR = ".dsh"

IO_REPARSE_TAG_MOUNT_POINT = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF

# 状态码。判据是「是否 reparse point」+「解析到哪」，与「是否是目录」无关。
OK = "ok"
MISSING = "missing"
LINK_ELSEWHERE = "link-elsewhere"
LINK_BROKEN = "link-broken"
FILE_RESIDUAL = "file-residual"
FILE_FOREIGN = "file-foreign"
DIR_COPY = "dir-copy"
DIR_FOREIGN = "dir-foreign"

_kernel32 = None


def _get_file_attributes(path: Path) -> int | None:
    """GetFileAttributesW 的返回值；路径读不到时返回 None。

    为什么不用 `os.lstat().st_reparse_tag`：那个属性 Python 3.8 才有，旧解释器上会取到
    0，真实的 junction 被判成「不是链接」。本脚本要在 Windows 上认出 junction，不能把
    判定押在一个可能不存在的属性上。
    """
    global _kernel32
    if _kernel32 is None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        kernel32.GetFileAttributesW.argtypes = (ctypes.c_wchar_p,)
        kernel32.GetFileAttributesW.restype = ctypes.c_uint32
        _kernel32 = kernel32
    value = int(_kernel32.GetFileAttributesW(str(path)))
    return None if value == INVALID_FILE_ATTRIBUTES else value


def is_reparse_point(path: Path) -> bool:
    """symlink 或 junction（两者都是 reparse point）。"""
    if os.name != "nt":
        return path.is_symlink()
    attrs = _get_file_attributes(path)
    if attrs is None:
        return path.is_symlink()  # 路径不存在：退回标准库，后续按缺失处理
    return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)


def is_junction(path: Path) -> bool:
    """Windows junction。`os.path.islink()` 把 junction 也算 symlink，所以单独认一遍。"""
    if os.name != "nt":
        return False
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None:
        try:
            if isjunction(path):
                return True
        except OSError:
            pass
    try:
        info = path.lstat()
    except OSError:
        return False
    tag = getattr(info, "st_reparse_tag", None)
    if tag is not None:
        return tag == IO_REPARSE_TAG_MOUNT_POINT
    # Python 3.8 以下拿不到 reparse tag：junction 由 mklink /J 建，目标必须是绝对路径，
    # 而本脚本建的 symlink 用相对路径，按这一条兜底。
    try:
        raw = os.readlink(path)
    except OSError:
        return False
    return raw.startswith("\\\\?\\") or os.path.isabs(raw)


def link_kind(path: Path) -> str:
    """链接类型。打屏与 git 侧适配都按它选，不能用 `is_symlink()`（junction 也算 True）。"""
    return "junction" if is_junction(path) else "symlink"


def resolved(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:
        return None


def points_to(path: Path, target: Path) -> bool:
    """链接/目录最终是否落在 target（symlink、junction、真实目录都适用）。"""
    where = resolved(path)
    if where is None:
        return False
    try:
        return where == target.resolve()
    except OSError:
        return False


def foreign_entries(
    link: Path, target: Path, limit: int = 5,
) -> tuple[list[str], int] | None:
    """link 目录里不在 target 下的条目（最多 limit 条，附总数）。读不动时返回 None。

    用途只有一处：判断一个目录副本是不是纯副本。是纯副本才允许 `--fix-copy` 删掉它，
    否则里面可能有使用者自己放的文件。
    """
    try:
        known = {str(path.relative_to(target)) for path in target.rglob("*")}
    except OSError:
        return None
    found: list[str] = []
    total = 0
    try:
        for path in link.rglob("*"):
            rel = str(path.relative_to(link))
            if rel in known:
                continue
            total += 1
            if len(found) < limit:
                found.append(rel)
    except OSError:
        return None
    return found, total


def inspect(link: Path, target: Path) -> tuple[str, str]:
    """判定 link 的状态，返回 (状态码, 说明)。说明供打屏用，可以是空串。"""
    if is_reparse_point(link):
        if not link.exists():
            return LINK_BROKEN, "链接解析不到内容"
        if points_to(link, target):
            return OK, link_kind(link)
        where = resolved(link)
        shown = str(where) if where is not None else "解析失败"
        return LINK_ELSEWHERE, f"指向 {shown}"

    if link.is_file():
        # Windows core.symlinks=false clone 残留：内容为目标路径的普通文本文件
        try:
            content = link.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            content = ""
        if content in (REL_TARGET, str(target)):
            return FILE_RESIDUAL, f"内容为 {content} 的普通文件"
        return FILE_FOREIGN, "普通文件，内容不是 ../skills"

    if link.exists():
        foreign = foreign_entries(link, target)
        if foreign is None:
            return DIR_FOREIGN, "目录副本，内容读不动"
        listed, total = foreign
        if total:
            more = "" if total <= len(listed) else " 等"
            return DIR_FOREIGN, f"目录副本，含 skills/ 之外的内容：{'、'.join(listed)}{more}"
        return DIR_COPY, "目录副本"

    return MISSING, ""


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


def remove_link(path: Path) -> None:
    """删链接本身，不碰它指向的内容。junction 在 Windows 上是目录，`os.unlink` 会失败。"""
    try:
        os.unlink(path)
        return
    except OSError:
        pass
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "rmdir", str(path)],
            check=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        return
    os.rmdir(path)


def _build(link: Path, target: Path, label: str, head: str) -> tuple[str, str | None]:
    """建链接并回读校验。回读不过就不报成功，「已配置」要是证据而不是宣称。"""
    kind = make_link(link, target)
    if link.exists() and points_to(link, target):
        return f"[{label}] ✅ {head}：{link} -> {REL_TARGET}（{kind}）", kind
    return (
        f"[{label}] ⚠️ 链接已创建但校验失败：{link} 解析不到 {REL_TARGET}，请手动检查（{kind}）",
        None,
    )


def ensure_link(
    agent_dir: Path, label: str, target: Path, fix_copy: bool,
) -> tuple[str, str | None]:
    """保证 <agent_dir>/skills 指向 target。返回 (报告行, 链接类型)；类型为 None 表示没建好。"""
    link = agent_dir / "skills"
    state, detail = inspect(link, target)

    if state == OK:
        return f"[{label}] ✅ 正常：{link} -> {REL_TARGET}（{detail}）", detail

    if state == MISSING:
        agent_dir.mkdir(parents=True, exist_ok=True)
        return _build(link, target, label, "已建立链接")

    if state == FILE_RESIDUAL:
        link.unlink()
        agent_dir.mkdir(parents=True, exist_ok=True)
        return _build(link, target, label, "已修正文本文件残留")

    if state == LINK_BROKEN:
        remove_link(link)
        return _build(link, target, label, "已重建断裂的链接")

    if state == LINK_ELSEWHERE:
        return (
            f"[{label}] ⚠️ {link} {detail}，不是 {REL_TARGET}，未改动；确认后删除该链接再重跑",
            None,
        )

    if state == FILE_FOREIGN:
        return f"[{label}] ⚠️ {link} {detail}，未改动；确认后删除再重跑", None

    if state == DIR_FOREIGN:
        return (
            f"[{label}] ⚠️ {link} {detail}，未改动；移走这些内容后加 --fix-copy 重跑",
            None,
        )

    # DIR_COPY：读得到 skill，但内容不随 git pull 更新
    if not fix_copy:
        return (
            f"[{label}] ⚠️ {link} 是目录副本，不是链接：agent 现在读得到 skills，"
            f"但内容不随 git pull 更新；加 --fix-copy 换成链接，或手动删除后重跑",
            None,
        )
    if is_reparse_point(link):  # 防御：rmtree 只对普通目录用，对链接会连带删目标内容
        return f"[{label}] ⚠️ {link} 状态在检查后变化，未改动；重跑一次", None
    shutil.rmtree(link)
    return _build(link, target, label, "已用链接替换目录副本")


def report_state(link: Path, target: Path, label: str) -> tuple[str, bool]:
    """`--check` 用：只报告状态，不写盘。返回 (报告行, 是否正常)。"""
    state, detail = inspect(link, target)

    if state == OK:
        return f"[{label}] ✅ 正常：{link} -> {REL_TARGET}（{detail}）", True
    if state == MISSING:
        return f"[{label}] ❌ 不存在：{link}，不带 --check 重跑会建立", False
    if state == LINK_ELSEWHERE:
        return f"[{label}] ⚠️ {link} {detail}，不是 {REL_TARGET}，需手动处理", False
    if state == LINK_BROKEN:
        return f"[{label}] ⚠️ {link} {detail}，不带 --check 重跑会重建", False
    if state == FILE_RESIDUAL:
        return f"[{label}] ⚠️ {link} {detail}，不带 --check 重跑会修正", False
    if state == FILE_FOREIGN:
        return f"[{label}] ⚠️ {link} {detail}，需手动处理", False
    if state == DIR_FOREIGN:
        return f"[{label}] ⚠️ {link} {detail}，--fix-copy 也不会动它", False
    return (
        f"[{label}] ⚠️ {link} 是目录副本，不是链接：读得到 skills，"
        f"但内容不随 git pull 更新，加 --fix-copy 可换成链接",
        False,
    )


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
        return f"⚠️ 设置 core.symlinks=true 失败：{exc}"
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
    """本机是否装了该 agent：配置目录存在，或命令可执行。

    两条都不覆盖「home 不在 `~` 下」的形态（DSH Desktop 把 home 放在
    `%APPDATA%\\dsh-desktop\\harness`）——该形态对应的 `.dsh` 不参与检测，见 REPO_OWNED_DIR。
    """
    return (Path.home() / conf_dir).is_dir() or shutil.which(cmd) is not None


def skip_reason(conf_dir: str, cmd: str) -> str:
    """自动模式判定「未安装」时，逐条给出两条检测的实际取值，让用户看出是误判还是真没装。"""
    return f"~/{conf_dir} 不存在、PATH 上没有 {cmd}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="为已安装的 agent 建项目级 skills 链接（指向本仓库 skills/）",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--agents", metavar="LIST", help="逗号分隔手动指定，如 claude,codex")
    group.add_argument("--all", action="store_true", help="全部建（不管装没装）")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true",
                        help="只读：逐条打印状态，不写盘、不改 git 配置")
    action.add_argument("--fix-copy", action="store_true",
                        help="把没有 skills/ 之外内容的目录副本换成链接")
    parser.add_argument(
        "--no-git-adjust", action="store_true",
        help="Windows 上不自动做 git 侧适配（junction 的 skip-worktree / 真 symlink 的 core.symlinks）",
    )
    args = parser.parse_args(argv)

    if not SKILLS_DIR.is_dir():
        print(f"错误：{SKILLS_DIR} 不存在（请确认在 ascend-sleuth 仓库内运行）", file=sys.stderr)
        return 1

    known = [conf_dir.lstrip(".") for _, conf_dir, _ in AGENTS]
    if args.agents:
        wanted = {item.strip().lstrip(".") for item in args.agents.split(",") if item.strip()}
        mode = "manual"
        unknown = sorted(wanted - set(known))
        if unknown:
            print(f"--agents 里有不认识的名字：{'、'.join(unknown)}")
            print("可写：" + " ".join(known))
            return 1
    else:
        wanted = set()
        mode = "all" if args.all else "auto"

    unresolved: list[tuple[str, str]] = []
    skipped: list[str] = []
    for label, conf_dir, cmd in AGENTS:
        if conf_dir == REPO_OWNED_DIR:
            want = True  # 仓库自己的条目，任何模式都修
        elif mode == "manual":
            want = conf_dir.lstrip(".") in wanted
        elif mode == "all":
            want = True
        else:
            want = detected(conf_dir, cmd)
        if not want:
            skipped.append(f"[跳过] {label}：{skip_reason(conf_dir, cmd)}")
            continue
        link = REPO_DIR / conf_dir / "skills"
        if args.check:
            line, good = report_state(link, SKILLS_DIR, label)
            print(line)
            if not good:
                unresolved.append((conf_dir, label))
            continue
        report, kind = ensure_link(REPO_DIR / conf_dir, label, SKILLS_DIR, args.fix_copy)
        print(report)
        if kind is None:  # 没建好 / 没修：不替用户删，也不报成功
            unresolved.append((conf_dir, label))

    if skipped and (args.check or (os.name == "nt" and mode == "auto")):
        # Windows 上「没建」与「建好了」必须在输出里分开：这正是 `.dsh/skills` 长期修不上的成因。
        # `--check` 是诊断命令，未检测到的 agent 也列出来，否则「没有这一行」会被读成正常。
        print()
        for line in skipped:
            print(line)
        if not args.check:
            print("要连未检测到的 agent 一起建：python3 scripts/enable_agent_skills.py --all")

    if os.name == "nt" and not args.check and not args.no_git_adjust:
        link = REPO_DIR / ".dsh" / "skills"
        if not is_reparse_point(link):  # 不是链接（目录副本 / 破损残留）：不动 git 配置
            note = None
        elif link_kind(link) == "symlink":
            note = ensure_core_symlinks(REPO_DIR)
        else:  # junction 在 Windows 上被 is_symlink() 也算 symlink，必须按类型分开走
            note = ensure_skip_worktree(REPO_DIR, ".dsh/skills")
        if note:
            print(note)

    print()
    if unresolved:
        names = "、".join(label for _, label in unresolved)
        print(f"有 {len(unresolved)} 个 agent 的 skills 目录需要处理：{names}")
        print("按上面每行的提示处理后重跑；只看状态不写盘，加 --check。")
        if any(conf_dir == REPO_OWNED_DIR for conf_dir, _ in unresolved):
            print(f"DSH 读的是 {REPO_DIR / '.dsh' / 'skills'}：它不存在或读不出内容时，/skill 列表为空。")
            print("目录副本能列出 skill，但内容不随 git pull 更新。")
        return 1
    print("完成。在仓库目录内启动 agent 即自动发现 skills/（各 agent 项目 roots 扫描）。")
    print("仓库 git pull 更新 SKILL.md 后：DSH 热刷新即时生效；其余 agent 重新加载会话即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_entry(main))
