"""Admin area: People & access rules."""


def _uid(dbq, username):
    return dbq('SELECT user_id FROM wsb.app_user WHERE username = %s', (username,))[0]['user_id']


def _role(dbq, email):
    rows = dbq("""SELECT r.role_name, u.active FROM wsb.app_user u JOIN wsb.app_role r USING (role_id)
                  WHERE lower(u.email) = lower(%s)""", (email,))
    return (rows[0]['role_name'], rows[0]['active']) if rows else None


def _access_rows(dbq):
    return dbq("SELECT count(*) n FROM wsb.activity_log WHERE kind = 'access'")[0]['n']


def test_people_page_lists_everyone(client, sign_in):
    sign_in(client, 'demo_tier1')
    page = client.get('/admin/people').get_data(as_text=True)
    for name in ('Fleet Manager', 'Backup Fleet Manager', 'Boat Captain', 'Campus Staff', 'Former Staff'):
        assert name in page
    assert 'Top admin' in page and 'Access removed' in page


def test_top_admin_adds_people_at_each_tier(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    for email, level, role in (('new.top@fgcu.edu', 'top_admin', 'Top admin'), ('cap@fgcu.edu', 'editor', 'Staff'),
                               ('view@fgcu.edu', 'viewer', 'Read-only')):
        r = client.post('/admin/people', data={'password': 'temp-pass-42', 'full_name': 'New ' + level, 'email': email, 'level': level})
        assert r.status_code == 302 and _role(dbq, email) == (role, True)
    assert _access_rows(dbq) == 3


def test_old_admin_level_is_refused(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    r = client.post('/admin/people', data={'password': 'temp-pass-42', 'full_name': 'Old', 'email': 'old@fgcu.edu', 'level': 'admin'})
    assert r.status_code in (400, 403) and _role(dbq, 'old@fgcu.edu') is None


def test_add_form_offers_the_three_tiers(client, sign_in):
    sign_in(client, 'demo_tier1')
    page = client.get('/admin/people').get_data(as_text=True)
    form = page[page.index('id="add-person"'):]
    form = form[:form.index('</form>')]
    assert 'value="top_admin"' in form and 'value="editor"' in form and 'value="viewer"' in form
    assert 'value="admin"' not in form


def test_editors_and_viewers_cannot_manage_people(client, sign_in, dbq):
    for who in ('demo_editor', 'demo_tier2'):
        sign_in(client, who)
        assert client.get('/admin/people').status_code == 403
        assert client.post(f"/admin/people/{_uid(dbq, 'demo_tier2')}/level", data={'level': 'top_admin'}).status_code == 403
    assert _role(dbq, 'campus.staff@example.edu') == ('Read-only', True)


def test_top_admin_changes_tiers(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    uid = _uid(dbq, 'demo_editor')
    assert client.post(f'/admin/people/{uid}/level', data={'level': 'viewer'}).status_code == 302
    assert _role(dbq, 'editor.staff@example.edu') == ('Read-only', True)
    client.post(f'/admin/people/{uid}/level', data={'level': 'top_admin'})
    assert _role(dbq, 'editor.staff@example.edu') == ('Top admin', True)
    client.post(f'/admin/people/{uid}/level', data={'level': 'editor'})
    assert _role(dbq, 'editor.staff@example.edu') == ('Staff', True)
    assert _access_rows(dbq) == 3


def test_remove_and_restore_access(client, sign_in, dbq, app_module):
    other = app_module.app.test_client()
    sign_in(other, 'demo_tier2')
    assert other.get('/help').status_code == 200
    sign_in(client, 'demo_tier1')
    uid = _uid(dbq, 'demo_tier2')
    assert client.post(f'/admin/people/{uid}/access', data={'active': '0'}).status_code == 302
    assert _role(dbq, 'campus.staff@example.edu') == ('Read-only', False)
    r = other.get('/help')
    assert r.status_code == 302 and '/login' in r.headers['Location']
    client.post(f'/admin/people/{uid}/access', data={'active': '1'})
    assert _role(dbq, 'campus.staff@example.edu') == ('Read-only', True)


def test_nobody_changes_themselves(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    me = _uid(dbq, 'demo_tier1')
    assert client.post(f'/admin/people/{me}/level', data={'level': 'viewer'}).status_code == 403
    assert client.post(f'/admin/people/{me}/access', data={'active': '0'}).status_code == 403
    assert _role(dbq, 'fleet.manager@example.edu') == ('Top admin', True)


def test_always_keeps_a_top_admin(app_module, dbq):
    dbq("""UPDATE wsb.app_user SET active = FALSE WHERE username <> 'demo_tier1'
           AND role_id = (SELECT role_id FROM wsb.app_role WHERE role_name = 'Top admin')""")   # leave just one
    with app_module.app.app_context():
        import admin
        only = _uid(dbq, 'demo_tier1')
        assert admin.keeps_a_top_admin(only, 'editor', True) is False
        assert admin.keeps_a_top_admin(only, 'top_admin', False) is False
        assert admin.keeps_a_top_admin(only, 'top_admin', True) is True
        assert admin.keeps_a_top_admin(_uid(dbq, 'demo_tier2'), 'viewer', False) is True


def test_bad_input_gives_plain_messages(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    before = dbq('SELECT count(*) n FROM wsb.app_user')[0]['n']
    page = client.post('/admin/people', data={'password': 'temp-pass-42', 'full_name': 'Dup', 'email': 'Campus.Staff@example.edu', 'level': 'viewer'}).get_data(as_text=True)
    assert 'already has access' in page
    page = client.post('/admin/people', data={'password': 'temp-pass-42', 'full_name': ' ', 'email': 'x@fgcu.edu', 'level': 'viewer'}).get_data(as_text=True)
    assert 'Enter a name' in page
    page = client.post('/admin/people', data={'password': 'temp-pass-42', 'full_name': 'X', 'email': 'not-an-email', 'level': 'viewer'}).get_data(as_text=True)
    assert 'Enter a valid email' in page
    assert client.post('/admin/people', data={'password': 'temp-pass-42', 'full_name': 'X', 'email': 'y@fgcu.edu', 'level': 'boss'}).status_code == 403
    assert dbq('SELECT count(*) n FROM wsb.app_user')[0]['n'] == before
