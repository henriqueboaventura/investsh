"""IR e IOF da renda fixa, com valores calculados à mão."""
import importlib
import sys
from datetime import date

import pytest

from support import PKG_SRC

if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))
tax = importlib.import_module('investsh.tax')

TODAY = date(2026, 10, 18)


def cdb(**kw):
    base = {'name': 'CDB', 'broker': 'XP', 'category': 'CDB', 'balance': 1100.0, 'invested': 1000.0,
            'purchaseDate': '2024-01-03', 'maturity': '2028-03-01',
            'rate': {'kind': 'PERCENT_CDI', 'value': 116.0}}
    base.update(kw)
    return base


@pytest.mark.parametrize('days, rate', [(1, 0.225), (180, 0.225), (181, 0.20), (360, 0.20),
                                        (361, 0.175), (720, 0.175), (721, 0.15)])
def test_ir_table(days, rate):
    assert tax.ir_rate(days) == rate


@pytest.mark.parametrize('days, rate', [(1, 0.96), (10, 0.66), (29, 0.03), (30, 0.0), (400, 0.0)])
def test_iof_table(days, rate):
    assert tax.iof_rate(days) == rate


def test_redeem_long_term_cdb():
    r = tax.redeem_today(cdb(), [], TODAY)
    assert r == {'gross': 1100.0, 'gain': 100.0, 'ir': 15.0, 'iof': 0.0, 'net': 1085.0,
                 'ir_rate': 0.15, 'days': 1019, 'approx': False}


def test_redeem_with_iof_in_first_month():
    r = tax.redeem_today(cdb(purchaseDate='2026-10-08'), [], TODAY)   # 10 dias: IOF 66%
    assert r['iof'] == 66.0
    assert r['ir'] == round((100 - 66) * 0.225, 2)
    assert r['net'] == round(1100 - 66 - 7.65, 2)


def test_exempt_and_loss():
    assert tax.redeem_today(cdb(category='LCA'), [], TODAY)['net'] == 1100.0
    assert tax.redeem_today(cdb(taxExempt=True), [], TODAY)['ir'] == 0.0
    assert tax.redeem_today(cdb(balance=900.0), [], TODAY)['net'] == 900.0   # prejuízo: sem IR


def test_without_purchase_date_uses_first_snapshot_and_no_iof():
    history = [{'date': '2026-10-01', 'assets': [{'name': 'CDB', 'broker': 'XP'}]},
               {'date': '2026-09-01', 'assets': [{'name': 'CDB', 'broker': 'Nubank'}]}]
    r = tax.redeem_today(cdb(purchaseDate=None), history, TODAY)
    assert (r['days'], r['approx'], r['iof'], r['ir']) == (17, True, 0.0, 22.5)
    assert tax.redeem_today(cdb(purchaseDate=None), [], TODAY)['approx'] is True


@pytest.mark.parametrize('inv', [cdb(category='ETF'), cdb(investedUSD=10.0), cdb(invested=None)])
def test_not_applicable(inv):
    assert tax.redeem_today(inv, [], TODAY) is None


def test_net_rate_uses_bracket_at_maturity():
    assert tax.net_rate(cdb(), [], TODAY) == ('PERCENT_CDI', pytest.approx(98.6))
    short = cdb(purchaseDate='2026-10-01', maturity='2027-01-01')   # 92 dias: 22,5%
    assert tax.net_rate(short, [], TODAY) == ('PERCENT_CDI', pytest.approx(116 * 0.775))
    assert tax.net_rate(cdb(category='LCA', rate={'kind': 'PERCENT_CDI', 'value': 92.0}), [], TODAY) == \
        ('PERCENT_CDI', 92.0)
    assert tax.net_rate(cdb(rate={'kind': 'IPCA_PLUS', 'value': 6.0}), [], TODAY) is None


def test_rate_label():
    assert tax.rate_label('PERCENT_CDI', 110.0) == '110% CDI'
    assert tax.rate_label('ANNUAL_FIXED', 9.75) == '9,75% a.a.'
    assert tax.rate_label('IPCA_PLUS', 6.4) == 'IPCA+6,4%'
