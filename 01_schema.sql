-- =====================================================================
-- Water School Vehicle Management Database  (SQL Server / T-SQL)
-- File 01: Schema (tables, constraints, indexes, helper functions, triggers)
-- Run order: 01_schema.sql -> 02_security.sql -> 03_sample_data.sql
-- Safe to re-run on an EMPTY database. It will not drop existing data.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Helper: Florida state fiscal year (July 1 - June 30), e.g. 'FY25-26'
-- Your maintenance spreadsheets are organised by fiscal year.
-- ---------------------------------------------------------------------
CREATE OR ALTER FUNCTION wsb.fiscal_year
(
    @d DATE
)
RETURNS VARCHAR(8)
AS
BEGIN
    DECLARE @result VARCHAR(8);

    IF @d IS NULL
        SET @result = NULL;
    ELSE IF MONTH(@d) >= 7
        SET @result = 'FY' + RIGHT(CONVERT(VARCHAR(4), YEAR(@d)), 2) + '-' + RIGHT(CONVERT(VARCHAR(4), YEAR(DATEADD(YEAR, 1, @d))), 2);
    ELSE
        SET @result = 'FY' + RIGHT(CONVERT(VARCHAR(4), YEAR(DATEADD(YEAR, -1, @d))), 2) + '-' + RIGHT(CONVERT(VARCHAR(4), YEAR(@d)), 2);

    RETURN @result;
END;
GO

-- =====================================================================
-- SECTION 1: PEOPLE
-- =====================================================================

CREATE TABLE wsb.driver (
    driver_id    INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    first_name   VARCHAR(50) NOT NULL,
    last_name    VARCHAR(50) NOT NULL,
    email        VARCHAR(100) NULL UNIQUE,
    department   VARCHAR(50) NULL,
    driver_type  VARCHAR(30) NULL CHECK (driver_type IN ('Faculty','Staff','OPS','Other')),
    approved     BIT NOT NULL CONSTRAINT DF_driver_approved DEFAULT 0,
    active       BIT NOT NULL CONSTRAINT DF_driver_active DEFAULT 1
);
GO

CREATE TABLE wsb.driver_license (
    license_id      INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    driver_id       INT NOT NULL CONSTRAINT FK_driver_license_driver FOREIGN KEY REFERENCES wsb.driver(driver_id) ON DELETE CASCADE,
    license_number  VARCHAR(20) NULL,
    state           VARCHAR(20) NULL,
    expiration_date DATE NULL,
    license_file    VARCHAR(255) NULL,
    verified_date   DATE NULL,
    verified_by     VARCHAR(50) NULL
);
GO

-- Training / authorisation items from "FGCU_TWS_Driver_Requirements":
-- defensive driving, fleet orientation, boater safety, trailer training,
-- golf cart training, captaining agreement, vessel practical test, etc.
CREATE TABLE wsb.driver_qualification (
    qualification_id   INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    driver_id          INT NOT NULL CONSTRAINT FK_driver_qualification_driver FOREIGN KEY REFERENCES wsb.driver(driver_id) ON DELETE CASCADE,
    qualification_type VARCHAR(40) NOT NULL CHECK (qualification_type IN (
        'Vehicle Use Acknowledgement','FL License Check','Defensive Driving',
        'Fleet Orientation','Boater Safety Course','Vessel Practical Test',
        'Captaining Agreement','Trailer Training','Golf Cart Training','Other')),
    completed_date     DATE NULL,
    expiration_date    DATE NULL,
    document_location  VARCHAR(255) NULL,
    verified_by        VARCHAR(50) NULL,
    notes              NVARCHAR(MAX) NULL
);
GO

-- =====================================================================
-- SECTION 2: VEHICLES (boats, cars, trucks, trailers, golf carts, ATVs)
-- =====================================================================

