#!/usr/bin/env python3
# rehearse_evolve_loop.py —— evolve-check 闭环的端到端演练（离线、可重复、不改本仓）
#
# 为什么需要它：evolve-check 的链路由四段构成——**内容流程落 exec-log → evolve-check 读现场 →
# 产卡并自验证 → 卡随 PR 过 CI**——而每一段都各自"看起来没问题"。2026-09-10 审计发现的实际
# 状况是：读现场的命令两种环境都抛异常、exec-log 9 天只有 4 条、卡的完整性规则只写在 SKILL.md
# 里（CI 里没有）。这类断点只有**把整条链在临时副本里真跑一遍**才会暴露（读代码、读文档都会说
# "已落地"）。所以本脚本把"闭环能跑通"从叙述变成可执行断言：正例走通、负例必须报错、CI 命令逐条
# 在本地复跑。
#
# 与 CI 的分工：本脚本**不进 CI**（它不是回归门，是验证工具，同 scripts/panel_render_check.js 的
# 定位）。CI 只跑 kb-checks.yml 里那几条确定性检查；本脚本负责证明"这套检查真的能拦住坏卡"。
#
# 用法：
#   python3 scripts/rehearse_evolve_loop.py            # 全跑（含面板渲染断言，需 node）
#   python3 scripts/rehearse_evolve_loop.py --no-panel # 跳过 node 面板断言
#   python3 scripts/rehearse_evolve_loop.py --keep     # 保留临时副本（排查用，会打印路径）
#
# 退出码：0 = 全部断言通过；1 = 有断言失败（逐条打印）。

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SKIP_TOP = {".git", "src-code", ".s2-replay", ".ixn-replay", ".flow-replay",
            ".auto-fetch", "__pycache__", "node_modules", "traces", "eval-reports"}

FAILS = []
COUNT = 0


def check(name, cond, detail=""):
    global COUNT
    COUNT += 1
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}" + (f"  :: {detail}" if detail else ""))
        FAILS.append(name)


def run(args, cwd, env=None):
    e = dict(os.environ)
    e["PYTHONIOENCODING"] = "utf-8"
    if env:
        e.update(env)
    r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, env=e)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def py(root, *args):
    return run([sys.executable, *args], cwd=root)


def make_copy(dest: Path):
    """把仓库复制成独立演练场（不带 .git/运行时件，快且不污染本仓）。"""
    shutil.copytree(REPO, dest, ignore=shutil.ignore_patterns(*SKIP_TOP), dirs_exist_ok=True)
    # 演练场不需要历史 execlog：先确保从"无记录"这个真实起点开始
    (dest / "metrics" / "skill-exec-log.yaml").unlink(missing_ok=True)
    return dest


# ---------------------------------------------------------------- ① 取数入口三态
def ex_degraded(root: Path):
    print("\n[E1] 取数入口 · 无 exec-log（新 worktree 的真实起点）")
    rc, out = py(root, "scripts/tail_exec_log.py")
    check("tail_exec_log 无记录时 exit 0（不是崩溃）", rc == 0, out[-300:])
    check("报出「无执行记录」", "无执行记录" in out, out[-200:])
    check("给出退化口径（不假装有数据）", "如实标注" in out or "基于现场判断" in out, out[-200:])
    check("标注共享范围（防读成全系统）", "同一克隆共享" in out or "检出内" in out, out[-200:])
    check("沙箱（无 .git）退化为检出内路径", "检出内" in out, out[-200:])
    # 旧实现（SKILL.md 原内联命令）在同一环境下的行为——留档对比
    old = ("import yaml;d=yaml.safe_load(open('metrics/skill-exec-log.yaml'));"
           "print('\\n'.join(f\"{r['seq']} {r['skill']} {r.get('at','')[:16]}\" for r in (d.get('records') or [])[-3:]))")
    rc_old, out_old = py(root, "-c", old)
    check("（对照）旧内联命令在此环境下抛异常 = 断点可复现", rc_old != 0 and "No such file" in out_old,
          out_old[-160:])


