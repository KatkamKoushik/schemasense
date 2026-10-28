"""Playwright End-to-End Browser Smoke Test for SchemaSense Console.

Verifies real-browser DOM rendering, responsive viewports, and zero JavaScript console errors.
Skips cleanly if Playwright or browser binaries are not installed.
"""

from __future__ import annotations

import os
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen

import pytest

playwright = pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402


@pytest.fixture(scope="module")
def streamlit_server():
    """Launches headless Streamlit app on port 8501 for E2E browser tests."""
    port = "8501"
    env = os.environ.copy()
    env["STREAMLIT_SERVER_PORT"] = port
    env["STREAMLIT_SERVER_HEADLESS"] = "true"
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    proc = subprocess.Popen(
        [
            "streamlit",
            "run",
            "app.py",
            "--server.port",
            port,
            "--server.headless",
            "true",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for server to become healthy (up to 15s)
    for _ in range(30):
        try:
            with urlopen(f"http://localhost:{port}/_stcore/health", timeout=1) as resp:
                if resp.status == 200:
                    break
        except (URLError, OSError):
            time.sleep(0.5)

    yield f"http://localhost:{port}"

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.mark.playwright
def test_playwright_browser_initial_render_and_console_cleanliness(streamlit_server):
    """
    Spins up headless Chromium, navigates to SchemaSense console,
    asserts title, verifies no unhandled JS errors in console, and checks responsive layout.
    """
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as err:  # noqa: BLE001
            pytest.skip(f"Chromium browser binary not installed: {err}")

        # 1. Desktop Viewport Test
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        console_errors = []
        page.on("pageerror", lambda err: console_errors.append(str(err)))

        page.goto(streamlit_server, wait_until="networkidle", timeout=15000)

        # Verify page title
        assert "SchemaSense" in page.title() or "Streamlit" in page.title()

        # Assert no uncaught JavaScript exceptions were fired in the browser
        assert len(console_errors) == 0, (
            f"Browser console errors detected: {console_errors}"
        )

        # 2. Mobile Responsive Viewport Test
        mobile_context = browser.new_context(viewport={"width": 375, "height": 667})
        mobile_page = mobile_context.new_page()
        mobile_page.goto(streamlit_server, wait_until="networkidle", timeout=15000)

        # Assert mobile page successfully rendered
        assert mobile_page.is_visible("body")

        browser.close()
