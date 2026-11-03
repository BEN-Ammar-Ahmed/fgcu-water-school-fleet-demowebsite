-- =====================================================================
-- File 03: Reference data + FICTIONAL sample data
-- SQL Server version
-- Run AFTER 01 and 02.
-- =====================================================================

SET NOCOUNT ON;
GO

-- ---------------------------------------------------------------------
-- PART A: WEX Purchase Activity Report code legend
-- ---------------------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'AD')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('AD', 'Transaction', 'Adjustment');
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'CL')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('CL', 'Transaction', 'Cardlock');
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'CP')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('CP', 'Transaction', 'Contract Pricing');
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'EN')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('EN', 'Transaction', 'Enhanced Merchant Network');
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'IP')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('IP', 'Transaction', 'Indoor Payment Terminal');
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'MF')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('MF', 'Transaction', 'Mobile Fueling');
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'MN')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('MN', 'Transaction', 'Manual');
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'OP')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('OP', 'Transaction', 'Outdoor Payment Terminal');
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'PS')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('PS', 'Transaction', 'Private Site');
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'TP')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('TP', 'Transaction', 'Transponder');
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'TR')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('TR', 'Transaction', 'Transaction Reversal');
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'CCF')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('CCF', 'Fee', 'Currency Conversion Fee');
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'EVF')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('EVF', 'Fee', 'Electric Vehicle Fee');
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'PSF')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('PSF', 'Fee', 'Private Site Fee');
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'TSF')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('TSF', 'Fee', 'Truck Stop Fee');
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'CBF')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('CBF', 'Fee', 'Cash Back Fee');
IF NOT EXISTS (SELECT 1 FROM wsb.wex_code WHERE code = 'ONF')
    INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES ('ONF', 'Fee', 'Out of Network Fee');
GO

-- ---------------------------------------------------------------------
-- PART B: SAMPLE DATA (fictional)
-- ---------------------------------------------------------------------

INSERT INTO wsb.driver (first_name, last_name, email, department, driver_type, approved, active)
VALUES
    ('Alex', 'Rivera', 'arivera@example.edu', 'Marine Operations', 'Staff', 1, 1),
    ('Jordan', 'Lee', 'jlee@example.edu', 'Research', 'Faculty', 1, 1),
    ('Sam', 'Patel', 'spatel@example.edu', 'Outreach', 'OPS', 0, 1);
GO

INSERT INTO wsb.driver_license (driver_id, license_number, state, expiration_date, license_file, verified_date, verified_by)
SELECT d.driver_id,
       'SAMPLE-' + CAST(d.driver_id AS varchar(10)) + '0001',
       'FL',
       CAST('2028-06-30' AS date),
       '/secure/licenses/sample_' + CAST(d.driver_id AS varchar(10)) + '.pdf',
       CAST('2026-09-15' AS date),
       'Fleet Manager'
FROM wsb.driver AS d;
GO

INSERT INTO wsb.driver_qualification (driver_id, qualification_type, completed_date, expiration_date, verified_by)
SELECT d.driver_id, q.qualification_type, CAST('2026-08-01' AS date), NULL, 'Fleet Manager'
FROM wsb.driver AS d
CROSS JOIN (VALUES ('Vehicle Use Acknowledgement'), ('Defensive Driving'), ('Fleet Orientation')) AS q(qualification_type)
WHERE d.last_name IN ('Rivera', 'Lee');

INSERT INTO wsb.driver_qualification (driver_id, qualification_type, completed_date, expiration_date, verified_by)
SELECT d.driver_id, 'Boater Safety Course', CAST('2026-07-10' AS date), CAST('2031-07-10' AS date), 'Marine Operations Manager'
FROM wsb.driver AS d
WHERE d.last_name = 'Rivera';
GO

INSERT INTO wsb.vehicle (asset_number, vehicle_type, make, model, year, vin, license_plate, department, wex_card_last4,
                        current_mileage, current_hours, location, status, notes)
