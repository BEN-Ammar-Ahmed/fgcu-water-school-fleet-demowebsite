-- =====================================================================
-- File 04: Import from existing spreadsheets (staging + transforms)   PostgreSQL / Supabase
-- PostgreSQL version of ../04_import_staging.sql.
-- Pattern:  CSV -> stg_* table (all text, never fails) -> clean INSERT into real tables
-- Why: spreadsheets are messy (blank rows, "$1,234.50", "10-03" with no year).
--      Staging lets you load first, LOOK, fix, then move clean rows across.
--
-- Steps for each source:
--   1. Excel: File > Save As > CSV UTF-8, one sheet at a time, header on row 1.
--      For the WEX date column, format the cells as TEXT first (so 10-03 stays 10-03).
--      Put the columns in the same order as the stg_ table below.
--   2. Run this file once so the stg_ tables exist, then load the CSV into the
--      matching stg_ table. Either
--        a) Supabase: Table Editor > schema "wsb" > the stg_ table > Insert > Import data from CSV
--        b) pgAdmin: right-click the stg_ table > Import/Export Data > Import, Header on
--        c) psql:    \copy wsb.stg_mileage_log FROM 'mileage_log.csv' WITH (FORMAT csv, HEADER true)
--   3. Fill wsb.stg_vehicle_map once (spreadsheet vehicle name -> asset number).
--   4. Run the matching TRANSFORM block (select it, run), then the checks,
--      then empty the stg_ table (bottom of this file).
-- Run as the database owner. On an empty stg_ table each transform does nothing,
-- so running the whole file just creates the tables.
-- The real fleet data is confidential: keep the CSV files out of GitHub.
-- =====================================================================

-- ---------------------------------------------------------------------
-- "Try" converters: return NULL instead of an error for bad values
-- (PostgreSQL's version of SQL Server's TRY_CONVERT).
-- Dates like 10/3/2026 are read as month/day/year.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION wsb.try_int(p TEXT) RETURNS INT
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN RETURN NULLIF(btrim(p), '')::INT; EXCEPTION WHEN others THEN RETURN NULL; END $$;

CREATE OR REPLACE FUNCTION wsb.try_numeric(p TEXT) RETURNS NUMERIC
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN RETURN NULLIF(btrim(p), '')::NUMERIC; EXCEPTION WHEN others THEN RETURN NULL; END $$;

CREATE OR REPLACE FUNCTION wsb.try_date(p TEXT) RETURNS DATE
LANGUAGE plpgsql STABLE SET datestyle = 'ISO, MDY' AS $$
BEGIN RETURN NULLIF(btrim(p), '')::DATE; EXCEPTION WHEN others THEN RETURN NULL; END $$;

CREATE OR REPLACE FUNCTION wsb.try_timestamp(p TEXT) RETURNS TIMESTAMP
LANGUAGE plpgsql STABLE SET datestyle = 'ISO, MDY' AS $$
BEGIN RETURN NULLIF(btrim(p), '')::TIMESTAMP; EXCEPTION WHEN others THEN RETURN NULL; END $$;

CREATE OR REPLACE FUNCTION wsb.try_time(p TEXT) RETURNS TIME
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN RETURN NULLIF(btrim(p), '')::TIME; EXCEPTION WHEN others THEN RETURN NULL; END $$;

-- Money / mileage text -> number: drops $ , and spaces first ("$1,234.50" -> 1234.50)
CREATE OR REPLACE FUNCTION wsb.clean_number(p TEXT) RETURNS NUMERIC
LANGUAGE sql IMMUTABLE AS $$ SELECT wsb.try_numeric(regexp_replace(p, '[$,[:space:]]', '', 'g')) $$;

REVOKE EXECUTE ON FUNCTION wsb.try_int(TEXT), wsb.try_numeric(TEXT), wsb.try_date(TEXT),
                           wsb.try_timestamp(TEXT), wsb.try_time(TEXT), wsb.clean_number(TEXT) FROM PUBLIC;

-- ---------------------------------------------------------------------
-- Shared staging tables
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wsb.stg_params (import_year INT NOT NULL);   -- WEX report prints MM-DD only
-- INSERT INTO wsb.stg_params VALUES (2026);                            -- <-- set before the WEX transform

