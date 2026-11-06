"""changes.diff / changes.text: before → after detail for the activity log."""
import datetime as dt

from changes import diff, text


def test_changed_fields_with_old_and_new():
    d = diff({'status': 'Active', 'mileage': 41200}, {'status': 'In shop', 'mileage': '42050'},
             {'status': 'Status', 'mileage': 'Mileage'})
    assert d == [{'field': 'Status', 'old': 'Active', 'new': 'In shop'},
                 {'field': 'Mileage', 'old': '41,200', 'new': '42,050'}]


def test_none_and_empty_are_the_same():
    assert diff({'notes': None}, {'notes': ''}, {'notes': 'Notes'}) == []


def test_same_number_as_text_is_no_change():
    assert diff({'year': 2019, 'hours': 12.5}, {'year': '2019', 'hours': '12.5'}, {}) == []


def test_dates():
    d = diff({'day': dt.date(2026, 3, 2)}, {'day': '2026-11-06'}, {'day': 'Last done'})
    assert d == [{'field': 'Last done', 'old': 'Mar 02, 2026', 'new': 'Nov 06, 2026'}]


def test_hidden_fields_have_no_values():
    d = diff({'vin': '1FTAAA'}, {'vin': '2FTBBB'}, {'vin': 'VIN'})
    assert d == [{'field': 'VIN', 'old': None, 'new': None, 'hidden': True}]
    assert '1FT' not in text(d) and text(d) == 'VIN: changed'


def test_text():
    assert text([{'field': 'Status', 'old': 'Active', 'new': 'In shop'},
                 {'field': 'Mileage', 'old': '41,200', 'new': '42,050'}]) == 'Status: Active → In shop · Mileage: 41,200 → 42,050'
    assert text(None) == ''
