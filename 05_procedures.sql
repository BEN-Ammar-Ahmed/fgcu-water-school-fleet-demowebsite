-- =====================================================================
-- File 05: Data-entry stored procedures   SQL Server
-- Run AFTER 01-03. These are the "forms" for adding data: one call per task,
-- with validation and plain-English error messages, so people do not have to
-- write raw INSERT statements. Staff and Admin can run them; Read-only cannot.
-- =====================================================================
SET NOCOUNT ON;
GO

-- ---------------------------------------------------------------------
-- Add a trip.  Look up IDs with:  SELECT vehicle_id, asset_number FROM wsb.vehicle;
--                                 SELECT driver_id, first_name, last_name FROM wsb.driver;
-- Leave @end_datetime / @ending_mileage NULL for a trip still in progress.
-- ---------------------------------------------------------------------
CREATE OR ALTER PROCEDURE wsb.add_trip
    @asset_number     VARCHAR(20),
    @driver_email     VARCHAR(100),
    @start_datetime   DATETIME2,
    @end_datetime     DATETIME2 = NULL,
    @starting_mileage INT = NULL,
    @ending_mileage   INT = NULL,
    @destination      VARCHAR(100) = NULL,
    @purpose          VARCHAR(100) = NULL,
    @project_program  VARCHAR(100) = NULL,
    @notes            NVARCHAR(MAX) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @vehicle_id INT, @driver_id INT, @approved BIT, @active BIT;

    SELECT @vehicle_id = vehicle_id FROM wsb.vehicle WHERE asset_number = @asset_number;
    IF @vehicle_id IS NULL THROW 50001, 'Unknown asset number. Check wsb.vehicle.', 1;

    SELECT @driver_id = driver_id, @approved = approved, @active = active FROM wsb.driver WHERE email = @driver_email;
    IF @driver_id IS NULL THROW 50002, 'Unknown driver email. Add the driver first.', 1;
    IF @approved = 0 OR @active = 0 THROW 50003, 'This driver is not approved or is inactive.', 1;

    INSERT INTO wsb.trip (vehicle_id, driver_id, start_datetime, end_datetime, starting_mileage, ending_mileage,
                          destination, purpose, project_program, notes)
    VALUES (@vehicle_id, @driver_id, @start_datetime, @end_datetime, @starting_mileage, @ending_mileage,
            @destination, @purpose, @project_program, @notes);

    SELECT SCOPE_IDENTITY() AS new_trip_id;
END;
GO

-- ---------------------------------------------------------------------
-- Add a fuel purchase (manual entry, e.g. from the paper log).
-- ---------------------------------------------------------------------
CREATE OR ALTER PROCEDURE wsb.add_fuel
    @asset_number VARCHAR(20),
    @fuel_date    DATE,
    @gallons      DECIMAL(8,3),
    @total_cost   DECIMAL(8,2),
    @mileage      INT = NULL,
    @vendor       VARCHAR(50) = NULL,
    @trip_id      INT = NULL
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @vehicle_id INT = (SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = @asset_number);
    IF @vehicle_id IS NULL THROW 50001, 'Unknown asset number. Check wsb.vehicle.', 1;

    INSERT INTO wsb.fuel_record (vehicle_id, trip_id, fuel_date, mileage, gallons, total_cost, vendor, source)
    VALUES (@vehicle_id, @trip_id, @fuel_date, @mileage, @gallons, @total_cost, @vendor, 'Manual');

    SELECT SCOPE_IDENTITY() AS new_fuel_id;
END;
GO

-- ---------------------------------------------------------------------
-- Add an invoice with ONE line for ONE vehicle (the most common case: a shop
-- invoice or P-Card purchase). For statements covering many vehicles, call
-- wsb.add_invoice once, then wsb.add_invoice_line once per charge.
-- ---------------------------------------------------------------------
CREATE OR ALTER PROCEDURE wsb.add_invoice
    @invoice_number   VARCHAR(40),
    @invoice_type     VARCHAR(20),     -- WEX Statement | Maintenance | Parts | Registration/Insurance | Other
    @vendor           VARCHAR(80),
    @invoice_date     DATE,
    @total_amount     DECIMAL(10,2),
    @funding_source   VARCHAR(80) = NULL,
    @pcard_workday_no VARCHAR(40) = NULL,
    @purchaser        VARCHAR(80) = NULL,
    @invoice_file     VARCHAR(255) = NULL,
    @payment_due_date DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (SELECT 1 FROM wsb.invoice WHERE vendor = @vendor AND invoice_number = @invoice_number)
        THROW 50010, 'That vendor + invoice number is already in the database.', 1;

    INSERT INTO wsb.invoice (invoice_number, invoice_type, vendor, invoice_date, payment_due_date, total_amount,
                             funding_source, pcard_workday_no, purchaser, invoice_file)
    VALUES (@invoice_number, @invoice_type, @vendor, @invoice_date, @payment_due_date, @total_amount,
            @funding_source, @pcard_workday_no, @purchaser, @invoice_file);

    SELECT SCOPE_IDENTITY() AS new_invoice_id;
END;
GO

