"""Vehicle reservations: request -> inbox -> approve / deny / ask for info -> emails (13_reservations.sql)."""
import datetime as dt

import pytest

import reservations

SOON = dt.datetime.now().replace(second=0, microsecond=0) + dt.timedelta(days=3)


def _form(**over):
    f = {'requester_name': 'Campus Staff', 'requester_email': 'campus.staff@example.edu', 'uin': '81234567',
         'phone': '239-555-0100', 'pickup_at': SOON.strftime('%Y-%m-%dT%H:%M'),
         'return_at': (SOON + dt.timedelta(hours=6)).strftime('%Y-%m-%dT%H:%M'),
         'destination': 'Matlacha Boat Ramp', 'purpose': 'Water sampling', 'vehicle_type': 'Boat',
         'passengers': '3', 'drivers': 'Ana Lee, alee@example.edu\nBo Park', 'notes': ''}
    f.update(over)
    return f


def _request(client, sign_in, dbq, who='demo_tier2', **over):
    sign_in(client, who)
    r = client.post('/reserve', data=_form(**over))
    assert r.status_code == 302, r.get_data(as_text=True)[:2000]
    return dbq('SELECT max(reservation_id) id FROM wsb.reservation')[0]['id']


def _boat(dbq, tag='DEMO-B01'):
    return dbq('SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = %s', (tag,))[0]['vehicle_id']


def _emails(dbq, rid):
    return dbq('SELECT to_email, subject, body, sent_at FROM wsb.email_outbox WHERE reservation_id = %s '
               'ORDER BY email_id', (rid,))


def test_parse_drivers():
    d, e = reservations.parse_drivers('Ana Lee, alee@x.edu\n\nBo Park\nCy; bad-email')
    assert d == [{'name': 'Ana Lee', 'email': 'alee@x.edu'}, {'name': 'Bo Park', 'email': ''},
                 {'name': 'Cy', 'email': 'bad-email'}]
    assert len(e) == 1 and 'bad-email' in e[0]
    assert reservations.drivers_text(d[:2]) == 'Ana Lee, alee@x.edu\nBo Park'


def test_anyone_signed_in_can_request(client, sign_in, dbq):
    sign_in(client, 'demo_tier2')
    page = client.get('/reserve').get_data(as_text=True)
    assert 'Request a vehicle' in page and 'campus.staff@example.edu' in page and 'Send request' in page
    rid = _request(client, sign_in, dbq)
    r = dbq('SELECT * FROM wsb.reservation WHERE reservation_id = %s', (rid,))[0]
    assert r['status'] == 'Pending' and r['uin'] == '81234567' and r['passengers'] == 3
    assert r['drivers'] == [{'name': 'Ana Lee', 'email': 'alee@example.edu'}, {'name': 'Bo Park', 'email': ''}]
    assert dbq('SELECT action FROM wsb.reservation_event WHERE reservation_id = %s', (rid,))[0]['action'] == 'Requested'


def test_signed_out_goes_to_sign_in(client):
    r = client.get('/reserve')
    assert r.status_code == 302 and '/login' in r.headers['Location']


def test_request_emails_requester_and_every_approver(client, sign_in, dbq):
    rid = _request(client, sign_in, dbq)
    mails = _emails(dbq, rid)
    to = [m['to_email'] for m in mails]
    assert to[0] == 'campus.staff@example.edu' and 'We got your vehicle request' in mails[0]['subject']
    assert 'Matlacha Boat Ramp' in mails[0]['body'] and 'UIN: 81234567' in mails[0]['body']
    assert {'fleet.manager@example.edu', 'fleet.backup@example.edu'} <= set(to[1:])
    assert 'editor.staff@example.edu' not in to                # Tier 2 without the approve switch
    assert all(m['sent_at'] is None for m in mails)              # no SMTP in tests: they wait in the outbox


def test_approve_switch_adds_someone_to_the_inbox(client, sign_in, dbq):
    dbq("""INSERT INTO wsb.app_user_permission (user_id, permission)
           SELECT user_id, 'approve' FROM wsb.app_user WHERE username = 'demo_editor'""")
    rid = _request(client, sign_in, dbq)
    assert 'editor.staff@example.edu' in [m['to_email'] for m in _emails(dbq, rid)]
    sign_in(client, 'demo_editor')
    assert f'/reservations/{rid}"' in client.get('/reservations').get_data(as_text=True)


