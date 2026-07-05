"""Pillar 1 (end-to-end UI): the Brain Explorer renders and isolates in a real browser.

Guarded: skipped unless Playwright and a browser are installed, so it never breaks
CI or a normal run. Locally: `pip install playwright && playwright install chromium`.
"""

from __future__ import annotations

import functools
import http.server
import importlib.util
import pathlib
import threading

import pytest

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import sync_playwright  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
UI = REPO_ROOT / "ui"

FINSERV = "finserv-ai-engineering"
RECRUIT = "enterprise-ai-recruitment"


@pytest.fixture(scope="module")
def ui_server():
    # Export the data the SPA reads, then serve ui/ on an ephemeral port.
    spec = importlib.util.spec_from_file_location(
        "export_ui_data", REPO_ROOT / "scripts" / "export_ui_data.py"
    )
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    exporter.export(
        str(REPO_ROOT / ".brain" / "index.json"), "corpus", "personal", str(UI / "data")
    )

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(UI))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}/index.html"
    httpd.shutdown()


def test_explorer_renders_and_isolation_follows_identity(ui_server):
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
    except Exception as exc:  # noqa: BLE001 - no browser binary available
        pytest.skip(f"no browser available: {exc}")

    try:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        console_errors: list[str] = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        page.goto(ui_server)
        # Connections is the default page; switch to Explore for the graph + browser.
        page.click('#pagetabs button[data-page="explore"]')
        page.wait_for_selector("canvas#graph", timeout=8000)
        page.wait_for_selector("#browser .domgroup", timeout=8000)

        # Admin sees both domains (the graph is a canvas, so isolation is observed
        # through the domain browser and the visible-document count).
        page.select_option("#principal", "group:brain-admins@example.com")
        page.wait_for_timeout(300)
        assert page.locator("#browser .domgroup").count() == 2
        admin_docs = int(page.locator("#visN").inner_text())

        # Switching to a single-domain identity shrinks the visible sub-graph.
        page.select_option("#principal", "group:finserv-eng@example.com")
        page.wait_for_timeout(300)
        assert page.locator("#browser .domgroup").count() == 1
        fin_docs = int(page.locator("#visN").inner_text())
        assert fin_docs < admin_docs

        # A recruitment query as the finserv caller never surfaces recruitment.
        page.fill("#query", "candidate sourcing interview copilots hiring bias")
        page.wait_for_timeout(300)
        for meta in page.locator("#results .hit .meta").all_inner_texts():
            assert RECRUIT not in meta
            assert FINSERV in meta

        assert not console_errors, console_errors
    finally:
        browser.close()
        pw.stop()
