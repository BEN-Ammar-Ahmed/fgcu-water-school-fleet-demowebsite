import re
from pathlib import Path

DASH = Path(__file__).resolve().parent.parent
ALLOWED = {'#f7f7f6', '#ffffff', '#fff', '#111111', '#111', '#555555', '#555', '#dcdcd8',
           '#c2261c', '#9a5b00', '#fde8e8', '#fff4e0'}


def test_topbar_shows_user_and_tier(client, sign_in):
    sign_in(client, 'demo_tier2')
    r = client.get('/help')
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert 'Campus Staff' in page and 'Tier 2' in page
    assert '+ Add' not in page and 'id="add-menu"' not in page


def test_tier1_sees_add(client, sign_in):
    sign_in(client, 'demo_tier1')
    assert 'id="add-menu"' in client.get('/help').get_data(as_text=True)


def test_no_emoji_in_templates():
    emoji = re.compile('[\U0001F000-\U0001FFFF☀-➿⭐⚓]')
    bad = [p.name for p in (DASH / 'templates').glob('*.html') if emoji.search(p.read_text(encoding='utf-8'))]
    assert bad == []


def _is_gray(h):
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return max(r, g, b) - min(r, g, b) <= 6


def test_css_has_only_allowed_colors():
    css = (DASH / 'static' / 'style.css').read_text(encoding='utf-8').lower()
    colors = set(re.findall(r'#[0-9a-f]{6}\b|#[0-9a-f]{3}\b', css))
    assert [c for c in colors if c not in ALLOWED and not _is_gray(c)] == []
    assert 'rgb(' not in css.replace('rgba(0,0,0', '').replace('rgba(0, 0, 0', '')