VALUES
    ('SAMPLE-T01', 'Truck', 'Ford', 'F-250', 2021, 'SAMPLEVIN0000000T1', 'SMP-T01', 'Marine Operations', '1111', 48210, NULL, 'Main Lot', 'Available', 'Tow truck for trailered vessels'),
    ('SAMPLE-C01', 'Car', 'Toyota', 'Camry', 2019, 'SAMPLEVIN0000000C1', 'SMP-C01', 'Research', '2222', 61500, NULL, 'Main Lot', 'Available', NULL),
    ('SAMPLE-B01', 'Boat', 'Carolina Skiff', '21 DLV', 2020, 'SAMPLEHIN0000000B1', 'FL1234SM', 'Marine Operations', NULL, NULL, 512.5, 'Boatyard', 'Available', 'Research skiff'),
    ('SAMPLE-TR1', 'Trailer', 'Load Rite', 'Aluminum Tandem', 2020, 'SAMPLEVIN0000000R1', 'SMP-R01', 'Marine Operations', NULL, NULL, NULL, 'Boatyard', 'Available', NULL),
    ('SAMPLE-G01', 'Golf Cart', 'Club Car', 'Carryall', 2018, 'SAMPLEVIN0000000G1', NULL, 'Outreach', NULL, NULL, NULL, 'Campus', 'In Maintenance', 'Needs new batteries');
GO

INSERT INTO wsb.vehicle_document (vehicle_id, document_type, file_location, issue_date, expiration_date, access_level, notes)
SELECT v.vehicle_id, 'Registration', '/secure/docs/sample_reg_' + v.asset_number + '.pdf', CAST('2026-01-15' AS date), CAST('2027-01-15' AS date), 'General', NULL
FROM wsb.vehicle AS v
WHERE v.asset_number = 'SAMPLE-T01'
UNION ALL
SELECT v.vehicle_id, 'Insurance - Auto Liability', '/secure/docs/sample_al.pdf', CAST('2026-07-01' AS date), CAST('2027-06-30' AS date), 'Staff', NULL
FROM wsb.vehicle AS v
WHERE v.asset_number = 'SAMPLE-T01'
UNION ALL
SELECT v.vehicle_id, 'Title', '/secure/docs/sample_title.pdf', CAST('2021-03-01' AS date), NULL, 'Admin', 'Original title on file in Fleet Office'
FROM wsb.vehicle AS v
WHERE v.asset_number = 'SAMPLE-T01';
GO

INSERT INTO wsb.maintenance_rule (vehicle_id, maintenance_type, mileage_interval, time_interval_months, last_completed_mileage, last_completed_date)
SELECT v.vehicle_id, 'Oil Change', 5000, 6, 45000, CAST('2026-03-10' AS date)
FROM wsb.vehicle AS v
WHERE v.asset_number = 'SAMPLE-T01'
UNION ALL
SELECT v.vehicle_id, 'Oil Change', 5000, 6, 58000, CAST('2026-06-01' AS date)
FROM wsb.vehicle AS v
WHERE v.asset_number = 'SAMPLE-C01'
UNION ALL
SELECT v.vehicle_id, 'Tire Rotation', 7500, NULL, 55000, CAST('2026-02-01' AS date)
FROM wsb.vehicle AS v
WHERE v.asset_number = 'SAMPLE-C01';
GO

-- Invoice 1: a WEX monthly statement covering two vehicles ---------------
INSERT INTO wsb.invoice (invoice_number, invoice_type, vendor, invoice_date, payment_due_date, total_amount,
                        funding_source, account_number_last4, invoice_file, notes)
VALUES ('SAMPLE-WEX-001', 'WEX Statement', 'WEX Bank', CAST('2026-10-15' AS date), CAST('2026-11-05' AS date), 187.40,
        'Fleet Fuel Account', '9999', '/secure/invoices/sample_wex_2026_10.pdf', 'Fictional sample statement');
