"""verify_upstream_outcomes 的口径回归测试。

为什么值得单测：这个脚本把上游状态写进案例的 validation_record，而它有三类错法都是静默的——
① 没有上游锚点时猜一个结局，外部对照的分母被虚增；② 查询失败（未登录、限流）时按「未验证」
记一笔，限流被当成上游否定，案例被错标；③ 游标先推进、写回后不核对，scripts/settle_trace_feedback.py
头注记的 VLLM-ASC-12430 教训说的就是这种（游标说结算过、盘上什么都没有，这笔证据永久不再重试）。
三类都不会报错，只会朝错的方向学习。测试用假 gh 把每条边界钉住，不依赖 gh、网络与登录。
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_upstream_outcomes as vuo  # noqa: E402

REPO = "vllm-project/vllm-ascend"
ISSUE_2760 = f"repos/{REPO}/issues/2760"

CASE_TMPL = """# 测试案例：{cid}
cases:
  - id: {cid}
    title: "测试案例"
    category: interrupt
{extra}    root_cause: x
    fix: y
"""


def anchor_block(issue=None, pr=None, url=True):
    lines = ["    upstream:", f"      - repo: {REPO}"]
    if issue is not None:
        lines.append(f"        issue: {issue}")
    if pr is not None:
        lines.append(f"        pr: {pr}")
    if url:
        kind = "pull" if pr is not None else "issues"
        lines.append(f'        url: "https://github.com/{REPO}/{kind}/{issue if issue is not None else pr}"')
    return "\n".join(lines) + "\n"


def write_case(root, cid, extra="", rel="knowledge/inference/vllm-ascend/interrupt", name=None):
    path = root / rel / f"{name or cid}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CASE_TMPL.format(cid=cid, extra=extra), encoding="utf-8")
    return path


def read_record(path, cid):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for case in doc["cases"]:
        if case["id"] == cid:
            return case.get("validation_record") or {}
    raise AssertionError(f"{path} 里没有案例 {cid}")


class FakeGh:
    """假 gh api：按路径查表返回 payload；未准备的路径与 fail 列表都按取不到处理。"""

    def __init__(self, payloads=None, fail=()):
        self.payloads = payloads or {}
        self.fail = set(fail)
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        if path in self.fail:
            raise vuo.GhError("gh api 失败：未登录或限流")
        if path in self.payloads:
            return self.payloads[path]
        raise vuo.GhError(f"测试未准备这个路径：{path}")


class VerifyUpstreamOutcomesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "knowledge").mkdir()
        self.state = self.root / ".settle-state.json"

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = vuo.run(root=self.root, week="2026-W40", **kwargs)
        return rc, out.getvalue(), err.getvalue()

    # ---------------------------------------------------------------- 没有锚点

    def test_no_anchor_is_not_comparable_and_writes_nothing(self):
        path = write_case(self.root, "VLLM-ASC-1")
        before = path.read_bytes()
        gh = FakeGh()
        rc, out, _ = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0)
        self.assertIn("不可对照", out)
        self.assertEqual(gh.calls, [], "没有锚点就不该发查询")
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.state.exists(), "没有可写的内容就不该生成游标")

    # ---------------------------------------------------------------- 上游确认

    def test_closed_completed_settles_consistent(self):
        path = write_case(self.root, "VLLM-ASC-2", extra=anchor_block(issue=2760))
        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "completed"}})
        rc, out, err = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0, err)
        record = read_record(path, "VLLM-ASC-2")
        self.assertEqual(record["consistent"], 1)
        self.assertEqual(record["self_consistent"], 0)
        self.assertEqual(record["inconsistent"], 0)
        self.assertEqual(record["last_verified"], "2026-W40")
        self.assertIn("现场是否解决", out, "输出里要有判据边界")
        self.assertIn("# 测试案例：VLLM-ASC-2", path.read_text(encoding="utf-8"),
                      "行级写回要保住文件头注释")
        self.assertTrue(self.state.exists())

    def test_dry_run_plans_without_writing(self):
        path = write_case(self.root, "VLLM-ASC-3", extra=anchor_block(issue=2760))
        before = path.read_bytes()
        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "completed"}})
        rc, out, _ = self.run_script(api=gh)
        self.assertEqual(rc, 0)
        self.assertIn("dry-run", out)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.state.exists())

    def test_anchor_from_case_source_settles_self_consistent(self):
        extra = anchor_block(issue=2760) + (
            "    references:\n"
            f'      - "https://github.com/{REPO}/issues/2760"\n')
        path = write_case(self.root, "VLLM-ASC-4", extra=extra)
        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "completed"}})
        rc, out, _ = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0)
        record = read_record(path, "VLLM-ASC-4")
        self.assertEqual(record["self_consistent"], 1, "锚点是案例来源时不能记成独立确认")
        self.assertEqual(record["consistent"], 0)
        self.assertIn("非独立", out)

    def test_merged_pr_anchor_settles_consistent(self):
        path = write_case(self.root, "VLLM-ASC-5", extra=anchor_block(pr=2781))
        gh = FakeGh({
            f"repos/{REPO}/issues/2781": {"state": "closed", "state_reason": None,
                                          "pull_request": {"url": "u"}},
            f"repos/{REPO}/pulls/2781": {"merged": True},
        })
        rc, _, err = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0, err)
        self.assertEqual(read_record(path, "VLLM-ASC-5")["consistent"], 1)

    def test_closed_without_state_reason_uses_merged_closing_pr(self):
        path = write_case(self.root, "VLLM-ASC-6", extra=anchor_block(issue=9001))
        gh = FakeGh({
            f"repos/{REPO}/issues/9001": {"state": "closed", "state_reason": None},
            f"repos/{REPO}/issues/9001/timeline?per_page=100": [
                {"event": "cross-referenced",
                 "source": {"issue": {"number": 9002, "pull_request": {"url": "u"}}}},
            ],
            f"repos/{REPO}/pulls/9002": {"merged": True},
        })
        rc, _, err = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0, err)
        self.assertEqual(read_record(path, "VLLM-ASC-6")["consistent"], 1)

    # ---------------------------------------------------------------- 不是确认

    def test_gh_failure_is_unverifiable_without_negative_conclusion(self):
        path = write_case(self.root, "VLLM-ASC-7", extra=anchor_block(issue=2760))
        before = path.read_bytes()
        gh = FakeGh(fail=(ISSUE_2760,))
        rc, out, _ = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0)
        self.assertIn("不可查证", out)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.state.exists(), "取不到时不写、也不推进游标")

    def test_closed_without_reason_and_no_reference_is_unverifiable(self):
        path = write_case(self.root, "VLLM-ASC-8", extra=anchor_block(issue=9001))
        gh = FakeGh({
            f"repos/{REPO}/issues/9001": {"state": "closed", "state_reason": None},
            f"repos/{REPO}/issues/9001/timeline?per_page=100": [],
        })
        rc, out, _ = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0)
        self.assertIn("不可查证", out)
        self.assertEqual(read_record(path, "VLLM-ASC-8"), {})

    def test_not_planned_without_claim_is_not_a_negative_conclusion(self):
        path = write_case(self.root, "VLLM-ASC-9", extra=anchor_block(issue=2760))
        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "not_planned"}})
        rc, out, _ = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0, "上游不修本身不是矛盾")
        self.assertIn("未验证", out)
        self.assertEqual(read_record(path, "VLLM-ASC-9"), {})
        self.assertFalse(self.state.exists())

    def test_open_issue_is_not_a_verification(self):
        path = write_case(self.root, "VLLM-ASC-10", extra=anchor_block(issue=2760))
        gh = FakeGh({ISSUE_2760: {"state": "open", "state_reason": None}})
        rc, out, _ = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0)
        self.assertIn("未验证", out)
        self.assertEqual(read_record(path, "VLLM-ASC-10"), {})

    # ---------------------------------------------------------------- 矛盾

    def test_contradiction_records_inconsistent_and_exits_1(self):
        extra = anchor_block(issue=12430) + (
            "    verification:\n"
            f"      source: {vuo.MERGED_CLAIM}\n")
        path = write_case(self.root, "VLLM-ASC-11", extra=extra)
        gh = FakeGh({f"repos/{REPO}/issues/12430": {"state": "closed", "state_reason": "not_planned"}})
        rc, out, err = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 1, err)
        self.assertIn("矛盾", out)
        record = read_record(path, "VLLM-ASC-11")
        self.assertEqual(record["inconsistent"], 1)
        self.assertEqual(record["consistent"], 0)

    # ---------------------------------------------------------------- 幂等与游标

    def test_same_outcome_twice_does_not_double_count(self):
        path = write_case(self.root, "VLLM-ASC-12", extra=anchor_block(issue=2760))
        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "completed"}})
        rc, _, _ = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0)
        rc, out, _ = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0)
        self.assertIn("结局未变", out)
        self.assertEqual(read_record(path, "VLLM-ASC-12")["consistent"], 1)

    def test_unverifiable_run_does_not_advance_cursor(self):
        path = write_case(self.root, "VLLM-ASC-13", extra=anchor_block(issue=2760))
        rc, _, _ = self.run_script(apply=True, api=FakeGh(fail=(ISSUE_2760,)))
        self.assertEqual(rc, 0)
        self.assertFalse(self.state.exists())
        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "completed"}})
        rc, _, _ = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0)
        self.assertEqual(read_record(path, "VLLM-ASC-13")["consistent"], 1,
                         "上一轮取不到不能挡住下一轮的确认")

    def test_writeback_recheck_failure_keeps_cursor(self):
        path = write_case(self.root, "VLLM-ASC-14", extra=anchor_block(issue=2760))
        before = path.read_bytes()
        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "completed"}})
        with mock.patch.object(vuo, "write_text_lf", lambda *a, **k: None):
            rc, _, err = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 2, "写不进去是环境不可用")
        self.assertIn("写回复核不通过", err)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.state.exists(), "游标不能在写回没落地时推进")

    def test_cursor_says_settled_but_record_gone_is_repaired(self):
        path = write_case(self.root, "VLLM-ASC-15", extra=anchor_block(issue=2760))
        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "completed"}})
        rc, _, _ = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0)
        # 模拟合并/回滚把落地冲掉了：删掉 validation_record 块，游标不动
        path.write_text(CASE_TMPL.format(cid="VLLM-ASC-15", extra=anchor_block(issue=2760)),
                        encoding="utf-8")
        rc, out, err = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0, err)
        self.assertIn("补写", out)
        self.assertEqual(read_record(path, "VLLM-ASC-15")["consistent"], 1)

    # ---------------------------------------------------------------- 参数与范围

    def test_unknown_case_returns_2(self):
        write_case(self.root, "VLLM-ASC-16")
        rc, _, err = self.run_script(case_id="VLLM-ASC-404", apply=True, api=FakeGh())
        self.assertEqual(rc, 2)
        self.assertIn("找不到", err)

    def test_case_filter_checks_only_that_case(self):
        write_case(self.root, "VLLM-ASC-17", extra=anchor_block(issue=2760))
        write_case(self.root, "VLLM-ASC-18", extra=anchor_block(issue=9999))
        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "completed"}})
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = vuo.run(root=self.root, case_id="VLLM-ASC-17", as_json=True, api=gh, week="2026-W40")
        self.assertEqual(rc, 0, err.getvalue())
        report = json.loads(out.getvalue())
        self.assertEqual([r["case"] for r in report["results"]], ["VLLM-ASC-17"])
        self.assertEqual(gh.calls, [ISSUE_2760])

    def test_archive_and_index_files_are_skipped(self):
        write_case(self.root, "VLLM-ASC-OLD", extra=anchor_block(issue=2760),
                   rel="knowledge/_archive")
        (self.root / "knowledge" / "_index.yaml").write_text(
            "cases:\n  - id: VLLM-ASC-IDX\n", encoding="utf-8")
        write_case(self.root, "VLLM-ASC-19", extra=anchor_block(issue=2760))
        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "completed"}})
        rc, out, err = self.run_script(apply=True, api=gh, as_json=True)
        self.assertEqual(rc, 0, err)
        report = json.loads(out)
        self.assertEqual(report["cases_scanned"], 1)
        self.assertEqual([r["case"] for r in report["results"]], ["VLLM-ASC-19"])

    def test_json_output_is_machine_readable_and_carries_the_boundary(self):
        write_case(self.root, "VLLM-ASC-20", extra=anchor_block(issue=2760))
        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "completed"}})
        rc, out, _ = self.run_script(apply=True, api=gh, as_json=True)
        self.assertEqual(rc, 0)
        report = json.loads(out)
        self.assertTrue(report["applied"])
        self.assertEqual(report["summary"]["verified"], 1)
        self.assertEqual(report["results"][0]["outcome"], vuo.VERIFIED)
        self.assertEqual(report["results"][0]["field"], "consistent")
        self.assertEqual(report["results"][0]["action"], "write")
        self.assertEqual(report["results"][0]["anchors"][0]["state_reason"], "completed")
        self.assertIn("现场是否解决", report["boundary"])
        self.assertEqual(report["summary"]["no_anchor"], 0)

    def test_record_without_validation_record_gets_a_new_block(self):
        path = write_case(self.root, "VLLM-ASC-21", extra=anchor_block(issue=2760))
        self.assertNotIn("validation_record", path.read_text(encoding="utf-8"))
        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "completed"}})
        rc, _, err = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0, err)
        record = read_record(path, "VLLM-ASC-21")
        self.assertEqual(sorted(record), sorted(vuo.REC_KEYS))
        self.assertIn("fix: y", path.read_text(encoding="utf-8"))

    def test_malformed_anchor_is_reported_not_guessed(self):
        extra = "    upstream:\n      - repo: vllm-project/vllm-ascend\n"
        path = write_case(self.root, "VLLM-ASC-22", extra=extra)
        gh = FakeGh()
        rc, out, _ = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0)
        self.assertEqual(gh.calls, [])
        self.assertIn("不可查证", out)
        self.assertEqual(read_record(path, "VLLM-ASC-22"), {})

    def test_existing_record_block_is_updated_in_place(self):
        extra = anchor_block(issue=2760) + (
            "    validation_record:  # 已有记录\n"
            "      consistent: 2\n"
            "      inconsistent: 0\n"
            "      self_consistent: 3\n"
            "      last_verified: 2026-W01\n")
        path = write_case(self.root, "VLLM-ASC-24", extra=extra)
        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "completed"}})
        rc, _, err = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0, err)
        record = read_record(path, "VLLM-ASC-24")
        self.assertEqual(record["consistent"], 3)
        self.assertEqual(record["self_consistent"], 3)
        self.assertEqual(record["last_verified"], "2026-W40")
        text = path.read_text(encoding="utf-8")
        self.assertIn("# 已有记录", text, "既有块里的注释要留住")
        self.assertEqual(text.count("validation_record:"), 1, "不能插出第二块")

    def test_multiple_anchors_count_once(self):
        extra = ("    upstream:\n"
                 f"      - repo: {REPO}\n        issue: 2760\n"
                 f"      - repo: {REPO}\n        issue: 9999\n")
        path = write_case(self.root, "VLLM-ASC-25", extra=extra)
        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "completed"},
                     f"repos/{REPO}/issues/9999": {"state": "open", "state_reason": None}})
        rc, _, err = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 0, err)
        self.assertEqual(read_record(path, "VLLM-ASC-25")["consistent"], 1,
                         "一条案例一次查证记一次，不按锚点数累加")

    def test_closed_unmerged_pr_contradicts_merged_claim(self):
        extra = anchor_block(pr=2781) + ("    verification:\n"
                                        f"      source: {vuo.MERGED_CLAIM}\n")
        path = write_case(self.root, "VLLM-ASC-26", extra=extra)
        gh = FakeGh({f"repos/{REPO}/issues/2781": {"state": "closed",
                                                   "pull_request": {"url": "u"}},
                     f"repos/{REPO}/pulls/2781": {"merged": False}})
        rc, out, _ = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 1)
        self.assertIn("矛盾", out)
        self.assertEqual(read_record(path, "VLLM-ASC-26")["inconsistent"], 1)

    def test_cursor_is_saved_per_case_so_a_later_failure_keeps_earlier_ones(self):
        path_a = write_case(self.root, "VLLM-ASC-30", extra=anchor_block(issue=2760))
        path_b = write_case(self.root, "VLLM-ASC-31", extra=anchor_block(issue=2761))
        real_write = vuo.write_text_lf

        def flaky(target, text, encoding="utf-8"):
            if Path(target).resolve() == path_b.resolve():
                return None          # 模拟这一条的写盘没落地
            return real_write(target, text, encoding=encoding)

        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "completed"},
                     f"repos/{REPO}/issues/2761": {"state": "closed", "state_reason": "completed"}})
        with mock.patch.object(vuo, "write_text_lf", flaky):
            rc, _, err = self.run_script(apply=True, api=gh)
        self.assertEqual(rc, 2, err)
        self.assertEqual(read_record(path_a, "VLLM-ASC-30")["consistent"], 1)
        cursor = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertIn("VLLM-ASC-30", cursor["_upstream_outcomes"],
                      "先落地的那条要已经进游标，整轮不重跑也不重复累加")
        self.assertNotIn("VLLM-ASC-31", cursor["_upstream_outcomes"])

    def test_unreadable_cursor_warns_on_stderr_and_json_stays_clean(self):
        write_case(self.root, "VLLM-ASC-27", extra=anchor_block(issue=2760))
        self.state.write_text("{ 这不是 JSON", encoding="utf-8")
        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "completed"}})
        rc, out, err = self.run_script(apply=True, api=gh, as_json=True)
        self.assertEqual(rc, 0, err)
        report = json.loads(out)
        self.assertEqual(report["summary"]["verified"], 1)
        self.assertIn("游标文件解析失败", err)

    def test_cli_accepts_dry_run_and_refuses_it_together_with_apply(self):
        path = write_case(self.root, "VLLM-ASC-23", extra=anchor_block(issue=2760))
        before = path.read_bytes()
        gh = FakeGh({ISSUE_2760: {"state": "closed", "state_reason": "completed"}})
        with mock.patch.object(vuo, "gh_api", gh), mock.patch.object(
                sys, "argv", ["verify_upstream_outcomes.py", "--dry-run", "--root", str(self.root)]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = vuo.main()
        self.assertEqual(rc, 0)
        self.assertIn("dry-run", out.getvalue())
        self.assertEqual(path.read_bytes(), before)
        with mock.patch.object(sys, "argv", ["verify_upstream_outcomes.py", "--dry-run", "--apply",
                                            "--root", str(self.root)]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    vuo.main()
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
