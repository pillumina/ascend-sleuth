#!/usr/bin/env python3
# log_skill_exec.py —— 统一 skill 执行记录（run.md §4 机制 C 落地）
#
# 每次内容流程 skill 调用（diagnose / to-postmortem / to-reference / issue-ingest /
# knowledge-groom / replay）收尾时 append 一条执行记录到 metrics/skill-exec-log.yaml——
# 让 feedback loop 有全链路数据源（不只诊断侧），也让 evolve-check 收尾钩子有真实
# 现场记录可读（替代 agent 记忆"本轮做了什么"）。
#
# 记录字段（对齐 run.md §4 + execution §2 脱敏纪律）：
#   - skill + 版本（commit hash）+ 时间 + 触发者（session/task/人）
#   - 输入摘要：只记引用与聚合（issue 号 / 文件路径 / trace id），不落客户原文
#   - 产出：case/reference/卡 id 与状态流转
#   - 成本：token（估算或 DSH tokenMeter measured）
#   - decision_reason：关键决策一句话依据
# 边界：记录对象是 skill 与动作，不是人（roadmap 不做 KPI/身份/使用观测红线不变）
#
# 确定性 append（原则二）：脚本负责 YAML 写入，agent 只提供参数——避免手写破坏
# 多行结构（仓库教训：yaml.safe_dump roundtrip 会截断多行标量）。
#
# 用法：
#   python3 scripts/log_skill_exec.py --skill to-postmortem \
#     --products "VLLM-ASC-12345(submitted),VLLM-ASC-12346(submitted)" \
#     --reason "沉淀 2 条 #12345/#12346 case（S2 缺口驱动）" \
#     [--source issue-ingest] [--session <id>] [--tokens N] [--ref <issue>]

import argparse
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import yaml

from exec_log_path import describe, resolve

VALID_SKILLS = {
    "diagnose", "resume-diagnosis", "to-postmortem", "to-reference",
    "issue-ingest", "knowledge-groom", "s2-replay", "replay-golden",
    "evolve-check", "self-evolve", "capacity-health",
}