CREATE TABLE wsb.vehicle (
    vehicle_id      INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    asset_number    VARCHAR(20) NULL UNIQUE,
    vehicle_type    VARCHAR(30) NOT NULL CHECK (vehicle_type IN ('Boat','Car','Truck','Trailer','Golf Cart','ATV','Other')),
    make            VARCHAR(30) NULL,
    model           VARCHAR(30) NULL,
    year            INT NULL CHECK (year BETWEEN 1950 AND 2100),
    vin             VARCHAR(30) NULL UNIQUE,
    license_plate   VARCHAR(20) NULL,
    department      VARCHAR(50) NULL,
    wex_card_last4  CHAR(4) NULL,
    current_mileage INT NULL CHECK (current_mileage >= 0),
    current_hours   DECIMAL(8,1) NULL CHECK (current_hours >= 0),
    location        VARCHAR(50) NULL,
    status          VARCHAR(20) NOT NULL CONSTRAINT DF_vehicle_status DEFAULT 'Available' CHECK (status IN ('Available','In Use','In Maintenance','Out of Service','Retired')),
    active          BIT NOT NULL CONSTRAINT DF_vehicle_active DEFAULT 1,
    notes           NVARCHAR(MAX) NULL
);
GO

CREATE TABLE wsb.vehicle_document (
    document_id      INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    vehicle_id       INT NOT NULL CONSTRAINT FK_vehicle_document_vehicle FOREIGN KEY REFERENCES wsb.vehicle(vehicle_id) ON DELETE CASCADE,
    document_type    VARCHAR(40) NOT NULL CHECK (document_type IN ('Registration','Insurance - Auto Liability',
        'Insurance - General Liability','Insurance - Workers Comp','Title','Inspection','Manual','Other')),
    file_location    VARCHAR(255) NOT NULL,
    issue_date       DATE NULL,
    expiration_date  DATE NULL,
    access_level     VARCHAR(10) NOT NULL CONSTRAINT DF_vehicle_document_access DEFAULT 'General' CHECK (access_level IN ('General','Staff','Admin')),
    notes            NVARCHAR(MAX) NULL
);
GO

CREATE TABLE wsb.maintenance_rule (
    rule_id                INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    vehicle_id             INT NOT NULL CONSTRAINT FK_maintenance_rule_vehicle FOREIGN KEY REFERENCES wsb.vehicle(vehicle_id) ON DELETE CASCADE,
    maintenance_type       VARCHAR(50) NOT NULL,
    mileage_interval       INT NULL CHECK (mileage_interval > 0),
    time_interval_months   INT NULL CHECK (time_interval_months > 0),
    last_completed_mileage INT NULL,
    last_completed_date    DATE NULL,
    enabled                BIT NOT NULL CONSTRAINT DF_maintenance_rule_enabled DEFAULT 1,
    CHECK (mileage_interval IS NOT NULL OR time_interval_months IS NOT NULL)
);
GO

-- =====================================================================
-- SECTION 3: INVOICES  (new - designed from WEX statements + maintenance sheets)
-- =====================================================================
-- One INVOICE = one bill/statement (a WEX monthly statement, a shop invoice,
-- a P-Card purchase). It has many INVOICE_LINEs, and each line can be tied to
-- ONE vehicle. That is how a single WEX statement covering 10 vehicles still
-- links every dollar to the right vehicle.

CREATE TABLE wsb.invoice (
    invoice_id          INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    invoice_number      VARCHAR(40) NULL,
    invoice_type        VARCHAR(20) NOT NULL CHECK (invoice_type IN ('WEX Statement','Maintenance','Parts','Registration/Insurance','Other')),
    vendor              VARCHAR(80) NOT NULL,
    invoice_date        DATE NOT NULL,
    payment_due_date    DATE NULL,
    total_amount        DECIMAL(10,2) NOT NULL,
    funding_source      VARCHAR(80) NULL,
    pcard_workday_no    VARCHAR(40) NULL,
    purchaser           VARCHAR(80) NULL,
    account_number_last4 CHAR(4) NULL,
    invoice_file        VARCHAR(255) NULL,
    fiscal_year         AS (wsb.fiscal_year(invoice_date)) PERSISTED,
    notes               NVARCHAR(MAX) NULL,
    created_by          VARCHAR(50) CONSTRAINT DF_invoice_created_by DEFAULT SUSER_SNAME(),
    created_at          DATETIME2 NOT NULL CONSTRAINT DF_invoice_created_at DEFAULT SYSUTCDATETIME(),
    UNIQUE (vendor, invoice_number)
);
GO

