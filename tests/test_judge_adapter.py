"""judge_adapter：提示拼装与环境变量读取。"""

import os
import sys
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import judge_adapter as ja  # noqa: E402


class PromptTest(unittest.TestCase):
    def test_expected_and_output_are_embedded(self):
        prompt = ja._prompt("candidate text", {"namespace": "inference/vllm-ascend"})
        self.assertIn("inference/vllm-ascend", prompt)
        self.assertIn("candidate text", prompt)
        self.assertIn('"score"', prompt)

    def test_output_is_clipped_to_last_6000_chars(self):
        prompt = ja._prompt("x" * 7000 + "TAIL", {})
        self.assertNotIn("x" * 7000, prompt)
        self.assertIn("TAIL", prompt)


class EnvTest(unittest.TestCase):
    def test_missing_env_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ja.JudgeError):
                ja._env("SLEUTH_OUT")

    def test_present_env_is_returned(self):
        with mock.patch.dict(os.environ, {"SLEUTH_OUT": "path.txt"}):
            self.assertEqual(ja._env("SLEUTH_OUT"), "path.txt")


class ScoreTest(unittest.TestCase):
    def test_echo_scores_one_without_subprocess(self):
        self.assertEqual(ja._score("echo", "prompt", 1.0), 1)

    def test_unknown_agent_raises(self):
        with self.assertRaises(ja.JudgeError):
            ja._score("magic", "prompt", 1.0)


if __name__ == "__main__":
    unittest.main()
