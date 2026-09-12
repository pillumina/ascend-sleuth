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
import shlex
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


def q(path):
    """在 shell 命令里安全引用一个路径：POSIX 用 shlex.quote，Windows 用双引号。

    shlex.quote 在 Windows 上产**单引号**，而 cmd.exe 不认单引号——`'C:\\...\\python.exe' -c ...`
    会被当成"名字里带引号的程序"而报 9009（命令不存在）。这是本脚本在 Windows 上
    "正例 --run 判 PASS" 失败的原因，与解释器是否存在无关。
    """
    s = str(path)
    return f'"{s}"' if os.name == "nt" else shlex.quote(s)


def ci_local_argv(cmd: str):
    """**仅 Windows**：CI 的单行命令 → 本地 argv；返回 None 表示仍交给 shell。

    Windows 上 `python3` 是 Microsoft Store 的应用执行别名占位程序（既不打印版本也不
    返回 0），`pip` 也不是可执行文件——照抄 CI 的 shell 片段必然失败，而那失败会被读成
    "CI 检查在本机不通过"（其实与检查内容无关）。单行步骤改为按 argv 直接执行：
    `python3` → 当前解释器、`pip` → `当前解释器 -m pip`。这**比走 bash 更忠实**：同一程序、
    同一参数，且不依赖本机是否装了 POSIX shell。

    POSIX 上**直接返回 None**（即完全走原来的 `bash -c`）：那里 `python3`/`pip` 本就是可用
    可执行文件，改成本地 argv 只会引入无谓差异（例如某些发行版的 `pip` 与
    `python -m pip` 并不指向同一环境）。
    """
    if os.name != "nt":
        return None
    line = cmd.strip()
    if not line or "\n" in line:
        return None
    try:
        parts = shlex.split(line)
    except ValueError:
        return None
    if not parts:
        return None
    if parts[0] == "python3":
        return [sys.executable, *parts[1:]]
    if parts[0] == "pip":
        return [sys.executable, "-m", "pip", *parts[1:]]
    return None


