"""Independent RUNBOOK-driven, browser-only rehearsal. No application imports."""
import json
import re
import traceback
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright


def run(url, username, password, out_dir):
    """Run the three situations through visible UI and preserve failures verbatim."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "CI_ONLY", "target": "CI_ONLY", "agent_rehearsal_not_user_study": True,
        "cloud_acceptance": False, "recording_consent": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "instructions": "lab/reports/interview/RUNBOOK.md", "situations": [],
        "limitations": ["Synthetic authenticated CI browser check; not independent participant interaction or cloud TLS acceptance.",
                         "No paid model credentials, new inference, or fresh verifier PASS requested."],
    }
    page = None

    def save_report():
        (out / "independent_rehearsal.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            probe = browser.new_context()
            probe_page = probe.new_page()
            response = probe_page.goto(url, wait_until="domcontentloaded")
            report["unauthenticated_status"] = response.status if response else None
            report["authentication_required"] = bool(response and response.status in (401, 403))
            probe.close()
            for scenario in ("confirmed", "unknown-owner", "stale"):
                item = {"scenario": scenario, "steps": [], "issues": [], "result": "RUNNING"}
                report["situations"].append(item)
                context = browser.new_context(http_credentials={"username": username, "password": password}, accept_downloads=True)
                page = context.new_page()
                page.set_default_timeout(15000)
                page.on("pageerror", lambda error: item["issues"].append({"browser_exception": str(error)}))

                def rendered():
                    # Browser-observed requests complete before inspecting rendered state.
                    # This waits on the UI; it does not issue application API requests.
                    page.wait_for_load_state("networkidle", timeout=30000)
                    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")

                def snapshot(name):
                    rendered()
                    text = page.locator("body").inner_text()
                    (out / (scenario + "-" + name + ".txt")).write_text(text, encoding="utf-8")
                    page.screenshot(path=str(out / (scenario + "-" + name + ".png")), full_page=True)
                    return text

                def click(pattern, label, required=True):
                    rx = re.compile(pattern, re.I)
                    for role in ("button", "link", "tab"):
                        matches = page.get_by_role(role, name=rx).all()
                        visible = [m for m in matches if m.is_visible() and m.is_enabled()]
                        if len(visible) == 1:
                            actual = visible[0].inner_text()
                            visible[0].click()
                            rendered()
                            item["steps"].append({"action": label, "visible_label": actual})
                            return True
                        if len(visible) > 1:
                            raise RuntimeError("Ambiguous visible UI for %s: %s" % (label, [m.inner_text() for m in visible]))
                    if required:
                        snapshot("missing-" + str(len(item["steps"])))
                        raise RuntimeError("No unique enabled visible button/link for " + label)
                    return False

                def choose(value, label):
                    # Inspect the browser's actual option text, never application internals.
                    candidates = []
                    for select in page.get_by_role("combobox").all():
                        if not select.is_visible():
                            continue
                        for option in select.locator("option").all():
                            text = option.inner_text().strip()
                            if re.search(value, text, re.I):
                                candidates.append((select, text))
                    if len(candidates) == 1:
                        select, text = candidates[0]
                        select.select_option(label=text)
                        rendered()
                        item["steps"].append({"action": label, "visible_option": text})
                        return
                    if not candidates:
                        # Segmented controls can expose the same choice as a button/radio.
                        radios = page.get_by_role("radio", name=re.compile(value, re.I)).all()
                        radios = [r for r in radios if r.is_visible()]
                        if len(radios) == 1:
                            radios[0].check()
                            rendered()
                            item["steps"].append({"action": label, "visible_option": value})
                            return
                        click(value, label)
                        return
                    raise RuntimeError("Ambiguous visible options for " + label + ": " + str([v for _, v in candidates]))

                def settle(label):
                    # Poll rendered state with the product's refresh control only.
                    deadline = time.monotonic() + 120
                    while True:
                        body = page.locator("body").inner_text()
                        if re.search(r"\b(QUEUED|RUNNING|PENDING)\b", body):
                            if time.monotonic() > deadline:
                                raise RuntimeError("UI job did not reach terminal state: " + label)
                            page.wait_for_timeout(1000)
                            click(r"^Обновить состояние$", "refresh job state")
                            continue
                        return snapshot(label)

                def require(pattern, text, meaning):
                    if not re.search(pattern, text, re.I):
                        raise AssertionError("Visible UI assertion failed: " + meaning)
                    item.setdefault("checks", []).append(meaning)

                try:
                    page.goto(url, wait_until="domcontentloaded")
                    initial = snapshot("initial")
                    item["preflight_visible"] = initial
                    require(r"BLOCKED", initial, "apply is BLOCKED")
                    if not report["authentication_required"]:
                        raise AssertionError("Unauthenticated browser did not receive authentication challenge")
                    labels = {"confirmed": "Подтверждённая зависимость", "unknown-owner": "Неизвестный владелец", "stale": "Устаревание после новой ревизии"}
                    choose(labels[scenario], "choose scenario")
                    click(r"^Начать отдельную сессию$", "create fresh session")
                    fresh = snapshot("fresh-session")
                    item["session_visible"] = fresh
                    require(r"(?:scenario|сценар|version|верси)", fresh, "session scenario/version visible")
                    change_id = "independent-" + scenario + "-" + uuid.uuid4().hex[:10]
                    page.get_by_label("ID изменения", exact=True).fill(change_id)
                    item["change_id"] = change_id
                    require(r"Ломающее: неверный backfill RUB", page.locator("body").inner_text(), "supported breaking example selected")
                    click(r"^Сохранить изменение$", "create revision 1")
                    click(r"^Страница изменения$", "open change details")
                    choose(r"LIVE RUN", "collect mode LIVE RUN")
                    click(r"^Собрать основания$", "collect actual sources")
                    collected = settle("collection")
                    require(r"SUCCEEDED|SUCCESS|COMPLETED|успеш|заверш", collected, "source collection reached visible success")
                    if scenario != "unknown-owner":
                        # Deliberately expose unavailable LIVE; retain failure in history.
                        click(r"^Запустить анализ$", "attempt LIVE without model credentials")
                        failed = settle("live-unavailable")
                        require(r"FAILED|BLOCKED|UNKNOWN|ошиб|недоступ|ключ|credential", failed, "LIVE unavailable reason remains visible")
                        item["live_unavailable"] = True
                    choose(r"FIXTURE\s*/?\s*CONTROL" if scenario == "unknown-owner" else r"REPLAY", "explicit saved analysis mode")
                    click(r"^Запустить анализ$", "run saved analysis")
                    analysis = settle("analysis")
                    require(r"SUCCEEDED|SUCCESS|COMPLETED|успеш|заверш", analysis, "saved analysis terminal success")
                    click(r"^Inbox команды$", "open inbox")
                    if scenario == "unknown-owner":
                        owner = snapshot("ownership-control")
                        require(r"coordinator|координатор", owner, "coordinator card visible")
                        require(r"unknown|неизвест|не определ|не установлен", owner, "unknown owner explicit")
                        require(r"CONTROL|контрол", owner, "ownership controlled input labeled")
                        require(r"\?|уточн|назнач|владел", owner, "coordinator ownership question visible")
                    else:
                        choose(r"billing|биллинг", "choose billing demonstration role")
                        inbox = snapshot("inbox")
                        require(r"billing|биллинг", inbox, "billing card visible")
                        require(r"Почему касается команды|основан|evidence|basis", inbox, "card grounds visible")
                        click(r"^Записать решение$", "record shown team decision")
                        click(r"^Патч и проверка$", "open patch view")
                        choose(r"REPLAY", "explicit saved SQL mode")
                        click(r"^Подготовить патч$", "prepare saved SQL")
                        patch = settle("saved-sql")
                        require(r"SQL|UPDATE|ALTER", patch, "saved SQL visible")
                        require(r"BLOCKED", patch, "acknowledgement never grants apply")
                        if scenario == "stale":
                            click(r"^Страница изменения$", "return to change")
                            click(r"^Подготовить новую ревизию$", "prepare revision 2")
                            click(r"^Сохранить изменение$", "submit revision 2")
                            stale = snapshot("new-revision")
                            require(r"stale|устар|истори|неактуаль|нов.*оцен", stale, "prior results are historical after revision 2")
                    with page.expect_download(timeout=15000) as download_info:
                        click(r"^Экспорт исследования JSON$", "export selected session JSON")
                    download_info.value.save_as(str(out / (scenario + "-session-export.json")))
                    click(r"^Завершить сессию$", "end selected session")
                    snapshot("ended")
                    choose(labels[scenario], "choose clean follow-on scenario")
                    click(r"^Начать отдельную сессию$", "create next empty session")
                    clean = snapshot("next-clean-session")
                    if change_id in clean:
                        raise AssertionError("Prior session change is visible in new session")
                    item.setdefault("checks", []).append("new session excludes previous change ID")
                    click(r"^Завершить сессию$", "end clean follow-on session")
                    item["result"] = "COMPLETED"
                except Exception:
                    item["result"] = "FAILED"
                    item["exception"] = traceback.format_exc()
                    try:
                        snapshot("failure")
                        click(r"end session|завершить сессию|закончить сессию", "end after failure", required=False)
                    except Exception:
                        item["cleanup_exception"] = traceback.format_exc()
                finally:
                    context.close()
                    save_report()
        finally:
            browser.close()
            report["finished_at"] = datetime.now(timezone.utc).isoformat()
            save_report()
    return report
