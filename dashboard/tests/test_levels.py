"""The four access levels: Top admin, Admin, Tier 2 can edit, Tier 2 view only."""
import pytest

from tiers import LEVEL_LABELS, CurrentUser, doc_levels, level_for_role


def _u(level):
    return CurrentUser(user_id=1, username='u', full_name='U', email=None, level=level)


def _vid(dbq, tag='DEMO-T01'):
    return dbq('SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = %s', (tag,))[0]['vehicle_id']


def test_level_mapping_and_labels():
    assert [level_for_role(r) for r in ('Top admin', 'Admin', 'Staff', 'Read-only', 'anything')] == \
        ['top_admin', 'admin', 'editor', 'viewer', 'viewer']
    assert [LEVEL_LABELS[l] for l in ('top_admin', 'admin', 'editor', 'viewer')] == \
        ['Top admin', 'Admin', 'Tier 2 · can edit', 'Tier 2 · view only']
    assert _u('editor').tier_label == 'Tier 2 · can edit'


@pytest.mark.parametrize('level,edit,delete,lic,people,admins', [
    ('top_admin', True, True, True, True, True),
    ('admin', True, True, False, True, False),
    ('editor', True, False, False, False, False),
    ('viewer', False, False, False, False, False),
])
def test_permissions_per_level(level, edit, delete, lic, people, admins):
    u = _u(level)
    assert (u.can_edit, u.can_delete, u.can_see_licenses, u.can_manage_people, u.can_manage_admins) == \
        (edit, delete, lic, people, admins)
    assert u.is_admin == (level in ('top_admin', 'admin'))


def test_doc_levels_per_level():
    assert doc_levels(_u('top_admin')) == doc_levels(_u('admin')) == ['General', 'Staff', 'Admin']
    assert doc_levels(_u('editor')) == doc_levels(_u('viewer')) == ['General', 'Staff']


def test_demo_users_have_the_four_levels(dbq):
    rows = {r['username']: r['role_name'] for r in dbq(
        "SELECT u.username, r.role_name FROM wsb.app_user u JOIN wsb.app_role r USING (role_id)")}
    assert rows['demo_tier1'] == 'Top admin' and rows['demo_tier1_backup'] == 'Admin'
    assert rows['demo_editor'] == 'Staff' and rows['demo_tier2'] == 'Read-only'


def test_editor_can_add_but_not_delete(client, sign_in, dbq):
    sign_in(client, 'demo_editor')
    vid = _vid(dbq)
    assert client.get('/vehicles/new').status_code == 200
    assert client.post(f'/vehicles/{vid}/delete').status_code == 403
    rid = dbq('SELECT rule_id FROM wsb.maintenance_rule WHERE vehicle_id = %s LIMIT 1', (vid,))[0]['rule_id']
    assert client.post(f'/rules/{rid}/delete').status_code == 403
    did = dbq("SELECT document_id FROM wsb.vehicle_document WHERE access_level = 'General' LIMIT 1")[0]['document_id']
    assert client.post(f'/documents/{did}/delete').status_code == 403
    page = client.get(f'/vehicles/{vid}').get_data(as_text=True)
    assert f'/vehicles/{vid}/edit' in page and 'Delete vehicle' not in page


def test_viewer_cannot_add(client, sign_in):
    sign_in(client, 'demo_tier2')
    assert client.get('/vehicles/new').status_code == 403


def test_admin_has_no_confidential_access(client, sign_in, dbq):
    did = dbq("SELECT driver_id FROM wsb.driver WHERE email = 'spatel@example.edu'")[0]['driver_id']
    sign_in(client, 'demo_tier1_backup')
    assert client.get(f'/drivers/{did}').status_code == 403
    page = client.get('/search?q=Patel').get_data(as_text=True)
    assert 'DEMO-DL-' not in page and 'Licenses ·' not in page
    assert 'License number' not in client.get('/drivers/new').get_data(as_text=True)


def test_top_admin_sees_licenses(client, sign_in):
    sign_in(client, 'demo_tier1')
    assert 'DEMO-DL-' in client.get('/search?q=Patel&kind=licenses').get_data(as_text=True)


def test_admin_sees_admin_documents_editor_does_not(client, sign_in, dbq):
    vid = _vid(dbq)
    sign_in(client, 'demo_tier1_backup')
    assert 'DEMO-T01_title.pdf' in client.get(f'/vehicles/{vid}').get_data(as_text=True)
    sign_in(client, 'demo_editor')
    assert 'DEMO-T01_title.pdf' not in client.get(f'/vehicles/{vid}').get_data(as_text=True)


def test_topbar_shows_level_name(client, sign_in):
    sign_in(client, 'demo_editor')
    assert 'Tier 2 · can edit' in client.get('/help').get_data(as_text=True)
