"""Input/parameter-aware cache and machine-readable workflow status."""
import hashlib
import json
import os
from pathlib import Path
import time


def write_json(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def cache_key(root, mw, skill_dir, parameters):
    digest = hashlib.sha256()
    digest.update(json.dumps(parameters, sort_keys=True).encode())
    digest.update(os.path.realpath(root).encode('utf-8'))
    mw = os.path.realpath(mw)
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in ('cluster_analysis_output', '__pycache__', '.git')
                         and os.path.realpath(os.path.join(directory, d)) != mw
                         and not os.path.islink(os.path.join(directory, d)))
        for name in sorted(files):
            if name.endswith(('-wal', '-shm')):
                continue
            p = Path(directory, name)
            s = p.stat()
            digest.update(str(p.relative_to(root)).encode('utf-8'))
            digest.update(f'{s.st_size}:{s.st_mtime_ns}'.encode())
            # Large traces use metadata; small metadata/config/data are content checked.
            if s.st_size <= 1024 * 1024:
                digest.update(p.read_bytes())
    for p in sorted(Path(skill_dir).rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts and 'tests' not in p.parts and p.suffix in ('.py', '.md', '.html', '.js', '.css'):
            digest.update(str(p.relative_to(skill_dir)).encode('utf-8'))
            digest.update(p.read_bytes())
    return digest.hexdigest()


class WorkflowState:
    def __init__(self, mw, root):
        self.mw = Path(mw)
        self.data = {'status': 'running', 'input': root, 'stages': {}, 'warnings': [], 'errors': []}
        self.key = None
        self.started = time.monotonic()

    def record(self, stage, status, detail=''):
        self.data['stages'][stage] = {'status': status, 'detail': detail[-3000:]}

    def finish(self, rc):
        self.data.update(status='complete' if rc == 0 else 'partial' if rc == 2 else 'failed',
                         returncode=rc, elapsed_seconds=round(time.monotonic() - self.started, 3))
        write_json(self.mw / 'workflow_status.json', self.data)
        # Failed/partial runs never validate a cache.
        write_json(self.mw / 'workflow_cache.json', {'key': self.key, 'status': self.data['status']})
