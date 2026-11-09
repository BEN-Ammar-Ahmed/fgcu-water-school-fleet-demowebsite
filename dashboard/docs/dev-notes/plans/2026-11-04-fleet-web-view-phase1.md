# Fleet Web View — Phase 1 (core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing Flask prototype into the search-first, black-and-white, tiered site from the design: placeholder FGCU sign-in, Tier 1 / Tier 2 / license-access rules, expanding search home page, full vehicle page, add/edit forms and a help page.

**Architecture:** Keep the single Flask app in `dashboard/` and its psycopg2 helpers (`q`, `run`, `db`). Move tier rules into `tiers.py` and search into `search.py` (both plain functions, unit-tested). Replace the role picker with a user-based session (`session['user_id']`), with every permission check going through `tiers.py`. Templates and CSS are rewritten, and routes that already work are kept. Tests run against a throwaway PostgreSQL 17 in Docker, built from `sql_postgres/` plus the demo data.

**Tech Stack:** Python 3.14, Flask 3.1, psycopg2 2.9, Jinja2, pytest 9, PostgreSQL 17 (Docker for tests, Supabase for real), plain CSS + a little vanilla JS. No new runtime dependencies in Phase 1.

**Spec:** `docs/superpowers/specs/2026-11-04-fleet-web-view-design.md`

**Phase 2 (separate plan, later):** spreadsheet upload (5.6), downloads (5.7), sign-in alert pop-up (5.8), stats (5.9), admin area + activity log (5.10), invoice forms.

## Global Constraints

- Colors: black, white and grays only. The only color is red / amber on Overdue / Due soon warnings. Status is always a word badge, never color alone.
- Icons: inline SVG line icons only. No emoji anywhere in templates.
- Desktop-first: designed for 1280–1920px, and must stay usable down to 900px.
- Tier 1 = `wsb.app_role.role_name = 'Admin'`, which can view, add, edit and delete. Tier 2 = `'Read-only'` (and `'Staff'` if present), which is view-only. License access = new `wsb.app_user.can_see_licenses`.
- Documents: Tier 1 sees access levels `General`, `Staff` and `Admin`. Tier 2 sees `General` and `Staff`.
- Tier 2 never sees driver emails, license numbers or license files. Only `can_see_licenses` users see `wsb.driver_license` data.
- Database changes go only in `sql_postgres/` as re-runnable SQL, ending with `SELECT wsb.lock_out_public_api();`.
- `dashboard/`, `.env`, real-data SQL and uploads are never committed to the outer repo. Commit messages and PR text contain no Claude / Claude Code attribution.
- Search animation: open/close and move-to-top transitions are about 0.45s (`cubic-bezier(.2,.8,.2,1)`). `/` opens search and Esc closes it.

## Review Focus

1. **Search text with SQL wildcards or quotes** (`50%`, `_`, `O'Brien`) must be treated literally: no error and no match-everything. → test in Task 4.
2. **Tier 2 reaching edit or license data by typing URLs** (POST to edit routes, `/drivers/<id>`, a license search) must get 403 or no data, not just a hidden button. → tests in Tasks 2, 5, 7.
3. **A user deactivated while signed in** is signed out on their next request. → test in Task 2.
4. **Date-like text that isn't a valid date** (`2026-13-45`, `10/3`) must not crash. It falls back to a text search, and a valid partial date (`October 2026`) matches that month. → test in Task 4.
5. **Very common searches** (`a`, `Ford`) return at most 50 rows per group, with the true total shown ("showing 50 of 212"). → test in Task 4.

## File Structure

| File | Responsibility |
|---|---|
| `sql_postgres/07_web_access.sql` (create) | `can_see_licenses` column on `wsb.app_user` |
| `sql_postgres/07b_demo_users.sql` (create) | Fictional sign-in users (one per tier + one with license access) |
| `dashboard/tiers.py` (create) | `CurrentUser`, loading users, every permission rule |
| `dashboard/search.py` (create) | Date-term parsing, grouped search with tier filtering |
| `dashboard/app.py` (modify) | Routes: sign-in, home/search, vehicle page, forms, help. Old role code removed. |
| `dashboard/templates/*.html` (rewrite) | New layout and pages |
| `dashboard/templates/_icons.html` (create) | Jinja macros for SVG icons |
| `dashboard/static/style.css` (rewrite) | Black-and-white design |
| `dashboard/static/search.js` (create) | Expanding search behavior |
| `dashboard/tests/conftest.py` (create) | Docker test database, app client, sign-in helper |
| `dashboard/tests/test_*.py` (create) | Tests per task |
| `dashboard/README.md` (modify) | Maintainer guide |