def run(args, cwd, env=None):
    e = dict(os.environ)
    e["PYTHONIOENCODING"] = "utf-8"
    # PYTHONUTF8=1：让子进程的 Python 走 UTF-8 模式（`open()` 默认 UTF-8、标准流 UTF-8）。
    # 这不是"给 Windows 开后门"，而是**让本机与 CI 的默认行为一致**：Linux 上 locale 默认
    # 就是 UTF-8，而中文 Windows 上 `open('triage-tree.yaml')` 按 GBK 解码 → 那份含中文
    # 注释的文件直接 UnicodeDecodeError，CI 里那条 triage-tree 语法检查在本机永远跑不过
    # ——失败原因（本机编码）与检查内容（YAML 可解析性）无关，属误报。
    e["PYTHONUTF8"] = "1"
    if env:
        e.update(env)
    r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, env=e, encoding="utf-8", errors="replace")
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
    enc_first = any(k in out_old for k in ("ReaderError", "codec", "decode", "UnicodeDecodeError"))
    # 历史断点：`at` 未加引号 → PyYAML 读成 datetime → `[:16]` 直接 TypeError（内联版必崩）。
    # 写侧改为带引号 ISO 字符串后**该断点已修**，所以这里断言"不再因类型崩溃"而不是"必失败"。
    # 编码那一层仍可能拦下内联版（open() 未指定 encoding），但不作为判据——"别内联"的真正理由
    # 是脚本自带路径解析 / 共享范围标注 / 退化口径三件，内联版都没有。
    check("（对照）旧内联命令不再因 at 类型崩溃（datetime 断点已修）",
          "subscriptable" not in out_old,
          out_old[-220:] + ("（本平台另被默认编码拦下——同一「别内联」理由的另一种表现）"
                            if enc_first else ""))
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
        "predicted_effect": {          # 本条不是占位：演练卡的预测就是"结构合法、校验通过"
            "metric": "演练卡的结构合法性",
            "from": "骨架态（measure 为占位）被 verify_proposals 拦下",
            "to": "补齐结构后 --check 通过（exit 0）",
            "measure": {"command": "python3 scripts/verify_proposals.py --check", "expect_exit": 0},
        },
        "validation": {"method": "scan_review", "baseline": "—", "success_criteria": "—", "rollback": "git revert"},
        "risk": "low",
        "principle_refs": [2, 8, 10, 11],
        "source_signals": [{"signal": "process_friction", "evidence": "演练信号",
                            "trajectory": ["scripts/rehearse_evolve_loop.py"]}],
        "actual_cost": None,
        # 结论刻意写长（最长那条 >70 字）：面板渲染断言用"**被展开卡**的最长 conclusion 是否
        # 完整出现在渲染文本中"来验证全文未被截断，而它挑的是按 created_at 降序排第一的卡。
        # 本演练每轮都会新产一张卡（created_at = 当天），所以当"当天晚于最新已提交卡的日期"时，
        # 本卡**就是**排第一的那张——结论若只有"演练产卡"这种 4 字短句，那条断言必然失败
        # （2026-09-11 实测：macOS 复现，Linux 亦复现，与平台无关）。夹具应当长成断言所假设的
        # 样子：**别为了"简洁"把这几条改短**。
        "decisions": [{"who": "agent", "when": "2026-09-10", "type": "proposal",
                       "conclusion": "演练：产卡即执行——方案成形后先落卡，记录 layer / title / "
                                     "source_signals 等字段并把状态置为 in_experiment；本轮目的是"
                                     "验证卡结构与生命周期规则的机器可判性，不产生真实知识变更。"}],
    })
    card_path.write_text(yaml.safe_dump(card, allow_unicode=True, sort_keys=False), encoding="utf-8")
    rc, out = py(root, "scripts/verify_proposals.py", "--check")
    check("在途卡（只记 proposal）不误报", rc == 0, out[-300:])

    # 反例：只记 action（验证还在跑）也不该误报——首版规则在这里误报过
    card["decisions"].append({"who": "agent", "when": "2026-09-10", "type": "action",
                              "conclusion": "演练：只追加一条 action 记录（验证仍在跑）——用于证明"
                                            "『只记 action』属正常中间态、校验器不应报错；随后再"
                                            "补齐 eval 与 decision，把卡推进到终态。"})
    card_path.write_text(yaml.safe_dump(card, allow_unicode=True, sort_keys=False), encoding="utf-8")
    rc, out = py(root, "scripts/verify_proposals.py", "--check")
    check("在途卡（只记 action、验证未跑）不误报", rc == 0, out[-300:])

    # 执行 + 验证都完成但没判断 → 必须报
    card["decisions"].append({"who": "agent", "when": "2026-09-10", "type": "eval",
                              "conclusion": "演练：追加 eval 记录——按影响面分级，本例属纯文档/注释面，"
                                            "不跑 replay，只做 scan + 人审；判据是生命周期三阶段齐备"
                                            "后，校验器能正确区分『中间态』与『未闭合』两种情形。"})
    card_path.write_text(yaml.safe_dump(card, allow_unicode=True, sort_keys=False), encoding="utf-8")
    rc, out = py(root, "scripts/verify_proposals.py", "--check")
    check("卡不完整（action+eval 齐但无 decision）被拦", rc != 0 and "卡不完整" in out, out[-300:])

    # 补判断 → 终态（validated 需 actual_cost.tokens，否则报成本缺口）
    card["status"] = "validated"
    card["decisions"].append({"who": "agent", "when": "2026-09-10", "type": "decision",
                              "conclusion": "演练：追加 decision 记录并置 validated——结论是四条生命"
                                            "周期规则（终态需判断、validated 需成本、执行完未推进、"
                                            "僵尸卡）都能被机械拦住；本卡是演练夹具，不代表真实决策。"})
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
    # 先清掉 --new 产出的骨架卡再校验：骨架的 measure 是刻意留的占位（EV-2026-050），
    # 本断言问的是"清理后有无残留副作用"，与骨架自身是否合法无关——骨架的合法性由
    # [E11] 断言。留在卡池里会让本断言依赖当天日期（cutover 前后结论相反）。
    made.unlink()
    rc, out = py(root, "scripts/verify_proposals.py", "--check")
    check("清理后卡池校验仍通过（断言无残留副作用）", rc == 0, out[-200:])


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
        # 容量**一个格子只报一条**（2026-09 七轮的设计）：格子同时越过 soft/hard 时合成一条，
        # 在判据出处里点名越过了哪两条判据。所以断言从"同一格出现两行"（旧渲染的产物）
        # 改为"格子被报到 + 两种判据都点名"——两条判据都得浮出来，重复行不该回来。
        check("崩坏数据：报 soft_cap 与 hard_cap 越界（一格子一条，两种判据都点名）",
              t3.count("interrupt = 70/30") >= 1 and "cell_soft_cap" in t3 and "cell_hard_cap" in t3,
              t3[:200])
        check("崩坏数据：报反馈下限 + 不可解读", "不可解读" in t3, t3[:200])
        check("崩坏数据：--check 非零", rc != 0, f"rc={rc}")
    finally:
        tl_path.write_text(tl_backup, encoding="utf-8")
        idx_path.write_text(idx_backup, encoding="utf-8")
    rc, out = py(root, "scripts/verify_metrics.py", "--check")
    check("还原后 timeline 结构仍合法", rc == 0, out[-200:])


