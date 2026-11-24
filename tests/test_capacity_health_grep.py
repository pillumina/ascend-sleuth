"""候选溢出率的 grep 参数解析：引号截断会造出恒真判别式，把数字抬高。

为什么值得单测：候选溢出率决定"检索质量恶化"与拆分评估是否触发，算错不会崩，只会给出一个
看起来正常的数——2026-11-24 盘点同一份库，旧解析报 24/51，按 shell 词法切分后 14/51。两处截断都出在
"双引号里含单引号"：`grep -E "...'NoneType' object..."` 被断成 `...|`（空分支恒真），
`grep -aE "Can't find ..."` 被断成 `Can`（过宽）。本文件钉住这两类形状与相邻的解析边界。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import capacity_health as ch  # noqa: E402


class GrepPatternsTest(unittest.TestCase):
    def test_single_quote_inside_double_quotes_keeps_both_alternatives(self):
        """双引号里含单引号时不能截断——否则右侧空分支让判别式恒真。"""
        cmd = ("grep -E \"sfa_cp\\.py.*build_cp_metadata|'NoneType' object has no attribute 'to'\" "
               "{{log_path}}")
        pats = ch.grep_patterns(cmd)
        self.assertEqual(len(pats), 1)
        self.assertIn("'NoneType' object has no attribute 'to'", pats[0])
        self.assertFalse(ch.always_true(pats[0]), "截断后的空分支会被判成恒真")

    def test_apostrophe_word_not_truncated(self):
        """`Can't` 里的单引号不能让模式变成 `Can`。"""
        cmd = ("grep -aE \"Can't find remoteBuffer by key|Failed to put key .*res:\\[-800\\]\" "
               "{{log_path}}")
        pats = ch.grep_patterns(cmd)
        self.assertEqual(pats, ["Can't find remoteBuffer by key|Failed to put key .*res:\\[-800\\]"])

    def test_pattern_after_double_dash(self):
        """`grep -aoE -- '...'` 的 `--` 是选项终止符，后面的模式要取到。"""
        cmd = "grep -aoE -- 'int8_cache=dram|memcache|netloader' {{launch_log}}"
        self.assertEqual(ch.grep_patterns(cmd), ["int8_cache=dram|memcache|netloader"])

    def test_inverted_grep_is_not_a_discriminator(self):
        """`grep -v` 是排除项：把它当症状会让"缺少某行"的输入命中这条 case。"""
        cmd = "ps -eo pid,etime,stat,cmd | grep -E 'vllm serve|EngineCore' | grep -v grep"
        self.assertEqual(ch.grep_patterns(cmd), ["vllm serve|EngineCore"])
        cmd = "grep -rn 'seed_all()' {{train_code_path}} | grep -v 'mode=True'"
        self.assertEqual(ch.grep_patterns(cmd), ["seed_all()"])

    def test_bare_word_is_not_a_discriminator(self):
        """未加引号的裸词是取日志的手段，不是"这条 case 认什么症状"。"""
        self.assertEqual(ch.grep_patterns("grep -i version"), [])

    def test_escaped_quotes_in_pattern_are_kept(self):
        """双引号内的转义引号解码成普通引号，模式仍应取到。"""
        cmd = r'grep -aoE "\"reasoning_tokens\":[0-9]+" {{sampled_completion}}'
        self.assertEqual(ch.grep_patterns(cmd), ['"reasoning_tokens":[0-9]+'])

    def test_double_backslash_in_pattern_is_decoded(self):
        """双反斜杠在引号内解码为单反斜杠；解码后的词不能拿去与原文比子串，否则会静默丢掉。"""
        cmd = r'grep -E "dispatch_ffn_combine\\(\\) Expected" {{log_path}}'
        self.assertEqual(ch.grep_patterns(cmd), [r"dispatch_ffn_combine\(\) Expected"])

    def test_bare_word_with_quoted_file_name_is_not_a_discriminator(self):
        """模式是裸词、文件参数带引号时，不能把文件参数误当判别式。"""
        self.assertEqual(ch.grep_patterns("grep -i version 'version'"), [])

    def test_explicit_pattern_option_and_terminator(self):
        """`-e` 与 `--` 后的引号模式都是 grep 的判别式。"""
        self.assertEqual(ch.grep_patterns("grep -e 'foo|bar' {{log_path}}"), ["foo|bar"])
        self.assertEqual(ch.grep_patterns("grep -- 'foo|bar' {{log_path}}"), ["foo|bar"])

    def test_pattern_file_option_stops_extraction(self):
        """`grep -f patterns.txt` 后面跟的是待搜文件，不能当模式。"""
        self.assertEqual(ch.grep_patterns("grep -f patterns.txt 'log-file'"), [])
        self.assertEqual(ch.grep_patterns("grep --file=patterns.txt 'log-file'"), [])

    def test_fixed_string_is_escaped(self):
        """`-F` 的固定串按字面量比对，不能被当成正则。"""
        self.assertEqual(ch.grep_patterns("grep -F 'a.b' {{log_path}}"), [r"a\.b"])

    def test_unbalanced_quotes_do_not_crash(self):
        """命令模板写坏时返回空，不抛异常——取不到判别式比整个度量崩掉好定位。"""
        self.assertEqual(ch.grep_patterns('grep -E "Can\'t {{log_path}}'), [])

    def test_patterns_of_case_keeps_expected_regex(self):
        """两条来源都保留：命令模板的 grep 模式与 `expected` 的 regex 断言。"""
        case = {
            "quickly_check": {
                "primary": {
                    "command_template": "grep -E 'foo' {{log_path}}",
                    "expected": "regex:foo|bar",
                }
            }
        }
        self.assertEqual(ch.patterns_of_case(case), ["foo", "foo|bar"])


if __name__ == "__main__":
    unittest.main()
