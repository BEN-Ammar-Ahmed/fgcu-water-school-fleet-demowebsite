# Admin View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (chosen: build here, one final review). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Four access levels enforced everywhere, plus an admin area (Overview, People & access, Activity, Manage data) with an append-only activity log and "who's online".

**Architecture:** Levels come from `wsb.app_role.role_name` and are interpreted only in `tiers.py`. Activity is written by one helper, `log_activity()`, in `app.py`, into a new append-only table. The admin routes live in a new `admin.py` blueprint with its own templates (`templates/admin/`). The existing search page gains a "browse" mode for Manage data's "Open list".

**Tech Stack:** Python 3.14, Flask 3.1, psycopg2, Jinja2, pytest, PostgreSQL 17 (Docker for tests).

**Spec:** `docs/superpowers/specs/2026-11-05-admin-view-design.md`

## Global Constraints
- Levels (role_name → level): `Top admin` → `top_admin`, `Admin` → `admin`, `Staff` → `editor`, anything else → `viewer`.
- Labels: `Top admin`, `Admin`, `Tier 2 · can edit`, `Tier 2 · view only`.
- Confidential (licenses, driver page) = top admin only. Delete = top admin + admin. Add/edit = top admin + admin + editor.
- Admins may only assign `editor` / `viewer` and only change people currently at `editor` / `viewer`. At least one active top admin must always remain. Nobody changes their own access.
- `wsb.activity_log` is append-only: a trigger refuses UPDATE, DELETE and TRUNCATE.
- Black and white, no emoji, SVG icons, desktop-first. Tests never touch Supabase. No Claude attribution in commits.

## Review Focus
1. An admin POSTing a change that makes someone `admin`/`top_admin`, or changes an existing admin → must be refused (403 or message), with no change in the database. → Task 3 tests.
2. Removing, downgrading or deactivating the last active top admin (including yourself) → refused. → Task 3 tests.
3. Anyone below top admin reaching license data through search, the driver page, the driver form or Manage data → nothing shown. → Tasks 1, 4 tests.
4. Activity entries edited or deleted through SQL → the database refuses. → Task 1 test.
5. People & access with a duplicate email, an empty name or an unknown level → plain message, no crash. → Task 3 tests.

## File Structure
| File | Responsibility |
|---|---|
| `sql_postgres/08_admin_levels.sql` (create) | `Top admin` role, `wsb.activity_log` + immutability trigger, `app_user.last_seen` / `last_page` |
| `sql_postgres/07b_demo_users.sql` (modify) | Demo users for the four levels |
| `dashboard/tiers.py` (modify) | Level model and permission properties |
| `dashboard/app.py` (modify) | `require(...)` flags, `log_activity`, last-seen hook, delete routes, browse mode |
| `dashboard/admin.py` (create) | Admin blueprint: overview, people, activity, data |
| `dashboard/templates/admin/*.html` (create) | Admin pages + shared admin layout |
| `dashboard/tests/test_levels.py`, `test_activity.py`, `test_admin_*.py` (create) | Tests |

---

### Task 1: Four levels everywhere
**Interfaces (produces):** `CurrentUser(user_id, username, full_name, email, level)` with properties `can_edit`, `can_delete`, `can_see_licenses`, `can_manage_people`, `can_manage_admins`, `is_admin`, `tier_label`. `level_for_role(role_name) -> str`. `LEVELS = ['top_admin','admin','editor','viewer']`, `LEVEL_LABELS`, `ROLE_FOR_LEVEL` (level → role_name). `doc_levels(user)`: top_admin/admin → all three, others → General + Staff. `require(edit=False, delete=False, licenses=False, admin=False)`.
- [ ] Write `test_levels.py`: the level mapping and labels; each permission property per level; editor can POST `/vehicles/new` but gets 403 on `/vehicles/<id>/delete`, `/rules/<id>/delete` and `/documents/<id>/delete`; viewer gets 403 on `/vehicles/new`; the admin (`demo_tier1_backup`) gets 403 on `/drivers/<id>` and finds no licenses in search; the top admin sees licenses; the admin sees Admin-level documents ("Title"); the editor doesn't. Update older tests that used `demo_tier2_licenses` for license access to use `demo_tier1`.
- [ ] Run → FAIL. Write `08_admin_levels.sql` (drop and re-add the role_name CHECK to allow `Top admin`, insert the `Top admin` row with `pg_role 'wsb_top_admin'`, create the activity table + trigger, add the last_seen/last_page columns, `lock_out_public_api()`). Update `07b` (demo_tier1 → Top admin, add demo_editor `editor.staff@example.edu` → Staff). Add `08` to conftest's file list and the README run order.
- [ ] Implement `tiers.py` and the `app.py` changes; delete routes use `require(delete=True)`, `/drivers/<id>` uses `require(licenses=True)`, and license fields depend on `can_see_licenses`. Update the help page's tier table to the four levels.
- [ ] Run the full suite → PASS. Commit "Four access levels".

