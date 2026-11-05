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
    for name in ('Demo Fleet Manager', 'Demo Backup Manager', 'Demo Boat Captain', 'Demo Campus Staff', 'Demo Former Staff'):
        assert name in page
    assert 'Top admin' in page and 'Access removed' in page


def test_top_admin_adds_an_admin(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    r = client.post('/admin/people', data={'full_name': 'New Admin', 'email': 'new.admin@fgcu.edu', 'level': 'admin'})
    assert r.status_code == 302
    assert _role(dbq, 'new.admin@fgcu.edu') == ('Admin', True)
    assert _access_rows(dbq) == 1


def test_admin_adds_an_editor(client, sign_in, dbq):
    sign_in(client, 'demo_tier1_backup')
    client.post('/admin/people', data={'full_name': 'New Captain', 'email': 'cap@fgcu.edu', 'level': 'editor'})
    assert _role(dbq, 'cap@fgcu.edu') == ('Staff', True)


def test_admin_cannot_add_an_admin(client, sign_in, dbq):
    sign_in(client, 'demo_tier1_backup')
    r = client.post('/admin/people', data={'full_name': 'Sneaky', 'email': 'sneaky@fgcu.edu', 'level': 'admin'})
    assert r.status_code == 403 and _role(dbq, 'sneaky@fgcu.edu') is None
    r = client.post('/admin/people', data={'full_name': 'Sneaky', 'email': 'sneaky@fgcu.edu', 'level': 'top_admin'})
    assert r.status_code == 403 and _role(dbq, 'sneaky@fgcu.edu') is None


def test_admin_offered_only_tier2_levels(client, sign_in):
    sign_in(client, 'demo_tier1_backup')
    page = client.get('/admin/people').get_data(as_text=True)
    form = page[page.index('id="add-person"'):]
    form = form[:form.index('</form>')]
    assert 'value="editor"' in form and 'value="viewer"' in form
    assert 'value="admin"' not in form and 'value="top_admin"' not in form


def test_admin_cannot_change_an_admin(client, sign_in, dbq):
    sign_in(client, 'demo_tier1_backup')
    tid = _uid(dbq, 'demo_tier1')
    assert client.post(f'/admin/people/{tid}/level', data={'level': 'viewer'}).status_code == 403
    assert client.post(f'/admin/people/{tid}/access', data={'active': '0'}).status_code == 403
    assert _role(dbq, 'fleet.manager@example.edu') == ('Top admin', True)


def test_admin_cannot_promote_tier2(client, sign_in, dbq):
    sign_in(client, 'demo_tier1_backup')
    assert client.post(f"/admin/people/{_uid(dbq, 'demo_tier2')}/level", data={'level': 'admin'}).status_code == 403
    assert _role(dbq, 'campus.staff@example.edu') == ('Read-only', True)


def test_admin_switches_editor_and_viewer(client, sign_in, dbq):
    sign_in(client, 'demo_tier1_backup')
    uid = _uid(dbq, 'demo_editor')
    assert client.post(f'/admin/people/{uid}/level', data={'level': 'viewer'}).status_code == 302
    assert _role(dbq, 'editor.staff@example.edu') == ('Read-only', True)
    client.post(f'/admin/people/{uid}/level', data={'level': 'editor'})
    assert _role(dbq, 'editor.staff@example.edu') == ('Staff', True)
    assert _access_rows(dbq) == 2


def test_top_admin_promotes_and_demotes(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    uid = _uid(dbq, 'demo_tier1_backup')
    client.post(f'/admin/people/{uid}/level', data={'level': 'top_admin'})
    assert _role(dbq, 'fleet.backup@example.edu') == ('Top admin', True)
    client.post(f'/admin/people/{uid}/level', data={'level': 'admin'})
    assert _role(dbq, 'fleet.backup@example.edu') == ('Admin', True)


def test_remove_and_restore_access(client, sign_in, dbq, app_module):
    other = app_module.app.test_client()
    sign_in(other, 'demo_tier2')
    assert other.get('/help').status_code == 200
    sign_in(client, 'demo_tier1_backup')
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
    with app_module.app.app_context():
        import admin
        only = _uid(dbq, 'demo_tier1')
        assert admin.keeps_a_top_admin(only, 'admin', True) is False
        assert admin.keeps_a_top_admin(only, 'top_admin', False) is False
        assert admin.keeps_a_top_admin(only, 'top_admin', True) is True
        assert admin.keeps_a_top_admin(_uid(dbq, 'demo_tier2'), 'viewer', False) is True


def test_bad_input_gives_plain_messages(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    before = dbq('SELECT count(*) n FROM wsb.app_user')[0]['n']
    page = client.post('/admin/people', data={'full_name': 'Dup', 'email': 'Campus.Staff@example.edu', 'level': 'viewer'}).get_data(as_text=True)
    assert 'already has access' in page
    page = client.post('/admin/people', data={'full_name': ' ', 'email': 'x@fgcu.edu', 'level': 'viewer'}).get_data(as_text=True)
    assert 'Enter a name' in page
    page = client.post('/admin/people', data={'full_name': 'X', 'email': 'not-an-email', 'level': 'viewer'}).get_data(as_text=True)
    assert 'Enter a valid email' in page
    assert client.post('/admin/people', data={'full_name': 'X', 'email': 'y@fgcu.edu', 'level': 'boss'}).status_code == 403
    assert dbq('SELECT count(*) n FROM wsb.app_user')[0]['n'] == before
