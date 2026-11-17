"""The actual native writer keeps a late liability's payment month live."""
from types import SimpleNamespace

import openpyxl
import pytest

import native_land_rent_book as rent_book
import office_workbook as office
from xlsx_eval import Evaluator


@pytest.mark.parametrize('payment_month,expected', [(None, 37), (5, 37), (60, 61), (120, 121)])
def test_native_project_horizon_follows_the_editable_cash_calendar(monkeypatch, payment_month, expected):
    class Captured(Exception):
        pass

    monthly, parameters = {}, {}

    class Rows:
        def section(self, *a, **kw):
            pass

        def month(self, name, label, formula, **kw):
            monthly[name] = formula

        def param(self, name, label, formula, *a, **kw):
            parameters[name] = formula
            if name == 'guard.horizon':
                raise Captured

    count = 121
    calendar = rent_book.RentalReferences('Lease', {'cash_rows': {'total': 6}})
    refs = {'k': "'Probe'!$A$1", 't.rve': '24', 'in.residual_months': '0',
            'cx.plan_last': '-1', 'guard.rent_last_k': "'Probe'!B5:DR5"}
    monkeypatch.setattr(office, 'ref', lambda key, mod='': refs.get(key, '0'))
    monkeypatch.setattr(office, '_path_cx', lambda *a, **kw: '0')
    book = SimpleNamespace(n=count, rent_calendars={'guard': (calendar, None)})
    with pytest.raises(Captured):
        office._cash_path(book, Rows(), {'code': 'guard', 'tab': 'Tab'}, [], [], [], {}, {'order': []}, count)
    wb = openpyxl.Workbook()
    probe = wb.active
    probe.title = 'Probe'
    lease = wb.create_sheet('Lease')
    for month in range(count):
        lease.cell(6, 4 + month, 1 if month == payment_month else 0)
    formula = monthly.get('guard.rent_last_k')
    probe['A2'] = '=' + formula if formula else -1
    for month in range(count):
        probe['A1'] = month
        probe.cell(5, 2 + month, Evaluator(wb).cell('Probe', 'A2'))
    probe['A3'] = parameters['guard.horizon']
    assert Evaluator(wb).cell('Probe', 'A3') == expected
