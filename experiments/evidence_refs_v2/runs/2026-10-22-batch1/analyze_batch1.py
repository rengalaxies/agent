"""Read-only verification and cost summary; never imports or invokes a model."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("report", type=Path)
    p.add_argument("manifest", type=Path)
    p.add_argument("ledger", type=Path)
    p.add_argument("pricing", type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    report, packet, ledger, prices = map(read, [args.report, args.manifest, args.ledger, args.pricing])
    original_digest = packet["manifest_digest"]
    fixed = {k: v for k, v in packet.items() if k != "manifest_digest"}
    actual_digest = hashlib.sha256(json.dumps(fixed, sort_keys=True, ensure_ascii=False,
                                            separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert actual_digest == original_digest == report["manifest_digest"] == ledger["manifest_digest"]
    assert report["source_sha"] == ledger["source_sha"]
    assert report["historical_request_count"] == 21
    assert report["historical_requests"] == packet["historical_requests"] == ledger["historical_requests"]
    assert report["new_attempts"] == ledger["attempts"]
    assert report["cases"] == ledger["cases"]
    assert report["new_request_cap"] == ledger["request_cap"] == 30
    assert report["new_money_cap_micro"] == ledger["money_cap_micro"] == 100_000_000
    assert len(ledger["attempts"]) <= 30
    assert report["reserved_new_micro"] <= 100_000_000
    assert [a["id"] for a in ledger["attempts"]] == list(range(22, 22 + len(ledger["attempts"])))
    historical_estimate = Decimal(0)
    for attempt in ledger["historical_requests"]:
        if attempt["usage"] is not None:
            rate = prices["models"][attempt["model"]]
            historical_estimate += (Decimal(attempt["usage"]["prompt_tokens"]) * Decimal(rate["input_per_million"])
                                   + Decimal(attempt["usage"]["completion_tokens"]) * Decimal(rate["output_per_million"])) / 1_000_000
    rows = []
    for case in packet["plan"]["case_order"]:
        for model in packet["plan"]["models"]:
            key = case + ":" + model
            item = next((c for c in ledger["cases"] if c["key"] == key), None)
            attempts = [a for a in ledger["attempts"] if a["case_key"] == key]
            usage = [a["usage"] for a in attempts if a["usage"] is not None]
            inp = sum(u["prompt_tokens"] for u in usage)
            out = sum(u["completion_tokens"] for u in usage)
            rate = prices["models"][model]
            estimate = (Decimal(inp) * Decimal(rate["input_per_million"])
                        + Decimal(out) * Decimal(rate["output_per_million"])) / 1_000_000
            result = item.get("result", {}) if item else {}
            trace = result.get("report", {})
            events = trace.get("events", [])
            rows.append(dict(case=case, model=model, status=result.get("status", "NOT_RUN"),
                             reason=result.get("reason"), requests=len(attempts),
                             http_statuses=[a["http_status"] for a in attempts],
                             finish_reasons=[a.get("finish_reason") for a in attempts],
                             actions=[e["action"] for e in events],
                             evaluation=result.get("evaluation"),
                             observed_input=inp, observed_output=out,
                             unknown_usage_ids=[a["id"] for a in attempts if a["usage"] is None],
                             known_usage_estimate_rub=str(estimate),
                             request_elapsed_seconds=sum(e["seconds"] for e in events),
                             case_elapsed_seconds=(max([a.get("observation_epoch", a["reserved_at"])
                                                        for a in attempts], default=item["started"])
                                                   - item["started"]) if item else None,
                             candidates=trace.get("candidate_ids", [])))
    summary = dict(source_sha=report["source_sha"], manifest_digest=original_digest,
                   status=report["status"], series_elapsed_seconds=(report["finished_epoch"]
                        - report["series_started_epoch"]) if report.get("finished_epoch") else None,
                   new_requests=report["new_request_count"], historical_requests=21,
                   reserved_rub=str(Decimal(report["reserved_new_micro"]) / 1_000_000),
                   new_usage=report["new_usage"], historical_usage=report["historical_usage"],
                   historical_known_usage_estimate_rub=str(historical_estimate),
                   rows=rows, actual_billed_cost="NOT_MEASURED",
                   pricing_source=prices["source"],
                   new_known_usage_estimate_rub=str(sum(Decimal(r["known_usage_estimate_rub"]) for r in rows)))
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
