"""Home dashboards: editors get things to act on, viewers get what's available."""


def test_editor_dashboard(client, sign_in):
    sign_in(client, 'demo_editor')
    html = client.get('/').get_data(as_text=True)
    for part in ('id="attention"', 'id="out-now"', 'id="mine"', 'data-stat="overdue">1<', 'Mark done'):
        assert part in html, part
    assert 'id="available"' not in html


def test_viewer_dashboard_is_read_only(client, sign_in, dbq):
    n = dbq("SELECT count(*) n FROM wsb.vehicle WHERE active AND status = 'Available'")[0]['n']
    sign_in(client, 'demo_tier2')
    html = client.get('/').get_data(as_text=True)
    for part in ('id="available"', 'id="out-now"', 'id="maint-due"', f'data-stat="available">{n}<'):
        assert part in html, part
    assert 'Mark done' not in html and 'id="mine"' not in html


def test_out_now_lists_trips_in_progress(client, sign_in, dbq):
    open_trips = dbq('SELECT count(*) n FROM wsb.trip WHERE end_datetime IS NULL')[0]['n']
    sign_in(client, 'demo_editor')
    assert f'data-stat="out">{open_trips}<' in client.get('/').get_data(as_text=True)


def test_my_changes_show_my_edits_only(client, sign_in, dbq):
    dbq("""INSERT INTO wsb.activity_log (user_id, full_name, kind, summary)
           SELECT user_id, full_name, 'change', 'Someone else edited X' FROM wsb.app_user WHERE username = 'demo_tier1'""")
    dbq("""INSERT INTO wsb.activity_log (user_id, full_name, kind, summary)
           SELECT user_id, full_name, 'change', 'I edited Y' FROM wsb.app_user WHERE username = 'demo_editor'""")
    sign_in(client, 'demo_editor')
    html = client.get('/').get_data(as_text=True)
    assert 'I edited Y' in html and 'Someone else edited X' not in html


def test_mark_done_from_home_returns_home(client, sign_in, dbq):
    sign_in(client, 'demo_editor')
    rid = dbq('SELECT rule_id FROM wsb.maintenance_rule ORDER BY rule_id LIMIT 1')[0]['rule_id']
    r = client.post(f'/maintenance/{rid}/done', data={'back': '/'})
    assert r.headers['Location'].endswith('/')
