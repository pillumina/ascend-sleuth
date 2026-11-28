"""Resolve the Ascend platform from collected product names, independent of topology."""
import re
from pathlib import Path

from .evidence import read_manifest


DMI = 'dmi_product_name.txt'
NPU = 'npu_smi_product.txt'
PRODUCT_FIELD = re.compile(r'\s*(?:Product\s+(?:Type|Name|Model)|产品(?:类型|名称|型号))\s*[:：]\s*(.*?)\s*', re.I)
PLATFORM = re.compile(
    r'^(?:(?:HUAWEI|华为) *)?(?:ATLAS *|A(?=200|300|800|900)|(?:ASCEND|昇腾) +(?=A[0-9]))'
    r'(?:[0-9]+[ITV]? *(?:(?:DK|RCK|POD|SUPERPOD) *)?)?(A[0-9]+)(?![A-Z0-9])')
GENERATION_TOKEN = re.compile(r'(?<![A-Z0-9])A[0-9]{1,2}(?![A-Z0-9])')
# openUBMC's product classification lists A800I 2UP as Atlas 800I A2 2UP.
# Huawei Cloud's A5 solution product guide lists Atlas 950 SuperPoD.
ALIASES = {'A800I 2UP': 'A2', 'ATLAS 950 SUPERPOD': 'A5'}


def _generations(value, npu):
    value = re.sub(r'[\s_-]+', ' ', value.upper()).strip()
    if value in ALIASES:
        return {ALIASES[value]}
    match = PLATFORM.match(value)
    if match:
        return {match[1]} | set(GENERATION_TOKEN.findall(value))
    # A short generation value in the vendor's product field is scoped to an
    # Ascend device. An arbitrary DMI model (for example an OEM's "A3") is not.
    if npu and GENERATION_TOKEN.fullmatch(value):
        return {value}
    return set()


def detect_product(snapshot):
    """Accept analyzer snapshot keys or bare sidecar filenames (also for live callers)."""
    manifest, state = read_manifest(snapshot)
    evidence = []
    candidates = set()
    for name in (DMI, NPU):
        path = 'hostbound/' + name
        raw = snapshot.get(path, snapshot.get(name, ''))
        claims = [row for row in manifest.get('entries', []) if row.get('raw_path') in (path, name)]
        if (not isinstance(raw, str) or state == 'PARSE_FAILED' or
                any(row.get('status') != 'COLLECTED' or row.get('returncode') not in (None, 0) for row in claims)):
            continue
        lines = raw.strip().splitlines()
        if name == NPU:
            values = []
            for line in lines:
                match = PRODUCT_FIELD.fullmatch(line)
                if match:
                    values.append(match[1])
        else:
            values = lines if len(lines) == 1 else []
        for value in values:
            found = _generations(value, name == NPU)
            evidence.append({'source': path, 'value': value, 'generations': sorted(found)})
            candidates.update(found)
    status = 'unknown'
    generation = 'unknown'
    if len(candidates) > 1:
        status = 'conflict'
    elif candidates and candidates <= {'A2', 'A3', 'A5'}:
        status = 'identified'
        generation, = candidates
    return {'generation': generation, 'status': status, 'evidence': evidence}


def read_product(folder):
    """Read the same optional evidence directly from an unpacked hostbound directory."""
    snapshot = {}
    folder = Path(folder)
    for name in (DMI, NPU, 'collection_manifest.json'):
        try:
            snapshot[name] = (folder / name).read_text(encoding='utf-8-sig', errors='replace')
        except FileNotFoundError:
            pass
        except OSError:
            snapshot[name] = ''
    return detect_product(snapshot)
