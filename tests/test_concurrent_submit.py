"""并发提交冲突实验：三个人同时提交，「现状」与「改后」各撞几次、丢不丢内容。

为什么要有这个文件：这次改动的目标是一句用户体验话——"大家一起用、一起往平台提交时，
别冲突一大堆"。这种话只能用可复跑的实验回答，不能用论证回答。所以这里真起一个临时 git 仓库、
真建三条分支、真做 `git merge`，把冲突数、需要人判断的文件数、合并后内容丢没丢**量出来**。

两个场景（`SCENARIOS`）：
  same-ns   三人改**同一个** namespace（vllm-ascend/interrupt）+ 同一个路由分支——最坏情况
  diff-ns   三人各改一个 namespace（vllm-ascend / verl / slding? 见下）+ 各改一个路由分支——常见情况

两种提交纪律（`POLICIES`）：
  before    「现状」：每个 PR 都提交生成物；总表头注带生成日期（三人跨天各自重建 → 日期行必撞）
  after     「改后」：PR 只提交 case 本体 + 分片 + triage-tree.d/（**生成物不进 PR**——
            总表与 triage 聚合由主干 job 重建，CI 有门拦着）；triage-tree.d/ 走 merge=union，
            两边新增的症状词都留住
"""
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CONTRIB = [
    ("a", "TEST-CONC-A", "wordAlphaUnique", "2026-09-19"),
    ("b", "TEST-CONC-B", "wordBetaUnique", "2026-09-20"),
    ("c", "TEST-CONC-C", "wordGammaUnique", "2026-09-21"),
]
# 场景 → 每位参与者的 (namespace 目录, 路由分支 id, 改哪个 triage 源文件)
SCENARIOS = {
    "same-ns": [
        ("inference/vllm-ascend/interrupt", "inference_interrupt", "40-inference-interrupt.yaml"),
        ("inference/vllm-ascend/interrupt", "inference_interrupt", "40-inference-interrupt.yaml"),
        ("inference/vllm-ascend/interrupt", "inference_interrupt", "40-inference-interrupt.yaml"),
    ],
    "diff-ns": [
        ("inference/vllm-ascend/interrupt", "inference_interrupt", "40-inference-interrupt.yaml"),
        ("training/verl/interrupt", "training_interrupt", "10-training-interrupt.yaml"),
        ("training/mindspeed-llm/interrupt", "training_precision", "20-training-precision.yaml"),
    ],
}
POLICIES = ("before", "after")

CASE = """cases:
  - id: {cid}
    title: "并发提交实验用 case（{cid}）"
    category: interrupt
    tags: [exp]
    compat:
      - framework: vllm-ascend
        ranges: ["0.23.0"]
    confidence:
      score: 0.5
    symptoms:
      - "并发实验症状：{cid}"
    quickly_check:
      primary:
        command_template: "echo {cid}"
        expected: "regex:{cid}"
"""


def git(repo: Path, *args, check=True):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check)


def py(repo: Path, *args):
    return subprocess.run(["python3", *args], cwd=repo, capture_output=True, text=True, check=False)


def append_symptom(path: Path, branch_id: str, word: str):
    """往路由分支的 symptoms 列表尾部追加一条——现实中加词就是这个动作，
    也正是"两人同一天加词会落在同一段文本上"的那段文本。"""
    lines = path.read_text(encoding="utf-8").split("\n")
    start = next(i for i, l in enumerate(lines) if l.strip() == f"- id: {branch_id}")
    si = next(i for i in range(start, len(lines)) if lines[i].strip() == "symptoms:")
    ei = si + 1
    while ei < len(lines) and (not lines[ei].strip() or lines[ei].startswith("      ")):
        ei += 1
    lines.insert(ei, f'      - ["{word}"]  # 并发提交实验')
    path.write_text("\n".join(lines), encoding="utf-8")


def word_in_triage(repo: Path, word: str) -> bool:
    if (repo / "triage-tree.yaml").exists() and word in (repo / "triage-tree.yaml").read_text(encoding="utf-8"):
        return True
    return False


