"""Read-only Linux CPUFreq audit. All frequencies in the JSON are kHz."""
import argparse
import json
import math
import re
import sys
import time
from pathlib import Path


def read(path):
    try:
        return path.read_text().strip() or None
    except (OSError, UnicodeError):
        return None


def positive(value):
    return int(value) if value and value.isascii() and value.isdigit() and int(value) > 0 else None


def cpus(text):
    result = set()
    for part in re.split(r'[,\s]+', text or ''):
        if not re.fullmatch(r'\d+(?:-\d+)?', part):
            return set()
        bounds = [int(number) for number in part.split('-')]
        result.update(range(bounds[0], bounds[-1] + 1))
    return result


def observation(peak, limit):
    if peak is None or limit is None:
        return 'UNKNOWN'
    return 'REACHED_IN_SAMPLES' if peak >= limit else 'NOT_SEEN_IN_SAMPLES'


def audit(root, samples, interval):
    online = cpus(read(root / 'online'))
    paths = sorted((root / 'cpufreq').glob('policy[0-9]*'))
    if not paths:
        paths = sorted({path.resolve() for path in root.glob('cpu[0-9]*/cpufreq')})
    policies = []
    covered = set()
    governors = set()
    for path in paths:
        members = cpus(read(path / 'affected_cpus') or read(path / 'related_cpus'))
        if online and members and not members & online:
            continue
        governor = read(path / 'scaling_governor')
        if members & online and governor:
            governors.add(governor)
            covered.update(members & online)
        policies.append((path, {'path': str(path), 'cpus': sorted(members), 'governor': governor,
            'driver': read(path / 'scaling_driver'), 'epp': read(path / 'energy_performance_preference'),
            'policy_max_khz': positive(read(path / 'scaling_max_freq')),
            'hardware_max_khz': positive(read(path / 'cpuinfo_max_freq')),
            'scaling_cur_khz_snapshot': positive(read(path / 'scaling_cur_freq')),
            'hardware_samples': 0, 'hardware_peak_khz': None, 'hardware_min_khz': None,
            'policy_max_hits': None, 'hardware_max_hits': None}))
    for index in range(samples):
        for path, row in policies:
            current = positive(read(path / 'cpuinfo_cur_freq'))
            if current is not None:
                row['hardware_samples'] += 1
                row['hardware_peak_khz'] = max(row['hardware_peak_khz'] or 0, current)
                row['hardware_min_khz'] = min(row['hardware_min_khz'] or current, current)
                for label in ('policy', 'hardware'):
                    limit = row[label + '_max_khz']
                    if limit is not None:
                        field = label + '_max_hits'
                        row[field] = (row[field] or 0) + int(current >= limit)
        if policies and index + 1 < samples:
            time.sleep(interval)
    for path, row in policies:
        for label in ('policy', 'hardware'):
            row[label + '_max_observation'] = observation(row['hardware_peak_khz'], row[label + '_max_khz'])
    mode = 'UNKNOWN'
    if online and online == covered and all(row['governor'] and row['cpus'] for _, row in policies):
        if governors == {'performance'}:
            mode = 'ALL_PERFORMANCE'
        else:
            mode = 'MIXED' if 'performance' in governors else 'NONE_PERFORMANCE'
    return {'online_governor': mode, 'online_cpus': sorted(online), 'unverified_cpus': sorted(online - covered),
            'samples_requested_per_policy': samples, 'interval_sec': interval,
            'policies': [row for _, row in policies]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=10)
    parser.add_argument('--interval', type=float, default=1.0, help='seconds between observations')
    args = parser.parse_args()
    if args.samples < 1 or not math.isfinite(args.interval) or args.interval <= 0:
        parser.error('samples and interval must be positive and finite')
    if not sys.platform.startswith('linux'):
        parser.exit(2, 'Run this check on the target Linux host.\n')
    print(json.dumps(audit(Path('/sys/devices/system/cpu'), args.samples, args.interval), indent=2))


if __name__ == '__main__':
    main()
