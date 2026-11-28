"""Check Ascend compatibility against the bundled, versioned reference."""

import json
from pathlib import Path
import re

KNOWLEDGE = Path(__file__).with_name("ascend-compatibility.json")
SCOPE_FIELDS = ("hardware", "hardware_variant", "model", "cann_edition", "architecture", "install_method")
STATUSES = {
    "confirmed": "已确认配套",
    "candidate": "仅有候选",
    "incompatible": "明确不配套",
    "unknown": "无法确认",
    "not_applicable": "不适用",
}
ARCHITECTURES = {"arm64": "aarch64", "amd64": "x86_64", "x64": "x86_64"}
EDITIONS = {"社区版": "community", "商用版": "commercial"}


def load():
    data = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    if data["schema_version"] != 1:
        raise ValueError("Unsupported knowledge schema.")
    return data


def norm(value):
    return value.strip().casefold()


def version_text(value):
    return re.sub(r"^v(?=\d+\.)", "", norm(value))


def matches(rule_value, actual, key):
    actual = version_text(actual)
    if isinstance(rule_value, str):
        expected = version_text(rule_value)
        if key == "python" and re.fullmatch(r"\d+\.\d+", expected):
            return re.fullmatch(re.escape(expected) + r"(?:\.\d+)?", actual) is not None
        return actual == expected
    if "branch" in rule_value:
        branch = re.escape(version_text(rule_value["branch"])).replace("x", r"\d+")
        return re.fullmatch(branch, actual) is not None
    if not re.fullmatch(r"\d+(?:\.\d+){1,2}", actual):
        return False
    to_pair = lambda value: tuple(map(int, value.split(".")[:2]))
    return to_pair(rule_value["gte"]) <= to_pair(actual) < to_pair(rule_value["lt"])


def read_aliases(data, field):
    if field == "hardware":
        aliases = data["hardware_aliases"]
        return {norm(name): value for name, value in {**aliases, **{item: item for item in aliases.values()}}.items()}
    return {
        norm(alias): key
        for key, aliases in data["component_aliases"].items()
        for alias in [key, *aliases]
    }


def clean_input(payload, data):
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object.")
    unknown = set(payload) - {*SCOPE_FIELDS, "versions", "checks", "workload", "mode"}
    if unknown:
        raise ValueError("Unknown input fields: " + ", ".join(sorted(unknown)))
    mode = payload.get("mode", "compatibility")
    if mode not in ("compatibility", "download"):
        raise ValueError("mode must be compatibility or download.")
    aliases = read_aliases(data, "components")
    known = {key for record in data["rules"] for key in record["versions"]}

    def key_for(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Component names must be non-empty strings.")
        key = norm(value)
        if key in {"torchnpu", "triton"}:
            raise ValueError(f"Ambiguous component {value}; use torchnpu_release or torch_npu, and triton_ascend for the Ascend plugin.")
        return aliases.get(key, key) if key not in known else key

    raw_versions = payload.get("versions")
    if not isinstance(raw_versions, dict):
        raise ValueError("versions must be a JSON object.")
    versions = {}
    for name, value in raw_versions.items():
        key = key_for(name)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name}: provide a non-empty version string or null.")
        if key in versions and version_text(versions[key]) != version_text(value):
            raise ValueError(f"Conflicting versions supplied for {key}.")
        versions[key] = value.strip()

    scope = {}
    families = read_aliases(data, "hardware")
    for key in SCOPE_FIELDS:
        value = payload.get(key)
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} must be a non-empty string.")
            value = value.strip()
            if key == "hardware":
                value = families.get(norm(value), value)
            if key == "cann_edition":
                value = EDITIONS.get(norm(value), norm(value))
                if value not in EDITIONS.values():
                    raise ValueError("cann_edition must be community or commercial.")
            if key == "architecture":
                value = ARCHITECTURES.get(norm(value), norm(value))
            scope[key] = value

    workload = payload.get("workload")
    if workload is not None:
        workload = key_for(workload)
        if mode == "download":
            raise ValueError("workload applies only in compatibility mode.")

    groups = payload.get("checks")
    if groups is not None:
        if not isinstance(groups, list) or not groups or any(not isinstance(group, list) or not group for group in groups):
            raise ValueError("checks must contain one or more nonempty arrays of component names.")
        groups = [sorted({key_for(key) for key in group}) for group in groups]
    elif not workload:
        groups = [sorted({key_for(key) for key in raw_versions})]
    if not workload and not any(groups):
        raise ValueError("Specify at least one component or workload.")
    return mode, scope, versions, groups or [], workload


