-- =====================================================================
-- File 06: Security test script   SQL Server
-- Run as sa AFTER 01-05. It impersonates a user in each role (no passwords
-- needed) and shows what is allowed (should succeed) and denied (should fail).
-- Every "EXPECT DENIED" line should print an error message; if one succeeds,
-- the security is wrong. TEST users are created and removed by this script.
-- Run it in blocks (select a block, run) so you can read each result.
-- =====================================================================
SET NOCOUNT ON;

-- Setup: three users without logins, one per role ---------------------------
IF DATABASE_PRINCIPAL_ID('test_admin')  IS NULL CREATE USER test_admin  WITHOUT LOGIN;
IF DATABASE_PRINCIPAL_ID('test_staff')  IS NULL CREATE USER test_staff  WITHOUT LOGIN;
IF DATABASE_PRINCIPAL_ID('test_viewer') IS NULL CREATE USER test_viewer WITHOUT LOGIN;
ALTER ROLE wsb_admin    ADD MEMBER test_admin;
ALTER ROLE wsb_staff    ADD MEMBER test_staff;
ALTER ROLE wsb_readonly ADD MEMBER test_viewer;
GO

-- ===== READ-ONLY =====
EXECUTE AS USER = 'test_viewer';
    SELECT 'viewer: vehicles visible (EXPECT 8 with demo data)' AS test, COUNT(*) AS n FROM wsb.vehicle;
    SELECT 'viewer: documents visible (EXPECT General only: 6 with demo data)' AS test, COUNT(*) AS n FROM wsb.vehicle_document;
    SELECT 'viewer: driver directory works (no email column)' AS test, COUNT(*) AS n FROM wsb.v_driver_directory;
    BEGIN TRY SELECT * FROM wsb.driver_license;               PRINT 'FAIL: viewer read driver_license'; END TRY BEGIN CATCH PRINT 'OK (denied): viewer -> driver_license'; END CATCH;
    BEGIN TRY SELECT email FROM wsb.driver;                   PRINT 'FAIL: viewer read driver.email';   END TRY BEGIN CATCH PRINT 'OK (denied): viewer -> driver';          END CATCH;
    BEGIN TRY SELECT * FROM wsb.app_user;                     PRINT 'FAIL: viewer read app_user';       END TRY BEGIN CATCH PRINT 'OK (denied): viewer -> app_user';        END CATCH;
    BEGIN TRY INSERT INTO wsb.vehicle (vehicle_type) VALUES ('Car'); PRINT 'FAIL: viewer inserted';     END TRY BEGIN CATCH PRINT 'OK (denied): viewer INSERT vehicle';      END CATCH;
    BEGIN TRY EXEC wsb.add_fuel 'DEMO-C01','2026-11-02',5,20;  PRINT 'FAIL: viewer ran add_fuel';       END TRY BEGIN CATCH PRINT 'OK (denied): viewer EXEC add_fuel';       END CATCH;
REVERT;
GO

-- ===== STAFF =====
EXECUTE AS USER = 'test_staff';
    SELECT 'staff: documents visible (EXPECT General + Staff: 14 with demo data)' AS test, COUNT(*) AS n FROM wsb.vehicle_document;
    SELECT 'staff: license table readable' AS test, COUNT(*) AS n FROM wsb.driver_license;
    BEGIN TRY DELETE FROM wsb.fuel_record WHERE 1 = 0;        PRINT 'FAIL: staff DELETE allowed';       END TRY BEGIN CATCH PRINT 'OK (denied): staff DELETE fuel_record';   END CATCH;
    BEGIN TRY SELECT * FROM wsb.audit_log;                    PRINT 'FAIL: staff read audit_log';       END TRY BEGIN CATCH PRINT 'OK (denied): staff -> audit_log';        END CATCH;
    BEGIN TRY SELECT * FROM wsb.app_user;                     PRINT 'FAIL: staff read app_user';        END TRY BEGIN CATCH PRINT 'OK (denied): staff -> app_user';         END CATCH;
    BEGIN TRY INSERT INTO wsb.vehicle_document (vehicle_id, document_type, file_location, access_level)
              SELECT TOP 1 vehicle_id, 'Title', '/secure/docs/test.pdf', 'Admin' FROM wsb.vehicle;
              PRINT 'FAIL: staff created an Admin-level document'; END TRY BEGIN CATCH PRINT 'OK (denied): staff INSERT Admin-level document'; END CATCH;
    EXEC wsb.add_fuel @asset_number = 'DEMO-C01', @fuel_date = '2026-11-02', @gallons = 5, @total_cost = 20, @vendor = 'TEST';  -- allowed
REVERT;
GO

-- ===== ADMIN =====
EXECUTE AS USER = 'test_admin';
    SELECT 'admin: documents visible (EXPECT all 16 with demo data)' AS test, COUNT(*) AS n FROM wsb.vehicle_document;
    SELECT 'admin: audit log readable' AS test, COUNT(*) AS n FROM wsb.audit_log;
    DELETE FROM wsb.fuel_record WHERE vendor = 'TEST';       -- allowed: removes the staff test row
    BEGIN TRY DELETE FROM wsb.audit_log WHERE 1 = 0;          PRINT 'FAIL: admin could delete audit rows'; END TRY BEGIN CATCH PRINT 'OK (denied): admin DELETE audit_log (append-only)'; END CATCH;
REVERT;
GO

-- Clean up ----------------------------------------------------------------
ALTER ROLE wsb_admin    DROP MEMBER test_admin;
ALTER ROLE wsb_staff    DROP MEMBER test_staff;
ALTER ROLE wsb_readonly DROP MEMBER test_viewer;
DROP USER test_admin;
DROP USER test_staff;
DROP USER test_viewer;
GO
