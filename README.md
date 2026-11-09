# FGCU Water School Vehicle Database

A database and two websites for the FGCU Water School fleet (boats, cars, trucks, trailers, golf carts and ATVs):
vehicles, maintenance, trips, fuel, invoices, documents, drivers, and vehicle reservations.

COP 3710 Database Project with Service Learning, Fall 2026. Team Incognito: Evan Goudy (lead), Ahmed Ben Ammar,
Marina Bunyatova, Naila Desgrottes. Community partner: The Water School.

**Taking this over?** Start with [`HANDOVER.md`](HANDOVER.md): set up your own empty database and import your data,
no SQL needed.

## What's in this repository

| Where | What | Start with |
|---|---|---|
| Top folder (`00_…` to `06_….sql`, `MANUAL.md`, `Er_Diagram.jpeg`) | The original database design for **SQL Server**: schema, security, sample data, import staging, data-entry procedures, security tests | [`MANUAL.md`](MANUAL.md) |
| [`sql_postgres/`](sql_postgres/) | The same database for **PostgreSQL / Supabase**, which is what the real database runs, plus the files the websites added (`07`–`15`) | [`sql_postgres/README.md`](sql_postgres/README.md) |
| [`dashboard/`](dashboard/) | The two websites (Python + Flask): the **fleet site** for staff, and the **vehicle request site** | [`dashboard/README.md`](dashboard/README.md) |

```
.
├── 00_create_database.sql … 06_security_tests.sql   SQL Server version (original design)
├── MANUAL.md, Er_Diagram.jpeg                       How the SQL Server version works
├── sql_postgres/                                    PostgreSQL / Supabase version (the real database)
│   └── test_data/                                   Fictional data for practice databases and tests only
└── dashboard/                                       The websites
    ├── app.py, admin.py, stats.py, …                Fleet site (staff, signed in)
    ├── reserve_app.py, reserve_templates/           Vehicle request site (anyone with the link)
    ├── templates/, static/                          Pages, styles and scripts
    ├── tests/                                       Automatic tests (throwaway database in Docker)
    └── docs/                                        Reservations guide; dev-notes/ = build history
```

## The two websites in one minute

- **Fleet site** (`python app.py`, port 5000): search everything, vehicle pages, log trips, fuel and maintenance,
  maintenance schedules and alerts, documents, spending and trip stats, import spreadsheets, approve vehicle
  requests. Three tiers (Top admin, Editor, Viewer) with per-person switches; driver's licenses are Tier 1 only.
  Every change is recorded in the activity log.
- **Vehicle request site** (`python reserve_app.py`, port 5001): pick dates and see which vehicles are free, send a
  request, and get the answer by email. Requests land in the fleet site's Reservations inbox.

Setup, settings, sign-in, tests and the code map: [`dashboard/README.md`](dashboard/README.md).

## Rules for this repository

- **No real data and no passwords on GitHub.** The real vehicle list (VINs, plates), driver's licenses, project
  documents and the `.env` file with the database password stay on your own computer; `.gitignore` keeps them out.
- **Never run `sql_postgres/test_data/` on the real database.** It's fictional data for practice and tests.
- **Run the tests before you push:** `cd dashboard` then `python -m pytest -q` (see the dashboard README).