GO

INSERT INTO wsb.invoice_line (invoice_id, vehicle_id, line_date, category, description, amount)
SELECT i.invoice_id, v.vehicle_id, CAST('2026-10-03' AS date), 'Fuel', 'Regular unleaded, sample station', 92.15
FROM wsb.invoice AS i
CROSS JOIN wsb.vehicle AS v
WHERE i.invoice_number = 'SAMPLE-WEX-001' AND v.asset_number = 'SAMPLE-T01'
UNION ALL
SELECT i.invoice_id, v.vehicle_id, CAST('2026-10-09' AS date), 'Fuel', 'Regular unleaded, sample station', 60.25
FROM wsb.invoice AS i
CROSS JOIN wsb.vehicle AS v
WHERE i.invoice_number = 'SAMPLE-WEX-001' AND v.asset_number = 'SAMPLE-C01'
UNION ALL
SELECT i.invoice_id, NULL, CAST('2026-10-15' AS date), 'Fee', 'Monthly account fee', 35.00
FROM wsb.invoice AS i
WHERE i.invoice_number = 'SAMPLE-WEX-001';
GO

-- Invoice 2: a maintenance shop invoice paid by P-Card -------------------
INSERT INTO wsb.invoice (invoice_number, invoice_type, vendor, invoice_date, total_amount, funding_source,
                        pcard_workday_no, purchaser, invoice_file)
VALUES ('SAMPLE-SHOP-5521', 'Maintenance', 'Sample Auto Care', CAST('2026-09-22' AS date), 148.99,
        'Marine Ops operating budget', 'SAMPLE_PCT', 'Alex Rivera', '/secure/invoices/sample_shop_5521.pdf');
GO

INSERT INTO wsb.invoice_line (invoice_id, vehicle_id, line_date, category, description, amount)
SELECT i.invoice_id, v.vehicle_id, CAST('2026-09-22' AS date), 'Service', 'Oil and filter change', 89.99
FROM wsb.invoice AS i
CROSS JOIN wsb.vehicle AS v
WHERE i.invoice_number = 'SAMPLE-SHOP-5521' AND v.asset_number = 'SAMPLE-C01'
UNION ALL
SELECT i.invoice_id, v.vehicle_id, CAST('2026-09-22' AS date), 'Parts', 'Wiper blades', 59.00
FROM wsb.invoice AS i
CROSS JOIN wsb.vehicle AS v
WHERE i.invoice_number = 'SAMPLE-SHOP-5521' AND v.asset_number = 'SAMPLE-C01';
GO

INSERT INTO wsb.maintenance_record (vehicle_id, invoice_line_id, service_date, mileage_at_service, service_type, cost, vendor, description, next_service_date, next_service_mileage)
SELECT v.vehicle_id, l.line_id, CAST('2026-09-22' AS date), 61200, 'Oil Change', 89.99, 'Sample Auto Care', 'Oil and filter change', CAST('2027-03-22' AS date), 66200
FROM wsb.vehicle AS v
JOIN wsb.invoice_line AS l ON l.vehicle_id = v.vehicle_id
JOIN wsb.invoice AS i ON i.invoice_id = l.invoice_id
WHERE v.asset_number = 'SAMPLE-C01' AND i.invoice_number = 'SAMPLE-SHOP-5521' AND l.category = 'Service';
GO

-- Trips + fuel -----------------------------------------------------------
INSERT INTO wsb.trip (vehicle_id, driver_id, start_datetime, end_datetime, starting_mileage, ending_mileage, destination, purpose, project_program, notes)
SELECT v.vehicle_id, d.driver_id, CAST('2026-10-03 08:00' AS datetime2), CAST('2026-10-03 16:30' AS datetime2), 48100, 48210,
       'Sample Boat Ramp', 'Trailer vessel to field site', 'Water Quality Monitoring', 'Sample trip'
