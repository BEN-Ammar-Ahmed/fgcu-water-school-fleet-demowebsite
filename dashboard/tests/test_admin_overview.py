"""Admin area: who can get in, and the Overview page."""
import pytest


@pytest.mark.parametrize('who,code', [('demo_tier2', 403), ('demo_editor', 403), ('demo_tier1_backup', 200), ('demo_tier1', 200)])
def test_only_admins_get_in(client, sign_in, who, code):
    sign_in(client, who)
    assert client.get('/admin').status_code == code


def test_signed_out_goes_to_login(client):
    r = client.get('/admin')
    assert r.status_code == 302 and '/login' in r.headers['Location']


def test_admin_link_only_for_admins(client, sign_in):
    sign_in(client, 'demo_editor')
    assert 'href="/admin"' not in client.get('/help').get_data(as_text=True)
    sign_in(client, 'demo_tier1_backup')
    assert 'href="/admin"' in client.get('/help').get_data(as_text=True)


def test_overview_cards_and_numbers(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    page = client.get('/admin').get_data(as_text=True)
    for label in ('Active vehicles', 'Trips this month', 'Fuel this month', 'Cost this fiscal year',
                  'Latest activity', 'Needs attention', 'Online now'):
        assert label in page, label
    assert 'data-stat="vehicles">8<' in page
    assert 'data-stat="overdue">1<' in page and 'data-stat="soon">' in page and 'data-stat="expiring">' in page


def test_overview_is_decluttered(client, sign_in):
    sign_in(client, 'demo_tier1')
    page = client.get('/admin').get_data(as_text=True)
    for gone in ('Most used vehicles', 'People with access', 'data-stat="people"'):
        assert gone not in page, gone
    assert page.index('id="activity"') < page.index('id="attention"') < page.index('id="online"')


def test_overview_shows_edit_details(client, sign_in, dbq):
    dbq("""INSERT INTO wsb.activity_log (full_name, kind, summary, details) VALUES
           ('Fleet Manager', 'change', 'Edited vehicle X', '[{"field": "Mileage", "old": "41,200", "new": "42,050"}]')""")
    sign_in(client, 'demo_tier1')
    assert 'Mileage: 41,200 → 42,050' in client.get('/admin').get_data(as_text=True)


def test_people_page_shows_level_counts(client, sign_in, dbq):
    top = dbq("""SELECT count(*) n FROM wsb.app_user u JOIN wsb.app_role r USING (role_id)
                 WHERE u.active AND r.role_name = 'Top admin'""")[0]['n']
    sign_in(client, 'demo_tier1')
    page = client.get('/admin/people').get_data(as_text=True)
    assert 'data-levels' in page and f'<b>{top}</b> Tier 1 · Top admin' in page


def test_signed_in_now_list(client, sign_in, dbq):
    dbq("UPDATE wsb.app_user SET last_seen = now() - interval '5 minutes', last_page = 'Search: Sea Ark' WHERE username = 'demo_editor'")
    dbq("UPDATE wsb.app_user SET last_seen = now() - interval '20 minutes', last_page = 'Help' WHERE username = 'demo_tier2'")
    sign_in(client, 'demo_tier1')
    page = client.get('/admin').get_data(as_text=True)
    online = page[page.index('id="online"'):]
    online = online[:online.index('</section>')]
    assert 'Boat Captain' in online and 'Search: Sea Ark' in online
    assert 'Campus Staff' not in online


def test_recent_activity_on_overview(client, sign_in, dbq):
    client.post('/login', data={'password': 'test-password-1', 'username': 'campus.staff@example.edu'})
    sign_in(client, 'demo_tier1')
    page = client.get('/admin').get_data(as_text=True)
    assert 'Campus Staff' in page and 'Signed in' in page
