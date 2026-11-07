"""Three tiers (Tier 1 top admin, Tier 2 editor, Tier 3 viewer) plus per-person switches (12_tiers.sql)."""
import pytest

from tiers import DEFAULTS, LEVEL_LABELS, PERMS, CurrentUser, doc_levels, level_for_role, switchable


def _u(level, extras=()):
    return CurrentUser(user_id=1, username='u', full_name='U', email=None, level=level, extras=frozenset(extras))


def _vid(dbq, tag='DEMO-T01'):
    return dbq('SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = %s', (tag,))[0]['vehicle_id']


def _switch_on(dbq, username, perm):
    dbq("""INSERT INTO wsb.app_user_permission (user_id, permission)
           SELECT user_id, %s FROM wsb.app_user WHERE username = %s""", (perm, username))


def test_level_mapping_and_labels():
    assert [level_for_role(r) for r in ('Top admin', 'Admin', 'Staff', 'Read-only', 'anything')] == \
        ['top_admin', 'top_admin', 'editor', 'viewer', 'viewer']
    assert [LEVEL_LABELS[l] for l in ('top_admin', 'editor', 'viewer')] == \
        ['Tier 1 · Top admin', 'Tier 2 · Editor', 'Tier 3 · Viewer']


def test_defaults_match_the_agreed_table():
    assert DEFAULTS['top_admin'] == frozenset(PERMS)
    assert DEFAULTS['editor'] == {'maintenance', 'checkout'}
    assert DEFAULTS['viewer'] == frozenset()
    assert 'delete' not in switchable('viewer') and 'delete' in switchable('editor')
    assert switchable('top_admin') == []


@pytest.mark.parametrize('level,edit,delete,lic,people', [
    ('top_admin', True, True, True, True),
    ('editor', True, False, False, False),
    ('viewer', False, False, False, False),
])
def test_permissions_per_level(level, edit, delete, lic, people):
    u = _u(level)
    assert (u.can_edit, u.can_delete, u.can_see_licenses, u.can_manage_people, u.is_admin) == \
        (edit, delete, lic, people, level == 'top_admin')


def test_switches_add_abilities_but_never_licenses_or_viewer_delete():
    e = _u('editor', {'trips_fuel', 'delete'})
    assert e.can('trips_fuel') and e.can_delete and not e.can_see_licenses and not e.is_admin
    v = _u('viewer', {'delete', 'vehicles'})
    assert not v.can_delete and v.can('vehicles') and v.can_edit
    assert v.import_targets == ['vehicles']


def test_doc_levels_per_level():
    assert doc_levels(_u('top_admin')) == ['General', 'Staff', 'Admin']
    assert doc_levels(_u('editor')) == doc_levels(_u('viewer')) == ['General', 'Staff']


def test_test_accounts_have_the_three_tiers(dbq):
    rows = {r['username']: r['role_name'] for r in dbq(
        "SELECT u.username, r.role_name FROM wsb.app_user u JOIN wsb.app_role r USING (role_id)")}
    assert rows['demo_tier1'] == rows['demo_tier1_backup'] == 'Top admin'
    assert rows['demo_editor'] == 'Staff' and rows['demo_tier2'] == 'Read-only'
    assert not [u for u, r in rows.items() if r == 'Admin']          # the middle level is gone


def test_editor_defaults(client, sign_in, dbq):
    """Tier 2: maintenance yes; vehicles, trips, fuel, documents and delete no."""
    sign_in(client, 'demo_editor')
    vid = _vid(dbq)
    assert client.get('/maintenance/new').status_code == 200
    for path in ('/vehicles/new', f'/vehicles/{vid}/edit', '/trips/new', '/fuel/new'):
        assert client.get(path).status_code == 403, path
    assert client.post(f'/vehicles/{vid}/delete').status_code == 403
    page = client.get(f'/vehicles/{vid}').get_data(as_text=True)
    assert 'Mark done' in page and 'Log service' in page
    assert f'/vehicles/{vid}/edit' not in page and 'Delete vehicle' not in page and 'Log trip' not in page
    assert 'Choose a file to upload' not in page


def test_switch_turns_on_one_ability(client, sign_in, dbq):
    _switch_on(dbq, 'demo_editor', 'trips_fuel')
    sign_in(client, 'demo_editor')
    assert client.get('/trips/new').status_code == 200 and client.get('/fuel/new').status_code == 200
    assert client.get('/vehicles/new').status_code == 403


def test_viewer_cannot_add(client, sign_in):
    sign_in(client, 'demo_tier2')
    for path in ('/vehicles/new', '/maintenance/new', '/trips/new'):
        assert client.get(path).status_code == 403
    assert 'id="add-menu"' not in client.get('/help').get_data(as_text=True)


def test_top_admin_sees_licenses(client, sign_in):
    sign_in(client, 'demo_tier1')
    assert 'DEMO-DL-' in client.get('/search?q=Patel&kind=licenses').get_data(as_text=True)


def test_top_admin_sees_admin_documents_editor_does_not(client, sign_in, dbq):
    vid = _vid(dbq)
    sign_in(client, 'demo_tier1_backup')
    assert 'DEMO-T01_title.pdf' in client.get(f'/vehicles/{vid}').get_data(as_text=True)
    sign_in(client, 'demo_editor')
    assert 'DEMO-T01_title.pdf' not in client.get(f'/vehicles/{vid}').get_data(as_text=True)


def test_topbar_shows_tier_name(client, sign_in):
    sign_in(client, 'demo_editor')
    assert 'Tier 2 · Editor' in client.get('/help').get_data(as_text=True)


def test_top_admin_sets_switches_and_it_is_logged(client, sign_in, dbq):
    uid = dbq("SELECT user_id FROM wsb.app_user WHERE username = 'demo_editor'")[0]['user_id']
    sign_in(client, 'demo_tier1')
    assert 'Extra abilities' in client.get('/admin/people').get_data(as_text=True)
    client.post(f'/admin/people/{uid}/switches', data={'perm_trips_fuel': 'on', 'perm_maintenance': 'on'})
    got = {r['permission'] for r in dbq('SELECT permission FROM wsb.app_user_permission WHERE user_id = %s', (uid,))}
    assert got == {'trips_fuel'}                      # maintenance is already in Tier 2, so not stored
    log = dbq("SELECT * FROM wsb.activity_log WHERE kind = 'access' ORDER BY activity_id DESC LIMIT 1")[0]
    assert {'field': PERMS['trips_fuel'], 'old': 'Off', 'new': 'On'} in log['details']
    client.post(f'/admin/people/{uid}/switches', data={})
    assert not dbq('SELECT 1 FROM wsb.app_user_permission WHERE user_id = %s', (uid,))


def test_only_top_admins_set_switches(client, sign_in, dbq):
    uid = dbq("SELECT user_id FROM wsb.app_user WHERE username = 'demo_tier2'")[0]['user_id']
    sign_in(client, 'demo_editor')
    assert client.post(f'/admin/people/{uid}/switches', data={'perm_delete': 'on'}).status_code == 403
    sign_in(client, 'demo_tier1')
    client.post(f'/admin/people/{uid}/switches', data={'perm_delete': 'on'})     # viewers can't get delete
    assert not dbq('SELECT 1 FROM wsb.app_user_permission WHERE user_id = %s', (uid,))
