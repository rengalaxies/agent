"""Real browser smoke test of the synthetic loopback pilot, no real credentials."""
import argparse
import json
from pathlib import Path
from threading import Thread
from playwright.sync_api import sync_playwright
from services.evidence_pilot import create_server

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
server = create_server(args.output / 'state')
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={'width': 1180, 'height': 1000})
        page.goto('http://127.0.0.1:' + str(server.server_port))
        page.wait_for_function('document.querySelector("#state").textContent.includes("NEEDS_REVIEW")')
        page.locator('[data-action="approve"]').click()
        page.wait_for_function('JSON.parse(document.querySelector("#state").textContent).current_evidence_decision === "ACCEPT"')
        page.locator('[data-action="authorize"]').click()
        page.wait_for_function('JSON.parse(document.querySelector("#state").textContent).last_decision?.terminal_state === "COMMITTED"')
        page.locator('[data-action="restart"]').click()
        page.wait_for_function('JSON.parse(document.querySelector("#state").textContent).historical_authorizations === 1')
        page.locator('[data-action="revoke"]').click()
        page.wait_for_function('JSON.parse(document.querySelector("#state").textContent).current_evidence_decision === "NEEDS_REVIEW"')
        page.locator('[data-action="authorize"]').click()
        page.wait_for_function('JSON.parse(document.querySelector("#state").textContent).last_decision?.terminal_state === "ESCALATED"')
        final = json.loads(page.locator('#state').inner_text())
        assert final['last_decision']['release_id'] is None
        assert final['historical_authorizations'] == 1
        page.screenshot(path=str(args.output / 'pilot-after-revocation.png'), full_page=True)
        (args.output / 'browser-result.json').write_text(json.dumps(final, indent=2) + '\n')
        browser.close()
    print('Synthetic pilot browser lifecycle: PASS')
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
