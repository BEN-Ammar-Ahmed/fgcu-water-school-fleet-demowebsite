"""Stats pages (stats.py): spending and trips, by fiscal year (July to June) and vehicle type."""
import datetime as dt
from decimal import Decimal

import stats


def _fy(d):
    return stats.fiscal_year_of(d)


def test_fiscal_year():
    assert _fy(dt.date(2026, 7, 1)) == 2026 and _fy(dt.date(2026, 6, 30)) == 2025
    assert stats.fy_label(2026) == 'FY26-27'


def test_spending_adds_fuel_and_service_without_double_counting(client, sign_in, dbq):
    vid = dbq("SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = 'DEMO-C01'")[0]['vehicle_id']
    today = dt.date.today()
    dbq('DELETE FROM wsb.fuel_record'); dbq('DELETE FROM wsb.maintenance_record')
    dbq("DELETE FROM wsb.invoice_line"); dbq('DELETE FROM wsb.invoice')
    dbq('INSERT INTO wsb.fuel_record (vehicle_id, fuel_date, gallons, total_cost) VALUES (%s, %s, 10, 40.00)', (vid, today))
    dbq('INSERT INTO wsb.maintenance_record (vehicle_id, service_date, service_type, cost) VALUES (%s, %s, %s, 100.00)',
        (vid, today, 'Oil Change'))
    # an invoice line already linked to the fuel record is not counted again; an unlinked fee is
    inv = dbq("""INSERT INTO wsb.invoice (invoice_type, vendor, invoice_date, total_amount)
                 VALUES ('Other', 'TEST', %s, 65) RETURNING invoice_id""", (today,))[0]['invoice_id']
    line = dbq("""INSERT INTO wsb.invoice_line (invoice_id, vehicle_id, category, amount) VALUES (%s, %s, 'Fuel', 40)
                  RETURNING line_id""", (inv, vid))[0]['line_id']
    dbq('UPDATE wsb.fuel_record SET invoice_line_id = %s', (line,))
    dbq("INSERT INTO wsb.invoice_line (invoice_id, vehicle_id, category, amount) VALUES (%s, %s, 'Registration', 25)", (inv, vid))
    sign_in(client, 'demo_tier2')                       # every tier can see costs
    page = client.get('/stats/spending').get_data(as_text=True)
    assert 'data-stat="total">$165<' in page and 'data-stat="fuel">$40<' in page
    assert 'data-stat="maintenance">$100<' in page and 'data-stat="other">$25<' in page
    assert '2019 Toyota Camry' in page
    home = client.get('/').get_data(as_text=True)
    assert 'data-stat="spent">$165<' in home and '/stats/spending' in home and '/stats/trips' in home


def test_spending_filters_by_year_and_type(client, sign_in, dbq):
    vid = dbq("SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = 'DEMO-C01'")[0]['vehicle_id']
    dbq('DELETE FROM wsb.fuel_record'); dbq('DELETE FROM wsb.maintenance_record')
    dbq("DELETE FROM wsb.invoice_line"); dbq('DELETE FROM wsb.invoice')
    last_year = dt.date(_fy(dt.date.today()) - 1, 8, 1)
    dbq('INSERT INTO wsb.fuel_record (vehicle_id, fuel_date, gallons, total_cost) VALUES (%s, %s, 10, 30.00)', (vid, last_year))
    sign_in(client, 'demo_tier1')
    assert 'data-stat="total">$0<' in client.get('/stats/spending').get_data(as_text=True)
    page = client.get(f'/stats/spending?fy={_fy(dt.date.today()) - 1}').get_data(as_text=True)
    assert 'data-stat="total">$30<' in page
    page = client.get(f'/stats/spending?fy={_fy(dt.date.today()) - 1}&type=Boat').get_data(as_text=True)
    assert 'data-stat="total">$0<' in page
    assert client.get('/stats/spending?fy=nonsense&type=Spaceship').status_code == 200


def test_trips_stats(client, sign_in, dbq):
    dbq('DELETE FROM wsb.fuel_record WHERE trip_id IS NOT NULL'); dbq('DELETE FROM wsb.trip')
    vid = dbq("SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = 'DEMO-T02'")[0]['vehicle_id']
    did = dbq("SELECT driver_id FROM wsb.driver WHERE approved AND active LIMIT 1")[0]['driver_id']
    now = dt.datetime.now().replace(microsecond=0)
    dbq("""INSERT INTO wsb.trip (vehicle_id, driver_id, start_datetime, end_datetime, starting_mileage, ending_mileage,
                                 destination, purpose) VALUES (%s, %s, %s, %s, 100, 160, 'Boat Ramp', 'Sampling'),
                                (%s, %s, %s, NULL, 160, NULL, 'Boat Ramp', 'Sampling')""",
        (vid, did, now - dt.timedelta(hours=5), now - dt.timedelta(hours=2), vid, did, now - dt.timedelta(hours=1)))
    sign_in(client, 'demo_tier2')
    page = client.get('/stats/trips').get_data(as_text=True)
    assert 'data-stat="trips">2<' in page and 'data-stat="miles">60<' in page and '1 still out' in page
    assert 'Boat Ramp' in page and 'Out now' in page and '2022 Chevrolet Silverado 1500' in page


def test_stats_need_sign_in(client):
    assert '/login' in client.get('/stats/spending').headers['Location']
    assert '/login' in client.get('/stats/trips').headers['Location']


def test_admin_cards_link_to_stats(client, sign_in):
    sign_in(client, 'demo_tier1')
    page = client.get('/admin').get_data(as_text=True)
    assert '/stats/spending' in page and '/stats/trips' in page
