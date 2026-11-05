"""Admin area: Activity page, Manage data page, and browse mode for "Open list"."""
import pytest


def _log(dbq, kind, summary, who='Demo Campus Staff', at="now()"):
    dbq(f"INSERT INTO wsb.activity_log (full_name, kind, summary, at) VALUES (%s, %s, %s, {at})", (who, kind, summary))


@pytest.mark.parametrize('path', ['/admin/activity', '/admin/data'])
def test_viewers_and_editors_cannot_open(client, sign_in, path):
    for who in ('demo_tier2', 'demo_editor'):
        sign_in(client, who)
        assert client.get(path).status_code == 403


def test_activity_newest_first_and_filters(client, sign_in, dbq):
    _log(dbq, 'view', 'Vehicle: old one', at="now() - interval '3 days'")
    _log(dbq, 'change', 'Added a trip · F-250', who='Demo Boat Captain')
    _log(dbq, 'download', 'Opened Registration')
    sign_in(client, 'demo_tier1_backup')
    page = client.get('/admin/activity').get_data(as_text=True)
    assert page.index('Opened Registration') < page.index('Added a trip') < page.index('Vehicle: old one')
    page = client.get('/admin/activity?kind=change').get_data(as_text=True)
    assert 'Added a trip' in page and 'Opened Registration' not in page
    page = client.get('/admin/activity?q=captain').get_data(as_text=True)
    assert 'Added a trip' in page and 'Opened Registration' not in page
    from datetime import date, timedelta
    page = client.get(f'/admin/activity?date_to={(date.today() - timedelta(days=1)).isoformat()}').get_data(as_text=True)
    assert 'Vehicle: old one' in page and 'Added a trip' not in page


def test_activity_paging(client, sign_in, dbq):
    dbq("INSERT INTO wsb.activity_log (full_name, kind, summary) SELECT 'Bulk', 'view', 'Row ' || g FROM generate_series(1, 130) g")
    sign_in(client, 'demo_tier1')
    first = client.get('/admin/activity').get_data(as_text=True)
    assert 'Row 130' in first and 'Row 20<' not in first and 'page=2' in first
    second = client.get('/admin/activity?page=2').get_data(as_text=True)
    assert 'Row 20<' in second and 'Row 130' not in second


def test_bad_activity_filters_do_not_crash(client, sign_in):
    sign_in(client, 'demo_tier1')
    assert client.get('/admin/activity?page=abc&date_from=nope&kind=zzz').status_code == 200


def test_manage_data_counts_and_links(client, sign_in):
    sign_in(client, 'demo_tier1_backup')
    page = client.get('/admin/data').get_data(as_text=True)
    assert 'data-count="vehicles">8<' in page and 'data-count="trips">8<' in page
    assert 'browse=1' in page and 'kind=vehicles' in page
    assert 'data-count="licenses"' not in page and 'kind=licenses' not in page
    sign_in(client, 'demo_tier1')
    page = client.get('/admin/data').get_data(as_text=True)
    assert 'Confidential' in page and 'data-count="licenses">6<' in page


@pytest.mark.parametrize('kind,label,n', [('vehicles', 'Vehicles', 8), ('trips', 'Trips', 8), ('fuel', 'Fuel', 8),
                                          ('documents', 'Documents', 16), ('drivers', 'Drivers', 6)])
def test_browse_lists_everything_of_one_kind(client, sign_in, kind, label, n):
    sign_in(client, 'demo_tier1')
    page = client.get(f'/search?kind={kind}&browse=1').get_data(as_text=True)
    assert f'{label} · {n}' in page


def test_browse_licenses_only_for_top_admin(client, sign_in):
    sign_in(client, 'demo_tier1_backup')
    r = client.get('/search?kind=licenses&browse=1')
    assert 'DEMO-DL-' not in r.get_data(as_text=True)
    sign_in(client, 'demo_tier1')
    assert 'Licenses · 6' in client.get('/search?kind=licenses&browse=1').get_data(as_text=True)


def test_browse_all_is_not_allowed(client, sign_in):
    sign_in(client, 'demo_tier2')
    assert client.get('/search?browse=1').status_code == 302
