-- =====================================================================
-- File 02: Security  (roles, permissions, data access)
-- SQL Server version
-- Run AFTER 01_schema.sql, as a database administrator.
-- =====================================================================

SET NOCOUNT ON;
GO

-- 1) Database roles -------------------------------------------------------
IF DATABASE_PRINCIPAL_ID('wsb_admin') IS NULL
    CREATE ROLE [wsb_admin];
GO

IF DATABASE_PRINCIPAL_ID('wsb_staff') IS NULL
    CREATE ROLE [wsb_staff];
GO

IF DATABASE_PRINCIPAL_ID('wsb_readonly') IS NULL
    CREATE ROLE [wsb_readonly];
GO

-- 2) Start from zero: nobody gets anything by default ---------------------
REVOKE ALL ON SCHEMA::wsb FROM public;
GO

-- 3) ADMIN: everything, including deletes and user management -------------
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.driver TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.driver_license TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.driver_qualification TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.vehicle TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.vehicle_document TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.maintenance_rule TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.invoice TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.invoice_line TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.wex_code TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.trip TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.fuel_record TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.maintenance_record TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.app_role TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.app_user TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.audit_log TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.v_vehicle_summary TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.v_cost_by_vehicle_fy TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.v_invoice_reconciliation TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.v_fuel_efficiency TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.v_maintenance_due TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.v_driver_directory TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.v_state_audit_vehicle_log TO [wsb_admin];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::wsb.v_expiring_items TO [wsb_admin];
GO

-- 4) STAFF: view everything operational, add/edit, NO delete ------------
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.driver TO [wsb_staff];
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.driver_license TO [wsb_staff];
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.driver_qualification TO [wsb_staff];
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.vehicle TO [wsb_staff];
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.vehicle_document TO [wsb_staff];
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.maintenance_rule TO [wsb_staff];
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.invoice TO [wsb_staff];
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.invoice_line TO [wsb_staff];
GRANT SELECT ON OBJECT::wsb.wex_code TO [wsb_staff];
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.trip TO [wsb_staff];
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.fuel_record TO [wsb_staff];
GRANT SELECT, INSERT, UPDATE ON OBJECT::wsb.maintenance_record TO [wsb_staff];
GRANT SELECT ON OBJECT::wsb.v_vehicle_summary TO [wsb_staff];
GRANT SELECT ON OBJECT::wsb.v_cost_by_vehicle_fy TO [wsb_staff];
GRANT SELECT ON OBJECT::wsb.v_invoice_reconciliation TO [wsb_staff];
GRANT SELECT ON OBJECT::wsb.v_fuel_efficiency TO [wsb_staff];
GRANT SELECT ON OBJECT::wsb.v_maintenance_due TO [wsb_staff];
GRANT SELECT ON OBJECT::wsb.v_driver_directory TO [wsb_staff];
GRANT SELECT ON OBJECT::wsb.v_state_audit_vehicle_log TO [wsb_staff];
REVOKE ALL ON OBJECT::wsb.app_user FROM [wsb_staff];
REVOKE ALL ON OBJECT::wsb.app_role FROM [wsb_staff];
REVOKE ALL ON OBJECT::wsb.audit_log FROM [wsb_staff];
GO

-- 5) READ-ONLY: reports and non-personal tables only ----------------------
GRANT SELECT ON OBJECT::wsb.vehicle TO [wsb_readonly];
GRANT SELECT ON OBJECT::wsb.trip TO [wsb_readonly];
GRANT SELECT ON OBJECT::wsb.fuel_record TO [wsb_readonly];
GRANT SELECT ON OBJECT::wsb.maintenance_record TO [wsb_readonly];
GRANT SELECT ON OBJECT::wsb.maintenance_rule TO [wsb_readonly];
GRANT SELECT ON OBJECT::wsb.invoice TO [wsb_readonly];
GRANT SELECT ON OBJECT::wsb.invoice_line TO [wsb_readonly];
GRANT SELECT ON OBJECT::wsb.vehicle_document TO [wsb_readonly];
GRANT SELECT ON OBJECT::wsb.wex_code TO [wsb_readonly];
GRANT SELECT ON OBJECT::wsb.v_vehicle_summary TO [wsb_readonly];
GRANT SELECT ON OBJECT::wsb.v_cost_by_vehicle_fy TO [wsb_readonly];
GRANT SELECT ON OBJECT::wsb.v_invoice_reconciliation TO [wsb_readonly];
GRANT SELECT ON OBJECT::wsb.v_fuel_efficiency TO [wsb_readonly];
GRANT SELECT ON OBJECT::wsb.v_maintenance_due TO [wsb_readonly];
GRANT SELECT ON OBJECT::wsb.v_driver_directory TO [wsb_readonly];
GRANT SELECT ON OBJECT::wsb.v_state_audit_vehicle_log TO [wsb_readonly];
REVOKE ALL ON OBJECT::wsb.driver FROM [wsb_readonly];
REVOKE ALL ON OBJECT::wsb.driver_license FROM [wsb_readonly];
REVOKE ALL ON OBJECT::wsb.driver_qualification FROM [wsb_readonly];
REVOKE ALL ON OBJECT::wsb.app_user FROM [wsb_readonly];
REVOKE ALL ON OBJECT::wsb.app_role FROM [wsb_readonly];
REVOKE ALL ON OBJECT::wsb.audit_log FROM [wsb_readonly];
REVOKE ALL ON OBJECT::wsb.v_expiring_items FROM [wsb_readonly];
GO

-- 6) Role catalogue rows ---------------------------------------------------
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

-- 7) Helper procedure to create a login, map the login to a DB user, and add
--    the user to the right SQL Server role.
CREATE OR ALTER PROCEDURE wsb.create_wsb_user
    @p_username sysname,
    @p_full_name nvarchar(100),
    @p_email nvarchar(100),
    @p_role varchar(20),
    @p_password nvarchar(128)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @role_id int;
    SELECT @role_id = role_id
    FROM wsb.app_role
    WHERE role_name = @p_role;

    IF @role_id IS NULL
    BEGIN
        RAISERROR('Unknown role %s. Use Admin, Staff or Read-only.', 16, 1, @p_role);
        RETURN;
    END;

    DECLARE @dbRoleName sysname;
    SELECT @dbRoleName = pg_role
    FROM wsb.app_role
    WHERE role_name = @p_role;

    DECLARE @sql nvarchar(max);

    IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = @p_username)
    BEGIN
        SET @sql = N'CREATE LOGIN ' + QUOTENAME(@p_username) + N' WITH PASSWORD = ''' + REPLACE(@p_password, '''', '''''') + N''';';
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
    BEGIN
        INSERT INTO wsb.app_user (username, full_name, email, role_id)
        VALUES (@p_username, @p_full_name, @p_email, @role_id);
    END;
END;
GO

-- Example usage:
-- EXEC wsb.create_wsb_user @p_username = 'jsmith', @p_full_name = 'Jane Smith', @p_email = 'jsmith@fgcu.edu', @p_role = 'Staff', @p_password = 'TempPass#2026';
GO
