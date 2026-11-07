"""Sign-in: username (or email) + password, lockout, temporary passwords (14_passwords.sql)."""
import passwords

PW = 'test-password-1'


def _login(client, username, password=PW, **extra):
    return client.post('/login', data={'username': username, 'password': password, **extra})


def test_login_page_is_a_username_and_password_form(client):
    page = client.get('/login').get_data(as_text=True)
    assert 'name="username"' in page and 'type="password"' in page
    assert 'Fleet Manager' not in page and 'Tier 1' not in page        # no list of accounts


def test_sign_in_with_username_or_email(client):
    assert _login(client, 'demo_tier2').status_code == 302
    client.get('/logout')
    r = _login(client, 'Campus.Staff@example.edu')
    assert r.status_code == 302
    with client.session_transaction() as s:
        assert s.get('user_id')


def test_wrong_password_and_unknown_user_look_the_same(client):
    a = _login(client, 'demo_tier2', 'nope-nope-nope')
    b = _login(client, 'nobody@fgcu.edu', 'nope-nope-nope')
    assert a.status_code == b.status_code == 401
    assert 'Wrong username or password.' in a.get_data(as_text=True)
    assert 'Wrong username or password.' in b.get_data(as_text=True)
    with client.session_transaction() as s:
        assert not s.get('user_id')


def test_failed_sign_in_is_logged_without_the_password(client, dbq):
    _login(client, 'demo_tier2', 'secret-guess-123')
    row = dbq("SELECT summary FROM wsb.activity_log WHERE kind = 'sign-in' ORDER BY activity_id DESC LIMIT 1")[0]
    assert 'Failed sign-in for "demo_tier2"' in row['summary']
    assert 'secret-guess-123' not in str(dbq('SELECT * FROM wsb.activity_log'))


def test_lockout_after_too_many_wrong_passwords(client, dbq):
    for _ in range(passwords.MAX_TRIES):
        r = _login(client, 'demo_tier2', 'wrong-password')
    assert 'Too many wrong passwords' in r.get_data(as_text=True)
    r = _login(client, 'demo_tier2')                                   # right password, still locked
    assert r.status_code == 401 and 'Too many wrong passwords' in r.get_data(as_text=True)
    dbq("UPDATE wsb.app_user_password SET locked_until = now() - interval '1 minute'")
    assert _login(client, 'demo_tier2').status_code == 302


def test_inactive_user_cannot_sign_in(client):
    assert _login(client, 'former.staff@example.edu').status_code == 401


def test_passwords_are_stored_hashed(dbq):
    rows = dbq('SELECT password_hash FROM wsb.app_user_password')
    assert rows and all(PW not in r['password_hash'] and r['password_hash'].startswith('scrypt:') for r in rows)


def test_next_link_is_kept_and_checked(client):
    assert _login(client, 'demo_tier2', next='/search?q=F-250').headers['Location'].endswith('/search?q=F-250')
    client.get('/logout')
    assert _login(client, 'demo_tier2', next='https://evil.example').headers['Location'].endswith('/')


def test_signed_in_user_deactivated_is_signed_out(client, sign_in, dbq):
    sign_in(client, 'demo_tier2')
    dbq("UPDATE wsb.app_user SET active = false WHERE username = 'demo_tier2'")
    r = client.get('/')
    assert r.status_code == 302 and '/login' in r.headers['Location']


def test_change_own_password(client):
    _login(client, 'demo_tier2')
    r = client.post('/account/password', data={'current': 'wrong', 'new': 'brand-new-pass', 'confirm': 'brand-new-pass'})
    assert 'current password is not right' in r.get_data(as_text=True)
    r = client.post('/account/password', data={'current': PW, 'new': 'short', 'confirm': 'short'})
    assert 'at least 8 characters' in r.get_data(as_text=True)
    r = client.post('/account/password', data={'current': PW, 'new': 'brand-new-pass', 'confirm': 'other-pass-x'})
    assert "don&#39;t match" in r.get_data(as_text=True)
    assert client.post('/account/password', data={'current': PW, 'new': 'brand-new-pass',
                                                  'confirm': 'brand-new-pass'}).status_code == 302
    client.get('/logout')
    assert _login(client, 'demo_tier2').status_code == 401
    assert _login(client, 'demo_tier2', 'brand-new-pass').status_code == 302


def test_top_admin_adds_person_with_temporary_password(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    client.post('/admin/people', data={'full_name': 'Nia Vale', 'email': 'nvale@fgcu.edu', 'level': 'viewer',
                                       'password': 'temp-pass-42'})
    row = dbq("""SELECT u.username, p.must_change FROM wsb.app_user u JOIN wsb.app_user_password p USING (user_id)
                 WHERE u.email = 'nvale@fgcu.edu'""")[0]
    assert row == {'username': 'nvale', 'must_change': True}
    other = client.application.test_client()
    r = _login(other, 'nvale', 'temp-pass-42')
    assert r.headers['Location'].endswith('/account/password')
    assert other.get('/').headers['Location'].endswith('/account/password')      # must choose a password first
    assert other.post('/account/password', data={'current': 'temp-pass-42', 'new': 'nias-own-pass',
                                                 'confirm': 'nias-own-pass'}).status_code == 302
    assert other.get('/').status_code == 200


def test_temporary_password_too_short_is_refused(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    r = client.post('/admin/people', data={'full_name': 'Kai Lane', 'email': 'klane@fgcu.edu', 'level': 'viewer',
                                           'password': 'short'})
    assert 'The temporary password needs at least 8 characters.' in r.get_data(as_text=True)
    assert not dbq("SELECT 1 FROM wsb.app_user WHERE email = 'klane@fgcu.edu'")


def test_top_admin_resets_a_password_and_unlocks(client, sign_in, dbq):
    uid = dbq("SELECT user_id FROM wsb.app_user WHERE username = 'demo_tier2'")[0]['user_id']
    dbq("UPDATE wsb.app_user_password SET locked_until = now() + interval '1 hour' WHERE user_id = %s", (uid,))
    sign_in(client, 'demo_tier1')
    client.post(f'/admin/people/{uid}/password', data={'password': 'reset-pass-77'})
    other = client.application.test_client()
    assert _login(other, 'demo_tier2', 'reset-pass-77').headers['Location'].endswith('/account/password')
    log = dbq("SELECT summary FROM wsb.activity_log WHERE kind = 'access' ORDER BY activity_id DESC LIMIT 1")[0]
    assert log['summary'] == 'Set a temporary password for Campus Staff'


def test_only_top_admin_resets_passwords(client, sign_in, dbq):
    uid = dbq("SELECT user_id FROM wsb.app_user WHERE username = 'demo_tier2'")[0]['user_id']
    sign_in(client, 'demo_editor')
    assert client.post(f'/admin/people/{uid}/password', data={'password': 'reset-pass-77'}).status_code == 403


def test_tier2_cannot_edit(client, sign_in, dbq):
    sign_in(client, 'demo_tier2')
    vid = dbq("SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = 'DEMO-T01'")[0]['vehicle_id']
    assert client.post(f'/vehicles/{vid}/edit', data={'vehicle_type': 'Car', 'status': 'Available'}).status_code == 403
