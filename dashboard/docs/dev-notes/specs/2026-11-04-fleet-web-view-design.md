# Water School Fleet: web view redesign

**Date:** 2026-11-04 · **Author:** Ahmed Ben Ammar · **Status:** draft for approval

## 1. Intent and why

The Water School (FGCU) keeps its fleet records (boats, trucks, cars, trailers, golf carts) as files in Microsoft Teams folders: no search and no access control. The client, Reagan, asked for a web-based system that staff sign in to with their work account, where they can **find anything quickly** and where **access is tiered**, so sensitive records like driver's licenses are seen only by a few people.

The database (PostgreSQL on Supabase, schema `wsb`, files in `sql_postgres/`) is done. A prototype dashboard exists in `dashboard/` (Python Flask + Jinja templates). Its look and structure don't match what the client asked for, and an earlier Claude Design attempt didn't either: it used a role picker instead of a work-account sign-in, let a "Staff" role edit when the client's Tier 2 is view-only, designed for phones, and had no real search.

This redesign makes the site **search-first, plain black and white, desktop-first**, built around the client's three access tiers.

**What success looks like:** the new fleet manager signs in, types a vehicle name, and gets everything about it (trips, fuel, maintenance, documents) on one screen. Reagan can see who has access to what and change it herself, and nobody sees data above their tier.

## 2. Users and access tiers

From the client meeting:

| Tier | Who | Can do |
|---|---|---|
| **Tier 1** | Fleet manager + one backup (at least 2 people) | Everything: view, search, add, edit, delete, upload spreadsheets, download, admin area |
| **Tier 2** | Frequent users and main-campus staff (insurance, vehicle use) | View, search, download only what they can see. **No adding or editing.** |
| **Tier 3** | About 3 people | Can open the **driver's license** records |

- **Tier 3 is an extra permission, not a level below Tier 2.** *(My call: the client described it as a restricted folder visible to ~3 people. Those people are probably Tier 1 staff, so Tier 3 is a "can see licenses" switch that can be turned on for a Tier 1 or Tier 2 person.)*
- Add / edit / delete is **Tier 1 only**. *(My call, from the meeting notes: Tier 2 is view-only.)*
- Everyone must be signed in. There's no public page apart from the sign-in screen.
- Primary users are on desktops and laptops. Phones are not a priority.

## 3. Goals, non-goals, anti-goals

**Goals**
1. Search-first home page with the expanding search bar (section 5.2).
2. FGCU sign-in as a placeholder, plus a demo tier switcher until the real sign-in exists.
3. Vehicle page with everything about one vehicle.
4. Add and edit records (Tier 1).
5. Upload spreadsheets in bulk with a preview before saving (Tier 1).
6. Download what you're looking at.
7. Pop-up maintenance alerts at sign-in.
8. Stats and charts.
9. Admin area: who's signed in, activity, who can see what.
10. Help / instruction page.

**Non-goals (not now)**
- Real FGCU / Microsoft single sign-on. It's a placeholder, and Reagan or FGCU IT connects it later.
- Live GPS tracking (the client has no access to that data yet).
- Phone layouts beyond "doesn't break".
- Push notifications or email alerts (the client prefers pop-ups).
- Migrating the real Teams files. The client labels what can be used first.

**Anti-goals (a failure even if it "works")**
- **Anyone seeing data above their tier**, in any form: page, search result, download or count. Driver's license data in particular.
- **Real confidential data on GitHub**, in screenshots or in class demos. Demos use the fictional demo data (`sql_postgres/03b_demo_data.sql`) or data the client has labeled shareable.
- A busy, colorful, generic "SaaS dashboard" look. The client and Ahmed want plain and calm.
- A search box that's just decoration. It has to actually find vehicles, trips, documents and dates.

## 4. Constraints