# ---------------------------------------------------------------- ⑨ 预测的出处（可复现）
def ex_measure_path(root: Path):
    """EV-2026-050：predicted_effect 必须带可复现口径（第 16 条）。

    为什么钉成演练断言：这条规则的全部价值在"两侧都对"——正例能过、该红必红、不该红不哭狼。
    只验一侧的版本会在两种真实场景下静默失效：①把关过松，占位命令带一条自洽的期望过审
    （假绿）；②把关过紧，存量卡被追溯 → CI 常红 → 规则被人绕过。两种失效都不会自己暴露。

    日期用远期（2030）与远期过去（2026-01）构造：断言不随当天日期漂移。若用"今天"，
    本演练会在 cutover 生效日前后给出不同结论——写日期相关的断言 = 埋定时炸弹。
    """
    print("\n[E11] 预测的出处 · 可复现口径两侧对照（该红必红 / 不哭狼）")
    import copy
    import json as _json

    ideas = root / "proposals" / "ideas"
    CMD = f"{q(sys.executable)} -c \"print('MEASURE-OK')\""

    def base(cid, created):
        return {
            "id": cid, "layer": "L2", "title": f"演练卡 {cid}", "status": "in_experiment",
            "authorization": "review", "dimension": "observability", "created_at": created,
            "source_signals": [{"signal": "observability_gap", "evidence": "e", "trajectory": ["t"]}],
            "hypothesis": "h", "validation": {"method": "scan_review"}, "risk": "low",
            "principle_refs": [8], "decisions": [], "supersedes": [], "superseded_by": None,
        }

    def write(doc):
        p = ideas / f"{doc['id']}.yaml"
        p.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return p

    def verify():
        return py(root, "scripts/verify_proposals.py", "--check")

    # ① 正例：强制范围内 + 可复现口径 → 结构过、判据真的成立
    ok = base("EV-2099-101", "2030-01-01")
    ok["predicted_effect"] = {"metric": "m", "from": "a", "to": "b",
                              "measure": {"command": CMD, "expect_stdout": "MEASURE-OK"}}
    p_ok = write(ok)
    rc, out = verify()
    check("正例（强制范围 + 可复现口径）通过校验", rc == 0, out[-300:])
    rc, out = py(root, "scripts/ev_measure.py", "EV-2099-101", "--run")
    check("正例 --run 判 PASS（exit 0）", rc == 0 and "PASS" in out, out[-300:])
    check("--run 打印实测 exit 与输出（判据可见，不是黑盒）", "实测" in out and "MEASURE-OK" in out,
          out[-300:])

    # ② 有预测但没给复现口径（规则本体）
    d2 = base("EV-2099-102", "2030-01-01")
    d2["predicted_effect"] = {"metric": "m", "from": "a", "to": "b"}
    p2 = write(d2)
    rc, out = verify()
    check("强制卡写了预测但缺 measure 被拦", rc != 0 and "缺 measure" in out, out[-320:])
    rc, out = py(root, "scripts/ev_measure.py", "EV-2099-102")
    check("缺 measure 的卡判「无法判定」而非冒充通过（exit 2）",
          rc == 2 and "无法判定" in out, out[-300:])
    p2.unlink()

    # ②b 更早的断点：整个 predicted_effect 缺失 → 报的是另一条（别只覆盖一种）
    p2b = write(base("EV-2099-109", "2030-01-01"))
    rc, out = verify()
    check("强制卡缺整个 predicted_effect 被拦", rc != 0 and "缺 predicted_effect" in out, out[-320:])
    p2b.unlink()

    # ③ 有 command 无期望 → 不可判定，必须报（没有期望就无法判定符合与否）
    d3 = base("EV-2099-103", "2030-01-01")
    d3["predicted_effect"] = {"metric": "m", "from": "a", "to": "b",
                              "measure": {"command": CMD}}
    p3 = write(d3)
    rc, out = verify()
    check("有 command 但无期望被拦", rc != 0 and "无期望" in out, out[-300:])
    p3.unlink()

    # ④ 占位命令（产卡骨架的默认形态）→ 必须响亮失败，不得带假绿过审
    d4 = base("EV-2099-104", "2030-01-01")
    d4["predicted_effect"] = {"metric": "m", "from": "a", "to": "b",
                              "measure": {"command": "待填：复现命令", "expect_exit": 0}}
    p4 = write(d4)
    rc, out = verify()
    check("占位 command 被拦（骨架忘填 = 响亮失败）", rc != 0 and "占位符" in out, out[-300:])
    p4.unlink()

    # ⑤ 判据侧该红必红：结构合法、但期望在真实世界里不成立 → --run 必须 FAIL
    d5 = base("EV-2099-105", "2030-01-01")
    d5["predicted_effect"] = {"metric": "m", "from": "a", "to": "b",
                              "measure": {"command": CMD, "expect_stdout": "NEVER-APPEARS"}}
    p5 = write(d5)
    rc, out = verify()
    check("（前提）期望不成立的卡结构上合法——结构检查管不到语义", rc == 0, out[-260:])
    rc, out = py(root, "scripts/ev_measure.py", "EV-2099-105", "--run")
    check("期望不成立 → --run 判 FAIL（exit 1，预测被证伪）", rc == 1 and "FAIL" in out, out[-320:])
    p5.unlink()

    # ⑥ 不哭狼 · 存量卡：cutover 之前创建、无口径 → 不因 measure 报错，但如实标为存量豁免。
    #    （须带一条 decision，避开既有的"僵尸卡"规则——本断言单测的是 measure 豁免，不是烂卡）
    d6 = base("EV-2099-106", "2026-01-01")
    d6["decisions"] = [{"who": "agent", "when": "2026-01-01", "type": "decision",
                        "conclusion": "存量演练卡（已闭合）"}]
    p6 = write(d6)
    rc, out = verify()
    check("存量卡（早于 cutover）不因缺 measure 被报错", rc == 0, out[-300:])
    rc, out = py(root, "scripts/ev_measure.py", "EV-2099-106")
    check("存量卡查询如实标「存量豁免」并判无法判定（exit 2）",
          rc == 2 and "存量卡" in out, out[-300:])
    p6.unlink()

    # ⑦ 不哭狼 · 如实声明不可度量：合法退化路径，不计为缺口、不冒充通过
    d7 = base("EV-2099-107", "2030-01-01")
    d7["predicted_effect"] = {"metric": "m", "from": "a", "to": "b",
                              "measure": {"reason": "该预测依赖外部团队排期，本仓无可复现判据"}}
    p7 = write(d7)
    rc, out = verify()
    check("声明不可度量（reason）通过校验——诚实退化不阻断", rc == 0, out[-300:])
    rc, out = py(root, "scripts/ev_measure.py", "EV-2099-107")
    check("声明不可度量的卡判无法判定（exit 2）且打印理由，不冒充通过",
          rc == 2 and "声明不可度量" in out and "外部团队排期" in out, out[-320:])
    p7.unlink()

    # ⑧ 找不到卡 → 也无法判定，不得静默成功
    rc, out = py(root, "scripts/ev_measure.py", "EV-2099-999")
    check("找不到卡时 exit 2（不静默成功）", rc == 2 and "找不到卡" in out, out[-200:])

    # ⑨ --audit 分四类计数，且缺口存在时非零退出
    p9 = write(base("EV-2099-108", "2030-01-01"))          # 缺口：强制卡无 measure
    rc, out = py(root, "scripts/ev_measure.py", "--audit", "--json")
    try:
        data = _json.loads(out[out.index("{"):]) if "{" in out else {}
    except ValueError:
        data = {}
    check("--audit 缺口存在时非零退出（现状可当门用）", rc == 1, out[-260:])
    check("--audit 如实点名缺口卡", "EV-2099-108" in (data.get("missing") or []), out[-320:])
    check("--audit 把可复现的正例计入 runnable",
          "EV-2099-101" in (data.get("runnable") or []), out[-320:])
    check("--audit 计入存量豁免（不静默丢弃存量）", len(data.get("legacy") or []) >= 40,
          out[-320:])
    p9.unlink()
    rc, out = py(root, "scripts/ev_measure.py", "--audit")
    check("清掉缺口后 --audit 归零（不哭狼）", rc == 0 and "缺口（强制卡缺 measure） :   0" in out,
          out[-400:])

    # ⑩ 还原：卡池校验仍通过（断言无残留副作用）
    p_ok.unlink()
    rc, out = verify()
    check("清理后卡池校验仍通过（无残留副作用）", rc == 0, out[-260:])


