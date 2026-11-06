"""10_suggestions.sql: sign-out kind, details column, log still append-only, pg_trgm present."""
import psycopg2
import pytest


def test_activity_allows_sign_out(dbq):
    dbq("INSERT INTO wsb.activity_log (kind, summary) VALUES ('sign-out', 'Signed out')")
    assert dbq("SELECT count(*) n FROM wsb.activity_log WHERE kind = 'sign-out'")[0]['n'] == 1


def test_activity_has_details_column(dbq):
    dbq("""INSERT INTO wsb.activity_log (kind, summary, details)
           VALUES ('change', 'x', '[{"field": "Status", "old": "A", "new": "B"}]'::jsonb)""")
    row = dbq("SELECT details FROM wsb.activity_log WHERE summary = 'x'")[0]
    assert row['details'] == [{'field': 'Status', 'old': 'A', 'new': 'B'}]


def test_old_rows_still_append_only(dbq):
    dbq("INSERT INTO wsb.activity_log (kind, summary) VALUES ('view', 'y')")
    with pytest.raises(psycopg2.Error, match='cannot be changed or deleted'):
        dbq("UPDATE wsb.activity_log SET summary = 'z' WHERE summary = 'y'")


def test_pg_trgm_installed_in_test_db(dbq):
    assert dbq("SELECT count(*) n FROM pg_extension WHERE extname = 'pg_trgm'")[0]['n'] == 1