---

### Task 0: Local history and test harness

**Files:**
- Create: `dashboard/tests/conftest.py`, `dashboard/tests/test_smoke.py`, `dashboard/pytest.ini`

**Interfaces:**
- Produces fixtures: `app_module` (the imported `app` module), `client` (Flask test client on a fresh database cloned from the template), `sign_in(client, username: str) -> None` (sets `session['user_id']` for that `wsb.app_user.username`), `dbq(sql, args=()) -> list[dict]` (query the current test database).

- [ ] **Step 1:** In `dashboard/`, run `git init` and commit the current files as "Prototype before redesign". This is a local-only nested repo with no remote, ignored by the outer repo. It gives undo history for the dashboard, which the outer repo deliberately ignores. Add `uploads/`, `.env` and `__pycache__/` to `dashboard/.gitignore` first.
- [ ] **Step 2:** Start the test database: `docker run -d --name wsb-test-db -e POSTGRES_PASSWORD=test -p 54329:5432 postgres:17`.
- [ ] **Step 3:** Write `conftest.py`:
  - Before importing `app`, set `os.environ['DATABASE_URL']` to the test URL, so `load_env_file`'s `setdefault` never picks up the Supabase `.env`. **Tests must never connect to Supabase.** Assert that `'supabase' not in app.DB_URL`.
  - Once per session, (re)create database `wsb_template` and run, in order: `sql_postgres/01_schema.sql`, `02_security.sql`, `03_reference_data.sql`, `03b_demo_data.sql`, `04_import_staging.sql`, `05_procedures.sql`, `07_web_access.sql`, `07b_demo_users.sql` (skip the 07 files until Task 1 creates them).
  - For each test, `DROP DATABASE IF EXISTS wsb_test` and then `CREATE DATABASE wsb_test TEMPLATE wsb_template`. Monkeypatch `app.DB_URL` to it and `app.UPLOADS` to `tmp_path`, and set `app.app.config['TESTING'] = True`.
- [ ] **Step 4:** `test_smoke.py::test_template_has_demo_data` asserts that `dbq("select count(*) n from wsb.vehicle where asset_number like 'DEMO-%'")[0]['n'] == 8`.
- [ ] **Step 5:** Run `pytest -q` from `dashboard/`. Expected: 1 passed.
- [ ] **Step 6:** Commit in the `dashboard/` repo: "Add test harness".

### Task 1: Database: license access and demo users

**Files:**
- Create: `sql_postgres/07_web_access.sql`, `sql_postgres/07b_demo_users.sql`
- Test: `dashboard/tests/test_db_access.py`

**Interfaces:**
- Produces: column `wsb.app_user.can_see_licenses BOOLEAN NOT NULL DEFAULT FALSE`. Demo users (username / email / role / licenses):
  `demo_tier1` / `fleet.manager@example.edu` / Admin / true ·
  `demo_tier1_backup` / `fleet.backup@example.edu` / Admin / false ·
  `demo_tier2` / `campus.staff@example.edu` / Read-only / false ·
  `demo_tier2_licenses` / `insurance.office@example.edu` / Read-only / true ·
  `demo_inactive` / `former.staff@example.edu` / Read-only / false, `active = false`.