CREATE OR ALTER PROCEDURE wsb.add_invoice_line
    @vendor         VARCHAR(80),
    @invoice_number VARCHAR(40),
    @asset_number   VARCHAR(20) = NULL,   -- NULL for charges that belong to no vehicle (account fees)
    @category       VARCHAR(20),          -- Fuel | Repair | Parts | Service | Fee | Registration | Insurance | Credit/Adjustment | Other
    @amount         DECIMAL(10,2),
    @description    NVARCHAR(MAX) = NULL,
    @line_date      DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @invoice_id INT = (SELECT invoice_id FROM wsb.invoice WHERE vendor = @vendor AND invoice_number = @invoice_number);
    IF @invoice_id IS NULL THROW 50011, 'Invoice not found. Add it first with wsb.add_invoice.', 1;

    DECLARE @vehicle_id INT = NULL;
    IF @asset_number IS NOT NULL
    BEGIN
        SELECT @vehicle_id = vehicle_id FROM wsb.vehicle WHERE asset_number = @asset_number;
        IF @vehicle_id IS NULL THROW 50001, 'Unknown asset number. Check wsb.vehicle.', 1;
    END;

    INSERT INTO wsb.invoice_line (invoice_id, vehicle_id, line_date, category, description, amount)
    VALUES (@invoice_id, @vehicle_id, @line_date, @category, @description, @amount);

    -- Show whether the invoice now adds up (unassigned_difference should reach 0.00)
    SELECT invoice_number, total_amount, lines_total, unassigned_difference
    FROM wsb.v_invoice_reconciliation WHERE invoice_id = @invoice_id;
END;
GO

-- ---------------------------------------------------------------------
-- Record completed maintenance and roll the recurring rule forward.
-- ---------------------------------------------------------------------
CREATE OR ALTER PROCEDURE wsb.add_maintenance
    @asset_number         VARCHAR(20),
    @service_date         DATE,
    @service_type         VARCHAR(50),
    @cost                 DECIMAL(8,2) = NULL,
    @vendor               VARCHAR(50) = NULL,
    @mileage_at_service   INT = NULL,
    @description          NVARCHAR(MAX) = NULL,
    @next_service_date    DATE = NULL,
    @next_service_mileage INT = NULL
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @vehicle_id INT = (SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = @asset_number);
    IF @vehicle_id IS NULL THROW 50001, 'Unknown asset number. Check wsb.vehicle.', 1;

    DECLARE @rule_id INT = (SELECT TOP 1 rule_id FROM wsb.maintenance_rule
                            WHERE vehicle_id = @vehicle_id AND maintenance_type = @service_type AND enabled = 1);

    BEGIN TRANSACTION;
        INSERT INTO wsb.maintenance_record (vehicle_id, rule_id, service_date, mileage_at_service, service_type, cost, vendor,
                                            description, next_service_date, next_service_mileage)
        VALUES (@vehicle_id, @rule_id, @service_date, @mileage_at_service, @service_type, @cost, @vendor,
                @description, @next_service_date, @next_service_mileage);

        IF @rule_id IS NOT NULL
            UPDATE wsb.maintenance_rule
            SET last_completed_date = @service_date,
                last_completed_mileage = COALESCE(@mileage_at_service, last_completed_mileage)
            WHERE rule_id = @rule_id;
    COMMIT TRANSACTION;

    SELECT SCOPE_IDENTITY() AS new_maintenance_id;
END;
GO

-- Permissions: Staff and Admin may run the data-entry procedures
GRANT EXECUTE ON OBJECT::wsb.add_trip          TO wsb_staff;
GRANT EXECUTE ON OBJECT::wsb.add_fuel          TO wsb_staff;
GRANT EXECUTE ON OBJECT::wsb.add_invoice       TO wsb_staff;
GRANT EXECUTE ON OBJECT::wsb.add_invoice_line  TO wsb_staff;
GRANT EXECUTE ON OBJECT::wsb.add_maintenance   TO wsb_staff;
GO

-- Examples
-- EXEC wsb.add_trip @asset_number='DEMO-T01', @driver_email='arivera@example.edu',
--      @start_datetime='2026-11-02 08:00', @destination='Matlacha Boat Ramp', @purpose='Field work';
-- EXEC wsb.add_fuel @asset_number='DEMO-C01', @fuel_date='2026-11-02', @gallons=11.2, @total_cost=42.50, @vendor='Sample Gas A';
-- EXEC wsb.add_invoice @invoice_number='DEMO-SHOP-1003', @invoice_type='Maintenance', @vendor='Gulf Coast Auto Care',
--      @invoice_date='2026-11-02', @total_amount=120.00, @purchaser='Alex Rivera';
-- EXEC wsb.add_invoice_line @vendor='Gulf Coast Auto Care', @invoice_number='DEMO-SHOP-1003',
--      @asset_number='DEMO-T02', @category='Service', @amount=120.00, @description='Oil change';
-- EXEC wsb.add_maintenance @asset_number='DEMO-T02', @service_date='2026-11-02', @service_type='Oil Change',
--      @cost=120.00, @vendor='Gulf Coast Auto Care', @mileage_at_service=30500;
GO