CREATE TABLE wsb.invoice_line (
    line_id       INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    invoice_id    INT NOT NULL CONSTRAINT FK_invoice_line_invoice FOREIGN KEY REFERENCES wsb.invoice(invoice_id) ON DELETE CASCADE,
    vehicle_id    INT NULL CONSTRAINT FK_invoice_line_vehicle FOREIGN KEY REFERENCES wsb.vehicle(vehicle_id),
    line_date     DATE NULL,
    category      VARCHAR(20) NOT NULL CHECK (category IN ('Fuel','Repair','Parts','Service','Fee','Registration','Insurance','Credit/Adjustment','Other')),
    description   NVARCHAR(MAX) NULL,
    amount        DECIMAL(10,2) NOT NULL
);
GO

-- WEX Purchase Activity Report code legend (AD, CL, CP ... and fee codes)
CREATE TABLE wsb.wex_code (
    code        VARCHAR(5) NOT NULL PRIMARY KEY,
    code_type   VARCHAR(12) NOT NULL CHECK (code_type IN ('Transaction','Fee')),
    meaning     VARCHAR(60) NOT NULL
);
GO

-- =====================================================================
-- SECTION 4: ACTIVITY  (trips, fuel, maintenance)
-- =====================================================================

CREATE TABLE wsb.trip (
    trip_id           INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    vehicle_id        INT NOT NULL CONSTRAINT FK_trip_vehicle FOREIGN KEY REFERENCES wsb.vehicle(vehicle_id),
    driver_id         INT NOT NULL CONSTRAINT FK_trip_driver FOREIGN KEY REFERENCES wsb.driver(driver_id),
    start_datetime    DATETIME2 NOT NULL,
    end_datetime      DATETIME2 NULL,
    starting_mileage  INT NULL,
    ending_mileage    INT NULL,
    destination       VARCHAR(100) NULL,
    purpose           VARCHAR(100) NULL,
    project_program   VARCHAR(100) NULL,
    notes             NVARCHAR(MAX) NULL,
    CHECK (end_datetime IS NULL OR end_datetime >= start_datetime),
    CHECK (ending_mileage IS NULL OR starting_mileage IS NULL OR ending_mileage >= starting_mileage)
);
GO

CREATE TABLE wsb.fuel_record (
    fuel_id          INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    vehicle_id       INT NOT NULL CONSTRAINT FK_fuel_record_vehicle FOREIGN KEY REFERENCES wsb.vehicle(vehicle_id),
    trip_id          INT NULL CONSTRAINT FK_fuel_record_trip FOREIGN KEY REFERENCES wsb.trip(trip_id),
    invoice_line_id  INT NULL CONSTRAINT FK_fuel_record_invoice_line FOREIGN KEY REFERENCES wsb.invoice_line(line_id),
    fuel_date        DATE NOT NULL,
    fuel_time        TIME NULL,
    mileage          INT NULL,
    gallons          DECIMAL(8,3) NULL CHECK (gallons >= 0),
    cost_per_unit    DECIMAL(7,3) NULL,
    total_cost       DECIMAL(8,2) NULL,
    other_cost       DECIMAL(8,2) CONSTRAINT DF_fuel_record_other_cost DEFAULT 0,
    product          VARCHAR(20) NULL,
    vendor           VARCHAR(50) NULL,
    site_address     VARCHAR(150) NULL,
    ticket_number    VARCHAR(30) NULL,
    wex_tran_code    VARCHAR(5) NULL CONSTRAINT FK_fuel_record_wex_code FOREIGN KEY REFERENCES wsb.wex_code(code),
    source           VARCHAR(20) NOT NULL CONSTRAINT DF_fuel_record_source DEFAULT 'Manual' CHECK (source IN ('Manual','WEX Import','Mileage Log'))
);
GO

