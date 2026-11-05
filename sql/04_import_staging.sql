-- =====================================================================
-- File 04: Import from existing spreadsheets (staging + transforms)   SQL Server
-- Pattern:  CSV -> stg_* table (all text, never fails) -> clean INSERT into real tables
-- Why: spreadsheets are messy (blank rows, "$1,234.50", "10-03" with no year).
--      Staging lets you load first, LOOK, fix, then move clean rows across.
--
-- Steps for each source:
--   1. Excel: File > Save As > CSV UTF-8, one sheet at a time, header on row 1.
--      For the WEX date column, format the cells as TEXT first (so 10-03 stays 10-03).
--   2. Load the CSV into the matching stg_ table. Either
--        a) SQL Server Management Studio / Azure Data Studio: right-click the database >
--           Tasks > Import Flat File (columns must already be text), or
--        b) BULK INSERT (the path must be readable BY THE SQL SERVER machine):
--             BULK INSERT wsb.stg_mileage_log FROM 'C:\wsb\mileage_log.csv'
--             WITH (FORMAT = 'CSV', FIRSTROW = 2, CODEPAGE = '65001');
--   3. Fill wsb.stg_vehicle_map once (spreadsheet vehicle name -> asset number).
--   4. Run the matching TRANSFORM block, then the checks, then TRUNCATE the stg_ table.
-- Run as sa / db_owner. Remove the DEMO data first (bottom of 03_sample_data.sql).
-- =====================================================================
SET NOCOUNT ON;
GO

IF OBJECT_ID('wsb.stg_params') IS NULL
    CREATE TABLE wsb.stg_params (import_year INT NOT NULL);   -- WEX report prints MM-DD only
GO
-- INSERT INTO wsb.stg_params VALUES (2026);                  -- <-- set before the WEX transform

IF OBJECT_ID('wsb.stg_vehicle_map') IS NULL
    CREATE TABLE wsb.stg_vehicle_map (
        vehicle_text  NVARCHAR(200) NOT NULL PRIMARY KEY,
        asset_number  VARCHAR(20)   NOT NULL REFERENCES wsb.vehicle(asset_number)
    );
GO
-- Example:  INSERT INTO wsb.stg_vehicle_map VALUES ('Ford F250 white', 'WS-T01'), ('Skiff 1', 'WS-B01');

-- ---------------------------------------------------------------------
-- SOURCE 1: FLEET_MILEAGE_LOG.xlsx ("State Audited Vehicle Log")
-- ---------------------------------------------------------------------
IF OBJECT_ID('wsb.stg_mileage_log') IS NULL
    CREATE TABLE wsb.stg_mileage_log (
        vehicle_text NVARCHAR(200), date_out NVARCHAR(30), time_out NVARCHAR(30),
        mileage_out NVARCHAR(30), mileage_in NVARCHAR(30), destination NVARCHAR(200),
        full_name NVARCHAR(100), purpose NVARCHAR(200), date_return NVARCHAR(30),
        time_return NVARCHAR(30), gas_station NVARCHAR(100), amount NVARCHAR(30)
    );
GO

-- TRANSFORM 1 -> trip.  Fuel amounts are NOT imported from the log (use WEX data
-- instead, to avoid counting the same fill twice).
INSERT INTO wsb.trip (vehicle_id, driver_id, start_datetime, end_datetime, starting_mileage, ending_mileage, destination, purpose)
SELECT v.vehicle_id, d.driver_id,
       TRY_CONVERT(DATETIME2, s.date_out + ' ' + COALESCE(NULLIF(s.time_out, ''), '00:00')),
       CASE WHEN NULLIF(LTRIM(RTRIM(s.date_return)), '') IS NULL THEN NULL
            ELSE TRY_CONVERT(DATETIME2, s.date_return + ' ' + COALESCE(NULLIF(s.time_return, ''), '00:00')) END,
       TRY_CONVERT(INT, REPLACE(REPLACE(s.mileage_out, ',', ''), ' ', '')),
       TRY_CONVERT(INT, REPLACE(REPLACE(s.mileage_in,  ',', ''), ' ', '')),
       s.destination, s.purpose
FROM wsb.stg_mileage_log AS s
JOIN wsb.stg_vehicle_map AS m ON m.vehicle_text = s.vehicle_text
JOIN wsb.vehicle AS v ON v.asset_number = m.asset_number
JOIN wsb.driver  AS d ON LOWER(d.first_name + ' ' + d.last_name) = LOWER(LTRIM(RTRIM(s.full_name)))
WHERE TRY_CONVERT(DATETIME2, s.date_out + ' 00:00') IS NOT NULL;
GO
-- Rows that did NOT import (fix the map or add the driver, then re-run for those rows only):
-- SELECT s.* FROM wsb.stg_mileage_log s
-- LEFT JOIN wsb.stg_vehicle_map m ON m.vehicle_text = s.vehicle_text
-- LEFT JOIN wsb.driver d ON LOWER(d.first_name + ' ' + d.last_name) = LOWER(LTRIM(RTRIM(s.full_name)))
-- WHERE m.vehicle_text IS NULL OR d.driver_id IS NULL OR TRY_CONVERT(DATETIME2, s.date_out + ' 00:00') IS NULL;

