# PostgreSQL / Supabase version of the database

These files are the PostgreSQL version of the SQL Server scripts in the top folder (`../`).
They make the same tables, views, roles and data-entry steps, and they run on
Supabase (PostgreSQL 17) or a local PostgreSQL.

## Run order

| File | What it does | Supabase (real data) | Empty practice database |
|---|---|---|---|
| `00_create_database.sql` | Creates `water_school_fleet` | Skip | Run first |
| `01_schema.sql` | Tables, audit triggers, indexes, report views | Run | Run |
| `02_security.sql` | Admin / Staff / Read-only roles and permissions | Run | Run |
| `03_reference_data.sql` | WEX code legend, role list | Run | Run |
| `03b_demo_data.sql` | Fictional demo vehicles, drivers, invoices (also used by the dashboard tests) | **Never** | Optional |
| `03c_real_vehicles.sql` | The real 73 vehicles and 57 maintenance rules. Confidential: kept on your computer, not on GitHub | Already loaded | Skip |
| `04_import_staging.sql` | Tables and steps for importing the spreadsheets | Run | Run |
| `05_procedures.sql` | Data-entry functions (`add_trip`, `add_fuel`, ...) | Run | Run |
| `06_security_tests.sql` | Checks the permissions; every line should say PASS | Run any time | Run any time |
| `07_web_access.sql` | Web site tiers: adds the "can see driver's licenses" switch | Run | Run |
| `08_admin_levels.sql` | Four access levels (Top admin, Admin, Tier 2 can edit / view only), activity log, who's online | Run | Run |
| `09_demo_users.sql` | Fictional sign-in users, one per level, until the real list arrives (was `07b`) | Run (remove later) | Run |
| `10_suggestions.sql` | Typing suggestions (pg_trgm when allowed), edit details and sign-outs in the activity log | Run | Run |
| `11_vehicle_name.sql` | A Name field for each vehicle (copied once from the start of its notes) | Run | Run |
| `12_tiers.sql` | Three tiers plus per-person switches; the old Admin level becomes Tier 1 | Run | Run |

On Supabase, open **SQL Editor → New query**, paste one file, and click **Run**.
Files 01–05 can be run again at any time; they keep existing data.
`06_security_tests.sql` undoes everything it does, so it is safe on the real data.

## Differences from the SQL Server files

- **Calling the data-entry steps:** `EXEC wsb.add_fuel @asset_number = 'X', ...`
  becomes `SELECT wsb.add_fuel(p_asset_number => 'X', ...);`. Examples are at the
  bottom of `05_procedures.sql`.
- **`add_invoice_line`:** `p_category` and `p_amount` come before `p_asset_number`,
  because PostgreSQL needs the optional values last. Calls that use names (`=>`) are not affected.
- **Audit log:** one row per changed record, with the row stored as JSON (`record_data` is `JSONB`).
- **`invoice.invoice_type`** is 25 characters, not 20: `'Registration/Insurance'` is 22
  characters, so the SQL Server version rejects it.
- **Supabase lock-down:** every table has row-level security on, and Supabase's public web
  API roles (`anon`, `authenticated`) have no access to the `wsb` schema.
- **Creating logins:** `SELECT wsb.create_wsb_user('jsmith', 'Jane Smith', 'jsmith@fgcu.edu', 'Staff', '<password>');`
  On Supabase the person signs in as `jsmith.<project ref>` through the Session pooler.

The dashboard connects as the database owner, so these permissions do not limit it.
