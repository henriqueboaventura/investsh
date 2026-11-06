"""Ações (e outros ativos negociados na B3): cotação, compra e venda com preço médio.

Ativo com `ticker` tem quantidade (`quantity`) e custo (`invested`); o preço médio
(`averagePrice`) é custo ÷ quantidade. O saldo é quantidade × cotação (`lastPrice`, do
dia `lastPriceDate`). Compra soma ao custo; venda tira do custo a parte vendida pelo
preço médio, que não muda, e o lucro realizado vai para `trades`.

Cotação e fechamentos do último mês vêm do Yahoo Finance (sem chave de API): uma
requisição por ticker, em paralelo, ao abrir o investsh.
"""
import json
import urllib.request
from datetime import date, datetime, timedelta

from .core import add_to_balance, take_from_balance, is_stock  # noqa: F401 (is_stock: API daqui)

QUOTE_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1mo&interval=1d'
TIMEOUT = 6

# Categorias que perguntam o ticker no cadastro (ativos em reais negociados na B3)
TICKER_CATEGORIES = ('Ação', 'Fundo Imobiliário', 'ETF')


def symbol(ticker):
    """Símbolo no Yahoo: PETR4 → PETR4.SA (com ponto, fica como está)."""
    t = ticker.strip().upper()
    return t if '.' in t else f'{t}.SA'


