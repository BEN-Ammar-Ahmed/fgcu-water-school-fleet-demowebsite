-- 11_vehicle_name.sql
-- A vehicle's own name (e.g. "2013 Ford F150 4x4", "Canoe trailer"), edited on its Edit page.
-- Until now the site used the first part of the notes as the name, so notes like
-- "Console repair pending" turned into the vehicle's name. The first time this runs it copies
-- that first part of the notes into the new column; after that, name and notes are separate.
-- Safe to run more than once.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'wsb' AND table_name = 'vehicle' AND column_name = 'name') THEN
        ALTER TABLE wsb.vehicle ADD COLUMN name VARCHAR(80);
        UPDATE wsb.vehicle SET name = left(nullif(trim(split_part(notes, ';', 1)), ''), 80);
    END IF;
END;
$$;

COMMENT ON COLUMN wsb.vehicle.name IS
    'What people call this vehicle. Empty = the site shows year, make and model.';
