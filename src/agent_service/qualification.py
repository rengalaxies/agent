"""The model path runs only on a batch 2B qualification that matches what is actually loaded.

The service configuration points at a 2B report (``amvp-report-2``, written by
``tools.autonomous_mvp.scorer.report``) by path, ``run_id`` and the SHA-256 of
the report file. A self-declared verdict is not enough: anyone can write
``QUALIFIED``. The report is accepted only if

* it comes from the 2B runner in a GitHub Actions run at a clean commit
  (``provenance``) and names the manifest digest of the series;
* the configured model ID has verdict ``QUALIFIED``, every program phase is
  ``COMPLETED`` for it, the program ran in full (``G7_program_complete``,
  executed == expected) and every gate and metric of the program holds;
* the provider endpoint (``provider.chat_endpoint``) and the protocol
  fingerprint of the run (``protocol``, the manifest's ``protocol.fingerprint()``)
  equal those computed here from the loaded executor, system prompt, action
  schema (every action, graph_* included), constitution and core files;
* the model profile its evaluation case-runs used (``models[id].profile``,
  ``tools.autonomous_mvp.protocol.model_profile``) equals the one this process
  sends: ModelConfig fields plus what ``agent_graph.inference.ChatModel`` adds
  to every request. Credential names, configuration IDs, caps, prices and the
  request timeout belong to the installation and are not compared.

Any mismatch keeps the model off and gives a stable reason code plus a
readable message for ``python -m agent_service doctor``. This checks the
report, it does not prove a run happened: the file is trusted by its digest.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

REPORT_SCHEMA = "amvp-report-2"
RUNNER = "tools.autonomous_mvp.runner"
WORKFLOW = ".github/workflows/autonomous-mvp-model.yml@"
EXECUTOR = "agent_graph.executor.run_investigation"
PINNED_FILES = ("constitutions/agent-service-v1.yaml", "src/agent_graph/actions.py", "src/agent_graph/executor.py")
LOADED_PREFIXES = ("src/agent_graph/", "constitutions/")
ROOT = Path(__file__).resolve().parents[2]
# What ChatModel._request sends besides the ModelConfig values.
CHAT_STREAM = False
CHAT_SAMPLING = {"temperature": 0}
CHAT_RESPONSE_FORMAT = {"type": "json_schema", "name": "graph_action", "strict": True}
# Profile fields compared with the loaded configuration. timeout_seconds is reported but not
# compared: it changes when a request is abandoned, never what the model is sent.
PROFILE_FIELDS = ("endpoint", "model", "protocol", "token_parameter", "max_output_tokens", "context_tokens",
                  "max_prompt_bytes", "max_tool_lines", "stream", "response_format", "sampling")
PROVENANCE_FIELDS = ("runner", "repository", "workflow_ref", "workflow_run_id", "workflow_run_attempt", "source_sha")


@dataclass(frozen=True)
class Qualification:
    ok: bool
    reason_code: str
    message: str
    model_id: str | None = None
    run_id: str | None = None


def text_sha256(path: Path) -> str:
    """Same rule as the 2B runner: text hash with CRLF normalized to LF."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def loaded_fingerprint(constitution_path: str | None) -> dict:
    """The protocol fingerprint of the code and constitution this process runs."""
    from agent_graph.actions import PROTOCOL, action_schema, system_prompt
    from agent_graph.constitution import DEFAULT_PATH, load

    path = Path(constitution_path or DEFAULT_PATH)
    constitution, version = load(path)
    files = {f: text_sha256(ROOT / f) for f in PINNED_FILES if f != PINNED_FILES[0]}
    files[PINNED_FILES[0]] = text_sha256(path)
    return {"protocol": PROTOCOL, "executor": EXECUTOR, "constitution_version": version,
            "system_sha256": hashlib.sha256(system_prompt(constitution).encode()).hexdigest(),
            "schema_sha256": hashlib.sha256(json.dumps(action_schema(), sort_keys=True).encode()).hexdigest(),
            "code_sha256": files}


