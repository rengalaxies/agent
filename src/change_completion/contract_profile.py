"""Bounded JSON-contract / declarative Python-consumer / SQL profile.

The Python consumer is a canonical trusted template, never arbitrary repository
code. This is one replaceable execution profile, not the product's stack limit.
An operator pins the independent suite digest outside candidate-controlled files.
"""
import ast
from hashlib import sha256
import json
from pathlib import Path
import re
import time

from .adapters import read_repository_file
from .comparison import compare_tables
from .executor import execute_select
from .verification import TableRecord, load_json

PROFILE = "contract-python-sql/1"
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]{0,63}\Z")
MAX_INTEGER = 2**63 - 1
TEMPLATE = '''"""Generated bounded consumer: integer minor units only."""
MAPPING = {mapping}

def consume(event):
    return {{target: event[source] * factor
            for target, (source, factor) in MAPPING.items()}}
'''


def render_consumer(mapping):
    _mapping(mapping)
    return TEMPLATE.format(mapping=repr(dict(sorted(mapping.items()))))


def _mapping(mapping):
    if type(mapping) is not dict or not 1 <= len(mapping) <= 32:
        raise ValueError("unsupported_mapping")
    for target, rule in mapping.items():
        if (type(target) is not str or not IDENTIFIER.fullmatch(target)
                or type(rule) not in (list, tuple) or len(rule) != 2
                or type(rule[0]) is not str or not IDENTIFIER.fullmatch(rule[0])
                or type(rule[1]) is not int or not 0 < rule[1] <= 1_000_000):
            raise ValueError("unsupported_mapping")


def parse_consumer(source):
    if type(source) is not str or len(source.encode()) > 16_384:
        raise ValueError("consumer_size_limit")
    try:
        tree = ast.parse(source)
        mapping = ast.literal_eval(tree.body[1].value)
        _mapping(mapping)
        if source != render_consumer(mapping):
            raise ValueError("noncanonical_python_consumer")
        return mapping
    except (SyntaxError, IndexError, AttributeError, TypeError, RecursionError) as exc:
        raise ValueError("unsupported_python_consumer") from exc


def _read(root, path):
    # Existing dirfd/O_NOFOLLOW reader rejects traversal and symlinks.
    data = read_repository_file(root, path)
    if isinstance(data, str):
        data = data.encode()
    if len(data) > 1_000_000:
        raise ValueError("artifact_limit")
    return data


def _manifest(root, raw=None):
    manifest = load_json(_read(root, "profile.json") if raw is None else raw)
    if set(manifest) != {"profile", "contract", "consumers"} or manifest["profile"] != PROFILE:
        raise ValueError("unsupported_profile")
    consumers = manifest["consumers"]
    if type(consumers) is not list or not 1 <= len(consumers) <= 16:
        raise ValueError("consumer_limit")
    ids = set()
    for item in consumers:
        if (type(item) is not dict or set(item) != {"id", "python", "sql"}
                or type(item["id"]) is not str or not IDENTIFIER.fullmatch(item["id"])
                or item["id"] in ids):
            raise ValueError("invalid_consumer")
        ids.add(item["id"])
    paths = ["profile.json", manifest["contract"]]
    for item in consumers:
        paths.extend([item["python"], item["sql"]])
    if (any(type(path) is not str or not path or len(path) > 256 for path in paths)
            or len(set(paths)) != len(paths)):
        raise ValueError("overlapping_or_invalid_artifact_paths")
    return manifest


def _contract(raw):
    contract = load_json(raw)
    if set(contract) != {"fields"} or type(contract["fields"]) is not dict or not 1 <= len(contract["fields"]) <= 32:
        raise ValueError("unsupported_contract")
    for field, declaration in contract["fields"].items():
        if (not IDENTIFIER.fullmatch(field) or type(declaration) is not dict
                or set(declaration) != {"type", "unit"} or declaration["type"] != "integer"
                or declaration["unit"] not in {"count", "rub", "kopeck", "day"}):
            raise ValueError("unsupported_contract_field")
    return contract


def _fixture(events, contract, mapping):
    if type(events) is not list or not 1 <= len(events) <= 200:
        raise ValueError("event_limit")
    fields = contract["fields"]
    if any(source not in fields for source, _ in mapping.values()):
        raise ValueError("missing_contract_field")
    rows = []
    for event in events:
        if type(event) is not dict or set(event) != set(fields):
            raise ValueError("event_contract_mismatch")
        if any(type(value) is not int or abs(value) > MAX_INTEGER for value in event.values()):
            raise ValueError("integer_required")
        row = {target: event[source] * factor for target, (source, factor) in mapping.items()}
        if any(abs(value) > MAX_INTEGER for value in row.values()):
            raise ValueError("integer_overflow")
        rows.append(row)
    return {"schemas": {"events": {key: "INTEGER" for key in mapping}}, "tables": {"events": rows}}