# ---------------------------------------------------------------- ⑩ 封存对照集
def ex_holdout(root: Path):
    """封存对照集（holdout）：把"CI 绿是否有意义"钉成可执行断言。

    这条机制的全部价值在**独立性**：改动者能改被测对象、也能改量尺时，"无回归"不是
    独立信号。所以断言必须证明两侧：改封存夹具**必红**（哈希就是判据），而未封存的
    夹具被改**不红**（不哭狼，否则贡献者会被无关的红劝退）。
    """
    print("\n[E12] 封存对照集 · 改量尺必红 / 改非对照集不哭狼")
    import json as _json

    manifest = root / "eval" / "holdout.yaml"
    golden = root / "eval" / "golden"
    doc = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    entries = [e for e in (doc.get("entries") or []) if isinstance(e, dict)]
    sealed = entries[0]["fixture"]
    unsealed = next((f.name for f in sorted(golden.glob("*.fixture.yaml"))
                     if f.name not in {e["fixture"] for e in entries}), None)

    # ① 基线：封存后 --check 绿
    rc, out = py(root, "scripts/holdout.py", "--check")
    check("封存后 --check 绿", rc == 0 and "OK" in out, out[-200:])

    # ② 该红必红：改封存夹具的内容（模拟"把量尺改松"）
    p = golden / sealed
    backup = p.read_bytes()
    manifest_bytes = manifest.read_bytes()      # reseal 会改 manifest，测试结束要一并还原
    p.write_bytes(backup + "\n# 演练：篡改封存夹具\n".encode("utf-8"))
    rc, out = py(root, "scripts/holdout.py", "--check")
    check("改封存夹具内容 → --check 非零（哈希即判据）", rc != 0 and "内容已变" in out, out[-260:])

    # ③ reseal 是合法出口（维护者动作），但要留下可见痕迹
    rc, out = py(root, "scripts/holdout.py", "--reseal", "--id", sealed)
    check("维护者 reseal 后回到绿（合法出口存在，不是死锁）",
          rc == 0 and "更新 1 条封存哈希" in out, out[-260:])
    check("reseal 提示需带 holdout-change 标签（改量尺须在评审面上可见）",
          "holdout-change" in out, out[-260:])
    rc, out = py(root, "scripts/holdout.py", "--check")
    check("reseal 后 --check 绿", rc == 0, out[-200:])
    p.write_bytes(backup)
    manifest.write_bytes(manifest_bytes)        # 还原 reseal 对量尺记录本身的改动

    # ④ 删封存夹具 → 红（防"删掉量尺"绕过）
    p.unlink()
    rc, out = py(root, "scripts/holdout.py", "--check")
    check("删除封存夹具 → --check 非零", rc != 0 and "不存在" in out, out[-260:])
    p.write_bytes(backup)
    rc, out = py(root, "scripts/holdout.py", "--check")
    check("恢复后回到绿（断言无残留副作用）", rc == 0, out[-200:])

    # ⑤ 不哭狼：改**未封存**的夹具不该红（贡献者正常同步夹具不被误伤）
    if unsealed:
        q = golden / unsealed
        qb = q.read_bytes()
        q.write_bytes(qb + "\n# 演练：改非对照集夹具\n".encode("utf-8"))
        rc, out = py(root, "scripts/holdout.py", "--check")
        check(f"改未封存夹具（{unsealed}）不报错——不哭狼", rc == 0, out[-260:])
        q.write_bytes(qb)

    # ⑥ 用法错与优雅退化
    rc, out = py(root, "scripts/holdout.py", "--reseal")
    check("reseal 缺 --all/--id 时 exit 2（不静默全量重封）", rc == 2, out[-200:])
    manifest_backup = manifest.read_bytes()
    manifest.unlink()
    rc, out = py(root, "scripts/holdout.py", "--check")
    check("对照集未建立时 --check exit 0（优雅退化，不是崩溃）", rc == 0 and "未找到" in out, out[-200:])
    manifest.write_bytes(manifest_backup)

    # ⑦ 覆盖面缺口如实报出（软信号：有 case 却无夹具的格子 = 无回归保护）
    rc, out = py(root, "scripts/holdout.py", "--list", "--json")
    try:
        data = _json.loads(out[out.index("{"):]) if "{" in out else {}
    except ValueError:
        data = {}
    gaps = data.get("populated_cells_without_fixture") or []
    check("--list 报出封存条目数", len(data.get("holdout") or []) == len(entries),
          f"manifest={len(entries)} json={len(data.get('holdout') or [])}")
    check("--list 报出「有 case 却无夹具」的格子（training 段无回归保护是事实，须可见）",
          any("training/" in g for g in gaps), str(gaps)[:200])
    all_cells = (data.get("golden_cells") or []) + gaps
    dupes = [g for g in all_cells if any(g.endswith("/" + seg + "/" + seg)
                                         for seg in ("interrupt", "precision", "performance"))]
    check("格子名不自我重复（category 目录只算一次）", not dupes, str(dupes)[:200])


