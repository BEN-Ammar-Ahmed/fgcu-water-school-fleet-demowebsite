def test_unknown_email_gets_no_access(client):
    r = client.post('/login/demo', data={'email': 'nobody@fgcu.edu'})
    assert r.status_code == 403
    assert "You don't have access yet" in r.get_data(as_text=True)


def test_inactive_user_cannot_sign_in(client):
    r = client.post('/login/demo', data={'email': 'former.staff@example.edu'})
    assert r.status_code == 403


def test_known_email_signs_in(client):
    r = client.post('/login/demo', data={'email': 'Campus.Staff@example.edu'})
    assert r.status_code == 302
    with client.session_transaction() as s:
        assert s.get('user_id')


def test_signed_in_user_deactivated_is_signed_out(client, sign_in, dbq):
    sign_in(client, 'demo_tier2')
    dbq("UPDATE wsb.app_user SET active = false WHERE username = 'demo_tier2'")
    r = client.get('/')
    assert r.status_code == 302 and '/login' in r.headers['Location']


def test_tier2_cannot_edit(client, sign_in, dbq):
    sign_in(client, 'demo_tier2')
    vid = dbq("SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = 'DEMO-T01'")[0]['vehicle_id']
    assert client.post(f'/vehicles/{vid}/edit', data={'vehicle_type': 'Car', 'status': 'Available'}).status_code == 403
    assert client.post('/vehicles/new', data={'vehicle_type': 'Car', 'status': 'Available'}).status_code == 403


def test_tier1_can_edit(client, sign_in):
    sign_in(client, 'demo_tier1')
    assert client.get('/vehicles/new').status_code == 200


def test_login_has_no_role_picker(client):
    page = client.get('/login').get_data(as_text=True)
    assert 'Sign in with FGCU' in page
    assert 'Read-only' not in page
