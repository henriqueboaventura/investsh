"""Saldo estimado de hoje para renda fixa com taxa conhecida (% do CDI ou prefixada).

Parte do último saldo registrado e aplica a taxa desde a data em que ele foi registrado
(a foto do histórico em que o saldo passou a ser o atual). Serve para conferir o valor
digitado ao atualizar: diferença grande costuma ser erro de digitação ou de ativo.

Fica de fora o que não segue a curva: Tesouro Direto (preço de mercado), dólar, cripto
e IPCA+ (o IPCA do mês só sai depois). É uma estimativa bruta: sem IR, e o CDI vai até
a última taxa divulgada pelo Banco Central.
"""
from datetime import date, timedelta

from .core import balance_since

# Diferença entre o valor digitado e o estimado que merece aviso
TOLERANCE = 0.01


def supported(inv):
    """Ativo cuja curva dá para estimar: renda fixa em R$ com % do CDI ou taxa prefixada."""
    rate = inv.get('rate') or {}
    return (rate.get('kind') in ('PERCENT_CDI', 'ANNUAL_FIXED')
            and isinstance(rate.get('value'), (int, float))
            and inv.get('category') not in ('Tesouro Direto', 'Crypto')
            and 'investedUSD' not in inv)


def as_of(inv, history, today):
    """Data em que o saldo atual foi registrado (ver core.balance_since)."""
    return balance_since(inv, history, today)


def _business_days(start, end):
    """Dias úteis (seg–sex) em [start, end); feriados não descontados."""
    n, d = 0, start
    while d < end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def estimate(inv, history, cdi, today):
    """{'value', 'as_of'} com o saldo estimado para hoje, ou None.

    `cdi` = {data: CDI do dia em %} (bench.cdi). Rende cada dia útil d com
    as_of <= d < hoje (a taxa de hoje só é conhecida amanhã).
    """
    if not supported(inv) or not inv.get('balance'):
        return None
    start = as_of(inv, history, today)
    if start >= today:
        return None
    rate = inv['rate']
    if rate['kind'] == 'PERCENT_CDI':
        if not cdi:
            return None
        factor = 1.0
        for d, v in cdi.items():
            if start <= d < today:
                factor *= 1 + rate['value'] / 100 * v / 100
    else:
        factor = (1 + rate['value'] / 100) ** (_business_days(start, today) / 252)
    return {'value': round(inv['balance'] * factor, 2), 'as_of': start}


def divergence(value, est):
    """Diferença relativa do valor digitado para o estimado, se passar da tolerância."""
    if not est or not est['value']:
        return None
    diff = (value - est['value']) / est['value']
    return diff if abs(diff) > TOLERANCE else None