@pytest.mark.parametrize('over,msg', [
    ({'uin': 'abc'}, 'UIN must be numbers only.'),
    ({'requester_email': 'nope'}, 'Email must look like'),
    ({'phone': '12'}, 'Phone needs at least 7 digits.'),
    ({'return_at': SOON.strftime('%Y-%m-%dT%H:%M')}, 'Return must be after pick up.'),
    ({'pickup_at': '2020-01-01T08:00', 'return_at': '2020-01-01T10:00'}, "Pick up can&#39;t be in the past."),
    ({'destination': ''}, 'Destination is required.'),
    ({'drivers': 'Ana, not-an-email'}, 'does not look like an email'),
])
def test_bad_requests_are_explained(client, sign_in, dbq, over, msg):
    sign_in(client, 'demo_tier2')
    r = client.post('/reserve', data=_form(**over))
    assert r.status_code == 200 and msg in r.get_data(as_text=True)
    assert dbq('SELECT count(*) n FROM wsb.reservation')[0]['n'] == 0


def test_inbox_is_for_approvers_only(client, sign_in, dbq):
    rid = _request(client, sign_in, dbq)
    sign_in(client, 'demo_tier2')
    assert client.get('/reservations').headers['Location'].endswith('/reservations/mine')
    assert f'/reservations/{rid}"' in client.get('/reservations/mine').get_data(as_text=True)
    sign_in(client, 'demo_editor')
    assert client.get(f'/reservations/{rid}').status_code == 403          # not theirs, no approve switch
    assert f'/reservations/{rid}"' not in client.get('/reservations/mine').get_data(as_text=True)
    assert client.post(f'/reservations/{rid}/decide', data={'action': 'deny', 'note': 'x'}).status_code == 403
    sign_in(client, 'demo_tier1')
    page = client.get('/reservations').get_data(as_text=True)
    assert f'/reservations/{rid}"' in page and 'Campus Staff' in page and 'Pending · 1' in page
    assert 'title="Requests waiting for a decision">1<' in page


def test_approve_assigns_a_vehicle_and_emails(client, sign_in, dbq):
    rid = _request(client, sign_in, dbq)
    vid = _boat(dbq)
    sign_in(client, 'demo_tier1')
    page = client.get(f'/reservations/{rid}').get_data(as_text=True)
    assert 'Vehicle to give them' in page and 'DEMO-B01' in page
    r = client.post(f'/reservations/{rid}/decide', data={'action': 'approve'})
    assert dbq('SELECT status FROM wsb.reservation WHERE reservation_id = %s', (rid,))[0]['status'] == 'Pending'
    client.post(f'/reservations/{rid}/decide', data={'action': 'approve', 'vehicle_id': vid, 'note': 'Keys at the dock office.'})
    row = dbq('SELECT * FROM wsb.reservation WHERE reservation_id = %s', (rid,))[0]
    assert row['status'] == 'Approved' and row['vehicle_id'] == vid and row['decided_by'] == 'Fleet Manager'
    last = _emails(dbq, rid)[-1]
    assert last['to_email'] == 'campus.staff@example.edu' and 'approved' in last['subject']
    assert 'Keys at the dock office.' in last['body'] and 'Vehicle:' in last['body']
    log = dbq("SELECT * FROM wsb.activity_log WHERE kind = 'reservation' ORDER BY activity_id DESC LIMIT 1")[0]
    assert f'Approved vehicle request #{rid}' in log['summary']
    assert {'field': 'Status', 'old': 'Pending', 'new': 'Approved'} in log['details']
    # decided requests can't be decided again
    client.post(f'/reservations/{rid}/decide', data={'action': 'deny', 'note': 'changed my mind'})
    assert dbq('SELECT status FROM wsb.reservation WHERE reservation_id = %s', (rid,))[0]['status'] == 'Approved'


