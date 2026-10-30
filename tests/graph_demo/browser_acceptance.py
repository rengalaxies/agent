"""Real browser journey against the real CLI backend and operator Docker runner. No route mocks."""

from pathlib import Path
import shutil

from playwright.sync_api import sync_playwright

from agent_graph_demo.contracts import now
from tools.agent_graph_demo.run_scenario import run
from tools.agent_graph_demo.runtime_guard import RuntimeGuard


def journey(base_url, username, password, operator, output, store):
    output = Path(output)
    screenshots = []
    observations = []
    guard = RuntimeGuard(
        operator["state_root"],
        operator["runtime_root"],
        operator["image"],
        operator["product_sha"],
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=shutil.which("chromium") or None, headless=True
        )
        try:
            anon = browser.new_context()
            assert anon.request.get(base_url).status == 401
            anon.close()
            context = browser.new_context(
                viewport={"width": 1440, "height": 1100},
                http_credentials={"username": username, "password": password},
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base_url)
            old_sid = page.locator("#sessions").input_value()
            page.get_by_role("button", name="Новый показ", exact=True).click()
            page.wait_for_function(
                "old => document.querySelector('#sessions').value.length===36 && document.querySelector('#sessions').value!==old && document.querySelector('#message').textContent.includes('Новый показ A')",
                arg=old_sid,
            )
            sid = page.locator("#sessions").input_value()
            page.get_by_role("button", name="Обследовать исходники", exact=True).click()
            page.wait_for_function(
                "() => document.querySelector('#edges').children.length===3 && !document.querySelector('#prepare').disabled",
                timeout=180000,
            )
            # Scenario A has no real gap: the old "Неполные данные" came from FastAPI route
            # decorators counted as unknown clients, which batch 2A removed as noise.
            coverage = page.locator("#coverage").inner_text()
            assert coverage.startswith("Обследован разрешённый корпус"), coverage
            assert "Семантическая корректность не доказана" in coverage

            def actual(version):
                generation = guard.read()["generation"]
                receipt = run(operator, sid, version, generation, output / "receipts")
                observations.append(
                    {
                        "version": version,
                        "status": receipt["status"],
                        "consumers": receipt["consumers"],
                        "manifest": receipt["running_manifest_sha256"],
                        "health_control": receipt.get("health_control"),
                    }
                )
                assert (
                    len(
                        {
                            c["Config"]["Labels"]["com.docker.compose.project"]
                            for c in guard.active(guard.inventory())
                        }
                    )
                    == 1
                )
                page.get_by_role(
                    "button", name="Получить результаты", exact=True
                ).click()
                page.wait_for_function(
                    f"() => document.querySelector('#running').dataset.version==='{version}'"
                )
                return receipt

            a = actual("A")
            page.screenshot(path=str(output / "baseline.png"), full_page=True)
            screenshots.append("baseline.png")
            assert a["status"] == "PASS"
            assert all(
                v["actual_count"] == 250 and v["passed"]
                for v in a["consumers"].values()
            )
            page.locator('button[data-version="B"]').click()
            page.wait_for_function(
                "() => document.querySelector('#proposed').dataset.version==='B' && !document.querySelector('#prepare').disabled",
                timeout=180000,
            )
            assert page.locator("#running").get_attribute("data-version") == "A"
            assert "Reporting: возможна потеря" in page.locator("#impact").inner_text()
            page.locator("#edges button").filter(has_text="Reporting → Orders").click()
            page.wait_for_function(
                "() => document.querySelector('#evidence-meta').textContent.includes('reporting / client.py')"
            )
            assert "requests.get" in page.locator("#source").inner_text()
            b = actual("B")
            assert b["status"] == "FAIL"
            assert b["consumers"]["Reporting"]["missing_ids"] == list(range(101, 251))
            assert b["consumers"]["Billing"]["passed"]
            page.wait_for_function(
                "() => document.querySelector('#checks').textContent.includes('Есть потери данных')"
            )
            # Audit 2026-10-22: a correction at B replaced the B analysis with the version-A hint.
            page.locator("#edges button").filter(has_text="Reporting → Orders").click()
            page.wait_for_function(
                "() => document.querySelector('#evidence-meta').textContent.includes('reporting / client.py')"
            )
            page.locator("#correction-details summary").click()
            page.locator("#statement").fill("Владелец Reporting уведомлён о лимите")
            page.locator("#correct").click()
            page.wait_for_function(
                "() => [...document.querySelectorAll('#history button')].some(b => b.textContent.startsWith('Человеческое уточнение') && !b.disabled)"
                " && !document.querySelector('#prepare').disabled",
                timeout=180000,
            )
            assert "Reporting: возможна потеря" in page.locator("#impact").inner_text()
            for width, height, label in [
                (1440, 1100, "desktop-B"),
                (390, 844, "mobile-B"),
            ]:
                page.set_viewport_size({"width": width, "height": height})
                page.screenshot(path=str(output / (label + ".png")), full_page=True)
                assert page.evaluate(
                    "() => document.documentElement.scrollWidth <= window.innerWidth"
                )
                screenshots.append(label + ".png")
            page.set_viewport_size({"width": 1440, "height": 1100})
            # A failed graph/history read must not leave the previous usable quote.
            page.route("**/graph*", lambda route: route.abort())
            page.locator("#history button").last.click()
            page.wait_for_function("() => document.querySelector('#source').textContent.includes('Прежние основания скрыты')")
            assert "requests.get" not in page.locator("#source").inner_text()
            assert page.locator("#edges button").count() == 0
            assert page.locator("#correct").is_disabled()
            assert "недоступен" in page.locator("#message").inner_text()
            page.screenshot(path=str(output / "graph-unavailable.png"), full_page=True)
            screenshots.append("graph-unavailable.png")
            page.unroute("**/graph*")
            page.locator("#current").click()
            page.wait_for_function("() => document.querySelector('#edges').children.length===3 && document.querySelector('#workspace').getAttribute('aria-busy')==='false'")
            assert page.locator("#source").inner_text().strip().startswith("Здесь появится")
            assert page.locator("#workspace").get_attribute("aria-busy") == "false"
            assert "недоступен" not in page.locator("#message").inner_text()
            assert "error" not in (page.locator("#message").get_attribute("class") or "").split()
            page.locator("#prepare").focus()
            assert page.locator("#prepare").evaluate("e => e === document.activeElement")
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("() => document.documentElement.scrollWidth <= innerWidth")
            page.set_viewport_size({"width": 1440, "height": 1100})
            page.locator('button[data-version="D"]').click()
            page.wait_for_function(
                "() => document.querySelector('#proposed').dataset.version==='D' && !document.querySelector('#prepare').disabled",
                timeout=180000,
            )
            assert page.locator("#running").get_attribute("data-version") == "B"
            d = actual("D")
            page.screenshot(path=str(output / "repair.png"), full_page=True)
            screenshots.append("repair.png")
            assert (
                d["status"] == "PASS"
                and d["consumers"]["Reporting"]["actual_count"] == 250
            )
            page.locator('button[data-version="E"]').click()
            page.wait_for_function(
                "() => document.querySelector('#proposed').dataset.version==='E' && !document.querySelector('#prepare').disabled",
                timeout=180000,
            )
            assert page.locator("#edges button").count() == 4
            export = page.locator("#edges button").filter(has_text="Export → Orders")
            export.focus()
            page.keyboard.press("Enter")
            page.wait_for_function(
                "() => document.querySelector('#evidence-meta').textContent.includes('export / client.py')"
            )
            e = actual("E")
            assert e["status"] == "PASS" and e["consumers"]["Export"]["passed"]
            page.locator("#history button").filter(has_text="Анализ B").click()
            page.wait_for_function(
                "() => document.querySelector('#freshness').textContent.includes('Исторический')"
            )
            assert "Reporting: возможна потеря" in page.locator("#impact").inner_text()
            assert "Export" not in page.locator("#graph-drawing").text_content()
            page.get_by_role("button", name="Вернуться к текущему результату").click()
            page.wait_for_function(
                "() => !document.querySelector('#freshness').textContent.includes('Исторический')"
            )
            page.locator("#edges button").filter(has_text="Export → Orders").click()
            page.wait_for_function(
                "() => document.querySelector('#evidence-meta').textContent.includes('export / client.py')"
            )
            for width, height, label in [
                (1440, 1100, "desktop-E"),
                (390, 844, "mobile-E"),
            ]:
                page.set_viewport_size({"width": width, "height": height})
                page.screenshot(path=str(output / (label + ".png")), full_page=True)
                assert page.evaluate(
                    "() => document.documentElement.scrollWidth <= window.innerWidth"
                )
                screenshots.append(label + ".png")
            # Both responses come from the real API; inject only a delay to force reverse arrival.
            page.evaluate("""() => {
                window.__realDemoApi = api;
                window.__delayNextEvidence = true;
                api = async function(path, body) {
                    const delay = path.includes('/evidence/') && window.__delayNextEvidence;
                    if (delay) window.__delayNextEvidence = false;
                    const result = await window.__realDemoApi(path, body);
                    if (delay) await new Promise(resolve => setTimeout(resolve, 600));
                    return result;
                };
            }""")
            page.locator("#edges button").filter(has_text="Export → Orders").click()
            page.locator("#edges button").filter(has_text="Billing → Orders").click()
            page.wait_for_function(
                "() => document.querySelector('#evidence-meta').textContent.includes('billing / client.py')"
            )
            page.wait_for_timeout(750)
            assert "billing / client.py" in page.locator("#evidence-meta").inner_text()
            assert (
                page.locator("#edges button[aria-pressed=true]")
                .inner_text()
                .startswith("Billing")
            )
            assert page.evaluate("() => document.activeElement.id") == "evidence-title"
            assert page.locator("#evidence-title").bounding_box()["y"] < 100
            page.evaluate(
                "() => { api = window.__realDemoApi; delete window.__realDemoApi; }"
            )
            page.evaluate(
                "() => showEvidence('ffffffffffffffffffffffffffffffff').catch(() => {})"
            )
            assert page.locator("#evidence-meta").inner_text() == "Основание недоступно"
            assert "requests.get" not in page.locator("#source").inner_text()
            assert page.locator("#correct").is_disabled()
            # Explicit synthetic fixture checks HTML escaping. It is not a model response or graph success.
            fixture = dict(
                repository="explicit-ui-test-fixture",
                path="escape.txt",
                start_line=1,
                end_line=1,
                scenario_version="TEST",
                context_id="TEST",
                basis="TEST",
                revision="TEST",
                sha256="TEST",
                quote='<img src=x onerror="window.__source_executed=true"><script>window.__source_executed=true</script>',
            )
            eid = store.artifact(sid, "evidence", fixture)
            page.evaluate("(id)=>showEvidence(id)", eid)
            assert "<script>" in page.locator("#source").inner_text()
            assert page.locator("#source img, #source script").count() == 0
            assert page.evaluate("() => window.__source_executed") is None
            page.reload()
            page.wait_for_function(
                "() => document.querySelector('#proposed').dataset.version==='E' && document.querySelector('#edges').children.length===4 && document.querySelector('#workspace').getAttribute('aria-busy')==='false'"
            )
            assert page.locator("#sessions").input_value() == sid
            assert page.locator("#history button").filter(has_text="Анализ B").count() == 1
            assert "Исторический" not in page.locator("#freshness").inner_text()
            # Explicit persisted-state fixtures exercise the real API/UI; they are not new discoveries.
            saved_session = store.session(sid)
            saved_graph = store.get_artifact(sid, saved_session["graph_ref"], "graph")
            for name, graph_fixture in (
                ("profile-stale", {**saved_graph, "profile": "author-previous-profile"}),
                ("partial-source", {**saved_graph, "coverage": "PARTIAL",
                                    "gaps": [{"code": "repository_unavailable", "repository": "reporting"}]}),
            ):
                fixture_ref = store.artifact(sid, "graph", graph_fixture)
                with store.transaction() as db:
                    store.put_session(db, {**saved_session, "graph_ref": fixture_ref})
                try:
                    page.reload()
                    page.wait_for_function("() => document.querySelector('#edges').children.length===4 && document.querySelector('#workspace').getAttribute('aria-busy')==='false'")
                    if name == "profile-stale":
                        assert "Изменился профиль анализа" in page.locator("#freshness").inner_text()
                        assert "прежнего профиля" in page.locator("#impact").inner_text()
                        page.locator("#edges button").filter(has_text="Export → Orders").click()
                        page.wait_for_function("() => document.querySelector('#evidence-meta').textContent.includes('export / client.py')")
                        assert page.locator("#correct").is_disabled()
                    else:
                        assert page.locator("#coverage").inner_text().startswith("Неполные данные")
                        assert "repository_unavailable" in page.locator("#gaps").text_content()
                        assert "Неполные исходники" in page.locator("#next-action").inner_text()
                    page.screenshot(path=str(output / (name + ".png")), full_page=True)
                    screenshots.append(name + ".png")
                finally:
                    with store.transaction() as db:
                        store.put_session(db, saved_session)
            assert not errors, errors
            guard.stop(sid, guard.read()["generation"])
            assert not guard.inventory()
            context.close()
            return {
                "status": "PASS",
                "session_id": sid,
                "scenarios": observations,
                "screenshots": screenshots,
                "checks": [
                    "real CLI discovery",
                    "real Docker HTTP A/B/D/E",
                    "Status negative control",
                    "proposed/running separation",
                    "history reopened",
                    "page reload restores saved E and B history",
                    "graph failure clears old evidence and findings",
                    "graph retry restores current result and clears error",
                    "old profile and PARTIAL shown using explicit persisted-state UI fixtures",
                    "keyboard edge selection",
                    "context change clears SVG selection",
                    "reverse evidence response arrival (real API, injected client delay)",
                    "mobile edge selection focuses visible evidence",
                    "390px overflow",
                    "explicit fixture source escaping",
                    "anonymous 401",
                ],
                "observed_at": now(),
            }
        finally:
            browser.close()