CREATE TABLE wsb.maintenance_record (
    maintenance_id        INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    vehicle_id            INT NOT NULL CONSTRAINT FK_maintenance_record_vehicle FOREIGN KEY REFERENCES wsb.vehicle(vehicle_id),
    rule_id               INT NULL CONSTRAINT FK_maintenance_record_rule FOREIGN KEY REFERENCES wsb.maintenance_rule(rule_id),
    invoice_line_id       INT NULL CONSTRAINT FK_maintenance_record_invoice_line FOREIGN KEY REFERENCES wsb.invoice_line(line_id),
    service_date          DATE NOT NULL,
    mileage_at_service    INT NULL,
    service_type          VARCHAR(50) NULL,
    cost                  DECIMAL(8,2) NULL,
    vendor                VARCHAR(50) NULL,
    description           NVARCHAR(MAX) NULL,
    next_service_date     DATE NULL,
    next_service_mileage  INT NULL
);
GO

-- =====================================================================
-- SECTION 5: SECURITY TABLES + AUDIT
-- =====================================================================

CREATE TABLE wsb.app_role (
    role_id      INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    role_name    VARCHAR(20) NOT NULL UNIQUE CHECK (role_name IN ('Admin','Staff','Read-only')),
    pg_role      VARCHAR(30) NOT NULL UNIQUE,
    description  VARCHAR(200) NULL
);
GO

CREATE TABLE wsb.app_user (
    user_id      INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    username     VARCHAR(50) NOT NULL UNIQUE,
    full_name    VARCHAR(100) NOT NULL,
    email        VARCHAR(100) NULL UNIQUE,
    role_id      INT NOT NULL CONSTRAINT FK_app_user_role FOREIGN KEY REFERENCES wsb.app_role(role_id),
    driver_id    INT NULL CONSTRAINT FK_app_user_driver FOREIGN KEY REFERENCES wsb.driver(driver_id),
    active       BIT NOT NULL CONSTRAINT DF_app_user_active DEFAULT 1,
    created_at   DATETIME2 NOT NULL CONSTRAINT DF_app_user_created_at DEFAULT SYSUTCDATETIME(),
    last_login   DATETIME2 NULL
);
GO

CREATE TABLE wsb.audit_log (
    audit_id     BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    changed_at   DATETIME2 NOT NULL CONSTRAINT DF_audit_log_changed_at DEFAULT SYSUTCDATETIME(),
    changed_by   VARCHAR(50) NOT NULL CONSTRAINT DF_audit_log_changed_by DEFAULT SUSER_SNAME(),
    table_name   VARCHAR(50) NOT NULL,
    action       VARCHAR(10) NOT NULL,
    record_data  NVARCHAR(MAX) NULL
);
GO

CREATE TRIGGER wsb.trg_audit_driver
ON wsb.driver
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO wsb.audit_log (table_name, action, record_data)
    SELECT 'driver',
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN 'UPDATE'
               WHEN EXISTS (SELECT 1 FROM inserted) THEN 'INSERT'
               ELSE 'DELETE'
           END,
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN (SELECT * FROM inserted FOR JSON PATH)
               WHEN EXISTS (SELECT 1 FROM inserted) THEN (SELECT * FROM inserted FOR JSON PATH)
               ELSE (SELECT * FROM deleted FOR JSON PATH)
           END;
END;
GO

CREATE TRIGGER wsb.trg_audit_driver_license
ON wsb.driver_license
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO wsb.audit_log (table_name, action, record_data)
    SELECT 'driver_license',
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN 'UPDATE'
               WHEN EXISTS (SELECT 1 FROM inserted) THEN 'INSERT'
               ELSE 'DELETE'
           END,
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN (SELECT * FROM inserted FOR JSON PATH)
               WHEN EXISTS (SELECT 1 FROM inserted) THEN (SELECT * FROM inserted FOR JSON PATH)
               ELSE (SELECT * FROM deleted FOR JSON PATH)
           END;