def loaded_profile(policy) -> dict:
    """The model profile this process uses, in the shape of the 2B ``model_profile``."""
    m = policy.model
    return {"endpoint": m.endpoint, "model": m.model, "protocol": m.protocol, "token_parameter": m.token_parameter,
            "max_output_tokens": m.max_output_tokens, "context_tokens": m.context_tokens,
            "max_prompt_bytes": m.max_prompt_bytes, "timeout_seconds": m.timeout_seconds,
            "max_tool_lines": policy.limits.max_tool_lines, "stream": CHAT_STREAM,
            "response_format": dict(CHAT_RESPONSE_FORMAT), "sampling": dict(CHAT_SAMPLING)}


LABELS = {"constitution_version": "версия конституции", "system_sha256": "хеш системного prompt",
          "schema_sha256": "хеш схемы действий и инструментов", "protocol": "протокол", "executor": "исполнитель"}
PROFILE_LABELS = {"endpoint": "endpoint модели", "model": "ID модели", "protocol": "протокол действий",
                  "token_parameter": "имя параметра лимита ответа", "max_output_tokens": "лимит токенов ответа",
                  "context_tokens": "размер контекста", "max_prompt_bytes": "лимит размера запроса",
                  "max_tool_lines": "окно чтения исходников (limits.max_tool_lines)",
                  "stream": "потоковый режим", "response_format": "формат ответа",
                  "sampling": "параметры сэмплирования"}


def _provenance_gaps(provenance) -> list[str]:
    """Names of provenance fields that are missing or malformed."""
    if not isinstance(provenance, dict):
        return list(PROVENANCE_FIELDS)
    p = provenance
    repository = p.get("repository")
    valid = {"runner": p.get("runner") == RUNNER,
             "repository": isinstance(repository, str) and re.fullmatch(r"[\w.-]+/[\w.-]+", repository) is not None,
             "workflow_ref": isinstance(p.get("workflow_ref"), str) and isinstance(repository, str)
             and p["workflow_ref"].startswith(f"{repository}/{WORKFLOW}"),
             "workflow_run_id": isinstance(p.get("workflow_run_id"), str) and p["workflow_run_id"].isdigit(),
             "workflow_run_attempt": type(p.get("workflow_run_attempt")) is int and p["workflow_run_attempt"] >= 1,
             "source_sha": isinstance(p.get("source_sha"), str)
             and re.fullmatch(r"[0-9a-f]{40}", p["source_sha"]) is not None}
    return [f for f in PROVENANCE_FIELDS if not valid[f]]


def _result_failure(report: dict, entry: dict, model_id: str, run_id: str) -> tuple[str, str] | None:
    """Structure of a QUALIFIED result: every phase completed, the program in full, every gate and metric held."""
    program = report.get("program") if isinstance(report.get("program"), dict) else {}
    phases, gates, metrics = program.get("phases"), program.get("gates"), program.get("metrics")
    if not (phases and gates and metrics and all(isinstance(x, list) for x in (phases, gates, metrics))):
        return ("qualification_report_incomplete",
                f"Модель {model_id} отключена: в отчёте {run_id} нет списка фаз, гейтов и метрик программы "
                "(поле program), сверить результат не с чем.")
    done = entry.get("phases") if isinstance(entry.get("phases"), dict) else {}
    open_phases = [p for p in phases if not isinstance(done.get(p), dict) or done[p].get("status") != "COMPLETED"
                   or done[p].get("reserved_open") != 0]
    if open_phases:
        return ("qualification_phase_incomplete",
                f"Модель {model_id} отключена: в отчёте {run_id} не завершены фазы {', '.join(open_phases)}, "
                "а вердикт QUALIFIED требует всех фаз программы в статусе COMPLETED.")
    recorded = entry.get("gates") if isinstance(entry.get("gates"), dict) else {}
    if recorded.get("G7_program_complete") is not True or entry.get("executed") != entry.get("expected_case_runs") \
            or not entry.get("executed"):
        return ("qualification_program_incomplete",
                f"Модель {model_id} отключена: в отчёте {run_id} программа выполнена не полностью "
                f"(G7_program_complete={recorded.get('G7_program_complete')}, выполнено {entry.get('executed')} "
                f"из {entry.get('expected_case_runs')} case-run), а вердикт QUALIFIED.")
    failed = sorted(g for g in set(gates) | set(recorded) if recorded.get(g) is not True)
    if failed:
        return ("qualification_gate_failed",
                f"Модель {model_id} отключена: в отчёте {run_id} вердикт QUALIFIED, но гейты {', '.join(failed)} "
                "не выполнены или отсутствуют. Отчёт противоречит сам себе.")
    thresholds = entry.get("thresholds") if isinstance(entry.get("thresholds"), dict) else {}
    failed = sorted(t for t in set(metrics) | set(thresholds)
                    if not isinstance(thresholds.get(t), dict) or thresholds[t].get("passed") is not True)
    if failed:
        return ("qualification_threshold_failed",
                f"Модель {model_id} отключена: в отчёте {run_id} вердикт QUALIFIED, но метрики {', '.join(failed)} "
                "не прошли порог или отсутствуют. Отчёт противоречит сам себе.")
    return None