class Experiment:
    """一次实验 = 一个临时仓库 + 两条/三条分支 + 顺序合并 + 记账。"""

    def __init__(self, scenario: str, policy: str):
        self.scenario = scenario
        self.policy = policy
        self.merges = 0
        self.conflicted_merges = 0
        self.generated_conflicts = 0      # 生成物冲突（重跑生成器即解，无判断）
        self.judgment_conflicts = 0       # 手写面冲突（要人决定留哪份）
        self.stale_gates = 0              # 全部合完之后、修之前，门是红的
        self.tmp = tempfile.TemporaryDirectory(prefix=f"concurrent-{scenario}-{policy}-")
        self.repo = Path(self.tmp.name) / "repo"

    # ---------------------------------------------------------------- 搭台
    def setup(self):
        r = self.repo
        r.mkdir(parents=True)
        shutil.copytree(ROOT / "knowledge", r / "knowledge")
        shutil.copytree(ROOT / "scripts", r / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(ROOT / "triage-tree.yaml", r / "triage-tree.yaml")
        if self.policy == "before":
            # 「现状」= 今天仓库的真实状态，两样都要还原（不还原就是把自己的收益记进基线，
            # 对比就没有意义；也**不能**用 `git show HEAD:` 取历史版本——本次改动合并进主干后
            # HEAD 就变成新版，基线会静默退回成"随便什么"，这条测试就白写了）：
            #   ① 路由只有一个文件可改：不拷 triage-tree.d/；
            #   ② 没有任何 merge=union：把当前文件里所有 union 规则剔掉。
            kept = [l for l in (ROOT / ".gitattributes").read_text(encoding="utf-8").split("\n")
                    if "merge=union" not in l]
            (r / ".gitattributes").write_text("\n".join(kept), encoding="utf-8")
        else:
            shutil.copy2(ROOT / ".gitattributes", r / ".gitattributes")
            shutil.copytree(ROOT / "triage-tree.d", r / "triage-tree.d")
        git(r, "init", "-q", "-b", "main")
        git(r, "config", "user.email", "exp@example.com")
        git(r, "config", "user.name", "并发实验")
        git(r, "add", "-A")
        git(r, "commit", "-qm", "base")

    # ---------------------------------------------------------------- 各人的提交
    def stamp_legacy_date(self, day: str):
        """旧生成器（本次改动前）会在总表头注写 `# 生成日期：<今天>`。这里按天打这个戳：
        三人跨天各自重建 → 这一行每人都不一样 → 合流必撞。这是"现状"最主要的冲突来源，
        也是点 1（去掉日期行）要消掉的东西。不打戳 = 基线少一条主要矛盾。"""
        if self.policy != "before":
            return
        idx = self.repo / "knowledge" / "_index.yaml"
        text = idx.read_text(encoding="utf-8")
        if "生成日期：" in text:
            return
        idx.write_text(re.sub(r"^# case 总数", f"# 生成日期：{day}    case 总数",
                              text, count=1, flags=re.M), encoding="utf-8")

    def contribute(self, i, ns_dir, branch_id, triage_file, cid, word, day):
        r = self.repo
        tag = CONTRIB[i][0]
        git(r, "checkout", "-q", "-b", f"kb/{tag}", "main")
        case = r / "knowledge" / ns_dir / f"{cid}.yaml"
        case.parent.mkdir(parents=True, exist_ok=True)
        case.write_text(CASE.format(cid=cid), encoding="utf-8")

        if self.policy == "before":
            append_symptom(r / "triage-tree.yaml", branch_id, word)
            added = [str(case.relative_to(r)), "triage-tree.yaml"]
        else:
            append_symptom(r / "triage-tree.d" / triage_file, branch_id, word)
            added = [str(case.relative_to(r)), f"triage-tree.d/{triage_file}"]

        # 各人按自己被告知的方式重建（现状：连总表一起提交；改后：只提交分片与聚合）
        py(r, "scripts/build_index.py")
        self.stamp_legacy_date(day)
        if self.policy == "before":
            added = [str(case.relative_to(r)), "triage-tree.yaml"]
            added += ["knowledge/_index.yaml", "knowledge/_index"]
        else:
            if self.policy == "after":
                # 本地跑一次生成器（看有没有意外），但**不提交聚合**——它是主干重建面，
                # PR 里带它就会撞（CI 的「生成物不得进 PR」那道门也会红）。
                py(r, "scripts/build_triage_tree.py")
            added.append("knowledge/_index")
        git(r, "add", *added)
        git(r, "commit", "-qm", f"{tag}: case {cid} + 路由词 {word}")

    # ---------------------------------------------------------------- 合流
    def merge(self, tag, branch_id):
        r = self.repo
        self.merges += 1
        p = git(r, "merge", "--no-ff", "-m", f"merge kb/{tag}", f"kb/{tag}", check=False)
        if p.returncode == 0:
            return []
        self.conflicted_merges += 1
        files = git(r, "diff", "--name-only", "--diff-filter=U").stdout.split()
        for f in files:
            kind = self.classify(f)
            if kind == "judgment":
                self.judgment_conflicts += 1
                self.resolve_keep_all_words(f, branch_id)
            else:
                self.generated_conflicts += 1
                self.resolve_by_rerun(f)
        git(r, "add", "-A")
        git(r, "commit", "-qm", f"merge kb/{tag}（解决冲突）")
        return files

    def classify(self, path: str) -> str:
        """这个文件在**这个纪律下**是生成物还是手写源——决定冲突要"重跑"还是"人判断"。

        同一个路径在两个纪律下角色不同，这正是本次改动的实质：
          - 现状：`triage-tree.yaml` 既是源又是所有人加词的目标 → 冲突要人判断留哪份（judgment）。
          - 改后：路由数据在 `triage-tree.d/`（手写源，union 自动两边都留），
                  `triage-tree.yaml` 变成生成物 → 冲突只需重跑（generated）。
        生成物清单与「主干重建面」一致：总表、全部分片、triage 聚合。
        """
        if path == "knowledge/_index.yaml" or path.startswith("knowledge/_index/"):
            return "generated"
        if path == "triage-tree.yaml":
            return "generated" if self.policy == "after" else "judgment"
        return "judgment"

    def resolve_by_rerun(self, path: str):
        """生成物冲突的标准动作：不手改，重跑一次生成器。"""
        py(self.repo, "scripts/build_index.py")
        self.stamp_legacy_date("2026-09-22")     # 解决冲突那天 = 又一个不同的日期
        if self.policy == "after":
            py(self.repo, "scripts/build_triage_tree.py")

    def resolve_keep_all_words(self, path: str, branch_id: str):
        """手写面冲突：认真的人会两边都留——这一步的存在本身就是成本。

        模拟最认真的解法：删冲突标记、把三人的词都补进**同一个分支**。故意不是最优解——
        真实的解决比这更快更糙（`test_casual_resolution_loses_a_route_word` 量的是那个代价）。
        """
        p = self.repo / path
        lines = [l for l in p.read_text(encoding="utf-8").split("\n")
                 if not l.startswith(("<<<<<<<", "=======", ">>>>>>>"))
                 and "并发提交实验" not in l]
        start = next(i for i, l in enumerate(lines) if l.strip() == f"- id: {branch_id}")
        si = next(i for i in range(start, len(lines)) if lines[i].strip() == "symptoms:")
        at = si + 1
        while at < len(lines) and (not lines[at].strip() or lines[at].startswith("      ")):
            at += 1
        for _tag, _cid, word, _day in CONTRIB:
            lines.insert(at, f'      - ["{word}"]  # 并发提交实验')
            at += 1
        p.write_text("\n".join(lines), encoding="utf-8")

    def merge_casual(self, tag, branch_id):
        """手忙脚乱地解冲突：生成物重跑（必须的），手写面 `git checkout --ours`——
        取自己那份，别人的改动就没了。这是"现状"下最省事的解法，也是下面那条测试量的东西。"""
        r = self.repo
        p = git(r, "merge", "--no-ff", "-m", f"merge kb/{tag}", f"kb/{tag}", check=False)
        if p.returncode == 0:
            return []
        files = git(r, "diff", "--name-only", "--diff-filter=U").stdout.split()
        for f in files:
            if self.classify(f) == "generated":
                self.resolve_by_rerun(f)
            else:
                git(r, "checkout", "--ours", "--", f)
        git(r, "add", "-A")
        git(r, "commit", "-qm", f"merge kb/{tag}（取自己那份）")
        return files

    def robot_on_main(self):
        """主干 job：重建生成物并提交（改后才有；现状靠人）。"""
        if self.policy != "after":
            return
        py(self.repo, "scripts/build_index.py")
        py(self.repo, "scripts/build_triage_tree.py")
        git(self.repo, "add", "knowledge/_index.yaml", "knowledge/_index", "triage-tree.yaml")
        if git(self.repo, "diff", "--cached", "--quiet", check=False).returncode != 0:
            git(self.repo, "commit", "-qm", "chore(generated): 主干重建 [skip ci]")

    # ---------------------------------------------------------------- 收尾断言
    def gates(self):
        rc_index = py(self.repo, "scripts/build_index.py", "--check", "--master").returncode
        rc_triage = py(self.repo, "scripts/build_triage_tree.py", "--check").returncode \
            if self.policy == "after" else 0
        return rc_index == 0 and rc_triage == 0

    def all_contributions_present(self):
        r = self.repo
        for i, (tag, cid, word, _day) in enumerate(CONTRIB):
            ns_dir = SCENARIOS[self.scenario][i][0]
            if not (r / "knowledge" / ns_dir / f"{cid}.yaml").exists():
                return False
            if word not in (r / "triage-tree.yaml").read_text(encoding="utf-8"):
                return False
        return True

    def run(self):
        t0 = time.time()
        self.setup()
        for i, (tag, cid, word, day) in enumerate(CONTRIB):
            ns_dir, branch_id, triage_file = SCENARIOS[self.scenario][i]
            self.contribute(i, ns_dir, branch_id, triage_file, cid, word, day)
        for i, (tag, _cid, _word, _day) in enumerate(CONTRIB):
            git(self.repo, "checkout", "-q", "main")
            self.merge(tag, SCENARIOS[self.scenario][i][1])
            self.robot_on_main()
        git(self.repo, "checkout", "-q", "main")
        if not self.gates():
            self.stale_gates += 1
        self.result = {
            "scenario": self.scenario,
            "policy": self.policy,
            "merges": self.merges,
            "conflicted_merges": self.conflicted_merges,
            "generated_conflicts": self.generated_conflicts,
            "judgment_conflicts": self.judgment_conflicts,
            "stale_gates": self.stale_gates,
            "all_present": self.all_contributions_present(),
            "gates_green": self.gates(),
            "seconds": round(time.time() - t0, 1),
        }
        return self.result

    def close(self):
        self.tmp.cleanup()


def run_matrix():
    out = []
    for scenario in SCENARIOS:
        for policy in POLICIES:
            e = Experiment(scenario, policy)
            try:
                out.append(e.run())
            finally:
                e.close()
    return out


def format_table(rows) -> str:
    head = ("场景", "纪律", "合并次数", "撞的合并", "生成物冲突", "要人判断的冲突", "合并后门红", "内容全留", "门绿")
    lines = ["\t".join(head)]
    for r in rows:
        lines.append("\t".join(str(x) for x in (
            r["scenario"], r["policy"], r["merges"], r["conflicted_merges"],
            r["generated_conflicts"], r["judgment_conflicts"], r["stale_gates"],
            r["all_present"], r["gates_green"])))
    return "\n".join(lines)


class ConcurrentSubmitTest(unittest.TestCase):
    rows = None

    @classmethod
    def setUpClass(cls):
        cls.rows = run_matrix()

    def by(self, scenario, policy):
        return next(r for r in self.rows if r["scenario"] == scenario and r["policy"] == policy)

    # ---------------------------------------------------------------- 问题存在（现状）
    def test_before_policy_collides(self):
        """现状必须能重现"冲突一大堆"：两种场景下都至少撞一次。没有这条，改后的对比就没有基线。"""
        for scenario in SCENARIOS:
            r = self.by(scenario, "before")
            self.assertGreaterEqual(r["conflicted_merges"], 1,
                                    f"{scenario} 现状预期有冲突，实测 {r}")

    def test_before_policy_needs_judgment_on_handwritten_route(self):
        """现状里"要人判断留哪份"的冲突出现在手写的路由文件上（同 namespace 场景）。"""
        r = self.by("same-ns", "before")
        self.assertGreaterEqual(r["judgment_conflicts"], 1, r)

    # ---------------------------------------------------------------- 改后：冲突清零、内容不丢
    def test_after_policy_has_no_judgment_conflicts(self):
        """改后：手写面冲突归零（triage-tree.d/ 走 union，生成物不进 PR）。"""
        for scenario in SCENARIOS:
            r = self.by(scenario, "after")
            self.assertEqual(r["judgment_conflicts"], 0, r)

    def test_after_policy_loses_nothing_and_gates_are_green(self):
        """最要紧的一条：并发的三份提交，合并后一份都不能少，门要能自己变绿。"""
        for scenario in SCENARIOS:
            r = self.by(scenario, "after")
            self.assertTrue(r["all_present"], r)
            self.assertTrue(r["gates_green"], r)
            self.assertEqual(r["stale_gates"], 0, r)

    def test_after_policy_beats_before_on_conflicted_merges(self):
        for scenario in SCENARIOS:
            b, a = self.by(scenario, "before"), self.by(scenario, "after")
            self.assertLessEqual(a["conflicted_merges"], b["conflicted_merges"],
                                 f"{scenario}: before={b} after={a}")

    def test_before_policy_leaves_main_gate_red(self):
        """现状最烦人的一点：三人合并完，主干门还是红的——因为"最后一个人重建过索引"
        在旧流程里是人的记忆责任。改后由主干 job 负责，门自己变绿（同一实验里量出来）。"""
        for scenario in SCENARIOS:
            self.assertFalse(self.by(scenario, "before")["gates_green"],
                             f"{scenario}：预期现状合完后门是红的")

    def test_diff_ns_case_is_fully_clean(self):
        """常见的并发形态（各人改各自的框架）：改后应当**一次都不撞**。"""
        r = self.by("diff-ns", "after")
        self.assertEqual(r["conflicted_merges"], 0, r)

    def test_casual_resolution_loses_a_route_word(self):
        """改前的风险上限：手忙脚乱地解冲突（手写面取自己那份）会**少一条路由词**。
        生成物可以重跑，手写面不能——这正是 union 合并要买的东西：让"两人加的词都留住"
        不依赖任何人的细心程度。"""
        e = Experiment("same-ns", "before")
        try:
            e.setup()
            for i, (tag, cid, word, day) in enumerate(CONTRIB):
                ns, bid, tf = SCENARIOS["same-ns"][i]
                e.contribute(i, ns, bid, tf, cid, word, day)
            git(e.repo, "checkout", "-q", "main")
            e.merge(CONTRIB[0][0], SCENARIOS["same-ns"][0][1])
            e.merge_casual(CONTRIB[1][0], SCENARIOS["same-ns"][1][1])
            text = (e.repo / "triage-tree.yaml").read_text(encoding="utf-8")
            self.assertIn(CONTRIB[0][2], text)
            self.assertNotIn(CONTRIB[1][2], text,
                             "预期：取自己那份 → 别人的路由词丢掉（改前做不到自动两边都留）")
        finally:
            e.close()


if __name__ == "__main__":
    rows = run_matrix()
    print(format_table(rows))
    print()
    for r in rows:
        print(r)
