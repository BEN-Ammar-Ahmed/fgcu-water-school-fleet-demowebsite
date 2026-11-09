# Water School Fleet website: maintainer guide

A Flask website on top of the `wsb` PostgreSQL schema (Supabase for the real data).
Search-first, black and white, with the client's access tiers. For how to *use* it, see the in-site Help page (`/help`).

## Run it

There are two websites. Both use the same database.

```
cd dashboard
python app.py            # the fleet site:            http://localhost:5000
python reserve_app.py    # the vehicle request site:  http://localhost:5001  (run in a second terminal)
```

The database connection comes from `DATABASE_URL`:

- **Supabase (real data):** put the Session pooler URI in `dashboard/.env` as `DATABASE_URL=...` (copy `.env.example`).
  Percent-encode special characters in the password, or use a letters-and-numbers password.
- **Local PostgreSQL:** without `.env` it uses `dbname=water_school_fleet user=postgres host=localhost`.

Also in `.env` (never in git):

| Setting | What for |
|---|---|
| `SECRET_KEY` | Fleet site sign-in cookie. Without it, everyone is signed out at every restart. |
| `RESERVE_SECRET_KEY` | Same, for the request site. Use a different value. |
| `FLEET_URL`, `RESERVE_URL` | The two sites' addresses, used in links and emails (default `http://localhost:5000` and `:5001`). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`, `MAIL_REPLY_TO` | Real email sending (see `docs/reservations.md`). Without them emails wait in the outbox. |
| `FLEET_CONTACT_EMAIL` | Optional "Questions?" address in the request site's footer. |
| `LOGO_FILE`, `LOGO_WIDE` | Optional: use another logo file from `static/` (e.g. the official FGCU Water School logo). `LOGO_WIDE=1` for a wide logo with the words in it. |

## Database setup

`python setup_database.py` runs the files in `../sql_postgres/` in order on the database in `DATABASE_URL`
(`--create-db` makes a local one first, `--sample` adds fictional practice data). Then `python create_admin.py` makes
the first Tier 1 account. Step by step for a new owner: `../HANDOVER.md`.
By hand instead: run the files in order (see the README there). On Supabase: SQL Editor -> paste a file -> Run.
Never run the files in `sql_postgres/test_data/` on the real project.

## Sign-in

Username (or email) and password. Passwords are stored only as hashes in `wsb.app_user_password`
(`14_passwords.sql`); after 5 wrong passwords in a row an account is locked for 15 minutes.

- **First top admin:** after running `14_passwords.sql`, nobody has a password. Set one from a terminal:
  `python set_password.py <username or email>` (typed hidden).
- **Everyone else:** a top admin adds them in Admin -> People with a password and gives it to them, or uses
  "Set a new password" on their row (this also unlocks a locked account).
- **Changing your own password:** your name in the top bar -> Change password.

Code: `passwords.py` (checks, lockout, hashing), the `login` and `change_password` routes in `app.py`.

## Access tiers

All rules live in `tiers.py`: Tier 1 top admin, Tier 2 editor, Tier 3 viewer, plus per-person switches
(Admin -> People -> Extra abilities). The table is on the Help page.

## Vehicle request site

`reserve_app.py` with its own pages in `reserve_templates/` (it also reuses `templates/form_entry.html`).
Anyone with the link picks free vehicles and sends a request; it lands in the fleet site's Reservations inbox
(`reservations.py`). Shared logic is in `reservation_core.py`. Full description: `docs/reservations.md`.

## Code map

| File | What it does |
|---|---|
| `app.py` | Routes: sign-in, search, vehicle page, forms, maintenance, documents, help |
| `tiers.py` | Who someone is and what their tier allows |
| `search.py` | Grouped search across vehicles, trips, fuel, maintenance, documents and licenses |
| `forms.py` | Field definitions and form checking for the add / edit forms |
| `templates/` | Pages (`base.html` = top bar, `home.html` = search, `_icons.html` = SVG icons) |
| `static/style.css`, `static/search.js` | Look, and the expanding search bar |
| `admin.py` | Admin area: overview, people (tiers, switches, passwords), activity, data |
| `passwords.py`, `set_password.py` | Password checks, lockout and hashing; setting a password from a terminal |
| `setup_database.py`, `create_admin.py` | Set up an empty database from `sql_postgres/`; make the first Tier 1 account |
| `reservations.py` | Reservations inbox on the fleet site (approve, deny, ask for info) |
| `reserve_app.py`, `reserve_templates/` | The separate vehicle request site |
| `reservation_core.py`, `mailer.py` | Shared reservation logic; email outbox and sending |
| `import_views.py`, `importer.py` | Import a spreadsheet |
| `common.py` | Settings, small helpers and the database connections (kept open and reused) both sites use |
| `stats.py` | Spending and trips pages (`/stats/spending`, `/stats/trips`) |

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

1. Run the files in `../sql_postgres/` in order. See the README there, and skip `test_data/` (fictional).
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

## Speed

Every round trip to Supabase takes about 0.1 s, and opening a new connection about 1 s. So:

- Connections are kept open and reused (`common.Database`; up to 6 for the fleet site, 3 for the request site).
- A page's independent queries run at the same time on separate connections (`DATABASE.q_many`), e.g. the search
  groups, the vehicle page sections, the home and admin numbers.
- The Activity log and "last seen" are written in the background after the page is sent (`DATABASE.later`).
- CSS and scripts are cached by the browser for a month; their address changes when the file changes (`asset()`).

Tests switch the pool off (`DB_POOL = False`); `tests/test_db_pool.py` checks it.
