-- =====================================================================
-- File 05: Data-entry functions   PostgreSQL / Supabase
-- PostgreSQL version of ../05_procedures.sql. Run AFTER 01-03.
-- These are the "forms" for adding data: one call per task, with validation and
-- plain-English error messages, so people do not have to write raw INSERTs.
-- Staff and Admin can run them; Read-only cannot. Safe to re-run.
--
-- SQL Server:  EXEC wsb.add_fuel @asset_number = 'X', ...
-- PostgreSQL:  SELECT wsb.add_fuel(p_asset_number => 'X', ...);   (examples at the bottom)
-- Each function returns the new row's id.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Add a trip.  Look up values with:  SELECT asset_number FROM wsb.vehicle;
--                                    SELECT first_name, last_name, email FROM wsb.driver;
-- Leave p_end_datetime / p_ending_mileage out for a trip still in progress.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION wsb.add_trip(
    p_asset_number     VARCHAR,
    p_driver_email     VARCHAR,
    p_start_datetime   TIMESTAMP,
    p_end_datetime     TIMESTAMP DEFAULT NULL,
    p_starting_mileage INT       DEFAULT NULL,
    p_ending_mileage   INT       DEFAULT NULL,
    p_destination      VARCHAR   DEFAULT NULL,
    p_purpose          VARCHAR   DEFAULT NULL,
    p_project_program  VARCHAR   DEFAULT NULL,
    p_notes            TEXT      DEFAULT NULL
)
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE v_vehicle_id INT; v_driver_id INT; v_approved BOOLEAN; v_active BOOLEAN; v_new_id INT;
BEGIN
    SELECT vehicle_id INTO v_vehicle_id FROM wsb.vehicle WHERE asset_number = p_asset_number;
    IF v_vehicle_id IS NULL THEN RAISE EXCEPTION 'Unknown asset number. Check wsb.vehicle.'; END IF;

    SELECT driver_id, approved, active INTO v_driver_id, v_approved, v_active FROM wsb.driver WHERE email = p_driver_email;
    IF v_driver_id IS NULL THEN RAISE EXCEPTION 'Unknown driver email. Add the driver first.'; END IF;
    IF NOT v_approved OR NOT v_active THEN RAISE EXCEPTION 'This driver is not approved or is inactive.'; END IF;

    INSERT INTO wsb.trip (vehicle_id, driver_id, start_datetime, end_datetime, starting_mileage, ending_mileage,
                          destination, purpose, project_program, notes)
    VALUES (v_vehicle_id, v_driver_id, p_start_datetime, p_end_datetime, p_starting_mileage, p_ending_mileage,
            p_destination, p_purpose, p_project_program, p_notes)
    RETURNING trip_id INTO v_new_id;

    RETURN v_new_id;
END;
$$;

-- ---------------------------------------------------------------------
-- Add a fuel purchase (manual entry, e.g. from the paper log).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION wsb.add_fuel(
    p_asset_number VARCHAR,
    p_fuel_date    DATE,
    p_gallons      NUMERIC(8,3),
    p_total_cost   NUMERIC(8,2),
    p_mileage      INT     DEFAULT NULL,
    p_vendor       VARCHAR DEFAULT NULL,
    p_trip_id      INT     DEFAULT NULL
)
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE v_vehicle_id INT; v_new_id INT;
BEGIN
    SELECT vehicle_id INTO v_vehicle_id FROM wsb.vehicle WHERE asset_number = p_asset_number;
    IF v_vehicle_id IS NULL THEN RAISE EXCEPTION 'Unknown asset number. Check wsb.vehicle.'; END IF;

    INSERT INTO wsb.fuel_record (vehicle_id, trip_id, fuel_date, mileage, gallons, total_cost, vendor, source)
    VALUES (v_vehicle_id, p_trip_id, p_fuel_date, p_mileage, p_gallons, p_total_cost, p_vendor, 'Manual')
    RETURNING fuel_id INTO v_new_id;

    RETURN v_new_id;
END;
$$;