def check(reference: dict | None, policy, constitution_path: str | None) -> Qualification:
    """``reference`` is ``{report_path, run_id, report_sha256}`` from the service configuration."""
    if policy.model is None:
        return Qualification(False, "model_not_configured", "Модель не настроена: сервис работает без модели.")
    model_id = policy.model.model
    if not reference:
        return Qualification(False, "qualification_missing",
                             f"Модель {model_id} отключена: в конфигурации нет ссылки на отчёт квалификации 2Б "
                             "(core.model_qualification).", model_id)
    path = Path(reference["report_path"])
    try:
        raw = path.read_bytes()
    except OSError:
        return Qualification(False, "qualification_report_unreadable",
                             f"Модель {model_id} отключена: отчёт 2Б {path} не читается.", model_id)
    if hashlib.sha256(raw).hexdigest() != reference["report_sha256"]:
        return Qualification(False, "qualification_report_digest_mismatch",
                             f"Модель {model_id} отключена: SHA-256 файла {path} не совпадает с указанным в "
                             "конфигурации. Отчёт изменён или указан не тот файл.", model_id)
    try:
        report = json.loads(raw)
    except ValueError:
        return Qualification(False, "qualification_report_invalid",
                             f"Модель {model_id} отключена: отчёт 2Б не является JSON.", model_id)
    if not isinstance(report, dict):
        return Qualification(False, "qualification_report_invalid",
                             f"Модель {model_id} отключена: отчёт 2Б не является JSON-объектом.", model_id)
    run_id = report.get("run_id")
    if report.get("schema") != REPORT_SCHEMA or run_id != reference["run_id"]:
        return Qualification(False, "qualification_report_mismatch",
                             f"Модель {model_id} отключена: ожидался отчёт {REPORT_SCHEMA} запуска "
                             f"{reference['run_id']}, в файле {report.get('schema')} запуска {run_id}.", model_id, run_id)
    gaps = _provenance_gaps(report.get("provenance"))
    if gaps:
        return Qualification(False, "qualification_provenance_missing",
                             f"Модель {model_id} отключена: в отчёте {run_id} нет происхождения или оно неполное "
                             f"(provenance: {', '.join(gaps)}). Отчёт должен выпустить {RUNNER} в запуске "
                             "GitHub Actions на чистом коммите.", model_id, run_id)
    manifest_digest = report.get("manifest_digest")
    if not isinstance(manifest_digest, str) or re.fullmatch(r"[0-9a-f]{64}", manifest_digest) is None:
        return Qualification(False, "qualification_manifest_missing",
                             f"Модель {model_id} отключена: в отчёте {run_id} нет digest manifest серии "
                             "(manifest_digest), неизвестно, какая программа выполнялась.", model_id, run_id)
    models = report.get("models") if isinstance(report.get("models"), dict) else {}
    entry = models.get(model_id)
    if not isinstance(entry, dict):
        return Qualification(False, "model_not_in_qualification",
                             f"Модель {model_id} отключена: в отчёте {run_id} её нет. Квалифицированы: "
                             f"{', '.join(sorted(models)) or 'никто'}.", model_id, run_id)
    if entry.get("verdict") != "QUALIFIED":
        return Qualification(False, "model_not_qualified",
                             f"Модель {model_id} отключена: в отчёте {run_id} вердикт {entry.get('verdict')}, "
                             "а нужен QUALIFIED.", model_id, run_id)
    failure = _result_failure(report, entry, model_id, run_id)
    if failure:
        return Qualification(False, failure[0], failure[1], model_id, run_id)
    recorded, provider = report.get("protocol"), report.get("provider")
    if not isinstance(recorded, dict) or not isinstance(provider, dict) or not provider.get("chat_endpoint"):
        return Qualification(False, "qualification_report_incomplete",
                             f"Модель {model_id} отключена: в отчёте {run_id} нет отпечатка протокола или "
                             "endpoint провайдера (поля protocol, provider.chat_endpoint), сверить не с чем.",
                             model_id, run_id)
    # chat_endpoint is the stable provider id; name/verification are descriptive and credential
    # names may differ between the 2B runner and an installation.
    if provider["chat_endpoint"] != policy.model.endpoint:
        return Qualification(False, "qualification_provider_mismatch",
                             f"Модель {model_id} отключена: отчёт {run_id} квалифицировал её на "
                             f"{provider['chat_endpoint']}, а настроен {policy.model.endpoint}.", model_id, run_id)
    loaded = loaded_fingerprint(constitution_path)
    for field in ("protocol", "executor", "constitution_version", "system_sha256", "schema_sha256"):
        if recorded.get(field) != loaded[field]:
            return Qualification(False, f"qualification_{field}_mismatch",
                                 f"Модель {model_id} отключена: {LABELS[field]} в отчёте {run_id} "
                                 f"({str(recorded.get(field))[:16]}) не совпадает с загруженной "
                                 f"({loaded[field][:16]}). Нужна новая квалификация 2Б для текущей версии.",
                                 model_id, run_id)
    files = recorded.get("code_sha256") or {}
    # Every core file the report pinned and this process loads, plus the three it must pin.
    # The 2B harness (tools/autonomous_mvp) is not loaded by the service and is not compared.
    names = set(PINNED_FILES) | {n for n in files if n.startswith(LOADED_PREFIXES)}
    for name in sorted(names):
        digest = loaded["code_sha256"].get(name) or (text_sha256(ROOT / name) if (ROOT / name).is_file() else None)
        if files.get(name) != digest:
            return Qualification(False, "qualification_code_mismatch",
                                 f"Модель {model_id} отключена: файл {name} отличается от проверенного в отчёте "
                                 f"{run_id}. Нужна новая квалификация 2Б.", model_id, run_id)
    used = entry.get("profile")
    missing = [f for f in PROFILE_FIELDS if not isinstance(used, dict) or f not in used]
    if missing:
        return Qualification(False, "qualification_profile_missing",
                             f"Модель {model_id} отключена: в отчёте {run_id} нет профиля параметров модели "
                             f"или в нём нет полей {', '.join(missing)}; сверить с конфигурацией не с чем.",
                             model_id, run_id)
    expected = loaded_profile(policy)
    for field in PROFILE_FIELDS:
        if used[field] != expected[field]:
            return Qualification(False, f"qualification_profile_{field}_mismatch",
                                 f"Модель {model_id} отключена: {PROFILE_LABELS[field]} в отчёте {run_id} "
                                 f"({json.dumps(used[field], ensure_ascii=False)}) не совпадает с загруженной "
                                 f"конфигурацией ({json.dumps(expected[field], ensure_ascii=False)}). Нужна "
                                 "квалификация 2Б с этими параметрами или конфигурация как в отчёте.",
                                 model_id, run_id)
    return Qualification(True, "qualified", f"Модель {model_id} включена: отчёт {run_id} QUALIFIED, отпечаток "
                                            "протокола и профиль параметров совпадают с загруженными.",
                         model_id, run_id)