def check_profile(repository: Path, suite_bytes: bytes, approved_suite_sha256: str):
    """Capture real outputs and compare against separately approved expectations."""
    report = {"profile": PROFILE, "status": "STOP", "checks": [], "effects_authorized": False,
              "coverage_limits": ["declared_consumers_only", "canonical_integer_mapping_only",
                                  "bounded_sqlite_select", "no_production_cutover"]}
    try:
        if sha256(suite_bytes).hexdigest() != approved_suite_sha256:
            raise ValueError("unapproved_suite")
        suite = load_json(suite_bytes)
        if set(suite) != {"cases"} or type(suite["cases"]) is not list or not 2 <= len(suite["cases"]) <= 32:
            raise ValueError("independent_cases_required")
        manifest_bytes = _read(repository, "profile.json")
        manifest = _manifest(repository, manifest_bytes)
        if len(suite["cases"]) * len(manifest["consumers"]) > 64:
            raise ValueError("capture_budget_limit")
        contract_bytes = _read(repository, manifest["contract"])
        contract = _contract(contract_bytes)
        artifacts = {"profile.json": sha256(manifest_bytes).hexdigest(),
                     manifest["contract"]: sha256(contract_bytes).hexdigest()}
        deadline = time.monotonic() + 30
        consumers = {}
        for item in manifest["consumers"]:
            python = _read(repository, item["python"])
            sql = _read(repository, item["sql"])
            consumers[item["id"]] = (parse_consumer(python.decode()), sql.decode())
            artifacts.update({item["python"]: sha256(python).hexdigest(), item["sql"]: sha256(sql).hexdigest()})
        case_ids = set()
        for case in suite["cases"]:
            if (type(case) is not dict or set(case) != {"id", "input", "expected"}
                    or type(case["id"]) is not str or not case["id"] or case["id"] in case_ids
                    or type(case["expected"]) is not dict or set(case["expected"]) != set(consumers)):
                raise ValueError("incomplete_or_duplicate_case")
            case_ids.add(case["id"])
            for consumer, (mapping, sql) in consumers.items():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("profile_wall_time_limit")
                observed = execute_select(sql, _fixture(case["input"], contract, mapping),
                                          timeout_seconds=min(2, remaining))
                if observed["status"] != "executed":
                    raise ValueError("sql_execution_" + observed["status"])
                expected = TableRecord.model_validate(case["expected"][consumer]).table()
                actual = TableRecord.model_validate(observed["actual"]).table()
                compared = compare_tables(expected, actual)
                if time.monotonic() > deadline:
                    raise ValueError("profile_wall_time_limit")
                report["checks"].append({"case": case["id"], "consumer": consumer,
                                         "status": compared.status, "reason_codes": compared.reason_codes})
        # Re-read artifacts to avoid reporting success for a changed snapshot.
        if any(sha256(_read(repository, path)).hexdigest() != digest for path, digest in artifacts.items()):
            raise ValueError("snapshot_changed")
        report["artifacts"] = artifacts
        report["suite_sha256"] = approved_suite_sha256
        statuses = {check["status"] for check in report["checks"]}
        report["status"] = "STOP" if "STOP" in statuses else "FAIL" if "FAIL" in statuses else "PASS"
    except (ValueError, TypeError, KeyError, OSError, UnicodeError, RecursionError) as exc:
        report["reason_codes"] = [str(exc)[:160]]
    return report


def generate_candidate(source: Path, output: Path, changes: dict):
    """Copy declared files and replace explicitly named consumer mappings only."""
    manifest = _manifest(source)
    if type(changes) is not dict or not changes or set(changes) - {c["id"] for c in manifest["consumers"]}:
        raise ValueError("unknown_consumer_change")
    files = {"profile.json": _read(source, "profile.json"), manifest["contract"]: _read(source, manifest["contract"])}
    for consumer in manifest["consumers"]:
        files[consumer["python"]] = (render_consumer(changes[consumer["id"]]).encode()
                                      if consumer["id"] in changes else _read(source, consumer["python"]))
        files[consumer["sql"]] = _read(source, consumer["sql"])
    if len(files) != 2 + 2 * len(manifest["consumers"]):
        raise ValueError("overlapping_artifact_paths")
    # Exclusive fresh directory: no source writes, symlink traversal or overwrites.
    if output.resolve().is_relative_to(source.resolve()):
        raise ValueError("output_must_differ")
    if any(parent.is_symlink() for parent in output.absolute().parents):
        raise ValueError("symlink_output_parent")
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        for path, data in files.items():
            relative = Path(path)
            if relative.is_absolute() or any(part in {"..", ".git"} for part in relative.parts):
                raise ValueError("unsafe_artifact_path")
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(data)
    except Exception:
        # Keep partial artifacts inspectable; never silently remove user paths.
        raise
    return {"status": "PREPARED", "files": sorted(files), "effects_authorized": False}
