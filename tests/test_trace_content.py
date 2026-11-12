"""三段时间线 + 修订记录 schema、content 写入口与 hash 一致性的回归。

护五件事，都是「错了不报错、只把记录写坏」的那一类：
1. 字段口径只有一份：写入口落盘前挡非法值，`--all` 用同一份校验器；
2. 写入口自动生成 append-only 修订（按 id diff、removed:<id>、每个被改字段的 hash）；
3. 深比较走 canonical 形式：手写 YAML 没加引号的时间与 JSON 里的字符串视为同一个值；
4. 绕过写入口手改内容后，`--all` 能靠修订里的 hash 抓到；
5. 内容字段有值却没有任何修订 hash 时也判红（删掉 revisions 再手改 / 首次手写）。
"""

import argparse
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import _trace_content as tc  # noqa: E402
import trace_transition as tt  # noqa: E402
import verify_trace_status as vt  # noqa: E402
from _trace_state import load_vocab  # noqa: E402

NOW = "2026-11-12T10:00:00+08:00"


def args(**kw):
    defaults = dict(reopen=False, correct_ending=False, backfill_ending=False, to=None, kind=None,
                    report_source=None, report_result=None, report_note=None,
                    verdict=None, review_note=None,
                    handed_to=None, duplicate_of=None, note=None, summary=None, severity=None,
                    fix_emitted=None, stop_reason=None, by="agent", source="agent",
                    expect_sha256=None, field="content", state=None, case_id=None,
                    inbox_path=None, dry_run=False, scheme_version=None, content_file=None)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def valid_content():
    return {
        "summary": "训练在 step 120 挂起（HCCL 通信超时）",
        "incident_env": "A5-950 / mindspeed-llm / CANN 8.2 / 单机 8 卡",
        "incident_timeline": [{
            "id": "inc-1", "at": NOW, "at_note": "起服务约 8 分钟后",
            "what": "训练在 step 120 挂起", "source": "log", "step": 1,
            "evidence": {"files": ["traces/evidence/s1/train.log"], "quote": "rank3: HCCL timeout",
                         "line": 12},
        }],
        "failure_process": {
            "axis": "time",
            "window": {"from": "09:00:00", "to": "10:00:00"},
            "clock_note": "日志时间比墙钟晚 8 h",
            "nodes": [{
                "id": "fp-1", "at": NOW, "x": None, "what": "HCCL 通信超时",
                "quote": "rank3: HCCL timeout", "repeat": "每 ~1 s 一次",
                "evidence": {"file": "traces/evidence/s1/train.log", "line": 17},
            }],
        },
        "upstream_timeline": [{
            "id": "up-1", "at": "2026-11-10", "what": "上游 issue 已修复",
            "source": "issue", "ref": "#13976",
            "evidence": {"files": ["traces/evidence/s1/issue.txt"]},
        }],
    }


def with_revision(content, kind="fact_corrected", reason="用户贴了日志", by="agent",
                  hashes=None, changes=None):
    """造一份「写入口会写出的」文档：revisions 里的 hash 默认按当前值算。"""
    doc = copy.deepcopy(content)
    doc["revisions"] = [{
        "at": NOW, "by": by, "kind": kind,
        "changes": changes or [{"target": "inc-1", "before": "", "after": "训练在 step 120 挂起"}],
        "reason": reason,
        "hashes": hashes if hashes is not None else {
            field: tc.canonical_hash(doc[field]) for field in tc.WRITABLE_FIELDS
            if field in doc},
    }]
    return doc


BASE = """session_id: "{sid}"
status: in_progress
summary: "训练挂起"
severity: service-affecting
updated_at: "2026-10-30T09:00:00+08:00"
trace:
  - {{step: 1, role: user, content: "贴了栈"}}
"""