END;
GO

CREATE TRIGGER wsb.trg_audit_driver_qualification
ON wsb.driver_qualification
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO wsb.audit_log (table_name, action, record_data)
    SELECT 'driver_qualification',
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN 'UPDATE'
               WHEN EXISTS (SELECT 1 FROM inserted) THEN 'INSERT'
               ELSE 'DELETE'
           END,
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN (SELECT * FROM inserted FOR JSON PATH)
               WHEN EXISTS (SELECT 1 FROM inserted) THEN (SELECT * FROM inserted FOR JSON PATH)
               ELSE (SELECT * FROM deleted FOR JSON PATH)
           END;
END;
GO

CREATE TRIGGER wsb.trg_audit_vehicle
ON wsb.vehicle
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO wsb.audit_log (table_name, action, record_data)
    SELECT 'vehicle',
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN 'UPDATE'
               WHEN EXISTS (SELECT 1 FROM inserted) THEN 'INSERT'
               ELSE 'DELETE'
           END,
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN (SELECT * FROM inserted FOR JSON PATH)
               WHEN EXISTS (SELECT 1 FROM inserted) THEN (SELECT * FROM inserted FOR JSON PATH)
               ELSE (SELECT * FROM deleted FOR JSON PATH)
           END;
END;
GO

CREATE TRIGGER wsb.trg_audit_vehicle_document
ON wsb.vehicle_document
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO wsb.audit_log (table_name, action, record_data)
    SELECT 'vehicle_document',
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN 'UPDATE'
               WHEN EXISTS (SELECT 1 FROM inserted) THEN 'INSERT'
               ELSE 'DELETE'
           END,
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN (SELECT * FROM inserted FOR JSON PATH)
               WHEN EXISTS (SELECT 1 FROM inserted) THEN (SELECT * FROM inserted FOR JSON PATH)
               ELSE (SELECT * FROM deleted FOR JSON PATH)
           END;
END;
GO

CREATE TRIGGER wsb.trg_audit_invoice
ON wsb.invoice
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO wsb.audit_log (table_name, action, record_data)
    SELECT 'invoice',
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN 'UPDATE'
               WHEN EXISTS (SELECT 1 FROM inserted) THEN 'INSERT'
               ELSE 'DELETE'
           END,
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN (SELECT * FROM inserted FOR JSON PATH)
               WHEN EXISTS (SELECT 1 FROM inserted) THEN (SELECT * FROM inserted FOR JSON PATH)
               ELSE (SELECT * FROM deleted FOR JSON PATH)
           END;
END;
GO

CREATE TRIGGER wsb.trg_audit_invoice_line
ON wsb.invoice_line
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO wsb.audit_log (table_name, action, record_data)
    SELECT 'invoice_line',
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN 'UPDATE'
               WHEN EXISTS (SELECT 1 FROM inserted) THEN 'INSERT'
               ELSE 'DELETE'
           END,
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN (SELECT * FROM inserted FOR JSON PATH)
               WHEN EXISTS (SELECT 1 FROM inserted) THEN (SELECT * FROM inserted FOR JSON PATH)
               ELSE (SELECT * FROM deleted FOR JSON PATH)
           END;
END;
GO

CREATE TRIGGER wsb.trg_audit_maintenance_record
ON wsb.maintenance_record
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO wsb.audit_log (table_name, action, record_data)
    SELECT 'maintenance_record',
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN 'UPDATE'
               WHEN EXISTS (SELECT 1 FROM inserted) THEN 'INSERT'
               ELSE 'DELETE'
           END,
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN (SELECT * FROM inserted FOR JSON PATH)
               WHEN EXISTS (SELECT 1 FROM inserted) THEN (SELECT * FROM inserted FOR JSON PATH)
               ELSE (SELECT * FROM deleted FOR JSON PATH)
           END;
