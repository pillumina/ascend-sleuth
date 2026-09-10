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
    check("标注本地件（防读成全系统）", "跨 worktree/克隆不聚合" in out, out[-200:])
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
    check("看板标注本地件口径", "不聚合" in (se.get("note") or ""), str(se.get("note"))[:120])
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


# ---------------------------------------------------------------- ⑥ CI parity
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
    check("CI 不跑 verify_exec_log（本地件，跑了只会空转）",
          not any("verify_exec_log" in c for _, c in cmds))
    for jname, cmd in cmds:
        rc, out = run(["bash", "-c", cmd], cwd=root)
        label = f"[{jname}] {cmd.splitlines()[0][:70]}"
        check(f"CI 命令通过 {label}", rc == 0, out[-260:])
    return cmds


# ---------------------------------------------------------------- ⑦ 面板渲染断言
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
