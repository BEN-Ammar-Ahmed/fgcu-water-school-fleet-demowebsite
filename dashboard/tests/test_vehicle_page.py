def _t01(dbq):
    return dbq("SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = 'DEMO-T01'")[0]['vehicle_id']


def test_vehicle_page_sections(client, sign_in, dbq):
    sign_in(client, 'demo_tier2')
    page = client.get(f'/vehicles/{_t01(dbq)}').get_data(as_text=True)
    for sid in ('details', 'maintenance', 'trips', 'fuel', 'costs', 'documents'):
        assert f'id="{sid}"' in page, sid
    for text in ('Matlacha Boat Ramp', 'Sample Gas C', 'Brake Service', 'FY26-27', 'Alex Rivera'):
        assert text in page, text
    assert 'arivera@example.edu' not in page


def test_tier2_hides_admin_docs_and_buttons(client, sign_in, dbq):
    vid = _t01(dbq)
    sign_in(client, 'demo_tier2')
    page = client.get(f'/vehicles/{vid}').get_data(as_text=True)
    assert '/secure/docs/DEMO-T01_title.pdf' not in page and '>Title<' not in page
    assert 'restricted' not in page   # not even a count of hidden documents (spec anti-goal)
    assert f'/vehicles/{vid}/edit' not in page and 'Delete vehicle' not in page


def test_tier1_sees_edit_delete(client, sign_in, dbq):
    vid = _t01(dbq)
    sign_in(client, 'demo_tier1')
    page = client.get(f'/vehicles/{vid}').get_data(as_text=True)
    assert f'/vehicles/{vid}/edit' in page and 'Delete vehicle' in page
    assert '>Title<' in page


def test_vehicle_without_records_renders(client, sign_in, dbq):
    vid = dbq("SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = 'DEMO-G01'")[0]['vehicle_id']
    sign_in(client, 'demo_tier2')
    r = client.get(f'/vehicles/{vid}')
    assert r.status_code == 200 and 'No trips yet' in r.get_data(as_text=True)


def test_vehicle_name_is_its_own_field(client, sign_in, dbq):
    """Names come from the Name field, not from notes (11_vehicle_name.sql)."""
    vid = dbq("SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = 'DEMO-B02'")[0]['vehicle_id']
    assert dbq('SELECT name FROM wsb.vehicle WHERE vehicle_id = %s', (vid,))[0]['name'] == 'Boston Whaler 170 Montauk'
    dbq("UPDATE wsb.vehicle SET notes = 'Needs new bilge pump' WHERE vehicle_id = %s", (vid,))
    sign_in(client, 'demo_tier2')
    html = client.get(f'/vehicles/{vid}').get_data(as_text=True)
    assert 'Boston Whaler 170 Montauk' in html and '<title>Needs new bilge pump' not in html
    dbq("UPDATE wsb.vehicle SET name = NULL WHERE vehicle_id = %s", (vid,))
    assert '2018 Boston Whaler 170 Montauk' in client.get(f'/vehicles/{vid}').get_data(as_text=True)


def test_edit_page_has_name_field(client, sign_in):
    sign_in(client, 'demo_tier1')
    assert 'name="name"' in client.get('/vehicles/1/edit').get_data(as_text=True)
