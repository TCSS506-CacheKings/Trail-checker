# Trail Checker — CONTRACTS.md

**Team:** Cache Kings
**Project repo:** [https://github.com/TCSS506-CacheKings/Trail-checker](https://github.com/TCSS506-CacheKings/Trail-checker)
**Status:** Draft for team review before implementation
**Team members and roles:**

| Member        | Role            |
| ------------- | --------------- |
| Ryan Belmonte | Server-side     |
| Liam Sipp     | Client-side     |
| Nick Stjern   | DB-and-security |

## 0. Project summary

Trail Checker is a Flask + Postgres web app that helps hikers quickly check whether a trailhead or outdoor location looks reasonable to visit based on current weather and air quality. A user enters a location name, the app resolves it to coordinates, retrieves current weather and air pollution data, and displays a simple trail-readiness summary. Logged-in users can save locations they care about and remove saved locations later.

The Week 6 implementation is intentionally small. We are not building a full hiking map, trail database, or official trail-closure system yet. The goal is a reliable end-to-end slice: browser → Flask routes → Postgres → OpenWeather APIs → rendered condition results.

## 1. Schema

Existing skeleton tables remain unless explicitly changed below.

### users

| Column        | Type     | Constraints / notes                       |
| ------------- | -------- | ----------------------------------------- |
| id            | integer  | Primary key                               |
| username      | string   | Required, unique, indexed                 |
| password_hash | string   | Required; never store plaintext passwords |
| created_at    | datetime | Required; default current UTC timestamp   |

Notes:

* DB-and-security will refactor authentication from direct `session["user_id"]` access to Flask-Login.
* The `users` table may keep the skeleton's original structure if it already satisfies these fields, but it must support Flask-Login's user loading by id.

### saved_trails

| Column       | Type     | Constraints / notes                                                     |
| ------------ | -------- | ----------------------------------------------------------------------- |
| id           | integer  | Primary key                                                             |
| user_id      | integer  | Required foreign key to `users.id`; cascade delete when user is deleted |
| display_name | string   | Required; human-readable location name shown to the user                |
| query_text   | string   | Required; original search text submitted by the user                    |
| latitude     | float    | Required                                                                |
| longitude    | float    | Required                                                                |
| country      | string   | Optional; from geocoding response                                       |
| state        | string   | Optional; from geocoding response when available                        |
| notes        | string   | Optional; user note, max 500 characters                                 |
| created_at   | datetime | Required; default current UTC timestamp                                 |
| updated_at   | datetime | Required; update when notes or display name change                      |

Constraints:

* `user_id` must reference a valid user.
* A user should not be able to create exact duplicate saved trails with the same `user_id`, `latitude`, and `longitude`.
* Deleting a user must delete that user's saved trails.

### trail_checks

| Column              | Type     | Constraints / notes                                                             |
| ------------------- | -------- | ------------------------------------------------------------------------------- |
| id                  | integer  | Primary key                                                                     |
| user_id             | integer  | Optional foreign key to `users.id`; nullable because anonymous users can search |
| query_text          | string   | Required; original search text                                                  |
| resolved_name       | string   | Required; resolved location name from geocoding                                 |
| latitude            | float    | Required                                                                        |
| longitude           | float    | Required                                                                        |
| weather_main        | string   | Required; e.g., Clouds, Rain, Clear                                             |
| weather_description | string   | Required; e.g., light rain                                                      |
| temp_f              | float    | Required; current temperature in Fahrenheit                                     |
| feels_like_f        | float    | Optional                                                                        |
| humidity            | integer  | Optional                                                                        |
| wind_mph            | float    | Optional                                                                        |
| visibility_meters   | integer  | Optional                                                                        |
| aqi                 | integer  | Optional; OpenWeather AQI scale 1-5                                             |
| pm2_5               | float    | Optional                                                                        |
| pm10                | float    | Optional                                                                        |
| recommendation      | string   | Required; one of `good`, `caution`, `poor`, `unknown`                           |
| checked_at          | datetime | Required; default current UTC timestamp                                         |

Notes:

* `trail_checks` is a lightweight audit/history table for searches. It helps the team prove data is persisted, but the UI does not need a full history page in Week 6.
* The app may skip writing a `trail_checks` row if the external API call fails before usable data is returned.

## 2. Endpoint contracts

### Shared response conventions

HTML routes return rendered templates or redirects with flash messages.

JSON API routes use this success envelope:

```json
{
  "ok": true,
  "data": {}
}
```

JSON API routes use this error envelope:

```json
{
  "ok": false,
  "error": {
    "code": "machine_readable_code",
    "message": "Human readable explanation"
  }
}
```

Common error codes:

| Status | Code                       | Meaning                                                         |
| ------ | -------------------------- | --------------------------------------------------------------- |
| 400    | `invalid_input`            | Missing, too short, too long, or malformed user input           |
| 401    | `login_required`           | User must be logged in for this action                          |
| 404    | `not_found`                | Resource does not exist, or does not belong to the current user |
| 502    | `external_api_error`       | OpenWeather returned malformed/unusable data                    |
| 503    | `external_api_unavailable` | Timeout, rate limit, bad API key, or service unavailable        |

### GET `/trail-checker`

**Owner:** Client-side + server-side
**Auth required:** No
**Purpose:** Render the main Trail Checker search page.

Request:

* No required query parameters.

Response:

* `200 OK`
* Renders `templates/trail_checker.html`.
* Page includes:

  * Search form with `method="GET"` and `action="/trail-checker/results"`.
  * Text input named `q`.
  * Submit button.
  * Brief explanation of what data is checked.
  * Link to `/saved-trails` visible in navigation for logged-in users.

Errors:

* None expected for normal rendering.

### GET `/trail-checker/results`

**Owner:** Server-side + client-side
**Auth required:** No
**Purpose:** Resolve a user-entered location and show current trail condition summary.

Request query parameters:

| Name | Required | Validation                       |
| ---- | -------- | -------------------------------- |
| q    | Yes      | Trimmed string, 2-100 characters |

Server behavior:

1. Validate `q`.
2. Call OpenWeather Geocoding API using `q`.
3. Use the first geocoding result unless no results are returned.
4. Call OpenWeather Current Weather API using resolved `lat` and `lon`.
5. Call OpenWeather Air Pollution API using resolved `lat` and `lon`.
6. Compute a simple recommendation:

   * `poor` if AQI is 4 or 5, or wind speed is very high, or weather indicates thunderstorm/extreme conditions.
   * `caution` if AQI is 3, rain/snow is present, visibility is low, or wind is moderately high.
   * `good` if AQI is 1-2 and conditions are mild.
   * `unknown` if weather data exists but recommendation cannot be confidently computed.
7. Persist a `trail_checks` row when usable weather data is returned.
8. Render results page.

Response:

* `200 OK`
* Renders `templates/trail_results.html`.
* Template context includes:

  * `query_text`
  * `resolved_name`
  * `latitude`
  * `longitude`
  * `weather_main`
  * `weather_description`
  * `temp_f`
  * `feels_like_f`
  * `humidity`
  * `wind_mph`
  * `visibility_meters`
  * `aqi`
  * `pm2_5`
  * `pm10`
  * `recommendation`
  * `is_saved` boolean for logged-in users when matching saved trail exists

Client-visible page requirements:

* Show a clear result card.
* Show weather and air quality in separate sections.
* Show the recommendation badge: Good / Use Caution / Poor / Unknown.
* If logged in, show a form/button to save the location.
* If anonymous, show a message that users can log in to save locations.

Errors:

* `400 Bad Request`: invalid `q`; render `trail_checker.html` with error flash and preserve prior input.
* `404 Not Found`: no geocoding results; render `trail_checker.html` with "location not found" flash.
* `503 Service Unavailable`: OpenWeather timeout, rate limit, invalid key, or connection failure; render `trail_checker.html` with external service error flash.
* `502 Bad Gateway`: OpenWeather response is missing expected fields; render `trail_checker.html` with malformed data flash.

### GET `/api/conditions`

**Owner:** Server-side
**Auth required:** No
**Purpose:** JSON endpoint for tests and future frontend enhancement. Returns the same condition data as `/trail-checker/results` without rendering HTML.

Request query parameters:

| Name | Required | Validation                       |
| ---- | -------- | -------------------------------- |
| q    | Yes      | Trimmed string, 2-100 characters |

Success response:

* `200 OK`

```json
{
  "ok": true,
  "data": {
    "query_text": "Mount Rainier",
    "resolved_name": "Mount Rainier",
    "latitude": 46.8523,
    "longitude": -121.7603,
    "weather": {
      "main": "Clouds",
      "description": "overcast clouds",
      "temp_f": 48.2,
      "feels_like_f": 45.1,
      "humidity": 72,
      "wind_mph": 8.3,
      "visibility_meters": 10000
    },
    "air_quality": {
      "aqi": 2,
      "pm2_5": 4.2,
      "pm10": 7.5
    },
    "recommendation": "good"
  }
}
```

Errors:

* Uses shared JSON error envelope.
* `400`, `404`, `502`, and `503` must be handled as described above.

### GET `/saved-trails`

**Owner:** Client-side + DB-and-security
**Auth required:** Yes
**Purpose:** Show the logged-in user's saved trail/location list.

Request:

* No required parameters.

Response:

* `200 OK`
* Renders `templates/saved_trails.html`.
* Template context includes `saved_trails`, ordered newest first.
* Empty state appears when the user has no saved trails.

Errors:

* Anonymous users are redirected to `/login` or receive the skeleton's normal login-required behavior.

### POST `/saved-trails`

**Owner:** Server-side + DB-and-security
**Auth required:** Yes
**Purpose:** Save a location from a result page.

Form fields:

| Name         | Required | Validation                       |
| ------------ | -------- | -------------------------------- |
| display_name | Yes      | 2-100 characters                 |
| query_text   | Yes      | 2-100 characters                 |
| latitude     | Yes      | Valid float between -90 and 90   |
| longitude    | Yes      | Valid float between -180 and 180 |
| country      | No       | Max 10 characters                |
| state        | No       | Max 100 characters               |
| notes        | No       | Max 500 characters               |

Success response:

* `302 Found` redirect to `/saved-trails`.
* Flash message: saved successfully.

Errors:

* `400 Bad Request`: invalid or missing form data; re-render result or saved page with error flash.
* Duplicate saved location for same user: do not create a second row. Redirect to `/saved-trails` with a flash message explaining it was already saved.
* Anonymous user: redirect to `/login`.

### POST `/saved-trails/<trail_id>/delete`

**Owner:** Server-side + DB-and-security
**Auth required:** Yes
**Purpose:** Delete one saved trail belonging to the current user.

Request:

* Path parameter `trail_id` must be an integer.

Success response:

* `302 Found` redirect to `/saved-trails`.
* Flash message: deleted successfully.

Errors:

* `404 Not Found`: saved trail does not exist or belongs to another user.
* Anonymous user: redirect to `/login`.

### GET `/saved-trails/<trail_id>/check`

**Owner:** Server-side + client-side
**Auth required:** Yes
**Purpose:** Re-check current conditions for a saved trail.

Request:

* Path parameter `trail_id` must be an integer and must belong to current user.

Server behavior:

1. Load saved trail by id and current user.
2. Use saved `latitude` and `longitude` directly.
3. Call current weather and air pollution APIs.
4. Render `trail_results.html` using the saved trail's display name and latest live conditions.

Response:

* `200 OK`
* Renders `templates/trail_results.html`.

Errors:

* `404 Not Found`: saved trail does not exist or belongs to another user.
* `502` or `503`: external API failure, shown with flash message.

## 3. External API contract

Primary external provider: OpenWeather.

### API key handling

* Store key in environment variable: `OPENWEATHER_API_KEY`.
* Never hardcode the key in Python, templates, tests, `.env` committed to git, README screenshots, or terminal logs.
* If the key is missing, server routes that need OpenWeather must return `503 external_api_unavailable` with a clear message.

### OpenWeather Geocoding API

Docs: [https://openweathermap.org/api/geocoding-api](https://openweathermap.org/api/geocoding-api)

Endpoint:

```text
GET http://api.openweathermap.org/geo/1.0/direct?q={query}&limit=1&appid={API key}
```

Auth:

* API key required through `appid`.

Inputs:

* `query`: user location input from `q`.
* `limit`: use `1` for MVP to keep behavior deterministic.

Expected response shape:

```json
[
  {
    "name": "Mount Rainier",
    "lat": 46.8523,
    "lon": -121.7603,
    "country": "US",
    "state": "Washington"
  }
]
```

Failure handling:

* Empty array: return `404 not_found`.
* Timeout: return `503 external_api_unavailable`.
* HTTP 401 or invalid key: return `503 external_api_unavailable`.
* HTTP 429/rate limit: return `503 external_api_unavailable`.
* Missing `lat` or `lon`: return `502 external_api_error`.

### OpenWeather Current Weather API

Docs: [https://openweathermap.org/current](https://openweathermap.org/current)

Endpoint:

```text
GET https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={API key}&units=imperial
```

Auth:

* API key required through `appid`.

Expected response fields used:

* `weather[0].main`
* `weather[0].description`
* `main.temp`
* `main.feels_like`
* `main.humidity`
* `wind.speed`
* `visibility`
* `name`

Failure handling:

* Timeout: return `503 external_api_unavailable`.
* HTTP 401 or invalid key: return `503 external_api_unavailable`.
* HTTP 429/rate limit: return `503 external_api_unavailable`.
* Non-200 response: return `503 external_api_unavailable`.
* Missing required fields: return `502 external_api_error`.

### OpenWeather Air Pollution API

Docs: [https://openweathermap.org/api/air-pollution](https://openweathermap.org/api/air-pollution)

Endpoint:

```text
GET http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={API key}
```

Auth:

* API key required through `appid`.

Expected response fields used:

* `list[0].main.aqi`
* `list[0].components.pm2_5`
* `list[0].components.pm10`

Failure handling:

* Timeout: do not fail the entire result if weather data succeeded. Render weather results and set air quality fields to `None` / unknown with a warning flash.
* HTTP 401 or invalid key: same as timeout behavior if weather succeeded.
* HTTP 429/rate limit: same as timeout behavior if weather succeeded.
* Malformed response: same as timeout behavior if weather succeeded.

### Rate limits and free-tier concern

OpenWeather free/self-service access should be enough for Week 6 development and demo usage. The team will avoid polling and will only call the APIs after user-initiated searches or saved-trail rechecks.

Implementation rule:

* No background refresh jobs.
* No automatic repeated requests from JavaScript.
* Each user search may produce up to three external calls: geocoding, current weather, and air pollution.

## 4. Authorization rules

### Anonymous users

Anonymous users may:

* View `/` and existing skeleton public pages.
* View `/trail-checker`.
* Search `/trail-checker/results?q=...`.
* Call `/api/conditions?q=...`.

Anonymous users may not:

* View `/saved-trails`.
* Save a trail.
* Delete a saved trail.
* Re-check a saved trail by id.

### Logged-in users

Logged-in users may:

* Do everything anonymous users can do.
* Save a trail/location from search results.
* View only their own saved trails.
* Delete only their own saved trails.
* Re-check only their own saved trails.

### Ownership restrictions

* A user requesting another user's saved trail must receive `404 Not Found`, not `403 Forbidden`.
* This applies to:

  * `POST /saved-trails/<trail_id>/delete`
  * `GET /saved-trails/<trail_id>/check`
* The app should not reveal whether another user's saved trail id exists.

### Input validation and security

* All location text input must be trimmed and length-limited.
* Notes must be length-limited to 500 characters.
* Latitude and longitude must be parsed as floats and range-checked.
* Jinja templates must rely on default escaping and must not use unsafe `|safe` for user-provided content.
* External API key must stay in environment variables.
* Server-side code must not trust hidden form fields beyond validation.
* Database constraints should back up application-level checks where possible.

## 5. Role boundaries

### Server-side — Ryan

Owns:

* Flask route handlers for new project routes.
* OpenWeather API integration using `requests`.
* External API timeout, status-code, and malformed-response handling.
* Recommendation calculation helper.
* JSON envelope for `/api/conditions`.
* Server-side tests: `tests/test_server_conditions.py`.

Primary files likely touched:

* `app.py`
* Optional helper file such as `weather_service.py` or `trail_service.py` if the team agrees
* `tests/test_server_conditions.py`

Should not own:

* Final visual layout of templates.
* Database constraint design without Nick's review.
* Secret handling rules without Nick's review.

### Client-side — Liam

Owns:

* New templates for Trail Checker pages.
* Bootstrap layout and presentation.
* Navigation links in `templates/base.html`.
* Forms and input names matching server contracts.
* User-visible empty states, error states, and result cards.
* Client-side tests: `tests/test_client_templates.py` using Flask test client + BeautifulSoup.

Primary files likely touched:

* `templates/base.html`
* `templates/trail_checker.html`
* `templates/trail_results.html`
* `templates/saved_trails.html`
* `static/js/forms.js` only if needed for form UX, without breaking Week 5 behavior
* Optional `static/css` file if the skeleton has one
* `tests/test_client_templates.py`

Should not own:

* API calls from Flask.
* Database schema constraints.
* Authorization logic.

### DB-and-security — Nick

Owns:

* SQLModel models and schema constraints.
* Foreign keys and cascade behavior.
* Flask-Login refactor.
* Login-required enforcement.
* Ownership checks and 404-for-not-yours behavior.
* Input validation review.
* Secret hygiene review for `OPENWEATHER_API_KEY`.
* DB/security tests: `tests/test_db_security.py`.

Primary files likely touched:

* `app.py`
* Optional `models.py` if the team agrees to split models out
* `tests/test_db_security.py`

Should not own:

* Final page styling.
* External API response mapping beyond validating that stored data is safe.

### Shared coordinator work, because this is a 3-person team

Since the team has three members, there is no separate coordinator role. The team shares coordinator responsibilities.

Shared responsibilities:

* Review and approve this `CONTRACTS.md` before role implementation starts.
* Commit four initially failing tests before implementation begins.
* Maintain `coord_session.md` with real planning notes, questions, and decisions.
* Make `tests/test_integration.py` pass once all role slices are implemented.
* Write and run the whole-system `e2e.md`.

Integration test file:

* `tests/test_integration.py`
* Owner: shared, with final review from all three members.

## 6. Initial test contracts

The Week 6 contract PR should add these tests before implementation work begins. They should fail at first because the app has not implemented these features yet.

### `tests/test_server_conditions.py`

Owner: Ryan, server-side.

Should assert:

* `/api/conditions?q=Mount%20Rainier` returns `200` with `ok: true` when OpenWeather responses are mocked.
* The success payload includes `weather`, `air_quality`, and `recommendation` keys.
* Invalid short query returns `400 invalid_input`.
* Geocoding empty result returns `404 not_found`.
* OpenWeather timeout returns `503 external_api_unavailable`.
* Malformed weather response returns `502 external_api_error`.

### `tests/test_db_security.py`

Owner: Nick, DB-and-security.

Should assert:

* `saved_trails` table exists with expected columns.
* `trail_checks` table exists with expected columns.
* Saved trails require a valid `user_id`.
* Duplicate exact saved trail for same user is rejected or gracefully prevented.
* Anonymous user cannot access `/saved-trails`.
* User A cannot delete or re-check User B's saved trail and gets `404`.

### `tests/test_client_templates.py`

Owner: Liam, client-side.

Should assert:

* `/trail-checker` renders a form with `action="/trail-checker/results"`, `method="GET"`, and input named `q`.
* The Trail Checker page has a submit button.
* The base navbar includes a link to `/trail-checker`.
* The results template includes stable selectors/classes for weather card, air quality card, and recommendation badge.
* `/saved-trails` page has an empty-state container when no saved trails exist.
* Tests should check structure and selectors, not exact marketing copy.

### `tests/test_integration.py`

Owner: shared.

Should assert:

* User can register or log in.
* Logged-in user can search a realistic location with mocked OpenWeather responses.
* User can save the returned location.
* Saved location appears on `/saved-trails`.
* User can re-check that saved location.
* User can delete the saved location.
* Deleted location no longer appears on `/saved-trails`.

## 7. Whole-system E2E expectations

The final `e2e.md` must exercise:

1. Fresh app startup with Docker Compose.
2. Login/register flow.
3. Anonymous Trail Checker search page.
4. Real OpenWeather search with a realistic outdoor location.
5. Real OpenWeather edge/weird query that may expose contract gaps.
6. Logged-in save flow.
7. Saved trails list page.
8. Re-check saved trail flow.
9. Delete saved trail flow.
10. Ownership probe with two users, if time allows.

At least one E2E step must hit the real OpenWeather service, not mocked fixtures.

## 7a. Week 7 — OAuth (GitHub) addendum

Week 7 adds federated identity via GitHub OAuth. The Week 6 contracts above remain in force; this section adds to and modifies them where noted.

### 7a.1 Schema additions

New table `oauth_identity`:

| column | type | nullable | constraint |
|---|---|---|---|
| `id` | int (PK) | no | |
| `user_id` | int (FK users.id) | no | `ON DELETE CASCADE`; indexed |
| `provider` | varchar(50) | no | `CHECK (provider IN ('github'))` |
| `provider_user_id` | varchar(255) | no | `CHECK (length(provider_user_id) > 0)` |
| `created_at` | timestamptz | no | |

Plus: `UNIQUE (provider, provider_user_id)`.

Modified column on `users`:

* `password_hash` is now **NULLABLE**. An OAuth-only `User` has `password_hash IS NULL`.

### 7a.2 Linking policy (Nick N3)

* Each new `(provider, provider_user_id)` creates a new `User`. Auto-link by email is explicitly **not** supported in Week 7. Email is not a reliable identity claim on GitHub.
* A `User` is identified by `users.id`, not by email. Two GitHub accounts that share an email become two distinct users.
* The `CHECK (provider IN ('github'))` constraint blocks case-variant duplicates ("GitHub" vs "github") that the unique constraint alone would miss.
* Usernames assigned to OAuth users are stored verbatim from GitHub's `login` field. Case is preserved and treated as significant by the `users.username` unique constraint — `OctoCat` and `octocat` are two distinct accounts. The Week 7 callback contract does not normalize case.

### 7a.3 Transactional contract for the OAuth callback (Ryan)

The lookup-or-create flow in `/auth/github/callback` MUST run as a single transaction:

1. SELECT `OAuthIdentity` by `(provider, provider_user_id)`.
2. If not found: INSERT `User`, FLUSH to obtain `user.id`, INSERT `OAuthIdentity`, COMMIT.
3. If the COMMIT raises `IntegrityError` (a concurrent callback won the race), ROLLBACK and re-SELECT to use the winning identity.

This prevents the orphan-User class of bug where a User row is committed before its OAuthIdentity row fails the unique constraint.

### 7a.4 OAuth `state` validation (Ryan)

The OAuth `state` parameter MUST be validated using Authlib's built-in mechanism (`oauth.github.authorize_redirect(...)` paired with `oauth.github.authorize_access_token()`). Without `state` validation an attacker can trick a victim into linking the attacker's GitHub account to the victim's session — this is the OAuth equivalent of CSRF. Any custom `state` handling requires explicit team review.

### 7a.5 Rate limits

* `/login` — `10 per minute` per IP (unchanged).
* `/auth/github/callback` — `10 per minute` per IP. The callback is an equivalent auth surface and must be rate-limited symmetrically.
* `/login/github` (redirect initiator) — not rate-limited; it has no auth side-effects.

### 7a.6 Test-mode backdoor (Ryan R5)

`/test/login/<username>` is a complete authentication bypass and MUST be guarded by **three** independent conditions:

1. `TESTING` environment is set (i.e. `os.environ["TESTING"] == "1"`).
2. `app.debug` is True OR the host is `localhost`/`127.0.0.1`.
3. The route returns `404` (not `403`) when any gate fails, to avoid leaking its existence.

A single-gate guard is insufficient: one misconfigured deploy with `TESTING=1` leaked into production is total compromise.

### 7a.7 Session and cookie lifetimes (Nick N4)

* `PERMANENT_SESSION_LIFETIME` = 12 hours. Applied by setting `session.permanent = True` after every `login_user(...)` call.
* `REMEMBER_COOKIE_DURATION` = 30 days. Applied when `login_user(user, remember=True)` is called.
* OAuth login is always `remember=True` (Liam L5 spec).
* Password login reads the `remember` form field (truthy = remember=True).
* `SESSION_PROTECTION="strong"`: any mismatch in IP/User-Agent on session reload triggers a full logout (not just `non-fresh`). The false-positive cost (user changes networks) is acceptable for this app.

### 7a.8 Secret hygiene (Nick N6)

* `.env` is the single source of truth for secrets. `.env.example` lists the keys with placeholder values.
* `app.py` calls `load_dotenv()` before any `os.environ` read so bare-metal `flask run` and `pytest` get the same env as Docker Compose.
* New secrets in Week 7: `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`. Never echo into logs, screenshots, or git history.

### 7a.9 CSRF (Nick N5)

No new CSRF-exempt routes in Week 7. `/login/github` is GET-only (no body to protect); `/auth/github/callback` is protected by OAuth `state` rather than CSRF tokens. All POST forms keep `{{ csrf_token() }}`.

### 7a.10 Test plumbing (Nick N7)

* `tests/e2e/conftest.py` sets `TESTING=1`, `SECRET_KEY=test-secret-e2e`, and a per-pytest-session tempfile SQLite `DATABASE_URL` BEFORE app import.
* The tempfile path is randomized per session and chmod'd 0600 so concurrent runs cannot collide and other users on a shared host cannot read it.
* `tests/conftest.py` remains the in-memory SQLite setup for unit/integration tests.

### 7a.11 Operational note for migration

Changing `users.password_hash` from `NOT NULL` to `NULL` under SQLModel's `create_all` is destructive on Postgres. The first deploy of Week 7 requires `docker compose down -v` before `docker compose up -d --build` so the `users` table is recreated with the new schema. SQLite test runs are unaffected (fresh DB per run).

### 7a.12 Navbar text contract (cross-slice)

When a user is authenticated, every Flask-rendered page must show, in the navbar:

```
Logged in as {username}
```

followed by a Logout control. `{username}` is the literal value of `User.username` for the currently authenticated session, surfaced to templates by the `inject_user` context processor as `user.username`. No prefix, no truncation, no styling that would split the string across DOM nodes in a way that breaks a `to_contain_text` assertion.

Playwright e2e tests will assert this exact string. Any change to the format requires updating this contract and the affected tests in the same PR.

This contract is cross-slice:
* Nick (DB-and-security): guarantees `User.username` is non-null, unique, and stable for the session lifetime.
* Liam (client): owns the navbar template and the exact text rendering.
* Ryan (server): guarantees that the OAuth callback writes a non-empty `User.username` per §7a.2 before calling `login_user`.

## 8. Known limitations for Week 6

The team is deliberately punting the following:

* No official trail closure/status data. The app checks weather and air quality near a location; it does not know whether a trail is officially open or closed.
* No map UI. Coordinates may be shown as text, but we are not embedding maps yet.
* No autocomplete. Search is a normal text field.
* No advanced location disambiguation. The first geocoding result is used for MVP. A later version can let users pick from multiple results.
* No background refresh. Conditions update only when the user searches or re-checks a saved trail.
* No OAuth yet. Week 6 uses the skeleton login flow refactored to Flask-Login; OAuth is expected later.
* No mobile-first polish beyond reasonable Bootstrap responsiveness.
* No production-grade rate-limit handling. We handle OpenWeather failures gracefully, but we do not implement local caching or request throttling this week.
* No user profile settings.
* No public sharing of saved trails.

## 9. Open questions for team review

Ryan should confirm:

* Whether `/api/conditions` and `/trail-checker/results` should share one helper function.
* Whether he wants to split OpenWeather logic into `weather_service.py` instead of keeping it in `app.py`.

Nick should confirm:

* Exact SQLModel syntax for composite uniqueness on saved trails.
* Whether cascade delete is practical in the current skeleton setup.
* Whether Flask-Login should be added in the same PR as schema or separately.

Liam should confirm:

* Exact Bootstrap layout for result cards.
* Stable CSS selectors/classes that tests can target without locking copy.
* Whether saved trail notes are included in the first UI pass or left as a hidden/simple optional field.

Team should confirm:

* Whether using only OpenWeather is acceptable for the current version.
* Whether the app name should be `Trail Checker`, `TrailCheck`, or another final display name.
* Whether the repo route names should use `/trail-checker` or shorter `/trails` paths.
