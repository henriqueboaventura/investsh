"""IR e IOF da renda fixa: quanto se resgataria hoje e a taxa líquida no vencimento.

Tabela regressiva do IR sobre o ganho (saldo − custo), pelo prazo desde a compra:
22,5% até 180 dias, 20% até 360, 17,5% até 720 e 15% acima. IOF regressivo sobre o
ganho nos primeiros 29 dias. Isentos (LCA, LCI, taxExempt) pagam zero.

Sem `purchaseDate`, o prazo conta da primeira foto do histórico com o ativo: é uma
aproximação (o prazo real é maior, então o IR mostrado pode ficar acima do real) e
a tela marca com "≈". Fundos, ETFs e ações têm regras próprias e ficam de fora.
"""
from datetime import date

from .core import asset_key

FIXED_INCOME = ('CDB', 'LCA', 'LCI', 'LC', 'RDB', 'Tesouro Direto', 'Debênture', 'CRI', 'CRA')

# IOF regressivo: % do ganho no dia 1..29 de aplicação (dia 30 em diante: zero)
IOF = [96, 93, 90, 86, 83, 80, 76, 73, 70, 66, 63, 60, 56, 53, 50, 46, 43, 40, 36, 33,
       30, 26, 23, 20, 16, 13, 10, 6, 3]


def ir_rate(days):
    """Alíquota do IR (fração) pelo prazo em dias corridos."""
    if days <= 180:
        return 0.225
    if days <= 360:
        return 0.20
    if days <= 720:
        return 0.175
    return 0.15


def iof_rate(days):
    """Alíquota do IOF (fração do ganho) pelo prazo em dias corridos."""
    return IOF[days - 1] / 100 if 1 <= days < 30 else (1.0 if days <= 0 else 0.0)


def applies(inv):
    """Renda fixa em reais (o cálculo é sobre `invested`, em R$)."""
    return inv.get('category') in FIXED_INCOME and 'investedUSD' not in inv


def exempt(inv):
    return bool(inv.get('taxExempt')) or inv.get('category') in ('LCA', 'LCI', 'CRI', 'CRA')


def purchase(inv, history):
    """(data da compra, aproximada?) — purchaseDate ou a primeira foto com o ativo."""
    try:
        if inv.get('purchaseDate'):
            return date.fromisoformat(inv['purchaseDate']), False
    except ValueError:
        pass
    key = asset_key(inv)
    dates = [s.get('date') for s in history
             if any((a.get('name'), a.get('broker')) == key for a in s.get('assets') or [])]
    dates = [d for d in dates if d]
    try:
        return (date.fromisoformat(min(dates)), True) if dates else (None, True)
    except ValueError:
        return None, True


def redeem_today(inv, history, today):
    """{'gross', 'gain', 'ir', 'iof', 'net', 'ir_rate', 'days', 'approx'} ou None.

    None quando não dá para calcular (fora da renda fixa em R$ ou sem custo).
    """
    if not applies(inv):
        return None
    gross, cost = inv.get('balance') or 0.0, inv.get('invested')
    if not isinstance(cost, (int, float)) or cost <= 0:
        return None
    bought, approx = purchase(inv, history)
    days = (today - bought).days if bought else None
    gain = max(gross - cost, 0.0)
    if exempt(inv):
        rate, iof = 0.0, 0.0
    else:
        rate = ir_rate(days if days is not None else 0)
        # IOF só com a data real da compra: a aproximação poderia inventar um IOF de 90%
        iof = gain * iof_rate(days) if days is not None and not approx else 0.0
    ir = (gain - iof) * rate
    return {'gross': gross, 'gain': gain, 'ir': round(ir, 2), 'iof': round(iof, 2),
            'net': round(gross - ir - iof, 2), 'ir_rate': rate, 'days': days, 'approx': approx}


def net_rate(inv, history, today):
    """Taxa líquida de IR no vencimento: (tipo, valor) ou None.

    % do CDI e prefixado: taxa × (1 − alíquota do prazo total). Para o prefixado é uma
    aproximação (o IR incide no ganho acumulado, não na taxa anual). Sem vencimento,
    vale a alíquota do prazo até hoje. IPCA+ não tem equivalente simples: None.
    """
    rate = inv.get('rate') or {}
    if rate.get('kind') not in ('PERCENT_CDI', 'ANNUAL_FIXED') or not applies(inv):
        return None
    if not isinstance(rate.get('value'), (int, float)):
        return None
    if exempt(inv):
        return rate['kind'], rate['value']
    bought, _ = purchase(inv, history)
    end = None
    if inv.get('maturity'):
        try:
            end = date.fromisoformat(inv['maturity'])
        except ValueError:
            end = None
    days = ((end or today) - bought).days if bought else 0
    return rate['kind'], rate['value'] * (1 - ir_rate(days))


def rate_label(kind, value):
    v = f'{value:.2f}'.rstrip('0').rstrip('.').replace('.', ',')
    return f'{v}% CDI' if kind == 'PERCENT_CDI' else f'{v}% a.a.' if kind == 'ANNUAL_FIXED' else f'IPCA+{v}%'
