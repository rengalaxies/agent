"""Live configurations of a readiness revision: the service with a qualified model and the live baseline.

Both take the model, endpoint, request parameters and price from the 2B program
(``experiments/autonomous_mvp/programs/2b-r1``), so the service's model profile
is the one a 2B series qualifies and the baseline asks the same model on the
same endpoint.

``service-model``: the bench policy gets the 2B model section and read window
(``limits.max_tool_lines``); the qualification reference (report path, run_id,
SHA-256) goes to ``CoreAnalyzer`` as in an installation. ``preflight`` runs
``agent_service.qualification.check`` before the first change: on any mismatch
the series is refused before a model call, with the check's reason code. No
flag turns the model on.

``baseline-live``: ``CloudRuTransport`` on the 2B endpoint; the baseline's own
search protocol (``baseline.PROTOCOL``) with the model's completion limit. The
2B qualification covers ``actions-v3`` only and says nothing about the quality
of the baseline prompt.

A series stops early (``SeriesStop``) at its deadline, after an unauthorised or
rate-limited transport, or after two consecutive changes whose model requests
all failed. The changes left are recorded as not run, so they stay in every
denominator. Token counts the provider did not report stay unknown (None), and
so does their price.
"""
from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
import re
import time

MODEL_PROGRAM = "2b-r1"
READ_WINDOW = 60  # limits.max_tool_lines of every 2B case policy, part of the compared profile
STOP_AFTER_FAILED_CHANGES = 2
FATAL_TRANSPORT = ("http_unauthorized", "http_rate_limited")


def model_program():
    from tools.autonomous_mvp import program as program_2b

    return program_2b.load(MODEL_PROGRAM)[1]


def model_entry(model_id, program=None):
    program = program or model_program()
    for model in program["models"]:
        if model["id"] == model_id:
            return model
    raise SystemExit(f"REFUSED unknown model {model_id}: not in the 2B program {MODEL_PROGRAM}")


def slug(model_id):
    return re.sub(r"[^A-Za-z0-9_.-]", "--", model_id)


def model_section(model_id, *, steps=12, program=None):
    """The ModelConfig of the service-model configuration: the 2B case policy's model fields.

    Caps bound one analysis (``steps`` constitution steps); they are not part of the compared profile.
    """
    program = program or model_program()
    model, p = model_entry(model_id, program), program["parameters"]
    endpoint = program["provider"]["chat_endpoint"]
    tokens = (p["max_prompt_bytes"] + 4096 + model["max_completion_tokens"]) * steps
    rate = int(max(Decimal(model["price"]["input_per_million"]), Decimal(model["price"]["output_per_million"]))
               .to_integral_value(rounding=ROUND_CEILING))
    return dict(endpoint=endpoint, allowed_endpoints=[endpoint], model=model_id,
                configuration_id=f"readiness:{model_id}", api_key_env=program["provider"]["credential_env"],
                protocol="actions-v3", token_parameter=p["token_parameter"], allow_source_transfer=True,
                route="corporate", context_tokens=p["context_tokens"], max_output_tokens=model["max_completion_tokens"],
                max_prompt_bytes=p["max_prompt_bytes"], timeout_seconds=min(60.0, float(p["request_timeout_seconds"])),
                installation_token_cap=tokens, run_token_cap=tokens, currency="RUB",
                micro_per_million_tokens=rate * 1_000_000, installation_micro_cap=tokens * rate, run_micro_cap=tokens * rate)


def binding(model_id, *, qualification=None, program=None):
    """What a ledger records about its model: compared by the scorer before a baseline comparison."""
    program = program or model_program()
    model = model_entry(model_id, program)
    out = dict(model=model_id, endpoint=program["provider"]["chat_endpoint"], model_program=MODEL_PROGRAM,
               price=model["price"], max_completion_tokens=model["max_completion_tokens"])
    if qualification:
        out["qualification"] = dict(run_id=qualification["run_id"], report_sha256=qualification["report_sha256"])
    return out


def preflight(section: dict, qualification: dict | None, constitution_path=None):
    """The qualification check of the loaded code and profile; refuses the series before any model call.

    ``check`` reads the policy's model and read window only, the same in every change of the series.
    """
    from types import SimpleNamespace

    from agent_graph.contracts import Limits, ModelConfig
    from agent_service.qualification import check

    policy = SimpleNamespace(model=ModelConfig.model_validate(section), limits=Limits(max_tool_lines=READ_WINDOW))
    result = check(qualification, policy, constitution_path)
    if not result.ok:
        raise SystemExit(f"REFUSED model_not_qualified {result.reason_code}: {result.message}")
    return result


def rub(prompt_tokens, completion_tokens, price):
    """Roubles of known token counts at the 2B price; None when a count is unknown."""
    if prompt_tokens is None or completion_tokens is None:
        return None
    total = (Decimal(prompt_tokens) * Decimal(price["input_per_million"])
             + Decimal(completion_tokens) * Decimal(price["output_per_million"])) / Decimal(1_000_000)
    return float(round(total, 4))


class CountingModel:
    """The model the service runs with, every request counted with its outcome."""

    def __init__(self, inner):
        self.inner, self.calls, self.failures = inner, 0, 0

    def complete_raw(self, messages, schema, **kwargs):
        self.calls += 1
        try:
            return self.inner.complete_raw(messages, schema, **kwargs)
        except Exception:
            self.failures += 1
            raise


class SeriesStop:
    """When a live series stops before its last change, and why."""

    def __init__(self, seconds, *, clock=time.monotonic):
        self.clock, self.deadline, self.failed_in_a_row, self.reason = clock, clock() + seconds, 0, None

    def observe(self, requests, failures, codes=()):
        """One finished change: its model requests, how many failed, the transport codes it saw."""
        if any(code in FATAL_TRANSPORT for code in codes):
            self.reason = "transport_" + next(c for c in codes if c in FATAL_TRANSPORT)
        elif requests and failures == requests:
            self.failed_in_a_row += 1
            if self.failed_in_a_row >= STOP_AFTER_FAILED_CHANGES:
                self.reason = "model_requests_failing"
        else:
            self.failed_in_a_row = 0
        return self.reason

    def before_change(self):
        if self.reason is None and self.clock() >= self.deadline:
            self.reason = "series_deadline"
        return self.reason


def not_run(change, configuration, reason):
    """A change the series did not reach: a failure in every rate, never a skipped item."""
    return dict(change_id=change["change_id"], split=change["split"], family=change["family"],
                configuration=configuration, error=f"not_run:{reason}", wall_seconds=0.0,
                costs=dict(model_calls=0, prompt_tokens=0, completion_tokens=0, rub=0.0),  # nothing was sent
                human=dict(interventions=0, active_minutes=None, status="NOT_RECORDED"))