-- ---------------------------------------------------------------------
-- Add an invoice. For one charge on one vehicle (a shop invoice or P-Card
-- purchase) follow it with one wsb.add_invoice_line call; for statements
-- covering many vehicles, call wsb.add_invoice_line once per charge.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION wsb.add_invoice(
    p_invoice_number   VARCHAR,
    p_invoice_type     VARCHAR,        -- WEX Statement | Maintenance | Parts | Registration/Insurance | Other
    p_vendor           VARCHAR,
    p_invoice_date     DATE,
    p_total_amount     NUMERIC(10,2),
    p_funding_source   VARCHAR DEFAULT NULL,
    p_pcard_workday_no VARCHAR DEFAULT NULL,
    p_purchaser        VARCHAR DEFAULT NULL,
    p_invoice_file     VARCHAR DEFAULT NULL,
    p_payment_due_date DATE    DEFAULT NULL
)
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE v_new_id INT;
BEGIN
    IF EXISTS (SELECT 1 FROM wsb.invoice WHERE vendor = p_vendor AND invoice_number = p_invoice_number) THEN
        RAISE EXCEPTION 'That vendor + invoice number is already in the database.';
    END IF;

    INSERT INTO wsb.invoice (invoice_number, invoice_type, vendor, invoice_date, payment_due_date, total_amount,
                             funding_source, pcard_workday_no, purchaser, invoice_file)
    VALUES (p_invoice_number, p_invoice_type, p_vendor, p_invoice_date, p_payment_due_date, p_total_amount,
            p_funding_source, p_pcard_workday_no, p_purchaser, p_invoice_file)
    RETURNING invoice_id INTO v_new_id;

    RETURN v_new_id;
END;
$$;

-- Returns whether the invoice now adds up (unassigned_difference should reach 0.00)
CREATE OR REPLACE FUNCTION wsb.add_invoice_line(
    p_vendor         VARCHAR,
    p_invoice_number VARCHAR,
    p_category       VARCHAR,          -- Fuel | Repair | Parts | Service | Fee | Registration | Insurance | Credit/Adjustment | Other
    p_amount         NUMERIC(10,2),
    p_asset_number   VARCHAR DEFAULT NULL,   -- leave out for charges that belong to no vehicle (account fees)
    p_description    TEXT    DEFAULT NULL,
    p_line_date      DATE    DEFAULT NULL
)
RETURNS TABLE (invoice_number VARCHAR, total_amount NUMERIC, lines_total NUMERIC, unassigned_difference NUMERIC)
LANGUAGE plpgsql
AS $$
#variable_conflict use_column
DECLARE v_invoice_id INT; v_vehicle_id INT;
BEGIN
    SELECT i.invoice_id INTO v_invoice_id FROM wsb.invoice AS i
    WHERE i.vendor = p_vendor AND i.invoice_number = p_invoice_number;
    IF v_invoice_id IS NULL THEN RAISE EXCEPTION 'Invoice not found. Add it first with wsb.add_invoice.'; END IF;

    IF p_asset_number IS NOT NULL THEN
        SELECT v.vehicle_id INTO v_vehicle_id FROM wsb.vehicle AS v WHERE v.asset_number = p_asset_number;
        IF v_vehicle_id IS NULL THEN RAISE EXCEPTION 'Unknown asset number. Check wsb.vehicle.'; END IF;
    END IF;

    INSERT INTO wsb.invoice_line (invoice_id, vehicle_id, line_date, category, description, amount)
    VALUES (v_invoice_id, v_vehicle_id, p_line_date, p_category, p_description, p_amount);

    RETURN QUERY
    SELECT r.invoice_number, r.total_amount, r.lines_total, r.unassigned_difference
    FROM wsb.v_invoice_reconciliation AS r WHERE r.invoice_id = v_invoice_id;
END;
$$;