def test_double_booking_is_blocked(client, sign_in, dbq):
    a = _request(client, sign_in, dbq)
    b = _request(client, sign_in, dbq, pickup_at=(SOON + dt.timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
                 return_at=(SOON + dt.timedelta(hours=9)).strftime('%Y-%m-%dT%H:%M'))
    vid = _boat(dbq)
    sign_in(client, 'demo_tier1')
    client.post(f'/reservations/{a}/decide', data={'action': 'approve', 'vehicle_id': vid})
    page = client.get(f'/reservations/{b}').get_data(as_text=True)
    assert 'already reserved' in page
    r = client.post(f'/reservations/{b}/decide', data={'action': 'approve', 'vehicle_id': vid}, follow_redirects=True)
    assert 'already reserved for part of that time' in r.get_data(as_text=True)
    assert dbq('SELECT status FROM wsb.reservation WHERE reservation_id = %s', (b,))[0]['status'] == 'Pending'


def test_deny_needs_a_reason(client, sign_in, dbq):
    rid = _request(client, sign_in, dbq)
    sign_in(client, 'demo_tier1')
    client.post(f'/reservations/{rid}/decide', data={'action': 'deny', 'note': ''})
    assert dbq('SELECT status FROM wsb.reservation WHERE reservation_id = %s', (rid,))[0]['status'] == 'Pending'
    client.post(f'/reservations/{rid}/decide', data={'action': 'deny', 'note': 'No boats that weekend.'})
    assert dbq('SELECT status FROM wsb.reservation WHERE reservation_id = %s', (rid,))[0]['status'] == 'Denied'
    last = _emails(dbq, rid)[-1]
    assert 'denied' in last['subject'] and 'Reason: No boats that weekend.' in last['body']


def test_needs_info_then_requester_updates(client, sign_in, dbq):
    rid = _request(client, sign_in, dbq)
    sign_in(client, 'demo_tier1')
    client.post(f'/reservations/{rid}/decide', data={'action': 'info', 'note': 'How many passengers, exactly?'})
    assert dbq('SELECT status FROM wsb.reservation WHERE reservation_id = %s', (rid,))[0]['status'] == 'Needs info'
    last = _emails(dbq, rid)[-1]
    assert 'more information' in last['subject'] and f'/reservations/{rid}/edit' in last['body']

    sign_in(client, 'demo_tier2')
    page = client.get(f'/reservations/{rid}').get_data(as_text=True)
    assert 'More information needed' in page and 'How many passengers, exactly?' in page
    form = client.get(f'/reservations/{rid}/edit').get_data(as_text=True)
    assert 'They asked: How many passengers, exactly?' in form and 'Ana Lee, alee@example.edu' in form
    client.post(f'/reservations/{rid}/edit', data=_form(passengers='5'))
    row = dbq('SELECT status, passengers FROM wsb.reservation WHERE reservation_id = %s', (rid,))[0]
    assert row == {'status': 'Pending', 'passengers': 5}
    assert 'was updated' in _emails(dbq, rid)[-1]['subject']


def test_only_the_requester_updates_or_cancels(client, sign_in, dbq):
    rid = _request(client, sign_in, dbq)
    sign_in(client, 'demo_tier1')
    assert client.get(f'/reservations/{rid}/edit').status_code == 403
    assert client.post(f'/reservations/{rid}/cancel').status_code == 403
    sign_in(client, 'demo_tier2')
    client.post(f'/reservations/{rid}/cancel')
    assert dbq('SELECT status FROM wsb.reservation WHERE reservation_id = %s', (rid,))[0]['status'] == 'Cancelled'
    assert client.get(f'/reservations/{rid}/edit').status_code == 302


def test_cancelling_an_approved_request_tells_approvers(client, sign_in, dbq):
    rid = _request(client, sign_in, dbq)
    sign_in(client, 'demo_tier1')
    client.post(f'/reservations/{rid}/decide', data={'action': 'approve', 'vehicle_id': _boat(dbq)})
    sign_in(client, 'demo_tier2')
    client.post(f'/reservations/{rid}/cancel')
    last = _emails(dbq, rid)[-1]
    assert 'cancelled' in last['subject'] and last['to_email'] != 'campus.staff@example.edu'


def test_requester_sees_only_their_own_emails(client, sign_in, dbq):
    rid = _request(client, sign_in, dbq)
    sign_in(client, 'demo_tier2')
    page = client.get(f'/reservations/{rid}').get_data(as_text=True)
    assert 'We got your vehicle request' in page and 'New vehicle request from' not in page
    assert 'waiting to send' in page
    sign_in(client, 'demo_tier1')
    assert 'New vehicle request from' in client.get(f'/reservations/{rid}').get_data(as_text=True)


def test_mailer_does_nothing_without_smtp(app_module, monkeypatch):
    import mailer
    monkeypatch.delenv('SMTP_HOST', raising=False)
    assert mailer.configured() is False
    assert mailer.send_waiting(lambda *a, **k: 1 / 0, None) == 0       # doesn't even read the outbox