- **Build on what exists:** Flask + Jinja in `dashboard/`, the `wsb` schema on Supabase (PostgreSQL 17), and the existing connection via `dashboard/.env` (`DATABASE_URL`). Don't switch frameworks.
- **The database is the source of truth for rules:** tables, views (`v_maintenance_due`, `v_cost_by_vehicle_fy`, `v_fuel_efficiency`, `v_expiring_items`, ...), data-entry functions (`wsb.add_trip`, `add_fuel`, `add_invoice`, `add_invoice_line`, `add_maintenance`), import staging tables (`wsb.stg_*`) and the audit log (`wsb.audit_log`, filled by triggers). Reuse them instead of re-writing the logic in Python.
- **Changes to the database go in `sql_postgres/`** as re-runnable SQL, matching the style of the existing files, and keep the Supabase lock-down (`wsb.lock_out_public_api()`).
- **Confidential:** `dashboard/`, `.env`, real-data SQL files, `project_files/` and uploaded files stay out of git (already in `.gitignore`).
- **Look:** black, white and grays only. The only color is a small red / amber on overdue / due-soon warnings *(my call, so warnings stand out)*. Never show status by color alone; always include the word. Light theme. *(Dark mode is optional; my call to skip it unless it's easy.)*
- **Desktop-first:** design for 1280–1920px wide. Below about 900px it only has to stay usable.

## 5. What gets built

### 5.1 Sign-in (placeholder)
- The page has the site name and one button: **"Sign in with FGCU"**. Under it, small print says FGCU sign-in will be connected by FGCU IT.
- Until the real sign-in exists, clicking it opens a **demo sign-in**: pick a person from the app's user list (`wsb.app_user`). Their tier and license access come from the database, not from a role picker.
- Build it so the real sign-in can replace the demo with minimal changes: one function that turns "who signed in" (an email) into a user record with a tier. *(My call: FGCU uses Microsoft accounts, so this would likely become Microsoft Entra ID sign-in later.)*
- Unknown emails get a "You don't have access yet. Ask the fleet manager." page.

### 5.2 Home page: search
This was decided with a clickable mockup. Keep the behavior and feel:
- The page starts almost empty: a top bar (site name on the left, signed-in person and their tier on the right) and **one round button in the middle with a clean magnifying-glass line icon** (SVG, not an emoji).
- **Clicking it stretches the button sideways into a full search bar** (smooth, about 0.45s). "What are you looking for?" fades in above it, and category buttons fade in below it: **All, Vehicles, Trips, Fuel, Maintenance, Documents**. The overdue / due-soon counts show under those.
- **Enter** searches: the bar **slides up to the top**, and the results fill the page, grouped by type with a count per group (e.g. "Trips · 12"). Clicking a category button narrows the results to that type.
- **Esc** closes the bar before searching. Typing `/` anywhere opens it *(my call)*.
- The search should understand vehicle names, property tags, plates, VIN / hull number, driver names, destinations, vendors, document types and dates (e.g. "October", "2026-10-03"). Each result links to where it lives (vehicle page, trip, document).
- After searching, a **filter row** appears for the selected type, for example Trips: vehicle, driver, from / to date. This covers the client's "search and filter by vehicle, trip, date".
- Results respect tiers (section 2). Driver's license results appear only for people with license access.
- Reference mockup: `.superpowers/brainstorm/7998-1793841585/content/search-expand.html` (local only).

### 5.3 Top bar and navigation
- Always visible after sign-in: site name (click = home), a compact search bar once you've searched, **+ Add** (Tier 1), **Admin** (Tier 1), **Help**, and the person's name and tier with a sign-out option.
- No big sidebar. Home is search, and everything else is reached from results or the top bar. *(My call, to keep the "almost empty" feel.)*

### 5.4 Vehicle page
- Header: vehicle name (year, make, model, or the original spreadsheet description), type, property tag, status shown as a word badge, and **Edit** / **Delete** (Tier 1).
- Sections on one page: **Details** (plate, VIN / hull, department, location, mileage or engine hours, notes), **Maintenance** (rules, last done, next due, status, and "Mark done" for Tier 1), **Trips**, **Fuel**, **Costs** (by fiscal year), **Documents** (filtered by access level).
- Each section has **Download** and, for Tier 1, **Add**.

### 5.5 Add and edit (Tier 1)
- Forms for vehicle, trip, fuel, maintenance record, maintenance rule, invoice with lines, document upload and driver (license fields need license access).
- Use the database functions where they exist (`wsb.add_trip`, ...) so the database's own checks and messages are reused. Show database error messages in plain English next to the form.
- Every change is already recorded by the audit triggers.
- Delete asks for confirmation. Tier 1 only.

### 5.6 Upload spreadsheets (Tier 1)
- For the three existing sources: **mileage log**, **WEX activity report**, **maintenance sheet**. They match `wsb.stg_mileage_log`, `stg_wex_activity` and `stg_maintenance_sheet`, and the import steps in `sql_postgres/04_import_staging.sql`.
- Flow: choose source → upload CSV / Excel → **preview** showing how many rows will import, which rows have problems and why (unknown vehicle name, unknown driver, unreadable date) → fix the vehicle-name matches (`wsb.stg_vehicle_map`) on the page → **Import** → summary of what was added.
- Nothing is saved to the real tables until **Import** is clicked.

### 5.7 Download data
- A **Download** button on search results, filtered lists and vehicle-page sections gives you exactly what's on screen, with the same filters.
- Format: **Excel-friendly CSV** *(my call; the question "what do they do with it next" wasn't answered. If they need Excel or PDF reports, add them later)*.
- Downloads follow the same tier rules as the screen.
- Downloads are recorded in the activity log (who, what, when).

### 5.8 Pop-up maintenance alerts
- Right after sign-in, a pop-up lists what's **overdue** and **due soon** (from `wsb.v_maintenance_due` / the dashboard's maintenance logic), plus documents and licenses expiring in the next 60 days (licenses only for license access).
- Buttons: **View** (goes to the item) and **Dismiss**. It doesn't come back until the next sign-in *(my call)*.
- The thresholds (miles / months) come from the maintenance rules. The client will supply real values later, so the pop-up must handle "no rules yet".

### 5.9 Stats and charts
- One stats page: fuel spend per month and per vehicle, trips per month, how often each vehicle is used, maintenance cost per fiscal year (from `v_cost_by_vehicle_fy`) and fuel efficiency (`v_fuel_efficiency`).
- Black and gray charts, with a filter for date range and vehicle type, and a Download for each chart's numbers.
- Visible to Tier 1 and Tier 2 *(my call)*.

### 5.10 Admin area (Tier 1)
- **Overview:** total vehicles, trips this month, fuel spent this month, overdue maintenance and active users.
- **Who's signed in now:** name, tier and when they signed in. "Now" means active in the last 15 minutes *(my call)*.
- **Activity:** a searchable list of who **viewed**, **changed**, **downloaded** or **imported** what, and when. Changes come from `wsb.audit_log`. Views, downloads, sign-ins and imports are **new**: the site records them in a new table (for example `wsb.activity_log`, added through `sql_postgres/`). Tier 1 cannot edit or delete entries.
- **People and access:** list of users with tier and license access. Tier 1 can add a person (name, FGCU email), change their tier, turn license access on or off, or deactivate them. Each change is logged.
- **What each tier can see:** a plain table explaining the tiers (replaces the old "Roles" page).

### 5.11 Help page
- A plain-English guide inside the site: how to search, what each tier can do, how to add records, how to upload each spreadsheet (with the expected columns), how to download, and who to contact for access.
- Plus a short **maintainer guide** in the repo (how to run the site, connect to Supabase, run the SQL files and where FGCU sign-in plugs in). The client listed an instruction manual as a core requirement.

## 6. Look and feel
- Black, white and grays. One typeface, clear sizes. Generous white space.
- Status as word badges (Available, In Use, In Maintenance, Out of Service, Retired, Overdue, Due soon, OK).
- Line icons (SVG) only, no emoji.
- Smooth but quick animations (about 0.2–0.45s), only where they help: the search bar opening and moving, the pop-up appearing.
- Keyboard: everything reachable by Tab, `/` opens search, Esc closes, and the focus ring is visible.

## 7. Calls already settled (my calls; check them)
- **Change the existing dashboard in place, don't start over.** Keep the routes and database helpers that work (vehicles, maintenance, documents) and replace the templates and CSS. Add new routes for search, upload, download, stats, admin and help.
- **Tiers in the database:** reuse `wsb.app_role` (Admin = Tier 1, Read-only = Tier 2; the existing "Staff" edit role is not used by the site) and add a `can_see_licenses BOOLEAN` column to `wsb.app_user` for Tier 3. It's added in `sql_postgres/` as a re-runnable change.
- **Driver data for Tier 2:** they see driver names on trips (as in `v_driver_directory`), but not emails, license numbers or license files.
- **Documents for Tier 2:** they see `General` and `Staff` access-level documents. `Admin`-level documents (e.g. titles) are Tier 1 only.
- **Demo users:** until Reagan sends the real list, seed a few fictional users (`@example.edu`), one per tier and one with license access, so the demo sign-in works.
- **Spreadsheets:** accept `.csv` and `.xlsx`.

## 8. Left to the builder
- How search is implemented: PostgreSQL full-text search, `ILIKE` across columns or a mix. It must be fast on the real data (73 vehicles now, thousands of trips and fuel rows later).
- Chart library (a small one loaded from an allowed CDN, or plain SVG).
- Where uploaded documents are stored (today: `dashboard/uploads/`, local and git-ignored). Moving to Supabase Storage is fine if it stays private.
- How the database-side tiers map to the existing roles (`wsb_admin`, `wsb_staff`, `wsb_readonly`) versus app-level checks. The site connects as the database owner today, so the app must enforce tiers itself. Keep the database roles consistent where practical.
- Page structure, template organization and CSS approach within Flask / Jinja.

## 9. Open items for the client (not blocking)
- The list of people per tier, with emails (Reagan is sending it).
- Real maintenance thresholds (Reagan is reviewing old documents).
- Which data is shareable for class demos (Reagan is labeling it in Teams).
- How FGCU sign-in will be connected (Reagan / FGCU IT).
