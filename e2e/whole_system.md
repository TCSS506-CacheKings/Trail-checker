# Trail Checker - Whole-System End-to-End Walk

**Team:** Cache Kings  
**Project:** Trail Checker  
**Supporting role E2E files:**
- `e2e/client-side.md`
- `e2e/db-and-security.md`
- `e2e/server.md`

## 1. Definition

End-to-end for Trail Checker means testing the full system across the main project boundaries: browser UI, Flask routes, Postgres persistence, authentication/security behavior, and the external OpenWeather APIs.

The full system path is:

Browser -> Flask templates/routes -> SQLModel/Postgres -> OpenWeather geocoding/weather/air-pollution APIs -> rendered trail condition results and saved-trail flows.

This file ties together the three role-specific E2E files. Liam's client-side file verifies templates, navigation, forms, Bootstrap layout, stable selectors, and CSRF-compatible form markup. Nick's DB/security file verifies schema constraints, Flask-Login behavior, ownership rules, CSRF/security assumptions, and secret hygiene. Ryan's server-side file verifies live OpenWeather behavior, `/api/conditions`, `/trail-checker/results`, saved-trail rechecks, and server error handling.

## 2. The walk

1. Pull latest `main` and confirm the repo is clean.
2. Run the full test suite with `py -m pytest -v`.
3. Start the app with Docker Compose.
4. Open `/` and confirm the navbar links to `/trail-checker`.
5. Open `/trail-checker` and confirm the search page renders.
6. Submit `Mount Rainier` through the search form.
7. Confirm the results page shows weather, air quality, and recommendation sections.
8. Call `/api/conditions?q=Mount%20Rainier` and confirm successful JSON.
9. Call `/api/conditions?q=M` and confirm `400 invalid_input`.
10. Call `/api/conditions?q=zzzznotrealplace999` and confirm `404 not_found`.
11. Register or log in as a test user.
12. Search again while logged in and confirm the save form appears.
13. Save the location and confirm it appears on `/saved-trails`.
14. Re-check the saved trail and confirm results render using stored coordinates.
15. Delete the saved trail and confirm it no longer appears.
16. Inspect Postgres schema for `users`, `saved_trails`, and `trail_checks`.
17. Confirm `trail_checks` stores anonymous searches with `user_id IS NULL` and logged-in searches with the current user's id.
18. Confirm anonymous users cannot access saved-trail actions.
19. Confirm user B cannot access or delete user A's saved trail and receives `404`.
20. Confirm `OPENWEATHER_API_KEY` is read from the environment and no real key is hardcoded.

## 3. Pass criteria

- **Step 1:** `main` is up to date and `git status` is clean.
- **Step 2:** Full pytest suite passes.
- **Step 3:** Docker Compose starts the app and database.
- **Step 4:** Home page loads and navbar includes `/trail-checker`.
- **Step 5:** Trail Checker search form matches the contract.
- **Step 6:** Search submits through `GET /trail-checker/results`.
- **Step 7:** Results page includes weather card, air quality card, and recommendation badge.
- **Step 8:** API returns `ok: true` with weather, air quality, and recommendation data.
- **Step 9:** Invalid short input returns `400 invalid_input`.
- **Step 10:** Nonsense location returns `404 not_found`.
- **Step 11:** Auth flow works.
- **Step 12:** Logged-in results page shows save form.
- **Step 13:** Saved trail appears on `/saved-trails`.
- **Step 14:** Re-check uses stored coordinates and renders results.
- **Step 15:** Delete flow removes the saved trail.
- **Step 16:** Database schema matches `CONTRACTS.md`.
- **Step 17:** `trail_checks` user id behavior matches the contract.
- **Step 18:** Anonymous users are blocked from saved-trail actions.
- **Step 19:** Ownership probes return `404`, not `403`.
- **Step 20:** No real API key is committed or printed.

## 4. Execution log

Final verification was run after the client-side, server-side, and DB/security role work was merged into `main`.

