import pytest


def _vid(dbq, tag):
    return dbq('SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = %s', (tag,))[0]['vehicle_id']


def test_add_trip_success(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    vid = _vid(dbq, 'DEMO-T01')
    r = client.post('/trips/new', data={
        'vehicle_id': vid, 'driver_id': dbq("SELECT driver_id FROM wsb.driver WHERE email = 'arivera@example.edu'")[0]['driver_id'], 'start_datetime': '2026-11-02T08:00',
        'end_datetime': '2026-11-02T12:00', 'starting_mileage': '48210', 'ending_mileage': '48300',
        'destination': 'Matlacha Boat Ramp', 'purpose': 'Field work'})
    assert r.status_code == 302 and r.headers['Location'].endswith(f'/vehicles/{vid}#trips')
    assert dbq('SELECT current_mileage FROM wsb.vehicle WHERE vehicle_id = %s', (vid,))[0]['current_mileage'] == 48300


def test_unapproved_driver_rejected_by_form(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    r = client.post('/trips/new', data={'vehicle_id': _vid(dbq, 'DEMO-T01'), 'driver_id': dbq("SELECT driver_id FROM wsb.driver WHERE email = 'spatel@example.edu'")[0]['driver_id'],
                                        'start_datetime': '2026-11-02T08:00'})
    assert r.status_code == 200
    assert 'Driver must be one of the choices.' in r.get_data(as_text=True)
    assert dbq("SELECT count(*) n FROM wsb.trip WHERE start_datetime = '2026-11-02 08:00'")[0]['n'] == 0


def test_db_error_message_passes_database_text(app_module):
    import psycopg2
    with app_module.app.app_context():
        try:
            app_module.run("SELECT wsb.add_trip(p_asset_number => 'DEMO-T01', p_driver_email => 'spatel@example.edu', "
                           "p_start_datetime => now()::timestamp)")
        except psycopg2.Error as e:
            assert app_module.db_error_message(e) == 'This driver is not approved or is inactive.'
        else:
            raise AssertionError('expected the database to refuse')
        try:
            app_module.run("INSERT INTO wsb.trip (vehicle_id, driver_id, start_datetime) VALUES (-1, -1, now())")
        except psycopg2.Error as e:
            assert app_module.db_error_message(e) == 'Could not save. Check the values and try again.'


def test_end_before_start_shows_plain_message(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    r = client.post('/trips/new', data={'vehicle_id': _vid(dbq, 'DEMO-T01'), 'driver_id': dbq("SELECT driver_id FROM wsb.driver WHERE email = 'arivera@example.edu'")[0]['driver_id'],
                                        'start_datetime': '2026-11-02T08:00', 'end_datetime': '2026-11-01T08:00'})
    assert r.status_code == 200 and 'Could not save' in r.get_data(as_text=True)


def test_trip_form_prefills_vehicle(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    vid = _vid(dbq, 'DEMO-T01')
    page = client.get(f'/trips/new?vehicle_id={vid}').get_data(as_text=True)
    assert f'value="{vid}" selected' in page
    assert 'spatel@example.edu' not in page


def test_add_fuel_and_maintenance(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    c01, t02 = _vid(dbq, 'DEMO-C01'), _vid(dbq, 'DEMO-T02')
    r = client.post('/fuel/new', data={'vehicle_id': c01, 'fuel_date': '2026-11-02', 'gallons': '11.2',
                                       'total_cost': '42.50', 'vendor': 'Sample Gas A'})
    assert r.status_code == 302 and r.headers['Location'].endswith(f'/vehicles/{c01}#fuel')
    assert dbq("SELECT count(*) n FROM wsb.fuel_record WHERE fuel_date = '2026-11-02'")[0]['n'] == 1
    r = client.post('/maintenance/new', data={'vehicle_id': t02, 'service_date': '2026-11-02',
                                              'service_type': 'Oil Change', 'cost': '120', 'mileage_at_service': '30500'})
    assert r.status_code == 302
    rule = dbq("""SELECT last_completed_date::text d FROM wsb.maintenance_rule
                  WHERE vehicle_id = %s AND maintenance_type = 'Oil Change'""", (t02,))[0]
    assert rule['d'] == '2026-11-02'


def test_bad_number_shows_message_not_crash(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    r = client.post('/fuel/new', data={'vehicle_id': _vid(dbq, 'DEMO-C01'), 'fuel_date': '2026-11-02',
                                       'gallons': 'lots', 'total_cost': '5'})
    assert r.status_code == 200 and 'Gallons must be a number' in r.get_data(as_text=True)


@pytest.mark.parametrize('path', ['/trips/new', '/fuel/new', '/maintenance/new', '/drivers/new'])
def test_tier2_forbidden_everywhere(client, sign_in, path):
    sign_in(client, 'demo_tier2')
    assert client.get(path).status_code == 403
    assert client.post(path, data={}).status_code == 403


def test_driver_license_fields_need_flag(client, sign_in, dbq):
    did = dbq("SELECT driver_id FROM wsb.driver WHERE email = 'spatel@example.edu'")[0]['driver_id']
    sign_in(client, 'demo_tier1_backup')
    assert 'License number' not in client.get('/drivers/new').get_data(as_text=True)
    assert client.get(f'/drivers/{did}').status_code == 403
    sign_in(client, 'demo_tier1')
    assert 'License number' in client.get('/drivers/new').get_data(as_text=True)
    page = client.get(f'/drivers/{did}')
    assert page.status_code == 200 and 'DEMO-DL-' in page.get_data(as_text=True)


def test_add_driver_with_license(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    r = client.post('/drivers/new', data={'first_name': 'Riley', 'last_name': 'Moss', 'email': 'rmoss@example.edu',
                                          'driver_type': 'Staff', 'approved': 'on', 'license_number': 'X123',
                                          'state': 'FL', 'license_expiration': '2029-01-31'})
    assert r.status_code == 302
    row = dbq("""SELECT d.approved, l.license_number FROM wsb.driver d JOIN wsb.driver_license l USING (driver_id)
                 WHERE d.email = 'rmoss@example.edu'""")[0]
    assert row['approved'] is True and row['license_number'] == 'X123'


def test_backup_cannot_set_license_by_post(client, sign_in, dbq):
    sign_in(client, 'demo_tier1_backup')
    client.post('/drivers/new', data={'first_name': 'Kai', 'last_name': 'Lane', 'email': 'klane@example.edu',
                                      'license_number': 'SNEAKY'})
    assert dbq("SELECT count(*) n FROM wsb.driver_license WHERE license_number = 'SNEAKY'")[0]['n'] == 0
    assert dbq("SELECT count(*) n FROM wsb.driver WHERE email = 'klane@example.edu'")[0]['n'] == 1


def test_edit_driver(client, sign_in, dbq):
    did = dbq("SELECT driver_id FROM wsb.driver WHERE email = 'spatel@example.edu'")[0]['driver_id']
    sign_in(client, 'demo_tier1')
    r = client.post(f'/drivers/{did}/edit', data={'first_name': 'Sam', 'last_name': 'Patel', 'email': 'spatel@example.edu',
                                                  'driver_type': 'OPS', 'approved': 'on'})
    assert r.status_code == 302
    assert dbq('SELECT approved FROM wsb.driver WHERE driver_id = %s', (did,))[0]['approved'] is True


def test_add_menu_links(client, sign_in):
    sign_in(client, 'demo_tier1')
    page = client.get('/help').get_data(as_text=True)
    for href in ('/trips/new', '/fuel/new', '/maintenance/new', '/drivers/new'):
        assert f'href="{href}"' in page


def test_forms_mark_suggestion_fields(client, sign_in):
    sign_in(client, 'demo_tier1')
    html = client.get('/fuel/new').get_data(as_text=True)
    assert 'data-suggest-select="vehicle"' in html and '<select name="vehicle_id"' in html   # plain list kept for no-JS
    assert 'data-suggest="vendor"' in html and 'data-suggest-submit="false"' in html
    html = client.get('/trips/new').get_data(as_text=True)
    assert 'data-suggest-select="driver"' in html and 'data-suggest="destination"' in html
    assert 'data-suggest="service_type"' in client.get('/maintenance/new').get_data(as_text=True)
    assert 'data-suggest="location"' in client.get('/vehicles/new').get_data(as_text=True)
