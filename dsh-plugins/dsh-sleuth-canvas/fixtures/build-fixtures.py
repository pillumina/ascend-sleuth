#!/usr/bin/env python3
"""重新生成 fixtures/ 下的 JSON 样例（仅开发用，不进运行时）。

做法（不手抄字段，避免与 host 实现漂移）：
  1. 把 fixtures/trace-samples/ 复制进一个临时目录，补上 scripts/metrics_health.py 标记，
     得到一个最小可用的 ascend-sleuth 假仓库；
  2. 用 node 跑 host/index.js 的 createHost（假 fs + sessions），把 list / detail 的
     真实输出写成 fixtures/list-sample.json 与 fixtures/detail-<session_id>.json；
     repo.path / generatedAt / version 换成固定占位，保证每次生成字节一致；
  3. 用 PyYAML 回读三份 trace 做交叉校验（session_id、事件数、证据文件存在），
     防止手写 YAML 与 host 解析器（自研子集解析器）口径分叉。

运行：python3 fixtures/build-fixtures.py
依赖：python3 + PyYAML；node 在 PATH 里。

fixtures/detail-sample.json 取事件数最多的那份 detail（页面与渲染冒烟用）。
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
TRACES = HERE / 'trace-samples'
HOST_ENTRY = PLUGIN / 'host' / 'index.js'

REPO_PLACEHOLDER = '/path/to/ascend-sleuth'
GENERATED_AT = '2026-01-05T12:00:00+08:00'

NODE_EXPORT = r'''
import fsp from 'node:fs/promises'
import path from 'node:path'

const [repoRoot, outDir, hostPath] = process.argv.slice(2)

function fail(message) {
  console.error('EXPORT FAILED: ' + message)
  process.exit(1)
}

const { __test } = await import(new URL('file://' + hostPath))
const target = (p) => ({ path: p, displayPath: p })

// 假 fs：语义照 docs/CONTRACT.md §2（resolve / readText / listDir / stat）。
const fakeFs = {
  async resolve(p, opts) {
    const cwd = opts && opts.cwd ? opts.cwd : repoRoot
    return target(path.isAbsolute(p) ? path.normalize(p) : path.resolve(cwd, p))
  },
  async readText(t) {
    return fsp.readFile(t.displayPath, 'utf8')
  },
  async listDir(t) {
    const entries = await fsp.readdir(t.displayPath, { withFileTypes: true })
    const out = []
    for (const entry of entries) {
      const full = path.join(t.displayPath, entry.name)
      let size = null
      try {
        const info = await fsp.stat(full)
        size = info.size
      } catch (error) { /* 拿不到大小就 null，host 会退回读文本 */ }
      out.push({ name: entry.name, type: entry.isDirectory() ? 'directory' : 'file', version: null, size })
    }
    return out
  },
  async stat(t) {
    try {
      const info = await fsp.stat(t.displayPath)
      return { type: info.isDirectory() ? 'directory' : 'file', size: info.size }
    } catch (error) {
      const notFound = new Error('not found: ' + t.displayPath)
      notFound.code = 'FS_NOT_FOUND'
      throw notFound
    }
  },
}

const header = { cwd: repoRoot }
const sessions = {
  async list() { return [{ header }] },
  async get() { return { header } },
}
const ctx = {
  get(name) {
    if (name === 'fs') return fakeFs
    if (name === 'sessions') return sessions
    return undefined
  },
}

const host = __test.createHost(ctx)
const list = await host.list({ sessionId: 'fixture-session' })
if (list.warnings.length) fail('list 返回了 warning: ' + JSON.stringify(list.warnings))
list.repo = { path: '/path/to/ascend-sleuth', detected: true }
list.generatedAt = '2026-01-05T12:00:00+08:00'
for (const session of list.sessions) session.version = null

const files = (await fsp.readdir(path.join(repoRoot, 'traces'), { withFileTypes: true }))
  .filter((entry) => entry.isFile() && entry.name.endsWith('.yaml'))
  .map((entry) => entry.name)
  .sort()

const details = []
for (const file of files) {
  const detail = await host.detail({ sessionId: 'fixture-session', file })
  if (detail.warnings.length) fail('detail ' + file + ' 返回了 warning: ' + JSON.stringify(detail.warnings))
  detail.session.version = null
  details.push({ file, detail })
}

const writeJson = async (name, value) => {
  // 机器读的契约样例：一行 JSON，减少 diff 体积；可读内容在 fixtures/README.md 与 docs/CONTRACT.md。
  await fsp.writeFile(path.join(outDir, name), JSON.stringify(value) + '\n', 'utf8')
}

await writeJson('list-sample.json', list)

let sample = null
for (const item of details) {
  const id = item.detail.session.id
  await writeJson('detail-' + id + '.json', item.detail)
  if (sample === null || item.detail.events.length > sample.detail.events.length) sample = item
}
const top = sample.detail.events.length
const ties = details.filter((item) => item.detail.events.length === top)
if (ties.length !== 1) fail('事件数最多的 trace 不唯一: ' + ties.map((item) => item.file).join(', '))
await writeJson('detail-sample.json', sample.detail)

console.log(JSON.stringify({
  list: 'list-sample.json',
  sample: 'detail-sample.json',
  sessions: list.sessions.map((session) => ({
    file: session.file,
    id: session.id,
    eventCount: session.eventCount,
    stepCount: session.stepCount,
  })),
  details: details.map((item) => ({
    source: item.file,
    file: 'detail-' + item.detail.session.id + '.json',
    events: item.detail.events.length,
  })),
}))
'''


def ensure_traces() -> list[Path]:
    traces = sorted(TRACES.glob('*.yaml'))
    if not traces:
        raise SystemExit('fixtures/trace-samples/ 下没有 trace YAML')
    return traces


def copy_repo(root: Path) -> None:
    shutil.copytree(TRACES, root / 'traces')
    scripts = root / 'scripts'
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / 'metrics_health.py').write_text('# 合成夹具仓库标记：host 用它识别仓库根\n', encoding='utf-8')


def run_host_export(repo_root: Path, out_dir: Path) -> dict:
    with tempfile.NamedTemporaryFile('w', suffix='.mjs', delete=False, encoding='utf-8') as handle:
        handle.write(NODE_EXPORT)
        export_script = Path(handle.name)
    try:
        completed = subprocess.run(
            ['node', str(export_script), str(repo_root), str(out_dir), str(HOST_ENTRY)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        export_script.unlink(missing_ok=True)
    if completed.returncode != 0:
        raise SystemExit('host 导出失败：\n' + (completed.stderr or completed.stdout))
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise SystemExit('host 导出没有输出')
    return json.loads(lines[-1])


def collapse(value: str) -> str:
    """折行、块标量的换行在两套解析器里可能差一个空格；比较前统一压成单空格。"""
    return ' '.join(str(value).split())


def check_with_pyyaml(traces: list[Path], summary: dict) -> None:
    """PyYAML 与 host 归一化结果交叉校验。

    host 的 YAML 子集解析器是这个插件自己实现的，手写夹具若只在它那里能读，
    与标准 YAML 语义已经分叉。这里用 PyYAML 回读同一份文件，逐项比较顶层摘要与
    每条事件的角色/动作/正文，确认两边读到的是同一份数据。
    """
    by_file = {item['source']: item for item in summary['details']}
    event_fields = ('content', 'output', 'reason', 'purpose', 'note')
    for trace in traces:
        doc = yaml.safe_load(trace.read_text(encoding='utf-8'))
        if not isinstance(doc, dict):
            raise SystemExit(f'{trace.name}: 顶层不是映射')
        events = doc.get('trace')
        if not isinstance(events, list):
            raise SystemExit(f'{trace.name}: 没有 trace 序列')
        expected = by_file.get(trace.name)
        if expected is None:
            raise SystemExit(f'{trace.name}: 没有对应的 detail 输出')
        if len(events) != expected['events']:
            raise SystemExit(
                f'{trace.name}: PyYAML 解析 {len(events)} 条事件，host 归一化 {expected["events"]} 条'
            )

        detail = json.loads((HERE / expected['file']).read_text(encoding='utf-8'))
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                raise SystemExit(f'{trace.name}: 第 {index} 条事件不是映射')
            host_event = detail['events'][index]
            for key, want in (('role', event.get('role')), ('action', event.get('action')),
                              ('step', event.get('step')), ('case', event.get('case'))):
                if want is None:
                    continue
                if collapse(host_event[key]) != collapse(want):
                    raise SystemExit(
                        f'{trace.name}: 第 {index} 条事件 {key} 分叉: PyYAML={want!r} host={host_event[key]!r}'
                    )
            for key in event_fields:
                want = event.get(key)
                if want is None:
                    continue
                if collapse(host_event[key]) != collapse(want):
                    raise SystemExit(
                        f'{trace.name}: 第 {index} 条事件 {key} 分叉: PyYAML={str(want)[:80]!r} host={str(host_event[key])[:80]!r}'
                    )

        # 顶层摘要逐项核对（host 归一化后的字段名与 YAML 键名不同）
        session = detail['session']
        top = (
            ('summary', session['summary']),
            ('status', session['status']),
            ('current_step', session['currentStep']),
            ('last_action', session['lastAction']),
        )
        for key, want in top:
            if collapse(want) != collapse(doc.get(key)):
                raise SystemExit(
                    f'{trace.name}: 顶层 {key} 分叉: PyYAML={str(doc.get(key))[:80]!r} host={str(want)[:80]!r}'
                )

        # evidence.files 指向的文件必须真实存在（host 的 detail 会断言 bytes 非 null）
        for event in events:
            evidence = event.get('evidence') if isinstance(event, dict) else None
            if not isinstance(evidence, dict):
                continue
            for rel in evidence.get('files') or []:
                # trace 里的 evidence.files 是运行时路径 `traces/evidence/…`；夹具源在
                # `fixtures/trace-samples/evidence/…`，按同一个相对结构对齐。
                parts = Path(rel).parts
                path = TRACES.joinpath(*parts[1:]) if parts[:1] == ('traces',) else HERE / rel
                if not path.is_file():
                    raise SystemExit(f'{trace.name}: 证据文件不存在: {rel}')
    session_ids = {item['id'] for item in summary['sessions']}
    yaml_ids = {yaml.safe_load(trace.read_text(encoding='utf-8'))['session_id'] for trace in traces}
    if session_ids != yaml_ids:
        raise SystemExit(f'session_id 不一致: fixtures={sorted(session_ids)} yaml={sorted(yaml_ids)}')


def main() -> int:
    traces = ensure_traces()
    for stale in HERE.glob('detail-*.json'):
        stale.unlink()
    (HERE / 'list-sample.json').unlink(missing_ok=True)

    with tempfile.TemporaryDirectory(prefix='sleuth-canvas-fixtures-') as tmp:
        repo_root = Path(tmp) / 'repo'
        repo_root.mkdir()
        copy_repo(repo_root)
        summary = run_host_export(repo_root, HERE)

    check_with_pyyaml(traces, summary)

    print('生成完成：')
    for item in summary['details']:
        size = (HERE / item['file']).stat().st_size
        print(f"  {item['file']}  events={item['events']}  bytes={size}")
    print(f"  {summary['list']}  sessions={len(summary['sessions'])}")
    print(f"  {summary['sample']}  ← 事件数最多的一份（页面/冒烟测试用）")
    return 0


if __name__ == '__main__':
    sys.exit(main())