### Task 2: Activity log and who's online
**Interfaces:** `log_activity(kind: str, summary: str) -> None` (kinds: `sign-in`, `view`, `change`, `download`, `access`). Writes user_id, username, kind, summary and path, and never raises (a failure to log must not break the page). `before_request` hook: for a signed-in user, if `last_seen` is older than 60 s, update `last_seen = now()` and `last_page` (a readable label of the request, set by the views via `g.page_label`, default = path).
- [ ] Write `test_activity.py`: sign-in creates a `sign-in` row; opening a vehicle page creates a `view` row naming the vehicle; a search creates a `view` row with the query; adding a trip creates a `change` row; deleting a vehicle creates a `change` row; downloading a document file creates a `download` row; `UPDATE`/`DELETE`/`TRUNCATE` on `wsb.activity_log` raise errors; last_seen is set after a request.
- [ ] Run → FAIL. Implement and call it from sign-in, the vehicle page, driver page, search page, every successful POST that changes data, and doc_file.
- [ ] Run the full suite → PASS. Commit "Activity log and last seen".

### Task 3: Admin blueprint, Overview, People & access
**Interfaces:** blueprint `admin` at `/admin`: `GET /admin` (overview), `GET /admin/people`, `POST /admin/people` (add), `POST /admin/people/<uid>/level`, `POST /admin/people/<uid>/access` (`active=0|1`). Rules in `tiers.py`: `assignable_levels(actor) -> list[str]`, `can_change(actor, target_level) -> bool`. A shared `templates/admin/layout.html` with the left menu.
- [ ] Write `test_admin_overview.py`: viewer/editor get 403 on `/admin`; admin and top admin get 200; the page shows each card label and the correct numbers for demo data (people with access, vehicles, overdue); signed-in-now lists a user active in the last 15 min with their last page and not one seen 20 min ago; the top-bar Admin link is shown only to admins.
- [ ] Write `test_admin_people.py`: top admin adds an admin; admin adds an editor; admin trying to add an admin → refused, nothing saved; admin trying to change an admin's level or access → 403; admin switches editor ↔ viewer; removing access sets active=false and the person is signed out next request; give access back; you can't change yourself; refusing to demote or remove the last top admin; duplicate email / empty name / unknown level → plain message; every change logs an `access` activity row.
- [ ] Run → FAIL. Implement. Run the full suite → PASS. Commit "Admin overview and people".

### Task 4: Activity page, Manage data, browse mode
**Interfaces:** `GET /admin/activity?kind=&q=&date_from=&date_to=&page=` (100 per page). `GET /admin/data`. `run_search(..., browse=True)`: no text needed, returns only the requested kind. `/search?kind=<k>&browse=1`.
- [ ] Write tests: the activity page lists rows newest first and filters by kind, text and date; paging works; Manage data shows counts; the licenses card only for top admin; `Open list` links work for each kind (browse mode returns rows); viewers can't reach `/admin/activity` or `/admin/data`.
- [ ] Run → FAIL. Implement. Run the full suite → PASS. Browser check of all four admin pages against the Docker preview database. Commit "Activity and manage data".

### Final: whole-branch review by a fresh reviewer, fix Important+ with tests, report rulings and deferred minors.
