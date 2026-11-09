"""Handover: a new owner sets up an empty database from this repository alone, makes the first account,
and imports their own data (setup_database.py, create_admin.py, the schedules import)."""
import io

import psycopg2
import psycopg2.extras
import pytest

import create_admin
import passwords
import setup_database
from conftest import SERVER, _admin, _drop

FRESH = 'wsb_handover'


@pytest.fixture()
def fresh_url():
    conn = _admin()
    with conn.cursor() as cur:
        _drop(cur, FRESH)
    conn.close()
    url = f'{SERVER}/{FRESH}'
    yield url
    conn = _admin()
    with conn.cursor() as cur:
        _drop(cur, FRESH)
    conn.close()


def test_file_order_skips_what_a_new_owner_must_not_run():
    files = [(p.relative_to(setup_database.SQL).as_posix(), why) for p, why in setup_database.setup_files()]
    names = [n for n, _ in files]
    assert names.index('01_schema.sql') < names.index('05_procedures.sql') < names.index('15_public_reservations.sql')
    skipped = {n for n, why in files if why}
    assert {'00_create_database.sql', '06_security_tests.sql'} <= skipped
    assert not [n for n in names if n.startswith('test_data/')]           # no fake data unless --sample
    sample = [p.relative_to(setup_database.SQL).as_posix() for p, _ in setup_database.setup_files(sample=True)]
    assert sample.index('test_data/03b_demo_data.sql') < sample.index('04_import_staging.sql')


def test_empty_database_is_set_up_from_the_repository_and_can_be_run_twice(fresh_url):
    setup_database.create_database(fresh_url)
    lines = []
    assert setup_database.run(fresh_url, setup_database.setup_files(), out=lines.append)
    assert 'Ready. 0 vehicles, 0 sign-in accounts.' in '\n'.join(lines)
    assert 'Next: python create_admin.py' in '\n'.join(lines)
    assert setup_database.run(fresh_url, setup_database.setup_files(), out=lines.append)     # safe to repeat
    with psycopg2.connect(fresh_url) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM wsb.app_role WHERE role_name IN ('Top admin', 'Staff', 'Read-only')")
        assert cur.fetchone()[0] == 3
        cur.execute('SELECT count(*) FROM wsb.vehicle')
        assert cur.fetchone()[0] == 0


def test_first_admin_without_sql(fresh_url):
    setup_database.create_database(fresh_url)
    setup_database.run(fresh_url, setup_database.setup_files(), out=lambda *_: None)
    conn = psycopg2.connect(fresh_url)
    assert create_admin.create(conn, 'Fleet Manager', 'fleet@fgcu.edu', 'fleet', 'short')[1].startswith('The new password')
    assert 'valid email' in create_admin.create(conn, 'Fleet Manager', 'nope', 'fleet', 'long-enough-pass')[1]
    uid, problem = create_admin.create(conn, 'Fleet Manager', 'fleet@fgcu.edu', 'Fleet', 'long-enough-pass')
    assert problem is None and uid
    assert 'already has an account' in create_admin.create(conn, 'X', 'fleet@fgcu.edu', 'other', 'long-enough-pass')[1]
    conn.close()

    c = psycopg2.connect(fresh_url, cursor_factory=psycopg2.extras.RealDictCursor)

    def q(sql, args=(), one=False):
        with c.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall() if cur.description else []
        return (rows[0] if rows else None) if one else rows

    def run(sql, args=()):
        with c.cursor() as cur:
            cur.execute(sql, args)
        c.commit()
    row, problem = passwords.check(q, run, 'fleet', 'long-enough-pass')            # can sign in
    assert problem is None and row['user_id'] == uid
    assert q("SELECT r.role_name FROM wsb.app_user u JOIN wsb.app_role r USING (role_id) WHERE user_id = %s",
             (uid,), one=True)['role_name'] == 'Top admin'
    c.close()


def _xlsx(rows):
    import openpyxl
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_schedules_import(client, sign_in, dbq):
    from test_import import _review, _review_form
    sign_in(client, 'demo_editor')                                  # Tier 2 can add schedules by hand, so can import
    data = _xlsx([['Vehicle', 'Service', 'Every (months)', 'Every (miles)', 'Last done', 'Mileage when last done'],
                  ['2019 Toyota Camry', 'Wiper Change', 12, None, '2026-03-01', None],
                  ['DEMO-T02', 'Tire Rotation', None, 7500, None, 30000],
                  ['DEMO-T02', 'Brake Check', None, None, None, None],          # no "how often"
                  ['DEMO-T01', 'Oil Change', 6, 5000, None, None]])             # DEMO-T01 already has one
    html = _review(client, 'schedules', 's.xlsx', data).get_data(as_text=True)
    assert 'Say how often' in html and 'already has a Oil Change schedule' in html
    form = _review_form(html)
    for i in (2, 3):                                                # untick the two problem rows
        form.pop(f'keep{i}', None)
    form['action'] = 'save'
    assert client.post('/import/review', data=form).status_code == 302
    rows = dbq("""SELECT v.asset_number, r.maintenance_type, r.time_interval_months, r.mileage_interval
                  FROM wsb.maintenance_rule r JOIN wsb.vehicle v USING (vehicle_id)
                  WHERE r.maintenance_type IN ('Wiper Change', 'Tire Rotation') ORDER BY 1""")
    got = {tuple(r.values()) for r in rows}
    assert {('DEMO-C01', 'Wiper Change', 12, None), ('DEMO-T02', 'Tire Rotation', None, 7500)} <= got
    assert not dbq("SELECT 1 FROM wsb.maintenance_rule WHERE maintenance_type = 'Brake Check'")   # unticked: not saved
    sign_in(client, 'demo_tier2')                                   # viewers can't
    assert client.get('/import').status_code == 403
