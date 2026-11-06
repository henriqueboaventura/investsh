"""Ações: preço médio na compra, lucro na venda, cotação do Yahoo e grade do gráfico.

Valores esperados calculados à mão.
"""
import importlib
import io
import json
import sys
from datetime import date

import pytest

from support import PKG_SRC

if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))
stocks = importlib.import_module('investsh.stocks')
core = importlib.import_module('investsh.core')

TODAY = date(2026, 10, 6)


def petr(**kw):
    base = {'name': 'PETR4', 'category': 'Ação', 'broker': 'Nubank', 'ticker': 'PETR4',
            'quantity': 10, 'invested': 400.0, 'averagePrice': 40.0, 'balance': 380.0,
            'previousBalance': 370.0, 'lastPrice': 38.0, 'lastPriceDate': TODAY.isoformat(),
            'allocationGroup': 'RV_ACOES'}
    base.update(kw)
    return base


# ── O que é ação ─────────────────────────────────────────────────────────────

def test_is_stock_needs_ticker_quantity_and_reais():
    assert core.is_stock(petr())
    assert not core.is_stock(petr(ticker=None))
    # Ticker só informativo: sem quantidade, ou em ativo em dólar (ETF americano)
    assert not core.is_stock({'name': 'AOK', 'ticker': 'AOK', 'balance': 1.0})
    assert not core.is_stock({'name': 'VT', 'ticker': 'VT', 'quantity': 3, 'investedUSD': 300.0})
    assert not core.can_transfer(petr())
    assert core.can_transfer({'name': 'VT', 'ticker': 'VT', 'quantity': 3, 'investedUSD': 300.0})


def test_stock_balance_is_never_stale():
    old = [{'date': '2026-01-01', 'assets': [{'name': 'PETR4', 'broker': 'Nubank', 'balance': 380.0}]}]
    assert core.stale_assets([petr()], old, TODAY, 35) == []


def test_symbol_and_quantity_text():
    assert stocks.symbol(' petr4 ') == 'PETR4.SA'
    assert stocks.symbol('IVVB11.SA') == 'IVVB11.SA'
    assert stocks.num(2.0) == 2 and isinstance(stocks.num(2.0), int)
    assert stocks.num(0.5) == 0.5
    assert stocks.qty_text(1500.0) == '1.500'
    assert stocks.qty_text(2.5) == '2,5'


# ── Compra e venda ───────────────────────────────────────────────────────────

def test_buy_updates_average_price_with_fees():
    a = petr()
    cost = stocks.buy(a, 10, 36.0, fees=2.0, day=TODAY)
    assert cost == 362.0                       # 10 × 36 + 2
    assert a['quantity'] == 20 and isinstance(a['quantity'], int)
    assert a['invested'] == 762.0
    assert a['averagePrice'] == 38.1           # 762 / 20
    # Saldo pela cotação do dia (38), não pelo preço da compra
    assert a['balance'] == 760.0
    # previousBalance acompanha o valor que entrou: a variação segue sendo só rendimento
    assert a['previousBalance'] == 370.0 + 380.0


def test_buy_without_todays_quote_uses_trade_price():
    a = petr(lastPriceDate='2026-10-01')
    stocks.buy(a, 5, 41.0, day=TODAY)
    assert (a['lastPrice'], a['lastPriceDate']) == (41.0, '2026-10-06')
    assert a['balance'] == 15 * 41.0


def test_first_buy_of_new_position():
    a = {'name': 'VALE3', 'ticker': 'VALE3', 'quantity': 0, 'invested': 0.0, 'balance': 0.0}
    stocks.buy(a, 3, 60.0, fees=0.3, day=TODAY)
    assert (a['quantity'], a['invested'], a['averagePrice']) == (3, 180.3, 60.1)


def test_sell_keeps_average_price_and_returns_profit():
    a = petr()
    proceeds, profit = stocks.sell(a, 4, 45.0, fees=1.0, day=TODAY)
    assert proceeds == 179.0                   # 4 × 45 − 1
    assert profit == 19.0                      # 179 − 4 × 40
    assert a['quantity'] == 6
    assert a['invested'] == 240.0
    assert a['averagePrice'] == 40.0           # não muda na venda
    assert a['balance'] == 6 * 38.0
    assert a['previousBalance'] == 370.0 - 4 * 38.0


def test_sell_everything_and_loss():
    a = petr()
    proceeds, profit = stocks.sell(a, 10, 35.0, day=TODAY)
    assert (proceeds, profit) == (350.0, -50.0)
    assert (a['quantity'], a['invested'], a['balance']) == (0, 0.0, 0.0)


def test_sell_more_than_position_is_refused():
    a = petr()
    assert stocks.sell(a, 11, 40.0, day=TODAY) is None
    assert stocks.sell(a, 0, 40.0, day=TODAY) is None
    assert a['quantity'] == 10