-- ---------------------------------------------------------------------
-- SOURCE 2: WEX Purchase Activity Report (CSV/Excel export from the WEX portal)
-- One row per fuel transaction. The vehicle/asset identifier is printed above each
-- group in the report: copy it down into every row before saving the CSV.
-- tran_date_mmdd must look like 10-03 (MM-DD, two digits each).
-- ---------------------------------------------------------------------
IF OBJECT_ID('wsb.stg_wex_activity') IS NULL
    CREATE TABLE wsb.stg_wex_activity (
        asset_identifier NVARCHAR(200), tran_date_mmdd NVARCHAR(10), tran_time NVARCHAR(20),
        site_address NVARCHAR(200), ticket_number NVARCHAR(30), tran_code NVARCHAR(10),
        odometer NVARCHAR(30), product NVARCHAR(30), units NVARCHAR(30), cost_per_unit NVARCHAR(30),
        fuel_amount NVARCHAR(30), other_amount NVARCHAR(30), exempt_tax NVARCHAR(30),
        net_amount NVARCHAR(30), reported_tax NVARCHAR(30)
    );
GO

-- Step 2.0: create the monthly WEX statement as an invoice (edit the values from the
-- Invoice Statement page: invoice number, closing date, due date, amount due):
-- INSERT INTO wsb.invoice (invoice_number, invoice_type, vendor, invoice_date, payment_due_date, total_amount, funding_source, account_number_last4)
-- VALUES ('<WEX INVOICE NUMBER>', 'WEX Statement', 'WEX Bank', '2026-10-15', '2026-11-05', 0.00, 'Fleet Fuel Account', '0000');

-- TRANSFORM 2 -> invoice_line + fuel_record.  Edit @wex_invoice, then run the whole block.
DECLARE @wex_invoice VARCHAR(40) = '<WEX INVOICE NUMBER>';
DECLARE @year INT = (SELECT TOP 1 import_year FROM wsb.stg_params);
DECLARE @invoice_id INT = (SELECT invoice_id FROM wsb.invoice WHERE invoice_number = @wex_invoice AND vendor = 'WEX Bank');

IF @invoice_id IS NULL OR @year IS NULL
    RAISERROR('Create the WEX invoice (step 2.0) and set stg_params first.', 16, 1);
ELSE
BEGIN
    -- cleaned rows
    SELECT v.vehicle_id,
           DATEFROMPARTS(@year, TRY_CONVERT(INT, LEFT(s.tran_date_mmdd, 2)), TRY_CONVERT(INT, RIGHT(s.tran_date_mmdd, 2))) AS fuel_date,
           TRY_CONVERT(TIME, NULLIF(s.tran_time, ''))                                              AS fuel_time,
           TRY_CONVERT(INT, REPLACE(REPLACE(s.odometer, ',', ''), ' ', ''))                         AS mileage,
           TRY_CONVERT(DECIMAL(8,3), REPLACE(s.units, ',', ''))                                     AS gallons,
           TRY_CONVERT(DECIMAL(7,3), REPLACE(REPLACE(s.cost_per_unit, '$', ''), ',', ''))           AS cost_per_unit,
           COALESCE(TRY_CONVERT(DECIMAL(10,2), REPLACE(REPLACE(s.fuel_amount,  '$', ''), ',', '')), 0) AS fuel_amt,
           COALESCE(TRY_CONVERT(DECIMAL(10,2), REPLACE(REPLACE(s.other_amount, '$', ''), ',', '')), 0) AS other_amt,
           s.product, s.site_address, s.ticket_number, UPPER(LTRIM(RTRIM(s.tran_code))) AS tran_code
    INTO #wex
    FROM wsb.stg_wex_activity AS s
    JOIN wsb.stg_vehicle_map AS m ON m.vehicle_text = s.asset_identifier
    JOIN wsb.vehicle AS v ON v.asset_number = m.asset_number;

    INSERT INTO wsb.invoice_line (invoice_id, vehicle_id, line_date, category, description, amount)
    SELECT @invoice_id, vehicle_id, fuel_date, 'Fuel', 'WEX ticket ' + ticket_number, fuel_amt + other_amt
    FROM #wex;

    INSERT INTO wsb.fuel_record (vehicle_id, invoice_line_id, fuel_date, fuel_time, mileage, gallons, cost_per_unit,
                                 total_cost, other_cost, product, site_address, ticket_number, wex_tran_code, source)
    SELECT w.vehicle_id, l.line_id, w.fuel_date, w.fuel_time, w.mileage, w.gallons, w.cost_per_unit,
           w.fuel_amt, w.other_amt, w.product, w.site_address, w.ticket_number,
           (SELECT c.code FROM wsb.wex_code AS c WHERE c.code = w.tran_code), 'WEX Import'
    FROM #wex AS w
    JOIN wsb.invoice_line AS l ON l.invoice_id = @invoice_id AND l.vehicle_id = w.vehicle_id
                              AND l.description = 'WEX ticket ' + w.ticket_number;

    DROP TABLE #wex;