# ---------------------------------------------------------------- ② 内容流程收尾落记录
def ex_content_flow_log(root: Path):
    print("\n[E2] 内容流程收尾 · 落 exec-log → 读现场")
    rc, out = py(root, "scripts/log_skill_exec.py", "--skill", "to-reference",
                 "--products", "msprof-x(active)", "--reason", "归纳 3 case 为一条 methodology",
                 "--source", "to-reference", "--tokens", "5000")
    check("log_skill_exec 写入成功", rc == 0, out[-200:])
    rc, out = py(root, "scripts/tail_exec_log.py")
    check("tail_exec_log 能读出刚落的记录", rc == 0 and "to-reference" in out, out[-300:])
    check("产出 id/状态被带出", "msprof-x(active)" in out, out[-200:])
    check("decision_reason 被带出", "归纳 3 case" in out, out[-200:])
    # 旧内联命令在有记录时的行为——留档对比（datetime 不可下标）
    old = ("import yaml;d=yaml.safe_load(open('metrics/skill-exec-log.yaml'));"
           "print('\\n'.join(f\"{r['seq']} {r['skill']} {r.get('at','')[:16]}\" for r in (d.get('records') or [])[-3:]))")
    rc_old, out_old = py(root, "-c", old)
    check("（对照）旧内联命令在有记录时抛 TypeError = 断点可复现",
          rc_old != 0 and "subscriptable" in out_old, out_old[-220:])
    rc, out = py(root, "scripts/verify_exec_log.py", "--check")
    check("exec-log 自查（seq 唯一/字段齐全）通过", rc == 0, out[-200:])


# ---------------------------------------------------------------- ③ 有信号：产卡→验证→自落记录→面板数据
def ex_signal_path(root: Path):
    print("\n[E3] evolve-check 有信号 · 产卡 → 校验 → 自落记录 → 看板可见")
    rc, out = py(root, "scripts/ev_proposal.py", "--new")
    check("ev_proposal --new 产骨架", rc == 0 and "已生成骨架" in out, out[-200:])
    card_path = next(root.glob("proposals/ideas/EV-*.yaml"), None)
    new_cards = sorted((root / "proposals" / "ideas").glob("EV-*.yaml"))
    card_path = new_cards[-1]
    card = yaml.safe_load(card_path.read_text(encoding="utf-8"))
    cid = card["id"]

    # 只记 proposal（在途态）：新规则不该误报
    card.update({
        "title": "演练卡（rehearse_evolve_loop）",
        "status": "in_experiment",
        "authorization": "review",
        "dimension": "process",
        "layer": "L2",
        "hypothesis": "演练：动作 + 验证 + 判断三步齐备后卡可闭合",
        "validation": {"method": "scan_review", "baseline": "—", "success_criteria": "—", "rollback": "git revert"},
        "risk": "low",
        "principle_refs": [2, 8, 10, 11],
        "source_signals": [{"signal": "process_friction", "evidence": "演练信号",
                            "trajectory": ["scripts/rehearse_evolve_loop.py"]}],
        "actual_cost": None,
        "decisions": [{"who": "agent", "when": "2026-09-10", "type": "proposal", "conclusion": "演练产卡"}],
    })
    card_path.write_text(yaml.safe_dump(card, allow_unicode=True, sort_keys=False), encoding="utf-8")
    rc, out = py(root, "scripts/verify_proposals.py", "--check")
    check("在途卡（只记 proposal）不误报", rc == 0, out[-300:])

    # 反例：只记 action（验证还在跑）也不该误报——首版规则在这里误报过
    card["decisions"].append({"who": "agent", "when": "2026-09-10", "type": "action", "conclusion": "演练执行"})
    card_path.write_text(yaml.safe_dump(card, allow_unicode=True, sort_keys=False), encoding="utf-8")
    rc, out = py(root, "scripts/verify_proposals.py", "--check")
    check("在途卡（只记 action、验证未跑）不误报", rc == 0, out[-300:])

    # 执行 + 验证都完成但没判断 → 必须报
    card["decisions"].append({"who": "agent", "when": "2026-09-10", "type": "eval", "conclusion": "演练验证"})
    card_path.write_text(yaml.safe_dump(card, allow_unicode=True, sort_keys=False), encoding="utf-8")
    rc, out = py(root, "scripts/verify_proposals.py", "--check")
    check("卡不完整（action+eval 齐但无 decision）被拦", rc != 0 and "卡不完整" in out, out[-300:])

    # 补判断 → 终态（validated 需 actual_cost.tokens，否则报成本缺口）
    card["status"] = "validated"
    card["decisions"].append({"who": "agent", "when": "2026-09-10", "type": "decision", "conclusion": "演练采纳"})
    card_path.write_text(yaml.safe_dump(card, allow_unicode=True, sort_keys=False), encoding="utf-8")
    rc, out = py(root, "scripts/verify_proposals.py", "--check")
    check("validated 缺 actual_cost.tokens 被拦（成本审计）", rc != 0 and "成本审计缺口" in out, out[-300:])
    card["actual_cost"] = {"tokens": 0, "source": "estimate", "note": "演练"}
    card_path.write_text(yaml.safe_dump(card, allow_unicode=True, sort_keys=False), encoding="utf-8")
    rc, out = py(root, "scripts/verify_proposals.py", "--check")
    check("补齐成本后卡闭合、校验通过", rc == 0, out[-300:])

    # evolve-check 自落记录（有信号分支）
    rc, out = py(root, "scripts/log_skill_exec.py", "--skill", "evolve-check",
                 "--products", f"{cid}(validated)", "--reason", "T3 信号 → 产卡并自验证采纳",
                 "--source", "to-reference", "--tokens", "8000")
    check("evolve-check 自落收尾记录", rc == 0, out[-200:])
    rc, out = py(root, "scripts/ev_board_data.py")
    try:
        board = json.loads(out)
    except Exception as e:
        board = {}
        check("看板数据可解析", False, f"{e} :: {out[:200]}")
    se = board.get("skill_exec") or {}
    check("看板 skill_exec 段存在且 present", bool(se.get("present")), json.dumps(se, ensure_ascii=False)[:200])
    check("看板显示 evolve-check 收尾 ≥1 次", (se.get("evolve_check_runs") or 0) >= 1, str(se.get("evolve_check_runs")))
    check("看板带出最后一条收尾的卡号",
          any(cid in p for r in [se.get("last_evolve_check") or {}] for p in (r.get("products") or [])),
          str(se.get("last_evolve_check"))[:200])
    check("看板标注共享范围口径", "同一克隆共享" in (se.get("note") or "") or "检出内" in (se.get("note") or ""),
          str(se.get("note"))[:120])
    check("看板带聚合视图（供 --summary→timeline 用）", isinstance(se.get("aggregate"), dict)
          and se["aggregate"].get("total") == se.get("total"), json.dumps(se.get("aggregate"), ensure_ascii=False)[:160])
    return cid