CREATE TABLE IF NOT EXISTS wsb.stg_vehicle_map (
    vehicle_text  TEXT        NOT NULL PRIMARY KEY,
    asset_number  VARCHAR(20) NOT NULL REFERENCES wsb.vehicle(asset_number)
);
-- Example:  INSERT INTO wsb.stg_vehicle_map VALUES ('Ford F250 white', 'WS-T01'), ('Skiff 1', 'WS-B01');

-- ---------------------------------------------------------------------
-- SOURCE 1: FLEET_MILEAGE_LOG.xlsx ("State Audited Vehicle Log")
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wsb.stg_mileage_log (
    vehicle_text TEXT, date_out TEXT, time_out TEXT,
    mileage_out TEXT, mileage_in TEXT, destination TEXT,
    full_name TEXT, purpose TEXT, date_return TEXT,
    time_return TEXT, gas_station TEXT, amount TEXT
);

-- TRANSFORM 1 -> trip.  Fuel amounts are NOT imported from the log (use WEX data
-- instead, to avoid counting the same fill twice).
INSERT INTO wsb.trip (vehicle_id, driver_id, start_datetime, end_datetime, starting_mileage, ending_mileage, destination, purpose)
SELECT v.vehicle_id, d.driver_id,
       wsb.try_timestamp(s.date_out || ' ' || COALESCE(NULLIF(btrim(s.time_out), ''), '00:00')),
       CASE WHEN NULLIF(btrim(s.date_return), '') IS NULL THEN NULL
            ELSE wsb.try_timestamp(s.date_return || ' ' || COALESCE(NULLIF(btrim(s.time_return), ''), '00:00')) END,
       wsb.clean_number(s.mileage_out)::INT,
       wsb.clean_number(s.mileage_in)::INT,
       LEFT(s.destination, 100), LEFT(s.purpose, 100)
FROM wsb.stg_mileage_log AS s
JOIN wsb.stg_vehicle_map AS m ON m.vehicle_text = s.vehicle_text
JOIN wsb.vehicle AS v ON v.asset_number = m.asset_number
JOIN wsb.driver  AS d ON lower(d.first_name || ' ' || d.last_name) = lower(btrim(s.full_name))
WHERE wsb.try_date(s.date_out) IS NOT NULL;
-- Rows that did NOT import (fix the map or add the driver, then re-run for those rows only):
-- SELECT s.* FROM wsb.stg_mileage_log s
-- LEFT JOIN wsb.stg_vehicle_map m ON m.vehicle_text = s.vehicle_text
-- LEFT JOIN wsb.driver d ON lower(d.first_name || ' ' || d.last_name) = lower(btrim(s.full_name))
-- WHERE m.vehicle_text IS NULL OR d.driver_id IS NULL OR wsb.try_date(s.date_out) IS NULL;

-- ---------------------------------------------------------------------
-- SOURCE 2: WEX Purchase Activity Report (CSV/Excel export from the WEX portal)
-- One row per fuel transaction. The vehicle/asset identifier is printed above each
-- group in the report: copy it down into every row before saving the CSV.
-- tran_date_mmdd must look like 10-03 (MM-DD, two digits each).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wsb.stg_wex_activity (
    asset_identifier TEXT, tran_date_mmdd TEXT, tran_time TEXT,
    site_address TEXT, ticket_number TEXT, tran_code TEXT,
    odometer TEXT, product TEXT, units TEXT, cost_per_unit TEXT,
    fuel_amount TEXT, other_amount TEXT, exempt_tax TEXT,
    net_amount TEXT, reported_tax TEXT
);

-- Step 2.0: create the monthly WEX statement as an invoice (edit the values from the
-- Invoice Statement page: invoice number, closing date, due date, amount due):
-- INSERT INTO wsb.invoice (invoice_number, invoice_type, vendor, invoice_date, payment_due_date, total_amount, funding_source, account_number_last4)
-- VALUES ('<WEX INVOICE NUMBER>', 'WEX Statement', 'WEX Bank', '2026-10-15', '2026-11-05', 0.00, 'Fleet Fuel Account', '0000');

