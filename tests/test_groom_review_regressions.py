"""独立预核反例的回归：内容空白、分类绑定、引用失败与人工合并目标。"""

import copy
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from tests import test_groom_recheck as fixtures  # noqa: E402
from tests.groom_fixtures import commit_all, git  # noqa: E402
import groom_recheck as recheck  # noqa: E402
from groom_common import canonical_content_sha  # noqa: E402
from groom_decide import apply_decision  # noqa: E402
from groom_record import pr_marker  # noqa: E402


class ReviewRegressionTest(unittest.TestCase):
    def fixture(self):
        x = fixtures.RecheckTest(); x.setUp()
        self.addCleanup(x.doCleanups)
        return x

    def test_semantic_whitespace_changes_content_hash(self):
        for field, before, after in [
            ('fix', "printf '%s' 'a  b'", "printf '%s' 'a b'"),
            ('quickly_check', {'primary': {'expected': 'regex:foo  bar'}},
             {'primary': {'expected': 'regex:foo bar'}}),
            ('diagnosis', [{'command_template': 'echo one\necho two'}],
             [{'command_template': 'echo one echo two'}]),
        ]:
            with self.subTest(field=field):
                a = {'id': 'CASE-X', field: before}; b = copy.deepcopy(a); b[field] = after
                self.assertNotEqual(canonical_content_sha(a), canonical_content_sha(b))

    def test_submitted_quoted_payload_change_is_rejected(self):
        x = self.fixture(); git(x.repo, 'checkout', '-q', 'pr-b')
        rel = 'knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml'; path = x.repo / rel
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
        data['cases'][0]['fix'] = "printf '%s' 'a  b'"
        sha = canonical_content_sha(data['cases'][0])
        data['cases'][0]['fix'] = "printf '%s' 'a b'"
        path.write_text(yaml.safe_dump(data), encoding='utf-8')
        head = commit_all(x.repo, 'changed quoted payload')
        out, _ = recheck.check(fixtures.marker(x.m0, sha), x.repo, x.m0, head, True)
        self.assertIn('content-mismatch', [f['code'] for f in out])

    def test_category_cannot_hide_old_assessment(self):
        x = self.fixture(); git(x.repo, 'checkout', '-q', '-b', 'modified-main', x.m0)
        rel = 'knowledge/inference/vllm-ascend/interrupt/CASE-A.yaml'; path = x.repo / rel
        path.write_text(path.read_text(encoding='utf-8').replace('link failure', 'changed root'), encoding='utf-8')
        base = commit_all(x.repo, 'modify existing case')
        git(x.repo, 'checkout', '-q', 'pr-b'); git(x.repo, 'merge', '--no-edit', 'modified-main')
        head = git(x.repo, 'rev-parse', 'HEAD').stdout.strip()
        for category, code in [('interrupt', 'assessment-stale'),
                               ('precision', 'category-mismatch'),
                               ('not-a-category', 'marker-invalid')]:
            with self.subTest(category=category):
                body = fixtures.marker(x.m0, x.b_sha, category=category)
                out, _ = recheck.check(body, x.repo, base, head, True)
                self.assertIn(code, [f['code'] for f in out])
                md = x.base / 'review-body.md'; md.write_text(body, encoding='utf-8')
                proc = subprocess.run([sys.executable, str(x.repo/'scripts/groom_recheck.py'),
                                       '--repo', str(x.repo), '--base', base, '--head', head,
                                       '--pr-body-file', str(md), '--enforce', '--json'],
                                      capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)

    def test_invalid_refs_are_rejected(self):
        x = self.fixture()
        body = fixtures.marker(x.m0, x.a_sha, submitted_case_id='CASE-A',
                               novelty='covered', candidate='CASE-A', human='covered')
        for base, head in [(x.m0, 'missing-review-head'), ('missing-review-base', x.head_b)]:
            out, _ = recheck.check(body, x.repo, base, head, True)
            self.assertEqual(out[0]['code'], 'git-ref-unavailable')

    def test_failed_diff_is_not_an_empty_change(self):
        x = self.fixture(); original = recheck.run_git
        def fail_diff(args, **kwargs):
            if args[0] == 'diff':
                return subprocess.CompletedProcess(args, 128, '', 'simulated object read failure')
            return original(args, **kwargs)
        with patch.object(recheck, 'run_git', side_effect=fail_diff):
            out, _ = recheck.check(fixtures.marker(x.m0, x.b_sha), x.repo, x.m0, x.head_b, True)
        self.assertEqual(out[0]['code'], 'git-read-failed')

    def test_failed_or_corrupt_case_read_is_not_no_change(self):
        x = self.fixture(); original = recheck.run_git
        body = fixtures.marker(x.m0, x.a_sha, submitted_case_id='CASE-A',
                               novelty='covered', candidate='CASE-A', human='covered')
        for code, data in [(128, ''), (0, 'cases: ['), (0, 'cases: []')]:
            with self.subTest(code=code, data=data):
                def fail_show(args, **kwargs):
                    if args[0] == 'show' and args[1].endswith('/CASE-B.yaml'):
                        return subprocess.CompletedProcess(args, code, data, 'simulated read failure')
                    return original(args, **kwargs)
                with patch.object(recheck, 'run_git', side_effect=fail_show):
                    out, _ = recheck.check(body, x.repo, x.m0, x.head_b, True)
                self.assertEqual(out[0]['code'], 'git-read-failed')

    def test_human_target_overrides_agent_candidate_end_to_end(self):
        x = self.fixture(); git(x.repo, 'checkout', '-q', 'main')
        rel = 'knowledge/inference/vllm-ascend/interrupt/CASE-A.yaml'; path = x.repo / rel
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
        data['cases'][0]['fix'] = 'approved fix'
        path.write_text(yaml.safe_dump(data), encoding='utf-8')
        head = commit_all(x.repo, 'human approved target A')
        sha = canonical_content_sha(data['cases'][0]); assessment_id = 'a' * 64
        doc = {'draft': 'd', 'draft_case_id': 'DRAFT-X', 'draft_category': 'interrupt',
               'assessment_id': assessment_id, 'content_binding': {'sha256': sha},
               'provenance': {'compared_against_commit': x.m1},
               'assessment': {'proposed_novelty': 'variant', 'candidate_case': 'CASE-C'},
               'human_decision_valid': True,
               'human_decision': {'decision': 'variant', 'candidate_case': 'CASE-A',
                                  'assessment_id': assessment_id, 'content_sha256': sha}}
        body = pr_marker(doc, submitted_case_id='CASE-A')
        self.assertEqual(recheck.parse_marker(body)['candidate_case'], 'CASE-A')
        out, _ = recheck.check(body, x.repo, x.m1, head, True)
        self.assertEqual(out, [])
        # 有效的人工 new_pattern 不应借用 agent 的候选。
        doc['human_decision_valid'] = True
        doc['human_decision'].update(decision='new_pattern', candidate_case=None)
        marker = recheck.parse_marker(pr_marker(doc, submitted_case_id='CASE-A'))
        self.assertEqual(marker['candidate_case'], '')
        # 没有有效人工批准时保留 agent 建议，不冒用人的目标。
        doc['human_decision_valid'] = False
        marker = recheck.parse_marker(pr_marker(doc, submitted_case_id='CASE-A'))
        self.assertEqual(marker['candidate_case'], 'CASE-C')
        self.assertEqual(marker['human_decision'], 'pending')

    def test_human_new_pattern_override_without_candidate_passes(self):
        x = self.fixture()
        doc = {
            'draft': 'd', 'draft_case_id': 'CASE-B',
            'draft_category': 'interrupt', 'assessment_id': 'a' * 64,
            'content_binding': {'sha256': x.b_sha},
            'provenance': {'compared_against_commit': x.m0,
                           'snapshot_authoritative': True},
            'assessment': {'proposed_novelty': 'variant',
                           'candidate_case': 'CASE-A', 'review_required': True},
        }
        doc, _ = apply_decision(doc, 'new_pattern', None, 'reviewer',
                                'different root cause')
        body = pr_marker(doc, submitted_case_id='CASE-B')
        findings, _ = recheck.check(body, x.repo, x.m0, x.head_b, True)
        self.assertEqual(findings, [])

    def test_human_variant_without_target_is_still_rejected(self):
        x = self.fixture()
        body = fixtures.marker(x.m0, x.b_sha, novelty='variant',
                               candidate='', human='variant')
        findings, _ = recheck.check(body, x.repo, x.m0, x.head_b, True)
        self.assertIn('marker-invalid', [f['code'] for f in findings])


if __name__ == '__main__':
    unittest.main()
