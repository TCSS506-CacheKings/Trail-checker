"""Playwright e2e: protected-page accessibility across the login lifecycle.

Owner: Nick (DB-and-security slice).

Verifies that /saved-trails is:
  1. Inaccessible while anonymous (redirected to /login, no protected DOM)
  2. Accessible after login (renders saved-trails-specific DOM)
  3. Inaccessible again after logout (redirected back to /login)

All assertions go through the rendered DOM via Playwright's `expect`,
which is what the Week 7 grading criterion calls for. Uses the password
auth path (not OAuth) so the test does not depend on Ryan's Authlib
wiring — keeping Nick's slice deterministic in CI.

The companion conftest (tests/e2e/conftest.py) sets TESTING=1,
DATABASE_URL to a per-session tempfile SQLite, and SECRET_KEY before
this module is imported. The live_server fixture below launches the
Flask app in a subprocess that inherits those env vars.
"""

import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
from playwright.sync_api import Page, expect


HOST = "127.0.0.1"


def _pick_free_port(host: str) -> int:
    """Ask the OS for an unused TCP port on the given host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def _wait_for_server(base_url: str, proc: subprocess.Popen, timeout: float = 15.0) -> None:
    """Wait until our subprocess is serving HTTP, not just until a port is open.

    A bare port check is not enough: if some *other* server is already on
    the port (e.g., a docker compose stack), `socket.connect` succeeds
    immediately and the test hits the wrong app. So we also poll an HTTP
    endpoint to confirm the response came from a healthy Flask process,
    and surface subprocess failure if it died during boot.
    """
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"Flask subprocess exited with code {proc.returncode} during boot."
            )
        try:
            with urllib.request.urlopen(f"{base_url}/login", timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(
        f"Server at {base_url} did not become ready within {timeout}s "
        f"(last error: {last_error!r})"
    )


@pytest.fixture(scope="session")
def live_server():
    """Boot Flask in a subprocess so Playwright can drive a real browser.

    Binds to a *random free port on 127.0.0.1* so the e2e suite never
    collides with a `docker compose up` stack on :5000, and so concurrent
    pytest workers do not fight over the same port.
    """
    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    port = _pick_free_port(HOST)
    base_url = f"http://{HOST}:{port}"

    runner = (
        "from app import app; "
        f"app.run(host='{HOST}', port={port}, debug=False, use_reloader=False)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", runner],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_server(base_url, proc)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_saved_trails_protected_then_accessible_then_protected_again(
    page: Page, live_server: str
) -> None:
    """The protected page must be DOM-inaccessible → accessible → inaccessible."""
    base = live_server

    # ---------------------------------------------------------------------
    # Phase 1 — Anonymous: protected DOM must NOT render
    # ---------------------------------------------------------------------
    page.goto(f"{base}/saved-trails")

    # Flask-Login redirects to /login?next=%2Fsaved-trails. The user-facing
    # signal of the redirect is the login form, so assert on DOM not URL.
    expect(page.locator("form[action$='/login']")).to_be_visible()
    expect(page.locator("input[name='username']")).to_be_visible()
    expect(page.locator("input[name='password']")).to_be_visible()

    # The protected page's signature heading must not appear anywhere in
    # the anonymous response. This is what proves *no leak*, not just
    # *redirected*.
    expect(page.get_by_text("Your saved locations")).to_have_count(0)

    # ---------------------------------------------------------------------
    # Phase 2 — Register a fresh user via the live UI, then visit /saved-trails
    # ---------------------------------------------------------------------
    page.goto(f"{base}/register")
    page.fill("input[name='username']", "e2e-protected")
    page.fill("input[name='password']", "password123")
    # Wrap the click in expect_navigation so we wait for the POST /register
    # → 302 → / round-trip to fully complete and the session cookie to be
    # persisted before issuing the next goto. Without this, the next goto
    # can interrupt the in-flight redirect and the session is lost.
    with page.expect_navigation():
        page.click("button[type='submit']")

    page.goto(f"{base}/saved-trails")

    expect(page).to_have_url(f"{base}/saved-trails")
    expect(page.get_by_text("Your saved locations")).to_be_visible()

    # Navbar shows the authenticated username. Asserting on the username
    # substring rather than a wrapper phrase keeps this test passing both
    # under the current "Hello, <username>" rendering and under the
    # §7a.12 contract text "Logged in as <username>" once Liam updates
    # templates/base.html.
    expect(page.locator("nav")).to_contain_text("e2e-protected")

    # The logout control must be present in the navbar — required for
    # Phase 3 to even be possible. We target the form's submit button by
    # its enclosing form's action attribute so the test stays stable if
    # Liam ever changes the button label.
    logout_button = page.locator("nav form[action$='/logout'] button[type='submit']")
    expect(logout_button).to_be_visible()

    # ---------------------------------------------------------------------
    # Phase 3 — Log out via the navbar POST form
    # ---------------------------------------------------------------------
    # click(force=True) skips Playwright's "receives events" actionability
    # check, which spuriously fails on Bootstrap's `.btn-link.nav-link`
    # combo in headless Chromium (the surrounding nav-link padding
    # overlaps the button's hit area). The button is fully visible and
    # enabled — confirmed by to_be_visible() above — so forcing the click
    # is safe and does not weaken the test. expect_navigation() then waits
    # for POST /logout → 302 → / so the session cookie is cleared before
    # Phase 4 navigates again.
    with page.expect_navigation():
        logout_button.click(force=True)

    # ---------------------------------------------------------------------
    # Phase 4 — Protected DOM must NOT render again
    # ---------------------------------------------------------------------
    page.goto(f"{base}/saved-trails")

    expect(page.locator("form[action$='/login']")).to_be_visible()
    expect(page.get_by_text("Your saved locations")).to_have_count(0)
    expect(page.locator("nav")).not_to_contain_text("e2e-protected")
