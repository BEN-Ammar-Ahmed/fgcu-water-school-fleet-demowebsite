"""Fixes from the admin-view review."""


def _uid(dbq, username):
    return dbq('SELECT user_id FROM wsb.app_user WHERE username = %s', (username,))[0]['user_id']


def test_names_with_quotes_never_end_up_inside_javascript(client, sign_in, dbq):
    evil = "x');alert(1);('"
    dbq("""INSERT INTO wsb.app_user (username, full_name, email, role_id)
           SELECT 'obrien', %s, 'obrien@fgcu.edu', role_id FROM wsb.app_role WHERE role_name = 'Read-only'""", (evil,))
    sign_in(client, 'demo_tier1')
    page = client.get('/admin/people').get_data(as_text=True)
    import re
    handlers = re.findall(r'on(?:submit|change)="([^"]*)"', page)   # the JavaScript itself
    assert handlers and not any('alert' in h or 'x&#39;' in h or "x'" in h for h in handlers)
    assert 'data-name="x&#39;);alert(1);(&#39;"' in page


def test_license_searches_are_not_shown_to_admins(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    client.get('/search?q=DEMO-DL-0003&kind=licenses')
    client.get('/search?q=DEMO-DL-0003')
    rows = dbq("SELECT summary, path FROM wsb.activity_log WHERE kind = 'view'")
    assert rows and not any('DEMO-DL' in (r['summary'] + (r['path'] or '')) for r in rows)
    assert 'DEMO-DL' not in (dbq("SELECT last_page FROM wsb.app_user WHERE username = 'demo_tier1'")[0]['last_page'] or '')
    sign_in(client, 'demo_tier1_backup')
    assert 'DEMO-DL' not in client.get('/admin/activity').get_data(as_text=True)
    assert 'DEMO-DL' not in client.get('/admin').get_data(as_text=True)


def test_editors_cannot_see_driver_emails(client, sign_in, dbq):
    did = dbq("SELECT driver_id FROM wsb.driver WHERE email = 'arivera@example.edu'")[0]['driver_id']
    dbq("""INSERT INTO wsb.app_user_permission (user_id, permission)
           SELECT user_id, 'trips_fuel' FROM wsb.app_user WHERE username = 'demo_editor'""")   # Tier 2 needs a switch for trips
    sign_in(client, 'demo_editor')
    assert client.get('/drivers/new').status_code == 403
    assert client.get(f'/drivers/{did}/edit').status_code == 403
    trip_form = client.get('/trips/new').get_data(as_text=True)
    assert 'Alex Rivera' in trip_form and '@example.edu' not in trip_form
    page = client.get('/search?q=arivera@example.edu&kind=drivers').get_data(as_text=True)
    assert 'Drivers ·' not in page
    assert 'href="/drivers/new"' not in client.get('/help').get_data(as_text=True)


def test_editor_with_trips_switch_logs_a_trip(client, sign_in, dbq):
    dbq("""INSERT INTO wsb.app_user_permission (user_id, permission)
           SELECT user_id, 'trips_fuel' FROM wsb.app_user WHERE username = 'demo_editor'""")   # Tier 2 needs a switch for trips
    vid = dbq("SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = 'DEMO-T01'")[0]['vehicle_id']
    did = dbq("SELECT driver_id FROM wsb.driver WHERE email = 'arivera@example.edu'")[0]['driver_id']
    sign_in(client, 'demo_editor')
    r = client.post('/trips/new', data={'vehicle_id': vid, 'driver_id': did, 'start_datetime': '2026-11-03T09:00'})
    assert r.status_code == 302
    assert dbq("SELECT count(*) n FROM wsb.trip WHERE start_datetime = '2026-11-03 09:00'")[0]['n'] == 1


def test_demo_users_can_be_deleted_after_signing_in(client, dbq):
    client.post('/login/account', data={'email': 'campus.staff@example.edu'})
    dbq("DELETE FROM wsb.app_user WHERE username = 'demo_tier2'")
    assert dbq("SELECT count(*) n FROM wsb.activity_log WHERE username = 'demo_tier2'")[0]['n'] == 1


def test_activity_text_filter_with_underscore_and_percent(client, sign_in, dbq):
    dbq("INSERT INTO wsb.activity_log (full_name, kind, summary) VALUES ('X', 'view', 'Opened insurance_card 50% off')")
    dbq("INSERT INTO wsb.activity_log (full_name, kind, summary) VALUES ('X', 'view', 'Opened insurancexcard')")
    sign_in(client, 'demo_tier1')
    page = client.get('/admin/activity?q=insurance_card').get_data(as_text=True)
    assert 'insurance_card 50% off' in page and 'insurancexcard' not in page
    assert 'insurance_card 50% off' in client.get('/admin/activity?q=50%25').get_data(as_text=True)


def test_signed_out_people_are_not_shown_as_signed_in(client, sign_in, dbq, app_module):
    other = app_module.app.test_client()
    other.post('/login/account', data={'email': 'editor.staff@example.edu'})
    other.get('/help')
    other.get('/logout')
    assert dbq("SELECT last_seen FROM wsb.app_user WHERE username = 'demo_editor'")[0]['last_seen'] is None
    sign_in(client, 'demo_tier1')
    page = client.get('/admin').get_data(as_text=True)
    online = page[page.index('id="online"'):]
    assert 'Boat Captain' not in online[:online.index('</section>')]
