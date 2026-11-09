-- 16_document_files.sql
-- Uploaded documents stored inside the database, for hosts with no lasting disk (Vercel).
-- Used only when the fleet site runs with DOCUMENTS_IN_DATABASE=1 (always on Vercel). Otherwise the
-- files stay in dashboard/uploads/ as before and this table stays empty.
-- file_location matches wsb.vehicle_document.file_location ('<vehicle id>/<random>_<name>').
-- Safe to run more than once.

CREATE TABLE IF NOT EXISTS wsb.document_file (
    file_location VARCHAR(500) PRIMARY KEY,
    content       BYTEA NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE wsb.document_file IS 'File contents of uploaded documents when DOCUMENTS_IN_DATABASE=1.';

SELECT wsb.lock_out_public_api();