-- ---------------------------------------------------------------------
-- Record completed maintenance and roll the recurring rule forward.
-- (A function runs as one transaction: both changes happen or neither does.)
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION wsb.add_maintenance(
    p_asset_number         VARCHAR,
    p_service_date         DATE,
    p_service_type         VARCHAR,
    p_cost                 NUMERIC(8,2) DEFAULT NULL,
    p_vendor               VARCHAR      DEFAULT NULL,
    p_mileage_at_service   INT          DEFAULT NULL,
    p_description          TEXT         DEFAULT NULL,
    p_next_service_date    DATE         DEFAULT NULL,
    p_next_service_mileage INT          DEFAULT NULL
)
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE v_vehicle_id INT; v_rule_id INT; v_new_id INT;
BEGIN
    SELECT vehicle_id INTO v_vehicle_id FROM wsb.vehicle WHERE asset_number = p_asset_number;
    IF v_vehicle_id IS NULL THEN RAISE EXCEPTION 'Unknown asset number. Check wsb.vehicle.'; END IF;

    SELECT rule_id INTO v_rule_id FROM wsb.maintenance_rule
    WHERE vehicle_id = v_vehicle_id AND maintenance_type = p_service_type AND enabled
    ORDER BY rule_id LIMIT 1;

    INSERT INTO wsb.maintenance_record (vehicle_id, rule_id, service_date, mileage_at_service, service_type, cost, vendor,
                                        description, next_service_date, next_service_mileage)
    VALUES (v_vehicle_id, v_rule_id, p_service_date, p_mileage_at_service, p_service_type, p_cost, p_vendor,
            p_description, p_next_service_date, p_next_service_mileage)
    RETURNING maintenance_id INTO v_new_id;

    IF v_rule_id IS NOT NULL THEN
        UPDATE wsb.maintenance_rule
        SET last_completed_date = p_service_date,
            last_completed_mileage = COALESCE(p_mileage_at_service, last_completed_mileage)
        WHERE rule_id = v_rule_id;
    END IF;

    RETURN v_new_id;
END;
$$;

-- Permissions: Staff and Admin may run the data-entry functions, nobody else
REVOKE ALL ON FUNCTION
    wsb.add_trip(VARCHAR, VARCHAR, TIMESTAMP, TIMESTAMP, INT, INT, VARCHAR, VARCHAR, VARCHAR, TEXT),
    wsb.add_fuel(VARCHAR, DATE, NUMERIC, NUMERIC, INT, VARCHAR, INT),
    wsb.add_invoice(VARCHAR, VARCHAR, VARCHAR, DATE, NUMERIC, VARCHAR, VARCHAR, VARCHAR, VARCHAR, DATE),
    wsb.add_invoice_line(VARCHAR, VARCHAR, VARCHAR, NUMERIC, VARCHAR, TEXT, DATE),
    wsb.add_maintenance(VARCHAR, DATE, VARCHAR, NUMERIC, VARCHAR, INT, TEXT, DATE, INT)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    wsb.add_trip(VARCHAR, VARCHAR, TIMESTAMP, TIMESTAMP, INT, INT, VARCHAR, VARCHAR, VARCHAR, TEXT),
    wsb.add_fuel(VARCHAR, DATE, NUMERIC, NUMERIC, INT, VARCHAR, INT),
    wsb.add_invoice(VARCHAR, VARCHAR, VARCHAR, DATE, NUMERIC, VARCHAR, VARCHAR, VARCHAR, VARCHAR, DATE),
    wsb.add_invoice_line(VARCHAR, VARCHAR, VARCHAR, NUMERIC, VARCHAR, TEXT, DATE),
    wsb.add_maintenance(VARCHAR, DATE, VARCHAR, NUMERIC, VARCHAR, INT, TEXT, DATE, INT)
    TO wsb_staff, wsb_admin;

SELECT wsb.lock_out_public_api();

-- Examples (the DEMO asset numbers exist only with test_data/03b_demo_data.sql)
-- SELECT wsb.add_trip(p_asset_number => 'DEMO-T01', p_driver_email => 'arivera@example.edu',
--        p_start_datetime => '2026-11-02 08:00', p_destination => 'Matlacha Boat Ramp', p_purpose => 'Field work');
-- SELECT wsb.add_fuel(p_asset_number => 'DEMO-C01', p_fuel_date => '2026-11-02', p_gallons => 11.2,
--        p_total_cost => 42.50, p_vendor => 'Sample Gas A');
-- SELECT wsb.add_invoice(p_invoice_number => 'DEMO-SHOP-1003', p_invoice_type => 'Maintenance',
--        p_vendor => 'Gulf Coast Auto Care', p_invoice_date => '2026-11-02', p_total_amount => 120.00,
--        p_purchaser => 'Alex Rivera');
-- SELECT * FROM wsb.add_invoice_line(p_vendor => 'Gulf Coast Auto Care', p_invoice_number => 'DEMO-SHOP-1003',
--        p_asset_number => 'DEMO-T02', p_category => 'Service', p_amount => 120.00, p_description => 'Oil change');
-- SELECT wsb.add_maintenance(p_asset_number => 'DEMO-T02', p_service_date => '2026-11-02',
--        p_service_type => 'Oil Change', p_cost => 120.00, p_vendor => 'Gulf Coast Auto Care',
--        p_mileage_at_service => 30500);
