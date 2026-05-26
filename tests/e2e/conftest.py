"""Pytest plumbing for end-to-end (Playwright) tests.

Sets TESTING and a file-backed SQLite DATABASE_URL BEFORE app.py is
imported. The file path is intentionally a per-pytest-session tempfile
so:

- The running app server and the test process can share the same DB
  (in-memory SQLite is per-connection and would not work here).
- Two test runs (xdist workers, two devs on a shared box, CI matrix
  workers) cannot collide on the same /tmp filename.
- The file lives outside the repo and is cleaned up at session end,
  so nothing leaks back into git.

Compare with tests/conftest.py which uses in-memory SQLite — that is
correct for unit/integration tests that go through Flask's test client
in-process, but it cannot be reached by a separately-launched server
process.
"""

import os
import sys
import tempfile
import uuid
from pathlib import Path


_E2E_DB_PATH = (
    Path(tempfile.gettempdir()) / f"trail_checker_e2e_{uuid.uuid4().hex}.db"
)

os.environ.setdefault("TESTING", "1")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_E2E_DB_PATH}")
os.environ.setdefault("SECRET_KEY", "test-secret-e2e")

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ),
)


def pytest_sessionstart(session):
    """Start every e2e session from a clean DB on disk."""
    if _E2E_DB_PATH.exists():
        _E2E_DB_PATH.unlink()
    _E2E_DB_PATH.touch(mode=0o600, exist_ok=True)


def pytest_sessionfinish(session, exitstatus):
    """Remove the tempfile DB so /tmp does not accumulate test artifacts."""
    try:
        if _E2E_DB_PATH.exists():
            _E2E_DB_PATH.unlink()
    except OSError:
        pass
