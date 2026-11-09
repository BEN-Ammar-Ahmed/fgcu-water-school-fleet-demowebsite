# Water School Fleet: admin view

**Date:** 2026-11-05 · **Author:** Ahmed Ben Ammar · **Status:** approved in chat ("Yes, build admin")
**Builds on:** `2026-11-04-fleet-web-view-design.md` (Phase 1 is built: `dashboard/`, tests in `dashboard/tests/`).
**Reference mockup:** `.superpowers/brainstorm/9103-1793905918/content/admin-view-v2.html` (local only).

## 1. Intent

Reagan (and the new fleet manager) need one place to see how the fleet and the site are being used, and to control who can see and change what without asking a developer. This also replaces Phase 1's two simple tiers with the four levels agreed with Ahmed.

## 2. Access levels (decided by Ahmed)

| Level | Stored as `wsb.app_role.role_name` | Confidential data (driver's licenses) | View | Add & edit | Delete | Manage people |
|---|---|---|---|---|---|---|
| **Top admin** | `Top admin` (new) | Yes | Yes | Yes | Yes | Everyone |
| **Admin** | `Admin` | No | Yes | Yes | Yes | Tier 2 people only |
| **Tier 2 · can edit** | `Staff` | No | Yes | Yes | No | No |
| **Tier 2 · view only** | `Read-only` | No | Yes | No | No | No |

- There can be several top admins and admins.
- **Only a top admin** can make someone an admin or top admin, or change or remove an admin or top admin.
- An admin can add Tier 2 people, switch them between *can edit* and *view only*, and remove or restore their access.
- **The site always keeps at least one active top admin.** It refuses any change that would leave none.
- Confidential data = driver's license records (`wsb.driver_license`, the driver page). Only top admins see it. The Phase 1 `can_see_licenses` switch is no longer used *(Ahmed: top admins have the confidential data. My call: the column stays in the database but the site ignores it)*.
- Documents: top admins and admins see all access levels (`General`, `Staff`, `Admin`). Tier 2 sees `General` and `Staff`.
- Driver emails: admins and top admins see them. Tier 2 does not.
- An admin can manage drivers (add and edit), but not their license fields.

## 3. The admin area

Reached from an **Admin** link in the top bar, shown to top admins and admins only. A left menu has: Overview, People & access, Activity, Manage data, ← Back to search. Black and white like the rest of the site.

### 3.1 Overview
- Cards: **people with access** (with the count per level), **signed in now**, **vehicles** (with the count per type), **maintenance overdue** (and due soon), **trips this month**, **fuel this month** ($), **spent this fiscal year** ($, current Florida fiscal year from `v_cost_by_vehicle_fy`), **documents expiring in the next 60 days**.
- **Signed in now:** name, level, and the last page they opened ("Search: Sea Ark", "Vehicle: 1996 Sea Ark…"). "Now" = active in the last 15 minutes.
- **Most used vehicles this month:** the top 5 by number of trips, as simple bars.
- **Recent activity:** the latest 5 entries, with a link to Activity.

### 3.2 People & access
- A list of everyone in `wsb.app_user`: name, email, level (a dropdown when the viewer may change it), confidential data Yes/No, status (signed in / offline / access removed), last signed in, and **Remove access** / **Give access back**.
- **Add person:** full name, FGCU email, level. Admins only get the two Tier 2 choices. A duplicate email gives a plain message.
- A search box and a level filter.
- Every change saves at once and is written to Activity.
- People can't remove their own access.

### 3.3 Activity
- An append-only list of sign-ins, views (vehicle pages, driver pages, searches), changes (every save, edit, delete, upload), downloads (document files) and access changes, each with time, person and a one-line summary.
- Filters: kind, text (person / summary), date range. Newest first, 100 per page.
- Nobody can edit or delete entries. The database itself refuses UPDATE / DELETE / TRUNCATE on the table.
- Stored in a new table `wsb.activity_log`, which records the person (not the shared database login).

### 3.4 Manage data
- One card per kind of record, with its count and buttons: vehicles, drivers, driver's licenses (top admin only, marked "Confidential"), trips, fuel records, maintenance, documents.
- **Open list** shows all records of that kind through the existing search results page (a "browse" mode that needs no search text). **+ Add** goes to the existing forms.
- Spreadsheet upload is Phase 2 and isn't shown.

## 4. Goals / non-goals / anti-goals
- **Goals:** the four levels enforced on the server everywhere (pages, forms, deletes, search, downloads), the four admin pages above, the activity log, and who's online.
- **Non-goals:** real FGCU sign-in, email invitations, spreadsheet upload, downloads of lists, dark mode / settings, the general menu redesign.
- **Anti-goals:** anyone below top admin seeing license data in any form; an admin giving out access above their own; ending up with no top admin; activity entries that can be edited or deleted; real fleet data in tests or screenshots.

## 5. Constraints
- Build on Phase 1 (Flask + Jinja + psycopg2, `tiers.py`, `search.py`, `forms.py`), with tests against Docker PostgreSQL only.
- Database changes go in a new re-runnable `sql_postgres/08_admin_levels.sql`. `07b_demo_users.sql` is updated to the four levels.
- No new Python dependencies.

## 6. Calls I made (check them)
- Last-seen tracking: `wsb.app_user.last_seen` + `last_page`, updated at most once a minute per person.
- Demo users: `demo_tier1` → Top admin, `demo_tier1_backup` → Admin, new `demo_editor` → Tier 2 can edit, `demo_tier2` → Tier 2 view only. `demo_tier2_licenses` becomes a Tier 2 view-only user (no license access anymore).
- The top-bar badge shows the level name ("Top admin", "Tier 2 · can edit").
