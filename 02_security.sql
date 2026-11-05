-- =====================================================================
-- File 02: Security  (roles, permissions, row-level security)   SQL Server
-- Run AFTER 01_schema.sql, connected as sa / a sysadmin.
--
-- Three tiers (from the project proposal):
--   wsb_admin     Admin      all data, can delete; CANNOT edit or delete the audit log
--   wsb_staff     Staff      view and add/edit operational data; no deletes;
--                            no users/roles/audit; no Admin-level documents
--   wsb_readonly  Read-only  view only; no personal data (no license numbers or
--                            emails); only 'General' documents
-- Real people get their own login, added to ONE of these roles with
-- wsb.create_wsb_user (below).  Nobody is granted anything by default.
-- =====================================================================
SET NOCOUNT ON;
GO

-- 1) Database roles ------------------------------------------------------
IF DATABASE_PRINCIPAL_ID('wsb_admin')    IS NULL CREATE ROLE wsb_admin;
IF DATABASE_PRINCIPAL_ID('wsb_staff')    IS NULL CREATE ROLE wsb_staff;
IF DATABASE_PRINCIPAL_ID('wsb_readonly') IS NULL CREATE ROLE wsb_readonly;
GO

-- 2) ADMIN: everything in the schema, but the audit log is append-only -----
GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON SCHEMA::wsb TO wsb_admin;
DENY  UPDATE, DELETE ON OBJECT::wsb.audit_log TO wsb_admin;
GO

-- 3) STAFF: add and edit operational data, NO delete ---------------------
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.driver               TO wsb_staff;
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.driver_license       TO wsb_staff;
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.driver_qualification TO wsb_staff;
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.vehicle              TO wsb_staff;
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.vehicle_document     TO wsb_staff;
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.maintenance_rule     TO wsb_staff;
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.invoice              TO wsb_staff;
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.invoice_line         TO wsb_staff;
GRANT SELECT                 ON OBJECT::wsb.wex_code             TO wsb_staff;
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.trip                 TO wsb_staff;
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.fuel_record          TO wsb_staff;
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.maintenance_record   TO wsb_staff;
GRANT SELECT ON OBJECT::wsb.v_vehicle_summary          TO wsb_staff;
GRANT SELECT ON OBJECT::wsb.v_cost_by_vehicle_fy       TO wsb_staff;
GRANT SELECT ON OBJECT::wsb.v_invoice_reconciliation   TO wsb_staff;
GRANT SELECT ON OBJECT::wsb.v_fuel_efficiency          TO wsb_staff;
GRANT SELECT ON OBJECT::wsb.v_maintenance_due          TO wsb_staff;
GRANT SELECT ON OBJECT::wsb.v_driver_directory         TO wsb_staff;
GRANT SELECT ON OBJECT::wsb.v_expiring_items           TO wsb_staff;
GRANT SELECT ON OBJECT::wsb.v_state_audit_vehicle_log  TO wsb_staff;
-- Staff get NOTHING on app_user, app_role, audit_log (no grant = no access).
GO

-- 4) READ-ONLY: reports and non-personal tables only -----------------------
GRANT SELECT ON OBJECT::wsb.vehicle                    TO wsb_readonly;
GRANT SELECT ON OBJECT::wsb.trip                       TO wsb_readonly;
GRANT SELECT ON OBJECT::wsb.fuel_record                TO wsb_readonly;
GRANT SELECT ON OBJECT::wsb.maintenance_record         TO wsb_readonly;
GRANT SELECT ON OBJECT::wsb.maintenance_rule           TO wsb_readonly;
GRANT SELECT ON OBJECT::wsb.invoice                    TO wsb_readonly;
GRANT SELECT ON OBJECT::wsb.invoice_line               TO wsb_readonly;
GRANT SELECT ON OBJECT::wsb.vehicle_document           TO wsb_readonly;  -- rows limited by the policy below
GRANT SELECT ON OBJECT::wsb.wex_code                   TO wsb_readonly;
GRANT SELECT ON OBJECT::wsb.v_vehicle_summary          TO wsb_readonly;
GRANT SELECT ON OBJECT::wsb.v_cost_by_vehicle_fy       TO wsb_readonly;
GRANT SELECT ON OBJECT::wsb.v_invoice_reconciliation   TO wsb_readonly;
GRANT SELECT ON OBJECT::wsb.v_fuel_efficiency          TO wsb_readonly;
GRANT SELECT ON OBJECT::wsb.v_maintenance_due          TO wsb_readonly;
GRANT SELECT ON OBJECT::wsb.v_driver_directory         TO wsb_readonly;  -- no email / license data
GRANT SELECT ON OBJECT::wsb.v_state_audit_vehicle_log  TO wsb_readonly;
-- Deliberately NOT granted: driver (email), driver_license, driver_qualification,
-- app_user, app_role, audit_log, v_expiring_items.
GO