FROM wsb.vehicle AS v
CROSS JOIN wsb.driver AS d
WHERE v.asset_number = 'SAMPLE-T01' AND d.last_name = 'Rivera'
UNION ALL
SELECT v.vehicle_id, d.driver_id, CAST('2026-10-09 09:00' AS datetime2), CAST('2026-10-09 12:00' AS datetime2), 61400, 61500,
       'Sample Community Center', 'Outreach presentation', 'Community Outreach', NULL
FROM wsb.vehicle AS v
CROSS JOIN wsb.driver AS d
WHERE v.asset_number = 'SAMPLE-C01' AND d.last_name = 'Lee';
GO

INSERT INTO wsb.fuel_record (vehicle_id, trip_id, invoice_line_id, fuel_date, fuel_time, mileage, gallons, cost_per_unit, total_cost, product, vendor, site_address, ticket_number, wex_tran_code, source)
SELECT v.vehicle_id, t.trip_id, l.line_id, CAST('2026-10-03' AS date), CAST('15:45' AS time), 48205, 24.500, 3.761, 92.15, 'Reg', 'Sample Gas', '123 Sample Rd', 'SAMPLE0001', 'OP', 'WEX Import'
FROM wsb.vehicle AS v
JOIN wsb.trip AS t ON t.vehicle_id = v.vehicle_id
JOIN wsb.invoice_line AS l ON l.vehicle_id = v.vehicle_id
JOIN wsb.invoice AS i ON i.invoice_id = l.invoice_id
WHERE v.asset_number = 'SAMPLE-T01' AND i.invoice_number = 'SAMPLE-WEX-001';
GO

-- Fuel with NO trip (common on WEX statements)
INSERT INTO wsb.fuel_record (vehicle_id, invoice_line_id, fuel_date, mileage, gallons, cost_per_unit, total_cost, product, vendor, ticket_number, wex_tran_code, source)
SELECT v.vehicle_id, l.line_id, CAST('2026-10-09' AS date), 61490, 16.000, 3.766, 60.25, 'Reg', 'Sample Gas', 'SAMPLE0002', 'IP', 'WEX Import'
FROM wsb.vehicle AS v
JOIN wsb.invoice_line AS l ON l.vehicle_id = v.vehicle_id
JOIN wsb.invoice AS i ON i.invoice_id = l.invoice_id
WHERE v.asset_number = 'SAMPLE-C01' AND i.invoice_number = 'SAMPLE-WEX-001';
GO

-- ---------------------------------------------------------------------
-- QUICK CHECKS - run these after loading:
-- ---------------------------------------------------------------------
-- SELECT * FROM wsb.v_cost_by_vehicle_fy;
-- SELECT * FROM wsb.v_invoice_reconciliation;
-- SELECT * FROM wsb.v_maintenance_due;
-- SELECT * FROM wsb.v_state_audit_vehicle_log;
GO

-- ---------------------------------------------------------------------
-- CLEAR SAMPLE DATA (run before loading real data; keeps reference data)
-- ---------------------------------------------------------------------
-- DELETE FROM wsb.fuel_record WHERE ticket_number LIKE 'SAMPLE%';
-- DELETE FROM wsb.maintenance_record WHERE vehicle_id IN (SELECT vehicle_id FROM wsb.vehicle WHERE asset_number LIKE 'SAMPLE-%');
-- DELETE FROM wsb.trip WHERE vehicle_id IN (SELECT vehicle_id FROM wsb.vehicle WHERE asset_number LIKE 'SAMPLE-%');
-- DELETE FROM wsb.invoice WHERE invoice_number LIKE 'SAMPLE-%';
-- DELETE FROM wsb.vehicle WHERE asset_number LIKE 'SAMPLE-%';
-- DELETE FROM wsb.driver WHERE email LIKE '%@example.edu';
GO
