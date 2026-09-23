"""route_check（提交前自查：这条 case 会被哪个分支接住）的口径回归测试。

为什么值得测：这个脚本是**内容类 PR 预核**里唯一能跑的动作，而它的结论会被写进 PR 的
「Agent 预核意见」。它错两边的代价不对称——误报（把正常的顺序差异说成问题）会让人忽略它，
漏报（本该报的分支误吸不报）等于这个动作不存在。所以下面钉三件事：
期望分支怎么推、首个命中怎么判、宽词重复怎么列。
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import route_check as RC  # noqa: E402

TRIAGE = """branches:
  - id: training_interrupt
    category: interrupt
    symptoms:
      - ["\\\\btimeout\\\\b", "RuntimeError"]
    search_namespaces:
      - training/<detected_framework>/
      - common/
    fallback: Tier 3
  - id: inference_interrupt
    category: interrupt
    symptoms:
      - ["\\\\btimeout\\\\b", "EE9999"]
    search_namespaces:
      - inference/<detected_framework>/
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
        self.branches = RC.load_branches(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def write_case(self, rel, cid="T-1", title="t", sym="s"):
        p = self.root / "knowledge" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(CASE.format(cid=cid, title=title, sym=sym), encoding="utf-8")
        return p

    def test_hits_follow_branch_order(self):
        """按聚合顺序返回，顺序就是"谁先接住"，这正是这个脚本要报的东西。"""
        # 症状文本写普通词（不要写正则字面量）：`\b` 在 Python 字符串里是退格符，
        # 写成 "\btimeout\b" 时匹配靠的是巧合——测试要测的是"顺序"，不该顺手埋这种坑。
        hits, broken = RC.hits_for("服务 timeout 了", self.branches)
        self.assertEqual([b for b, _ in hits], ["training_interrupt", "inference_interrupt"])
        self.assertEqual(broken, [])

    def test_hits_report_first_matching_pattern_per_branch(self):
        hits, _broken = RC.hits_for("RuntimeError: 超时", self.branches)
        self.assertEqual(hits, [("training_interrupt", "RuntimeError")])

    def test_no_hit_returns_empty(self):
        hits, broken = RC.hits_for("完全没有关键词", self.branches)
        self.assertEqual(hits, [])
        self.assertEqual(broken, [])

    def test_uncompilable_regex_is_reported_not_swallowed(self):
        """**阻断级回归**：不可编译的正则不能静默跳过。

        跳过的后果是"该分支根本没参与判定"，而输出读起来像"这条 case 没命中任何分支"——
        两者同形，等于脚本在真空通过（独立预核实测：把 inference 分支的正则写成 `[` 后，
        推理侧 case 被报成"无命中"并 exit 0）。
        """
        bad = [{"id": "training_interrupt", "category": "interrupt", "symptoms": [["x"]],
                "search_namespaces": ["training/<f>/"], "fallback": "Tier 3"},
               {"id": "inference_interrupt", "category": "interrupt", "symptoms": [["["]],
                "search_namespaces": ["inference/<f>/"], "fallback": "Tier 3"}]
        hits, broken = RC.hits_for("RuntimeError", bad)
        self.assertEqual(hits, [])
        self.assertEqual(broken, [("inference_interrupt", "[")])

    def test_cli_exits_nonzero_when_tree_has_uncompilable_regex(self):
        (self.root / "triage-tree.yaml").write_text(
            "branches:\n"
            "  - id: inference_interrupt\n"
            "    category: interrupt\n"
            '    symptoms:\n      - ["["]\n'
            "    search_namespaces: [inference/<f>/]\n"
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

    def test_expected_branch_from_path(self):
        """期望分支从路径推：knowledge/<训推>/<框架>/<性质>/x.yaml → <训推>_<性质>。"""
        p = self.write_case("inference/vllm-ascend/interrupt/X.yaml")
        self.assertEqual(RC.expected_branch(p, self.root), "inference_interrupt")
        p2 = self.write_case("training/verl/precision/X.yaml")
        self.assertEqual(RC.expected_branch(p2, self.root), "training_precision")

    def test_common_case_is_not_judged(self):
        """common/ 的共性 case 不参与路由（框架无关）→ 不该硬套一个期望分支。"""
        p = self.write_case("common/performance/X.yaml")
        self.assertEqual(RC.expected_branch(p, self.root), "")

    def test_wide_words_lists_cross_branch_patterns(self):
        ww = dict(RC.wide_words(self.branches))
        self.assertIn("\\btimeout\\b", ww)
        self.assertEqual(ww["\\btimeout\\b"], ["training_interrupt", "inference_interrupt"])
        self.assertNotIn("EE9999", ww)          # 只在 inference 侧 → 不是宽词

    def test_cli_flags_first_hit_mismatch(self):
        """期望 inference 但首个命中 training → exit 1 并说清缺什么。这是它的全部价值所在。"""
        self.write_case("inference/vllm-ascend/interrupt/X.yaml", cid="T-MIS", sym="\\btimeout\\b 了")
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"),
                            "knowledge/inference/vllm-ascend/interrupt/X.yaml",
                            "--root", str(self.root)],
                           capture_output=True, text=True, cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("首个命中是 training_interrupt", r.stdout)

    def test_cli_passes_when_expected_branch_hits_first(self):
        self.write_case("inference/vllm-ascend/interrupt/X.yaml", cid="T-OK", sym="EE9999 报错")
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"),
                            "knowledge/inference/vllm-ascend/interrupt/X.yaml",
                            "--root", str(self.root)],
                           capture_output=True, text=True, cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("inference_interrupt", r.stdout)

    def test_cli_reports_every_case_in_a_multi_case_file(self):
        """一个文件多条 cases 时逐条报——只报第一条会让后面那些静默漏过（草稿文件常是多条）。"""
        p = self.root / "knowledge" / "inference" / "vllm-ascend" / "interrupt" / "M.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        # 注意不能拼两份含 `cases:` 头的文档——YAML 会按重复键取后一份，夹具自己先坏了
        # （实测：那样写只会得到 M-2 一条，测试却以为在测"逐条报"）。
        p.write_text(
            "cases:\n"
            "  - id: M-1\n"
            '    title: t\n'
            "    category: interrupt\n"
            "    tags: [t]\n"
            "    confidence: {score: 0.5}\n"
            "    symptoms:\n"
            '      - "\\btimeout\\b 了"\n'
            "  - id: M-2\n"
            '    title: t\n'
            "    category: interrupt\n"
            "    tags: [t]\n"
            "    confidence: {score: 0.5}\n"
            "    symptoms:\n"
            '      - "EE9999 报错"\n', encoding="utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"),
                            "knowledge/inference/vllm-ascend/interrupt/M.yaml", "--root", str(self.root)],
                           capture_output=True, text=True, cwd=self.root)
        self.assertIn("M-1", r.stdout)
        self.assertIn("M-2", r.stdout)
        self.assertIn("第 2/2 条", r.stdout)
        self.assertEqual(r.returncode, 1, r.stdout)      # M-1 会误吸到 training 分支

    def test_cli_wide_words_mode(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"), "--wide-words",
                            "--root", str(self.root)], capture_output=True, text=True, cwd=self.root)
        self.assertEqual(r.returncode, 0)
        self.assertIn("跨分支重复的正则", r.stdout)


if __name__ == "__main__":
    unittest.main()
