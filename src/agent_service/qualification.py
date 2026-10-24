"""The model path runs only on a batch 2B qualification that matches what is actually loaded.

The service configuration points at a 2B report (``amvp-report-1``) by path,
``run_id`` and the SHA-256 of the report file. The report must say
``QUALIFIED`` for the configured model ID, name the same provider endpoint
(``provider.chat_endpoint``) and carry the protocol fingerprint of its run
(``protocol``, the manifest's ``protocol.fingerprint()``). That fingerprint is
compared with the one computed here from the loaded executor, system prompt,
action schema (it covers every action, graph_* included), constitution and core
files. A boolean switch is not enough: anyone can set it.

Any mismatch keeps the model off and gives a stable reason code plus a
readable message for ``python -m agent_service doctor``.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

REPORT_SCHEMA = "amvp-report-1"
EXECUTOR = "agent_graph.executor.run_investigation"
PINNED_FILES = ("constitutions/agent-service-v1.yaml", "src/agent_graph/actions.py", "src/agent_graph/executor.py")
LOADED_PREFIXES = ("src/agent_graph/", "constitutions/")
ROOT = Path(__file__).resolve().parents[2]


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


LABELS = {"constitution_version": "версия конституции", "system_sha256": "хеш системного prompt",
          "schema_sha256": "хеш схемы действий и инструментов", "protocol": "протокол", "executor": "исполнитель"}


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
    run_id = report.get("run_id")
    if report.get("schema") != REPORT_SCHEMA or run_id != reference["run_id"]:
        return Qualification(False, "qualification_report_mismatch",
                             f"Модель {model_id} отключена: ожидался отчёт {REPORT_SCHEMA} запуска "
                             f"{reference['run_id']}, в файле {report.get('schema')} запуска {run_id}.", model_id, run_id)
    entry = (report.get("models") or {}).get(model_id)
    if entry is None:
        return Qualification(False, "model_not_in_qualification",
                             f"Модель {model_id} отключена: в отчёте {run_id} её нет. Квалифицированы: "
                             f"{', '.join(sorted(report.get('models') or {})) or 'никто'}.", model_id, run_id)
    if entry.get("verdict") != "QUALIFIED":
        return Qualification(False, "model_not_qualified",
                             f"Модель {model_id} отключена: в отчёте {run_id} вердикт {entry.get('verdict')}, "
                             "а нужен QUALIFIED.", model_id, run_id)
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
    return Qualification(True, "qualified", f"Модель {model_id} включена: отчёт {run_id} QUALIFIED, отпечаток "
                                            "протокола совпадает с загруженным.", model_id, run_id)