class ValidateContentTest(unittest.TestCase):
    def test_valid_content_passes(self):
        doc = with_revision(valid_content())
        self.assertEqual(tc.validate_content(doc), [])

    def test_legacy_trace_without_new_fields_passes(self):
        # 旧 trace 没有这五个字段：不报错，也不要求回填。
        legacy = {"session_id": "old", "status": "resolved", "summary": "老单",
                  "transitions": [], "trace": [{"role": "user", "step": 1, "content": "x"}]}
        self.assertEqual(tc.validate_content(legacy), [])
        self.assertEqual(tc.validate_content({}), [])

    def test_summary_must_be_string(self):
        doc = {"summary": 3}
        errs = tc.validate_content(doc)
        self.assertTrue(any("summary" in e for e in errs), errs)

    def test_summary_cannot_be_empty(self):
        self.assertTrue(tc.validate_field("summary", "  "))

    def test_incident_env_must_be_one_line(self):
        errs = tc.validate_field("incident_env", "第一行\n第二行")
        self.assertTrue(any("一行" in e for e in errs), errs)

    def test_incident_source_enum(self):
        doc = valid_content()
        doc["incident_timeline"][0]["source"] = "grafana"
        errs = tc.validate_content(doc)
        self.assertTrue(any("source" in e and "不在枚举里" in e for e in errs), errs)

    def test_upstream_source_enum(self):
        doc = valid_content()
        doc["upstream_timeline"][0]["source"] = "log"  # 现场侧来源不能进上游时间线
        errs = tc.validate_content(doc)
        self.assertTrue(any("upstream_timeline[0]" in e and "source" in e for e in errs), errs)

    def test_id_pattern(self):
        doc = valid_content()
        doc["incident_timeline"][0]["id"] = "i-1"
        errs = tc.validate_content(doc)
        self.assertTrue(any("inc-<n>" in e for e in errs), errs)

    def test_duplicate_ids_rejected(self):
        doc = valid_content()
        row = copy.deepcopy(doc["incident_timeline"][0])
        doc["incident_timeline"].append(row)
        errs = tc.validate_content(doc)
        self.assertTrue(any("重复" in e for e in errs), errs)

    def test_time_format(self):
        doc = valid_content()
        doc["incident_timeline"][0]["at"] = "2026/11/12 10:00"
        errs = tc.validate_content(doc)
        self.assertTrue(any("不是可解析的时间" in e for e in errs), errs)
        # 只到日期、null 都合法（hash 覆盖由 with_revision 补上，单独检查字段形状）
        doc["incident_timeline"][0]["at"] = "2026-11-12"
        self.assertEqual(tc.validate_content(with_revision(doc)), [])
        doc["incident_timeline"][0]["at"] = None
        self.assertEqual(tc.validate_content(with_revision(doc)), [])

    def test_unquoted_yaml_datetime_is_accepted(self):
        rows = [{"id": "inc-1", "at": datetime.fromisoformat(NOW),
                 "what": "挂起", "source": "log"}]
        self.assertEqual(tc.validate_field("incident_timeline", rows), [])

    def test_failure_process_axis_enum(self):
        doc = valid_content()
        doc["failure_process"]["axis"] = "wall"
        errs = tc.validate_content(doc)
        self.assertTrue(any("axis" in e and "不在枚举里" in e for e in errs), errs)

    def test_nodes_over_limit(self):
        doc = valid_content()
        node = doc["failure_process"]["nodes"][0]
        doc["failure_process"]["nodes"] = [
            {**copy.deepcopy(node), "id": f"fp-{i}"} for i in range(1, 10)]
        errs = tc.validate_content(doc)
        self.assertTrue(any("超过上限 8" in e for e in errs), errs)

    def test_nodes_at_limit_pass(self):
        doc = valid_content()
        node = doc["failure_process"]["nodes"][0]
        doc["failure_process"]["nodes"] = [
            {**copy.deepcopy(node), "id": f"fp-{i}"} for i in range(1, 9)]
        self.assertEqual(tc.validate_content(with_revision(doc)), [])

    def test_incident_timeline_limit_is_16(self):
        doc = valid_content()
        row = doc["incident_timeline"][0]
        doc["incident_timeline"] = [
            {**copy.deepcopy(row), "id": f"inc-{i}"} for i in range(1, 17)]
        self.assertEqual(tc.validate_content(with_revision(doc)), [])
        doc["incident_timeline"].append({**copy.deepcopy(row), "id": "inc-17"})
        errs = tc.validate_content(doc)
        self.assertTrue(any("incident_timeline 有 17 条" in e and "上限 16" in e
                            for e in errs), errs)

    def test_upstream_timeline_limit_is_12(self):
        doc = valid_content()
        row = doc["upstream_timeline"][0]
        doc["upstream_timeline"] = [
            {**copy.deepcopy(row), "id": f"up-{i}"} for i in range(1, 13)]
        self.assertEqual(tc.validate_content(with_revision(doc)), [])
        doc["upstream_timeline"].append({**copy.deepcopy(row), "id": "up-13"})
        errs = tc.validate_content(doc)
        self.assertTrue(any("upstream_timeline 有 13 条" in e and "上限 12" in e
                            for e in errs), errs)

    def test_revisions_have_no_limit(self):
        # revisions 是 append-only：不设上限，多了不判红，只逐条查形状。
        doc = with_revision(valid_content())
        doc["revisions"] = doc["revisions"] * 30
        self.assertEqual([e for e in tc.validate_content(doc) if "上限" in e], [])

    def test_unknown_key_rejected(self):
        doc = valid_content()
        doc["incident_timeline"][0]["resource"] = "log"
        errs = tc.validate_content(doc)
        self.assertTrue(any("有未定义字段" in e and "resource" in e for e in errs), errs)

    def test_node_quote_required(self):
        doc = valid_content()
        del doc["failure_process"]["nodes"][0]["quote"]
        errs = tc.validate_content(doc)
        self.assertTrue(any("quote" in e and "必填" in e for e in errs), errs)

    def test_revision_requires_kind_and_changes_and_reason(self):
        doc = with_revision(valid_content())
        del doc["revisions"][0]["kind"]
        doc["revisions"][0]["changes"] = []
        doc["revisions"][0]["reason"] = ""
        errs = tc.validate_revision(doc["revisions"][0], "revisions[0]")
        text = "；".join(errs)
        self.assertIn("kind", text)
        self.assertIn("changes 至少一条", text)
        self.assertIn("reason", text)

    def test_revision_change_target_shape(self):
        base = {"target": "inc-1", "before": "", "after": "x"}
        self.assertEqual(tc.validate_revision({
            "at": NOW, "by": "agent", "kind": "fact_corrected",
            "changes": [base], "reason": "r"}), [])
        # 删除条目的 target 不要求当前存在
        self.assertEqual(tc.validate_revision({
            "at": NOW, "by": "agent", "kind": "fact_corrected",
            "changes": [{"target": "removed:inc-9", "before": "旧", "after": ""}],
            "reason": "r"}), [])
        bad = tc.validate_revision({
            "at": NOW, "by": "agent", "kind": "fact_corrected",
            "changes": [{"target": "某条目", "before": "", "after": "x"}], "reason": "r"})
        self.assertTrue(any("target" in e for e in bad), bad)

    def test_revision_at_requires_datetime(self):
        bad = tc.validate_revision({
            "at": "2026-11-12", "by": "agent", "kind": "fact_corrected",
            "changes": [{"target": "inc-1", "before": "", "after": "x"}], "reason": "r"})
        self.assertTrue(any("不是可解析的时间" in e for e in bad), bad)

    def test_hash_mismatch_caught_after_hand_edit(self):
        doc = with_revision(valid_content())
        doc["incident_timeline"][0]["what"] = "手改过的事实"
        errs = tc.validate_content(doc)
        self.assertTrue(any("hash 不一致" in e for e in errs), errs)

    def test_stale_hash_caught_even_if_not_latest_field_hash(self):
        # 最近一条带该字段 hash 的修订是第二版：第一版的旧 hash 不参与比较。
        doc = with_revision(valid_content())
        old_hash = tc.canonical_hash(doc["incident_timeline"])
        doc["incident_timeline"][0]["what"] = "改过"
        doc["revisions"].append({
            "at": NOW, "by": "agent", "kind": "fact_corrected",
            "changes": [{"target": "inc-1", "before": "旧", "after": "改过"}], "reason": "r2",
            "hashes": {"incident_timeline": tc.canonical_hash(doc["incident_timeline"])}})
        self.assertEqual(tc.validate_content(doc), [])
        doc["incident_timeline"][0]["what"] = "又手改"
        self.assertTrue(any("hash 不一致" in e for e in tc.validate_content(doc)))
        self.assertNotEqual(old_hash, tc.canonical_hash(doc["incident_timeline"]))

    def test_canonical_forms_match(self):
        # 同一个时刻：YAML 未加引号解析出的 datetime 与 JSON 里的字符串应判为相等。
        self.assertTrue(tc.field_equal(datetime.fromisoformat(NOW), NOW))
        self.assertEqual(tc.canonical_hash(datetime.fromisoformat(NOW)), tc.canonical_hash(NOW))

    def test_content_without_any_revision_hash_rejected(self):
        # 首次手写：内容字段有值、整份没有 revisions → 无法证明经写入口写，判红。
        errs = tc.validate_content(valid_content())
        for field in ("incident_env", "incident_timeline", "failure_process",
                      "upstream_timeline"):
            self.assertTrue(any(field in e and "没有修订 hash" in e for e in errs),
                            (field, errs))
        self.assertFalse(any("summary" in e and "没有修订 hash" in e for e in errs), errs)

    def test_deleting_revisions_then_hand_editing_caught(self):
        # 先删掉整个 revisions（绕开 hash 一致性），再手改内容：覆盖检查抓住。
        doc = with_revision(valid_content())
        del doc["revisions"]
        doc["incident_timeline"][0]["what"] = "删掉修订后手改"
        errs = tc.validate_content(doc)
        self.assertTrue(any("incident_timeline" in e and "没有修订 hash" in e for e in errs),
                        errs)

    def test_empty_content_fields_need_no_revision_hash(self):
        # 空列表 = 字段存在但没有内容，不要求 hash（否则清空后的单会被判红）。
        self.assertEqual(tc.validate_content({"incident_timeline": [],
                                              "upstream_timeline": []}), [])

    def test_summary_alone_needs_no_revision_hash(self):
        # summary 是既有字段：旧单可能没有修订记录，不能因它判红。
        self.assertEqual(tc.validate_content({"summary": "老摘要"}), [])


