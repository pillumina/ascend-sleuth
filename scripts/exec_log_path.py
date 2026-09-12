#!/usr/bin/env python3
# exec_log_path.py —— exec-log 的路径解析（单一事实源）
#
# 为什么需要它（2026-09-10 修一个结构缺陷）：
#   原先 exec-log 固定写在 `<检出>/metrics/skill-exec-log.yaml`，而它是 .gitignore 运行时件。
#   本仓库又**强制每个 agent/session 在独立 worktree 里工作**（CLAUDE.md「多 agent 协作」）——
#   两条叠加的后果实测如下（在临时仓库复现）：
#     ① 代理在 worktree 里收尾落了记录 → **主检出读不到**，而主检出正是用户会话的 cwd、
#        也是 DSH 面板读数据的地方 → "执行现场"区块常年空着，可见性形同虚设；
#     ② 收工 `git worktree remove`（甚至要 `--force`，因为那份未跟踪文件）→ 记录**随 worktree
#        一起消失**——流水直接丢，谈不上"统一执行记录"。
#   即：一个 per-worktree 的运行时文件，被拿来当"全流程观测台账"用，语义不成立。
#
# 现在的语义（同一克隆内共享）：
#   路径 = **主检出**（`git rev-parse --git-common-dir` 的父目录）下的 metrics/skill-exec-log.yaml。
#   同一克隆的所有 worktree 共写/共读同一份：
#     - 代理在任意 worktree 收尾落的记录，主检出立即能读到（面板可见）；
#     - worktree 清理不再丢数据（文件不在 worktree 内）；
#     - 无 git（沙箱/CI）时退化为检出内路径，保证隔离与可跑。
#   并发：多个 worktree 可能同时 append —— 该文件是 read-modify-write，**写侧必须持锁**
#   （见 log_skill_exec.py 的 flock），这也正是 CLAUDE.md「串行操作」那条纪律的适用场景。
#
# 边界（不假装）：**跨克隆/跨机不聚合**——本文件只解决"同一克隆内的一致性"。要跨机，
#   得让**聚合值**（不是流水）进 git（如 metrics/timeline.yaml），见 tail_exec_log.py --summary
#   与 docs/mechanism/run.md §4。
#
# 用法（调用方共用）：
#   from exec_log_path import LOG_REL, resolve
#   path, where = resolve(root, explicit=args.log, local=args.local)
#   path, where = resolve_rel(root, MEASURE_LOG_REL)      # 第二个共享件（口径同一条）
#
# 2026-09 泛化：**"同一克隆共享的运行件"不只 exec-log 一件**。`metrics/ev-measure-log.yaml`
#   （EV 卡预测的实测记录，判据「声明了却没测」的数据源）有一模一样的两个约束：面板读主检出、
#   worktree 清理不能丢数据。所以共享件路径解析与写锁原语都收在本模块，不再各写一份
#   （抄两份 = 口径漂移的经典来源；本模块的注释已经因为同一原因被引用过多次）。

import subprocess
from contextlib import contextmanager
from pathlib import Path

LOG_REL = Path("metrics") / "skill-exec-log.yaml"
# EV 卡预测的实测记录（reviewer 跑 ev_measure.py --run 时 append 一笔）
MEASURE_LOG_REL = Path("metrics") / "ev-measure-log.yaml"

# where 的含义（人读输出里直接标注，防止把"本地"读成"全系统"）
WHERE_LABEL = {
    "explicit": "指定路径（--log）",
    "local": "检出内（--local 强制）",
    "shared": "同一克隆共享（主检出 metrics/；所有 worktree 共写共读）",
    "fallback": "检出内（无 git 环境，退化）",
}


def _git_common_dir(root: Path):
    """git common dir 的绝对路径；失败返回 None（不抛）。"""
    try:
        r = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                           capture_output=True, text=True, cwd=str(root), encoding="utf-8", errors="replace")
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
    except Exception:
        pass
    try:  # 老版本 git 没有 --path-format，退回相对路径 + 手工解析
        r = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                           capture_output=True, text=True, cwd=str(root), encoding="utf-8", errors="replace")
        if r.returncode == 0 and r.stdout.strip():
            p = Path(r.stdout.strip())
            return p if p.is_absolute() else (root / p).resolve()
    except Exception:
        pass
    return None


def main_checkout(root: Path):
    """主检出根（同一克隆的"共享侧"）；拿不到返回 None。

    这套语义**不只用于 exec-log**：`traces/` 同样是各检出各一份的运行时件，而周批的指标
    生产者（trace_metrics.py）要读它——在 worktree 里跑会静默读不到（2026-09-10 实测：
    worktree 里 `traces/` 不存在 → "未找到任何 traces/*.yaml" → 周批会产出**空诊断指标**）。
    所以 metrics_snapshot.py 也用它来定位 traces 该读哪一份。
    """
    common = _git_common_dir(Path(root))
    if common is None:
        return None
    main_root = common.parent              # <主检出>/.git → <主检出>
    if (main_root / ".git").exists() or (main_root / "metrics").exists():
        return main_root
    return None


def resolve_rel(root: Path, rel: Path, explicit: Path = None, local: bool = False):
    """任意共享运行件 → (path, where)。绝不抛异常——取不到就老实退化。

    `resolve()` 是本函数在 exec-log 上的特例（保留旧签名，三个调用方不动）。
    """
    root = Path(root)
    if explicit is not None:
        return Path(explicit), "explicit"
    if local:
        return root / Path(rel), "local"
    main_root = main_checkout(root)
    if main_root is not None:
        return main_root / Path(rel), "shared"
    return root / Path(rel), "fallback"


def resolve(root: Path, explicit: Path = None, local: bool = False):
    """exec-log 的路径解析（保留原签名）。"""
    return resolve_rel(root, LOG_REL, explicit=explicit, local=local)


@contextmanager
def log_lock(path: Path):
    """共享运行件的跨进程写锁（flock）。yield True=已持锁 / False=本平台无 flock。

    read-modify-write 无锁 = 后写覆盖先写（丢记录）或算出重复 seq。无 fcntl 的平台
    （Windows）退化为不加锁：语义如实告知调用方，不假装有互斥。
    两个共享件（exec-log / ev-measure-log）共用本原语。
    """
    try:
        import fcntl
    except ImportError:
        yield False
        return
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield True
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def describe(path: Path, where: str) -> str:
    return f"{path}（{WHERE_LABEL.get(where, where)}）"
