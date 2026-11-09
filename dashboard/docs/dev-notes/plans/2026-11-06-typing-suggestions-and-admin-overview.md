# Typing Suggestions and Admin Overview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Suggestions while typing (search, forms, typos), a before → after activity log with sign-outs, and the
cleaner layout-B admin overview.

**Architecture:** One new SQL file adds `pg_trgm` (when allowed), a `details` column and the `'sign-out'` kind to
`wsb.activity_log`. A new `suggest.py` module answers `GET /suggest?field=&q=` with grouped JSON, using the same
access rules as `search.py`. A new `static/suggest.js` turns any input with `data-suggest` into an accessible
combobox. Edit routes diff the row before and after saving and pass the diff to `log_activity`.

**Tech Stack:** Flask, Jinja, psycopg2, PostgreSQL 17 (+ `pg_trgm`), plain JavaScript, pytest (Docker test DB,
see `tests/conftest.py`).

**Spec:** `dashboard/docs/dev-notes/specs/2026-11-05-typing-suggestions-and-admin-overview-design.md`. Mockups are in
`dashboard/docs/dev-notes/mockups/` (`admin-layout.html` layout B, `typing-suggestions.html`).

## Global Constraints

- No framework or build step for JS. Plain JS like `static/search.js`.
- Schema changes only in `sql_postgres/10_suggestions.sql`. List it in `sql_postgres/README.md` and in `SQL_FILES` in `tests/conftest.py`.
- The activity log stays append-only. Use `ALTER TABLE` only and never update old rows.
- Suggestions show after 2 characters, wait about 200 ms after typing stops, show at most 8 rows, and cancel older requests.
- Driver licenses never appear in suggestions. Suggestion calls are not logged.
- The site never replaces what someone typed. It only suggests.
- Confidential fields in log details show as `changed` with no values: `license_number`, `state`, `license_expiration`, `vin`, `license_plate`.
- Without `pg_trgm`: only starts-with/contains matches, no close matches and no "Did you mean".
- Without JavaScript, forms still submit (vehicle/driver stay `<select>`) and search works on Enter.
- Combobox markup: `role="combobox"`, `aria-expanded`, `aria-controls`, `aria-activedescendant`, and a `role="listbox"` of `role="option"`.

## Review Focus

1. Text with `%`, `_`, `\` or quotes typed into a suggestion box must match literally and never error. Use `search.escape_like` and parameters only. Test in Task 3.
2. A Tier 2 or editor user calling `/suggest?field=driver` or `field=search` must not get drivers (admin only) or licenses. Test in Task 3.
3. If an edit saves nothing new (same values), the log line has no detail line and no empty `details` list. Test in Task 2.
4. A database without `pg_trgm` must still answer `/suggest` with 200 and starts-with results. Test in Task 3 by forcing `suggest.HAS_TRGM = False`.
5. Unknown `field` values or 1-character text return `{"groups": [], "did_you_mean": null}` with 200, not a 500. Test in Task 3.

---

### Task 1: Database: `10_suggestions.sql`

**Files:**
- Create: `sql_postgres/10_suggestions.sql`
- Modify: `sql_postgres/README.md` (add the file to the run order), `dashboard/tests/conftest.py` (`SQL_FILES` += `'10_suggestions.sql'`)
- Test: `dashboard/tests/test_suggestions_sql.py`

**Interfaces:**
- Produces: `wsb.activity_log.details JSONB NULL` (a list of `{"field","old","new"}`). The `kind` check allows
  `'sign-out'`. `pg_trgm` is installed when allowed (on Supabase it lives in schema `extensions`). There are GIN trigram
  indexes on `vehicle` text (make, model, notes, asset_number, license_plate), `driver` names, and the free-text
  columns: `fuel_record.vendor`, `trip.destination`, `trip.purpose`, `trip.project_program`,
  `maintenance_record.service_type`, `maintenance_record.vendor`, `vehicle.location`, `vehicle.department`.

- [ ] **Step 1: Write failing tests** `test_activity_allows_sign_out` (insert with `kind='sign-out'` succeeds),
  `test_activity_has_details_column` (insert with `details='[{"field":"status","old":"A","new":"B"}]'::jsonb` and read it back),
  `test_old_rows_still_append_only` (an `UPDATE` still raises `The activity log cannot be changed or deleted.`).
- [ ] **Step 2: Run** `pytest tests/test_suggestions_sql.py -v`. Expect a FAIL on the kind check and the missing column.
- [ ] **Step 3: Write the SQL.** Wrap `CREATE EXTENSION IF NOT EXISTS pg_trgm` in a `DO` block that catches
  `insufficient_privilege` / `feature_not_supported` and raises a `NOTICE`. Create the indexes only `IF EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_trgm')`,
  using the opclass qualified with the extension's schema (look it up from `pg_extension.extnamespace`). Replace the kind check
  constraint (drop by name, then add with the 6 kinds). Make it idempotent like `08_admin_levels.sql`.
