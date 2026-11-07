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
    client.post('/login', data={'password': 'test-password-1', 'username': 'campus.staff@example.edu'})
    row = _last(dbq, 'sign-in')
    assert row and row['username'] == 'demo_tier2' and row['full_name'] == 'Campus Staff'


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
    client.post('/login', data={'password': 'test-password-1', 'username': 'campus.staff@example.edu'})
    with pytest.raises(psycopg2.Error):
        dbq(sql, ('x',) if '%s' in sql else None)
    assert _last(dbq, 'sign-in') is not None


def test_last_seen_and_page_are_recorded(client, sign_in, dbq):
    sign_in(client, 'demo_tier2')
    client.get('/search?q=Sea Ark')
    row = dbq("SELECT last_seen, last_page FROM wsb.app_user WHERE username = 'demo_tier2'")[0]
    assert row['last_seen'] is not None and row['last_page'] == 'Search: Sea Ark'


# --- Before → after detail and sign-outs (2026-11-06) ---------------------------------
def _edit_vehicle(client, dbq, vid, **changes):
    v = dbq('SELECT * FROM wsb.vehicle WHERE vehicle_id = %s', (vid,))[0]
    form = {k: ('' if v[k] is None else str(v[k])) for k in ('name', 'asset_number', 'vehicle_type', 'make', 'model', 'year', 'vin',
            'license_plate', 'department', 'current_mileage', 'current_hours', 'location', 'status', 'notes')}
    form.update(changes)
    return client.post(f'/vehicles/{vid}/edit', data=form)


def test_vehicle_edit_logs_before_after(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    vid = _vid(dbq)
    old = dbq('SELECT current_mileage FROM wsb.vehicle WHERE vehicle_id = %s', (vid,))[0]['current_mileage'] or 0
    _edit_vehicle(client, dbq, vid, current_mileage=str(old + 850), status='Out of Service')
    d = _last(dbq, 'change')['details']
    assert {'field': 'Status', 'old': 'Available', 'new': 'Out of Service'} in d or any(x['field'] == 'Status' for x in d)
    assert any(x['field'] == 'Mileage' and x['new'] == f'{old + 850:,}' for x in d)


def test_edit_without_changes_has_no_details(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    _edit_vehicle(client, dbq, _vid(dbq))
    row = _last(dbq, 'change')
    assert row['summary'].startswith('Edited vehicle') and row['details'] is None


def test_vin_change_is_hidden(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    _edit_vehicle(client, dbq, _vid(dbq), vin='ZZSECRET123')
    row = _last(dbq, 'change')
    assert {'field': 'VIN / HIN', 'old': None, 'new': None, 'hidden': True} in row['details']
    assert 'ZZSECRET123' not in str(row)


def test_driver_edit_hides_license_values(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    d = dbq("SELECT * FROM wsb.driver WHERE email = 'arivera@example.edu'")[0]
    client.post(f"/drivers/{d['driver_id']}/edit", data={
        'first_name': d['first_name'], 'last_name': d['last_name'], 'email': d['email'], 'department': 'Changed Dept',
        'driver_type': d['driver_type'] or '', 'approved': 'on' if d['approved'] else '', 'active': 'on',
        'license_number': 'LICSECRET99', 'state': 'FL', 'license_expiration': '2030-01-01'})
    row = _last(dbq, 'change')
    assert any(x['field'] == 'Department' and x['new'] == 'Changed Dept' for x in row['details'])
    assert any(x['field'] == 'License number' and x.get('hidden') for x in row['details'])
    assert 'LICSECRET99' not in str(row)


def test_mark_done_logs_last_done(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    rid = dbq('SELECT rule_id FROM wsb.maintenance_rule WHERE enabled ORDER BY rule_id LIMIT 1')[0]['rule_id']
    client.post(f'/maintenance/{rid}/done', data={'date': '2026-11-06'})
    d = _last(dbq, 'change')['details']
    assert any(x['field'] == 'Last done' and x['new'] == 'Nov 06, 2026' for x in d)


def test_sign_out_is_logged(client, sign_in, dbq):
    sign_in(client, 'demo_tier2')
    client.get('/logout')
    row = _last(dbq, 'sign-out')
    assert row and row['username'] == 'demo_tier2' and row['summary'] == 'Signed out'


def test_activity_page_shows_detail_line_and_sign_out_filter(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    _edit_vehicle(client, dbq, _vid(dbq), status='Out of Service')
    html = client.get('/admin/activity').get_data(as_text=True)
    assert 'Status: ' in html and '→ Out of Service' in html
    assert '<option value="sign-out"' in html