def test_trades_and_cash_moves_are_recorded():
    data = {'investments': []}
    a = petr()
    cash = {'name': 'Caixa Nubank', 'broker': 'Nubank', 'balance': 500.0, 'invested': 500.0}
    stocks.record_trade(data, a, 'venda', 2.0, 45.0, 0.5, profit=9.5, day=TODAY)
    assert data['trades'] == [{'date': '2026-10-06', 'name': 'PETR4', 'broker': 'Nubank',
                               'ticker': 'PETR4', 'side': 'venda', 'quantity': 2,
                               'price': 45.0, 'fees': 0.5, 'profit': 9.5}]
    assert stocks.pay_from(data, cash, a, 600.0) is False     # caixa não basta
    assert stocks.pay_from(data, cash, a, 200.0) is True
    stocks.receive_into(data, a, cash, 50.0)
    assert cash['balance'] == 350.0
    assert [(t['from'], t['to'], t['amount']) for t in data['transfers']] == [
        ('Caixa Nubank', 'PETR4', 200.0), ('PETR4', 'Caixa Nubank', 50.0)]


def test_rename_carries_trades():
    data = {'investments': [petr()], 'trades': [{'name': 'PETR4', 'broker': 'Nubank'}]}
    assert core.rename_asset(data, data['investments'][0], 'Petrobras PN', 'Nubank') is None
    assert data['trades'][0]['name'] == 'Petrobras PN'


# ── Cotação ──────────────────────────────────────────────────────────────────

def yahoo(closes, price=None, off=-10800):
    stamps = [(date(2026, 10, d) - date(1970, 1, 1)).days * 86400 + 13 * 3600 for d in range(1, len(closes) + 1)]
    return {'chart': {'result': [{'meta': {'regularMarketPrice': price, 'gmtoffset': off},
                                  'timestamp': stamps, 'indicators': {'quote': [{'close': closes}]}}]}}


def fake_urlopen(payload, seen=None):
    def urlopen(req, timeout=None):
        if seen is not None:
            seen.append(req.full_url)
        if isinstance(payload, Exception):
            raise payload
        return io.BytesIO(json.dumps(payload).encode())
    return urlopen


def test_fetch_quote_parses_closes(monkeypatch):
    seen = []
    monkeypatch.setattr(stocks.urllib.request, 'urlopen',
                        fake_urlopen(yahoo([10.0, None, 10.456], price=10.5), seen))
    q = stocks.fetch_quote('petr4')
    assert seen == ['https://query1.finance.yahoo.com/v8/finance/chart/PETR4.SA?range=1mo&interval=1d']
    assert q['price'] == 10.5
    # Dia sem fechamento fica de fora; datas no fuso da bolsa
    assert q['history'] == [(date(2026, 10, 1), 10.0), (date(2026, 10, 3), 10.46)]


def test_fetch_quote_without_price_uses_last_close(monkeypatch):
    monkeypatch.setattr(stocks.urllib.request, 'urlopen', fake_urlopen(yahoo([10.0, 11.0])))
    assert stocks.fetch_quote('PETR4')['price'] == 11.0


def test_fetch_quotes_skips_failures(monkeypatch):
    monkeypatch.setattr(stocks.urllib.request, 'urlopen', fake_urlopen(OSError('sem rede')))
    assert stocks.fetch_quotes(['PETR4', 'VALE3']) == {}
    assert stocks.fetch_quotes([]) == {}


def test_apply_quotes():
    a, usd = petr(lastPriceDate=None), {'name': 'VT', 'ticker': 'VT', 'quantity': 1, 'investedUSD': 1.0}
    b = petr(name='VALE3', ticker='VALE3')
    missing = stocks.apply_quotes([a, b, usd], {'PETR4': {'price': 39.5, 'history': []}}, TODAY)
    assert missing == ['VALE3']
    assert (a['balance'], a['lastPrice'], a['lastPriceDate']) == (395.0, 39.5, '2026-10-06')


# ── Gráfico ──────────────────────────────────────────────────────────────────

def test_chart_grid():
    hist = [(date(2026, 10, d), v) for d, v in ((1, 10.0), (2, 13.0), (3, 11.0))]
    grid, values = stocks.chart(hist, height=4, ref=12.0)
    assert [''.join(r) for r in grid] == [
        ' P ',    # 13
        '-||',    # 12: preço médio; as ligações 10→13 e 13→11 passam por cima
        ' |L',    # 11
        'P  ',    # 10
    ]
    assert values == [13.0, 12.0, 11.0, 10.0]


def test_chart_reference_far_away_is_left_out():
    hist = [(date(2026, 10, 1), 10.0), (date(2026, 10, 2), 11.0)]
    grid, values = stocks.chart(hist, height=3, ref=50.0)
    assert not any('-' in r for r in grid)
    assert values[0] == 11.0 and values[-1] == 10.0


def test_variation():
    assert stocks.variation([(TODAY, 40.0)], 42.0) == pytest.approx(0.05)
    assert stocks.variation([], 42.0) is None