def fetch_quote(ticker, timeout=TIMEOUT):
    """{'price': cotação, 'history': [(data, fechamento)]} do último mês.

    Levanta exceção se a cotação não vier (sem rede, ticker inexistente...).
    """
    req = urllib.request.Request(QUOTE_URL.format(symbol=symbol(ticker)),
                                 headers={'User-Agent': 'Mozilla/5.0 (investsh)'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())
    res = payload['chart']['result'][0]
    meta = res['meta']
    off = meta.get('gmtoffset') or 0
    closes = (res.get('indicators', {}).get('quote') or [{}])[0].get('close') or []
    by_day = {}
    for ts, close in zip(res.get('timestamp') or [], closes):
        if close is None:
            continue
        day = (datetime(1970, 1, 1) + timedelta(seconds=ts + off)).date()
        by_day[day] = round(float(close), 2)   # o mesmo dia repetido: fica o último
    history = sorted(by_day.items())
    price = meta.get('regularMarketPrice') or (history[-1][1] if history else None)
    if not price:
        raise ValueError(f'sem cotação para {ticker}')
    return {'price': round(float(price), 2), 'history': history}


def fetch_quotes(tickers, timeout=TIMEOUT):
    """{ticker: cotação} dos que responderam; os que falharam ficam de fora."""
    from concurrent.futures import ThreadPoolExecutor
    tickers = sorted({t.strip().upper() for t in tickers if t})
    if not tickers:
        return {}

    def one(t):
        try:
            return t, fetch_quote(t, timeout)
        except Exception:
            return t, None
    with ThreadPoolExecutor(max_workers=min(8, len(tickers))) as pool:
        return {t: q for t, q in pool.map(one, tickers) if q}


def num(q):
    """Quantidade inteira fica int no JSON (2, não 2.0)."""
    q = round(float(q), 8)
    return int(q) if q.is_integer() else q


def qty_text(q):
    q = num(q or 0)
    return f'{q:,}'.replace(',', '.') if isinstance(q, int) else f'{q:g}'.replace('.', ',')


def average_price(inv):
    q = inv.get('quantity') or 0
    if not q:
        return inv.get('averagePrice') or 0.0
    return inv.get('invested', 0) / q


def set_price(inv, price, day):
    """Cotação nova (da internet ou digitada): o saldo vira quantidade × cotação."""
    inv['lastPrice'] = round(price, 2)
    inv['lastPriceDate'] = day.isoformat()
    inv['balance'] = round((inv.get('quantity') or 0) * price, 2)


def apply_quotes(investments, quotes, day):
    """Aplica as cotações buscadas aos ativos com ticker. Devolve os tickers sem cotação."""
    missing = []
    for inv in investments:
        if not is_stock(inv):
            continue
        q = quotes.get(inv['ticker'].strip().upper())
        if q:
            set_price(inv, q['price'], day)
        else:
            missing.append(inv['ticker'])
    return missing


def _mark(inv, price, day):
    """Cotação para o saldo após uma operação: a do dia, se já buscada; senão a da operação."""
    if inv.get('lastPriceDate') != day.isoformat() or not inv.get('lastPrice'):
        inv['lastPrice'] = round(price, 2)
        inv['lastPriceDate'] = day.isoformat()
    return inv['lastPrice']


def buy(inv, qty, price, fees=0.0, day=None):
    """Compra: soma a quantidade e o custo (com as taxas). Devolve o custo em R$.

    O previousBalance acompanha, para a variação na tela continuar sendo só rendimento.
    """
    day = day or date.today()
    q0 = inv.get('quantity') or 0
    cost = round(qty * price + fees, 2)
    invested = inv.get('invested')
    if invested is None:
        invested = q0 * (inv.get('averagePrice') or 0)
    q1 = q0 + qty
    inv['quantity'] = num(q1)
    inv['invested'] = round(invested + cost, 2)
    inv['averagePrice'] = round(inv['invested'] / q1, 4)
    mark = _mark(inv, price, day)
    inv['balance'] = round(q1 * mark, 2)
    if 'previousBalance' in inv:
        inv['previousBalance'] = round(inv['previousBalance'] + qty * mark, 2)
    return cost


def sell(inv, qty, price, fees=0.0, day=None):
    """Venda: tira a quantidade e o custo dela pelo preço médio (que não muda).

    Devolve (valor recebido, lucro realizado) em R$, ou None se `qty` passar da posição.
    """
    day = day or date.today()
    q0 = inv.get('quantity') or 0
    if qty <= 0 or qty > q0 + 1e-9:
        return None
    proceeds = round(qty * price - fees, 2)
    invested = inv.get('invested')
    if invested is None:
        invested = q0 * (inv.get('averagePrice') or 0)
    cost_out = invested * qty / q0
    q1 = q0 - qty if qty < q0 else 0
    inv['quantity'] = num(q1)
    inv['invested'] = round(invested - cost_out, 2) if q1 else 0.0
    mark = _mark(inv, price, day)
    inv['balance'] = round(q1 * mark, 2)
    if 'previousBalance' in inv:
        inv['previousBalance'] = round(inv['previousBalance'] - qty * mark, 2)
    return proceeds, round(proceeds - cost_out, 2)


def record_trade(data, inv, side, qty, price, fees=0.0, profit=None, day=None):
    """Guarda a operação em data['trades'] (base para o IR de ações)."""
    trade = {'date': (day or date.today()).isoformat(), 'name': inv.get('name', ''),
             'broker': inv.get('broker', ''), 'ticker': inv.get('ticker', ''), 'side': side,
             'quantity': num(qty), 'price': round(price, 4), 'fees': round(fees, 2)}
    if profit is not None:
        trade['profit'] = round(profit, 2)
    data.setdefault('trades', []).append(trade)
    return trade


def _log_transfer(data, src, dst, amount, day=None):
    data.setdefault('transfers', []).append({
        'date': (day or date.today()).isoformat(),
        'from': src.get('name', ''), 'fromBroker': src.get('broker', ''),
        'to': dst.get('name', ''), 'toBroker': dst.get('broker', ''),
        'amount': round(amount, 2)})


def pay_from(data, src, inv, amount):
    """Compra paga com o saldo de outro ativo em reais (ex.: caixa da corretora).

    Tira de `src` e registra a transferência para `inv` (cujo saldo a compra já fez).
    Devolve False se o saldo de `src` não basta.
    """
    if take_from_balance(src, amount, 1) is None:
        return False
    _log_transfer(data, src, inv, amount)
    return True


def receive_into(data, inv, dst, amount):
    """Valor de uma venda que ficou na carteira, em outro ativo em reais."""
    add_to_balance(dst, amount, 1)
    _log_transfer(data, inv, dst, amount)


def variation(history, price):
    """Variação (fração) do primeiro fechamento do período até a cotação, ou None."""
    if not history or not history[0][1]:
        return None
    return price / history[0][1] - 1


def chart(history, height=12, ref=None):
    """Grade do gráfico de preços: (linhas, valores do eixo).

    Cada linha é uma lista de papéis, um por dia: 'P' ponto, 'L' último ponto, '|' ligação
    entre dias, '-' linha de referência (`ref`, ex. preço médio), ' ' vazio. `valores`
    tem o preço de cada linha (de cima para baixo). A referência fora da faixa de preços
    do período alarga a escala só até 15% além dela; mais longe, fica de fora.
    """
    vals = [c for _, c in history]
    lo, hi = min(vals), max(vals)
    if ref is not None:
        span = (hi - lo) or hi * 0.02
        if lo - span * 0.15 <= ref <= hi + span * 0.15:
            lo, hi = min(lo, ref), max(hi, ref)
        else:
            ref = None
    if hi == lo:
        hi, lo = hi * 1.01, lo * 0.99
    rng = hi - lo

    def row_of(v):
        return int(round((hi - v) / rng * (height - 1)))

    pos = [row_of(v) for v in vals]
    ref_row = row_of(ref) if ref is not None else None
    grid = []
    for r in range(height):
        cells = []
        for i, p in enumerate(pos):
            if p == r:
                cells.append('L' if i == len(pos) - 1 else 'P')
            elif i > 0 and min(pos[i - 1], p) < r < max(pos[i - 1], p):
                cells.append('|')
            elif r == ref_row:
                cells.append('-')
            else:
                cells.append(' ')
        grid.append(cells)
    values = [hi - r / (height - 1) * rng for r in range(height)]
    return grid, values
