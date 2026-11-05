# Water School Vehicle Management Database: Instruction Manual

For future student groups and Water School staff. Written by Team Incognito, Fall 2026.

## 1. What this is

A SQL Server database (`WSB_Vehicle_Database`, schema `wsb`) that replaces the scattered spreadsheets for boats, cars, trucks, trailers and golf carts. It tracks:

| Area | Tables |
|---|---|
| People | `driver`, `driver_license`, `driver_qualification` |
| Vehicles | `vehicle`, `vehicle_document`, `maintenance_rule` |
| Money | `invoice`, `invoice_line`, `wex_code` |
| Activity | `trip`, `fuel_record`, `maintenance_record` |
| Security | `app_role`, `app_user`, `audit_log` |

**Key idea:** one `invoice` (a WEX statement, a shop bill, a P-Card purchase) has many `invoice_line` rows, and each line is tied to **one vehicle**. That is how a single WEX statement covering many vehicles still shows the cost of each vehicle.

## 2. What you need

- SQL Server (2017 or newer; row-level security needs 2016+) running on `localhost:1433`
- Visual Studio Code with a SQL extension, or SSMS / Azure Data Studio
- The `sa` password (or another sysadmin login). Keep it out of GitHub.

## 3. First-time setup (empty database)

Run the files **in this order**, each one completely:

| # | File | What it does |
|---|---|---|
| 0 | `00_create_database.sql` | Creates `WSB_Vehicle_Database` |
| 1 | `01_schema.sql` | Schema, 15 tables, triggers, indexes, 8 report views |
| 2 | `02_security.sql` | Three roles, permissions, row-level security on documents |
| 3 | `03_sample_data.sql` | Reference data + fictional DEMO data |
| 5 | `05_procedures.sql` | Data-entry stored procedures |
| 6 | `06_security_tests.sql` | Proves the security works (optional but recommended) |

> **The files contain `GO` batch separators.** `GO` is understood by `sqlcmd`, SSMS, Azure Data Studio and the Microsoft "SQL Server (mssql)" VS Code extension. If your VS Code extension reports an error on `GO`, run the file from a terminal instead:
> `sqlcmd -S localhost -U sa -d WSB_Vehicle_Database -i 01_schema.sql`
> (for step 0 use `-d master`).

Check it worked:

```sql
SELECT COUNT(*) FROM wsb.vehicle;                      -- 8 with demo data
SELECT * FROM wsb.v_invoice_reconciliation;            -- unassigned_difference = 0.00
```

## 4. Going live with real data

1. Remove the demo rows: run the **CLEAR DEMO DATA** block at the bottom of `03_sample_data.sql` (uncomment it first).
2. Add real vehicles and drivers (section 5, or load them from `1 FLEET INFO` with the import steps in `04_import_staging.sql`).
3. Import the spreadsheets with `04_import_staging.sql` (section 7).

## 5. Adding data day to day

Use the procedures in `05_procedures.sql`. They check your input and give plain-English errors.

```sql
-- a trip
EXEC wsb.add_trip @asset_number='WS-T01', @driver_email='name@fgcu.edu',
     @start_datetime='2026-11-02 08:00', @end_datetime='2026-11-02 16:00',
     @starting_mileage=48210, @ending_mileage=48330,
     @destination='Matlacha Boat Ramp', @purpose='Field work', @project_program='Water Quality Monitoring';

-- a fuel purchase
EXEC wsb.add_fuel @asset_number='WS-T01', @fuel_date='2026-11-02', @gallons=24.5, @total_cost=92.15, @vendor='Sample Gas';

-- an invoice, then its lines (one line per vehicle charge)
EXEC wsb.add_invoice @invoice_number='5521', @invoice_type='Maintenance', @vendor='Gulf Coast Auto Care',
     @invoice_date='2026-11-02', @total_amount=148.99, @purchaser='Alex Rivera', @pcard_workday_no='26006092_PCT';
EXEC wsb.add_invoice_line @vendor='Gulf Coast Auto Care', @invoice_number='5521', @asset_number='WS-C01',
     @category='Service', @amount=89.99, @description='Oil and filter change';

-- completed maintenance (also moves the recurring rule forward)
EXEC wsb.add_maintenance @asset_number='WS-C01', @service_date='2026-11-02', @service_type='Oil Change',
     @cost=89.99, @vendor='Gulf Coast Auto Care', @mileage_at_service=61200;
```

Rules the database enforces for you:

- A driver must be **approved** and **active** to be put on a trip.
- A trip cannot end before it starts, and ending mileage cannot be lower than starting mileage.
- A vendor + invoice number can only be entered once.
- `vehicle.current_mileage` updates itself from trips and fuel records.
- Every change to the main tables is written to `audit_log` automatically.
- Only the **last 4 digits** of WEX cards and accounts are stored. Never type a full card number anywhere.

Adding a new vehicle or driver uses plain `INSERT` (Admin or Staff):

