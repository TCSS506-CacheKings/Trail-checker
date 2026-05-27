"""Server-side Week 7 Playwright test — OAuth post-login session via test backdoor.

The real GitHub redirect is not exercised here; /test/login/<username> stands
in for a successful OAuth callback per CONTRACTS.md §7a.6 and the assignment
test-login backdoor pattern.
"""

from playwright.sync_api import Page, expect


def test_backdoor_login_shows_logged_in_username(page: Page, live_server):
  """Happy-path: protected page, backdoor login, navbar contract text."""
  page.goto(f"{live_server.url}/saved-trails")
  expect(page).to_have_url(f"{live_server.url}/login?next=%2Fsaved-trails")

  page.goto(f"{live_server.url}/test/login/alice")
  expect(page).to_have_url(f"{live_server.url}/saved-trails")
  expect(page.get_by_text("Logged in as alice")).to_be_visible()
