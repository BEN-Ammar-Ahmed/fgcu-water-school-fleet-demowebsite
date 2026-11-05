def _t01(dbq):
    return dbq("SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = 'DEMO-T01'")[0]['vehicle_id']


def test_home_closed_state(client, sign_in):
    sign_in(client, 'demo_tier2')
    r = client.get('/')
    page = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'id="search-open"' in page and 'aria-label="Search"' in page
    assert '1 overdue' in page and '1 due soon' in page
    assert 'class="group"' not in page


def test_search_page_groups(client, sign_in, dbq):
    sign_in(client, 'demo_tier2')
    page = client.get('/search?q=F-250').get_data(as_text=True)
    assert 'Vehicles · 1' in page
    assert f'/vehicles/{_t01(dbq)}' in page
    assert 'value="F-250"' in page


def test_kind_chip_narrows(client, sign_in):
    sign_in(client, 'demo_tier2')
    page = client.get('/search?q=DEMO-T01&kind=trips').get_data(as_text=True)
    assert 'Trips ·' in page and 'Vehicles ·' not in page


def test_showing_n_of_total(client, sign_in, dbq):
    dbq("""INSERT INTO wsb.trip (vehicle_id, driver_id, start_datetime, destination)
           SELECT v.vehicle_id, d.driver_id, timestamp '2025-01-01' + g * interval '1 day', 'Bulk trip'
           FROM wsb.vehicle v, wsb.driver d, generate_series(1, 60) g
           WHERE v.asset_number = 'DEMO-T01' AND d.email = 'arivera@example.edu'""")
    sign_in(client, 'demo_tier2')
    page = client.get('/search?q=DEMO-T01&kind=trips').get_data(as_text=True)
    assert 'showing 50 of 63' in page


def test_tier2_license_search_hidden(client, sign_in):
    sign_in(client, 'demo_tier2')
    page = client.get('/search?q=Patel&kind=licenses').get_data(as_text=True)
    assert 'Licenses ·' not in page and 'DEMO-DL-' not in page
    assert 'kind=licenses' not in page
    sign_in(client, 'demo_tier1')   # only top admins see licenses
    page = client.get('/search?q=Patel&kind=licenses').get_data(as_text=True)
    assert 'DEMO-DL-' in page


def test_trip_filter_row(client, sign_in):
    sign_in(client, 'demo_tier2')
    page = client.get('/search?q=DEMO-T01&kind=trips&date_from=2026-10-01&date_to=2026-10-31').get_data(as_text=True)
    assert 'Trips · 2' in page and 'name="date_from"' in page and 'value="2026-10-01"' in page


def test_bad_filter_values_do_not_crash(client, sign_in):
    sign_in(client, 'demo_tier2')
    assert client.get('/search?q=x&kind=trips&date_from=notadate&vehicle_id=abc').status_code == 200


def test_old_vehicles_url_redirects(client, sign_in):
    sign_in(client, 'demo_tier2')
    r = client.get('/vehicles?type=Boat')
    assert r.status_code == 302
    loc = r.headers['Location']
    assert loc.startswith('/search') and 'kind=vehicles' in loc and 'vehicle_type=Boat' in loc
