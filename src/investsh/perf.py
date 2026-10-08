"""Rentabilidade da carteira descontando aportes, comparada ao CDI e ao IPCA.

Cada save grava uma foto em data/history.json com o saldo total e o total investido.
Entre duas fotos consecutivas, o rendimento é calculado pelo método de Dietz
modificado: (saldo final - saldo inicial - aportes) / (saldo inicial + aportes/2),
supondo os aportes no meio do período. Os períodos são encadeados por mês, nos
últimos 12 meses e desde a primeira foto com total investido.

CDI e IPCA são acumulados exatamente no mesmo intervalo de datas, para a
comparação ser justa. "% do CDI" = rendimento da carteira / rendimento do CDI.
"""
import calendar
from datetime import date, timedelta


def _day(s):
    return date.fromisoformat(s[:10])


def periods(history):
    """Períodos entre fotos consecutivas que têm total investido."""
    by_date = {}
    for s in history:
        if s.get('totalInvested') is not None and s.get('date'):
            by_date[_day(s['date'])] = s      # mesmo dia: vale a última foto
    snaps = [by_date[d] for d in sorted(by_date)]
    out = []
    for a, b in zip(snaps, snaps[1:]):
        flow = b['totalInvested'] - a['totalInvested']
        # Custo de ativos em dólar é guardado em R$ pela cotação do dia: a variação
        # cambial do custo não é aporte e sai do fluxo.
        if a.get('totalInvestedUSD') is not None and a.get('dollarRate') and b.get('dollarRate'):
            flow -= a['totalInvestedUSD'] * (b['dollarRate'] - a['dollarRate'])
        base = a['total'] + flow / 2
        if base <= 0:
            continue
        out.append({
            'start': _day(a['date']), 'end': _day(b['date']), 'flow': flow,
            'r': (b['total'] - a['total'] - flow) / base,
        })
    return out


def cdi_return(cdi, start, end):
    """CDI acumulado em (start, end]: `cdi` = {data: taxa diária em %}."""
    f = 1.0
    for d, rate in cdi.items():
        if start < d <= end:
            f *= 1 + rate / 100
    return f - 1


def ipca_return(ipca, start, end):
    """IPCA acumulado em (start, end], proporcional aos dias corridos de cada mês.

    `ipca` = {(ano, mês): variação mensal em %}. Retorna (valor, completo), em que
    completo=False indica mês ainda não divulgado (o valor cobre só o que existe);
    valor None = nenhum mês do período divulgado ainda.
    """
    f, complete, covered = 1.0, True, False
    d = start + timedelta(days=1)
    while d <= end:
        days_in_month = calendar.monthrange(d.year, d.month)[1]
        month_end = date(d.year, d.month, days_in_month)
        n = (min(end, month_end) - d).days + 1
        rate = ipca.get((d.year, d.month))
        if rate is None:
            complete = False
        else:
            covered = True
            f *= (1 + rate / 100) ** (n / days_in_month)
        d = month_end + timedelta(days=1)
    return (f - 1 if covered else None), complete


# "% do CDI" só para períodos com pelo menos tantos dias (28: inclui fevereiro)
MIN_DAYS_PCT_CDI = 28


def _row(ps, cdi, ipca):
    portfolio = 1.0
    for p in ps:
        portfolio *= 1 + p['r']
    start, end = ps[0]['start'], ps[-1]['end']
    row = {'start': start, 'end': end, 'portfolio': portfolio - 1,
           'cdi': None, 'ipca': None, 'ipca_complete': True, 'pct_cdi': None}
    if cdi is not None:
        c = 1.0
        for p in ps:
            c *= 1 + cdi_return(cdi, p['start'], p['end'])
        row['cdi'] = c - 1
        # Em poucos dias o CDI rende quase nada e a razão explode (ex.: -1,6% / 0,2%
        # = -800%): só faz sentido a partir de ~1 mês.
        if row['cdi'] > 0 and (end - start).days >= MIN_DAYS_PCT_CDI:
            row['pct_cdi'] = row['portfolio'] / row['cdi']
    if ipca is not None:
        i, complete, covered = 1.0, True, False
        for p in ps:
            v, ok = ipca_return(ipca, p['start'], p['end'])
            if v is not None:
                i *= 1 + v
                covered = True
            complete = complete and ok
        row['ipca'], row['ipca_complete'] = (i - 1 if covered else None), complete
    return row


