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
#   与 docs/evolution-run.md §4。
#
# 用法（三个调用方共用）：
#   from exec_log_path import LOG_REL, resolve
#   path, where = resolve(root, explicit=args.log, local=args.local)

import subprocess
from pathlib import Path

LOG_REL = Path("metrics") / "skill-exec-log.yaml"

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
                           capture_output=True, text=True, cwd=str(root))
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
    except Exception:
        pass
    try:  # 老版本 git 没有 --path-format，退回相对路径 + 手工解析
        r = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                           capture_output=True, text=True, cwd=str(root))
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


def resolve(root: Path, explicit: Path = None, local: bool = False):
    """返回 (log_path, where)。绝不抛异常——取不到就老实退化。"""
    root = Path(root)
    if explicit is not None:
        return Path(explicit), "explicit"
    if local:
        return root / LOG_REL, "local"
    main_root = main_checkout(root)
    if main_root is not None:
        return main_root / LOG_REL, "shared"
    return root / LOG_REL, "fallback"


def describe(path: Path, where: str) -> str:
    return f"{path}（{WHERE_LABEL.get(where, where)}）"
