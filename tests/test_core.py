"""Testes unitários dos cálculos, com valores esperados calculados à mão."""
import json

import pytest

from support import load_finances


@pytest.fixture(scope='module')
def f():
    return load_finances()


def inv(**kw):
    base = {'name': 'X', 'category': 'CDB', 'type': 'POS', 'broker': 'XP', 'balance': 0.0}
    base.update(kw)
    return base


# ── Formatação ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize('value, expected', [
    (0, 'R$ 0,00'),
    (1234.5, 'R$ 1.234,50'),
    (1234567.891, 'R$ 1.234.567,89'),
    (-98.765, 'R$ -98,77'),
    (0.004, 'R$ 0,00'),
])
def test_brl_fmt(f, value, expected):
    assert f.brl_fmt(value) == expected


def test_fmt_fixed_width(f):
    assert f.fmt(1234.5) == 'R$     1,234.50'
    assert f.fmt(-1) == 'R$        -1.00'


def test_gain_str(f):
    assert f.gain_str(110, 100) == f'{f.G}(+10.00 / +10.0%){f.RST}'
    assert f.gain_str(90, 100) == f'{f.R}(-10.00 / -10.0%){f.RST}'
    assert f.gain_str(90, 0) == ''
    assert f.gain_str(90, None) == ''


def test_sparkline(f):
    assert f.sparkline([]) == ''
    assert f.sparkline([5, 5, 5]) == '▄▄▄'
    assert f.sparkline([0, 4, 8]) == '▁▅█'
    assert len(f.sparkline(list(range(20)))) == 20


# ── Classificação e ordenação ────────────────────────────────────────────────

def test_classify(f):
    assert f.classify(inv(allocationGroup='RF_IPCA')) == ('Renda Fixa', 'IPCA')
    assert f.classify(inv(allocationGroup='RV_CRYPTO')) == ('Renda Variável', 'Crypto')
    assert f.classify(inv(allocationGroup='PREVIDENCIA')) == ('Previdência', 'Previdência')
    assert f.classify(inv(allocationGroup='NAO_EXISTE', category='Debênture')) == ('Outros', 'Debênture')
    assert f.classify(inv(category='')) == ('Outros', '—')


def test_sort_key_orders_broker_category_type_name(f):
    invs = [
        inv(name='b', broker='Binance', category='Crypto', type=None),
        inv(name='z', broker='XP', category='ETF', type=None),
        inv(name='a', broker='XP', category='CDB', type='PRE'),
        inv(name='c', broker='XP', category='CDB', type='POS'),
        inv(name='n', broker='Corretora Nova', category='CDB'),
        inv(name='m', broker='Nubank', category='LCA'),
    ]
    assert [i['name'] for i in sorted(invs, key=f.sort_key)] == ['c', 'a', 'z', 'm', 'b', 'n']


# ── Custo base e totais ──────────────────────────────────────────────────────

def test_cost_basis(f):
    assert f.cost_basis(inv(invested=100.0), 5) == 100.0
    assert f.cost_basis(inv(investedUSD=10.0), 5) == 50.0
    assert f.cost_basis(inv(category='Crypto', quantity=2, averagePrice=3.5), 5) == 7.0
    assert f.cost_basis(inv(category='Crypto', quantity=2), 5) is None
    assert f.cost_basis(inv(), 5) is None


def test_total_invested_skips_unknown_cost(f):
    data = {'dollarRate': 5.0, 'investments': [
        inv(invested=100.0), inv(investedUSD=10.0), inv(), inv(category='Crypto', quantity=1, averagePrice=20.0)]}
    assert f.total_invested(data) == 170.0


# ── Reserva de emergência ────────────────────────────────────────────────────

def reserve_data(total, cfg):
    return {'emergencyReserve': cfg, 'investments': [
        inv(name='R', balance=total, allocationGroup='RESERVA_EMERGENCIA'),
        inv(name='Outro', balance=1000.0, allocationGroup='RF_CDI')]}