- [ ] **Step 4: Run** the same tests. Expect a PASS. Then run the whole suite with `pytest`, and expect all to pass.
- [ ] **Step 5: Commit** `Add pg_trgm, activity details column and sign-out kind`

### Task 2: A fuller log (before → after, sign-outs)

**Files:**
- Create: `dashboard/changes.py`
- Modify: `dashboard/app.py` (`ACTIVITY_KINDS`, `log_activity`, `logout`, `vehicle_edit`, `_save_driver`, `maintenance_done`),
  `dashboard/admin.py` (`change_level`, `change_access`, `ACTIVITY_KINDS`), `dashboard/templates/admin/activity.html`
- Test: `dashboard/tests/test_changes.py`, extend `dashboard/tests/test_activity.py`

**Interfaces:**
- Produces: `changes.diff(before: dict, after: dict, labels: dict[str, str], hidden: frozenset[str] = HIDDEN) -> list[dict]`
  returns `[{"field": label, "old": str, "new": str}]` only for keys in `after` whose value differs after normalising
  (None and '' are the same; numbers keep thousands separators: `41,200`; dates as `Mar 02, 2026`; booleans as `Yes/No`).
  Hidden keys give `{"field": label, "old": None, "new": None, "hidden": True}`.
  `changes.HIDDEN = frozenset({'license_number','state','license_expiration','vin','license_plate'})`.
  `changes.text(details: list[dict]) -> str` gives `"Mileage: 41,200 → 42,050 · VIN: changed"`.
- Produces: `log_activity(kind, summary, user=None, path=None, details=None)`, which stores `details` as JSONB, or NULL when it is empty.
- Consumes: Task 1's column and kind.

- [ ] **Step 1: Write failing tests** in `test_changes.py`:
  `diff({'status':'Active','mileage':41200},{'status':'In shop','mileage':42050},{'status':'Status','mileage':'Mileage'})`
  `== [{'field':'Status','old':'Active','new':'In shop'},{'field':'Mileage','old':'41,200','new':'42,050'}]`.
  `diff({'notes':None},{'notes':''},{'notes':'Notes'}) == []`.
  `diff({'vin':'1FT…'},{'vin':'2FT…'},{'vin':'VIN'})[0]['hidden'] is True`.
  `text([...]) == 'Status: Active → In shop · Mileage: 41,200 → 42,050'`.
