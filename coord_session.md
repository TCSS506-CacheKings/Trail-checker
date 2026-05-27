# Week 6 Coordinator / Planning Session

Team: Cache Kings  
Project: Trail Checker  
Repo: https://github.com/TCSS506-CacheKings/Trail-checker

## Participants

- Liam Sipp  Client-side
- Ryan Belmonte  Server-side
- Nick Stjern  DB-and-security

## Context

Our team is using a three-person structure, so we do not have a separate coordinator role. We are sharing the coordinator responsibilities across the three roles.

We started by getting the Week 5 Flask/Postgres skeleton into the team repo, enabling the JavaScript submit-button fix, confirming the repo settings, and turning on branch protection / CI rules. After that, we moved into the Week 6 contract step.

## Questions we needed to answer

1. What should the Trail Checker MVP actually do for Week 6?
2. Which external API should we use?
3. What routes does the app need?
4. What data should be stored in Postgres?
5. What does each role own?
6. What tests need to exist before implementation starts?

## Decisions made

### Project scope

We agreed to keep the MVP small and realistic for Week 6.

The app will let a user search for a trailhead or outdoor location, check current weather and air quality, and display a simple trail-readiness recommendation.

Logged-in users can save locations, view saved locations, re-check them, and delete them.

### External API

We chose OpenWeather as the primary external API because it supports:

- Geocoding a location name into coordinates
- Current weather by latitude and longitude
- Air pollution / AQI by latitude and longitude

This keeps the external API integration realistic while avoiding a larger trail database integration for Week 6.

### Role ownership

Ryan owns server-side work:

- Flask routes
- OpenWeather API calls
- Request/response behavior
- API error handling

Liam owns client-side work:

- Templates
- Bootstrap layout
- Forms
- Navigation links
- Stable selectors for client-side tests

Nick owns DB-and-security work:

- SQLModel schema
- Flask-Login refactor
- Ownership rules
- Login-required behavior
- Secret hygiene

### Testing setup

We realized that listing the tests inside CONTRACTS.md is not enough. The Week 6 test files need to actually exist under the `tests/` folder.

We decided to add these files before role implementation:

- `tests/test_server_conditions.py`
- `tests/test_db_security.py`
- `tests/test_client_templates.py`
- `tests/test_integration.py`

These tests are expected to fail at first because the app has not implemented the Trail Checker features yet.

## Pushback / revisions

We intentionally avoided making the MVP too large.

Things we decided not to include in Week 6:

- Full trail database
- Official trail closure status
- Map UI
- Autocomplete
- Background refresh
- OAuth
- Public sharing of saved trails

We also discussed that the README/About/CONTRACTS files need to stay aligned so the project does not describe two different MVPs.

## Next step

The next setup step is to add the four Week 6 test files under `tests/`. After those files are committed in this branch, the team can review this setup PR before individual role implementation starts.

## DB-and-security slice (Nick)  implementation notes

The slice landed in `app.py`, `requirements.txt`, the existing auth templates, and `tests/test_db_security.py`. Key changes:

- Flask-Login replaces raw `session["user_id"]`. The session cookie now carries `_user_id` and `_fresh`.
- New SQLModel models `SavedTrail` and `TrailCheck` are defined with database-level constraints (`NOT NULL`, FK with `ondelete="CASCADE"` on `saved_trails`, FK with `ondelete="SET NULL"` on `trail_checks`, and composite `UniqueConstraint(user_id, latitude, longitude)`).
- `@login_required` guards `/saved-trails`, `POST /saved-trails`, `POST /saved-trails/<id>/delete`, and `GET /saved-trails/<id>/check`.
- Ownership lookups always filter by `id AND user_id`, returning `404` (not `403`) when the row does not exist or belongs to another user.
- CSRF protection via Flask-WTF is enabled on every state-changing route. A custom `CSRFError` handler redirects anonymous CSRF failures to `/login`.
- Cookie flags `HTTPONLY`, `SAMESITE=Lax`, and `SECURE=not debug` are set for both session and remember-me cookies.
- A startup check refuses to boot with the default `SECRET_KEY` outside of debug/testing.
- Login is rate-limited to 10 POSTs per minute per IP via Flask-Limiter.
- `register` enforces a password policy of 8-128 characters with at least one letter and one digit.
- `login` runs `check_password_hash` against a dummy hash when the username does not exist, removing the username-enumeration timing oracle.
- An `audit` logger emits structured events for register, login success/failure, logout, and saved-trail create/delete/denied actions.

### Coordination items for the other roles