def test_reserve_by_group_when_no_asset_names(f):
    d = reserve_data(500.0, {'minimum': 100, 'target': 200, 'maximum': 1000})
    assert f.reserva_total(d) == 500.0
    assert [i['name'] for i in f.alloc_investments(d)] == ['Outro']


def test_reserve_by_explicit_asset_names(f):
    d = reserve_data(500.0, {'assetNames': ['Outro']})
    assert f.reserva_total(d) == 1000.0
    assert [i['name'] for i in f.alloc_investments(d)] == ['R']


def test_reserve_included_in_allocation_when_configured(f):
    d = reserve_data(500.0, {'excludeFromAllocation': False})
    assert len(f.alloc_investments(d)) == 2


@pytest.mark.parametrize('total, kind, msg', [
    (50.0, 'below', 'R$ 50,00 abaixo do mínimo'),
    (100.0, 'ok', 'dentro da faixa ideal'),
    (1000.0, 'ok', 'dentro da faixa ideal'),
    (1500.0, 'above', 'R$ 500,00 acima do máximo — considere investir o excedente'),
])
def test_reserva_status(f, total, kind, msg):
    rs = f.reserva_status(reserve_data(total, {'minimum': 100, 'target': 200, 'maximum': 1000}))
    assert rs == (total, 100, 200, 1000, msg, kind)


def test_reserva_status_none_without_config_or_balance(f):
    assert f.reserva_status({'investments': []}) is None
    assert f.reserva_status(reserve_data(0.0, {'minimum': 1})) is None


# ── Histórico ────────────────────────────────────────────────────────────────

def test_monthly_summary_keeps_last_entry_per_month(f):
    hist = [{'date': '2026-01-05', 'total': 1}, {'date': '2026-02-01', 'total': 2},
            {'date': '2026-01-20', 'total': 3}, {'date': '', 'total': 9}]
    assert f.monthly_summary(hist) == [{'date': '2026-01-20', 'total': 3},
                                       {'date': '2026-02-01', 'total': 2}]


def test_history_snapshot(f):
    data = {'lastUpdated': '2026-10-06', 'fgts': 10.0, 'dollarRate': 5.0, 'investments': [
        inv(name='A', invested=100.0, balance=110.123456, maturity='2030-01-01', extra='ignorado'),
        inv(name='B', investedUSD=10.0, balance=60.0, broker='Nomad')]}
    snap = f.history_snapshot(data, 170.123456)
    assert snap == {
        'date': '2026-10-06', 'total': 170.1235, 'totalWithFGTS': 180.1235, 'totalInvested': 150.0,
        'assets': [
            {'name': 'A', 'category': 'CDB', 'type': 'POS', 'broker': 'XP', 'maturity': '2030-01-01', 'balance': 110.1235},
            {'name': 'B', 'category': 'CDB', 'type': 'POS', 'broker': 'Nomad', 'maturity': None, 'balance': 60.0}]}


def test_broker_monthly_series(tmp_path):
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'data').mkdir()
    from support import SRC, FINANCES_CMD
    (tmp_path / FINANCES_CMD[0]).write_text((SRC / FINANCES_CMD[0]).read_text(encoding='utf-8'), encoding='utf-8')
    hist = [
        {'date': '2026-01-01', 'total': 0, 'assets': [{'broker': 'XP', 'balance': 10}, {'broker': 'XP', 'balance': 5}]},
        {'date': '2026-02-01', 'total': 0},
        {'date': '2026-03-01', 'total': 0, 'assets': [{'broker': 'Nubank', 'balance': 7}, {'broker': 'XP', 'balance': None}]},
    ]
    (tmp_path / 'data' / 'history.json').write_text(json.dumps(hist))
    f = load_finances(tmp_path)
    assert f.broker_monthly_series(['XP', 'Nubank']) == (
        ['2026-01-01', '2026-02-01', '2026-03-01'], {'XP': [15, 0, 0], 'Nubank': [0, 0, 7]})
    assert f.broker_monthly_series(['XP'], months=1) == (['2026-03-01'], {'XP': [0]})
