# Handover guide: running the Water School fleet websites yourself

Everything you need is in this repository. You start with an **empty database** and fill it with your own data;
no data from the student team is included or needed.

You'll end up with two websites on your own database:

- **Fleet site** for staff (sign-in): vehicles, maintenance, trips, fuel, documents, stats, imports, approvals.
- **Vehicle request site** for requesters: pick dates, see what's free, send a request.

Time needed: about 30 minutes, then however long your data takes to import.

---

## 1. What you need

| Thing | Notes |
|---|---|
| A **PostgreSQL** database | **Supabase** (free plan is enough), PostgreSQL on an FGCU server, or PostgreSQL on a computer (manage it with pgAdmin if you like). The websites don't run on SQL Server; the SQL Server files in the top folder are the original design only. |
| **Python 3.11 or newer** | On the computer or server that will run the websites |
| This repository | `git clone https://github.com/EvanG64/Vehicle-Database--FGCU-Water-School-.git` (or download the ZIP from GitHub) |

## 2. Install

```
cd Vehicle-Database--FGCU-Water-School-/dashboard
python -m pip install -r requirements.txt
```

## 3. Connect to your database

Copy `dashboard/.env.example` to `dashboard/.env` and fill it in:

- `DATABASE_URL`: your database's connection string.
  - **Supabase:** your project → **Connect** (top bar) → **Session pooler** → URI. Replace `[YOUR-PASSWORD]`.
  - **Your own PostgreSQL:** `postgresql://USER:PASSWORD@HOST:5432/water_school_fleet`
- `SECRET_KEY` and `RESERVE_SECRET_KEY`: two different long random texts. Make each with
  `python -c "import secrets; print(secrets.token_hex(32))"`

**Never put `.env` on GitHub.** It holds your database password. The repository's `.gitignore` already leaves it out.

## 4. Set up the empty database (no SQL needed)

```
python setup_database.py
```

It runs the setup files from `sql_postgres/` in the right order and says `Ready.` at the end. It's safe to run
again. On your own PostgreSQL, if the database doesn't exist yet, use `python setup_database.py --create-db`.

Want a practice copy with fictional vehicles first? Set up a **separate** database with `--sample`.
Never use `--sample` on the real one.

## 5. Make the first account

```
python create_admin.py
```

It asks for a name, email, username and password, and makes a **Tier 1 (top admin)** account. Everyone else is
added on the website under **Admin → People**. Forgot a password? `python set_password.py <username or email>`.

## 6. Start the websites

```
python app.py            fleet site:    http://localhost:5000
python reserve_app.py    request site:  http://localhost:5001   (in a second window)
```

Sign in to the fleet site with the account from step 5.

## 7. Bring in your data

On the fleet site: **Add → Import a spreadsheet**. You choose what the file holds, match its columns, check
every row, and only then save. A file with a problem saves nothing until it's fixed. Import in this order,
because each step uses the one before:

| Order | Choose | From | Notes |
|---|---|---|---|
| 1 | Vehicles | Your fleet list | Property tag and type are required. Add the rest later on each vehicle's page if needed. |
| 2 | Drivers | Your driver list | License numbers are shown masked and saved for Tier 1 only. |
| 3 | Maintenance schedules | What needs doing and how often | e.g. "Oil Change, every 6 months or 5,000 miles, last done 3/10/2026" |
| 4 | Maintenance / repairs | "Vehicle and Boat Maintenance" sheet | Read as it is, including Purchaser, Funding source and P-Card Workday # |
| 5 | Fuel purchases, Trips | WEX exports, mileage logs | Trips need the driver's email and an approved driver |

Vehicles can be named by property tag or by name ("2013 Ford F-150", "Mako"); the review screen suggests the closest
match if a name is off. Spreadsheets only (.xlsx or .csv, the first sheet, up to 2,000 rows a file). PDFs and scans go
on each vehicle's page under **Documents**.

## 8. Before people use it for real

- **Run it on a server, not a laptop.** `python app.py` is fine for trying it out. For everyday use, run it on an
  FGCU server or a hosting service with a production server such as `waitress`
  (`python -m pip install waitress`, then `waitress-serve --port=5000 app:app`), so it's always on.
- **Set `FLEET_URL` and `RESERVE_URL`** in `.env` to the sites' real addresses, so links in emails work.
- **Email:** until `SMTP_HOST` and friends are set, emails wait in an outbox you can read on each request.
  Options are in `dashboard/docs/reservations.md`.
- **Uploaded documents** are saved in `dashboard/uploads/` on the computer running the site. Back that folder up.
- **Tests:** after any change, `python -m pytest -q` (needs Docker; see `dashboard/README.md`).

## Where to read more

| File | About |
|---|---|
| `README.md` | What's in the repository |
| `dashboard/README.md` | Settings, sign-in, tiers, code map, tests, speed |
| `dashboard/docs/reservations.md` | How requests and approvals work, email options |
| `sql_postgres/README.md` | Every setup file and what it does |
| `MANUAL.md` | The original SQL Server design |
