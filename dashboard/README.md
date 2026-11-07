# Water School Fleet website: maintainer guide

A Flask website on top of the `wsb` PostgreSQL schema (Supabase for the real data).
Search-first, black and white, with the client's access tiers. For how to *use* it, see the in-site Help page (`/help`).

## Run it

```
cd dashboard
python app.py
```

Open http://localhost:5000. The database connection comes from `DATABASE_URL`:

- **Supabase (real data):** put the Session pooler URI in `dashboard/.env` as `DATABASE_URL=...` (copy `.env.example`).
  Percent-encode special characters in the password, or use a letters-and-numbers password.
- **Local PostgreSQL:** without `.env` it uses `dbname=water_school_fleet user=postgres host=localhost`.

Set `SECRET_KEY` in `.env` too. Without it a random key is made at every start, which signs everyone out on restart.

## Database setup

Run the files in `../sql_postgres/` in order (see the README there): `01`–`05`, then `07_web_access.sql`
(the "license access" switch), `08_admin_levels.sql` (the four access levels, activity log and who's online) and `09_demo_users.sql`
(fictional demo users, to remove once the real list arrives).
On Supabase: SQL Editor → paste a file → Run. Never run `03b_demo_data.sql` on the real project.

## Access tiers

All rules live in `tiers.py`:

- **Tier 1** = `wsb.app_role.role_name = 'Admin'`: view, add, edit, delete.
- **Tier 2** = any other role: view only.
- **License access** = `wsb.app_user.can_see_licenses`: driver's license records (the client's "Tier 3").

People are rows in `wsb.app_user`. To give someone access, add a row with their FGCU email, a role and the license switch.

## Sign-in (placeholder)

`/login` shows "Sign in with FGCU". Until FGCU IT connects real single sign-on, `/login/fgcu` forwards to a
demo sign-in (`/login/account`). It only lists and accepts the fictional `@example.edu` users,
so real people in `wsb.app_user` can't be signed in as through it.

**Where real sign-in plugs in:** replace `login_fgcu()` in `app.py` with the FGCU / Microsoft Entra ID flow, and
when it returns the person's email, call `sign_in_email(email)`. That function is the only place a session is created.
Unknown or inactive emails get the "You don't have access yet" page. Then remove the demo sign-in routes.

## Code map

| File | What it does |
|---|---|
| `app.py` | Routes: sign-in, search, vehicle page, forms, maintenance, documents, help |
| `tiers.py` | Who someone is and what their tier allows |
| `search.py` | Grouped search across vehicles, trips, fuel, maintenance, documents and licenses |
| `forms.py` | Field definitions and form checking for the add / edit forms |
| `templates/` | Pages (`base.html` = top bar, `home.html` = search, `_icons.html` = SVG icons) |
| `static/style.css`, `static/search.js` | Look, and the expanding search bar |

Trips, fuel and services are saved through the database functions in `sql_postgres/05_procedures.sql`,
so the database's own checks apply.

## Tests

Tests use a throwaway PostgreSQL in Docker, never Supabase:

```
docker run -d --name wsb-test-db -e POSTGRES_PASSWORD=test -p 54329:5432 postgres:17
cd dashboard
python -m pytest
```

Each run rebuilds a template database from `sql_postgres/` plus the fictional demo data. Each test gets a fresh copy.

## Handing it over to the Water School

The student team hands this site and database to the Water School. Their IT team decides where it runs.
This is what they need to know.

### 1. Where to run it

Run the site on a **server** (an FGCU server, or a host such as Render or Railway), not on each staff laptop.
Staff then only open a normal web page, which every network allows.
The server, not the staff computer, needs to reach the database.

### 2. Connecting to the database

The connection is one line in `dashboard/.env` (or the host's settings page): `DATABASE_URL=...`.
Copy `.env.example` to start. Never put this line in GitHub.

The server must be able to reach the database on port **5432** (or **6543**).
Campus Wi-Fi and some home networks block these ports, which is another reason to use a server.

If the database stays on Supabase, it gives two addresses (Project Settings → Database → Connect):

| Address | Looks like | Notes |
|---|---|---|
| Session pooler (use this first) | `aws-0-….pooler.supabase.com:5432`, user `postgres.<project ref>` | Works on IPv4 networks. In Nov 2026 it did not answer on one student network. |
| Direct connection | `db.<project ref>.supabase.co:5432`, user `postgres` | Worked when the pooler didn't, but only on networks with IPv6 |

If the site can't connect, test the same `.env` from another network (for example a phone hotspot).
If it works there, the network is blocking the database port.

To move off Supabase to FGCU's own PostgreSQL, run the setup files (step 3) on the new server and change `DATABASE_URL`.

### 3. Setting up a new database

1. Run the files in `../sql_postgres/` in order. See the README there, and skip `03b_demo_data.sql` (fictional).
2. Load the real vehicles and maintenance rules with `03c_real_vehicles.sql`.
   It is confidential (VINs, plates), so it is not on GitHub; the student team hands it over directly.
3. Load the rest of the real data with `04_import_staging.sql` (see "Data still to load" below).

### 4. Before real staff use it

- [ ] Connect real FGCU sign-in (see "Sign-in" above) and remove the demo sign-in routes in `app.py`.
- [ ] Add the real people to `wsb.app_user`, then delete the demo users:
      `DELETE FROM wsb.app_user WHERE email LIKE '%@example.edu';`
- [ ] Set `SECRET_KEY` to a long random value (for example the output of `python -c "import secrets; print(secrets.token_hex(32))"`).
- [ ] Change the database password. The student team knew the old one.
- [ ] Add form protection (CSRF), see "Known limits".
- [ ] `app.py` only listens on `127.0.0.1`. To host it, run it with a production server (for example `waitress` or `gunicorn`)
      behind HTTPS, as FGCU IT requires.
- [ ] Decide where uploaded documents live. Today they are saved in `dashboard/uploads/` on the computer running the site.

### 5. Data still to load

Loaded so far: 73 vehicles, 57 maintenance rules, the WEX code list and the access roles.

| Data | Table(s) | Source |
|---|---|---|
| Maintenance and repair costs | `invoice`, `invoice_line`, `maintenance_record` | FY tabs of `Vehicle and Boat Maintenance.xlsx`, plus the invoice PDFs |
| Fuel | `invoice`, `invoice_line`, `fuel_record` | Monthly WEX statements (PDF), July 2024 onward |
| Trips | `trip` | `FLEET_MILEAGE_LOG.xlsx` |
| Boater safety certificates | `driver_qualification` | `Boaters Safety Cert Info.xlsx` |
| Insurance papers | `vehicle_document` | Fleet insurance PDFs, FY22-23 to FY26-27 |
| Drivers and licenses | `driver`, `driver_license` | Not received yet: ask the Fleet Manager |
| Registrations and titles | `vehicle_document` | Not received yet |
| Who gets a login | `app_user` | Not received yet |

## Known limits

- No protection against forged form submissions (CSRF) yet. Add it (e.g. Flask-WTF) before hosting on a server.
- Runs on 127.0.0.1 only. Don't host it anywhere without FGCU IT approval.
- Uploaded documents are saved in `dashboard/uploads/` on this computer (git-ignored).
- Not built yet (Phase 2): spreadsheet upload, downloads, the sign-in alert pop-up, stats, the admin area.
