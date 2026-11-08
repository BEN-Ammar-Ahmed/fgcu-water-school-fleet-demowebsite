"""Reservations: the separate request site (reserve_app.py) -> thank-you page and email -> the fleet site's inbox
(reservations.py) -> approve / deny / ask for info (by email) / edit / cancel. Tables: 13 and 15 in sql_postgres."""
import datetime as dt

import pytest

import reservation_core as rc

SOON = dt.datetime.now().replace(second=0, microsecond=0) + dt.timedelta(days=3)
F = '%Y-%m-%dT%H:%M'


def _form(**over):
    f = {'requester_name': 'Jamie Student', 'requester_email': 'jamie@example.edu', 'uin': '81234567',
         'phone': '239-555-0100', 'pickup_at': SOON.strftime(F),
         'return_at': (SOON + dt.timedelta(hours=6)).strftime(F),
         'destination': 'Matlacha Boat Ramp', 'purpose': 'Water sampling', 'vehicle_type': 'Boat',
         'requested_vehicle_id': '', 'passengers': '3', 'drivers': 'Ana Lee, alee@example.edu\nBo Park', 'notes': ''}
    f.update(over)
    return f


def _vid(dbq, tag='DEMO-B01'):
    return dbq('SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = %s', (tag,))[0]['vehicle_id']


def _send(reserve, dbq, **over):
    r = reserve.post('/request', data=_form(**over))
    assert r.status_code == 302, r.get_data(as_text=True)[:3000]
    assert r.headers['Location'].endswith('/thanks')
    return dbq('SELECT max(reservation_id) id FROM wsb.reservation')[0]['id']


def _status(dbq, rid):
    return dbq('SELECT status FROM wsb.reservation WHERE reservation_id = %s', (rid,))[0]['status']


def _emails(dbq, rid):
    return dbq('SELECT to_email, subject, body, sent_at FROM wsb.email_outbox WHERE reservation_id = %s '
               'ORDER BY email_id', (rid,))


# --- the request site ------------------------------------------------------------------------------------
def test_request_site_needs_no_account_and_shows_no_private_data(reserve, dbq):
    page = reserve.get('/').get_data(as_text=True)
    assert 'Request a vehicle' in page and 'Show free vehicles' in page and 'class="site-footer"' in page
    page = reserve.get(f"/?pickup_at={SOON.strftime(F)}&return_at={(SOON + dt.timedelta(hours=6)).strftime(F)}"
                       ).get_data(as_text=True)
    assert 'Primary research skiff' in page and 'Request this one' in page
    assert 'Boston Whaler' not in page                      # In Maintenance: not offered to requesters
    private = [x for r in dbq('SELECT vin, license_plate FROM wsb.vehicle') for x in r.values() if x]
    assert private and not [x for x in private if x in page]   # no VINs or plates


def test_type_filter_and_bad_times(reserve):
    end = (SOON + dt.timedelta(hours=6)).strftime(F)
    page = reserve.get(f'/?pickup_at={SOON.strftime(F)}&return_at={end}&type=Car').get_data(as_text=True)
    assert 'Toyota Camry' in page and 'Primary research skiff' not in page
    page = reserve.get(f'/?pickup_at={end}&return_at={SOON.strftime(F)}').get_data(as_text=True)
    assert 'Return must be after pick up.' in page


def test_send_a_request_shows_thank_you_page(reserve, dbq):
    vid = _vid(dbq)
    rid = _send(reserve, dbq, requested_vehicle_id=str(vid))
    r = dbq('SELECT * FROM wsb.reservation WHERE reservation_id = %s', (rid,))[0]
    assert r['status'] == 'Pending' and r['requested_vehicle_id'] == vid and r['vehicle_id'] is None
    assert r['requested_by'] is None and r['uin'] == '81234567'
    assert r['drivers'] == [{'name': 'Ana Lee', 'email': 'alee@example.edu'}, {'name': 'Bo Park', 'email': ''}]
    page = reserve.get('/thanks').get_data(as_text=True)
    assert 'Thank you, Jamie!' in page and 'Primary research skiff' in page and 'Pending review' in page
    assert f'#{rid}' in page and 'jamie@example.edu' in page and 'reply to that email' in page