-- TRANSFORM 2 -> invoice_line + fuel_record.  Edit v_wex_invoice, then run the whole block.
DO $$
DECLARE
    v_wex_invoice VARCHAR(40) := '<WEX INVOICE NUMBER>';
    v_year        INT;
    v_invoice_id  INT;
BEGIN
    SELECT import_year INTO v_year FROM wsb.stg_params LIMIT 1;
    SELECT invoice_id INTO v_invoice_id FROM wsb.invoice WHERE invoice_number = v_wex_invoice AND vendor = 'WEX Bank';

    IF v_invoice_id IS NULL OR v_year IS NULL THEN
        RAISE NOTICE 'WEX transform skipped: create the WEX invoice (step 2.0) and set stg_params first.';
        RETURN;
    END IF;

    -- cleaned rows
    CREATE TEMP TABLE tmp_wex ON COMMIT DROP AS
    SELECT v.vehicle_id,
           wsb.try_date(v_year || '-' || btrim(s.tran_date_mmdd))          AS fuel_date,
           wsb.try_time(s.tran_time)                                       AS fuel_time,
           wsb.clean_number(s.odometer)::INT                               AS mileage,
           wsb.clean_number(s.units)::NUMERIC(8,3)                         AS gallons,
           wsb.clean_number(s.cost_per_unit)::NUMERIC(7,3)                 AS cost_per_unit,
           COALESCE(wsb.clean_number(s.fuel_amount),  0)::NUMERIC(10,2)    AS fuel_amt,
           COALESCE(wsb.clean_number(s.other_amount), 0)::NUMERIC(10,2)    AS other_amt,
           LEFT(s.product, 20) AS product, LEFT(s.site_address, 150) AS site_address,
           LEFT(s.ticket_number, 30) AS ticket_number, upper(btrim(s.tran_code)) AS tran_code
    FROM wsb.stg_wex_activity AS s
    JOIN wsb.stg_vehicle_map AS m ON m.vehicle_text = s.asset_identifier
    JOIN wsb.vehicle AS v ON v.asset_number = m.asset_number;

    INSERT INTO wsb.invoice_line (invoice_id, vehicle_id, line_date, category, description, amount)
    SELECT v_invoice_id, vehicle_id, fuel_date, 'Fuel', 'WEX ticket ' || ticket_number, fuel_amt + other_amt
    FROM tmp_wex;

    INSERT INTO wsb.fuel_record (vehicle_id, invoice_line_id, fuel_date, fuel_time, mileage, gallons, cost_per_unit,
                                 total_cost, other_cost, product, site_address, ticket_number, wex_tran_code, source)
    SELECT w.vehicle_id, l.line_id, w.fuel_date, w.fuel_time, w.mileage, w.gallons, w.cost_per_unit,
           w.fuel_amt, w.other_amt, w.product, w.site_address, w.ticket_number,
           (SELECT c.code FROM wsb.wex_code AS c WHERE c.code = w.tran_code), 'WEX Import'
    FROM tmp_wex AS w
    JOIN wsb.invoice_line AS l ON l.invoice_id = v_invoice_id AND l.vehicle_id = w.vehicle_id
                              AND l.description = 'WEX ticket ' || w.ticket_number;

    DROP TABLE tmp_wex;
END $$;
-- Tip: if a ticket number repeats for the same vehicle, the join above returns two fuel
-- rows per ticket. Check:  SELECT ticket_number, COUNT(*) FROM wsb.fuel_record GROUP BY ticket_number HAVING COUNT(*) > 1;

-- ---------------------------------------------------------------------
-- SOURCE 3: Vehicle and Boat Maintenance sheet (one tab per fiscal year)
-- Columns: Date | Purchaser | Vehicle/Vessel | Repair items | Vendor | Funding source/account | Cost | Total Cost | P-Card WorkDay #
-- Do NOT load "TOTAL SPENT": the database calculates totals (v_cost_by_vehicle_fy).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wsb.stg_maintenance_sheet (
    entry_date TEXT, purchaser TEXT, vehicle_text TEXT,
    repair_items TEXT, vendor TEXT, funding_source TEXT,
    cost TEXT, total_cost TEXT, pcard_workday_no TEXT
);