- [ ] **Step 2: Write failing route tests** in `test_activity.py`:
  `test_vehicle_edit_logs_before_after` (edit a demo vehicle's status, and the newest log row's `details` has the Status pair),
  `test_edit_without_changes_has_no_details` (`details IS NULL`), `test_driver_edit_hides_license_values`
  (top admin edits license number, and the detail shows `hidden` with no values anywhere in the row),
  `test_mark_done_logs_last_done` (`field == 'Last done'`), `test_level_change_logs_details` (`field == 'Level'`),
  `test_sign_out_is_logged` (GET `/logout`, and the newest row has `kind == 'sign-out'` and the person's name),
  `test_activity_page_shows_detail_line_and_sign_out_filter` (the page contains `41,200 → 42,050`-style text and `<option value="sign-out"`).
- [ ] **Step 3: Run** `pytest tests/test_changes.py tests/test_activity.py -v`. Expect a FAIL.
- [ ] **Step 4: Implement `changes.py`**, then add `details` to `log_activity`, and log in `logout` *before* `session.clear()`
  (summary `Signed out`). In each edit route, load the before row (vehicle_edit already has `v`, driver_edit loads
  the driver plus latest license, and maintenance_done loads the rule's `last_completed_date/mileage`) and pass `details=diff(...)`.
  Labels come from the form field labels. Activity row: show `changes.text(a.details)` as a muted second line under the summary.
  Add `'sign-out': 'Sign-outs'` to the What filter.
- [ ] **Step 5: Run** the tests from Step 3, and then the full `pytest`. Expect a PASS.
- [ ] **Step 6: Commit** `Log before/after for edits and log sign-outs`

### Task 3: `/suggest` endpoint

**Files:**
- Create: `dashboard/suggest.py`
- Modify: `dashboard/app.py` (register the route `GET /suggest`, `@require()`, not logged, no `page_label`), `dashboard/search.py` (add `did_you_mean`)
- Test: `dashboard/tests/test_suggest.py`

**Interfaces:**
- Produces: `suggest.HAS_TRGM: bool | None` (set on first use by `suggest.trgm_available(q) -> bool`, which checks `pg_extension`).
- Produces: `suggest.suggest(q, user, field: str, text: str) -> dict` returns
  `{"groups": [{"label": str, "items": [{"label": str, "detail": str, "url": str | None, "value": str}]}], "did_you_mean": str | None}`.
  Fields and what they return:
  - `search`: groups Vehicles (url `/vehicles/<id>`, detail = status), Drivers (admin only, url = search for that driver), Maintenance (rules, url = vehicle page `#maintenance`), Documents (type + vehicle, access-level filtered via `tiers.doc_levels`). Never licenses. Last item of the last group: `{"label": "See all results", "url": "/search?q=<text>"}`.
  - `people` (admins only): names and emails from `wsb.app_user`, `url: None`, `value` = name.
  - `activity` (admins only): distinct `full_name` from `wsb.activity_log`, `url: None`.
  - `vehicle`: active vehicles, `value` = vehicle_id, label = `display_name` + asset number (same text as `_vehicle_choices`).
  - `driver`: approved, active drivers with an email, `value` = driver_id.
  - `vendor`, `destination`, `purpose`, `project_program`, `service_type`, `department`, `location`: distinct stored values, most used first, `url: None`.
  - Anything else, or text shorter than 2 chars: `{"groups": [], "did_you_mean": None}`.
  Ranking: starts-with, then contains, then (if `HAS_TRGM`) `similarity() > 0.3` under a group labelled `Close matches`. At most 8 items in total.
- Produces: `search.did_you_mean(q, user, text: str) -> str | None`, the best vehicle make/model, driver name or
  maintenance type with `similarity > 0.3`, or None (always None without trgm). `suggest()` sets `did_you_mean` only when there are no starts-with/contains hits.

- [ ] **Step 1: Write failing tests:**
  `test_short_or_unknown_field_is_empty` (`field=nope` and `q=f` both return `{"groups": [], "did_you_mean": None}`, status 200),
  `test_search_suggests_vehicles_first` (`q` = the first 3 letters of a demo vehicle model, and the first group label is `Vehicles` with a `/vehicles/` url),
  `test_search_never_returns_licenses` (top admin searches a demo license number fragment, and no item mentions it),
  `test_drivers_hidden_from_non_admins` (`demo_editor`, `field=search` gets no Drivers group),
  `test_people_and_activity_admin_only` (`demo_editor` gets empty groups for `people` and `activity`),
  `test_vendor_values_come_from_db` (a demo fuel vendor prefix returns that vendor),
  `test_like_wildcards_are_literal` (`q='%_'` gives 200 and no items),
  `test_typo_close_match` (`q` = a demo make with one letter swapped gives a `Close matches` group or `did_you_mean`),
  `test_works_without_trgm` (monkeypatch `suggest.HAS_TRGM = False`, and the typo query gives empty groups and `did_you_mean` None, while the prefix query still works),
  `test_suggest_not_logged` (the activity_log count is unchanged after 3 calls),
  `test_at_most_8_items`.
- [ ] **Step 2: Run** `pytest tests/test_suggest.py -v`. Expect a FAIL (404 on `/suggest`).
- [ ] **Step 3: Implement** `suggest.py` and `did_you_mean`. User text only goes in as parameters, and LIKE patterns go through `escape_like`.
- [ ] **Step 4: Run** the tests from Step 2, then the full `pytest`. Expect a PASS.
- [ ] **Step 5: Commit** `Add /suggest endpoint with access rules and close matches`

### Task 4: `suggest.js` combobox, wired to the search boxes

**Files:**
- Create: `dashboard/static/suggest.js`
- Modify: `dashboard/templates/base.html` (load the script, `data-suggest="search"` on the top search input), `dashboard/templates/home.html`
  (`data-suggest="search"` on `#q`, plus a "Did you mean" line when there are no results and `did_you_mean` is set),
  `dashboard/templates/admin/people.html` (`data-suggest="people" data-suggest-mode="fill"`), `dashboard/templates/admin/activity.html`
  (`data-suggest="activity" data-suggest-mode="fill"`), `dashboard/static/style.css` (dropdown styles from the mockup), `dashboard/app.py`
  (`search_page` passes `did_you_mean` when every group is empty)
- Test: `dashboard/tests/test_suggest_markup.py`

**Interfaces:**
- Consumes: `/suggest` JSON from Task 3.
- Produces: any `<input data-suggest="<field>">` gets the dropdown. `data-suggest-mode="go"` (the default) opens `url` on Enter or click.
  `fill` puts `label` in the box and submits its form. `pick` (used by Task 5) puts `label` in the box and `value` into the
  hidden input named by `data-suggest-target`. Groups render as non-selectable headings and bold the matched text.
  Esc closes. Down/Up move. Requests are debounced at 200 ms and cancelled with `AbortController`.
  The home page's existing "/" shortcut and expanding search in `search.js` keep working.

- [ ] **Step 1: Write failing markup tests:** the top search input has `data-suggest="search"` and `role="combobox"` is *not* server-rendered
  (JS adds it), the base page loads `suggest.js`, People and Activity inputs have `data-suggest-mode="fill"`, and a search for a misspelled demo make with no results shows `Did you mean` with a link to `/search?q=<fix>`.
- [ ] **Step 2: Run** `pytest tests/test_suggest_markup.py -v`. Expect a FAIL.
- [ ] **Step 3: Implement** the templates, `suggest.js` and the CSS.
- [ ] **Step 4: Run** the tests, then the full `pytest`. Expect a PASS.
- [ ] **Step 5: Check by hand in a browser:** type `f-1` in the top search, and the dropdown shows grouped rows. Arrow + Enter opens the vehicle. Esc closes it. Typing fast sends only the last request (check the Network tab). On People, picking a name filters the list.
- [ ] **Step 6: Commit** `Add typing suggestions to search, People and Activity`

### Task 5: Form suggestions

**Files:**
- Modify: `dashboard/forms.py` (`Field.suggest: str = ''`), `dashboard/templates/form_entry.html`, `dashboard/app.py`
  (set `suggest=` on fields: trip `vehicle_id`→`vehicle`, `driver_id`→`driver`, `destination`, `purpose`, `project_program`;
  fuel `vehicle_id`, `vendor`; maintenance `vehicle_id`, `service_type`, `vendor`; driver `department`), `dashboard/templates/vehicle_form.html`
  (`location`, `department`)
- Test: `dashboard/tests/test_forms.py` (extend)

**Interfaces:**
- Consumes: `suggest.js` `go` / `fill` / `pick` modes from Task 4.
- Produces: text fields with `suggest` render `<input ... data-suggest="<field>" data-suggest-mode="fill" autocomplete="off">`,
  where `fill` must not submit the form on a form page, so add `data-suggest-submit="false"`. Select fields with `suggest` render the existing
  `<select>` (the no-JS fallback) plus `data-suggest="<field>"` on a wrapper. `suggest.js` hides the select and shows a text
  box in `pick` mode that writes the chosen id into the select. A value that's typed but never picked leaves the select empty, so the
  existing "Vehicle is required." error still fires.

- [ ] **Step 1: Write failing tests:** the Log fuel page has `data-suggest="vendor"` on the vendor input and `data-suggest="vehicle"` on the vehicle wrapper,
  the vehicle `<select name="vehicle_id">` is still present, and posting the form with the select value still saves (existing test keeps passing).
- [ ] **Step 2: Run** `pytest tests/test_forms.py -v`. Expect a FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests, then the full `pytest`. Expect a PASS.
- [ ] **Step 5: Check by hand:** on Log fuel, typing `boat 4` lists the matching boats, and picking one and saving works. A typed vendor that's new saves as typed. With JS off, the form still works.
- [ ] **Step 6: Commit** `Suggest vehicles, drivers and past values on entry forms`

### Task 6: Admin overview, layout B

**Files:**
- Modify: `dashboard/admin.py` (`overview`: drop `types`, `top_vehicles`, `top_max`, `by_level`, `people`. Recent becomes the last 10 rows.
  Add `due_30`, the count of maintenance due soon. Keep `overdue`, `nums.expiring`. `_render_people` passes `by_level`), `dashboard/templates/admin/overview.html`,
  `dashboard/templates/admin/people.html` (level count chips at the top), `dashboard/static/style.css`
- Test: `dashboard/tests/test_admin_overview.py` (update), `dashboard/tests/test_admin_people.py` (extend)

**Interfaces:**
- Consumes: `changes.text` from Task 2 for the detail line.
- Produces: the overview page has, in order: four stats (`data-stat="vehicles"`, `"trips"`, `"fuel"`, `"fy"`). Then a two-column
  grid: left `section#activity` ("Latest activity", 10 rows: time, person, summary, detail line, and a "Full log →" link to
  `admin.activity`). Right `section#attention` (overdue → `/maintenance`, due soon → `/maintenance`, papers expiring →
  `/documents`, each with its count) and `section#online` (name and last page). It stacks to one column under 800px.

- [ ] **Step 1: Update and write failing tests:** the overview has the 4 `data-stat` values and no `people`, `online`, `overdue` or `expiring` stat tiles.
  It has no "Most used vehicles" text, has `id="attention"` with the overdue count and links, `id="online"`, and `id="activity"` with at most 10 rows and the
  detail line of a just-made edit. The People page shows the level counts.
- [ ] **Step 2: Run** `pytest tests/test_admin_overview.py tests/test_admin_people.py -v`. Expect a FAIL.
- [ ] **Step 3: Implement** to match `docs/dev-notes/mockups/admin-layout.html` option B, using existing `style.css` tokens.
- [ ] **Step 4: Run** the tests, then the full `pytest`. Expect a PASS.
- [ ] **Step 5: Check by hand** at desktop width and at a 375px width. Nothing overlaps and the page doesn't scroll sideways.
- [ ] **Step 6: Commit** `Admin overview: layout B, level counts move to People`

### Task 7: Final check

- [ ] **Step 1:** Run the full `pytest`. Everything passes.
- [ ] **Step 2:** In a browser, go through the spec's Goals 1–5 once with `demo_tier1` and once with `demo_editor`.
- [ ] **Step 3:** Update `dashboard/README.md`. Mention `10_suggestions.sql` in setup step 3, and remove "the admin area" from "Not built yet".
- [ ] **Step 4: Commit** `Docs: suggestions and admin overview`