def scope_match(required, actual):
    missing = []
    for key, value in required.items():
        if key not in actual:
            missing.append(key)
            continue
        expected = norm(value)
        if key == "architecture":
            expected = ARCHITECTURES.get(expected, expected)
        if expected != norm(actual[key]):
            return False, []
    return True, sorted(missing)


def matching_versions(required, actual, keys):
    return all(key in required and key in actual and matches(required[key], actual[key], key) for key in keys)


def describe(record):
    keys = ("id", "kind", "label", "scope", "published", "versions", "anchors", "channel",
            "all_filter", "cann_not_applicable", "edition_of_download")
    return {key: record[key] for key in keys if key in record}


def narrower(a, b, keys):
    """Return whether a is strictly more specific within the compared scope."""
    if not set(b["scope"].items()) <= set(a["scope"].items()):
        return False
    strict = a["scope"] != b["scope"]
    for key in keys:
        left, right = a["versions"][key], b["versions"][key]
        if left == right:
            continue
        if isinstance(left, str) and isinstance(right, dict) and matches(right, left, key):
            strict = True
        elif isinstance(left, str) and isinstance(right, str) and version_text(left) == version_text(right):
            continue
        else:
            return False
    return strict


def query_supports(record, keys, versions, scope):
    if record["kind"] == "hardware_candidates":
        requested_hardware = scope.get("hardware")
        return (len(keys) == 1 and bool(requested_hardware) and record["returned"]
                and requested_hardware in record["hardware"]
                and (not record["hardware_variant"] or norm(record["hardware_variant"]) == norm(scope.get("hardware_variant", "")))
                and matching_versions(record["versions"], versions, keys))
    if "hardware" in scope and "hardware" not in record["scope"]:
        return False
    applies, missing = scope_match(record["scope"], scope)
    if not applies or missing:
        return False
    if record["kind"] == "release_reference":
        return matching_versions(record["versions"], versions, keys)
    if not record["returned"] or not set(keys) & record["anchors"].keys():
        return False
    if not matching_versions(record["anchors"], versions, record["anchors"]):
        return False
    for key in keys:
        if key in record["anchors"]:
            continue
        options = record["choices"].get(key, [])
        if not any(
            matches(option["version"], versions[key], key)
            and (not option.get("hardware_variant") or norm(option["hardware_variant"]) == norm(scope.get("hardware_variant", "")))
            for option in options
        ):
            return False
    return True


def result(keys, status, reason, rows=(), missing=()):
    return {"components": sorted(keys), "status": status, "label": STATUSES[status], "reason": reason,
            "evidence": [describe(row) for row in list(rows)[:4]], "missing": sorted(missing)}


def compare(data, keys, versions, scope, mode, workload_rows=None):
    keys = set(keys)
    missing = keys - versions.keys()
    available = data["downloads"] if mode == "download" else data["rules"]
    profile_ids = None if workload_rows is None else {row["id"] for row in workload_rows}
    supports, potential, applicable_positive = [], [], []
    for row in available:
        if row["kind"] == "explicit_conflict":
            continue
        if row.get("anchor") and not matching_versions(row["versions"], versions, [row["anchor"]]):
            continue
        if mode == "compatibility" and "hdk" in keys and "hardware" in scope and "hardware" not in row["scope"]:
            continue
        if row["kind"] == "legacy_download" and scope.get("cann_edition", "community") != "community":
            continue
        if len(keys) == 1 and not row["scope"] and workload_rows is None:
            continue
        applicable, missing_scope = scope_match(row["scope"], scope)
        if applicable:
            if not missing_scope:
                applicable_positive.append(row)
            if (profile_ids is None or row["id"] in profile_ids) and matching_versions(row["versions"], versions, keys):
                if missing_scope:
                    potential.append((row, missing_scope))
                else:
                    supports.append(row)
    if mode == "compatibility":
        blockers = []
        for row in available:
            if row["kind"] != "explicit_conflict" or not row["versions"].keys() <= keys:
                continue
            if len(keys) > 1 and len(row["versions"]) == 1 and "hardware" not in scope:
                continue
            applicable, missing_scope = scope_match(row["scope"], scope)
            if not applicable or not matching_versions(row["versions"], versions, row["versions"]):
                continue
            if missing_scope:
                potential.append((row, missing_scope))
            else:
                blockers.append(row)
        for negative in blockers:
            overlap = negative["versions"].keys()
            counter = [row for row in applicable_positive if matching_versions(row["versions"], versions, overlap)
                       and not narrower(negative, row, overlap)]
            if counter and not any(narrower(row, negative, overlap) for row in counter):
                return result(keys, "unknown", "conflicting_rules", [negative, *counter], missing)
            if not counter:
                return result(keys, "incompatible", "explicit_conflict", [negative], missing)
    if missing:
        return result(keys, "unknown", "missing_versions", missing=missing)
    if supports:
        potentially_blocked = [(row, fields) for row, fields in potential if row["kind"] == "explicit_conflict"]
        if potentially_blocked:
            row, fields = min(potentially_blocked, key=lambda item: (len(item[1]), item[1]))
            return result(keys, "unknown", "missing_scope", [row], fields)
        return result(keys, "confirmed", "matched_rule", supports)
    if potential:
        row, fields = min(potential, key=lambda item: (len(item[1]), item[1]))
        return result(keys, "unknown", "missing_scope", [row], fields)
    if mode == "compatibility" and workload_rows is None:
        for row in data["rules"]:
            if row["kind"] != "release" or not (keys & set(row["not_applicable"])):
                continue
            applicable, missing_scope = scope_match(row["scope"], scope)
            relevant = keys - set(row["not_applicable"])
            if applicable and not missing_scope and matching_versions(row["versions"], versions, relevant | {"cann"}):
                return result(keys, "not_applicable", "release_marks_na", [row])
        candidate_rows = [
            row for row in data["candidates"]
            if query_supports(row, keys, versions, scope)
        ]
        if candidate_rows:
            scoped = [{**row, "versions": {key: versions[key] for key in sorted(keys)}} for row in candidate_rows if row["kind"] == "query"]
            return result(keys, "candidate", "candidate_only", scoped or candidate_rows)
    return result(keys, "unknown", "no_applicable_rule")