- Liam: template work remains  `templates/trail_checker.html`, `templates/trail_results.html`, and `templates/saved_trails.html` are not yet present. Every POST form Liam adds must include `{{ csrf_token() }}` (see the existing `login.html`, `register.html`, and the navbar logout form in `base.html` for reference).
- Liam: when `saved_trails.html` is added, render the `prior_input` template variable to repopulate the form after a validation error.
- Ryan: `check_saved_trail` currently renders the saved trail data with `recommendation="unknown"`. Wire it to the live OpenWeather fetch when the server-side slice lands.
- Ryan: `/api/conditions` JSON envelope and `trail_checks` insertion remain in the server-side slice. The `TrailCheck` model and its schema are ready.

### Known follow-ups not in scope for Week 6

- Migrate from `SQLModel.metadata.create_all` to Alembic so schema changes do not require `docker compose down -v`.
- Move password hashing from werkzeug's PBKDF2 default to Argon2 via `argon2-cffi`.
- Add Content Security Policy, X-Frame-Options, and X-Content-Type-Options headers (e.g. Flask-Talisman).
- HSTS once HTTPS is enforced in front of the app.
- Pwned Passwords API check during register.
- Persistent rate-limit storage (Redis) and IP-based abuse detection.

## Week 7 DB-and-security slice (Nick)  implementation notes

Slice landed across `app.py`, `requirements.txt`, `.env.example`, `tests/test_db_security.py`, `tests/test_auth.py`, and new `tests/e2e/conftest.py`. Reference CONTRACTS.md 7a for the authoritative contract.

### What changed in code

- **N6** `python-dotenv` added to `requirements.txt`. `app.py` calls `load_dotenv()` before any `os.environ` read so bare-metal `flask run` / `pytest` see the same env as Docker Compose. `.env.example` rewritten to list every required variable including the new `GITHUB_OAUTH_CLIENT_ID` and `GITHUB_OAUTH_CLIENT_SECRET`.
- **N1** New `OAuthIdentity` SQLModel with `UNIQUE(provider, provider_user_id)`, `ON DELETE CASCADE` on `user_id`, `index=True` on `user_id` (for fast reverse lookups and fast CASCADE), `CheckConstraint("provider IN ('github')")` to block case-variant duplicates, and `CheckConstraint("length(provider_user_id) > 0")`.
- **N2** `User.password_hash` is now `nullable=True` (typed `str | None`). The login route rejects `password_hash IS NULL` users without crashing and still runs the dummy hash to keep response timing constant.
- **N3** Enforced by N1's unique constraint + the lack of any email-based linking column. No code beyond the schema; the policy lives in CONTRACTS.md 7a.2.
- **N4** Added `PERMANENT_SESSION_LIFETIME = timedelta(hours=12)` and `REMEMBER_COOKIE_DURATION = timedelta(days=30)` to `app.config`. Set `login_manager.session_protection = "strong"`. `session.permanent = True` is set after every `login_user(...)` so the 12h lifetime actually applies. Login route now reads the `remember` form field.
- **N5** No new exempt routes. Verified by `git grep 'method="post"'` vs `git grep csrf_token()` in templates.
- **N7** New `tests/e2e/conftest.py` uses a per-pytest-session tempfile SQLite path (`tempfile.gettempdir() + uuid4().hex + ".db"`, chmod 0600) so concurrent runs cannot collide and `/tmp` is not used as a shared world-readable surface. `pytest_sessionfinish` cleans up.

### Coordination items for Ryan

- The `OAuthIdentity` model is importable as `from app import OAuthIdentity`. Use `(provider="github", provider_user_id=str(github_user_id))`  the CHECK constraint will reject any other case or empty value.
- Callback **must** use a single transaction for the lookup-or-create flow and handle `IntegrityError` on the unique constraint as "concurrent callback won the race" (re-SELECT). See CONTRACTS.md 7a.3.
- Callback **must** use Authlib's built-in `state` validation. See 7a.4.
- Callback **must** be rate-limited at the same rate as `/login` (`10 per minute`). See 7a.5.
- `/test/login/<username>` backdoor must have three independent gates (TESTING + (debug OR localhost host) + 404-on-failure). See 7a.6.
- OAuth login: always call `login_user(user, remember=True)` followed by `session.permanent = True`.

### Coordination items for Liam

- Login form should add a `<input type="checkbox" name="remember">` and label. The login route reads `request.form.get("remember")`; any truthy value (e.g. `"on"`) triggers `remember=True`.
- No template change is needed for OAuth's "Sign in with GitHub" button beyond `<a href="{{ url_for('login_github') }}">` once Ryan's route exists.

