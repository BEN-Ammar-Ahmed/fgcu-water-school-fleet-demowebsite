-- =====================================================================
-- Water School Vehicle Management Database - DATA POPULATION   SQL Server
-- Run AFTER 01_schema.sql and 02_security.sql.
--   PART A  reference data (real: WEX code legend, security roles) - keep in production
--   PART B  demonstration data - FICTIONAL names, VINs, plates and amounts.
--           The real Water School records contain personal and financial details,
--           so these rows imitate their structure (WEX statements, maintenance
--           sheet, mileage log) without using any real data.
--           Every demo row is tagged DEMO or uses an @example.edu address so the
--           CLEAR block at the bottom can remove it before real data is loaded.
-- =====================================================================
SET NOCOUNT ON;
GO

-- ---------------------------------------------------------------------
-- PART A: reference data
-- ---------------------------------------------------------------------
INSERT INTO wsb.wex_code (code, code_type, meaning)
SELECT v.code, v.code_type, v.meaning
FROM (VALUES
 ('AD','Transaction','Adjustment'),
 ('CL','Transaction','Cardlock'),
 ('CP','Transaction','Contract Pricing'),
 ('EN','Transaction','Enhanced Merchant Network'),
 ('IP','Transaction','Indoor Payment Terminal'),
 ('MF','Transaction','Mobile Fueling'),
 ('MN','Transaction','Manual'),
 ('OP','Transaction','Outdoor Payment Terminal'),
 ('PS','Transaction','Private Site'),
 ('TP','Transaction','Transponder'),
 ('TR','Transaction','Transaction Reversal'),
 ('CCF','Fee','Currency Conversion Fee'),
 ('EVF','Fee','Electric Vehicle Fee'),
 ('PSF','Fee','Private Site Fee'),
 ('TSF','Fee','Truck Stop Fee'),
 ('CBF','Fee','Cash Back Fee'),
 ('ONF','Fee','Out of Network Fee')
) AS v(code, code_type, meaning)
WHERE NOT EXISTS (SELECT 1 FROM wsb.wex_code w WHERE w.code = v.code);
GO

INSERT INTO wsb.app_role (role_name, pg_role, description)
SELECT v.role_name, v.pg_role, v.description
FROM (VALUES
 ('Admin',     'wsb_admin',    'Full access: manage users, delete records, see all documents'),
 ('Staff',     'wsb_staff',    'Add and edit operational data; cannot delete or manage users'),
 ('Read-only', 'wsb_readonly', 'View vehicles, trips, fuel, maintenance, invoices and reports only')
) AS v(role_name, pg_role, description)
WHERE NOT EXISTS (SELECT 1 FROM wsb.app_role r WHERE r.role_name = v.role_name);
GO

-- ---------------------------------------------------------------------
-- PART B: demonstration data
-- ---------------------------------------------------------------------

-- Drivers (6) ----------------------------------------------------------
INSERT INTO wsb.driver (first_name, last_name, email, department, driver_type, approved, active) VALUES
 ('Alex',   'Rivera',  'arivera@example.edu',  'Marine Operations', 'Staff',   1, 1),
 ('Jordan', 'Lee',     'jlee@example.edu',     'Research',          'Faculty', 1, 1),
 ('Sam',    'Patel',   'spatel@example.edu',   'Outreach',          'OPS',     0, 1),
 ('Morgan', 'Diaz',    'mdiaz@example.edu',    'Marine Operations', 'OPS',     1, 1),
 ('Taylor', 'Nguyen',  'tnguyen@example.edu',  'Research',          'Faculty', 1, 1),
 ('Casey',  'Brooks',  'cbrooks@example.edu',  'Administration',    'Staff',   1, 0);
GO

