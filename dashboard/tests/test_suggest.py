"""GET /suggest: grouped suggestions with the same access rules as search."""
import pytest

import suggest as suggest_mod


def _get(client, field, text):
    r = client.get('/suggest', query_string={'field': field, 'q': text})
    assert r.status_code == 200
    return r.get_json()


def _labels(data):
    return [i['label'] for g in data['groups'] for i in g['items'] if not i.get('all')]


@pytest.fixture(autouse=True)
def fresh_trgm_check():
    suggest_mod.TRGM_SCHEMA = None
    yield
    suggest_mod.TRGM_SCHEMA = None


def test_short_or_unknown_field_is_empty(client, sign_in):
    sign_in(client, 'demo_tier1')
    assert _get(client, 'nope', 'ford') == {'groups': [], 'did_you_mean': None}
    assert _get(client, 'search', 'f') == {'groups': [], 'did_you_mean': None}


def test_signed_out_cannot_use_it(client):
    assert client.get('/suggest?field=search&q=ford').status_code in (302, 401, 403)


def test_search_suggests_vehicles_first(client, sign_in):
    sign_in(client, 'demo_tier2')
    data = _get(client, 'search', 'F-25')
    first = data['groups'][0]
    assert first['label'] == 'Vehicles' and first['items'][0]['url'].startswith('/vehicles/')
    assert data['groups'][-1]['items'][-1]['label'] == 'See all results'


def test_multi_word_matches_each_word(client, sign_in):
    sign_in(client, 'demo_tier2')
    assert any('Camry' in l for l in _labels(_get(client, 'search', 'toyota cam')))


def test_search_never_returns_licenses(client, sign_in):
    sign_in(client, 'demo_tier1')
    data = _get(client, 'search', 'DEMO-DL')
    assert not any('DEMO-DL' in str(i) for g in data['groups'] for i in g['items'] if not i.get('all'))


def test_drivers_hidden_from_non_admins(client, sign_in):
    sign_in(client, 'demo_editor')
    assert 'Drivers' not in [g['label'] for g in _get(client, 'search', 'rivera')['groups']]
    sign_in(client, 'demo_tier1')
    assert 'Drivers' in [g['label'] for g in _get(client, 'search', 'rivera')['groups']]


def test_people_and_activity_admin_only(client, sign_in):
    sign_in(client, 'demo_editor')
    assert _get(client, 'people', 'demo')['groups'] == []
    assert _get(client, 'activity', 'demo')['groups'] == []
    sign_in(client, 'demo_tier1')
    assert 'Demo Boat Captain' in _labels(_get(client, 'people', 'boat'))


def test_viewer_gets_no_form_suggestions(client, sign_in):
    sign_in(client, 'demo_tier2')
    assert _get(client, 'vendor', 'sample')['groups'] == []


def test_vendor_values_come_from_db(client, sign_in):
    sign_in(client, 'demo_tier1')
    assert 'Sample Marina' in _labels(_get(client, 'vendor', 'sample ma'))


def test_form_vehicle_gives_ids(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    items = _get(client, 'vehicle', 'camry')['groups'][0]['items']
    vid = dbq("SELECT vehicle_id FROM wsb.vehicle WHERE model = 'Camry'")[0]['vehicle_id']
    assert items[0]['value'] == str(vid)


def test_like_wildcards_are_literal(client, sign_in):
    sign_in(client, 'demo_tier1')
    assert _labels(_get(client, 'search', '%_')) == []
    assert _get(client, 'search', "o'\\")['groups'] is not None


def test_typo_close_match(client, sign_in):
    sign_in(client, 'demo_tier1')
    data = _get(client, 'driver', 'rivra')
    assert data['groups'][-1]['label'] == 'Close matches' and 'Alex Rivera' in _labels(data)


def test_did_you_mean(client, sign_in):
    sign_in(client, 'demo_tier2')
    assert _get(client, 'search', 'toyta')['did_you_mean'] in ('Toyota', 'Toyota Camry')


def test_works_without_trgm(client, sign_in):
    sign_in(client, 'demo_tier1')
    suggest_mod.TRGM_SCHEMA = ''
    assert _get(client, 'driver', 'rivra') == {'groups': [], 'did_you_mean': None}
    assert 'Alex Rivera' in _labels(_get(client, 'driver', 'rive'))


def test_suggest_not_logged(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    n = dbq('SELECT count(*) n FROM wsb.activity_log')[0]['n']
    for t in ('fo', 'for', 'ford'):
        _get(client, 'search', t)
    assert dbq('SELECT count(*) n FROM wsb.activity_log')[0]['n'] == n


def test_at_most_8_items(client, sign_in):
    sign_in(client, 'demo_tier1')
    assert len(_labels(_get(client, 'search', 'de'))) <= 8