# ---------------------------------------------------------------- ⑪ CI parity
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
    posix_shell = shutil.which("bash") or shutil.which("sh")
    for jname, cmd in cmds:
        argv = ci_local_argv(cmd)
        if argv is not None:
            rc, out = run(argv, cwd=root)        # 单行命令：本机原生执行（见 ci_local_argv）
        elif posix_shell:
            rc, out = run([posix_shell, "-c", cmd], cwd=root)
        else:
            # 不假装通过：跳过必须**可见**（同仓库"跑了无信号 与 没跑 可分"的要求）
            print(f"  — 跳过（本平台无 POSIX shell，且该步是复合片段）："
                  f"[{jname}] {cmd.splitlines()[0][:60]}")
            continue
        label = f"[{jname}] {cmd.splitlines()[0][:70]}"
        check(f"CI 命令通过 {label}", rc == 0, out[-260:])
    return cmds


# ---------------------------------------------------------------- ⑫ 面板渲染断言
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


# ---------------------------------------------------------------- ⑬ live 期号规则
def ex_period_naming(root: Path):
    """live 期号的命名规则必须**能拦**，且存量豁免成立。

    为什么单独演一遍：期号是趋势锚点，而周批人人可跑（并发靠 PR merge 合流）。规则写进
    verify_metrics 后若只跑真实数据，只能证明"存量没被误伤"——证明不了"新写的错误期号会被拦"。
    """
    print("\n[E13] live 期号规则（YYYY-Www-live-MMDD）")
    base = "periods:\n- period: 2026-W35-live1\n  kind: live\n  recorded_at: '2026-08-31'\n  metrics: {sessions_total: 7}\n"
    cases = [
        ("存量豁免（cutover 前的旧形状不追溯改名）", base, 0),
        ("新 live 期号正确形状（带日期）",
         base + "- period: 2026-W40-live-1001\n  kind: live\n  recorded_at: '2026-10-01'\n  metrics: {sessions_total: 3}\n", 0),
        ("同一周两个不同期号都合法（靠日期区分，不再像'同一期被改'）",
         base + "- period: 2026-W40-live-1001\n  kind: live\n  recorded_at: '2026-10-01'\n  metrics: {sessions_total: 3}\n"
         "- period: 2026-W40-live-1003\n  kind: live\n  recorded_at: '2026-10-03'\n  metrics: {sessions_total: 5}\n", 0),
        ("新 live 期号缺日期 → 拦下",
         base + "- period: 2026-W40-live\n  kind: live\n  recorded_at: '2026-10-01'\n  metrics: {sessions_total: 3}\n", 1),
        ("新 live 期号用旧 -liveN 形状 → 拦下",
         base + "- period: 2026-W40-live2\n  kind: live\n  recorded_at: '2026-10-01'\n  metrics: {sessions_total: 3}\n", 1),
    ]
    for label, text, want in cases:
        d = root / "tmp-period-naming"
        (d / "metrics").mkdir(parents=True, exist_ok=True)
        (d / "metrics" / "timeline.yaml").write_text(text, encoding="utf-8")
        rc, out = run([sys.executable, "scripts/verify_metrics.py", "--check", "--root", str(d)], cwd=root)
        check(label, rc == want, "exit=%d 期望=%d :: %s" % (rc, want, out.strip()[:160]))
        if want == 1:
            check("  且点名了期号规则（不是一句泛泛的失败）", "YYYY-Www-live-MMDD" in out, out.strip()[:160])


