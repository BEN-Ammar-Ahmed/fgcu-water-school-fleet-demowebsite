# Typing suggestions and a cleaner admin overview: design

Date: 2026-11-05. Status: draft, waiting for Ahmed's approval.

## Why

Staff type the same vehicles, drivers, vendors and places again and again. Today the search box only shows results
after you press Enter, forms use plain text boxes or long dropdowns, and a typo ("fird") finds nothing.
The admin overview shows too many things at once (counts by level, vehicle types, top 5 vehicles, numbers, alerts,
who's online, recent activity), so it looks cluttered. Admins mainly want to see what needs attention, the fleet
numbers, who is on the site, and a log of who did what and when.

## Goals

1. **Search suggestions.** In the main search bar, after 2 letters, a dropdown shows matches grouped as Vehicles,
   Drivers and Maintenance (and the other search groups where they match, except Licenses), each with a short detail on the right
   (status, type). Arrow keys move, Enter opens the highlighted item, Esc closes, and the last row is
   "See all results". The same dropdown is used for the admin People search and the admin Log search.
2. **Form suggestions.** On the entry forms (log trip, log fuel, log maintenance, add/edit driver, add/edit vehicle):
   - Vehicle and Driver fields become type-to-find boxes that search the same lists the dropdowns use today
     (active vehicles; approved, active drivers with an email for trips). They still submit the same id, so the
     server-side checks don't change.
   - Free-text fields with repeated values suggest values already in the database while you type:
     vendor/station, destination, purpose, project/program, maintenance service type, department, location.
     You can always type something new.
3. **Typo help.**
   - Search: when nothing (or very little) matches, show "No exact match. Did you mean **Ford Ranger**?" with a link
     that reruns the search.
   - Form boxes and the search dropdown include close matches ("Rivra" → "Rivera, Jose") under a "Close matches" label.
   - The site never changes what someone typed on its own. It only suggests, and the person clicks.
4. **Admin overview, layout B** (approved mockup):
   - Top row: four numbers: active vehicles, trips this month, fuel spend this month, total cost this fiscal year.
   - Left (wider) column: "Latest activity", about the last 10 log lines, each with time, person, what happened and,
     for edits, the before → after details on a second line. A "Full log →" link goes to the Activity page.
   - Right column: "Needs attention" (maintenance overdue, due in 30 days, papers expiring in 60 days, each a link to
     the matching list) and "Online now" (name and page for each person seen in the last few minutes).
   - Removed from the overview: counts by admin level (move to the top of the People tab), vehicle types, and
     top 5 vehicles (dropped for now).
5. **A fuller log.**
   - Edits record each changed field as `Field: old → new` (for example `Mileage: 41,200 → 42,050`,
     `Status: Active → In shop`). This covers vehicle edits, driver edits, admin level and access changes, and any
     other edit route that changes an existing row. Adds and deletes keep their current one-line summary.
   - Sign-outs are logged (`kind = 'sign-out'`).
   - The Activity page shows the detail line too, and its "What" filter gets a Sign-outs choice.

## Non-goals

- No spell-checking of long free text (notes, descriptions).
- No auto-correct: nothing is replaced without a click.
- No AI or outside service. Matching runs in the database.
- No new charts or stats on the overview (that's still Phase 2).
- Old log lines are not rewritten. Only new edits get before → after detail.

## Anti-goals (would count as a failure even if it works)

- Suggestions that show something the person isn't allowed to see. The suggestion endpoint must use the same access
  rules as search (`search.py`): document access levels, drivers and licenses for Tier 1 only, and so on.
- Slow typing. Suggestions must not make the box lag. Wait for a short pause (about 200 ms) before asking the server,
  and cancel older requests.
- Confidential values in the log detail. License numbers, VINs and similar fields show as "changed" without the
  values. The builder lists which fields count.
- Losing the current form checks. Forms still go through the same database functions and `forms.parse`.
- A cluttered dropdown. At most about 8 rows, grouped, with the matched letters in bold.

## Constraints

- Flask + Jinja templates + plain JavaScript (no framework, no build step), matching `static/search.js`.
- PostgreSQL (Supabase now, possibly FGCU's own server later). Schema changes go in a new numbered file in
  `sql_postgres/` (for example `10_suggestions.sql`) so a fresh setup picks them up, and are listed in its README.
- The activity log is append-only (trigger in `08_admin_levels.sql`). New columns are added with `ALTER TABLE`;
  existing rows are not updated.
- The `kind` check on `wsb.activity_log` must allow `'sign-out'`.
- Keyboard and screen reader friendly: the boxes use the standard combobox pattern (`role="combobox"`,
  `aria-expanded`, `aria-activedescendant`, a `listbox` of options).
- Works without JavaScript: the form still submits (vehicle/driver fall back to the current `<select>`), and search
  still works on Enter.
- Tests in `dashboard/tests/` (pytest), as today.

## Decided

- Layout B for the admin overview (Ahmed picked it from the mockup).
- All three suggestion features: search, forms, typos (Ahmed).
- Before → after detail for edits (Ahmed).
- Sign-ins, sign-outs, changes and who did them are what the log is for (Ahmed).

## Claude's calls (Ahmed can overrule)

- Fuzzy matching uses PostgreSQL's `pg_trgm` extension (`similarity()` / `%` and trigram indexes). Supabase supports
  it, and so does any normal PostgreSQL server. Plain prefix/contains matches rank first, close matches after.
- One JSON endpoint, for example `GET /suggest?field=<name>&q=<text>`, returns grouped suggestions. Search, People,
  Log and each form field ask it with a different `field`. Unknown `field` values return an empty list.
- Suggestions for free-text fields come from distinct values already stored in that column (for example
  `SELECT DISTINCT vendor FROM wsb.fuel_record ...`), most used first.
- Log detail is stored in a new nullable `details` column (JSON list of `{field, old, new}`, or text) on
  `wsb.activity_log`, and shown as a second line under the summary.
- Admin level counts move to the top of the People tab as a small row of chips.
- "Online now" keeps the current rule (seen in the last `ONLINE_MINUTES`).
- **Suggestions and privacy.** Driver licenses never appear in suggestions. They stay reachable only through the
  full search, which is already logged. Suggestion lookups themselves are not logged (they fire on every pause in
  typing). Opening a page from a suggestion is logged as a view, as today. Documents appear in suggestions only by
  type and vehicle, with the same access-level filter as search.
- **People and Log dropdowns** suggest people's names (and emails on People). Picking one fills the box and filters
  the list to that person, instead of opening a page. So the shared dropdown has two modes: "go to page" (main search,
  vehicle/driver links) and "fill and filter" (People, Log, and the free-text form fields).
- **If `pg_trgm` is missing** (for example FGCU IT won't allow extensions), the site still works. The app checks once
  at startup, and without it, suggestions use plain "starts with / contains" matching, with no close matches and no
  "Did you mean". `10_suggestions.sql` creates the extension only if it's allowed. On Supabase it lives in the
  `extensions` schema, so SQL calls name it with the schema (`extensions.similarity(...)`).
- **Edits that get before → after detail:** vehicle edit, driver edit (license fields show "changed" without values),
  admin level and access changes, and "Mark done" on a schedule rule (`Last done: Mar 2 → Nov 6`). Mileage that the
  database functions update while logging a trip, fuel or service is not treated as an edit. The trip/fuel/service
  log line already says what was logged.

The approved mockups are in `dashboard/docs/mockups/` (`admin-layout.html`, layout B; `typing-suggestions.html`).
Names and numbers in them are made up.

## Left to the builder

- Exact similarity thresholds and how many rows per group.
- Which fields are confidential in the log detail (at least: license number, VIN, plate, anything Tier 1 only).
- How edit routes collect the "before" row (most already load it).
- Styling details, reusing `static/style.css` tokens.
- Whether the suggestion endpoint needs its own rate limit (probably not for a small staff site).
