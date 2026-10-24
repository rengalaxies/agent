"""Structured access logs as runtime bases. Observed traffic never proves absence.

One adapter, ``access-log-jsonl-1``: closed segments of server-side JSON access
logs, each with a coverage sidecar written on rotation. Log content is untrusted:
raw lines, request paths and unknown aliases never reach the output.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import stat

from pydantic import Field, model_validator

from .contracts import GraphError, Strict, digest
from .output_contracts import (
    SCHEMA_ID, SCHEMA_VERSION, Freshness, GraphRelationship, OperationEntity, RuntimeAggregates,
    RuntimeEvidence, ServiceEntity, SourceFreshness, entity_id, normalize_route)

ADAPTER = "access-log-jsonl-1"
SCHEMA = "agent-runtime-observations-1"
SEGMENT_SCHEMA = "access-log-segment-1"
EVIDENCE_CONTRACT = f"{SCHEMA_ID}-{SCHEMA_VERSION}"

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
ROUTE = re.compile(r"^/[A-Za-z0-9._~{}:/-]{0,199}$")
NAME = r"^[a-zA-Z0-9_.-]{1,80}$"


class IdentityAlias(Strict):
    alias: str = Field(min_length=1, max_length=200)
    service: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,64}$")


class SourceLimits(Strict):
    max_segments: int = Field(default=1000, ge=1, le=100_000)
    max_segment_bytes: int = Field(default=64 * 2**20, ge=1, le=2**31)
    max_line_bytes: int = Field(default=16384, ge=64, le=2**20)
    max_records: int = Field(default=1_000_000, ge=1, le=50_000_000)
    max_window_seconds: int = Field(default=7 * 86400, ge=1, le=90 * 86400)


class AccessLogSource(Strict):
    """Operator configuration. Nothing here comes from log content."""
    id: str = Field(pattern=NAME)
    installation_id: str = Field(pattern=NAME)
    environment: str = Field(pattern=NAME)
    root: str
    identities: list[IdentityAlias] = Field(min_length=1)
    # Services whose server access logs this source promises to carry.
    instrumented_services: list[str] = Field(min_length=1)
    limits: SourceLimits = Field(default_factory=SourceLimits)

    @model_validator(mode="after")
    def consistent(self):
        aliases = [a.alias.strip().lower() for a in self.identities]
        if len(set(aliases)) != len(aliases):
            raise ValueError("duplicate_identity_alias")
        if not set(self.instrumented_services) <= {a.service for a in self.identities}:
            raise ValueError("unmapped_instrumented_service")
        return self


class FreshnessPolicy(Strict):
    access_log_max_age_seconds: int = Field(default=86400, ge=1, le=90 * 86400)


def service_entity(installation, environment, service):
    return ServiceEntity(installation_id=installation, environment=environment, service=service)


def operation_entity(installation, environment, service, method, route):
    # entity_id keeps discovery.operation_id's formula: runtime and code meet on one node.
    return OperationEntity(installation_id=installation, environment=environment, service=service,
                           method=method.upper(), route=normalize_route(route))


def relationship_id(kind, from_id, to_id):
    return digest([kind, from_id, to_id])


# assess() status -> (FreshnessReason, UnknownCode) of output_contracts. None where
# the 2.0 contract has no code yet; batch-3.md lists the missing ones.
ASSESSMENT_CODES = {
    "OBSERVED": (None, None),
    "NO_TRAFFIC_OBSERVED": ("no_traffic_in_window", "runtime_not_observed"),
    "SAMPLED_NOT_OBSERVED": ("sampled_source", "runtime_not_observed"),
    "WINDOW_GAP": ("window_gap", "runtime_window_gap"),
    "SOURCE_UNAVAILABLE": ("source_unavailable", "runtime_not_observed"),
    "CALLEE_NOT_INSTRUMENTED": (None, "runtime_not_observed"),
    "ROUTE_NOT_RECORDED": (None, None),
    "OTHER_ROUTE_OBSERVED": (None, None),
}


def iso(value: datetime):
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_time(value):
    """Aware ISO 8601 only. A naive timestamp is ambiguous, not UTC."""
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00") if value.endswith("Z") else value)
    except ValueError:
        raise ValueError("invalid_timestamp") from None
    if parsed.tzinfo is None:
        raise ValueError("timestamp_without_offset")
    return parsed.astimezone(timezone.utc)


def window_bounds(start, end, limits):
    try:
        start = parse_time(start) if isinstance(start, str) else start
        end = parse_time(end) if isinstance(end, str) else end
    except ValueError:
        raise GraphError("invalid_window") from None
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        raise GraphError("invalid_window")
    if start.tzinfo is None or end.tzinfo is None:
        raise GraphError("window_without_offset")
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    if end <= start or (end - start).total_seconds() > limits.max_window_seconds:
        raise GraphError("invalid_window")
    return start, end


def subtract(intervals, removed):
    result = []
    for start, end in intervals:
        pieces = [(start, end)]
        for r_start, r_end in removed:
            pieces = [p for s, e in pieces
                      for p in ((s, min(e, r_start)), (max(s, r_end), e)) if p[0] < p[1]]
        result.extend(pieces)
    return result


def union(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def percentile(values, q):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def regular_file(path: Path):
    # No O_NOFOLLOW on Windows: refuse links by lstat. The root is operator-owned.
    mode = path.lstat().st_mode
    return stat.S_ISREG(mode) and not stat.S_ISLNK(mode)


def read_access_logs(source: AccessLogSource, start, end, *, checked_at=None,
                     freshness: FreshnessPolicy | None = None):
    limits = source.limits
    start, end = window_bounds(start, end, limits)
    checked_at = checked_at or datetime.now(timezone.utc)
    freshness = freshness or FreshnessPolicy()
    aliases = {a.alias.strip().lower(): a.service for a in source.identities}
    rejected, notes = Counter(), Counter()
    segments, covered, read_spans, gaps = [], {}, {}, []
    pairs, unattributed = {}, Counter()

    root = Path(source.root)
    if not root.is_absolute():
        raise GraphError("invalid_runtime_root")
    try:
        available = not root.is_symlink() and root.is_dir()
        names = sorted(p.name for p in root.iterdir()) if available else []
    except OSError:
        available, names = False, []
    if not available:
        return _result(source, start, end, checked_at, freshness, status="UNAVAILABLE",
                       reasons=["source_unavailable"], segments=[], covered={},
                       gaps=[dict(code="source_unavailable", service=s, start=iso(start), end=iso(end))
                             for s in sorted(source.instrumented_services)],
                       read_spans={}, rejected=rejected, notes=notes, pairs={}, unattributed=unattributed)

    sidecars = [n for n in names if n.endswith(".coverage.json")]
    data_files = {n for n in names if n.endswith(".jsonl")}
    described = set()
    records_read = 0
    for sidecar in sidecars:
        if len(segments) >= limits.max_segments:
            notes["segment_count_limit"] += 1
            break
        segment = _segment(root, sidecar, source, aliases, start, end, notes)
        if segment is None:
            continue
        described.add(segment["file"])
        if segment.get("skip"):
            continue
        emitter, s_start, s_end, rate = segment["service"], segment["start"], segment["end"], segment["sample_rate"]
        clipped = (max(s_start, start), min(s_end, end))
        try:
            raw = _read_segment(root / segment["file"], segment["sha256"], limits)
        except GraphError as exc:
            notes[exc.code] += 1
            gaps.append((emitter, clipped, exc.code))
            continue
        corrupt = False
        for line in raw.split(b"\n"):
            if not line.strip():
                continue
            if records_read >= limits.max_records:
                notes["record_limit"] += 1
                corrupt = True
                break
            records_read += 1
            reason = _record(line, segment, source, aliases, start, end, pairs, unattributed)
            if reason == "outside_window":
                notes[reason] += 1
            elif reason:
                rejected[reason] += 1
                # A record of another environment is not ours; any other rejected
                # record may have been the pair asked about.
                corrupt = corrupt or reason != "environment_mismatch"
        segments.append(dict(file=segment["file"], sha256=segment["sha256"], service=emitter,
                             start=iso(s_start), end=iso(s_end), sample_rate=rate))
        read_spans.setdefault(emitter, []).append(clipped)
        if corrupt:
            # Lost lines may have been this pair: the interval cannot support "no traffic".
            gaps.append((emitter, clipped, "corrupt_records"))
        else:
            covered.setdefault(emitter, []).append(clipped)
    for name in sorted(data_files - described):
        notes["open_segment_ignored"] += 1

    damaged = {}
    for emitter, interval, code in gaps:
        damaged.setdefault(emitter, []).append((interval, code))
    coverage = {}
    gap_rows = []
    for service in sorted(set(source.instrumented_services) | set(covered) | set(damaged)):
        bad = [i for i, _ in damaged.get(service, [])]
        good = union(subtract(union(covered.get(service, [])), bad))
        coverage[service] = good
        for interval, code in damaged.get(service, []):
            gap_rows.append(dict(code=code, service=service, start=iso(interval[0]), end=iso(interval[1])))
        for g_start, g_end in subtract([(start, end)], good + bad):
            gap_rows.append(dict(code="not_covered", service=service, start=iso(g_start), end=iso(g_end)))
    partial = bool(rejected or notes.keys() - {"outside_window"} or gap_rows)
    return _result(source, start, end, checked_at, freshness,
                   status="PARTIAL" if partial else "AVAILABLE",
                   reasons=sorted(set(rejected) | (set(notes) - {"outside_window"}) | {g["code"] for g in gap_rows}),
                   segments=segments, covered=coverage, gaps=sorted(gap_rows, key=lambda g: (g["service"], g["start"], g["code"])),
                   read_spans=read_spans, rejected=rejected, notes=notes, pairs=pairs,
                   unattributed=unattributed)


def _segment(root, sidecar, source, aliases, start, end, notes):
    path = root / sidecar
    try:
        if not regular_file(path) or path.stat().st_size > 4096:
            notes["invalid_coverage"] += 1
            return None
        meta = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        notes["invalid_coverage"] += 1
        return None
    try:
        if not isinstance(meta, dict) or meta.get("schema") != SEGMENT_SCHEMA:
            raise ValueError
        file = meta["file"]
        if (not isinstance(file, str) or not file.endswith(".jsonl") or "/" in file or "\\" in file
                or file != sidecar[:-len(".coverage.json")] + ".jsonl"):
            raise ValueError
        s_start, s_end = parse_time(meta["start"]), parse_time(meta["end"])
        rate = meta.get("sample_rate", 1.0)
        if (s_end <= s_start or isinstance(rate, bool) or not isinstance(rate, (int, float))
                or not 0 < rate <= 1 or not re.fullmatch(r"[a-f0-9]{64}", str(meta["sha256"]))
                or not isinstance(meta["emitter"], str) or not isinstance(meta["environment"], str)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        notes["invalid_coverage"] += 1
        return None
    segment = dict(file=file, start=s_start, end=s_end, sample_rate=float(rate), sha256=meta["sha256"],
                   service=aliases.get(meta["emitter"].strip().lower()))
    if meta["environment"] != source.environment:
        notes["environment_mismatch"] += 1
        segment["skip"] = True
    elif segment["service"] is None:
        notes["unmapped_emitter"] += 1
        segment["skip"] = True
    elif s_end <= start or s_start >= end:
        segment["skip"] = True  # outside the requested window; not a defect
    return segment


def _read_segment(path, sha256, limits):
    try:
        if not regular_file(path):
            raise GraphError("segment_not_regular")
        if path.stat().st_size > limits.max_segment_bytes:
            raise GraphError("segment_limit")
        raw = path.read_bytes()
    except OSError:
        raise GraphError("segment_unreadable") from None
    if len(raw) > limits.max_segment_bytes:
        raise GraphError("segment_limit")
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise GraphError("segment_digest_mismatch")
    return raw


def _record(line, segment, source, aliases, start, end, pairs, unattributed):
    if len(line) > source.limits.max_line_bytes:
        return "line_too_long"
    try:
        record = json.loads(line.decode("utf-8"))
    except (UnicodeError, ValueError):
        return "invalid_json"
    if not isinstance(record, dict):
        return "not_object"
    try:
        ts = parse_time(record.get("ts"))
    except ValueError as exc:
        return "missing_timestamp" if record.get("ts") is None else str(exc)
    if not segment["start"] <= ts < segment["end"]:
        return "outside_segment"
    if not start <= ts < end:
        return "outside_window"
    if "env" in record and record["env"] != source.environment:
        return "environment_mismatch"
    emitter = record.get("service")
    if not isinstance(emitter, str) or aliases.get(emitter.strip().lower()) != segment["service"]:
        return "emitter_mismatch"
    callee = segment["service"]
    method = record.get("method")
    method = method.upper() if isinstance(method, str) and method.upper() in METHODS else None
    route = record.get("route")
    route = (normalize_route(route) if isinstance(route, str) and ROUTE.fullmatch(route) and ".." not in route
             else None)
    status = record.get("status")
    status = status if type(status) is int and 100 <= status <= 599 else None
    duration = record.get("duration_ms")
    duration = float(duration) if (type(duration) in (int, float) and math.isfinite(duration)
                                   and 0 <= duration < 86_400_000) else None
    client = record.get("client")
    caller = aliases.get(client.strip().lower()) if isinstance(client, str) and len(client) <= 200 else None
    if caller is None:
        key = digest(client.strip().lower())[:16] if isinstance(client, str) and len(client) <= 200 else "absent"
        unattributed[(callee, key)] += 1
        return None
    sample = dict(status=status, duration=duration, rate=segment["sample_rate"], sha256=segment["sha256"],
                  ts=ts)
    pairs.setdefault((caller, callee, None, None), []).append(sample)
    if method and route:
        pairs.setdefault((caller, callee, method, route), []).append(sample)
    return None


def _aggregates(samples):
    result = dict(request_count=len(samples))
    rates = sorted({s["rate"] for s in samples})
    result["sample_rates"] = rates
    if rates != [1.0]:
        result["estimated_request_count"] = round(sum(1 / s["rate"] for s in samples), 3)
        result["estimate"] = True
    if all(s["status"] is not None for s in samples):
        result["error_count"] = sum(s["status"] >= 500 for s in samples)
        result["client_error_count"] = sum(400 <= s["status"] < 500 for s in samples)
    if all(s["duration"] is not None for s in samples):
        durations = [s["duration"] for s in samples]
        result["latency_ms"] = dict(p50=percentile(durations, 0.5), p95=percentile(durations, 0.95))
    return result


def _result(source, start, end, checked_at, freshness, *, status, reasons, segments, covered, gaps,
            read_spans, rejected, notes, pairs, unattributed):
    inst, env = source.installation_id, source.environment
    max_age = freshness.access_log_max_age_seconds
    source_ref = dict(id=source.id, uid=digest([inst, env, "runtime_source", source.id]),
                      kind="access_log", adapter=ADAPTER)
    observations = []
    for (caller, callee, method, route), samples in sorted(pairs.items(), key=lambda kv: tuple(x or "" for x in kv[0])):
        caller_ref = dict(service=caller, id=entity_id(service_entity(inst, env, caller)))
        callee_ref = dict(service=callee, id=entity_id(service_entity(inst, env, callee)))
        operation = None
        if method and route:
            operation = dict(service=callee, method=method, route=route,
                             id=entity_id(operation_entity(inst, env, callee, method, route)))
        kind = "CALLS_OPERATION" if operation else "CALLS_SERVICE"
        target = operation["id"] if operation else callee_ref["id"]
        # The observed interval is the request window clipped to the callee's
        # read segments. Gaps inside it are listed in result["gaps"].
        spans = read_spans[callee]
        w_start, w_end = min(s for s, _ in spans), max(e for _, e in spans)
        digests = sorted({s["sha256"] for s in samples})
        age = (checked_at - w_end).total_seconds()
        stale = age > max_age
        window = dict(start=iso(w_start), end=iso(w_end))
        aggregates = _aggregates(samples)
        reasons = ((["age_exceeded"] if stale else [])
                   + (["window_gap"] if any(g["service"] == callee for g in gaps) else [])
                   + (["sampled_source"] if aggregates.get("estimate") else []))
        observations.append(dict(
            id=digest([source_ref["uid"], kind, caller_ref["id"], target, window, digests]),
            # Contract kind "calls"; the target entity tells a service edge from an API call.
            relationship_id=relationship_id("calls", caller_ref["id"], target),
            kind=kind, origin="runtime", installation_id=inst, environment=env,
            caller=caller_ref, callee=callee_ref, operation=operation,
            method=method, route=route, window=window, aggregates=aggregates,
            provenance=dict(source=source_ref, segments=digests, source_version=digest(digests)),
            # Sufficient for the edge it backs. A service edge backs no operation.
            sufficiency="OBSERVED_WITHIN_WINDOW", semantic_level="operation" if operation else "service",
            freshness=Freshness(status="STALE" if stale else "CURRENT", checked_at=iso(checked_at),
                                reasons=reasons, valid_from=iso(w_start),
                                valid_until=iso(w_end + timedelta(seconds=max_age))).model_dump(mode="json"),
            visibility=[source.id]))
    return dict(
        schema=SCHEMA, adapter=ADAPTER, evidence_contract=EVIDENCE_CONTRACT,
        installation_id=inst, environment=env, checked_at=iso(checked_at), max_age_seconds=max_age,
        window=dict(start=iso(start), end=iso(end)),
        source=dict(**source_ref, status=status, reasons=reasons, segments=segments),
        coverage={s: [dict(start=iso(a), end=iso(b)) for a, b in spans] for s, spans in covered.items()},
        instrumented_services=sorted(source.instrumented_services),
        gaps=gaps, rejected=dict(sorted(rejected.items())), notes=dict(sorted(notes.items())),
        unattributed=[dict(callee=c, alias_digest=a, request_count=n)
                      for (c, a), n in sorted(unattributed.items())],
        observations=observations)


def assess(result, caller, callee, method=None, route=None):
    """Explain the runtime side of an expected edge. Never evidence of absence."""
    def answer(status, *reasons):
        freshness_reason, unknown = ASSESSMENT_CODES[status]
        return dict(status=status, caller=caller, callee=callee, method=method, route=route,
                    window=result["window"], proves_absence=False, reasons=list(reasons),
                    freshness_reason=freshness_reason, unknown=unknown)
    if result["source"]["status"] == "UNAVAILABLE":
        return answer("SOURCE_UNAVAILABLE", "source_unavailable")
    pair = [o for o in result["observations"] if o["caller"]["service"] == caller
            and o["callee"]["service"] == callee]
    wanted = method and route
    if wanted:
        exact = [o for o in pair if o["operation"] and o["method"] == method.upper()
                 and o["route"] == normalize_route(route)]
        if exact:
            return answer("OBSERVED", *exact[0]["freshness"]["reasons"])
        if any(o["operation"] for o in pair):
            # Same pair calls a different recorded route: visible conflict, not a silent pick.
            return answer("OTHER_ROUTE_OBSERVED", "route_differs")
        if pair:
            return answer("ROUTE_NOT_RECORDED", "service_edge_only")
    elif pair:
        return answer("OBSERVED", *pair[0]["freshness"]["reasons"])
    if callee not in result["instrumented_services"]:
        return answer("CALLEE_NOT_INSTRUMENTED", "callee_not_in_source")
    gaps = [g["code"] for g in result["gaps"] if g["service"] == callee]
    if gaps:
        return answer("WINDOW_GAP", *sorted(set(gaps)))
    rates = {s["sample_rate"] for s in result["source"]["segments"] if s["service"] == callee}
    if rates and min(rates) < 1:
        return answer("SAMPLED_NOT_OBSERVED", "sampled")
    return answer("NO_TRAFFIC_OBSERVED", "no_records_in_covered_window")


def relationships(result):
    """GraphRelationship records for the observed edges; storage is the next wave."""
    inst, env = result["installation_id"], result["environment"]
    edges = []
    for o in result["observations"]:
        target = (operation_entity(inst, env, o["callee"]["service"], o["method"], o["route"])
                  if o["operation"] else service_entity(inst, env, o["callee"]["service"]))
        edges.append(GraphRelationship(
            id=o["relationship_id"], kind="calls", source=service_entity(inst, env, o["caller"]["service"]),
            target=target, status="ACTIVE" if o["freshness"]["status"] == "CURRENT" else "STALE",
            origins=["runtime"], evidence_refs=[o["id"]], freshness=Freshness(**o["freshness"]),
            change_origin="runtime_sync", visibility=o["visibility"]).model_dump(mode="json"))
    return sorted(edges, key=lambda e: (e["source"]["service"], e["target"]["service"], e["target"]["kind"], e["id"]))


def evidence(observation):
    """One observation as output_contracts.RuntimeEvidence (validated, JSON form)."""
    o = observation
    inst, env = o["installation_id"], o["environment"]
    a = o["aggregates"]
    return RuntimeEvidence(
        id=o["id"], provenance="AUTHENTIC", sufficiency=o["sufficiency"],
        freshness=Freshness(**o["freshness"]), visibility=o["visibility"],
        source=o["provenance"]["source"]["id"], source_version=o["provenance"]["source_version"],
        consumer=service_entity(inst, env, o["caller"]["service"]),
        provider=service_entity(inst, env, o["callee"]["service"]),
        window_start=o["window"]["start"], window_end=o["window"]["end"],
        method=o["method"], route=o["route"],
        # The 2.0 aggregates carry no estimate or latency; the observation keeps them.
        aggregates=RuntimeAggregates(requests=a["request_count"], errors=a.get("error_count"),
                                     sampled=bool(a.get("estimate")))).model_dump(mode="json")


def evidence_records(result):
    return [evidence(o) for o in result["observations"]]


def source_freshness(result):
    """Freshness of the runtime source itself, for AnalysisResult.source_freshness."""
    source = result["source"]
    if source["status"] == "UNAVAILABLE":
        freshness = Freshness(status="UNKNOWN", checked_at=result["checked_at"], reasons=["source_unavailable"])
    else:
        age = (parse_time(result["checked_at"]) - parse_time(result["window"]["end"])).total_seconds()
        reasons = ((["partial_coverage"] if source["status"] == "PARTIAL" else [])
                   + (["window_gap"] if result["gaps"] else [])
                   + (["sampled_source"] if any(s["sample_rate"] < 1 for s in source["segments"]) else [])
                   + (["age_exceeded"] if age > result["max_age_seconds"] else []))
        freshness = Freshness(status="STALE" if age > result["max_age_seconds"] else "CURRENT",
                              checked_at=result["checked_at"], reasons=reasons)
    return SourceFreshness(source_kind="runtime", source_id=source["id"],
                           freshness=freshness).model_dump(mode="json")