class DiffContentTest(unittest.TestCase):
    def test_list_rows_added_removed_changed(self):
        before = [{"id": "inc-1", "what": "旧"}, {"id": "inc-2", "what": "保留"}]
        after = [{"id": "inc-2", "what": "保留"}, {"id": "inc-3", "what": "新增"}]
        changes = tc.diff_content("incident_timeline", before, after)
        targets = [c["target"] for c in changes]
        self.assertEqual(targets, ["removed:inc-1", "inc-3"])
        self.assertEqual(changes[0]["after"], "")
        self.assertEqual(changes[1]["before"], "")

    def test_list_row_changed(self):
        before = [{"id": "up-1", "what": "旧结论"}]
        after = [{"id": "up-1", "what": "新结论"}]
        changes = tc.diff_content("upstream_timeline", before, after)
        self.assertEqual(changes, [{"target": "up-1", "before": "旧结论", "after": "新结论"}])

    def test_failure_process_structural_and_node_diff(self):
        before = {"axis": "time", "clock_note": "旧时钟说明",
                  "nodes": [{"id": "fp-1", "what": "超时"}, {"id": "fp-2", "what": "重试"}]}
        after = {"axis": "step", "clock_note": "旧时钟说明",
                 "nodes": [{"id": "fp-1", "what": "超时（更正）"}]}
        changes = tc.diff_content("failure_process", before, after)
        targets = [c["target"] for c in changes]
        self.assertIn("failure_process", targets)   # axis 变了
        self.assertIn("fp-1", targets)
        self.assertIn("removed:fp-2", targets)

    def test_string_field_diff(self):
        self.assertEqual(tc.diff_content("summary", "旧", "新"),
                         [{"target": "summary", "before": "旧", "after": "新"}])

    def test_cleared_list_records_removed_rows(self):
        # 整段清成 null 时按条目记 removed:<id>（before 留着旧摘要），信息量比字段级一条多。
        changes = tc.diff_content("incident_timeline", [{"id": "inc-1", "what": "x"}], None)
        self.assertEqual(changes[0]["target"], "removed:inc-1")
        self.assertEqual(changes[0]["after"], "")


class ContentWriterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "traces").mkdir()
        self.traces = self.dir / "traces"

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, sid="s1", extra=""):
        path = self.traces / (sid + ".yaml")
        path.write_text(BASE.format(sid=sid) + extra, encoding="utf-8")
        return path

    def load(self, sid="s1"):
        return yaml.safe_load((self.traces / (sid + ".yaml")).read_text(encoding="utf-8"))

    def write(self, payload, sid="s1", **kw):
        path = self.dir / "content.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return tt.apply_transition(ROOT, self.traces, sid,
                                   args(content_file=str(path), **kw))

    def test_round_trip_writes_fields_revision_hashes_and_updated_at(self):
        path = self.make()
        before = path.read_text(encoding="utf-8")
        result = self.write({"set": valid_content(), "kind": "fact_corrected",
                             "reason": "用户贴了日志",
                             "evidence": {"files": ["traces/evidence/s1/train.log"]}})
        doc = self.load()
        self.assertTrue(result["ok"])
        self.assertEqual(result["changed"], list(tc.WRITABLE_FIELDS))
        self.assertEqual(doc["summary"], valid_content()["summary"])
        self.assertEqual(doc["incident_timeline"][0]["id"], "inc-1")
        self.assertEqual(doc["failure_process"]["nodes"][0]["id"], "fp-1")
        self.assertEqual(doc["upstream_timeline"][0]["ref"], "#13976")
        # 状态与事件流不动
        self.assertEqual(doc["status"], "in_progress")
        self.assertEqual(len(doc["trace"]), 1)
        # updated_at 刷新；revision 自动生成且 hash 与当前值一致
        self.assertEqual(len(doc["revisions"]), 1)
        rev = doc["revisions"][0]
        self.assertEqual(rev["by"], "agent")
        self.assertEqual(rev["kind"], "fact_corrected")
        self.assertEqual(rev["reason"], "用户贴了日志")
        self.assertEqual(set(rev["hashes"]), set(tc.WRITABLE_FIELDS))
        for field, digest in rev["hashes"].items():
            self.assertEqual(tc.canonical_hash(doc[field]), digest, field)
        self.assertNotIn('updated_at: "2026-10-30T09:00:00+08:00"', path.read_text(encoding="utf-8"))
        self.assertNotEqual(before, path.read_text(encoding="utf-8"))
        self.assertEqual(tc.validate_content(doc), [])

    def test_written_yaml_uses_indented_block_style(self):
        path = self.make()
        self.write({"set": valid_content(), "kind": "fact_corrected", "reason": "首版"})
        text = path.read_text(encoding="utf-8")
        # 不再是一行 flow JSON；条目挂在字段名下、缩进两格。
        self.assertNotIn("incident_timeline: [", text)
        self.assertNotIn("failure_process: {", text)
        self.assertNotIn("revisions: [", text)
        self.assertIn("incident_timeline:\n  - id: inc-1\n", text)
        self.assertIn("failure_process:\n  axis: time\n", text)
        self.assertIn("\nrevisions:\n  - at: ", text)
        # 落盘后的块 YAML 解析回来，hash 与修订记录仍对得上
        self.assertEqual(tc.validate_content(self.load()), [])

    def test_transitions_keep_flow_list_block(self):
        # 只有内容字段换块风格；transitions / reports / reviews 仍是原来的单行 flow。
        self.make()
        tt.apply_transition(ROOT, self.traces, "s1",
                            args(field=None, to="resolved", fix_emitted=True))
        text = (self.traces / "s1.yaml").read_text(encoding="utf-8")
        self.assertIn("transitions:\n  - {", text)

    def test_second_write_appends_revision_and_keeps_before(self):
        self.make()
        first = valid_content()
        self.write({"set": first, "kind": "fact_corrected", "reason": "首版"})
        second = copy.deepcopy(first)
        second["incident_timeline"][0]["what"] = "训练在 step 120 挂起（已更正）"
        second["upstream_timeline"] = []
        result = self.write({"set": {"incident_timeline": second["incident_timeline"],
                                     "upstream_timeline": second["upstream_timeline"]},
                             "kind": "fact_corrected", "reason": "用户更正"})
        doc = self.load()
        self.assertEqual(len(doc["revisions"]), 2)
        self.assertEqual(result["changed"], ["incident_timeline", "upstream_timeline"])
        targets = [c["target"] for c in doc["revisions"][1]["changes"]]
        self.assertIn("inc-1", targets)
        self.assertIn("removed:up-1", targets)
        self.assertEqual(doc["incident_timeline"][0]["what"], "训练在 step 120 挂起（已更正）")
        self.assertEqual(tc.validate_content(doc), [])

    def test_removed_node_uses_removed_target(self):
        self.make()
        first = valid_content()
        first["failure_process"]["nodes"].append(
            {"id": "fp-2", "what": "重试", "quote": "retry"})
        self.write({"set": {"failure_process": first["failure_process"]},
                    "kind": "fact_corrected", "reason": "首版"})
        only_first = copy.deepcopy(first["failure_process"])
        only_first["nodes"] = [only_first["nodes"][0]]
        result = self.write({"set": {"failure_process": only_first},
                             "kind": "fact_corrected", "reason": "删掉重试节点"})
        changes = result["revision"]["changes"]
        self.assertEqual([c["target"] for c in changes], ["removed:fp-2"])
        self.assertTrue(all(c["after"] == "" for c in changes))
        self.assertEqual(self.load()["failure_process"]["nodes"][0]["id"], "fp-1")

    def test_no_change_raises_e_no_change_and_writes_nothing(self):
        path = self.make()
        payload = {"set": valid_content(), "kind": "fact_corrected", "reason": "首版"}
        self.write(payload)
        snapshot = path.read_bytes()
        with self.assertRaises(tt.Fail) as ctx:
            self.write(payload)
        self.assertEqual(ctx.exception.code, "E_NO_CHANGE")
        self.assertEqual(path.read_bytes(), snapshot)

    def test_unquoted_yaml_time_equals_json_string(self):
        # 手写 trace 里 at 没加引号（PyYAML 解析成 datetime），写入口送同一个时刻的字符串：
        # canonical 深比较应判「没变化」，而不是多出一条无意义的修订。
        self.make(extra='incident_timeline:\n'
                        '  - {id: inc-1, at: 2026-11-12T10:00:00+08:00, what: 挂起, source: log}\n')
        with self.assertRaises(tt.Fail) as ctx:
            self.write({"set": {"incident_timeline": [
                {"id": "inc-1", "at": NOW, "what": "挂起", "source": "log"}]}})
        self.assertEqual(ctx.exception.code, "E_NO_CHANGE")

    def test_change_without_kind_or_reason_rejected(self):
        self.make()
        payload = {"set": {"summary": "新摘要"}}
        with self.assertRaises(tt.Fail) as ctx:
            self.write(payload)
        self.assertEqual(ctx.exception.code, "E_SCHEMA")
        self.assertIn("kind", ctx.exception.message)
        with self.assertRaises(tt.Fail) as ctx:
            self.write({"set": {"summary": "新摘要"}, "kind": "fact_corrected"})
        self.assertEqual(ctx.exception.code, "E_SCHEMA")
        self.assertIn("reason", ctx.exception.message)

    def test_invalid_content_rejected_before_write(self):
        path = self.make()
        snapshot = path.read_bytes()
        bad = valid_content()
        bad["failure_process"]["nodes"] = [{"id": "fp-1", "what": "x", "quote": "q"}] * 9
        with self.assertRaises(tt.Fail) as ctx:
            self.write({"set": bad, "kind": "fact_corrected", "reason": "r"})
        self.assertEqual(ctx.exception.code, "E_SCHEMA")
        self.assertEqual(path.read_bytes(), snapshot)

    def test_unknown_set_field_and_empty_set_rejected(self):
        self.make()
        with self.assertRaises(tt.Fail) as ctx:
            self.write({"set": {"incident_timeline_x": []}, "kind": "fact_corrected",
                        "reason": "r"})
        self.assertEqual(ctx.exception.code, "E_SCHEMA")
        with self.assertRaises(tt.Fail) as ctx:
            self.write({"set": {}, "kind": "fact_corrected", "reason": "r"})
        self.assertEqual(ctx.exception.code, "E_SCHEMA")

    def test_missing_content_file_rejected(self):
        self.make()
        with self.assertRaises(tt.Fail) as ctx:
            tt.apply_transition(ROOT, self.traces, "s1", args(content_file=None))
        self.assertEqual(ctx.exception.code, "E_SCHEMA")
        with self.assertRaises(tt.Fail) as ctx:
            tt.apply_transition(ROOT, self.traces, "s1",
                                args(content_file=str(self.dir / "nope.json")))
        self.assertEqual(ctx.exception.code, "E_SCHEMA")

    def test_clear_field_is_recorded(self):
        self.make()
        self.write({"set": valid_content(), "kind": "fact_corrected", "reason": "首版"})
        self.write({"set": {"upstream_timeline": None}, "kind": "fact_corrected",
                    "reason": "查证后没有上游修复记录"})
        doc = self.load()
        self.assertIsNone(doc["upstream_timeline"])
        self.assertEqual(doc["revisions"][-1]["changes"][0]["target"], "removed:up-1")
        self.assertEqual(tc.validate_content(doc), [])

    def test_by_user_recorded(self):
        self.make()
        self.write({"set": {"summary": "用户更正了现象"}, "kind": "fact_corrected",
                    "reason": "用户更正"}, by="user")
        self.assertEqual(self.load()["revisions"][-1]["by"], "user")

    def test_dry_run_does_not_write(self):
        path = self.make()
        snapshot = path.read_bytes()
        result = self.write({"set": {"summary": "新摘要"}, "kind": "fact_corrected",
                             "reason": "r"}, dry_run=True)
        self.assertTrue(result["dryRun"])
        self.assertEqual(result["changed"], ["summary"])
        self.assertEqual(path.read_bytes(), snapshot)

    def test_cli_round_trip_and_no_change_exit_code(self):
        self.make()
        content_path = self.dir / "cli-content.json"
        content_path.write_text(json.dumps(
            {"set": {"summary": "命令行写出"}, "kind": "fact_corrected", "reason": "r"},
            ensure_ascii=False), encoding="utf-8")
        argv = ["s1", "--root", str(ROOT), "--traces", str(self.traces),
                "--field", "content", "--content-file", str(content_path),
                "--by", "agent", "--json"]
        rc, out = self.run_main(argv)
        self.assertEqual(rc, 0, out)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["changed"], ["summary"])
        self.assertEqual(payload["revision"]["kind"], "fact_corrected")
        self.assertEqual(self.load()["summary"], "命令行写出")
        # 同样的内容再写一次：E_NO_CHANGE（退出码 8），文件不动
        snapshot = (self.traces / "s1.yaml").read_bytes()
        rc, out = self.run_main(argv)
        self.assertEqual(rc, 8, out)
        self.assertEqual(json.loads(out)["code"], "E_NO_CHANGE")
        self.assertEqual((self.traces / "s1.yaml").read_bytes(), snapshot)

    def test_touched_covers_content_fields(self):
        # verify_untouched 用 TOUCHED 判「越权改动」：漏一个字段，写入口会自己回滚。
        for field in tc.WRITABLE_FIELDS + ("revisions",):
            self.assertIn(field, tt.TOUCHED)

    def run_main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = tt.main(argv)
        return rc, out.getvalue()


class VerifyTraceStatusIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.vocab = load_vocab(ROOT)

    def check(self, doc, strict=False):
        entry = {"sessionId": "s1", "doc": doc, "error": None}
        return vt.check_trace(entry, self.vocab, strict, False)

    def test_content_errors_reach_verify_all(self):
        doc = {"session_id": "s1", "status": "in_progress", "summary": "x"}
        doc.update(valid_content())
        doc["failure_process"]["nodes"] = [
            {"id": "fp-1", "what": "x", "quote": "q"}] * 9
        errs = self.check(doc)
        self.assertTrue(any(e.startswith("s1: ") and "超过上限 8" in e for e in errs), errs)

    def test_legacy_trace_still_passes(self):
        doc = {"session_id": "s1", "status": "in_progress", "summary": "x"}
        self.assertEqual(self.check(doc), [])

    def test_hand_edited_content_caught_by_verify_all(self):
        doc = with_revision(valid_content())
        doc["incident_timeline"][0]["what"] = "绕过写入口改的"
        errs = self.check(doc)
        self.assertTrue(any("hash 不一致" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