END;
GO

CREATE TRIGGER wsb.trg_audit_fuel_record
ON wsb.fuel_record
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO wsb.audit_log (table_name, action, record_data)
    SELECT 'fuel_record',
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN 'UPDATE'
               WHEN EXISTS (SELECT 1 FROM inserted) THEN 'INSERT'
               ELSE 'DELETE'
           END,
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN (SELECT * FROM inserted FOR JSON PATH)
               WHEN EXISTS (SELECT 1 FROM inserted) THEN (SELECT * FROM inserted FOR JSON PATH)
               ELSE (SELECT * FROM deleted FOR JSON PATH)
           END;
END;
GO

CREATE TRIGGER wsb.trg_audit_trip
ON wsb.trip
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO wsb.audit_log (table_name, action, record_data)
    SELECT 'trip',
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN 'UPDATE'
               WHEN EXISTS (SELECT 1 FROM inserted) THEN 'INSERT'
               ELSE 'DELETE'
           END,
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN (SELECT * FROM inserted FOR JSON PATH)
               WHEN EXISTS (SELECT 1 FROM inserted) THEN (SELECT * FROM inserted FOR JSON PATH)
               ELSE (SELECT * FROM deleted FOR JSON PATH)
           END;
END;
GO

CREATE TRIGGER wsb.trg_audit_app_user
ON wsb.app_user
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO wsb.audit_log (table_name, action, record_data)
    SELECT 'app_user',
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN 'UPDATE'
               WHEN EXISTS (SELECT 1 FROM inserted) THEN 'INSERT'
               ELSE 'DELETE'
           END,
           CASE
               WHEN EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted) THEN (SELECT * FROM inserted FOR JSON PATH)
               WHEN EXISTS (SELECT 1 FROM inserted) THEN (SELECT * FROM inserted FOR JSON PATH)
               ELSE (SELECT * FROM deleted FOR JSON PATH)
           END;
END;
GO

-- Keep vehicle.current_mileage up to date when trips/fuel are logged
CREATE TRIGGER wsb.trg_trip_mileage
ON wsb.trip
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    UPDATE v
    SET current_mileage = i.ending_mileage
    FROM wsb.vehicle AS v
    INNER JOIN inserted AS i ON i.vehicle_id = v.vehicle_id
    WHERE i.ending_mileage IS NOT NULL
      AND (v.current_mileage IS NULL OR v.current_mileage < i.ending_mileage);
END;
GO

CREATE TRIGGER wsb.trg_fuel_mileage
ON wsb.fuel_record
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    UPDATE v
    SET current_mileage = i.mileage
    FROM wsb.vehicle AS v
    INNER JOIN inserted AS i ON i.vehicle_id = v.vehicle_id
    WHERE i.mileage IS NOT NULL
      AND (v.current_mileage IS NULL OR v.current_mileage < i.mileage);
END;
GO