- [ ] **Step 1:** Write `test_db_access.py::test_demo_users_and_license_flag`. It asserts the five rows above exactly (username, role_name, can_see_licenses, active).
- [ ] **Step 2:** Run it. Expected: FAIL (column does not exist).
- [ ] **Step 3:** Write `07_web_access.sql` (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, comment header in the style of 01–05, then `lock_out_public_api()`). Write `07b_demo_users.sql` (`INSERT ... ON CONFLICT (username) DO UPDATE` so it's re-runnable; header says "fictional; remove when Reagan sends the real list" with a commented DELETE). Add both to the README run-order table in `sql_postgres/README.md`, and enable them in conftest.
- [ ] **Step 4:** Run the test. Expected: PASS.
- [ ] **Step 5:** Commit in the outer repo: `git add sql_postgres/07_web_access.sql sql_postgres/07b_demo_users.sql sql_postgres/README.md` → "Add license-access flag and demo sign-in users".

### Task 2: Tiers and placeholder FGCU sign-in

**Files:**
- Create: `dashboard/tiers.py`
- Modify: `dashboard/app.py`: remove `ROLES`, `DOC_LEVELS`, `role()`, `can()`, `require(min_role)` and replace them with what's below. Update every `@require(...)`: `'Staff'` / `'Admin'` → `@require(edit=True)`, others → `@require()`.
- Rewrite: `templates/login.html`. Create: `templates/demo_signin.html`, `templates/no_access.html`.
- Test: `dashboard/tests/test_tiers.py`, `dashboard/tests/test_signin.py`

**Interfaces:**
- `tiers.py`:
  - `@dataclass(frozen=True) class CurrentUser: user_id: int; username: str; full_name: str; email: str | None; tier: int; can_see_licenses: bool`, plus property `can_edit -> bool` (`tier == 1`) and property `tier_label -> str` (`"Tier 1"` / `"Tier 2"`).
  - `tier_for_role(role_name: str) -> int`: `'Admin'` → 1, anything else → 2.
  - `doc_levels(user: CurrentUser) -> list[str]`: tier 1 → `['General','Staff','Admin']`, tier 2 → `['General','Staff']`.
  - `load_user(q, user_id: int) -> CurrentUser | None` and `user_for_email(q, email: str) -> CurrentUser | None`. Both return active users only, and email matching ignores case. `q` is `app.q`.
- `app.py`:
  - `current_user() -> CurrentUser | None` (cached on `g`). If `session['user_id']` points to a missing or inactive user, it clears the session and returns None.
  - `require(edit: bool = False, licenses: bool = False)` decorator. No user → redirect to `/login?next=...`. If `edit` and not `can_edit`, or `licenses` and not `can_see_licenses` → `abort(403)`.
  - `sign_in_email(email: str) -> CurrentUser | None` is the **single place real FGCU sign-in will call later**. It sets `session['user_id']` and returns the user, or returns None.
  - Routes: `GET /login` (page with one "Sign in with FGCU" button linking to `/login/fgcu`, and small print "FGCU sign-in will be connected by FGCU IT"). `GET /login/fgcu` → redirects to `/login/demo` until real SSO exists. `GET /login/demo` lists active users (name, email, tier, "license access") as buttons. `POST /login/demo` takes `email`, calls `sign_in_email`, and goes to `next` or `/`. If no user → `no_access.html` with status 403 and the text "You don't have access yet. Ask the fleet manager." `GET /logout`.
  - The context processor provides `user=current_user()` (replaces `role`, `can`, `ROLES`).

- [ ] **Step 1:** Write the tests:
  - `test_tiers.py::test_tier_for_role`: Admin→1, Read-only→2, Staff→2.
  - `test_tiers.py::test_doc_levels`: values as above.
  - `test_signin.py::test_unknown_email_gets_no_access`: POST `/login/demo` with `nobody@fgcu.edu` → 403, and the page contains "You don't have access yet".
  - `test_signin.py::test_inactive_user_cannot_sign_in`: same with `former.staff@example.edu` → 403.
  - `test_signin.py::test_signed_in_user_deactivated_is_signed_out`: sign in `demo_tier2`, set `active=false` in the database, GET `/` → redirect to `/login`.
  - `test_signin.py::test_tier2_cannot_edit`: as `demo_tier2`, POST `/vehicles/1/edit` → 403, and POST `/vehicles/new` → 403.
  - `test_signin.py::test_tier1_can_edit`: as `demo_tier1`, GET `/vehicles/new` → 200.
  - `test_signin.py::test_login_has_no_role_picker`: GET `/login` contains "Sign in with FGCU" and does not contain "Read-only".
- [ ] **Step 2:** Run `pytest tests/test_tiers.py tests/test_signin.py -q`. Expected: FAIL (no `tiers` module).
- [ ] **Step 3:** Implement `tiers.py` and the `app.py` changes above. Replace every `DOC_LEVELS[role()]` with `doc_levels(current_user())`.
- [ ] **Step 4:** Run the tests. Expected: all PASS, with `test_smoke` still passing.
- [ ] **Step 5:** Commit in the dashboard repo: "Tiers and placeholder FGCU sign-in".

### Task 3: Black-and-white layout and top bar

**Files:**
- Rewrite: `templates/base.html`, `static/style.css`, `templates/error.html`
- Create: `templates/_icons.html`
- Test: `dashboard/tests/test_layout.py`

**Interfaces:**
- `_icons.html` macros: `icon(name, size=20)` for names `search, plus, edit, trash, download, help, admin, logout, boat, car, truck, trailer, cart, close, check, alert`. Each is an inline `<svg>` with `stroke="currentColor"` and no fill colors.
- CSS custom properties on `:root`: `--bg #f7f7f6, --surface #fff, --ink #111, --ink2 #555, --line #dcdcd8, --warn-red #c2261c, --warn-amber #9a5b00` (no other colors). Classes used by later tasks: `.topbar`, `.page`, `.card`, `.badge` (+ `.badge-overdue`, `.badge-soon`), `.btn`, `.btn-primary` (black fill), `.table`, `.field`, `.form-error`, `.flash-ok`, `.flash-error`.
- `base.html` top bar: site name (link `/`), a block `topsearch` (empty by default; Task 5 fills it), **+ Add** menu (only if `user.can_edit`; links come from Task 7), **Help**, and the user's name plus `user.tier_label` with Sign out.

- [ ] **Step 1:** Write the tests:
  - `test_layout.py::test_topbar_shows_user_and_tier`: as `demo_tier2`, GET `/help` contains the user's full name and "Tier 2", and does not contain "+ Add".
  - `test_layout.py::test_tier1_sees_add`: as `demo_tier1`, the page contains "Add".
  - `test_layout.py::test_no_emoji_in_templates`: scan `templates/*.html` with a regex for code points above U+1F000 and for U+2600–U+27BF. Expect none.
  - `test_layout.py::test_css_has_only_allowed_colors`: every hex color in `style.css` must be in the allowed set above, plus grays where R=G=B (±6).
- [ ] **Step 2:** Run. Expected: FAIL (`/help` doesn't exist yet). Add a temporary `GET /help` returning a bare `base.html` page. Task 8 replaces it.
- [ ] **Step 3:** Implement the layout, CSS and icons. Use a single system font stack (`system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`) with clear sizes and a visible focus ring (`outline: 2px solid #111`).
- [ ] **Step 4:** Run `pytest -q`. Expected: all PASS.
- [ ] **Step 5:** Commit in the dashboard repo: "Black-and-white layout".

### Task 4: Search logic

**Files:**
- Create: `dashboard/search.py`
- Test: `dashboard/tests/test_search.py`

**Interfaces:**
- `KINDS = ['all', 'vehicles', 'trips', 'fuel', 'maintenance', 'documents', 'licenses']` ('licenses' is only offered when `user.can_see_licenses`).
- `GROUP_LIMIT = 50`
- `parse_date_term(text: str) -> tuple[date, date] | None` returns a half-open range `[start, end)`. It accepts `YYYY-MM-DD`, `MM/DD/YYYY`, `Month YYYY` / `Mon YYYY` (a whole month), and `Month` alone (that month in the current year). Anything else, including invalid dates, returns None.
- `escape_like(text: str) -> str` escapes `\`, `%` and `_` for `ILIKE ... ESCAPE '\'`.
- `run_search(q, user: CurrentUser, text: str, kind: str = 'all', filters: dict | None = None) -> dict[str, dict]` returns `{group: {'rows': list[dict], 'total': int}}` for each group in the requested kind (all groups for `'all'`). Empty or whitespace-only `text` with no filters returns `{}`.
  - vehicles: matches `notes, make, model, asset_number, license_plate, vin, location, department, vehicle_type`.
  - trips: matches vehicle text, `destination, purpose, project_program`, driver `first_name || ' ' || last_name`, and `start_datetime` within the date range. Rows include `driver_name`, never driver email.
  - fuel: matches vehicle text, `vendor, site_address, ticket_number`, and `fuel_date` within the date range.
  - maintenance: rules and records by vehicle text, `maintenance_type` / `service_type`, `vendor`, and dates.
  - documents: `document_type, notes`, vehicle text, `expiration_date` / `issue_date` within the date range, limited to `doc_levels(user)`.
  - licenses: only if `user.can_see_licenses`. Driver name, `license_number`, `state`, `expiration_date`.
  - `filters` keys (all optional): `vehicle_id:int, driver_id:int, date_from:date, date_to:date, vehicle_type:str, status:str, location:str, document_type:str`. Each applies only to the groups that have that column.
  - Every group is ordered newest first (vehicles by type then name), with `LIMIT GROUP_LIMIT`, and `total` comes from a separate `COUNT(*)`.

- [ ] **Step 1:** Write the tests (use the demo data from `03b_demo_data.sql`):
  - `test_parse_date_term`: `'2026-10-03'` → (Oct 3, Oct 4). `'10/03/2026'` → same. `'October 2026'` → (Oct 1, Nov 1). `'2026-13-45'` → None. `'10/3'` → None. `'Ford'` → None.
  - `test_vehicle_search_finds_f250`: as tier 2, `run_search(..., 'F-250')['vehicles']['rows'][0]['asset_number'] == 'DEMO-T01'`.
  - `test_date_search_finds_trips_that_day`: `'2026-10-03'`, kind trips → total == 1, and the destination is 'Matlacha Boat Ramp'.
  - `test_trips_have_no_driver_email`: no row key contains 'email'.
  - `test_wildcards_are_literal`: `'%'` → every group total == 0. `"O'Brien"` → no exception.
  - `test_tier2_never_gets_admin_documents`: searching `'Title'` as `demo_tier2` → 0 documents. As `demo_tier1` → 4.
  - `test_licenses_only_with_flag`: `'Patel'` as `demo_tier2` → no 'licenses' key. As `demo_tier2_licenses` → licenses total == 1.
  - `test_group_limit_and_total`: insert 60 trips for DEMO-T01 in the test, then search `'DEMO-T01'` kind trips → 50 rows and total ≥ 60.
  - `test_blank_search_returns_nothing`: `'   '` → `{}`.
- [ ] **Step 2:** Run `pytest tests/test_search.py -q`. Expected: FAIL (no module).
- [ ] **Step 3:** Implement with parameterized SQL only (never string-format user text). Text match is `ILIKE %s ESCAPE '\'` on `'%' + escape_like(text) + '%'`. A date range adds `OR (date_col >= %s AND date_col < %s)`.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit in the dashboard repo: "Search logic".

### Task 5: Search home page

**Files:**
- Modify: `dashboard/app.py`: `GET /` becomes the search page. `GET /search` takes args `q, kind, vehicle_id, driver_id, date_from, date_to, vehicle_type, status, location, document_type`. `GET /vehicles` → redirect to `/search?kind=vehicles` (keep the old args working). Remove the old dashboard route and template.
- Create: `templates/home.html`, `static/search.js`. Delete: `templates/dashboard.html`, `templates/vehicles.html`.
- Test: `dashboard/tests/test_home.py`

**Interfaces:**
- Consumes `run_search`, `KINDS`, `parse_date_term` (Task 4), `maintenance()` (existing), `icon()` (Task 3).
- `home.html` renders two states from the same template. **Closed** (no `q` and no filters): a centered round button `#search-open` (`aria-label="Search"`) with the search icon, plus hidden heading, chips and the counts "N overdue" / "N due soon". **Searched**: the bar at the top with `q` filled in, a chip row (`KINDS`, current kind selected, each chip is a link that keeps `q`), a filter row for the selected kind, and the groups with headings "Vehicles · 12" and, when total > rows, "showing 50 of 212". The search form is `GET /search`.
- `search.js` reproduces the approved mockup (`.superpowers/brainstorm/7998-1793841585/content/search-expand.html`): click → width grows to `min(600px, 86%)` and the input fades in. Enter submits. Esc closes when empty. `/` opens it from anywhere. After a search, the page loads already in the searched state, and the bar animates up from the center once (skip the animation when `prefers-reduced-motion`).
- Each result row links to its home: vehicle → `/vehicles/<id>`; trip, fuel, maintenance and document → the vehicle page anchor (`#trips`, `#fuel`, `#maintenance`, `#documents`); license → `/drivers/<driver_id>` (Task 7).

- [ ] **Step 1:** Write the tests:
  - `test_home_closed_state`: as tier 2, GET `/` → 200, contains `id="search-open"` and the overdue count "1 overdue" (demo DEMO-T01 oil change). Contains no result groups.
  - `test_search_page_groups`: GET `/search?q=F-250` → contains "Vehicles · 1" and a link to `/vehicles/` plus DEMO-T01's id.
  - `test_kind_chip_narrows`: `/search?q=DEMO-T01&kind=trips` contains "Trips ·" and not "Vehicles ·".
  - `test_tier2_license_search_hidden`: as `demo_tier2`, `/search?q=Patel&kind=licenses` → no "Licenses" group and no license number text "DEMO-DL-". As `demo_tier2_licenses` → contains "DEMO-DL-".
  - `test_old_vehicles_url_redirects`: `/vehicles?type=Boat` → 302 to `/search` with `kind=vehicles` and `vehicle_type=Boat`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement the route, template and JS.
- [ ] **Step 4:** Run `pytest -q`. Expected: all PASS.
- [ ] **Step 5:** Visual check: add a `.claude/launch.json` entry `fleet-test` that runs `python app.py` with `DATABASE_URL` set to the Docker test database (never Supabase), then compare `/` and `/search?q=F-250` with the mockup at 1440px and 900px wide. Fix anything off.
- [ ] **Step 6:** Commit in the dashboard repo: "Search home page".

### Task 6: Vehicle page

**Files:**
- Modify: `dashboard/app.py` (`vehicle(vid)`), rewrite `templates/vehicle.html`
- Test: `dashboard/tests/test_vehicle_page.py`

**Interfaces:**
- `vehicle(vid)` passes `v, rules, records, trips, fuel, costs, docs, hidden_docs, levels`:
  - `records`: `wsb.maintenance_record` for the vehicle, newest first.
  - `trips`: newest 50, each with `driver_name` (no email).
  - `fuel`: newest 50.
  - `costs`: `wsb.v_cost_by_vehicle_fy` rows for the vehicle.
  - `docs` and `hidden_docs`: as today, but using `doc_levels(user)`.
- Sections with anchors `#details #maintenance #trips #fuel #costs #documents`. The header has the name (`display_name`), type icon, property tag, a status word badge, and Edit / Delete (tier 1 only). Each section has **Add** (tier 1, linking to Task 7's forms with `vehicle_id` prefilled). Download buttons come in Phase 2, so leave no placeholder.

- [ ] **Step 1:** Write the tests (DEMO-T01):
  - `test_vehicle_page_sections`: GET `/vehicles/<T01 id>` contains every section id and "Matlacha Boat Ramp" (trip), "Sample Gas C" (fuel), "Brake Service" (record) and "FY26-27" (costs).
  - `test_tier2_hides_admin_docs_and_buttons`: as tier 2, no "Title" document row, the text "1 document hidden" (or the existing hidden-docs wording), and no Edit / Delete.
  - `test_tier1_sees_edit_delete`: as tier 1, contains `/vehicles/<id>/edit`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit in the dashboard repo: "Full vehicle page".

### Task 7: Add and edit forms (Tier 1)

**Files:**
- Modify: `dashboard/app.py`. Create: `templates/form_trip.html`, `form_fuel.html`, `form_maintenance.html`, `form_driver.html`, `driver.html`. Restyle `vehicle_form.html`.
- Test: `dashboard/tests/test_forms.py`

**Interfaces:**
- `db_error_message(e: psycopg2.Error) -> str` returns `e.diag.message_primary` for the database's own raised messages (e.g. "Unknown asset number. Check wsb.vehicle.") and a plain fallback "Could not save. Check the values and try again." otherwise.
- Routes (all `@require(edit=True)`; GET shows the form, POST saves):
  - `/trips/new?vehicle_id=` → `SELECT wsb.add_trip(p_asset_number => ..., p_driver_email => ..., p_start_datetime => ..., ...)`. The form shows a vehicle select (by asset number) and a driver select (active, approved drivers).
  - `/fuel/new?vehicle_id=` → `wsb.add_fuel(...)`.
  - `/maintenance/new?vehicle_id=` → `wsb.add_maintenance(...)`.
  - `/drivers/new` and `/drivers/<id>/edit` → plain INSERT / UPDATE on `wsb.driver`. License fields (`license_number, state, expiration_date`) on `wsb.driver_license` are shown and saved only when `user.can_see_licenses`.
  - `GET /drivers/<id>` uses `@require(licenses=True)`. It's the driver page with license and qualifications.
  - After saving, flash "Saved." and go back to the vehicle page anchor (or the driver page).
- The top-bar **+ Add** menu links: Vehicle, Trip, Fuel, Maintenance, Driver.

- [ ] **Step 1:** Write the tests:
  - `test_add_trip_success`: as tier 1, POST `/trips/new` (DEMO-T01, arivera@example.edu, 2026-11-02 08:00, mileage 48210→48300) → redirect to `/vehicles/<id>#trips`, and `wsb.vehicle.current_mileage` for DEMO-T01 becomes 48300.
  - `test_add_trip_shows_db_message`: driver `spatel@example.edu` (not approved) → 200 and the page contains "This driver is not approved or is inactive."
  - `test_add_fuel_and_maintenance`: one success each. The maintenance one rolls the DEMO-T02 Oil Change rule's `last_completed_date` forward.
  - `test_tier2_forbidden_everywhere`: as tier 2, GET and POST each new route → 403.
  - `test_driver_license_fields_need_flag`: as `demo_tier1_backup` (tier 1, no licenses), GET `/drivers/new` has no "License number" field, and GET `/drivers/<id>` → 403. As `demo_tier1` → the field is present and the page is 200.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Use named arguments for the database functions, exactly as in the examples at the bottom of `sql_postgres/05_procedures.sql`.
- [ ] **Step 4:** Run `pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit in the dashboard repo: "Add and edit forms".

### Task 8: Help page, cleanup and maintainer guide

**Files:**
- Create: `templates/help.html`. Delete: `templates/roles.html`. Modify: `dashboard/app.py` (`/roles` → 301 to `/help#tiers`; restyle `/maintenance` and `/documents` with the new layout), `dashboard/README.md`
- Test: `dashboard/tests/test_help.py`

**Interfaces:**
- `help.html` sections with anchors: `#search` (how to search, chips, `/` and Esc), `#tiers` (a table: Tier 1 / Tier 2 / License access and what each can do, from spec section 2), `#adding` (Tier 1 forms), `#access` ("Ask the fleet manager"). Uploading and downloading are Phase 2, so leave them out.
- `README.md` (maintainer guide): how to run (`python app.py`), `.env` / `DATABASE_URL`, running `sql_postgres` files in order including 07 / 07b, running tests (Docker command plus `pytest`), and where real FGCU sign-in plugs in (`sign_in_email` in `app.py`, `/login/fgcu`).

- [ ] **Step 1:** Write the tests: `test_help_sections` (as tier 2, GET `/help` → 200 and contains every anchor id), `test_roles_redirects` (`/roles` → 301 to `/help#tiers`), and `test_pages_still_work` (as tier 2, `/maintenance` and `/documents` → 200).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest -q`. Expected: all PASS.
- [ ] **Step 5:** Final check in the browser preview (`fleet-test`): sign in as each demo user, search, open a vehicle, add a trip as tier 1, and confirm tier 2 sees no Add / Edit and no licenses. Then run against Supabase **read-only** (sign in as a demo user, search, open a vehicle, write nothing) to confirm it works with the real data shape. Note: `07` and `07b` must first be run on Supabase. Ask Ahmed before running them.
- [ ] **Step 6:** Commit in the dashboard repo: "Help page and maintainer guide".
