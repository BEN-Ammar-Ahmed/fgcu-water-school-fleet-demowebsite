-- =====================================================================
-- File 03: Reference data   PostgreSQL / Supabase
-- PART A of ../03_sample_data.sql: real lookup rows that every database needs.
-- Run AFTER 01 and 02. Safe on the real Supabase database and safe to re-run.
-- (The fictional demo rows from PART B are in 03b_demo_data.sql.)
-- =====================================================================

-- WEX Purchase Activity Report code legend
INSERT INTO wsb.wex_code (code, code_type, meaning) VALUES
 ('AD','Transaction','Adjustment'),
 ('CL','Transaction','Cardlock'),
 ('CP','Transaction','Contract Pricing'),
 ('EN','Transaction','Enhanced Merchant Network'),
 ('IP','Transaction','Indoor Payment Terminal'),
 ('MF','Transaction','Mobile Fueling'),
 ('MN','Transaction','Manual'),
 ('OP','Transaction','Outdoor Payment Terminal'),
 ('PS','Transaction','Private Site'),
 ('TP','Transaction','Transponder'),
 ('TR','Transaction','Transaction Reversal'),
 ('CCF','Fee','Currency Conversion Fee'),
 ('EVF','Fee','Electric Vehicle Fee'),
 ('PSF','Fee','Private Site Fee'),
 ('TSF','Fee','Truck Stop Fee'),
 ('CBF','Fee','Cash Back Fee'),
 ('ONF','Fee','Out of Network Fee')
ON CONFLICT (code) DO NOTHING;

-- Security role catalogue (also added by 02_security.sql)
INSERT INTO wsb.app_role (role_name, pg_role, description) VALUES
 ('Admin',     'wsb_admin',    'Full access: manage users, delete records, see all documents'),
 ('Staff',     'wsb_staff',    'Add and edit operational data; cannot delete or manage users'),
 ('Read-only', 'wsb_readonly', 'View vehicles, trips, fuel, maintenance, invoices and reports only')
ON CONFLICT (role_name) DO NOTHING;
