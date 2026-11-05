-- =====================================================================
-- File 06: Security test script   PostgreSQL / Supabase
-- PostgreSQL version of ../06_security_tests.sql. Run AFTER 01-05 as the
-- database owner (Supabase SQL Editor is fine).
--
-- It creates a test user for each role, switches to it, and checks what is
-- allowed and what is denied. The result is a table of PASS / FAIL lines:
-- every line should say PASS.
-- Safe on the real database: everything the test does (test users, the test
-- fuel row, audit rows) is undone at the end, so it leaves nothing behind.
-- Expected counts are worked out from whatever data is in the database.
-- =====================================================================

CREATE OR REPLACE FUNCTION pg_temp.wsb_security_tests()
RETURNS TABLE (result TEXT)
LANGUAGE plpgsql
AS $$
DECLARE
    msgs         TEXT := '';
    n            BIGINT;
    exp_vehicles BIGINT;
    exp_general  BIGINT;
    exp_staff    BIGINT;
    exp_all_docs BIGINT;
    test_asset   VARCHAR;
    new_fuel_id  INT;
BEGIN
    BEGIN   -- everything inside this block is rolled back at the end
        -- Expected counts (as the owner, who sees everything)
        SELECT count(*) INTO exp_vehicles FROM wsb.vehicle;
        SELECT count(*) INTO exp_all_docs FROM wsb.vehicle_document;
        SELECT count(*) INTO exp_general  FROM wsb.vehicle_document WHERE access_level = 'General';
        SELECT count(*) INTO exp_staff    FROM wsb.vehicle_document WHERE access_level IN ('General','Staff');
        SELECT asset_number INTO test_asset FROM wsb.vehicle WHERE asset_number IS NOT NULL ORDER BY vehicle_id LIMIT 1;

        -- Test users, one per role
        CREATE ROLE wsb_test_admin  NOLOGIN IN ROLE wsb_admin;
        CREATE ROLE wsb_test_staff  NOLOGIN IN ROLE wsb_staff;
        CREATE ROLE wsb_test_viewer NOLOGIN IN ROLE wsb_readonly;
        GRANT wsb_test_admin, wsb_test_staff, wsb_test_viewer TO CURRENT_USER;   -- lets this script switch to them

        -- ===== READ-ONLY =====
        SET ROLE wsb_test_viewer;
        SELECT count(*) INTO n FROM wsb.vehicle;
        msgs := msgs || E'\n' || format('%s  viewer sees all vehicles (%s of %s)', CASE WHEN n = exp_vehicles THEN 'PASS' ELSE 'FAIL' END, n, exp_vehicles);
        SELECT count(*) INTO n FROM wsb.vehicle_document;
        msgs := msgs || E'\n' || format('%s  viewer sees General documents only (%s, expected %s)', CASE WHEN n = exp_general THEN 'PASS' ELSE 'FAIL' END, n, exp_general);
        BEGIN PERFORM 1 FROM wsb.v_driver_directory; msgs := msgs || E'\n' || 'PASS  viewer can read v_driver_directory';
        EXCEPTION WHEN insufficient_privilege THEN msgs := msgs || E'\n' || 'FAIL  viewer cannot read v_driver_directory'; END;
        BEGIN PERFORM 1 FROM wsb.driver_license; msgs := msgs || E'\n' || 'FAIL  viewer read driver_license';
        EXCEPTION WHEN insufficient_privilege THEN msgs := msgs || E'\n' || 'PASS  viewer denied: driver_license'; END;
        BEGIN PERFORM email FROM wsb.driver; msgs := msgs || E'\n' || 'FAIL  viewer read driver.email';
        EXCEPTION WHEN insufficient_privilege THEN msgs := msgs || E'\n' || 'PASS  viewer denied: driver (emails)'; END;
        BEGIN PERFORM 1 FROM wsb.app_user; msgs := msgs || E'\n' || 'FAIL  viewer read app_user';
        EXCEPTION WHEN insufficient_privilege THEN msgs := msgs || E'\n' || 'PASS  viewer denied: app_user'; END;
        BEGIN PERFORM 1 FROM wsb.v_expiring_items; msgs := msgs || E'\n' || 'FAIL  viewer read v_expiring_items';
        EXCEPTION WHEN insufficient_privilege THEN msgs := msgs || E'\n' || 'PASS  viewer denied: v_expiring_items'; END;
        BEGIN INSERT INTO wsb.vehicle (vehicle_type) VALUES ('Car'); msgs := msgs || E'\n' || 'FAIL  viewer inserted a vehicle';
        EXCEPTION WHEN insufficient_privilege THEN msgs := msgs || E'\n' || 'PASS  viewer denied: INSERT vehicle'; END;
        BEGIN PERFORM wsb.add_fuel(test_asset, DATE '2026-11-02', 5, 20); msgs := msgs || E'\n' || 'FAIL  viewer ran add_fuel';
        EXCEPTION WHEN insufficient_privilege THEN msgs := msgs || E'\n' || 'PASS  viewer denied: add_fuel'; END;
        RESET ROLE;

        -- ===== STAFF =====
        SET ROLE wsb_test_staff;
        SELECT count(*) INTO n FROM wsb.vehicle_document;
        msgs := msgs || E'\n' || format('%s  staff sees General + Staff documents (%s, expected %s)', CASE WHEN n = exp_staff THEN 'PASS' ELSE 'FAIL' END, n, exp_staff);
        BEGIN PERFORM 1 FROM wsb.driver_license; msgs := msgs || E'\n' || 'PASS  staff can read driver_license';
        EXCEPTION WHEN insufficient_privilege THEN msgs := msgs || E'\n' || 'FAIL  staff cannot read driver_license'; END;
        BEGIN DELETE FROM wsb.fuel_record WHERE false; msgs := msgs || E'\n' || 'FAIL  staff DELETE allowed';
        EXCEPTION WHEN insufficient_privilege THEN msgs := msgs || E'\n' || 'PASS  staff denied: DELETE fuel_record'; END;
        BEGIN PERFORM 1 FROM wsb.audit_log; msgs := msgs || E'\n' || 'FAIL  staff read audit_log';
        EXCEPTION WHEN insufficient_privilege THEN msgs := msgs || E'\n' || 'PASS  staff denied: audit_log'; END;
        BEGIN PERFORM 1 FROM wsb.app_user; msgs := msgs || E'\n' || 'FAIL  staff read app_user';
        EXCEPTION WHEN insufficient_privilege THEN msgs := msgs || E'\n' || 'PASS  staff denied: app_user'; END;
        BEGIN
            INSERT INTO wsb.vehicle_document (vehicle_id, document_type, file_location, access_level)
            SELECT vehicle_id, 'Title', '/secure/docs/test.pdf', 'Admin' FROM wsb.vehicle ORDER BY vehicle_id LIMIT 1;
            msgs := msgs || E'\n' || 'FAIL  staff created an Admin-level document';
        EXCEPTION WHEN insufficient_privilege THEN msgs := msgs || E'\n' || 'PASS  staff denied: INSERT Admin-level document'; END;
        IF test_asset IS NULL THEN
            msgs := msgs || E'\n' || 'SKIP  staff add_fuel (no vehicle with an asset number)';
        ELSE
            BEGIN
                new_fuel_id := wsb.add_fuel(p_asset_number => test_asset, p_fuel_date => DATE '2026-11-02',
                                            p_gallons => 5, p_total_cost => 20, p_vendor => 'TEST');
                msgs := msgs || E'\n' || 'PASS  staff can run add_fuel';
            EXCEPTION WHEN others THEN msgs := msgs || E'\n' || ('FAIL  staff add_fuel: ' || SQLERRM); END;
        END IF;
        RESET ROLE;

        -- ===== ADMIN =====
        SET ROLE wsb_test_admin;
        SELECT count(*) INTO n FROM wsb.vehicle_document;
        msgs := msgs || E'\n' || format('%s  admin sees all documents (%s of %s)', CASE WHEN n = exp_all_docs THEN 'PASS' ELSE 'FAIL' END, n, exp_all_docs);
        IF new_fuel_id IS NOT NULL THEN
            SELECT count(*) INTO n FROM wsb.audit_log WHERE table_name = 'fuel_record' AND action = 'INSERT'
                                                       AND (record_data->>'fuel_id')::INT = new_fuel_id;
            msgs := msgs || E'\n' || format('%s  admin reads audit_log; staff fuel entry was audited', CASE WHEN n = 1 THEN 'PASS' ELSE 'FAIL' END);
            BEGIN DELETE FROM wsb.fuel_record WHERE fuel_id = new_fuel_id; msgs := msgs || E'\n' || 'PASS  admin can DELETE';
            EXCEPTION WHEN others THEN msgs := msgs || E'\n' || ('FAIL  admin DELETE: ' || SQLERRM); END;
        END IF;
        BEGIN DELETE FROM wsb.audit_log WHERE false; msgs := msgs || E'\n' || 'FAIL  admin could delete audit rows';
        EXCEPTION WHEN insufficient_privilege THEN msgs := msgs || E'\n' || 'PASS  admin denied: DELETE audit_log (append-only)'; END;
        BEGIN UPDATE wsb.audit_log SET action = action WHERE false; msgs := msgs || E'\n' || 'FAIL  admin could edit audit rows';
        EXCEPTION WHEN insufficient_privilege THEN msgs := msgs || E'\n' || 'PASS  admin denied: UPDATE audit_log'; END;
        BEGIN PERFORM wsb.create_wsb_user('x', 'x', NULL, 'Staff', 'x'); msgs := msgs || E'\n' || 'FAIL  admin ran create_wsb_user';
        EXCEPTION WHEN insufficient_privilege THEN msgs := msgs || E'\n' || 'PASS  admin denied: create_wsb_user'; END;
        RESET ROLE;

        -- ===== SUPABASE PUBLIC API (anon / authenticated) =====
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            SELECT count(*) INTO n FROM information_schema.role_table_grants
            WHERE table_schema = 'wsb' AND grantee IN ('anon','authenticated');
            msgs := msgs || E'\n' || format('%s  public API has no access to wsb (%s table grants, schema usage: %s)',
                CASE WHEN n = 0 AND NOT has_schema_privilege('anon', 'wsb', 'USAGE')
                               AND NOT has_schema_privilege('authenticated', 'wsb', 'USAGE') THEN 'PASS' ELSE 'FAIL' END,
                n, has_schema_privilege('anon', 'wsb', 'USAGE') OR has_schema_privilege('authenticated', 'wsb', 'USAGE'));
        END IF;
        SELECT count(*) INTO n FROM pg_tables WHERE schemaname = 'wsb' AND NOT rowsecurity;
        msgs := msgs || E'\n' || format('%s  row-level security on for every wsb table (%s without)', CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END, n);

        RAISE EXCEPTION USING ERRCODE = 'WSB99', MESSAGE = 'undo test changes';
    EXCEPTION
        WHEN SQLSTATE 'WSB99' THEN NULL;                                   -- normal end: changes undone
        WHEN others THEN msgs := msgs || E'\n' || ('ERROR  test stopped early: ' || SQLERRM);
    END;

    RETURN QUERY SELECT u FROM unnest(string_to_array(ltrim(msgs, E'\n'), E'\n')) AS u;
END;
$$;

SELECT * FROM pg_temp.wsb_security_tests();