# ---------------------------------------------------------------- ⑭ 时序数据的源/生成物
def ex_timeline_sources(root: Path):
    """一期一文件 + 生成物：**冲突从判断题变成机械题**，且这道门必须能红。

    背景：timeline.yaml 原先既是源又是 append 目标，而它是一个列表文件——任意两人各加一期
    都会撞在同一段文本上，冲突要人判断"留哪一份"（判断错就静默丢一期读数）。改后源是
    metrics/timeline.d/<期号>.yaml（各人各写一个），聚合由 build_timeline.py 重建、CI 校验一致性。
    """
    print("\n[E14] 时序数据 · 源（一期一文件）与生成物一致")
    from datetime import date          # 模块级没有；本函数独立可用（同 ex_metrics_loop 的写法）
    demo = root / "tmp-timeline-src"
    if demo.exists():
        shutil.rmtree(demo)
    (demo / "metrics" / "timeline.d").mkdir(parents=True)

    def write_src(pid, kind, recorded, sessions):
        (demo / "metrics" / "timeline.d" / (pid + ".yaml")).write_text(
            yaml.safe_dump({"period": pid, "kind": kind, "recorded_at": recorded,
                            "metrics": {"sessions_total": sessions}},
                           allow_unicode=True, sort_keys=False), encoding="utf-8")

    write_src("2026-W40-live-1001", "live", "2026-10-01", 3)
    write_src("2026-W40-live-1003", "live", "2026-10-03", 5)

    # ① 重建 → 校验一致性
    rc, out = run([sys.executable, "scripts/build_timeline.py", "--root", str(demo)], cwd=root)
    check("源 → 生成物重建成功", rc == 0, out.strip()[-160:])
    rc, out = run([sys.executable, "scripts/build_timeline.py", "--check", "--root", str(demo)], cwd=root)
    check("生成物与源一致时 --check 绿", rc == 0, out.strip()[-160:])

    # ② 直接改生成物（绕过源）→ 必须红，且报错给出"重跑一次"的机械修法
    agg = demo / "metrics" / "timeline.yaml"
    agg.write_text(agg.read_text(encoding="utf-8") + "\n# 有人手改了生成物\n", encoding="utf-8")
    rc, out = run([sys.executable, "scripts/build_timeline.py", "--check", "--root", str(demo)], cwd=root)
    check("手改生成物 → --check 红（生成物不是源）", rc == 1, "exit=%d" % rc)
    check("  且给出机械修法（重跑重建，而不是让人判断留哪份）",
          "python3 scripts/build_timeline.py" in out, out.strip()[:160])

    # ③ 源里有重复期号（两个文件声明同一个 period）→ 必须红并点出是哪两个文件
    (demo / "metrics" / "timeline.d" / "dup.yaml").write_text(
        yaml.safe_dump({"period": "2026-W40-live-1001", "kind": "live",
                        "recorded_at": "2026-10-01", "metrics": {"sessions_total": 9}},
                       allow_unicode=True, sort_keys=False), encoding="utf-8")
    rc, out = run([sys.executable, "scripts/build_timeline.py", "--check", "--root", str(demo)], cwd=root)
    check("源内重复期号 → 红", rc == 1, "exit=%d" % rc)
    check("  且同时点出「期号与文件名不一致」与「期号重复」两处",
          "文件名不一致" in out and "重复" in out, out.strip()[:200])

    # ④ 文件名与期号不一致（有人手工改名）→ 必须红
    (demo / "metrics" / "timeline.d" / "dup.yaml").unlink()
    (demo / "metrics" / "timeline.d" / "2026-W40-live-1001.yaml").rename(
        demo / "metrics" / "timeline.d" / "renamed.yaml")
    rc, out = run([sys.executable, "scripts/build_timeline.py", "--check", "--root", str(demo)], cwd=root)
    check("文件名与期号不一致 → 红（期号即文件名）", rc == 1 and "文件名不一致" in out, out.strip()[:160])

    # ⑤ git 冲突标记（两人同期号 → add/add 冲突留在源文件里）→ 红，且报错必须说"下一步做什么"。
    #    实测来源：用两个真分支复现合并，发现不特判时报的是"YAML 解析失败：while scanning a simple key
    #    ... <<<<<<< HEAD"——人能对上的是文件名，报错却讲 YAML 语法。
    (demo / "metrics" / "timeline.d" / "renamed.yaml").rename(
        demo / "metrics" / "timeline.d" / "2026-W40-live-1001.yaml")
    (demo / "metrics" / "timeline.d" / "2026-W40-live-1003.yaml").write_text(
        "<<<<<<< HEAD\nperiod: 2026-W40-live-1003\nkind: live\nrecorded_at: '2026-10-03'\n"
        "metrics: {sessions_total: 5}\n=======\nperiod: 2026-W40-live-1003\nkind: live\n"
        "recorded_at: '2026-10-03'\nmetrics: {sessions_total: 8}\n>>>>>>> engD\n", encoding="utf-8")
    rc, out = run([sys.executable, "scripts/build_timeline.py", "--check", "--root", str(demo)], cwd=root)
    check("源文件含 git 冲突标记 → 红", rc == 1, "exit=%d" % rc)
    check("  且点名真因（两人写了同一个期号）而不是只报 YAML 语法错",
          "冲突标记" in out and "同一个期号" in out and "YAML 解析失败" not in out, out.strip()[:200])
    check("  且给出三种处置与「不要两份都留」",
          "加后缀" in out and "不要" in out and "两份都留" in out, out.strip()[:200])
    shutil.rmtree(demo, ignore_errors=True)

    # ⑤ 真实检出：生成物与源一致（存量 8 期的迁移结果）
    rc, out = run([sys.executable, "scripts/build_timeline.py", "--check"], cwd=root)
    check("真实检出：生成物与源一致（存量期已迁移）", rc == 0, out.strip()[-160:])

    # ⑥ 同天撞号自动加后缀（期号只带日期、不带人）
    demo2 = root / "tmp-period-bump"
    (demo2 / "metrics" / "timeline.d").mkdir(parents=True, exist_ok=True)
    iso = date.today().isocalendar()
    base = "%d-W%02d-live-%s" % (iso[0], iso[1], date.today().strftime("%m%d"))
    (demo2 / "metrics" / "timeline.d" / (base + ".yaml")).write_text(
        "period: %s\nkind: live\nrecorded_at: '%s'\nmetrics: {sessions_total: 3}\n"
        % (base, date.today().isoformat()), encoding="utf-8")
    rc, out = run([sys.executable, "scripts/metrics_snapshot.py", "--kind", "live", "--emit-yaml",
                   "--root", str(demo2)], cwd=root)
    check("同天已有一期 → 第二人自动加后缀（%s → -2）" % base,
          rc == 0 and ("period: " + base + "-2") in out, out.splitlines()[0][:120] if out else "")
    check("  加后缀的期号仍合法（命名规则允许 -N 后缀）",
          bool(re.match(r"^\d{4}-W\d{2}-live-\d{4}(-\d+)?$", base + "-2")))
    shutil.rmtree(demo2, ignore_errors=True)


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
        ex_measure_path(sandbox)
        ex_holdout(sandbox)
        ex_ci_parity(sandbox)
        ex_period_naming(sandbox)
        ex_timeline_sources(sandbox)
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