def test_thanks_without_a_request_goes_to_start(reserve):
    assert reserve.get('/thanks').headers['Location'].endswith('/')


def test_no_private_links_any_more(reserve, dbq):
    _send(reserve, dbq)
    token = dbq('SELECT public_token FROM wsb.reservation')[0]['public_token']
    assert reserve.get(f'/r/{token}').status_code == 404
    assert all(token not in m['body'] for m in dbq('SELECT body FROM wsb.email_outbox'))


def test_request_emails_requester_and_every_approver(reserve, dbq):
    rid = _send(reserve, dbq)
    mails = _emails(dbq, rid)
    assert mails[0]['to_email'] == 'jamie@example.edu' and 'Thank you for your vehicle request' in mails[0]['subject']
    assert 'pending review' in mails[0]['body'] and 'UIN: 81234567' in mails[0]['body']
    assert 'reply to this email' in mails[0]['body']
    to = [m['to_email'] for m in mails[1:]]
    assert {'fleet.manager@example.edu', 'fleet.backup@example.edu'} <= set(to)
    assert 'editor.staff@example.edu' not in to
    assert all(f'/reservations/{rid}' in m['body'] for m in mails[1:])
    assert all(m['sent_at'] is None for m in mails)          # no SMTP in tests: they wait in the outbox


@pytest.mark.parametrize('over,msg', [
    ({'uin': 'abc'}, 'UIN must be numbers only.'),
    ({'requester_email': 'nope'}, 'Email must look like'),
    ({'phone': '12'}, 'Phone needs at least 7 digits.'),
    ({'return_at': SOON.strftime(F)}, 'Return must be after pick up.'),
    ({'pickup_at': '2020-01-01T08:00', 'return_at': '2020-01-01T10:00'}, "Pick up can&#39;t be in the past."),
    ({'destination': ''}, 'Destination is required.'),
    ({'drivers': 'Ana, not-an-email'}, 'does not look like an email'),
])
def test_bad_requests_are_explained(reserve, dbq, over, msg):
    r = reserve.post('/request', data=_form(**over))
    assert r.status_code == 200 and msg in r.get_data(as_text=True)
    assert dbq('SELECT count(*) n FROM wsb.reservation')[0]['n'] == 0


def test_robots_and_floods_are_stopped(reserve, dbq):
    assert reserve.post('/request', data=_form(website='http://spam')).status_code == 400
    for i in range(5):
        _send(reserve, dbq, pickup_at=(SOON + dt.timedelta(days=i)).strftime(F),
              return_at=(SOON + dt.timedelta(days=i, hours=2)).strftime(F))
    assert reserve.post('/request', data=_form()).status_code == 429       # 5 a day per email


def test_the_two_sites_use_different_cookies(reserve, app_module):
    import reserve_app
    assert reserve_app.app.config['SESSION_COOKIE_NAME'] != app_module.app.config.get('SESSION_COOKIE_NAME', 'session')


# --- the inbox on the fleet site ---------------------------------------------------------------------------
def test_inbox_is_for_approvers_only(reserve, client, sign_in, dbq):
    rid = _send(reserve, dbq)
    sign_in(client, 'demo_tier2')
    assert client.get('/reservations').status_code == 403
    assert client.get(f'/reservations/{rid}').status_code == 403
    sign_in(client, 'demo_editor')
    assert client.post(f'/reservations/{rid}/decide', data={'action': 'deny', 'note': 'x'}).status_code == 403
    assert client.get(f'/reservations/{rid}/edit').status_code == 403
    sign_in(client, 'demo_tier1')
    page = client.get('/reservations').get_data(as_text=True)
    assert f'/reservations/{rid}"' in page and 'Jamie Student' in page and 'Pending · 1' in page
    assert 'title="Requests waiting for a decision">1<' in page


