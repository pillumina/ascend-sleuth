"""P1 regression tests; no Ascend tools, live probes, or model files required."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'references' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


c = load('compare_dumps')
d = load('msprechecker_dump')


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dump P1 ')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def compare(self, documents, names=None):
        paths = []
        for i, data in enumerate(documents):
            p = self.base / (names[i] if names else f'{i}.json')
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data), encoding='utf-8')
            paths.append(str(p))
        comparator = c.DumpComparator(paths)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(comparator.load_files())
        return comparator.compare()

    def test_same_basename_keeps_both_environments(self):
        r = self.compare([{'x': 1}, {'x': 2}], ['good/snapshot.json', 'bad/snapshot.json'])
        self.assertEqual(len(set(r['files'])), 2)
        self.assertEqual(r['diff_count'], 1)

    def test_json_types_are_not_coerced(self):
        for a, b in [(1, '1'), (True, 'True'), ({}, '{}'), ([], '[]'), ({'0': 1}, [1])]:
            with self.subTest(a=a, b=b):
                self.assertGreater(self.compare([{'x': a}, {'x': b}])['diff_count'], 0)

    def test_null_is_present_and_distinct_from_missing(self):
        r = self.compare([{'x': None, 'y': 1}, {'y': 1}])
        self.assertEqual(r['diff_count'], 1)
        item = r['diffs']['other']['only_in'][0]
        self.assertEqual(list(item['values'].values()), [None])
        self.assertEqual(len(item['present_in']), 1)

    def test_literal_keys_do_not_collide_with_nested_paths(self):
        a = {'a.b': 1, 'a': {'b': 2}, '': 3, 'x[0]': 4, 'x': [5]}
        b = {'a.b': 9, 'a': {'b': 2}, '': 3, 'x[0]': 8, 'x': [5]}
        self.assertEqual(self.compare([a, b])['diff_count'], 2)

    def test_metadata_exclusion_is_exact(self):
        r = self.compare([{'_meta': {'x': 1}, '_metadata': 1}, {'_meta': {'x': 2}, '_metadata': 2}])
        self.assertEqual(r['diff_count'], 1)

    def test_partial_load_reports_only_successful_files(self):
        paths = []
        for name, content in [('a.json', '{"x":1}'), ('bad.json', 'bad'), ('b.json', '{"x":1}')]:
            p = self.base / name
            p.write_text(content, encoding='utf-8')
            paths.append(str(p))
        obj = c.DumpComparator(paths)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertTrue(obj.load_files())
        r = obj.compare()
        self.assertEqual(len(r['files']), 2)
        self.assertEqual(r.get('status'), 'partial')
        self.assertEqual(len(r.get('skipped_files', [])), 1)
        out = self.base / 'diff.json'
        with contextlib.redirect_stdout(io.StringIO()):
            c.output_json(r, str(out))
        saved = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(saved.get('status'), 'partial')

    def test_html_escapes_untrusted_text(self):
        attack = '<img src=x onerror=alert(1)>'
        r = self.compare([{'_meta': {'hostname': attack}, attack: 1}, {attack: 2}])
        out = self.base / 'report.html'
        with contextlib.redirect_stdout(io.StringIO()):
            c.output_html(r, str(out))
        html = out.read_text(encoding='utf-8')
        self.assertNotIn(attack, html)
        self.assertIn('&lt;img', html)

    def test_high_similarity_does_not_claim_changes_are_safe(self):
        a = {str(i): i for i in range(100)}
        b = dict(a, **{'0': -1})
        out = self.base / 'report.html'
        with contextlib.redirect_stdout(io.StringIO()):
            c.output_html(self.compare([a, b]), str(out))
        self.assertNotIn('不影响核心功能', out.read_text(encoding='utf-8'))

    def test_legacy_dump_secrets_do_not_reach_any_report(self):
        secret = 'fixture-secret-123'
        r = self.compare([{'env': {'API_KEY': secret}}, {'env': {'API_KEY': 'different-secret'}}])
        out = self.base / 'diff.json'
        html = self.base / 'report.html'
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            c.output_text(r)
            c.output_json(r, str(out))
            c.output_html(r, str(html))
        self.assertNotIn(secret, buf.getvalue() + out.read_text(encoding='utf-8') + html.read_text(encoding='utf-8'))

    def test_masked_differences_keep_file_value_mapping(self):
        r = self.compare([{'env': {'API_KEY': 'old-value'}}, {'env': {'API_KEY': 'new-value'}}])
        self.assertEqual(r['diff_count'], 1)
        self.assertTrue(all(isinstance(values, dict) for values in r['all_diffs'].values()))

    def test_short_secret_does_not_corrupt_evidence_path(self):
        r = self.compare([{'env': {'TOKEN': 'x'}, 'x': 1}, {'env': {'TOKEN': 'y'}, 'x': 2}])
        paths = [item['path'] for group in r['diffs'].values() for item in group['modified']]
        self.assertTrue(any('"x"' in path for path in paths))

    def test_old_process_arguments_are_omitted_from_all_reports(self):
        secret = 'positional-fixture-value'
        a = {'runtime': {'targets': [{'cmd': 'python serve.py ' + secret}], 'ps_raw': ['python ' + secret]}}
        b = {'runtime': {'targets': [{'cmd': 'python other.py'}], 'ps_raw': []}}
        r = self.compare([a, b])
        out, html = self.base / 'diff.json', self.base / 'report.html'
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            c.output_text(r)
            c.output_json(r, str(out))
            c.output_html(r, str(html))
        self.assertNotIn(secret, buf.getvalue() + out.read_text(encoding='utf-8') + html.read_text(encoding='utf-8'))

    def test_file_label_that_mentions_token_does_not_break_reports(self):
        r = self.compare([{'x': 1}, {'x': 2}], ['token.json', 'other.json'])
        self.assertIsInstance(r['meta']['token.json'], dict)
        out = self.base / 'report.html'
        with contextlib.redirect_stdout(io.StringIO()):
            c.output_html(r, str(out))

    def test_model_token_limits_are_not_masked(self):
        r = self.compare([{'model config': {'max_tokens': 100}}, {'model config': {'max_tokens': 200}}])
        values = r['diffs']['config']['modified'][0]['values']
        self.assertEqual(set(values.values()), {100, 200})

    def test_secret_and_token_fields_with_suffixes_are_masked(self):
        a = {'env': {'SECRET_KEY': 'old-secret-fixture', 'TOKEN_VALUE': 'old-token-fixture'}}
        b = {'env': {'SECRET_KEY': 'new-secret-fixture', 'TOKEN_VALUE': 'new-token-fixture'}}
        r = self.compare([a, b])
        for item in r['diffs']['env']['modified']:
            self.assertEqual(set(item['values'].values()), {'***MASKED***'})

    def test_cli_same_name_partial_inputs_and_both_reports(self):
        paths = []
        for folder, doc in [('甲 目录', {'x': 1, 'n': None, 'api_key': 'fixture-cli-secret-a'}),
                            ('乙 目录', {'x': '1', 'api_key': 'fixture-cli-secret-b'})]:
            p = self.base / folder / 'snapshot.json'
            p.parent.mkdir()
            p.write_text(json.dumps(doc), encoding='utf-8')
            paths.append(str(p))
        invalid = self.base / 'invalid.json'
        invalid.write_text('not json', encoding='utf-8')
        out, html = self.base / 'diff.json', self.base / 'report.html'
        proc = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(ROOT / 'references/compare_dumps.py'),
                               *paths, str(invalid), '--json', str(out), '--html', str(html)],
                              capture_output=True, text=True, encoding='utf-8', timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        saved = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(saved['summary']['diff_count'], 3)
        self.assertEqual(saved['status'], 'partial')
        self.assertEqual(len(saved['files']), 2)
        self.assertEqual(len(saved['skipped_files']), 1)
        self.assertNotIn('fixture-cli-secret', proc.stdout + out.read_text(encoding='utf-8') + html.read_text(encoding='utf-8'))


class CollectorTests(unittest.TestCase):
    def test_filter_retains_all_documented_critical_variables(self):
        values = {k: 'value' for k in ('ASCEND_HOME_PATH', 'ASCEND_TOOLKIT_HOME', 'LD_LIBRARY_PATH',
                  'MINDIE_LLM_HOME_PATH', 'ATB_HOME_PATH', 'ATB_SPEED_HOME_PATH', 'HCCL_BUFFSIZE',
                  'TASK_QUEUE_ENABLE', 'RANK_TABLE_FILE', 'OMP_NUM_THREADS', 'PYTORCH_NPU_ALLOC_CONF')}
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(set(d.EnvCollector(True).collect().data), set(values))

    def test_non_contiguous_devices_are_enumerated(self):
        def fake_stat(path):
            if str(path).replace('\\', '/') in ('/dev/davinci2', '/dev/davinci7'):
                return types.SimpleNamespace(st_mode=stat.S_IFCHR)
            raise FileNotFoundError(path)
        with patch.object(d.os, 'listdir', return_value=['davinci2', 'davinci7', 'davinci_manager']), patch.object(d.os, 'stat', side_effect=fake_stat):
            self.assertEqual(d.get_npu_count(), 2)

    def test_sparse_device_ids_are_used_in_queries(self):
        with patch.object(d, 'get_npu_device_ids', return_value=[2, 7], create=True), patch.object(d, 'which', return_value='/tool'):
            obj = d.NPUCollector()
            with patch.object(obj, '_collect_one_device', side_effect=lambda i: {'device_id': i}):
                data = obj._collect_per_device()
        self.assertEqual([item['device_id'] for item in data['devices']], [2, 7])

    def test_failed_rank_table_is_not_reported_as_unrequested(self):
        args = types.SimpleNamespace(filter=True, rank_table_path='missing.json', scene='mindie',
                                     mies_config_path=None, user_config_path=None, mindie_env_path=None,
                                     weight_dir=None, chunk_size=32)
        with contextlib.ExitStack() as stack:
            for cls in (d.SysCollector, d.HardwareCollector, d.NPUCollector, d.AscendCollector,
                        d.EnvCollector, d.RuntimeCollector, d.NetworkCollector):
                stack.enter_context(patch.object(cls, 'collect', lambda obj: d.CollectorResult({}, obj.collect_type)))
            stack.enter_context(patch.object(d, 'parse_rank_table', side_effect=ValueError('bad rank table')))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            data = d.collect_all(args)
        self.assertEqual(data['_meta']['collection']['hccl']['status'], 'failed')
        self.assertIn('bad rank table', data['_meta']['collection']['hccl']['errors'])

    def test_zero_devices_does_not_construct_empty_pool(self):
        with patch.object(d, 'get_npu_count', return_value=0), patch.object(d.os, 'listdir', return_value=[]), patch.object(d, 'which', return_value='/tool'):
            r = d.HCCNCollector('link', 'link').collect()
        self.assertEqual(r.data, [])
        self.assertTrue(r.errors)

    def test_hccn_timeout_becomes_diagnostic_data(self):
        obj = d.HCCNCollector('link', 'link')
        def timeout(cmd, **kwargs):
            if not kwargs.get('timeout'):
                return 'would hang without a timeout'
            raise subprocess.TimeoutExpired(cmd, kwargs['timeout'])
        with patch.object(d.subprocess, 'check_output', side_effect=timeout), patch.object(d.subprocess, 'run', side_effect=timeout):
            result = obj._run_cmd(2)
        self.assertNotIn('would hang', str(result))
        self.assertIn('timeout', str(result).lower())

    def test_command_output_does_not_deadlock_and_stderr_is_preserved(self):
        code = 'import sys; print("x"*200000); print("failure detail",file=sys.stderr); sys.exit(7)'
        # POSIX parsing of quoted argv is portable when shell=False.
        cmd = [sys.executable, '-c', code]
        rc, output = d.run_cmd(cmd, timeout=5)
        self.assertEqual(rc, 7)
        self.assertTrue('failure detail' in output, 'stderr diagnostic was discarded')
        self.assertGreater(len(output), 200000)

    def test_run_cmd_timeout_is_bounded(self):
        rc, output = d.run_cmd([sys.executable, '-c', 'import time; time.sleep(10)'], timeout=0.1)
        self.assertNotEqual(rc, 0)
        self.assertIn('timeout', output.lower())

    def test_config_and_embedded_command_secrets_are_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'config.json'
            p.write_text(json.dumps({'password': 'fixture-password', 'nested': {'apiKey': 'fixture-api-key'},
                                    'url': 'https://alice:fixture-pass@host/a',
                                    'command': 'python serve.py --token fixture-token --port 8000'}), encoding='utf-8')
            payload = json.dumps(d.ConfigCollector(str(p)).collect().data)
        for secret in ('fixture-password', 'fixture-api-key', 'fixture-pass', 'fixture-token'):
            self.assertNotIn(secret, payload)

    def test_config_secret_key_and_token_value_are_masked(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'config.json'
            p.write_text(json.dumps({'SECRET_KEY': 'suffix-secret-fixture', 'TOKEN_VALUE': 'suffix-token-fixture',
                                    'max_tokens': 4096}), encoding='utf-8')
            result = d.ConfigCollector(str(p)).collect().data
        self.assertEqual(result['SECRET_KEY'], '***MASKED***')
        self.assertEqual(result['TOKEN_VALUE'], '***MASKED***')
        self.assertEqual(result['max_tokens'], 4096)

    def test_runtime_arguments_are_omitted(self):
        obj = d.RuntimeCollector()
        def read_file(path):
            if path.endswith('/cmdline'):
                return 'python\0serve.py\0positional-secret\0--port\08000\0'
            return ''
        with patch.object(d.os, 'listdir', return_value=['123']), patch.object(d.os, 'getpid', return_value=999), patch.object(obj, '_read_file', side_effect=read_file), patch.object(d, 'run_cmd', return_value=(0, 'ps fixture')):
            data = obj._collect_processes()
        self.assertNotIn('positional-secret', json.dumps(data))
        self.assertEqual(data['targets'][0]['executable'], 'python')

    def test_argv_credentials_are_masked_in_error_records(self):
        data = {'command': ['tool', '--token', 'argument-secret', '--port', '8000']}
        text = json.dumps(d.redact_sensitive(data))
        self.assertNotIn('argument-secret', text)
        self.assertIn('8000', text)

    def test_structured_read_error_is_partial_not_success(self):
        args = types.SimpleNamespace(filter=True, rank_table_path=None, scene=None,
                                     mies_config_path=None, user_config_path=None, mindie_env_path=None,
                                     weight_dir=None, chunk_size=32)
        with contextlib.ExitStack() as stack:
            for cls in (d.SysCollector, d.HardwareCollector, d.NPUCollector, d.AscendCollector,
                        d.EnvCollector, d.RuntimeCollector, d.NetworkCollector):
                stack.enter_context(patch.object(cls, 'collect', lambda obj: d.CollectorResult({'sample': 1}, obj.collect_type)))
            stack.enter_context(patch.object(d.HardwareCollector, 'collect', return_value=d.CollectorResult({'memory': {'error': 'permission denied'}}, 'hardware')))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            data = d.collect_all(args)
        state = data['_meta']['collection']['hardware']
        self.assertEqual(state['status'], 'partial')
        self.assertTrue(state['errors'])

    def test_unavailable_npu_query_has_explicit_status(self):
        with patch.object(d, 'get_npu_device_ids', return_value=[], create=True), patch.object(d, 'which', return_value=None), patch.object(d.os.path, 'isfile', return_value=False):
            obj = d.NPUCollector()
            snapshot = obj._collect_smi()
            devices = obj._collect_per_device()
        states = [value.get('collection_status') for payload in (snapshot, devices)
                  for value in payload.values() if isinstance(value, dict)]
        self.assertEqual(states, ['unavailable', 'unavailable'])

    def test_npu_unavailable_makes_dump_partial(self):
        args = types.SimpleNamespace(filter=True, rank_table_path=None, scene=None,
                                     mies_config_path=None, user_config_path=None, mindie_env_path=None,
                                     weight_dir=None, chunk_size=32)
        with contextlib.ExitStack() as stack:
            for cls in (d.SysCollector, d.HardwareCollector, d.AscendCollector, d.EnvCollector,
                        d.RuntimeCollector, d.NetworkCollector):
                stack.enter_context(patch.object(cls, 'collect', lambda obj: d.CollectorResult({'sample': 1}, obj.collect_type)))
            stack.enter_context(patch.object(d.NPUCollector, '_resolve_smi', return_value=None))
            for method in ('_collect_device_nodes', '_collect_optical', '_collect_log_dirs'):
                stack.enter_context(patch.object(d.NPUCollector, method, return_value={}))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            data = d.collect_all(args)
        self.assertEqual(data['_meta']['collection']['npu']['status'], 'partial')
        self.assertEqual(data['_meta']['status'], 'partial')

    def test_main_preserves_state_metadata_in_saved_dump(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'snapshot.json'
            state = {'schema_version': '1.1', 'status': 'partial',
                     'collection': {'system': {'status': 'failed', 'errors': ['fixture']}}}
            with patch.object(d, 'collect_all', return_value={'_meta': state, 'env': {}}), patch.object(sys, 'argv', ['dump', '-o', str(output)]), contextlib.redirect_stdout(io.StringIO()):
                d.main()
            saved = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(saved['_meta']['collection']['system']['status'], 'failed')
        self.assertEqual(saved['_meta']['status'], 'partial')
        self.assertEqual(saved['_meta']['tool'], 'msprechecker_dump.py')

    def test_failed_and_skipped_collection_states_survive_dump(self):
        args = types.SimpleNamespace(filter=True, rank_table_path=None, scene=None,
                                     mies_config_path=None, user_config_path=None, mindie_env_path=None,
                                     weight_dir=None, chunk_size=32)
        def ok(obj):
            return d.CollectorResult({'sample': 1}, obj.collect_type)
        with contextlib.ExitStack() as stack:
            for cls in (d.SysCollector, d.HardwareCollector, d.NPUCollector, d.AscendCollector,
                        d.EnvCollector, d.RuntimeCollector, d.NetworkCollector):
                stack.enter_context(patch.object(cls, 'collect', ok))
            stack.enter_context(patch.object(d.SysCollector, 'collect', side_effect=PermissionError('fixture denied')))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            data = d.collect_all(args)
        states = data.get('_meta', {}).get('collection', {})
        self.assertEqual(states.get('system', {}).get('status'), 'failed')
        self.assertEqual(states.get('ping', {}).get('status'), 'skipped')
        self.assertEqual(states.get('env', {}).get('scope'), 'filtered')


if __name__ == '__main__':
    unittest.main()