-- Driver licenses (one per driver; Sam Patel's expires soon) -----------
INSERT INTO wsb.driver_license (driver_id, license_number, state, expiration_date, license_file, verified_date, verified_by)
SELECT d.driver_id,
       'DEMO-DL-' + RIGHT('0000' + CAST(d.driver_id AS VARCHAR(10)), 4),
       'FL',
       CASE WHEN d.last_name = 'Patel' THEN CAST('2026-12-15' AS DATE)
            ELSE DATEADD(DAY, d.driver_id * 30, CAST('2028-06-30' AS DATE)) END,
       '/secure/licenses/demo_' + CAST(d.driver_id AS VARCHAR(10)) + '.pdf',
       CAST('2026-09-15' AS DATE),
       'Fleet Manager'
FROM wsb.driver AS d
WHERE d.email LIKE '%@example.edu';
GO

-- Driver qualifications (from the Driver Eligibility & Requirements sheet) -
INSERT INTO wsb.driver_qualification (driver_id, qualification_type, completed_date, expiration_date, verified_by)
SELECT d.driver_id, q.t, CAST('2026-08-01' AS DATE), NULL, 'Fleet Manager'
FROM wsb.driver AS d
CROSS JOIN (VALUES ('Vehicle Use Acknowledgement'), ('FL License Check'), ('Defensive Driving'), ('Fleet Orientation')) AS q(t)
WHERE d.approved = 1 AND d.email LIKE '%@example.edu';

INSERT INTO wsb.driver_qualification (driver_id, qualification_type, completed_date, expiration_date, verified_by)
SELECT d.driver_id, v.t, CAST(v.c AS DATE), CAST(v.e AS DATE), 'Marine Operations Manager'
FROM wsb.driver AS d
JOIN (VALUES
    ('Rivera', 'Boater Safety Course', '2026-07-10', '2031-07-10'),
    ('Diaz',   'Boater Safety Course', '2026-07-18', '2031-07-18'),
    ('Lee',    'Boater Safety Course', '2026-08-05', '2031-08-05'),
    ('Rivera', 'Trailer Training',     '2026-08-20', NULL),
    ('Diaz',   'Trailer Training',     '2026-08-20', NULL),
    ('Patel',  'Golf Cart Training',   '2026-09-30', NULL)
) AS v(ln, t, c, e) ON v.ln = d.last_name
WHERE d.email LIKE '%@example.edu';
GO

-- Vehicles (8: 2 trucks, 2 cars, 2 boats, 1 trailer, 1 golf cart) ------
INSERT INTO wsb.vehicle (asset_number, vehicle_type, make, model, year, vin, license_plate, department, wex_card_last4,
                         current_mileage, current_hours, location, status, notes) VALUES
 ('DEMO-T01','Truck',    'Ford',           'F-250',           2021,'DEMOVIN0000000T01','DMO-T01', 'Marine Operations','1101',48210,NULL, 'Main Lot','In Use',         'Tow truck for trailered vessels'),
 ('DEMO-T02','Truck',    'Chevrolet',      'Silverado 1500',  2022,'DEMOVIN0000000T02','DMO-T02', 'Marine Operations','1102',30420,NULL, 'Main Lot','Available',      NULL),
 ('DEMO-C01','Car',      'Toyota',         'Camry',           2019,'DEMOVIN0000000C01','DMO-C01', 'Research',         '1201',61500,NULL, 'Main Lot','Available',      NULL),
 ('DEMO-C02','Car',      'Ford',           'Escape',          2023,'DEMOVIN0000000C02','DMO-C02', 'Research',         '1202',22090,NULL, 'Main Lot','Available',      NULL),
 ('DEMO-B01','Boat',     'Carolina Skiff', '21 DLV',          2020,'DEMOHIN0000000B01','FL1001DM','Marine Operations',NULL,  NULL, 512.5,'Boatyard','Available',      'Primary research skiff'),
 ('DEMO-B02','Boat',     'Boston Whaler',  '170 Montauk',     2018,'DEMOHIN0000000B02','FL1002DM','Marine Operations',NULL,  NULL, 880.0,'Boatyard','In Maintenance', 'Console repair pending'),
 ('DEMO-TR1','Trailer',  'Load Rite',      'Aluminum Tandem', 2020,'DEMOVIN0000000TR1','DMO-R01', 'Marine Operations',NULL,  NULL, NULL, 'Boatyard','Available',      'Fits DEMO-B01'),
 ('DEMO-G01','Golf Cart','Club Car',       'Carryall 300',    2018,'DEMOVIN0000000G01',NULL,      'Outreach',         NULL,  NULL, NULL, 'Campus',  'Out of Service', 'Needs new batteries');
GO

-- Vehicle documents (access_level drives row-level security) -----------
INSERT INTO wsb.vehicle_document (vehicle_id, document_type, file_location, issue_date, expiration_date, access_level, notes)
SELECT v.vehicle_id, d.t, '/secure/docs/' + v.asset_number + '_' + d.f + '.pdf', CAST(d.i AS DATE), CAST(d.e AS DATE), d.a, d.n
FROM wsb.vehicle AS v
CROSS JOIN (VALUES
   ('Registration',               'reg',   '2026-01-15', '2027-01-15', 'General', NULL),
   ('Insurance - Auto Liability', 'al',    '2026-07-01', '2027-06-30', 'Staff',   NULL),
   ('Title',                      'title', '2021-03-01', NULL,         'Admin',   'Original title in Fleet Office')
) AS d(t, f, i, e, a, n)
WHERE v.asset_number IN ('DEMO-T01','DEMO-T02','DEMO-C01','DEMO-C02');

INSERT INTO wsb.vehicle_document (vehicle_id, document_type, file_location, issue_date, expiration_date, access_level, notes)
SELECT v.vehicle_id, d.t, '/secure/docs/' + v.asset_number + '_' + d.f + '.pdf', CAST(d.i AS DATE), CAST(d.e AS DATE), d.a, NULL
FROM wsb.vehicle AS v
CROSS JOIN (VALUES
   ('Registration',                  'reg', '2026-06-20', '2027-06-20', 'General'),
   ('Insurance - General Liability', 'gl',  '2026-07-01', '2027-06-30', 'Staff')
) AS d(t, f, i, e, a)
WHERE v.asset_number IN ('DEMO-B01','DEMO-B02');
GO

-- Recurring maintenance rules (DEMO-T01 oil change is overdue by date) ---
INSERT INTO wsb.maintenance_rule (vehicle_id, maintenance_type, mileage_interval, time_interval_months, last_completed_mileage, last_completed_date)
SELECT v.vehicle_id, r.t, r.mi, r.mo, r.lm, CAST(r.ld AS DATE)
FROM wsb.vehicle AS v
JOIN (VALUES
    ('DEMO-T01','Oil Change',           5000, 6,    45000, '2026-03-10'),
    ('DEMO-T02','Oil Change',           5000, 6,    28000, '2026-08-15'),
    ('DEMO-C01','Oil Change',           5000, 6,    58000, '2026-06-01'),
    ('DEMO-C02','Oil Change',           5000, 6,    20000, '2026-07-30'),
    ('DEMO-C01','Tire Rotation',        7500, NULL, 55000, '2026-02-01'),
    ('DEMO-B01','Outboard Service',     NULL, 12,   NULL,  '2026-09-22'),
    ('DEMO-TR1','Wheel Bearing Repack', NULL, 12,   NULL,  '2026-01-20')
) AS r(a, t, mi, mo, lm, ld) ON r.a = v.asset_number;
GO

-- Invoices (6) ---------------------------------------------------------
INSERT INTO wsb.invoice (invoice_number, invoice_type, vendor, invoice_date, payment_due_date, total_amount,
                         funding_source, pcard_workday_no, purchaser, account_number_last4, invoice_file, notes) VALUES
 ('DEMO-WEX-2026-09','WEX Statement','WEX Bank','2026-09-15','2026-10-06',217.75,'Fleet Fuel Account',NULL,NULL,'9999','/secure/invoices/demo_wex_2026_09.pdf','Monthly WEX statement'),
 ('DEMO-WEX-2026-10','WEX Statement','WEX Bank','2026-10-15','2026-11-05',266.25,'Fleet Fuel Account',NULL,NULL,'9999','/secure/invoices/demo_wex_2026_10.pdf','Monthly WEX statement'),
 ('DEMO-SHOP-1001','Maintenance','Gulf Coast Auto Care','2026-08-12',NULL,502.00,'Marine Ops operating budget','DEMO_PCT_1','Alex Rivera',NULL,'/secure/invoices/demo_shop_1001.pdf',NULL),
 ('DEMO-SHOP-1002','Maintenance','Bay Marine Services','2026-09-22',NULL,404.00,'Marine Ops operating budget','DEMO_PCT_2','Morgan Diaz',NULL,'/secure/invoices/demo_shop_1002.pdf',NULL),
 ('DEMO-PARTS-2001','Parts','Sample Parts Supply','2026-07-30',NULL,61.48,'Research operating budget','DEMO_PCT_3','Jordan Lee',NULL,'/secure/invoices/demo_parts_2001.pdf',NULL),
 ('DEMO-REG-3001','Registration/Insurance','FL Dept of Highway Safety','2026-06-20',NULL,98.00,'Marine Ops operating budget',NULL,'Alex Rivera',NULL,'/secure/invoices/demo_reg_3001.pdf','Falls in FY25-26');
GO

-- Invoice lines: each charge tied to ONE vehicle (or none for account fees) ----
INSERT INTO wsb.invoice_line (invoice_id, vehicle_id, line_date, category, description, amount)
SELECT i.invoice_id, v.vehicle_id, CAST(l.d AS DATE), l.c, l.ds, l.amt
FROM (VALUES
 ('DEMO-WEX-2026-09','DEMO-T01','2026-09-04','Fuel',   'WEX ticket DEMO-A1',  88.40),
 ('DEMO-WEX-2026-09','DEMO-T02','2026-09-18','Fuel',   'WEX ticket DEMO-A2',  76.10),
 ('DEMO-WEX-2026-09','DEMO-C01','2026-09-25','Fuel',   'WEX ticket DEMO-A3',  41.25),
 ('DEMO-WEX-2026-09',NULL,      '2026-09-15','Fee',    'Monthly account fee', 12.00),
 ('DEMO-WEX-2026-10','DEMO-T01','2026-10-03','Fuel',   'WEX ticket DEMO-B1',  92.15),
 ('DEMO-WEX-2026-10','DEMO-C02','2026-10-09','Fuel',   'WEX ticket DEMO-B2',  55.60),
 ('DEMO-WEX-2026-10','DEMO-T02','2026-10-20','Fuel',   'WEX ticket DEMO-B3',  68.30),
 ('DEMO-WEX-2026-10','DEMO-B01','2026-10-03','Fuel',   'WEX ticket DEMO-B4',  38.20),
 ('DEMO-WEX-2026-10',NULL,      '2026-10-15','Fee',    'Monthly account fee', 12.00),
 ('DEMO-SHOP-1001',  'DEMO-T01','2026-08-12','Repair', 'Front brake pads and rotors', 412.50),
 ('DEMO-SHOP-1001',  'DEMO-T01','2026-08-12','Service','Brake fluid flush',            89.50),
 ('DEMO-SHOP-1002',  'DEMO-B01','2026-09-22','Service','Outboard 100-hour service',   340.00),
 ('DEMO-SHOP-1002',  'DEMO-B01','2026-09-22','Parts',  'Impeller kit',                 64.00),
 ('DEMO-PARTS-2001', 'DEMO-C01','2026-07-30','Parts',  'Wiper blades - Camry',         29.99),
 ('DEMO-PARTS-2001', 'DEMO-C02','2026-07-30','Parts',  'Wiper blades - Escape',        31.49),
 ('DEMO-REG-3001',   'DEMO-B01','2026-06-20','Registration','Annual vessel registration',98.00)
) AS l(inv, asset, d, c, ds, amt)
JOIN wsb.invoice AS i ON i.invoice_number = l.inv
LEFT JOIN wsb.vehicle AS v ON v.asset_number = l.asset;
GO

-- Trips (8; the last one is still open) --------------------------------
INSERT INTO wsb.trip (vehicle_id, driver_id, start_datetime, end_datetime, starting_mileage, ending_mileage, destination, purpose, project_program, notes)
SELECT v.vehicle_id, d.driver_id, CAST(t.s AS DATETIME2), CAST(t.e AS DATETIME2), t.sm, t.em, t.dest, t.pur, t.prog, t.n
FROM (VALUES
 ('DEMO-T01','Rivera','2026-09-04 08:00','2026-09-04 16:00',47900,47990,'Sanibel Causeway Ramp','Trailer skiff to field site','Water Quality Monitoring',NULL),
 ('DEMO-T02','Diaz',  '2026-09-18 07:30','2026-09-18 15:45',30050,30230,'Lake Okeechobee Ramp','Trailer vessel for sampling','Estuary Research',NULL),
 ('DEMO-C01','Lee',   '2026-09-25 09:00','2026-09-25 13:00',61250,61330,'Fort Myers Library','Outreach talk','Community Outreach',NULL),
 ('DEMO-T01','Rivera','2026-10-03 08:00','2026-10-03 16:30',48100,48210,'Matlacha Boat Ramp','Trailer skiff to field site','Water Quality Monitoring','Boat battery switch confirmed off before departure'),
 ('DEMO-C02','Nguyen','2026-10-09 09:00','2026-10-09 12:00',22000,22090,'Naples Conservation Center','Site visit','Estuary Research',NULL),
 ('DEMO-T02','Diaz',  '2026-10-20 06:45','2026-10-20 17:00',30300,30420,'Charlotte Harbor Ramp','Trailer vessel for sampling','Estuary Research',NULL),
 ('DEMO-C01','Lee',   '2026-10-27 10:00','2026-10-27 14:30',61400,61500,'Estero Elementary School','STEM outreach','Community Outreach',NULL),
 ('DEMO-T01','Rivera','2026-10-29 08:00',NULL,              48210,NULL, 'Bokeelia Ramp','Trailer skiff to field site','Water Quality Monitoring','Trip still open')
) AS t(a, ln, s, e, sm, em, dest, pur, prog, n)
JOIN wsb.vehicle AS v ON v.asset_number = t.a
JOIN wsb.driver  AS d ON d.last_name = t.ln AND d.email LIKE '%@example.edu';
GO

-- Fuel records: WEX lines (linked to invoice lines; trip link optional) ---
INSERT INTO wsb.fuel_record (vehicle_id, trip_id, invoice_line_id, fuel_date, fuel_time, mileage, gallons, cost_per_unit,
                             total_cost, product, vendor, site_address, ticket_number, wex_tran_code, source)
SELECT v.vehicle_id, tr.trip_id, l.line_id, CAST(f.d AS DATE), CAST(f.tm AS TIME), f.mi, f.g, f.cpu,
       l.amount, 'Reg', f.vend, f.addr, f.tk, f.tc, 'WEX Import'
FROM (VALUES
 ('DEMO-A1','DEMO-T01','2026-09-04','15:20',47980,23.263,3.800,'Sample Gas A','101 Demo Rd, Fort Myers FL','OP'),
 ('DEMO-A2','DEMO-T02','2026-09-18','14:55',30210,20.026,3.800,'Sample Gas B','202 Demo Ave, Clewiston FL','IP'),
 ('DEMO-A3','DEMO-C01','2026-09-25','12:30',61320,10.855,3.800,'Sample Gas A','101 Demo Rd, Fort Myers FL','OP'),
 ('DEMO-B1','DEMO-T01','2026-10-03','15:45',48205,24.250,3.800,'Sample Gas C','303 Demo Blvd, Matlacha FL','OP'),
 ('DEMO-B2','DEMO-C02','2026-10-09','11:20',22085,14.632,3.800,'Sample Gas A','101 Demo Rd, Fort Myers FL','IP'),
 ('DEMO-B3','DEMO-T02','2026-10-20','16:10',30415,17.974,3.800,'Sample Gas D','404 Demo St, Punta Gorda FL','OP'),
 ('DEMO-B4','DEMO-B01','2026-10-03','13:10',NULL, 10.053,3.800,'Sample Marina','505 Demo Way, Matlacha FL','MF')
) AS f(tk, a, d, tm, mi, g, cpu, vend, addr, tc)
JOIN wsb.vehicle AS v ON v.asset_number = f.a
JOIN wsb.invoice_line AS l ON l.description = 'WEX ticket ' + f.tk
LEFT JOIN wsb.trip AS tr ON tr.vehicle_id = v.vehicle_id AND CAST(tr.start_datetime AS DATE) = CAST(f.d AS DATE);
GO

-- Fuel with no WEX invoice (manual entry from the paper mileage log) -----
INSERT INTO wsb.fuel_record (vehicle_id, trip_id, fuel_date, mileage, gallons, total_cost, vendor, source)
SELECT vehicle_id, NULL, CAST('2026-10-27' AS DATE), 61480, 9.100, 34.58, 'Sample Gas A', 'Mileage Log'
FROM wsb.vehicle WHERE asset_number = 'DEMO-C01';
GO

-- Maintenance records (most linked to invoice lines; one is a plain oil change) ----
INSERT INTO wsb.maintenance_record (vehicle_id, invoice_line_id, service_date, mileage_at_service, service_type, cost, vendor, description, next_service_date, next_service_mileage)
SELECT v.vehicle_id, l.line_id, CAST(m.sd AS DATE), m.mi, m.st, m.cost, m.vend, m.ds, CAST(m.nd AS DATE), m.nm
FROM (VALUES
 ('DEMO-T01','DEMO-SHOP-1001', 'Front brake pads and rotors','2026-08-12',47100,'Brake Service',     412.50,'Gulf Coast Auto Care','Replaced front pads and rotors',NULL,NULL),
 ('DEMO-T01','DEMO-SHOP-1001', 'Brake fluid flush',          '2026-08-12',47100,'Brake Fluid Flush', 89.50,'Gulf Coast Auto Care','Flushed and refilled brake fluid','2028-08-12',NULL),
 ('DEMO-B01','DEMO-SHOP-1002', 'Outboard 100-hour service',  '2026-09-22',NULL, 'Outboard Service', 340.00,'Bay Marine Services', 'Lower unit oil, plugs, filters','2027-09-22',NULL),
 ('DEMO-B01','DEMO-SHOP-1002', 'Impeller kit',               '2026-09-22',NULL, 'Parts',             64.00,'Bay Marine Services', 'Water pump impeller replaced',NULL,NULL),
 ('DEMO-C02','DEMO-PARTS-2001','Wiper blades - Escape',      '2026-07-30',20010,'Wiper Blades',      31.49,'Sample Parts Supply', 'Front wiper blades',NULL,NULL),
 ('DEMO-C01',NULL,             NULL,                         '2026-06-01',58000,'Oil Change',        74.99,'Gulf Coast Auto Care','Oil and filter','2026-12-01',63000)
) AS m(a, inv, ld, sd, mi, st, cost, vend, ds, nd, nm)
JOIN wsb.vehicle AS v ON v.asset_number = m.a
LEFT JOIN wsb.invoice AS i ON i.invoice_number = m.inv
LEFT JOIN wsb.invoice_line AS l ON l.invoice_id = i.invoice_id AND l.description = m.ld;
GO

-- App users (names only; real logins are created with wsb.create_wsb_user) ----
INSERT INTO wsb.app_user (username, full_name, email, role_id)
SELECT u.un, u.fn, u.em, r.role_id
FROM (VALUES ('demo_admin','Demo Admin','demo_admin@example.edu','Admin'),
             ('demo_staff','Demo Staff','demo_staff@example.edu','Staff'),
             ('demo_viewer','Demo Viewer','demo_viewer@example.edu','Read-only')) AS u(un, fn, em, rn)
JOIN wsb.app_role AS r ON r.role_name = u.rn
WHERE NOT EXISTS (SELECT 1 FROM wsb.app_user a WHERE a.username = u.un);
GO

-- ---------------------------------------------------------------------
-- QUICK CHECKS (expected counts in comments)
-- ---------------------------------------------------------------------
-- SELECT 'driver' AS tbl, COUNT(*) AS n FROM wsb.driver                    -- 6
-- UNION ALL SELECT 'driver_license', COUNT(*) FROM wsb.driver_license      -- 6
-- UNION ALL SELECT 'driver_qualification', COUNT(*) FROM wsb.driver_qualification  -- 26
-- UNION ALL SELECT 'vehicle', COUNT(*) FROM wsb.vehicle                    -- 8
-- UNION ALL SELECT 'vehicle_document', COUNT(*) FROM wsb.vehicle_document  -- 16
-- UNION ALL SELECT 'maintenance_rule', COUNT(*) FROM wsb.maintenance_rule  -- 7
-- UNION ALL SELECT 'invoice', COUNT(*) FROM wsb.invoice                    -- 6
-- UNION ALL SELECT 'invoice_line', COUNT(*) FROM wsb.invoice_line          -- 16
-- UNION ALL SELECT 'trip', COUNT(*) FROM wsb.trip                          -- 8
-- UNION ALL SELECT 'fuel_record', COUNT(*) FROM wsb.fuel_record            -- 8
-- UNION ALL SELECT 'maintenance_record', COUNT(*) FROM wsb.maintenance_record;  -- 6
-- SELECT * FROM wsb.v_invoice_reconciliation;  -- unassigned_difference = 0.00 on every row
-- SELECT * FROM wsb.v_cost_by_vehicle_fy;
-- SELECT * FROM wsb.v_maintenance_due;         -- DEMO-T01 oil change shows DUE

-- ---------------------------------------------------------------------
-- CLEAR DEMO DATA (uncomment and run before loading real data; keeps reference data)
-- ---------------------------------------------------------------------
-- DELETE FROM wsb.fuel_record        WHERE vehicle_id IN (SELECT vehicle_id FROM wsb.vehicle WHERE asset_number LIKE 'DEMO-%');
-- DELETE FROM wsb.maintenance_record WHERE vehicle_id IN (SELECT vehicle_id FROM wsb.vehicle WHERE asset_number LIKE 'DEMO-%');
-- DELETE FROM wsb.trip               WHERE vehicle_id IN (SELECT vehicle_id FROM wsb.vehicle WHERE asset_number LIKE 'DEMO-%');
-- DELETE FROM wsb.invoice            WHERE invoice_number LIKE 'DEMO-%';       -- lines cascade
-- DELETE FROM wsb.vehicle            WHERE asset_number  LIKE 'DEMO-%';        -- documents + rules cascade
-- DELETE FROM wsb.driver             WHERE email LIKE '%@example.edu';         -- licenses + qualifications cascade
-- DELETE FROM wsb.app_user           WHERE email LIKE '%@example.edu';
GO
