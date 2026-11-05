import pytest


@pytest.mark.parametrize('who', ['demo_tier1', 'demo_tier2'])
def test_main_pages_render(client, sign_in, dbq, who):
    sign_in(client, who)
    vid = dbq("SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = 'DEMO-T01'")[0]['vehicle_id']
    for path in ['/', f'/vehicles/{vid}', '/maintenance', '/documents']:
        r = client.get(path, follow_redirects=True)
        assert r.status_code == 200, path