END;
GO
-- Tip: if a ticket number repeats for the same vehicle, the join above returns two fuel
-- rows per ticket. Check:  SELECT ticket_number, COUNT(*) FROM wsb.fuel_record GROUP BY ticket_number HAVING COUNT(*) > 1;

-- ---------------------------------------------------------------------
-- SOURCE 3: Vehicle and Boat Maintenance sheet (one tab per fiscal year)
-- Columns: Date | Purchaser | Vehicle/Vessel | Repair items | Vendor | Funding source/account | Cost | Total Cost | P-Card WorkDay #
-- Do NOT load "TOTAL SPENT": the database calculates totals (v_cost_by_vehicle_fy).
-- ---------------------------------------------------------------------
IF OBJECT_ID('wsb.stg_maintenance_sheet') IS NULL
    CREATE TABLE wsb.stg_maintenance_sheet (
        entry_date NVARCHAR(30), purchaser NVARCHAR(100), vehicle_text NVARCHAR(200),
        repair_items NVARCHAR(MAX), vendor NVARCHAR(100), funding_source NVARCHAR(100),
        cost NVARCHAR(30), total_cost NVARCHAR(30), pcard_workday_no NVARCHAR(50)
    );
GO

-- TRANSFORM 3: one invoice per sheet row (the sheet has no invoice numbers), one line,
-- one maintenance record. invoice_number = 'SHEET-<yyyymmdd>-<row>' so it is unique and traceable.
SELECT IDENTITY(INT, 1, 1) AS rn,
       TRY_CONVERT(DATE, s.entry_date) AS d,
       TRY_CONVERT(DECIMAL(10,2), REPLACE(REPLACE(s.cost, '$', ''), ',', '')) AS cost_n,
       s.purchaser, s.vehicle_text, s.repair_items,
       COALESCE(NULLIF(LTRIM(RTRIM(s.vendor)), ''), 'Unknown') AS vendor,
       s.funding_source, s.pcard_workday_no
INTO #m
FROM wsb.stg_maintenance_sheet AS s
WHERE TRY_CONVERT(DATE, s.entry_date) IS NOT NULL
  AND TRY_CONVERT(DECIMAL(10,2), REPLACE(REPLACE(s.cost, '$', ''), ',', '')) IS NOT NULL;

INSERT INTO wsb.invoice (invoice_number, invoice_type, vendor, invoice_date, total_amount, funding_source, pcard_workday_no, purchaser)
SELECT 'SHEET-' + CONVERT(VARCHAR(8), d, 112) + '-' + CAST(rn AS VARCHAR(10)), 'Maintenance',
       vendor, d, cost_n, funding_source, pcard_workday_no, purchaser
FROM #m;

INSERT INTO wsb.invoice_line (invoice_id, vehicle_id, line_date, category, description, amount)
SELECT i.invoice_id, v.vehicle_id, m.d, 'Repair', m.repair_items, m.cost_n
FROM #m AS m
JOIN wsb.invoice AS i ON i.invoice_number = 'SHEET-' + CONVERT(VARCHAR(8), m.d, 112) + '-' + CAST(m.rn AS VARCHAR(10))
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

DROP TABLE #m;
GO

-- ---------------------------------------------------------------------
-- AFTER IMPORT: sanity checks, then clean up
-- ---------------------------------------------------------------------
-- SELECT COUNT(*) FROM wsb.trip; SELECT COUNT(*) FROM wsb.fuel_record; SELECT COUNT(*) FROM wsb.invoice;
-- SELECT * FROM wsb.v_invoice_reconciliation WHERE unassigned_difference <> 0;
-- SELECT * FROM wsb.invoice_line WHERE vehicle_id IS NULL AND category <> 'Fee';
-- TRUNCATE TABLE wsb.stg_mileage_log; TRUNCATE TABLE wsb.stg_wex_activity; TRUNCATE TABLE wsb.stg_maintenance_sheet;
GO