### Operational note for the first Week 7 deploy

Making `users.password_hash` nullable is a destructive schema change for an existing Postgres database under `SQLModel.metadata.create_all`. First deploy requires:

```bash
docker compose down -v
docker compose up -d --build
```

SQLite test runs are unaffected (fresh DB per run). This requirement is also captured in CONTRACTS.md 7a.11.

### Week 7 known follow-ups not in scope

- Persist audit log to a `security_events` table or a mounted file (currently stdout-only, recycled on container restart).
- Session invalidation on password change (Flask-Login does not handle this out of the box; needs a `session_version` field on `User` or `SECRET_KEY` rotation).
- Pre-commit hook to scan `.env.example` for accidentally-real secret values.
- Postgres `sslmode=require` once the DB ever moves off the in-Compose network.
- Account-deletion UI (CASCADE handles the data side, but no user-facing flow exists).

### Week 7 Playwright e2e (Nick)  implementation notes

The DB-and-security Playwright slice lives at `tests/e2e/test_protected_routes.py`. It is the lifecycle test required by the Week 7 grading rubric: protected page inaccessible ? accessible after login ? inaccessible again after logout, all verified through the rendered DOM via `page.expect(...)`.

Key design choices:

- **Password auth, not OAuth.** The test uses `/register` + `/login`, not the GitHub flow, so it does not depend on Ryan's Authlib slice. Ryan's own Playwright test covers the OAuth happy path.
- **Inline subprocess runner.** The `live_server` fixture launches Flask via `python -c "from app import app; app.run(host='127.0.0.1', ...)"` rather than `python app.py`. This pins the test server to `127.0.0.1` instead of `0.0.0.0`, so other processes on a shared CI runner cannot reach it.
- **Random ephemeral port.** The fixture binds to a free port returned by `socket.bind((host, 0))` instead of a hardcoded `:5000`, so a stale `docker compose up` stack on `:5000` cannot capture the test traffic (this bit me once during development  the test silently hit the Postgres-backed container, where CSRF is enabled, and registration failed without the test noticing).
- **HTTP-level readiness probe.** `_wait_for_server` polls `GET /login` (not just a TCP port open), so we only proceed once *our* Flask is actually serving requests, not just once the OS handed out the socket.
- **Force-overwrite of DATABASE_URL in tests/e2e/conftest.py.** `tests/conftest.py` hard-assigns `sqlite:///:memory:` for unit tests; the e2e conftest must use plain `os.environ[...] = ...` (not `setdefault`) or the subprocess boots against `:memory:`, where every connection sees an empty schema and `/register` blows up with `no such table: users`.
- **`expect_navigation()` around form submits.** Both the register and the logout clicks are wrapped so the test waits for `POST ? 302 ? GET` to fully complete before the next assertion. Without this, a follow-up `page.goto` can race the in-flight redirect and discard the session cookie.
- **`force=True` on the logout click.** Playwright's "receives events" actionability check spuriously fails on Bootstrap's `.btn-link.nav-link` combo in headless Chromium (the surrounding nav-link padding overlaps the button's hit area). The button is asserted visible immediately before the click, so forcing the click is safe and does not weaken the test.
- **Substring username assertion.** The test asserts `nav` contains `e2e-protected`, not the full `Logged in as e2e-protected` string. This passes both under today's `Hello, <username>` template and after Liam updates `templates/base.html` to the 7a.12 contract  keeping Nick's test decoupled from Liam's merge order.
- **No-leak assertion.** Each anonymous phase asserts that the protected heading (`Your saved locations`) has count `0`. This proves no protected DOM bleeds into the response, which is stronger than asserting the URL alone.

Dev dependencies (`playwright`, `pytest-playwright`) live in `requirements-dev.txt`, separate from production requirements, so the prod Docker image does not ship browser binaries. README.md has the install/run instructions for both bare-metal and Docker.

### Coordination items for the other Playwright authors

- **Liam** owns the navbar template update from `Hello, ` ? `Logged in as ` (7a.12). Until that lands, Ryan's "exact text" assertion will fail. Nick's test is decoupled from this.
- **Liam** owns pinning the post-login landing page (suggested: `/saved-trails`). Nick's test navigates explicitly, so this does not affect Nick.
- **Coordinator** owns the `/test/login/<username>` backdoor. Recommended shape: GET, three gates per 7a.6, calls `login_user(user); session.permanent = True`, redirects to whatever Liam pins as the post-login landing page.