def summary(history, cdi, ipca, today):
    """Rentabilidade por mês, nos últimos 12 meses e desde o início.

    `cdi`/`ipca` None = indicador indisponível (ex.: sem internet). Retorna None se
    o histórico ainda não tem dois saves com total investido.
    """
    ps = periods(history)
    if not ps:
        return None
    # Cada período conta no mês em que cai o seu meio (onde está a maior parte dos
    # dias): com saves no dia 1º, 01/09 → 01/10 é setembro, não outubro.
    months = {}
    for p in ps:
        mid = p['start'] + (p['end'] - p['start']) / 2
        months.setdefault((mid.year, mid.month), []).append(p)
    rows = []
    for (y, m), group in sorted(months.items()):
        row = _row(group, cdi, ipca)
        row.update(year=y, month=m)
        rows.append(row)
    cutoff = today - timedelta(days=365)
    recent = [p for p in ps if p['end'] > cutoff]
    return {
        'months': rows,
        'last_12m': _row(recent, cdi, ipca) if recent else None,
        'since_start': _row(ps, cdi, ipca),
    }


# ── Exibição (compartilhada entre a TUI e o --menu) ──────────────────────────

MESES = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
WIDTHS = (34, 10, 10, 10, 10)


def load(today):
    """Lê o histórico da pasta de dados e busca CDI/IPCA. Retorna (resumo, nota)."""
    import json
    import os
    from . import bench, config
    try:
        with open(os.path.join(config.ROOT, 'data', 'history.json'), encoding='utf-8') as f:
            history = json.load(f)
    except (FileNotFoundError, ValueError):
        history = []
    ps = periods(history)
    if not ps:
        return None, None
    start = ps[0]['start']
    cdi, ipca = bench.cdi(start, today), bench.ipca(start, today)
    missing = [n for n, v in (('CDI', cdi), ('IPCA', ipca)) if v is None]
    note = None if not missing else \
        f'{"/".join(missing)} indisponíve{"is" if len(missing) > 1 else "l"} ' \
        f'(sem conexão com o Banco Central e sem cache)'
    return summary(history, cdi, ipca, today), note


def _pct(v, plus=True):
    if v is None:
        return '—'
    return f'{v * 100:+.2f}%' if plus else f'{v * 100:.0f}%'


def table(s, note=None):
    """Linhas da tabela: lista de [(texto, tipo)], tipo em title/header/sep/label/pos/neg/dim."""
    lines = [[('Rentabilidade descontando aportes', 'title')]]
    if s is None:
        lines.append([('Precisa de dois saves com total investido para calcular '
                       '(cada save grava uma foto da carteira).', 'dim')])
        return lines

    def cells(label, row):
        out = [(label.ljust(WIDTHS[0]), 'label')]
        p = row['portfolio']
        out.append((_pct(p).rjust(WIDTHS[1]), 'pos' if p >= 0 else 'neg'))
        out.append((_pct(row['cdi']).rjust(WIDTHS[2]), 'dim'))
        ipca = _pct(row['ipca']) + ('*' if not row['ipca_complete'] else '')
        out.append((ipca.rjust(WIDTHS[3]), 'dim'))
        pc = row['pct_cdi']
        out.append((_pct(pc, plus=False).rjust(WIDTHS[4]),
                    'dim' if pc is None else ('pos' if pc >= 1 else 'neg')))
        return out

    def header(first):
        cols = (first.ljust(WIDTHS[0]), 'Carteira'.rjust(WIDTHS[1]), 'CDI'.rjust(WIDTHS[2]),
                'IPCA'.rjust(WIDTHS[3]), '% do CDI'.rjust(WIDTHS[4]))
        return [(''.join(cols), 'header')]

    sep = [('─' * sum(WIDTHS), 'sep')]
    st = s['since_start']
    ipca_available = not note or 'IPCA' not in note
    days = (st['end'] - st['start']).days
    lines += [[], header('Período'), sep,
              cells(f'Desde {st["start"]:%d/%m/%Y} ({days} dias)', st)]
    if s['last_12m'] and s['last_12m']['start'] != st['start']:
        lines.append(cells('Últimos 12 meses', s['last_12m']))
    lines += [[], header('Mês'), sep]
    for m in reversed(s['months'][-12:]):
        lines.append(cells(f'{MESES[m["month"]]}/{m["year"]}', m))
    incomplete = ipca_available and any(not r['ipca_complete'] for r in [st, *s['months']])
    lines.append([])
    if incomplete:
        lines.append([('* IPCA dos meses ainda não divulgados fica de fora do acumulado.', 'dim')])
    if any(r['cdi'] and r['pct_cdi'] is None for r in [st, *s['months']]):
        lines.append([(f'% do CDI só em períodos de {MIN_DAYS_PCT_CDI} dias ou mais '
                       '(em poucos dias a comparação não tem significado).', 'dim')])
    lines.append([('Rendimento entre saves pelo método de Dietz modificado; CDI e IPCA '
                   'no mesmo período (Banco Central).', 'dim')])
    if note:
        lines.append([(note, 'neg')])
    return lines