def test_approve_switch_adds_someone_to_the_inbox(reserve, client, sign_in, dbq):
    dbq("""INSERT INTO wsb.app_user_permission (user_id, permission)
           SELECT user_id, 'approve' FROM wsb.app_user WHERE username = 'demo_editor'""")
    rid = _send(reserve, dbq)
    assert 'editor.staff@example.edu' in [m['to_email'] for m in _emails(dbq, rid)]
    sign_in(client, 'demo_editor')
    assert f'/reservations/{rid}"' in client.get('/reservations').get_data(as_text=True)


def test_picked_vehicle_is_preselected_and_approver_can_change_it(reserve, client, sign_in, dbq):
    b1, c1 = _vid(dbq), _vid(dbq, 'DEMO-C01')
    rid = _send(reserve, dbq, requested_vehicle_id=str(b1))
    sign_in(client, 'demo_tier1')
    page = client.get(f'/reservations/{rid}').get_data(as_text=True)
    assert f'<option value="{b1}"  selected>' in page and 'The one they asked for is selected' in page
    client.post(f'/reservations/{rid}/decide', data={'action': 'approve', 'vehicle_id': c1, 'note': 'Boat is out.'})
    row = dbq('SELECT status, vehicle_id, requested_vehicle_id FROM wsb.reservation WHERE reservation_id = %s', (rid,))[0]
    assert row == {'status': 'Approved', 'vehicle_id': c1, 'requested_vehicle_id': b1}
    last = _emails(dbq, rid)[-1]
    assert last['to_email'] == 'jamie@example.edu' and 'approved' in last['subject']
    assert 'Boat is out.' in last['body'] and 'Vehicle given: 2019 Toyota Camry' in last['body']
    log = dbq("SELECT * FROM wsb.activity_log WHERE kind = 'reservation' ORDER BY activity_id DESC LIMIT 1")[0]
    assert f'Approved vehicle request #{rid}' in log['summary']
    assert {'field': 'Vehicle', 'old': 'Primary research skiff', 'new': '2019 Toyota Camry'} in log['details']


def test_approve_needs_a_vehicle_and_decided_stays_decided(reserve, client, sign_in, dbq):
    rid = _send(reserve, dbq)
    sign_in(client, 'demo_tier1')
    client.post(f'/reservations/{rid}/decide', data={'action': 'approve'})
    assert _status(dbq, rid) == 'Pending'
    client.post(f'/reservations/{rid}/decide', data={'action': 'approve', 'vehicle_id': _vid(dbq)})
    client.post(f'/reservations/{rid}/decide', data={'action': 'deny', 'note': 'changed my mind'})
    assert _status(dbq, rid) == 'Approved'


def test_booked_vehicles_disappear_and_double_booking_is_blocked(reserve, client, sign_in, dbq):
    vid = _vid(dbq)
    a = _send(reserve, dbq)
    sign_in(client, 'demo_tier1')
    client.post(f'/reservations/{a}/decide', data={'action': 'approve', 'vehicle_id': vid})
    start, end = (SOON + dt.timedelta(hours=2)).strftime(F), (SOON + dt.timedelta(hours=9)).strftime(F)
    page = reserve.get(f'/?pickup_at={start}&return_at={end}').get_data(as_text=True)
    assert 'Primary research skiff' not in page                                 # no longer free then
    r = reserve.post('/request', data=_form(pickup_at=start, return_at=end, requested_vehicle_id=str(vid)))
    assert r.status_code == 200 and 'one of the choices' in r.get_data(as_text=True)
    b = _send(reserve, dbq, pickup_at=start, return_at=end)
    assert 'already reserved' in client.get(f'/reservations/{b}').get_data(as_text=True)
    r = client.post(f'/reservations/{b}/decide', data={'action': 'approve', 'vehicle_id': vid}, follow_redirects=True)
    assert 'already reserved for part of that time' in r.get_data(as_text=True)
    assert _status(dbq, b) == 'Pending'