-- 5) Row-level security on documents ---------------------------------------
--    vehicle_document.access_level: General < Staff < Admin
--    (sysadmin / db_owner and wsb_admin see everything)
IF EXISTS (SELECT 1 FROM sys.security_policies WHERE name = 'vehicle_document_policy')
    DROP SECURITY POLICY wsb.vehicle_document_policy;
GO

CREATE OR ALTER FUNCTION wsb.fn_document_access (@access_level VARCHAR(10))
RETURNS TABLE
WITH SCHEMABINDING
AS
RETURN
    SELECT 1 AS allowed
    WHERE IS_MEMBER('db_owner') = 1
       OR IS_MEMBER('wsb_admin') = 1
       OR (IS_MEMBER('wsb_staff') = 1    AND @access_level IN ('General','Staff'))
       OR (IS_MEMBER('wsb_readonly') = 1 AND @access_level = 'General');
GO

CREATE SECURITY POLICY wsb.vehicle_document_policy
    ADD FILTER PREDICATE wsb.fn_document_access(access_level) ON wsb.vehicle_document,
    ADD BLOCK  PREDICATE wsb.fn_document_access(access_level) ON wsb.vehicle_document AFTER INSERT,
    ADD BLOCK  PREDICATE wsb.fn_document_access(access_level) ON wsb.vehicle_document AFTER UPDATE
    WITH (STATE = ON);
GO

-- 6) Role catalogue rows (mirrors the database roles above) ----------------
--    NOTE: the column is still called pg_role (left over from the first draft);
--    it simply holds the matching SQL Server role name.
IF NOT EXISTS (SELECT 1 FROM wsb.app_role WHERE role_name = 'Admin')
    INSERT INTO wsb.app_role (role_name, pg_role, description)
    VALUES ('Admin', 'wsb_admin', 'Full access: manage users, delete records, see all documents');
IF NOT EXISTS (SELECT 1 FROM wsb.app_role WHERE role_name = 'Staff')
    INSERT INTO wsb.app_role (role_name, pg_role, description)
    VALUES ('Staff', 'wsb_staff', 'Add and edit operational data; cannot delete or manage users');
IF NOT EXISTS (SELECT 1 FROM wsb.app_role WHERE role_name = 'Read-only')
    INSERT INTO wsb.app_role (role_name, pg_role, description)
    VALUES ('Read-only', 'wsb_readonly', 'View vehicles, trips, fuel, maintenance, invoices and reports only');
GO

-- 7) Helper: create a login + database user + role membership in one call.
--    Run it as sa / a sysadmin (creating logins is a server-level permission,
--    so it is NOT granted to wsb_admin).
CREATE OR ALTER PROCEDURE wsb.create_wsb_user
    @p_username  sysname,
    @p_full_name NVARCHAR(100),
    @p_email     NVARCHAR(100),
    @p_role      VARCHAR(20),
    @p_password  NVARCHAR(128)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @role_id INT, @dbRoleName sysname, @sql NVARCHAR(MAX);

    SELECT @role_id = role_id, @dbRoleName = pg_role
    FROM wsb.app_role WHERE role_name = @p_role;

    IF @role_id IS NULL
    BEGIN
        RAISERROR('Unknown role %s. Use Admin, Staff or Read-only.', 16, 1, @p_role);
        RETURN;
    END;

    IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = @p_username)
    BEGIN
        SET @sql = N'CREATE LOGIN ' + QUOTENAME(@p_username) + N' WITH PASSWORD = N''' + REPLACE(@p_password, '''', '''''') + N''';';
        EXEC sp_executesql @sql;
    END;

    IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = @p_username)
    BEGIN
        SET @sql = N'CREATE USER ' + QUOTENAME(@p_username) + N' FOR LOGIN ' + QUOTENAME(@p_username) + N';';
        EXEC sp_executesql @sql;
    END;

    SET @sql = N'ALTER ROLE ' + QUOTENAME(@dbRoleName) + N' ADD MEMBER ' + QUOTENAME(@p_username) + N';';
    EXEC sp_executesql @sql;

    IF NOT EXISTS (SELECT 1 FROM wsb.app_user WHERE username = @p_username)
        INSERT INTO wsb.app_user (username, full_name, email, role_id)
        VALUES (@p_username, @p_full_name, @p_email, @role_id);
END;
GO

-- Example:
-- EXEC wsb.create_wsb_user @p_username='jsmith', @p_full_name='Jane Smith',
--      @p_email='jsmith@fgcu.edu', @p_role='Staff', @p_password='ChangeMe#2026!';
GO
