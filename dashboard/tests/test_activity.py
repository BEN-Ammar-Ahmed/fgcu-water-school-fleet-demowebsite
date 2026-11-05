"""Activity log (who viewed / changed / downloaded what) and last-seen."""
import psycopg2
import pytest


def _vid(dbq, tag='DEMO-T01'):
    return dbq('SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = %s', (tag,))[0]['vehicle_id']


def _last(dbq, kind=None):
    rows = dbq('SELECT * FROM wsb.activity_log ' + ('WHERE kind = %s ' if kind else '') + 'ORDER BY activity_id DESC LIMIT 1',
               (kind,) if kind else None)
    return rows[0] if rows else None


def test_sign_in_is_logged(client, dbq):
    client.post('/login/demo', data={'email': 'campus.staff@example.edu'})
    row = _last(dbq, 'sign-in')
    assert row and row['username'] == 'demo_tier2' and row['full_name'] == 'Demo Campus Staff'


def test_vehicle_view_is_logged(client, sign_in, dbq):
    sign_in(client, 'demo_tier2')
    client.get(f'/vehicles/{_vid(dbq)}')
    row = _last(dbq, 'view')
    assert row['username'] == 'demo_tier2' and row['summary'].startswith('Vehicle: ')


def test_search_is_logged(client, sign_in, dbq):
    sign_in(client, 'demo_tier2')
    client.get('/search?q=F-250')
    assert _last(dbq, 'view')['summary'] == 'Search: F-250'


def test_adding_a_trip_is_logged(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    client.post('/trips/new', data={'vehicle_id': _vid(dbq), 'driver_id': dbq("SELECT driver_id FROM wsb.driver WHERE email = 'arivera@example.edu'")[0]['driver_id'],
                                    'start_datetime': '2026-11-02T08:00'})
    row = _last(dbq, 'change')
    assert row['username'] == 'demo_tier1' and 'trip' in row['summary'].lower()


def test_failed_save_is_not_logged(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    client.post('/fuel/new', data={'vehicle_id': _vid(dbq), 'fuel_date': 'x'})
    assert _last(dbq, 'change') is None


def test_deleting_a_vehicle_is_logged(client, sign_in, dbq):
    vid = dbq("INSERT INTO wsb.vehicle (vehicle_type, make) VALUES ('Car', 'Temp') RETURNING vehicle_id")[0]['vehicle_id']
    sign_in(client, 'demo_tier1')
    client.post(f'/vehicles/{vid}/delete')
    assert 'Deleted vehicle' in _last(dbq, 'change')['summary']


def test_document_download_is_logged(client, sign_in, dbq, app_module):
    vid = _vid(dbq)
    (app_module.UPLOADS / str(vid)).mkdir()
    (app_module.UPLOADS / str(vid) / 'abcd1234_reg.pdf').write_bytes(b'%PDF')
    did = dbq("""INSERT INTO wsb.vehicle_document (vehicle_id, document_type, file_location)
                 VALUES (%s, 'Registration', %s) RETURNING document_id""", (vid, f'{vid}/abcd1234_reg.pdf'))[0]['document_id']
    sign_in(client, 'demo_tier2')
    assert client.get(f'/documents/{did}/file?dl=1').status_code == 200
    assert 'Registration' in _last(dbq, 'download')['summary']


@pytest.mark.parametrize('sql', ['UPDATE wsb.activity_log SET summary = %s', 'DELETE FROM wsb.activity_log',
                                 'TRUNCATE wsb.activity_log'])
def test_log_cannot_be_changed(client, dbq, sql):
    client.post('/login/demo', data={'email': 'campus.staff@example.edu'})
    with pytest.raises(psycopg2.Error):
        dbq(sql, ('x',) if '%s' in sql else None)
    assert _last(dbq, 'sign-in') is not None


def test_last_seen_and_page_are_recorded(client, sign_in, dbq):
    sign_in(client, 'demo_tier2')
    client.get('/search?q=Sea Ark')
    row = dbq("SELECT last_seen, last_page FROM wsb.app_user WHERE username = 'demo_tier2'")[0]
    assert row['last_seen'] is not None and row['last_page'] == 'Search: Sea Ark'
