from pathlib import Path

DASH = Path(__file__).resolve().parent.parent


def test_help_sections(client, sign_in):
    sign_in(client, 'demo_tier2')
    r = client.get('/help')
    page = r.get_data(as_text=True)
    assert r.status_code == 200
    for anchor in ('search', 'tiers', 'adding', 'access'):
        assert f'id="{anchor}"' in page, anchor
    assert 'Top admin' in page and 'Tier 2 · can edit' in page and 'Tier 2 · view only' in page


def test_roles_redirects(client, sign_in):
    sign_in(client, 'demo_tier2')
    r = client.get('/roles')
    assert r.status_code == 301 and r.headers['Location'].endswith('/help#tiers')


def test_pages_still_work(client, sign_in):
    for who in ('demo_tier1', 'demo_tier2'):
        sign_in(client, who)
        for path in ('/maintenance', '/maintenance?show=all', '/documents'):
            assert client.get(path).status_code == 200, (who, path)


def test_tier2_sees_no_edit_controls_on_lists(client, sign_in):
    sign_in(client, 'demo_tier2')
    assert 'Mark done' not in client.get('/maintenance').get_data(as_text=True)
    assert 'Delete' not in client.get('/documents').get_data(as_text=True)


def test_transitional_helper_removed():
    assert not (DASH / 'templates' / 'roles.html').exists()
    uses = [p.name for p in (DASH / 'templates').glob('*.html') if "can('" in p.read_text(encoding='utf-8')]
    assert uses == []
    assert 'def _can(' not in (DASH / 'app.py').read_text(encoding='utf-8')


def test_readme_covers_maintainers():
    text = (DASH / 'README.md').read_text(encoding='utf-8')
    for needle in ('07_web_access.sql', 'pytest', 'sign_in_email', 'docker run', 'DATABASE_URL'):
        assert needle in text, needle