-- =====================================================================
-- INDEXES (foreign keys + common filters)
-- =====================================================================
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_trip_vehicle' AND object_id = OBJECT_ID('wsb.trip'))
    CREATE INDEX ix_trip_vehicle ON wsb.trip (vehicle_id, start_datetime);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_trip_driver' AND object_id = OBJECT_ID('wsb.trip'))
    CREATE INDEX ix_trip_driver ON wsb.trip (driver_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_fuel_vehicle' AND object_id = OBJECT_ID('wsb.fuel_record'))
    CREATE INDEX ix_fuel_vehicle ON wsb.fuel_record (vehicle_id, fuel_date);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_fuel_trip' AND object_id = OBJECT_ID('wsb.fuel_record'))
    CREATE INDEX ix_fuel_trip ON wsb.fuel_record (trip_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_fuel_line' AND object_id = OBJECT_ID('wsb.fuel_record'))
    CREATE INDEX ix_fuel_line ON wsb.fuel_record (invoice_line_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_maint_vehicle' AND object_id = OBJECT_ID('wsb.maintenance_record'))
    CREATE INDEX ix_maint_vehicle ON wsb.maintenance_record (vehicle_id, service_date);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_line_invoice' AND object_id = OBJECT_ID('wsb.invoice_line'))
    CREATE INDEX ix_line_invoice ON wsb.invoice_line (invoice_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_line_vehicle' AND object_id = OBJECT_ID('wsb.invoice_line'))
    CREATE INDEX ix_line_vehicle ON wsb.invoice_line (vehicle_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_invoice_fy' AND object_id = OBJECT_ID('wsb.invoice'))
    CREATE INDEX ix_invoice_fy ON wsb.invoice (fiscal_year);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_doc_vehicle' AND object_id = OBJECT_ID('wsb.vehicle_document'))
    CREATE INDEX ix_doc_vehicle ON wsb.vehicle_document (vehicle_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_lic_driver' AND object_id = OBJECT_ID('wsb.driver_license'))
    CREATE INDEX ix_lic_driver ON wsb.driver_license (driver_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_qual_driver' AND object_id = OBJECT_ID('wsb.driver_qualification'))
    CREATE INDEX ix_qual_driver ON wsb.driver_qualification (driver_id);
GO

-- =====================================================================
-- REPORTING VIEWS (budgeting + maintenance reporting from the proposal)
-- =====================================================================

CREATE OR ALTER VIEW wsb.v_vehicle_summary AS
SELECT v.vehicle_id, v.asset_number, v.vehicle_type, v.make, v.model, v.year,
       v.department, v.location, v.status, v.current_mileage, v.current_hours, v.active
FROM wsb.vehicle AS v;
GO

-- Cost per vehicle per fiscal year (replaces "FY22_23_TotalsByVehicleBoat" sheet)
CREATE OR ALTER VIEW wsb.v_cost_by_vehicle_fy AS
SELECT v.vehicle_id, v.asset_number, v.vehicle_type, v.make, v.model,
       i.fiscal_year,
       SUM(CASE WHEN l.category = 'Fuel' THEN l.amount ELSE 0 END) AS fuel_total,
       SUM(CASE WHEN l.category IN ('Repair','Parts','Service') THEN l.amount ELSE 0 END) AS maintenance_total,
       SUM(CASE WHEN l.category NOT IN ('Fuel','Repair','Parts','Service') THEN l.amount ELSE 0 END) AS other_total,
       SUM(l.amount) AS grand_total
FROM wsb.invoice_line AS l
JOIN wsb.invoice AS i ON i.invoice_id = l.invoice_id
JOIN wsb.vehicle AS v ON v.vehicle_id = l.vehicle_id
GROUP BY v.vehicle_id, v.asset_number, v.vehicle_type, v.make, v.model, i.fiscal_year;
GO

-- Invoices with how much of the total is assigned to vehicles (catches unlinked money)
CREATE OR ALTER VIEW wsb.v_invoice_reconciliation AS
SELECT i.invoice_id, i.invoice_number, i.vendor, i.invoice_date, i.fiscal_year, i.total_amount,
       COALESCE(SUM(l.amount),0) AS lines_total,
       i.total_amount - COALESCE(SUM(l.amount),0) AS unassigned_difference
FROM wsb.invoice AS i
LEFT JOIN wsb.invoice_line AS l ON l.invoice_id = i.invoice_id
GROUP BY i.invoice_id, i.invoice_number, i.vendor, i.invoice_date, i.fiscal_year, i.total_amount;
GO

CREATE OR ALTER VIEW wsb.v_fuel_efficiency AS
SELECT f.vehicle_id,
       v.asset_number,
       f.fuel_date,
       f.mileage,
       f.gallons,
       CAST((f.mileage - LAG(f.mileage) OVER (PARTITION BY f.vehicle_id ORDER BY f.fuel_date, f.fuel_id)) AS DECIMAL(10,2)) / NULLIF(f.gallons, 0) AS mpg_since_last_fill
FROM wsb.fuel_record AS f
JOIN wsb.vehicle AS v ON v.vehicle_id = f.vehicle_id
WHERE v.vehicle_type IN ('Car','Truck');
GO

-- Recurring maintenance that is due or overdue
CREATE OR ALTER VIEW wsb.v_maintenance_due AS
SELECT r.rule_id,
       v.vehicle_id,
       v.asset_number,
       v.make,
       v.model,
       r.maintenance_type,
       r.last_completed_date,
       r.last_completed_mileage,
       r.last_completed_mileage + r.mileage_interval AS due_at_mileage,
       CAST(DATEADD(MONTH, r.time_interval_months, r.last_completed_date) AS DATE) AS due_on_date,
       v.current_mileage,
       CASE
           WHEN (v.current_mileage >= r.last_completed_mileage + r.mileage_interval)
             OR (CAST(GETDATE() AS DATE) >= CAST(DATEADD(MONTH, r.time_interval_months, r.last_completed_date) AS DATE))
                THEN 'DUE'
           ELSE 'OK'
       END AS status
FROM wsb.maintenance_rule AS r
JOIN wsb.vehicle AS v ON v.vehicle_id = r.vehicle_id
WHERE r.enabled = 1 AND v.active = 1;
GO

-- Licences / training / documents expiring in the next 60 days
CREATE OR ALTER VIEW wsb.v_expiring_items AS
SELECT 'Driver license' AS item, d.first_name + ' ' + d.last_name AS name, l.expiration_date
FROM wsb.driver_license AS l
JOIN wsb.driver AS d ON d.driver_id = l.driver_id
WHERE l.expiration_date <= DATEADD(DAY, 60, CAST(GETDATE() AS DATE)) AND d.active = 1
UNION ALL
SELECT q.qualification_type, d.first_name + ' ' + d.last_name, q.expiration_date
FROM wsb.driver_qualification AS q
JOIN wsb.driver AS d ON d.driver_id = q.driver_id
WHERE q.expiration_date <= DATEADD(DAY, 60, CAST(GETDATE() AS DATE)) AND d.active = 1
UNION ALL
SELECT vd.document_type, COALESCE(v.asset_number, '?') + ' ' + COALESCE(v.make, ''), vd.expiration_date
FROM wsb.vehicle_document AS vd
JOIN wsb.vehicle AS v ON v.vehicle_id = vd.vehicle_id
WHERE vd.expiration_date <= DATEADD(DAY, 60, CAST(GETDATE() AS DATE)) AND v.active = 1;
GO

-- Driver directory WITHOUT email / license data (safe for Read-only users)
CREATE OR ALTER VIEW wsb.v_driver_directory AS
SELECT driver_id, first_name, last_name, department, driver_type, approved, active
FROM wsb.driver;
GO

-- Mirrors the paper "State Audited Vehicle Log" (FLEET_MILEAGE_LOG)
CREATE OR ALTER VIEW wsb.v_state_audit_vehicle_log AS
SELECT v.asset_number AS vehicle,
       CONVERT(VARCHAR(7), t.start_datetime, 23) AS month,
       CAST(t.start_datetime AS DATE) AS date_out,
       CAST(t.start_datetime AS TIME) AS time_out,
       t.starting_mileage AS mileage_out,
       t.ending_mileage AS mileage_in,
       t.destination,
       d.first_name + ' ' + d.last_name AS full_name,
       t.purpose AS purpose_of_trip,
       CAST(t.end_datetime AS DATE) AS date_return,
       CAST(t.end_datetime AS TIME) AS time_return,
       f.vendor AS gas_station,
       f.total_cost AS amount
FROM wsb.trip AS t
JOIN wsb.vehicle AS v ON v.vehicle_id = t.vehicle_id
JOIN wsb.driver AS d ON d.driver_id = t.driver_id
LEFT JOIN wsb.fuel_record AS f ON f.trip_id = t.trip_id;
GO
