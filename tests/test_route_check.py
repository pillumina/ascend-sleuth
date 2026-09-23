"""route_check（提交前自查：这条 case 会归到哪个性质）的口径回归测试。

为什么值得测：这个脚本是**内容类 PR 预核**里唯一能跑的动作，而它的结论会被写进 PR 的
「Agent 预核意见」。它错两边的代价不对称——误报（把正常的顺序差异说成问题）会让人忽略它，
漏报（本该报的性质误吸不报）等于这个动作不存在。所以下面钉四件事：
期望性质怎么推、首个命中怎么判、跨性质重复词怎么列、**侧不参与症状判定**（分层之后
候选分支里只有本侧的目录面，另一侧的性质词取不到）。
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import route_check as RC  # noqa: E402

TRIAGE = """sides:
  - id: training
    label: 训练
    namespaces:
      - training/<detected_framework>/
      - common/
    fallback: Tier 3
  - id: inference
    label: 推理
    namespaces:
      - inference/<detected_framework>/
      - common/
    fallback: Tier 3
natures:
  - id: interrupt
    category: interrupt
    symptoms:
      - ["\\\\btimeout\\\\b", "RuntimeError", "EE9999"]
      - ["超时", "timeout"]
    search_namespaces:
      - <side>/<detected_framework>/
      - common/
    fallback: Tier 3
  - id: performance
    category: performance
    symptoms:
      - ["slow", "SLA.*劣化"]
    search_namespaces:
      - <side>/<detected_framework>/
      - common/
    fallback: Tier 3
  - id: precision
    category: precision
    symptoms:
      - ["nan", "乱码"]
    search_namespaces:
      - <side>/<detected_framework>/
      - common/
    fallback: Tier 3
"""

CASE = """cases:
  - id: {cid}
    title: "{title}"
    category: interrupt
    tags: [t]
    confidence: {{score: 0.5}}
    symptoms:
      - "{sym}"
