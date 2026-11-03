-- =====================================================================
-- File 04: Import from existing spreadsheets (staging tables + transforms)
-- Pattern:  CSV  ->  stg_* table (all TEXT, never fails)  ->  clean INSERT into real tables
-- Why: spreadsheets are messy (blank rows, "$1,234.50", 10/3 with no year).
--      Staging lets you load first, LOOK, fix, then move clean rows across.
--
-- Run once to create the staging tables. Then for each source:
--   1. Excel: File > Save As > CSV UTF-8, one sheet at a time, header row on row 1.
--   2. pgAdmin: right-click the stg_ table > Import/Export Data > Import, header = Yes.
--      (or VS Code terminal:  \copy wsb.stg_mileage_log FROM 'file.csv' CSV HEADER)
--   3. Fill stg_vehicle_map (see below), run the matching TRANSFORM block.
--   4. TRUNCATE the stg_ table when done.
-- =====================================================================
SET search_path TO wsb, public;

-- Year to apply to WEX rows (the Purchase Activity Report prints MM-DD only)
CREATE TABLE IF NOT EXISTS stg_params (import_year INT);
-- INSERT INTO stg_params VALUES (2026);   -- <-- set before running WEX transform

-- Maps the free-text vehicle names used in spreadsheets to real vehicles.
-- Fill it by hand ONCE: 'Ford F250 white', 'Skiff 1', 'Truck 2' ... -> asset number.
CREATE TABLE IF NOT EXISTS stg_vehicle_map (
    vehicle_text  TEXT PRIMARY KEY,
    asset_number  VARCHAR(20) NOT NULL REFERENCES vehicle(asset_number)
);

-- ---------------------------------------------------------------------
-- SOURCE 1: FLEET_MILEAGE_LOG.xlsx  ("State Audited Vehicle Log")
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stg_mileage_log (
    vehicle_text TEXT, date_out TEXT, time_out TEXT, mileage_out TEXT, mileage_in TEXT,
    destination TEXT, full_name TEXT, purpose TEXT, date_return TEXT, time_return TEXT,
    gas_station TEXT, amount TEXT
);

-- TRANSFORM 1 -> trip  (fuel amounts are NOT imported here; use WEX data to avoid double counting)
-- Dates must be YYYY-MM-DD or M/D/YYYY. Rows whose vehicle or driver cannot be matched are skipped:
-- check them with the query under the INSERT.
INSERT INTO trip (vehicle_id, driver_id, start_datetime, end_datetime, starting_mileage, ending_mileage, destination, purpose)
SELECT v.vehicle_id, d.driver_id,
       (s.date_out || ' ' || COALESCE(NULLIF(s.time_out,''),'00:00'))::TIMESTAMP,
       NULLIF(s.date_return || ' ' || COALESCE(NULLIF(s.time_return,''),'00:00'),' 00:00')::TIMESTAMP,
       NULLIF(regexp_replace(s.mileage_out,'[^0-9]','','g'),'')::INT,
       NULLIF(regexp_replace(s.mileage_in ,'[^0-9]','','g'),'')::INT,
       s.destination, s.purpose
FROM stg_mileage_log s
JOIN stg_vehicle_map m ON m.vehicle_text = s.vehicle_text
JOIN vehicle v ON v.asset_number = m.asset_number
JOIN driver d  ON lower(d.first_name || ' ' || d.last_name) = lower(trim(s.full_name))
WHERE NULLIF(trim(s.date_out),'') IS NOT NULL;

-- Rows that did NOT import (fix the map or add the driver, then re-run only those):
-- SELECT s.* FROM stg_mileage_log s
-- LEFT JOIN stg_vehicle_map m ON m.vehicle_text = s.vehicle_text
-- LEFT JOIN driver d ON lower(d.first_name||' '||d.last_name) = lower(trim(s.full_name))
-- WHERE m.vehicle_text IS NULL OR d.driver_id IS NULL;