def compare_workload(data, workload, versions, scope):
    if workload not in versions:
        return result([workload], "unknown", "missing_workload_version", missing=[workload])
    profiles = [row for row in data["rules"] if row.get("workload") == workload
                and matches(row["versions"][workload], versions[workload], workload)
                and scope_match(row["scope"], scope)[0]]
    if not profiles:
        return result([workload], "unknown", "no_workload_profile")
    outcomes = []
    for profile in profiles:
        expected = profile["versions"]
        outcome = compare(data, expected, versions, scope, "compatibility", [profile])
        if outcome["status"] == "unknown":
            if not outcome["evidence"]:
                outcome["evidence"] = [describe(profile)]
            mismatches = {key: {"observed": versions[key], "expected": expected[key]}
                          for key in expected.keys() & versions.keys()
                          if not matches(expected[key], versions[key], key)}
            if mismatches:
                outcome["differences"] = dict(sorted(mismatches.items()))
                if outcome["reason"] != "conflicting_rules":
                    outcome["reason"] = "profile_version_differs"
                    outcome["evidence"] = [describe(profile)]
        outcomes.append(outcome)
    for state in ("confirmed", "incompatible"):
        for outcome in outcomes:
            if outcome["status"] == state:
                return outcome
    applicable_outcomes = [
        item for item, row in zip(outcomes, profiles)
        if matching_versions(row["versions"], versions, row["versions"].keys() & versions.keys())
    ]
    return min(applicable_outcomes or outcomes, key=lambda item: (not bool(item["missing"]), len(item["missing"])))


def evaluate(payload, data, *, require_hardware_for_hdk=False):
    mode, scope, versions, groups, workload = clean_input(payload, data)
    results = []
    for keys in groups:
        if require_hardware_for_hdk and "hdk" in keys and "hardware" not in scope:
            results.append(result(keys, "unknown", "missing_scope",
                                  missing={"hardware"} | (set(keys) - versions.keys())))
        else:
            results.append(compare(data, keys, versions, scope, mode))
    if workload:
        results.insert(0, compare_workload(data, workload, versions, scope))
    statuses = {row["status"] for row in results}
    status = next(item for item in ("incompatible", "unknown", "candidate", "not_applicable", "confirmed") if item in statuses)
    coverage = data["coverage"]["queries_by_hardware"].get(scope.get("hardware", "unspecified"), {})
    return {
        "status": status, "label": STATUSES[status], "mode": mode,
        "snapshot": data["snapshot"], "revision": data["revision"],
        "scope": scope, "workload": workload, "checks": results, "coverage": coverage,
    }


def lookup(data, target):
    target = norm(target)
    search_keys = ("product", "package", "topic", "conditions")
    records = [row for row in data["reference"]
               if target in norm(" ".join(str(row.get(key, "")) for key in search_keys))]
    return {"snapshot": data["snapshot"], "matches": len(records), "reference": records[:40]}