-- TRANSFORM 3: one invoice per sheet row (the sheet has no invoice numbers), one line,
-- one maintenance record. invoice_number = 'SHEET-<yyyymmdd>-<row>' so it is unique and traceable.
CREATE TEMP TABLE tmp_maint AS
SELECT row_number() OVER () AS rn,
       wsb.try_date(s.entry_date) AS d,
       wsb.clean_number(s.cost)::NUMERIC(10,2) AS cost_n,
       LEFT(s.purchaser, 80) AS purchaser, s.vehicle_text, s.repair_items,
       LEFT(COALESCE(NULLIF(btrim(s.vendor), ''), 'Unknown'), 80) AS vendor,
       LEFT(s.funding_source, 80) AS funding_source, LEFT(s.pcard_workday_no, 40) AS pcard_workday_no
FROM wsb.stg_maintenance_sheet AS s
WHERE wsb.try_date(s.entry_date) IS NOT NULL
  AND wsb.clean_number(s.cost) IS NOT NULL;

INSERT INTO wsb.invoice (invoice_number, invoice_type, vendor, invoice_date, total_amount, funding_source, pcard_workday_no, purchaser)
SELECT 'SHEET-' || to_char(d, 'YYYYMMDD') || '-' || rn, 'Maintenance',
       vendor, d, cost_n, funding_source, pcard_workday_no, purchaser
FROM tmp_maint;

INSERT INTO wsb.invoice_line (invoice_id, vehicle_id, line_date, category, description, amount)
SELECT i.invoice_id, v.vehicle_id, m.d, 'Repair', m.repair_items, m.cost_n
FROM tmp_maint AS m
JOIN wsb.invoice AS i ON i.invoice_number = 'SHEET-' || to_char(m.d, 'YYYYMMDD') || '-' || m.rn
LEFT JOIN wsb.stg_vehicle_map AS sm ON sm.vehicle_text = m.vehicle_text
LEFT JOIN wsb.vehicle AS v ON v.asset_number = sm.asset_number;

-- Lines with a NULL vehicle_id mean a vehicle name is missing from stg_vehicle_map:
-- add it, then  UPDATE wsb.invoice_line SET vehicle_id = ... WHERE vehicle_id IS NULL AND ...
SELECT COUNT(*) AS lines_missing_vehicle
FROM wsb.invoice_line AS l JOIN wsb.invoice AS i ON i.invoice_id = l.invoice_id
WHERE i.invoice_number LIKE 'SHEET-%' AND l.vehicle_id IS NULL;

-- Create maintenance_record rows from the repair lines
INSERT INTO wsb.maintenance_record (vehicle_id, invoice_line_id, service_date, service_type, cost, vendor, description)
SELECT l.vehicle_id, l.line_id, l.line_date, 'Repair', l.amount, LEFT(i.vendor, 50), l.description
FROM wsb.invoice_line AS l
JOIN wsb.invoice AS i ON i.invoice_id = l.invoice_id
WHERE i.invoice_number LIKE 'SHEET-%' AND l.vehicle_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM wsb.maintenance_record AS mr WHERE mr.invoice_line_id = l.line_id);

DROP TABLE tmp_maint;

-- Staging tables are owner-only: keep them away from the Supabase public API
SELECT wsb.lock_out_public_api();

-- ---------------------------------------------------------------------
-- AFTER IMPORT: sanity checks, then clean up
-- ---------------------------------------------------------------------
-- SELECT COUNT(*) FROM wsb.trip; SELECT COUNT(*) FROM wsb.fuel_record; SELECT COUNT(*) FROM wsb.invoice;
-- SELECT * FROM wsb.v_invoice_reconciliation WHERE unassigned_difference <> 0;
-- SELECT * FROM wsb.invoice_line WHERE vehicle_id IS NULL AND category <> 'Fee';
-- TRUNCATE TABLE wsb.stg_mileage_log, wsb.stg_wex_activity, wsb.stg_maintenance_sheet;