# ---------------------------------------------------------------- ④ 无信号分支
def ex_no_signal(root: Path):
    print("\n[E4] evolve-check 无信号 · 也要可见（否则'跑了无信号'与'没跑'不可区分）")
    rc, out = py(root, "scripts/log_skill_exec.py", "--skill", "evolve-check",
                 "--reason", "收尾无演进信号", "--source", "knowledge-groom", "--tokens", "3000")
    check("无信号收尾落记录成功", rc == 0, out[-200:])
    rc, out = py(root, "scripts/ev_board_data.py")
    se = (json.loads(out).get("skill_exec") or {})
    check("看板 evolve-check 次数 = 2", se.get("evolve_check_runs") == 2, str(se.get("evolve_check_runs")))
    check("看板单列 no-signal 计数 = 1", se.get("evolve_check_no_signal") == 1, str(se.get("evolve_check_no_signal")))
    rc, out = py(root, "scripts/tail_exec_log.py", "--skill", "evolve-check")
    check("按 skill 过滤能只看收尾记录", "收尾无演进信号" in out and "to-reference" not in out, out[-260:])


# ---------------------------------------------------------------- ⑤ 负例：其余规则真的会触发
def ex_negative_rules(root: Path):
    print("\n[E5] 负例 · 其余三条规则必须真的红（不是纸面规则）")
    base = (root / "proposals" / "ideas" / "EV-2099-001.yaml")
    good = {
        "id": "EV-2099-001", "layer": "L2", "title": "负例基卡", "status": "in_experiment",
        "authorization": "review", "dimension": "process", "created_at": "2026-09-10",
        "source_signals": [{"signal": "process_friction", "evidence": "e", "trajectory": ["t"]}],
        "hypothesis": "h", "validation": {"method": "scan_review"}, "risk": "low",
        "principle_refs": [2], "decisions": [], "supersedes": [], "superseded_by": None,
    }
    import copy
    import datetime

    def write(doc):
        base.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # ① 僵尸卡：在实验 40 天、只有 proposal
    z = copy.deepcopy(good)
    z["created_at"] = str(datetime.date.today() - datetime.timedelta(days=40))
    z["decisions"] = [{"who": "a", "when": "x", "type": "proposal", "conclusion": "c"}]
    write(z)
    rc, out = py(root, "scripts/verify_proposals.py", "--check")
    check("僵尸卡（≥14 天未闭合）被拦", rc != 0 and "僵尸卡" in out, out[-260:])

    # ② 出处缺失：source_signals 没有 trajectory
    t = copy.deepcopy(good)
    t["source_signals"] = [{"signal": "process_friction", "evidence": "e"}]
    t["decisions"] = [{"who": "a", "when": "x", "type": "decision", "conclusion": "c"}]
    write(t)
    rc, out = py(root, "scripts/verify_proposals.py", "--check")
    check("缺 trajectory（无出处）被拦", rc != 0 and "trajectory" in out, out[-260:])

    # ③ 终态卡无 decision
    n = copy.deepcopy(good)
    n["status"] = "validated"
    n["actual_cost"] = {"tokens": 0, "source": "estimate"}
    n["decisions"] = [{"who": "a", "when": "x", "type": "proposal", "conclusion": "c"}]
    write(n)
    rc, out = py(root, "scripts/verify_proposals.py", "--check")
    check("终态卡缺 agent 判断被拦", rc != 0, out[-260:])

    # ④ 清掉负例卡 → 恢复绿
    base.unlink()
    rc, out = py(root, "scripts/verify_proposals.py", "--check")
    check("移除负例卡后恢复通过（规则无残留副作用）", rc == 0, out[-260:])