```sql
INSERT INTO wsb.vehicle (asset_number, vehicle_type, make, model, year, vin, department, status)
VALUES ('WS-T03', 'Truck', 'Ford', 'F-150', 2024, '<VIN>', 'Marine Operations', 'Available');
```

`vehicle_type` must be one of Boat, Car, Truck, Trailer, Golf Cart, ATV, Other. `status` must be Available, In Use, In Maintenance, Out of Service or Retired.

## 6. Reports (views)

Query them like tables, for example `SELECT * FROM wsb.v_maintenance_due;`

| View | Answers |
|---|---|
| `v_cost_by_vehicle_fy` | Fuel, maintenance and total cost per vehicle per Florida fiscal year (July to June) |
| `v_invoice_reconciliation` | Does each invoice's total match the lines assigned to vehicles? |
| `v_maintenance_due` | Which recurring services are DUE (by mileage or by months)? |
| `v_expiring_items` | Licenses, training and documents expiring within 60 days (Staff and Admin) |
| `v_fuel_efficiency` | Miles per gallon between fill-ups for cars and trucks |
| `v_state_audit_vehicle_log` | The same columns as the paper State Audited Vehicle Log |
| `v_vehicle_summary` | One row per vehicle |
| `v_driver_directory` | Driver names and status, no emails or license data |

Power BI or Excel can connect to these views directly (Get Data > SQL Server).

## 7. Importing the existing spreadsheets

`04_import_staging.sql` loads three sources through staging tables so you can inspect the data before it goes into the real tables:

1. **Mileage log** (`FLEET_MILEAGE_LOG`) into trips
2. **WEX Purchase Activity Report** into fuel records and invoice lines
3. **Vehicle and Boat Maintenance sheet** into invoices, lines and maintenance records

For each: save the sheet as CSV (UTF-8), load it into its `stg_` table, fill `wsb.stg_vehicle_map` (spreadsheet name to asset number), run the matching transform, run the checks, then `TRUNCATE` the staging table. Do **not** import the "TOTAL SPENT" column; the views calculate totals.

## 8. Users and security

| Role | Can do |
|---|---|
| **Admin** (`wsb_admin`) | Everything, including deletes; sees all documents; cannot change or delete the audit log |
| **Staff** (`wsb_staff`) | View and add/edit operational data; no deletes; no user or audit tables; sees General and Staff documents |
| **Read-only** (`wsb_readonly`) | View vehicles, trips, fuel, maintenance, invoices and reports; no personal data (license numbers, emails); General documents only |

Add a person (run as `sa`):

```sql
EXEC wsb.create_wsb_user @p_username='jsmith', @p_full_name='Jane Smith',
     @p_email='jsmith@fgcu.edu', @p_role='Staff', @p_password='<temporary password>';
```

Remove access: `ALTER ROLE wsb_staff DROP MEMBER jsmith;` and `UPDATE wsb.app_user SET active = 0 WHERE username = 'jsmith';`

Each document has an `access_level` (General, Staff, Admin). SQL Server hides rows above a person's level automatically. Put titles and anything sensitive at **Admin**.

Re-run `06_security_tests.sql` after any change to permissions.

## 9. Backups and handoff

- Back up regularly: `BACKUP DATABASE WSB_Vehicle_Database TO DISK = 'C:\wsb\backup\wsb.bak' WITH INIT;`
- Store scans (licenses, invoices, registrations) in a secure shared folder; the database keeps only the file path.
- Do **not** put real license numbers, WEX account numbers, passwords or unredacted invoices in GitHub.
- When a new group takes over: give them this manual and the scripts, the `sa` or admin credentials through the Water School's normal secure channel, and the list of open items below.

## 10. Troubleshooting

| Message | Likely cause |
|---|---|
| `Invalid object name 'wsb.…'` | Wrong database selected, or `01_schema.sql` not run |
| `There is already an object named …` | The script was run twice on a non-empty database |
| `The INSERT statement conflicted with the FOREIGN KEY constraint` | The vehicle, driver or invoice does not exist yet; add it first |
| `The INSERT statement conflicted with the CHECK constraint` | A value is not in the allowed list (vehicle type, status, category, access level) |
| `Cannot insert duplicate key … UNIQUE` | VIN, asset number, email or vendor + invoice number already exists |
| `permission was denied` | Your role does not allow it; ask an Admin |
| `Unknown asset number` | Check `SELECT asset_number FROM wsb.vehicle;` |

## 11. Known limits and ideas for the next group

- No web or mobile front end (out of scope for this project). The stored procedures and views are the interface; Power BI or Power Apps are natural next steps.
- Boats track engine hours in `vehicle.current_hours`, but nothing updates it automatically.
- The role-catalogue column `app_role.pg_role` holds the SQL Server role name (the name is left over from an early draft).
- The Float Plan and Boat Checklist forms are not modelled yet.
