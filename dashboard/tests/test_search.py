import datetime as dt

import pytest

from search import parse_date_term, run_search
from tiers import load_user

D = dt.date


@pytest.fixture()
def find(app_module, dbq):
    def do(username, text, kind='all', filters=None):
        uid = dbq('SELECT user_id FROM wsb.app_user WHERE username = %s', (username,))[0]['user_id']
        with app_module.app.app_context():
            user = load_user(app_module.q, uid)
            return run_search(app_module.q, user, text, kind, filters)
    return do


def test_parse_date_term():
    assert parse_date_term('2026-10-03') == (D(2026, 10, 3), D(2026, 10, 4))
    assert parse_date_term('10/03/2026') == (D(2026, 10, 3), D(2026, 10, 4))
    assert parse_date_term('October 2026') == (D(2026, 10, 1), D(2026, 11, 1))
    assert parse_date_term('Dec 2026') == (D(2026, 12, 1), D(2027, 1, 1))
    assert parse_date_term('October') == (D(D.today().year, 10, 1), D(D.today().year, 11, 1))
    assert parse_date_term('2026-13-45') is None
    assert parse_date_term('10/3') is None
    assert parse_date_term('Ford') is None


def test_vehicle_search_finds_f250(find):
    rows = find('demo_tier2', 'F-250')['vehicles']['rows']
    assert rows[0]['asset_number'] == 'DEMO-T01'


def test_date_search_finds_trips_that_day(find):
    g = find('demo_tier2', '2026-10-03', 'trips')['trips']
    assert g['total'] == 1 and g['rows'][0]['destination'] == 'Matlacha Boat Ramp'


def test_trips_have_no_driver_email(find):
    rows = find('demo_tier2', 'DEMO-T01', 'trips')['trips']['rows']
    assert rows and not any('email' in k for r in rows for k in r)
    assert rows[0]['driver_name']


def test_wildcards_are_literal(find):
    assert all(g['total'] == 0 for g in find('demo_tier1', '%').values())
    assert all(g['total'] == 0 for g in find('demo_tier1', '_').values())
    find('demo_tier1', "O'Brien")


def test_tier2_never_gets_admin_documents(find):
    assert find('demo_tier2', 'Title', 'documents')['documents']['total'] == 0
    assert find('demo_tier1', 'Title', 'documents')['documents']['total'] == 4


def test_licenses_only_with_flag(find):
    assert 'licenses' not in find('demo_tier2', 'Patel')
    assert 'licenses' not in find('demo_tier2', 'Patel', 'licenses')
    assert 'licenses' not in find('demo_tier2_licenses', 'Patel')
    assert 'licenses' not in find('demo_tier1_backup', 'Patel')   # admin: no confidential data
    assert find('demo_tier1', 'Patel')['licenses']['total'] == 1


def test_group_limit_and_total(find, dbq):
    dbq("""INSERT INTO wsb.trip (vehicle_id, driver_id, start_datetime, destination)
           SELECT v.vehicle_id, d.driver_id, timestamp '2025-01-01' + g * interval '1 day', 'Bulk trip'
           FROM wsb.vehicle v, wsb.driver d, generate_series(1, 60) g
           WHERE v.asset_number = 'DEMO-T01' AND d.email = 'arivera@example.edu'""")
    g = find('demo_tier2', 'DEMO-T01', 'trips')['trips']
    assert len(g['rows']) == 50 and g['total'] >= 60


def test_blank_search_returns_nothing(find):
    assert find('demo_tier2', '   ') == {}


def test_filters_narrow_trips_by_date(find):
    g = find('demo_tier2', 'DEMO-T01', 'trips', {'date_from': D(2026, 10, 1), 'date_to': D(2026, 10, 31)})['trips']
    assert g['total'] == 2