@contextmanager
def _log_lock(log_path: Path):
    """跨进程互斥（flock）——共享 exec-log 后，多个 worktree 可能同时 append。

    read-modify-write 无锁 = 后写覆盖先写（丢记录）或算出重复 seq。无 fcntl 的平台
    （Windows）退化为不加锁：语义如实告知调用方（yield False），不假装有互斥。
    """
    try:
        import fcntl
    except ImportError:
        yield False
        return
    lock_path = log_path.with_suffix(log_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield True
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def git_head(root: Path) -> str:
    """当前检出对应的提交短哈希。

    为什么不能只问 `git`：**git 不在 PATH 上时**（本项目 Windows 实测：MinGit 便携版装在
    `%LOCALAPPDATA%\\mingit`，shell 里没有 `git`）这里会退化成 "unknown"，于是每条执行记录都丢掉
    "当时是哪个提交"——审计链最该有的那一栏变成空话。所以加一条不依赖 git 二进制的退化路径：
    直接读 `.git`（HEAD → refs/ → packed-refs，含 worktree 的 `gitdir:` 指针）。
    """
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, cwd=str(root), encoding="utf-8", errors="replace")
        head = r.stdout.strip()
        if head:
            return head
    except Exception:
        pass
    try:
        git_dir = root / ".git"
        if git_dir.is_file():                     # worktree / submodule：`.git` 是指向真实 git 目录的文件
            text = git_dir.read_text(encoding="utf-8", errors="replace").strip()
            if text.startswith("gitdir:"):
                git_dir = (git_dir.parent / text.split(":", 1)[1].strip()).resolve()
        head_line = (git_dir / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
        if head_line.startswith("ref:"):
            ref = head_line.split(":", 1)[1].strip()
            ref_file = git_dir / ref
            if ref_file.is_file():
                return ref_file.read_text(encoding="utf-8", errors="replace").strip()[:7]
            packed = git_dir / "packed-refs"
            if packed.is_file():
                for line in packed.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.endswith(" " + ref):
                        return line.split(" ", 1)[0][:7]
            return "unknown"
        return (head_line[:7] or "unknown")        # detached HEAD：HEAD 里直接就是哈希
    except Exception:
        return "unknown"


def iso_at(value) -> str:
    """把 `at` 规整成 ISO 字符串。

    为什么要规整：写回时是文本级构建，但**读回走 PyYAML**——未加引号的 `2026-09-12T17:56:41`
    会被解析成 datetime，再写出去就是 `2026-09-12 16:49:27`（空格、无 T）。同一字段两种形态，
    下游 `rec['at'][:10]` 这类下标操作还会直接 TypeError（evolve-check 文档专门警告过这条）。
    所以：读回时把 datetime 转回 ISO，写出去时**加引号**保持字符串。
    """
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def main():
    ap = argparse.ArgumentParser(description="统一 skill 执行记录（append-only）")
    ap.add_argument("--skill", required=True, help="调用的 skill 名")
    ap.add_argument("--products", default="", help="产出（逗号分隔 id(状态)，如 VLLM-ASC-1(submitted)）")
    ap.add_argument("--reason", default="", help="关键决策一句话依据（decision_reason）")
    ap.add_argument("--source", default="", help="触发者来源（issue-ingest/self-evolve/人工/会话）")
    ap.add_argument("--session", default="", help="session id（如有）")
    ap.add_argument("--tokens", type=int, default=0, help="token 消耗（估算或 measured）")
    ap.add_argument("--cost-source", default="estimate", choices=["estimate", "measured"],
                    help="token 口径（measured = DSH tokenMeter）")
    ap.add_argument("--ref", default="", help="输入引用（issue 号/文件/trace，不含原文）")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--log", type=Path, default=None,
                    help="显式指定 exec-log 路径（默认：同一克隆共享的主检出 metrics/skill-exec-log.yaml）")
    ap.add_argument("--local", action="store_true",
                    help="强制写在当前检出内（用于隔离测试/演练，不参与共享）")
    args = ap.parse_args()
    root = args.root.resolve()

    if args.skill not in VALID_SKILLS:
        print(f"skill '{args.skill}' 不在合法集合 {sorted(VALID_SKILLS)}"); sys.exit(1)

    log_path, where = resolve(root, explicit=args.log, local=args.local)
    log_path.parent.mkdir(parents=True, exist_ok=True)   # 空 metrics/ 的检出也能落（实测曾 FileNotFoundError）

    # 共享路径下多个 worktree 可能同时 append——read-modify-write 必须持锁，
    # 否则并发写会互相覆盖（丢记录）或算出重复 seq。无 flock 的平台退化为不加锁并如实提示。
    with _log_lock(log_path) as locked:
        if log_path.exists():
            try:
                doc = yaml.safe_load(log_path.read_text(encoding="utf-8")) or {}
            except Exception:
                doc = {}
        else:
            doc = {}

        records = doc.get("records") or []
        entry = {
            "seq": len(records) + 1,
            "skill": args.skill,
            "version": git_head(root),
            "at": datetime.now().isoformat(timespec="seconds"),
            "source": args.source or "manual",
        }
        if args.session:
            entry["session"] = args.session
        if args.ref:
            entry["ref"] = args.ref
        if args.products:
            # 解析 products：id(状态) 逗号分隔（id 本身不含逗号）
            entry["products"] = []
            for p in args.products.split(","):
                p = p.strip()
                if not p:
                    continue
                if "(" in p and p.rstrip().endswith(")"):
                    pid, _, st = p.rstrip()[:-1].partition("(")
                    entry["products"].append({"id": pid.strip(), "status": st.strip()})
                else:
                    # 括号不闭合 = 十有八九是"状态里带了逗号"（如 `id(in_progress,no_hit)`），
                    # 被 split 切成两段后**静默写成两条产物**——审计记录被悄悄改形，比报错更糟。
                    # 这里响亮失败，让人改用不含逗号的写法（`id(in_progress)` / `id(no_hit)`）。
                    if "(" in p or ")" in p:
                        print(
                            "log_skill_exec: --products 段「" + p + "」括号不闭合——逗号只用于分隔产物，"
                            "不能出现在 id 或状态里（要记两件事就写两条产物，或用 / 连接）",
                            file=sys.stderr)
                        sys.exit(2)   # 入口是 `main()`（不是 sys.exit(main())），必须自己 sys.exit 才带退出码
                    entry["products"].append({"id": p})
        if args.reason:
            entry["decision_reason"] = args.reason
        if args.tokens:
            entry["cost"] = {"tokens": args.tokens, "source": args.cost_source}

        records.append(entry)
        doc["_comment"] = ("GENERATED by scripts/log_skill_exec.py；统一 skill 执行记录（run.md §4）。"
                           "append-only——只追加不修改，供 evolve-check 收尾读现场 + metrics 全链路归因。"
                           "记录对象是 skill/动作/产物 id，非人（roadmap 不做 KPI/身份 红线）。")
        doc["records"] = records

        # 写回：文本级构建（每 record 手动序列化，避免 safe_dump 破坏中文/多行）
        out = [f"# {doc['_comment']}", "", "records:"]
        for r in records:
            out.append(f"- seq: {r['seq']}")
            out.append(f"  skill: {r['skill']}")
            out.append(f"  version: {r['version']}")
            out.append(f"  at: '{iso_at(r['at'])}'")   # 加引号：读回时保持字符串，不被 PyYAML 变 datetime
            out.append(f"  source: {r['source']}")
            if r.get("session"):
                out.append(f"  session: {r['session']}")
            if r.get("ref"):
                out.append(f"  ref: '{r['ref']}'")
            if r.get("products"):
                out.append("  products:")
                for p in r["products"]:
                    if p.get("status"):
                        out.append(f"    - id: {p['id']}")
                        out.append(f"      status: {p['status']}")
                    else:
                        out.append(f"    - id: {p['id']}")
            if r.get("decision_reason"):
                out.append(f"  decision_reason: '{r['decision_reason']}'")
            if r.get("cost"):
                out.append(f"  cost: {{tokens: {r['cost']['tokens']}, source: {r['cost']['source']}}}")
        log_path.write_text("\n".join(out) + "\n", encoding="utf-8")
        seq = entry["seq"]

    print(f"exec-log: seq {seq} 已记录（{args.skill}）→ {describe(log_path, where)}")
    if not locked:
        print("  ⚠ 本平台无 fcntl.flock：并发 append 无法互斥（单写入方场景无影响）")


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