# ---------------------------------------------------------------- ⑥ 卡号分配安全
def ex_card_id_safety(root: Path):
    """产卡链的机械环节：卡号分配不得撞号、不得静默覆盖既有卡。

    2026-09-10 实测过的真实事故面：`make_new()` 是直接覆盖写，而 `next_id()` 只看卡内
    `id:` 字段——一旦文件名与该字段不一致，算出的"下一个号"会撞上一个已存在的文件名，
    于是**静默吃掉一张既有卡**（我自己 `mv` 覆盖骨架时触发过一次同类事故）。这里把三类
    场景钉成固定断言：正常递增、字段/文件名不一致、目标文件已存在。
    """
    print("\n[E8] 卡号分配安全 · 不撞号、不覆盖")
    import hashlib
    import yaml as _yaml

    ideas = root / "proposals" / "ideas"

    def sha(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()

    # ① 正常递增：--next 的号必须与 --new 实际创建的号一致，且两次 --new 得到两个不同号
    rc, out = py(root, "scripts/ev_proposal.py", "--next")
    nxt = out.strip()
    rc2, out2 = py(root, "scripts/ev_proposal.py", "--new")
    made = sorted(ideas.glob("EV-*.yaml"))[-1]
    check("--next 与 --new 的卡号一致（" + nxt + "）", rc == 0 and rc2 == 0 and made.stem == nxt, out2[-200:])
    first_hash = sha(made)
    rc3, out3 = py(root, "scripts/ev_proposal.py", "--new")
    second = sorted(ideas.glob("EV-*.yaml"))[-1]
    check("连产两张卡得两个不同号、且第一张未被覆盖",
          rc3 == 0 and second != made and sha(made) == first_hash, out3[-200:])
    second.unlink()          # 清掉第二张骨架，别影响后续断言

    # ② 文件名与 id 字段不一致（复制粘贴手误）→ 必须避开"已占用的文件名"。
    #    构造旧算法**必然踩中**的精确条件：文件名叫 EV-<base+1>.yaml（= 旧算法算出的下一个号），
    #    内容 id 却写成更小的号。旧代码只看 id 字段 → 算出 base+1 → 覆盖写这个已存在的文件
    #    = 静默吃掉既有卡。这里同时留一条"对照"断言，证明缺陷路径可复现、修复不是空谈。
    id_nums = []
    for f in ideas.glob("EV-*.yaml"):
        d = _yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        cid = str(d.get("id", ""))
        parts = cid.split("-")
        if len(parts) == 3 and parts[1] == str(__import__("datetime").datetime.now().year):
            try:
                id_nums.append(int(parts[2]))
            except ValueError:
                pass
    base = max(id_nums)
    victim = ideas / f"EV-2026-{base + 1:03d}.yaml"
    victim.write_text(f"# 既有卡（文件名 {base + 1} / 字段 {base - 5}）\nid: EV-2026-{base - 5:03d}\n",
                      encoding="utf-8")
    before = victim.read_bytes()
    check(f"（对照）旧算法算出的号 {base + 1} 正是刚占用的文件名 = 覆盖路径可复现",
          victim.stem == f"EV-2026-{base + 1:03d}")
    rc, out = py(root, "scripts/ev_proposal.py", "--next")
    new_next = int(out.strip().split("-")[-1]) if rc == 0 and out.strip() else -1
    check("新算法避开已占文件名（返回号 > 被占号）", rc == 0 and new_next > base + 1, out.strip())
    rc, out = py(root, "scripts/ev_proposal.py", "--new")
    check("产卡不动那张'文件名/字段不一致'的既有卡", victim.read_bytes() == before, out[-200:])
    for f in ideas.glob(f"EV-2026-{new_next:03d}.yaml"):
        f.unlink()
    victim.unlink()

    # ③ 覆盖保护：直接把 make_new 指向一个已存在的目标，断言"拒绝写、原文件字节不变"。
    #    为什么用单元级调用（monkeypatch next_id）而不是端到端：next_id 修好后会把已占用的
    #    文件名也算进去，正常路径**永远不会**算出已存在的号——该分支只能被并发产卡 / 异常
    #    文件状态推到。（先写的端到端版本实测走不到、断言假失败，据实改成直击分支。）
    unit = '''
import sys
from pathlib import Path
sys.path.insert(0, "scripts")
import ev_proposal as ep

root = Path(".").resolve()
target = root / "proposals" / "ideas" / "EV-2026-777.yaml"
target.write_text("# 既有卡：不许被覆盖\\nid: EV-2026-777\\n", encoding="utf-8")
before = target.read_bytes()

ep.next_id = lambda r: "EV-2026-777"          # 模拟"分配到已被占用的号"
sys.argv = ["ev_proposal.py", "--new"]
try:
    ep.main()
except SystemExit as e:
    code = e.code
else:
    code = 0
print("REFUSED" if code not in (0, None) else "NO-REFUSAL", "exit=", code)
print("INTACT" if target.read_bytes() == before else "OVERWRITTEN")
target.unlink()
'''
    rc, out = py(root, "-c", unit)
    check("目标号被占用时拒绝产卡、非零退出（exit 2）", "REFUSED" in out and "exit= 2" in out, out[-260:])
    check("拒绝时既有卡字节不变（未被静默覆盖）", "INTACT" in out, out[-200:])
    rc, out = py(root, "scripts/verify_proposals.py", "--check")
    check("清理后卡池校验仍通过（断言无残留副作用）", rc == 0, out[-200:])
    made.unlink()


# ---------------------------------------------------------------- ⑦ 共享 exec-log
def ex_shared_exec_log(root: Path):
    """exec-log 的共享语义 + 并发锁（2026-09-10 修的结构缺陷）。

    缺陷本体：记录原先写在"各 worktree 的检出内"且是 .gitignore 件，而本仓库强制每个 agent
    在独立 worktree 干活 → 代理落的记录**主检出（= 用户会话 cwd / 面板读处）读不到**，
    worktree 一清记录随之消失。修法：路径解析到主检出（同一克隆共享），写侧持 flock。
    这里用一个临时 git 仓库 + 两个真实 linked worktree 来验证（沙箱自己无 .git，测不到这点）。
    """
    print("\n[E9] 共享 exec-log · 跨 worktree 可见 + worktree 清理不丢 + 并发不覆盖")
    import shutil as _sh
    import subprocess as _sp

    if _sh.which("git") is None:
        print("  — 跳过（无 git）")
        return
    demo = root.parent / "sharedlog-demo"
    wt1, wt2 = root.parent / "sharedlog-wt1", root.parent / "sharedlog-wt2"
    for p in (demo, wt1, wt2):
        _sh.rmtree(p, ignore_errors=True)
    demo.mkdir(parents=True)
    (demo / "metrics").mkdir()
    (demo / "metrics" / "timeline.yaml").write_text("periods: []\n", encoding="utf-8")
    _sh.copytree(root / "scripts", demo / "scripts")
    _sp.run(["git", "init", "-q"], cwd=demo, check=True)
    _sp.run(["git", "add", "-A"], cwd=demo, check=True)
    _sp.run(["git", "-c", "user.email=r@x", "-c", "user.name=r", "commit", "-qm", "init"], cwd=demo, check=True)
    _sp.run(["git", "worktree", "add", "-q", str(wt1), "-b", "kb/wt1"], cwd=demo, check=True)
    _sp.run(["git", "worktree", "add", "-q", str(wt2), "-b", "kb/wt2"], cwd=demo, check=True)

    # ① 从 worktree 落一条 → 主检出立刻能读到（这是修复的核心目标）
    rc, out = py(wt1, "scripts/log_skill_exec.py", "--skill", "to-reference",
                 "--products", "ref-x(active)", "--reason", "共享语义实测", "--source", "to-reference")
    check("worktree 写入解析到主检出共享件", rc == 0 and "同一克隆共享" in out, out[-220:])
    rc, out = py(demo, "scripts/tail_exec_log.py")
    check("主检出立刻读到 worktree 落的记录（修前读不到）", rc == 0 and "共享语义实测" in out, out[-260:])

    # ② 并发写：两个 worktree 各 5 条 → 全在、seq 唯一（锁的证据）
    old_n = len([1 for line in (demo / "metrics" / "skill-exec-log.yaml").read_text(encoding="utf-8").splitlines()
                 if line.strip().startswith("- seq:")])
    procs = []
    for i in range(5):
        for wt, tag in ((wt1, "w1"), (wt2, "w2")):
            procs.append(_sp.Popen([sys.executable, "scripts/log_skill_exec.py", "--skill", "evolve-check",
                                    "--reason", f"无演进信号 {tag}-{i}", "--source", "to-reference", "--tokens", "1"],
                                   cwd=str(wt), stdout=_sp.DEVNULL, stderr=_sp.DEVNULL))
    for p in procs:
        p.wait()
    rc, out = py(demo, "scripts/verify_exec_log.py", "--check")
    n_new = len([1 for line in (demo / "metrics" / "skill-exec-log.yaml").read_text(encoding="utf-8").splitlines()
                 if line.strip().startswith("- seq:")])
    check(f"10 条并发写入全部落盘（{old_n} → {n_new}）且 seq 唯一", rc == 0 and n_new == old_n + 10, out[-260:])

    # ③ 聚合视图（供 --summary → metrics/timeline.yaml 的跨机口径）
    rc, out = py(demo, "scripts/tail_exec_log.py", "--summary")
    check("聚合视图给出收尾次数与无信号次数",
          rc == 0 and "evolve-check 收尾 10 次" in out and "无信号 10 次" in out, out[-300:])

    # ④ worktree 清理不丢数据（修前：记录随 worktree 消失）
    _sp.run(["git", "worktree", "remove", "--force", str(wt1)], cwd=demo, check=True)
    rc, out = py(demo, "scripts/tail_exec_log.py", "--skill", "to-reference")
    check("worktree 被清后记录仍在（数据不再随 worktree 消失）", rc == 0 and "共享语义实测" in out, out[-260:])

    # ⑤ 无 git 环境退化为检出内路径（沙箱/CI 的隔离性）
    rc, out = py(root, "scripts/tail_exec_log.py")
    check("无 git 沙箱退化为检出内路径（隔离不被破坏）", "检出内" in out, out[-200:])
    for p in (demo, wt2):
        _sh.rmtree(p, ignore_errors=True)


# ---------------------------------------------------------------- ⑧ metrics 闭环
def ex_metrics_loop(root: Path):
    """metrics 的产出→入库→判据→检测→动作这条腿（2026-09-10 审计：原先只有"产出"和"入库"，
    检测腿是空的——按旧流程跑一遍不会被告知"结构指标 10 天没更新 / 格子 85/30 越界 /
    反馈为 0 导致误诊率不可解读"）。

    三组断言：①组装命令覆盖各来源；②在真实数据上，检测器必须把**真实存在的**越界与
    不可解读报出来；③合成的"健康"与"崩坏"两份数据：前者不许哭狼（`--check` 为 0），
    后者必须全中并非零。
    """
    print("\n[E10] metrics 闭环 · 组装覆盖全部来源 + 检测器该红必红、不该红不哭狼")
    import shutil as _sh

    # ① 组装：把真实 traces 拷进演练场（沙箱默认不含 traces/，它是各检出各一份的运行时件），
    #    验证诊断侧也会被组装进来。注意 traces 只在**主检出**里——本演练自己就活在 worktree 里，
    #    直接读 REPO/traces 会读不到（这正是 metrics_snapshot 要自动解析该读哪一份的原因）。
    import sys as _sys
    _sys.path.insert(0, str(REPO / "scripts"))
    from exec_log_path import main_checkout
    real_root = main_checkout(REPO) or REPO
    src_traces = real_root / "traces"
    dst_traces = root / "traces"
    if src_traces.is_dir():
        _sh.rmtree(dst_traces, ignore_errors=True)
        _sh.copytree(src_traces, dst_traces)
    rc, out = py(root, "scripts/metrics_snapshot.py", "--json")
    try:
        snap = json.loads(out)
    except Exception as e:
        snap = {}
        check("metrics_snapshot 输出可解析", False, f"{e} :: {out[:200]}")
    s = snap.get("sources") or {}
    check("组装覆盖结构侧", "structural_side" in s, str(list(s)))
    check("组装覆盖内容流程侧", "content_flow_side" in s, str(list(s)))
    check("组装覆盖诊断侧（真实 traces 已拷入）", "diagnose_side" in s, str(s.get("diagnose_side"))[:120])
    check("结构侧带出真实 case 总数", isinstance((snap.get("metrics") or {}).get("case_total"), int),
          str((snap.get("metrics") or {}).get("case_total")))
    check("拿不到的块如实点名（不写 0 冒充）", isinstance(snap.get("missing"), list))

    # ② 真实数据上的检测器：必须报出真实存在的越界与不可解读
    rc, out = py(root, "scripts/metrics_health.py", "--json")
    try:
        h = json.loads(out)
    except Exception:
        h = {}
    texts = " ".join(f.get("text", "") for f in (h.get("findings") or []))
    check("检测器报出容量越界（真实 85/30）", "interrupt = 85/30" in texts, texts[:200])
    check("检测器报出反馈下限被触发", "捕获反馈 0 条" in texts or "feedback" in texts.lower(), texts[:200])
    check("检测器把 misdiagnosis_rate 标为不可解读", "misdiagnosis_rate：不可解读" in texts, texts[:200])
    check("真实数据上 --check 非零（有 ✗ 未处理）", py(root, "scripts/metrics_health.py", "--check")[0] != 0)

    # ③ 两份合成数据：健康的不许哭狼；崩坏的必须全中
    tl_path = root / "metrics" / "timeline.yaml"
    idx_path = root / "knowledge" / "_index.yaml"
    tl_backup, idx_backup = tl_path.read_text(encoding="utf-8"), idx_path.read_text(encoding="utf-8")
    idx_small = ("# GENERATED FILE —— 由 scripts/build_index.py 生成，不要手改。\n"
                 "# 生成日期：2026-09-10    case 总数：20\n"
                 "#   容量(inference/vllm-ascend): interrupt=5/30\n")
    from datetime import date, timedelta

    def make_timeline(recorded, feedback, cell_count, case_total=20, attr_case=1):
        return yaml.safe_dump({"periods": [{
            "period": "2026-W37-live", "kind": "live", "title": "合成",
            "recorded_at": recorded, "source": "合成（演练）",
            "metrics": {
                "sessions_total": 3, "tier2_hit": 1,
                "misdiagnosis_rate": {"ok": 0, "total": 1},
                "attribution_ratio": {"case_error": attr_case, "execution_error": 0},
                "feedback_capture": {"resolved": feedback, "not_resolved": 0, "partial": 0},
                "case_total": case_total,
                "capacity_by_ns": {"inference/vllm-ascend": {"interrupt": {"count": cell_count, "cap": 30}}},
            },
        }]}, allow_unicode=True, sort_keys=False)

    try:
        # ③a 健康：今天的一期、有反馈、有归因、格子未越界 → 不许有 ✗（不哭狼）
        idx_path.write_text(idx_small, encoding="utf-8")
        tl_path.write_text(make_timeline(date.today().isoformat(), 1, 5), encoding="utf-8")
        rc, out = py(root, "scripts/metrics_health.py", "--json", "--check")
        h2 = json.loads(out)
        check("健康数据上不哭狼（0 项 ✗，--check 为 0）", h2.get("fail_count") == 0 and rc == 0,
              json.dumps([f for f in h2.get("findings") or [] if f.get("level") != "ok"], ensure_ascii=False)[:300])
        # ③b 崩坏：30 天前的一期 + **现实格子 70**（超 hard_cap）+ 反馈 0 + 无归因 → 必须全中且非零。
        #     注意容量越界判的是"当前现实"（_index 头注），不是快照旧值——头注也要跟着坏（测试口径）
        idx_path.write_text(idx_small.replace("interrupt=5/30", "interrupt=70/30"), encoding="utf-8")
        tl_path.write_text(make_timeline((date.today() - timedelta(days=30)).isoformat(), 0, 70, attr_case=0),
                           encoding="utf-8")
        rc, out = py(root, "scripts/metrics_health.py", "--json", "--check")
        h3 = json.loads(out)
        t3 = " ".join(f.get("text", "") for f in (h3.get("findings") or []))
        check("崩坏数据：报陈旧", "超期" in t3, t3[:200])
        check("崩坏数据：报 soft_cap 与 hard_cap 越界", t3.count("interrupt = 70/30") >= 2, t3[:200])
        check("崩坏数据：报反馈下限 + 不可解读", "不可解读" in t3, t3[:200])
        check("崩坏数据：--check 非零", rc != 0, f"rc={rc}")
    finally:
        tl_path.write_text(tl_backup, encoding="utf-8")
        idx_path.write_text(idx_backup, encoding="utf-8")
    rc, out = py(root, "scripts/verify_metrics.py", "--check")
    check("还原后 timeline 结构仍合法", rc == 0, out[-200:])


# ---------------------------------------------------------------- ⑨ CI parity
def ex_ci_parity(root: Path):
    print("\n[E6] CI parity · kb-checks 的每条命令在本地逐条复跑")
    wf_path = root / ".github" / "workflows" / "kb-checks.yml"
    wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    on = wf.get(True) or wf.get("on") or {}
    for ev in ("push", "pull_request"):
        paths = ((on.get(ev) or {}).get("paths") or [])
        check(f"{ev} 触发路径含 proposals/**", "proposals/**" in paths, str(paths)[:160])
    jobs = wf.get("jobs") or {}
    check("存在 proposal-audit job", "proposal-audit" in jobs, str(list(jobs)))
    cmds = []
    for jname, job in jobs.items():
        for step in job.get("steps") or []:
            if step.get("run"):
                cmds.append((jname, step["run"].strip()))
    check("proposal-audit 跑 verify_proposals --check",
          any("verify_proposals.py --check" in c for j, c in cmds if j == "proposal-audit"))
    check("CI 不跑 verify_exec_log（运行时件，CI 上不存在，跑了只会空转）",
          not any("verify_exec_log" in c for _, c in cmds))
    for jname, cmd in cmds:
        rc, out = run(["bash", "-c", cmd], cwd=root)
        label = f"[{jname}] {cmd.splitlines()[0][:70]}"
        check(f"CI 命令通过 {label}", rc == 0, out[-260:])
    return cmds


# ---------------------------------------------------------------- ⑩ 面板渲染断言
def ex_panel(root: Path, enabled: bool):
    print("\n[E7] 面板渲染断言（ev-panel 执行现场区块 + 既有断言不回归）")
    if not enabled:
        print("  — 跳过（--no-panel）")
        return
    if shutil.which("node") is None:
        print("  — 跳过（无 node）")
        return
    rc, out = run(["node", "scripts/panel_render_check.js"], cwd=root)
    tail = "\n".join(out.strip().splitlines()[-3:])
    check("panel_render_check 全绿", rc == 0 and "全部通过" in out, tail + " :: " + out[-400:])
    check("执行现场区块断言在其中", "执行现场" in out, tail)


def main():
    ap = argparse.ArgumentParser(description="evolve-check 闭环端到端演练")
    ap.add_argument("--no-panel", action="store_true", help="跳过 node 面板断言")
    ap.add_argument("--keep", action="store_true", help="保留临时副本")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="evloop-rehearsal-"))
    sandbox = tmp / "repo"
    print(f"演练场：{sandbox}")
    make_copy(sandbox)
    try:
        ex_degraded(sandbox)
        ex_content_flow_log(sandbox)
        ex_signal_path(sandbox)
        ex_no_signal(sandbox)
        ex_negative_rules(sandbox)
        ex_card_id_safety(sandbox)
        ex_shared_exec_log(sandbox)
        ex_metrics_loop(sandbox)
        ex_ci_parity(sandbox)
        ex_panel(sandbox, not args.no_panel)
    finally:
        if args.keep:
            print(f"\n保留演练场：{sandbox}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n断言 {COUNT - len(FAILS)}/{COUNT} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("闭环演练：全部通过")
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
