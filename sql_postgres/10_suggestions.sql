-- 10_suggestions.sql
-- Typing suggestions and a fuller activity log.
--   * pg_trgm (fuzzy "close match" search), when the server allows it.
--     Without it the site still works: suggestions use plain starts-with / contains matching.
--   * wsb.activity_log.details: what an edit changed, as a JSON list of {field, old, new}.
--   * wsb.activity_log.kind may now be 'sign-out'.
-- Safe to run more than once.

DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
EXCEPTION WHEN insufficient_privilege OR feature_not_supported OR undefined_file THEN
    RAISE NOTICE 'pg_trgm is not available here. Suggestions will skip close matches.';
END;
$$;

ALTER TABLE wsb.activity_log ADD COLUMN IF NOT EXISTS details JSONB;
COMMENT ON COLUMN wsb.activity_log.details IS
    'What an edit changed: [{"field": "Mileage", "old": "41,200", "new": "42,050"}]. Hidden fields have "hidden": true and no values.';

ALTER TABLE wsb.activity_log DROP CONSTRAINT IF EXISTS activity_log_kind_check;
ALTER TABLE wsb.activity_log ADD CONSTRAINT activity_log_kind_check
    CHECK (kind IN ('sign-in', 'sign-out', 'view', 'change', 'download', 'access'));

-- Trigram indexes, only when pg_trgm is installed (in whatever schema it lives, e.g. "extensions" on Supabase).
DO $$
DECLARE
    s TEXT;
    ix RECORD;
BEGIN
    SELECT n.nspname INTO s FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'pg_trgm';
    IF s IS NULL THEN
        RETURN;
    END IF;
    FOR ix IN SELECT * FROM (VALUES
        ('ix_trgm_vehicle_text', 'wsb.vehicle',
         $x$(lower(coalesce(asset_number, '') || ' ' || coalesce(make, '') || ' ' || coalesce(model, '') || ' ' || coalesce(notes, '')))$x$),
        ('ix_trgm_vehicle_location',   'wsb.vehicle',            '(lower(location))'),
        ('ix_trgm_vehicle_department', 'wsb.vehicle',            '(lower(department))'),
        ('ix_trgm_driver_name',        'wsb.driver',             $x$(lower(first_name || ' ' || last_name))$x$),
        ('ix_trgm_fuel_vendor',        'wsb.fuel_record',        '(lower(vendor))'),
        ('ix_trgm_trip_destination',   'wsb.trip',               '(lower(destination))'),
        ('ix_trgm_trip_purpose',       'wsb.trip',               '(lower(purpose))'),
        ('ix_trgm_trip_project',       'wsb.trip',               '(lower(project_program))'),
        ('ix_trgm_mr_service',         'wsb.maintenance_record', '(lower(service_type))'),
        ('ix_trgm_mr_vendor',          'wsb.maintenance_record', '(lower(vendor))')
    ) AS t(name, tbl, expr) LOOP
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %s USING gin (%s %I.gin_trgm_ops)', ix.name, ix.tbl, ix.expr, s);
    END LOOP;
END;
$$;
