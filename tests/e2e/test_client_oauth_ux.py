"""Client-side Week 7 Playwright test - OAuth login UX and navbar/logout flow.

The real GitHub token exchange is not exercised here. The test clicks the real
GitHub sign-in link, accepts either the external GitHub redirect or the
TESTING-mode not-configured fallback, then uses /test/login/<username> to stand
in for the post-OAuth authenticated session.
"""

from playwright.sync_api import Page, expect


def test_client_github_login_button_backdoor_session_and_logout(page: Page, live_server):
    """Client flow: GitHub button, test login, navbar text, logout redirect."""
    page.goto(f"{live_server.url}/login")

    github_button = page.get_by_role("link", name="Sign in with GitHub")
    expect(github_button).to_be_visible()

    github_button.click()
    page.wait_for_load_state("domcontentloaded")

    assert (
        page.url.startswith("https://github.com/")
        or page.url == f"{live_server.url}/login"
    )

    if page.url == f"{live_server.url}/login":
        expect(page.get_by_text("GitHub sign-in is not configured.")).to_be_visible()

    page.goto(f"{live_server.url}/test/login/LiamCase")
    expect(page).to_have_url(f"{live_server.url}/saved-trails")
    expect(page.get_by_text("Logged in as LiamCase")).to_be_visible()

    page.get_by_role("button", name="Logout").click()
    expect(page).to_have_url(f"{live_server.url}/login")
    expect(page.get_by_role("link", name="Sign in with GitHub")).to_be_visible()