-- ---------------------------------------------------------------------
-- SOURCE 2: WEX Purchase Activity Report  (export as CSV/Excel from the WEX portal)
-- One row per fuel transaction. The vehicle/asset identifier is printed above each group;
-- copy it down into every row in Excel before saving as CSV.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stg_wex_activity (
    asset_identifier TEXT, tran_date_mmdd TEXT, tran_time TEXT, site_address TEXT, ticket_number TEXT,
    tran_code TEXT, odometer TEXT, product TEXT, units TEXT, cost_per_unit TEXT,
    fuel_amount TEXT, other_amount TEXT, exempt_tax TEXT, net_amount TEXT, reported_tax TEXT
);

-- TRANSFORM 2a -> invoice + invoice_line + fuel_record
-- First create (or look up) the monthly WEX statement as an invoice (see manual), then:
-- replace 'WEX-INVOICE-NUMBER' below with its invoice_number.
WITH clean AS (
    SELECT v.vehicle_id,
           make_date((SELECT import_year FROM stg_params LIMIT 1),
                     split_part(s.tran_date_mmdd,'-',1)::INT, split_part(s.tran_date_mmdd,'-',2)::INT) AS fuel_date,
           NULLIF(s.tran_time,'')::TIME AS fuel_time,
           NULLIF(regexp_replace(s.odometer,'[^0-9]','','g'),'')::INT AS mileage,
           NULLIF(regexp_replace(s.units,'[^0-9.]','','g'),'')::NUMERIC AS gallons,
           NULLIF(regexp_replace(s.cost_per_unit,'[^0-9.]','','g'),'')::NUMERIC AS cpu,
           COALESCE(NULLIF(regexp_replace(s.fuel_amount,'[^0-9.\-]','','g'),'')::NUMERIC,0) AS fuel_amt,
           COALESCE(NULLIF(regexp_replace(s.other_amount,'[^0-9.\-]','','g'),'')::NUMERIC,0) AS other_amt,
           s.product, s.site_address, s.ticket_number, s.tran_code
    FROM stg_wex_activity s
    JOIN stg_vehicle_map m ON m.vehicle_text = s.asset_identifier
    JOIN vehicle v ON v.asset_number = m.asset_number
),
lines AS (
    INSERT INTO invoice_line (invoice_id, vehicle_id, line_date, category, description, amount)
    SELECT (SELECT invoice_id FROM invoice WHERE invoice_number = 'WEX-INVOICE-NUMBER' AND vendor = 'WEX Bank'),
           c.vehicle_id, c.fuel_date, 'Fuel', 'WEX ticket ' || c.ticket_number, c.fuel_amt + c.other_amt
    FROM clean c
    RETURNING line_id, vehicle_id, line_date, amount
)
SELECT count(*) AS lines_created FROM lines;
-- NOTE: the fuel_record rows are created in step 2b so each one can point at its invoice_line.

-- TRANSFORM 2b -> fuel_record linked to the lines created above (matches on vehicle + date + amount)
INSERT INTO fuel_record (vehicle_id, invoice_line_id, fuel_date, fuel_time, mileage, gallons, cost_per_unit,
                         total_cost, other_cost, product, site_address, ticket_number, wex_tran_code, source)
SELECT v.vehicle_id, l.line_id,
       make_date((SELECT import_year FROM stg_params LIMIT 1), split_part(s.tran_date_mmdd,'-',1)::INT, split_part(s.tran_date_mmdd,'-',2)::INT),
       NULLIF(s.tran_time,'')::TIME,
       NULLIF(regexp_replace(s.odometer,'[^0-9]','','g'),'')::INT,
       NULLIF(regexp_replace(s.units,'[^0-9.]','','g'),'')::NUMERIC,
       NULLIF(regexp_replace(s.cost_per_unit,'[^0-9.]','','g'),'')::NUMERIC,
       COALESCE(NULLIF(regexp_replace(s.fuel_amount,'[^0-9.\-]','','g'),'')::NUMERIC,0),
       COALESCE(NULLIF(regexp_replace(s.other_amount,'[^0-9.\-]','','g'),'')::NUMERIC,0),
       s.product, s.site_address, s.ticket_number,
       (SELECT code FROM wex_code WHERE code = upper(trim(s.tran_code))),
       'WEX Import'
FROM stg_wex_activity s
JOIN stg_vehicle_map m ON m.vehicle_text = s.asset_identifier
JOIN vehicle v ON v.asset_number = m.asset_number
JOIN invoice_line l ON l.vehicle_id = v.vehicle_id
     AND l.description = 'WEX ticket ' || s.ticket_number
