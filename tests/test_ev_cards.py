"""_ev_cards：合入指针判定（ev_proposal 与 ev_board_data 的唯一口径）。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import _ev_cards  # noqa: E402


class MergePointerTest(unittest.TestCase):
    def test_pr_and_issue_numbers_count(self):
        for text in ("随 PR #278 进入 main", "改动随 PR#97", "见 #1234"):
            self.assertTrue(_ev_cards.has_merge_pointer(text), text)

    def test_plain_numbers_and_short_refs_do_not_count(self):
        for text in ("", "没有编号", "共 3 次", "#1", "issue 1234"):
            self.assertFalse(_ev_cards.has_merge_pointer(text), text)

    def test_old_alias_keeps_working(self):
        self.assertIs(_ev_cards._has_any_ref, _ev_cards.has_merge_pointer)


if __name__ == "__main__":
    unittest.main()