| Step | Result | Notes |
|------|--------|-------|
| 1 | PASS | `main` was pulled and `git status` reported a clean working tree. |
| 2 | PASS | Full local test suite passed: `26 passed in 1.96s`. |
| 3 | PASS BY ROLE E2E | Docker startup is covered in Ryan's and Nick's role E2E files. |
| 4 | PASS | Client-side tests verify the Trail Checker navbar link. |
| 5 | PASS | Client-side tests verify search form route, method, and `q` input. |
| 6 | PASS | Search flow is covered by client and integration tests. |
| 7 | PASS | Results page selectors and sections are covered by client tests. |
| 8 | PASS | Server-side tests and E2E verify the JSON endpoint. |
| 9 | PASS | Server-side tests verify `400 invalid_input`. |
| 10 | PASS | Server-side tests verify `404 not_found`. |
| 11 | PASS | Auth tests verify register/login behavior. |
| 12 | PASS | Integration test verifies logged-in search flow. |
| 13 | PASS | Integration test verifies saving a trail. |
| 14 | PASS | Server follow-up tests verify saved-trail recheck behavior. |
| 15 | PASS | Integration test verifies deleting a saved trail. |
| 16 | PASS | DB/security tests verify schema and constraints. |
| 17 | PASS | Nick's DB/security E2E includes anonymous vs logged-in `trail_checks` verification. |
| 18 | PASS | DB/security tests verify anonymous users are blocked. |
| 19 | PASS | DB/security tests verify non-owner access returns `404`. |
| 20 | PASS BY ROLE E2E | Secret hygiene is covered in Nick's DB/security E2E and Ryan's server E2E. |

## 5. Findings and fixes

### Finding 1 - OpenWeather tests need mocks in CI

Some Flask routes render templates using OpenWeather-backed server code. The team fixed this by mocking OpenWeather responses in pytest with the `responses` library. Live OpenWeather behavior is tested in the server-side E2E instead.

### Finding 2 - Saved trails were a real integration dependency

The client-side saved-trails template existed before the `/saved-trails` route was fully integrated. Once Nick's DB/security work, Ryan's server routes, and Liam's templates were merged, the saved-trails route worked and the full test suite passed.

### Finding 3 - CSRF affected client-side forms

Nick's DB/security work added CSRF protection for POST routes. Liam updated the save and delete forms to include `csrf_token` hidden inputs.

### Finding 4 - New OpenWeather API keys can take time to activate

Ryan's live E2E found that a new OpenWeather key may initially return `401` even after the dashboard shows active. Re-running after the activation window resolved the issue.

### Finding 5 - Geocoding can return surprising locations

Ryan's live E2E found that `Mount Rainier` and `Rainier` resolved to different coordinates. This is documented as a Week 6 limitation because the MVP uses OpenWeather's first geocoding result without a disambiguation UI.

## 6. Per-role contributions

| Role | Person | Contribution |
|------|--------|--------------|
| Client-side | Liam Sipp | Trail Checker templates, navbar link, search/results/saved-trails UI, stable selectors, CSRF-compatible forms, and `e2e/client-side.md`. |
| Server-side | Ryan Belmonte | OpenWeather integration, `/api/conditions`, `/trail-checker/results`, trail check persistence, saved-trail recheck behavior, and `e2e/server.md`. |
| DB-and-security | Nick Stjern | Flask-Login refactor, `SavedTrail`/`TrailCheck` schema, constraints, ownership rules, CSRF/security behavior, and `e2e/db-and-security.md`. |
| Shared | All | Reviewed PRs, merged role slices, fixed integration issues, and verified the final test suite. |

## 7. What we would do differently next time

- Decide earlier that the role-specific E2E files also need a team-level summary.
- Add CSRF requirements to the initial contract so client-side forms include tokens from the start.
- Add a geocoding disambiguation plan earlier because live OpenWeather results can be surprising.
- Keep using role-specific E2E files, but create the whole-system summary immediately after all three role E2Es exist.