def test_deny_needs_a_reason(reserve, client, sign_in, dbq):
    rid = _send(reserve, dbq)
    sign_in(client, 'demo_tier1')
    client.post(f'/reservations/{rid}/decide', data={'action': 'deny', 'note': ''})
    assert _status(dbq, rid) == 'Pending'
    client.post(f'/reservations/{rid}/decide', data={'action': 'deny', 'note': 'No boats that weekend.'})
    assert _status(dbq, rid) == 'Denied'
    last = _emails(dbq, rid)[-1]
    assert 'denied' in last['subject'] and 'Reason: No boats that weekend.' in last['body']


def test_needs_info_by_email_then_approver_edits_and_approves(reserve, client, sign_in, dbq):
    rid = _send(reserve, dbq)
    sign_in(client, 'demo_tier1')
    client.post(f'/reservations/{rid}/decide', data={'action': 'info', 'note': 'How many passengers, exactly?'})
    assert _status(dbq, rid) == 'Needs info'
    last = _emails(dbq, rid)[-1]
    assert 'more information' in last['subject'] and 'reply to this email' in last['body'].lower()
    assert 'How many passengers, exactly?' in last['body'] and '/r/' not in last['body']

    page = client.get(f'/reservations/{rid}').get_data(as_text=True)
    assert "Waiting for the requester's reply by email" in page and 'Edit details' in page
    form = client.get(f'/reservations/{rid}/edit').get_data(as_text=True)
    assert 'You asked: How many passengers, exactly?' in form and 'Ana Lee, alee@example.edu' in form
    client.post(f'/reservations/{rid}/edit', data=_form(passengers='5'))
    row = dbq('SELECT status, passengers FROM wsb.reservation WHERE reservation_id = %s', (rid,))[0]
    assert row == {'status': 'Pending', 'passengers': 5}
    assert dbq("SELECT action FROM wsb.reservation_event WHERE reservation_id = %s ORDER BY event_id DESC LIMIT 1",
               (rid,))[0]['action'] == 'Details updated'
    client.post(f'/reservations/{rid}/decide', data={'action': 'approve', 'vehicle_id': _vid(dbq)})
    assert _status(dbq, rid) == 'Approved'


def test_approver_cancels_and_requester_is_told(reserve, client, sign_in, dbq):
    rid = _send(reserve, dbq)
    sign_in(client, 'demo_tier1')
    client.post(f'/reservations/{rid}/decide', data={'action': 'approve', 'vehicle_id': _vid(dbq)})
    assert 'Cancel this reservation' in client.get(f'/reservations/{rid}').get_data(as_text=True)
    client.post(f'/reservations/{rid}/decide', data={'action': 'cancel', 'note': 'The boat needs a repair.'})
    assert _status(dbq, rid) == 'Cancelled'
    last = _emails(dbq, rid)[-1]
    assert last['to_email'] == 'jamie@example.edu' and 'cancelled' in last['subject']
    assert 'The boat needs a repair.' in last['body']
    assert client.get(f'/reservations/{rid}/edit').status_code == 302          # nothing to edit any more


def test_parse_drivers():
    d, e = rc.parse_drivers('Ana Lee, alee@x.edu\n\nBo Park\nCy; bad-email')
    assert d == [{'name': 'Ana Lee', 'email': 'alee@x.edu'}, {'name': 'Bo Park', 'email': ''},
                 {'name': 'Cy', 'email': 'bad-email'}]
    assert len(e) == 1 and 'bad-email' in e[0]
    assert rc.drivers_text(d[:2]) == 'Ana Lee, alee@x.edu\nBo Park'


def test_mailer_does_nothing_without_smtp(monkeypatch):
    import mailer
    monkeypatch.delenv('SMTP_HOST', raising=False)
    assert mailer.configured() is False
    assert mailer.send_waiting(lambda *a, **k: 1 / 0, None) == 0
