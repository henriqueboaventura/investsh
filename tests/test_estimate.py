"""Saldo estimado da renda fixa (% do CDI e prefixado), com valores calculados à mão."""
import importlib
import sys
from datetime import date

import pytest

from support import PKG_SRC

if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))
est = importlib.import_module('investsh.estimate')

TODAY = date(2026, 10, 19)   # segunda-feira


def cdb(**kw):
    base = {'name': 'CDB', 'broker': 'XP', 'category': 'CDB', 'balance': 1000.0,
            'rate': {'kind': 'PERCENT_CDI', 'value': 110.0}}
    base.update(kw)
    return base


def snap(d, bal, name='CDB', broker='XP'):
    return {'date': d, 'assets': [{'name': name, 'broker': broker, 'balance': bal}]}


def test_as_of_is_first_snapshot_with_current_balance():
    history = [snap('2026-09-01', 990.0), snap('2026-10-01', 1000.0), snap('2026-10-06', 1000.0)]
    assert est.as_of(cdb(), history, TODAY) == date(2026, 10, 1)
    # Saldo editado nesta sessão (diferente da última foto): é de hoje
    assert est.as_of(cdb(balance=1010.0), history, TODAY) == TODAY
    # Mesmo nome em outra corretora não conta
    assert est.as_of(cdb(broker='Nubank'), history, TODAY) == TODAY


def test_percent_cdi_compounds_business_days_before_today():
    history = [snap('2026-10-15', 1000.0)]                 # quinta
    cdi = {date(2026, 10, 14): 0.05, date(2026, 10, 15): 0.05, date(2026, 10, 16): 0.05,
           date(2026, 10, 19): 0.05}                        # 19 = hoje: ainda não rende
    e = est.estimate(cdb(), history, cdi, TODAY)
    assert e == {'value': round(1000 * (1 + 1.1 * 0.0005) ** 2, 2), 'as_of': date(2026, 10, 15)}
    assert est.estimate(cdb(), history, None, TODAY) is None   # sem CDI


def test_fixed_rate_uses_business_days():
    pre = cdb(rate={'kind': 'ANNUAL_FIXED', 'value': 12.0})
    e = est.estimate(pre, [snap('2026-10-12', 1000.0)], None, TODAY)   # 12 a 16: 5 dias úteis
    assert e['value'] == round(1000 * 1.12 ** (5 / 252), 2)


@pytest.mark.parametrize('inv', [
    cdb(category='Tesouro Direto'),
    cdb(rate={'kind': 'IPCA_PLUS', 'value': 6.0}),
    cdb(rate=None),
    cdb(investedUSD=10.0),
    cdb(balance=0.0),
])
def test_not_estimated(inv):
    assert est.estimate(inv, [snap('2026-10-01', inv['balance'])], {date(2026, 10, 1): 0.05}, TODAY) is None


def test_divergence_tolerance():
    e = {'value': 1000.0}
    assert est.divergence(1009.0, e) is None
    assert est.divergence(1020.0, e) == pytest.approx(0.02)
    assert est.divergence(950.0, e) == pytest.approx(-0.05)
    assert est.divergence(950.0, None) is None