JOIN invoice i ON i.invoice_id = l.invoice_id AND i.invoice_number = 'WEX-INVOICE-NUMBER';

-- ---------------------------------------------------------------------
-- SOURCE 3: Vehicle and Boat Maintenance sheet (FY tabs)
-- Columns: Date | Purchaser | Vehicle/Vessel | Repair items | Vendor | Funding source/account | Cost | Total Cost | P-Card WorkDay #
-- Do NOT load the "TOTAL SPENT" column - the database calculates totals (v_cost_by_vehicle_fy).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stg_maintenance_sheet (
    entry_date TEXT, purchaser TEXT, vehicle_text TEXT, repair_items TEXT, vendor TEXT,
    funding_source TEXT, cost TEXT, total_cost TEXT, pcard_workday_no TEXT
);

-- TRANSFORM 3: one invoice per sheet row (the sheet has no invoice numbers), one line, one maintenance record.
-- invoice_number is generated as 'SHEET-<date>-<row>' so it is unique and traceable.
WITH numbered AS (
    SELECT row_number() OVER () AS rn, s.*,
           NULLIF(regexp_replace(s.cost,'[^0-9.\-]','','g'),'')::NUMERIC AS cost_n,
           s.entry_date::DATE AS d
    FROM stg_maintenance_sheet s
    WHERE NULLIF(trim(s.entry_date),'') IS NOT NULL AND NULLIF(trim(s.cost),'') IS NOT NULL
),
inv AS (
    INSERT INTO invoice (invoice_number, invoice_type, vendor, invoice_date, total_amount, funding_source, pcard_workday_no, purchaser)
    SELECT 'SHEET-' || to_char(n.d,'YYYYMMDD') || '-' || n.rn, 'Maintenance',
           COALESCE(NULLIF(trim(n.vendor),''),'Unknown'), n.d, n.cost_n,
           n.funding_source, n.pcard_workday_no, n.purchaser
    FROM numbered n
    RETURNING invoice_id, invoice_number
),
ln AS (
    INSERT INTO invoice_line (invoice_id, vehicle_id, line_date, category, description, amount)
    SELECT i.invoice_id, v.vehicle_id, n.d, 'Repair', n.repair_items, n.cost_n
    FROM numbered n
    JOIN inv i ON i.invoice_number = 'SHEET-' || to_char(n.d,'YYYYMMDD') || '-' || n.rn
    LEFT JOIN stg_vehicle_map m ON m.vehicle_text = n.vehicle_text
    LEFT JOIN vehicle v ON v.asset_number = m.asset_number
    RETURNING line_id, vehicle_id, line_date, description, amount
)
SELECT count(*) AS lines_created, count(*) FILTER (WHERE vehicle_id IS NULL) AS lines_missing_vehicle FROM ln;
-- Lines with a NULL vehicle_id mean a name is missing from stg_vehicle_map: add it, then
-- UPDATE invoice_line SET vehicle_id = ... for those lines (query v_invoice_reconciliation / filter vehicle_id IS NULL).

-- Optional: create maintenance_record rows from the repair lines
INSERT INTO maintenance_record (vehicle_id, invoice_line_id, service_date, service_type, cost, vendor, description)
SELECT l.vehicle_id, l.line_id, l.line_date, 'Repair', l.amount, i.vendor, l.description
FROM invoice_line l JOIN invoice i USING (invoice_id)
WHERE i.invoice_number LIKE 'SHEET-%' AND l.vehicle_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM maintenance_record mr WHERE mr.invoice_line_id = l.line_id);

-- ---------------------------------------------------------------------
-- AFTER IMPORT: sanity checks
-- ---------------------------------------------------------------------
-- SELECT count(*) FROM trip; SELECT count(*) FROM fuel_record; SELECT count(*) FROM invoice;
-- SELECT * FROM v_invoice_reconciliation WHERE unassigned_difference <> 0;
-- SELECT * FROM invoice_line WHERE vehicle_id IS NULL AND category <> 'Fee';
-- TRUNCATE stg_mileage_log, stg_wex_activity, stg_maintenance_sheet;