"""


class RouteCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "triage-tree.yaml").write_text(TRIAGE, encoding="utf-8")
        self.branches, self.sides = RC.load_tree(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def write_case(self, rel, cid="T-1", title="t", sym="s"):
        p = self.root / "knowledge" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(CASE.format(cid=cid, title=title, sym=sym), encoding="utf-8")
        return p

    def test_hits_follow_nature_order(self):
        """按聚合顺序返回，顺序就是"谁先归类"，这正是这个脚本要报的东西。"""
        # 症状文本写普通词（不要写正则字面量）：`\\b` 在 Python 字符串里是退格符，
        # 写成 "\\btimeout\\b" 时匹配靠的是巧合——测试要测的是"顺序"，不该顺手埋这种坑。
        hits, broken = RC.hits_for("服务 timeout 了", self.branches)
        self.assertEqual([b for b, _ in hits], ["interrupt"])
        self.assertEqual(broken, [])

    def test_hits_report_first_matching_pattern_per_nature(self):
        hits, _broken = RC.hits_for("RuntimeError: 超时", self.branches)
        self.assertEqual(hits, [("interrupt", "RuntimeError")])

    def test_no_hit_returns_empty(self):
        hits, broken = RC.hits_for("完全没有关键词", self.branches)
        self.assertEqual(hits, [])
        self.assertEqual(broken, [])

    # ---------------------------------------------------------------- 分层：侧在候选集之外
    def test_effective_branches_expand_side_placeholder(self):
        """侧已知 → 只拿本侧目录面；侧不在性质里判，所以展开后**看不到另一侧**。"""
        cand = RC.effective_branches(self.branches, "inference", sides=self.sides)
        self.assertEqual(cand[0]["search_namespaces"],
                         ["inference/<detected_framework>/", "common/"])
        for b in cand:
            self.assertNotIn("training/", " ".join(b["search_namespaces"]))

    def test_effective_branches_unknown_side_searches_both(self):
        """侧未知 → 所有已声明的侧都查（保底路径）；目录面去重，common/ 只出现一次。"""
        cand = RC.effective_branches(self.branches, None, sides=self.sides)
        self.assertEqual(cand[0]["search_namespaces"],
                         ["training/<detected_framework>/", "inference/<detected_framework>/",
                          "common/"])

    def test_unknown_side_covers_every_declared_side(self):
        """**加侧不漏查**：侧列表从聚合现取，不写死两个——多一个侧时"侧未知"必须把它也查上，
        否则新侧的 case 在侧未知路径上静默漏掉（没命中与漏查在输出上同形）。"""
        sides = self.sides + [{"id": "edge", "label": "边侧", "namespaces": ["edge/<f>/", "common/"],
                               "fallback": "Tier 3"}]
        cand = RC.effective_branches(self.branches, None, sides=sides)
        self.assertIn("edge/<detected_framework>/", cand[0]["search_namespaces"])
        known = RC.effective_branches(self.branches, "edge", sides=sides)
        self.assertEqual(known[0]["search_namespaces"], ["edge/<detected_framework>/", "common/"])

    def test_effective_branches_without_side_layer_refuses_to_guess(self):
        """聚合没给 `sides:` 时报错，不退回一对写死的侧——"读不到就悄悄用旧口径"正是
        删掉 `branches:` 别名时不要的形态。"""
        with self.assertRaises(ValueError):
            RC.effective_branches(self.branches, None)

    def test_effective_branches_inlines_detected_framework(self):
        cand = RC.effective_branches(self.branches, "training", framework="verl",
                                     sides=self.sides)
        self.assertEqual(cand[0]["search_namespaces"][0], "training/verl/")

    def test_nature_id_is_the_branch_id_not_side_plus_nature(self):
        """分层之后分支名就是性质名——`training_interrupt` 这种形状不该再出现。"""
        self.assertEqual([b["id"] for b in self.branches],
                         ["interrupt", "performance", "precision"])
        self.assertEqual(RC.expected_branch(
            self.write_case("training/verl/interrupt/X.yaml"), self.root), "interrupt")

    def test_uncompilable_regex_is_reported_not_swallowed(self):
        """**阻断级回归**：不可编译的正则不能静默跳过。

        跳过的后果是"该性质根本没参与判定"，而输出读起来像"这条 case 没命中任何性质"——
        两者同形，等于脚本在真空通过（独立预核实测：把某性质的正则写成 `[` 后，
        该侧 case 被报成"无命中"并 exit 0）。
        """
        bad = [{"id": "interrupt", "category": "interrupt", "symptoms": [["x"]],
                "search_namespaces": ["<side>/<f>/"], "fallback": "Tier 3"},
               {"id": "precision", "category": "precision", "symptoms": [["["]],
                "search_namespaces": ["<side>/<f>/"], "fallback": "Tier 3"}]
        hits, broken = RC.hits_for("RuntimeError", bad)
        self.assertEqual(hits, [])
        self.assertEqual(broken, [("precision", "[")])

    def test_cli_exits_nonzero_when_tree_has_uncompilable_regex(self):
        (self.root / "triage-tree.yaml").write_text(
            "sides:\n"
            "  - {id: inference, label: 推理, namespaces: [inference/<f>/], fallback: Tier 3}\n"
            "natures:\n"
            "  - id: interrupt\n"
            "    category: interrupt\n"
            '    symptoms:\n      - ["["]\n'
            "    search_namespaces: [<side>/<f>/]\n"
            "    fallback: Tier 3\n", encoding="utf-8")
        self.write_case("inference/vllm-ascend/interrupt/X.yaml", cid="T-BAD")
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"),
                            "knowledge/inference/vllm-ascend/interrupt/X.yaml", "--root", str(self.root)],
                           capture_output=True, text=True, cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("不可编译", r.stdout)
        self.assertIn("未参与判定", r.stdout)

    def test_cli_usage_errors_exit_two(self):
        """用法/读取错误是 2，与"判定不一致"的 1 分开（否则两类错会被读成同一件事）。"""
        p = self.root / "knowledge" / "inference" / "vllm-ascend" / "interrupt"
        p.mkdir(parents=True, exist_ok=True)
        for arg in (str(p), str(self.root / "nope.yaml")):
            r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"), arg,
                                "--root", str(self.root)], capture_output=True, text=True, cwd=self.root)
            self.assertEqual(r.returncode, 2, f"{arg}: {r.stdout}{r.stderr}")

    def test_unknown_nature_directory_exits_two(self):
        """目录里的性质段不是任何路由性质 → 2（路径与路由表对不上，先确认归哪一类）。"""
        p = self.write_case("inference/vllm-ascend/nonsense/X.yaml", cid="T-NS")
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"),
                            str(p), "--root", str(self.root)],
                           capture_output=True, text=True, cwd=self.root)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("不是任何路由性质", r.stderr)

    def test_case_side_and_nature_from_path(self):
        p = self.write_case("inference/vllm-ascend/interrupt/X.yaml")
        self.assertEqual(RC.case_side_and_nature(p, self.root), ("inference", "interrupt"))
        p2 = self.write_case("training/verl/precision/X.yaml")
        self.assertEqual(RC.case_side_and_nature(p2, self.root), ("training", "precision"))

    def test_common_case_is_not_judged(self):
        """common/ 的共性 case 不参与路由（框架无关）→ 不该硬套一个期望性质，也不判侧。"""
        p = self.write_case("common/performance/X.yaml")
        self.assertEqual(RC.case_side_and_nature(p, self.root), ("", ""))

    def test_wide_words_lists_cross_nature_patterns(self):
        """分层后这个词单的形状变了：列的是**同一形态被两个性质同时认领**（跨侧重复已不存在）。"""
        branches = self.branches + [{"id": "performance2", "category": "performance",
                                     "symptoms": [["\\btimeout\\b"]],
                                     "search_namespaces": ["<side>/<f>/"], "fallback": "Tier 3"}]
        ww = dict(RC.wide_words(branches))
        self.assertIn("\\btimeout\\b", ww)
        self.assertEqual(ww["\\btimeout\\b"], ["interrupt", "performance2"])
        self.assertNotIn("EE9999", ww)          # 只在 interrupt 一个性质里 → 不是宽词

    def test_cli_flags_first_hit_mismatch(self):
        """期望 interrupt 但首个命中 performance → exit 1 并说清缺什么。这是它的全部价值所在。"""
        self.write_case("inference/vllm-ascend/interrupt/X.yaml", cid="T-MIS",
                        sym="请求变 slow 了，但没报错")
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"),
                            "knowledge/inference/vllm-ascend/interrupt/X.yaml",
                            "--root", str(self.root)],
                           capture_output=True, text=True, cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("首个命中是 performance", r.stdout)

    def test_cli_shows_only_own_side_search_face(self):
        """报告里给出本条实际检索面——它只含本侧，侧不在症状层判，读报告的人要看得见这件事。"""
        self.write_case("inference/vllm-ascend/interrupt/X.yaml", cid="T-SIDE", sym="RuntimeError 超时")
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"),
                            "knowledge/inference/vllm-ascend/interrupt/X.yaml",
                            "--root", str(self.root)],
                           capture_output=True, text=True, cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("侧：inference", r.stdout)
        self.assertIn("只含本侧", r.stdout)
        self.assertIn("inference/<detected_framework>/", r.stdout)

    def test_cli_passes_when_expected_nature_hits_first(self):
        self.write_case("inference/vllm-ascend/precision/X.yaml", cid="T-OK", sym="输出 NaN 报错")
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"),
                            "knowledge/inference/vllm-ascend/precision/X.yaml",
                            "--root", str(self.root)],
                           capture_output=True, text=True, cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("precision", r.stdout)

    def test_cli_reports_every_case_in_a_multi_case_file(self):
        """一个文件多条 cases 时逐条报——只报第一条会让后面那些静默漏过（草稿文件常是多条）。"""
        p = self.root / "knowledge" / "inference" / "vllm-ascend" / "precision" / "M.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        # 注意不能拼两份含 `cases:` 头的文档——YAML 会按重复键取后一份，夹具自己先坏了
        # （实测：那样写只会得到 M-2 一条，测试却以为在测"逐条报"）。
        p.write_text(
            "cases:\n"
            "  - id: M-1\n"
            '    title: t\n'
            "    category: precision\n"
            "    tags: [t]\n"
            "    confidence: {score: 0.5}\n"
            "    symptoms:\n"
            '      - "输出 NaN 报错"\n'
            "  - id: M-2\n"
            '    title: t\n'
            "    category: precision\n"
            "    tags: [t]\n"
            "    confidence: {score: 0.5}\n"
            "    symptoms:\n"
            '      - "请求变 slow"\n', encoding="utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"),
                            "knowledge/inference/vllm-ascend/precision/M.yaml", "--root", str(self.root)],
                           capture_output=True, text=True, cwd=self.root)
        self.assertIn("M-1", r.stdout)
        self.assertIn("M-2", r.stdout)
        self.assertIn("第 2/2 条", r.stdout)
        self.assertEqual(r.returncode, 1, r.stdout)      # M-2 会误吸到性能性质

    def test_wide_words_red_when_router_layer_missing(self):
        """**真空通过**不能算过：路由层缺失时 `wide_words([])` 也是 []，与"真的没有重复词"同形。
        这条命令正是 to-postmortem 让加词的人扫一眼的那条，把"没读着"读成"没问题"会让人以为扫过了。"""
        (self.root / "triage-tree.yaml").write_text(
            "branches:\n  - {id: training_interrupt, category: interrupt, symptoms: [[oom]],"
            " search_namespaces: [training/<f>/], fallback: Tier 3}\n", encoding="utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"), "--wide-words",
                            "--root", str(self.root)], capture_output=True, text=True, cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("natures", r.stdout)

    def test_unreadable_tree_is_usage_error_not_mismatch(self):
        """读不到表 → 2（读取错误），与 1（期望性质对不上）分开。"""
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"), "--show-sides",
                            "--root", str(self.root / "nope")], capture_output=True, text=True,
                           cwd=self.root)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_cli_wide_words_mode(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"), "--wide-words",
                            "--root", str(self.root)], capture_output=True, text=True, cwd=self.root)
        self.assertEqual(r.returncode, 0)
        self.assertIn("跨性质重复的正则", r.stdout)

    def test_cli_show_sides_mode(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"), "--show-sides",
                            "--root", str(self.root)], capture_output=True, text=True, cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("合法侧：2 个", r.stdout)
        self.assertIn("training", r.stdout)
        self.assertIn("inference", r.stdout)

    def test_cli_show_sides_red_when_layer_missing(self):
        """侧层没落地时 --show-sides 要红（-1），不能静默说什么都没有。"""
        (self.root / "triage-tree.yaml").write_text(
            "natures:\n  - {id: interrupt, category: interrupt, symptoms: [[x]],"
            " search_namespaces: [common/], fallback: Tier 3}\n", encoding="utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"), "--show-sides",
                            "--root", str(self.root)], capture_output=True, text=True, cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("sides", r.stdout)


if __name__ == "__main__":
    unittest.main()
