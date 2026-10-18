"""Regras da carteira: classificação, custo base, reserva, histórico e formatação."""
import json, os

from . import config


CRYPTO_IDS  = {'Bitcoin':'bitcoin','Ethereum':'ethereum','Dogecoin':'dogecoin','XRP':'ripple'}


BROKER_ORDER = {'XP':0,'Nubank':1,'Nomad':2,'Binance':3}


CAT_ORDER    = {
    'CDB':0,'LCA':1,'LCI':2,'Tesouro Direto':3,'Previdência Privada':4,
    'ETF':5,'Fundo Imobiliário':6,'Fundos de Investimento':7,'Crypto':8,
}


TYPE_ORDER   = {'POS':0,'PRE':1,'IPCA':2,'Ouro':3}


def sort_key(inv):
    return (
        BROKER_ORDER.get(inv.get('broker',''), 99),
        CAT_ORDER.get(inv.get('category',''), 99),
        TYPE_ORDER.get(inv.get('type') or '', 99),
        inv.get('name',''),
    )


# allocationGroup é a fonte de verdade da classificação de cada ativo.
GROUP_META = {
    'RF_CDI':             {'main': 'Renda Fixa',        'label': 'CDI',                  'ideal': 'rfCDI'},
    'RF_PRE':              {'main': 'Renda Fixa',        'label': 'Pré-Fixado',           'ideal': 'rfPre'},
    'RF_IPCA':             {'main': 'Renda Fixa',        'label': 'IPCA',                 'ideal': 'rfIPCA'},
    'RESERVA_EMERGENCIA':  {'main': 'Renda Fixa',        'label': 'Reserva de Emergência','ideal': None},
    'CAIXA_TRANSITORIA':   {'main': 'Renda Fixa',        'label': 'Caixa Transitória',    'ideal': None},
    'RF_EXTERIOR':         {'main': 'Renda Fixa',        'label': 'RF Exterior (USD)',    'ideal': 'rfExterior'},
    'RV_ETF_BRASIL':       {'main': 'Renda Variável',    'label': 'ETF Brasil',           'ideal': 'rvETFBrasil'},
    'RV_ETF_EXTERIOR':     {'main': 'Renda Variável',    'label': 'ETF Exterior',         'ideal': 'rvETFExterior'},
    'RV_OURO':             {'main': 'Renda Variável',    'label': 'Ouro',                 'ideal': 'rvOuro'},
    'RV_FUNDOS_ACOES':     {'main': 'Renda Variável',    'label': 'Fundos de Ações',      'ideal': 'rvFundosAcoes'},
    'RV_FII':              {'main': 'Renda Variável',    'label': 'FII',                  'ideal': 'rvFII'},
    'RV_CRYPTO':           {'main': 'Renda Variável',    'label': 'Crypto',               'ideal': 'rvCrypto'},
    'MULTIATIVO_GLOBAL':   {'main': 'Multiativo Global', 'label': 'Multiativo Global',    'ideal': None},
    'PREVIDENCIA':         {'main': 'Previdência',       'label': 'Previdência',          'ideal': None},
}


def asset_key(inv):
    """Identifica o ativo: o mesmo nome pode existir em corretoras diferentes."""
    return (inv.get('name', ''), inv.get('broker', ''))


def balances_by_key(investments):
    """Saldo de cada ativo por asset_key (base do previousBalance no save)."""
    return {asset_key(i): i['balance'] for i in investments}


def classify(inv):
    meta = GROUP_META.get(inv.get('allocationGroup'))
    if meta:
        return meta['main'], meta['label']
    return 'Outros', inv.get('category', '') or '—'


def cost_basis(inv, dolar):
    """Custo base em BRL, ou None se desconhecido. Crypto usa quantity × averagePrice
    (baseline no valor atual quando o preço de compra real não está disponível — ex.
    extratos da Binance sem histórico)."""
    if inv.get('category') == 'Crypto':
        qty, ap = inv.get('quantity'), inv.get('averagePrice')
        return qty * ap if qty is not None and ap is not None else None
    if 'investedUSD' in inv:
        return inv['investedUSD'] * dolar
    return inv.get('invested')


def total_invested(data):
    """Soma do custo base (aportes líquidos) de todos os ativos com custo base conhecido."""
    dolar = data.get('dollarRate', 1)
    t = 0.0
    for inv in data['investments']:
        cb = cost_basis(inv, dolar)
        if cb is not None:
            t += cb
    return t


def is_reserva_asset(inv, data):
    cfg = data.get('emergencyReserve')
    if cfg and cfg.get('assetNames'):
        return inv.get('name') in cfg['assetNames']
    return inv.get('allocationGroup') == 'RESERVA_EMERGENCIA'  # fallback sem config explícita


def reserva_excluded(data):
    cfg = data.get('emergencyReserve')
    return cfg.get('excludeFromAllocation', True) if cfg else True


def alloc_investments(data):
    """Ativos considerados na % de alocação — reserva de emergência fica de fora
    (é parte, não faz parte da estratégia de alocação)."""
    invs = data['investments']
    if not reserva_excluded(data):
        return invs
    return [i for i in invs if not is_reserva_asset(i, data)]


def reserva_total(data):
    return sum(i['balance'] for i in data['investments'] if is_reserva_asset(i, data))


def reserva_status(data):
    """(total, mínimo, meta, máximo, texto, status) — status em {'below','above','ok'},
    ou None se sem config/saldo. Cor fica a cargo de quem chama (ANSI vs curses)."""
    cfg = data.get('emergencyReserve')
    total = reserva_total(data)
    if not cfg or total <= 0:
        return None
    mn, tg, mx = cfg.get('minimum', 0), cfg.get('target', 0), cfg.get('maximum', 0)
    if mn and total < mn:
        return (total, mn, tg, mx, f'{brl_fmt(mn - total)} abaixo do mínimo', 'below')
    if mx and total > mx:
        return (total, mn, tg, mx, f'{brl_fmt(total - mx)} acima do máximo — considere investir o excedente', 'above')
    return (total, mn, tg, mx, 'dentro da faixa ideal', 'ok')


IX_LABEL = {
    'CDI': 'CDI', 'SELIC': 'Selic', 'FIXED_RATE': 'Pré-fixado', 'IPCA': 'IPCA',
    'SP_500': 'S&P 500', 'FTSE_GLOBAL_ALL_CAP': 'FTSE Global All Cap',
    'LBMA_GOLD_PRICE': 'Ouro (LBMA)',
    'ICE_0_3_MONTH_US_TREASURY_SECURITIES_INDEX': 'Treasury EUA 0-3m',
    'IAFD': 'IAFD',
}


PURPOSE_LABEL = {
    'RENDA_POS_FIXADA_E_ESTABILIDADE': 'Renda pós-fixada e estabilidade',
    'TRAVAR_TAXA_ATE_O_VENCIMENTO': 'Travar taxa até o vencimento',
    'PROTECAO_INFLACAO_LONGO_PRAZO': 'Proteção inflação longo prazo',
    'RESERVA_EMERGENCIA': 'Reserva de emergência',
    'RESERVA_EMERGENCIA_REMUNERADA': 'Reserva de emergência remunerada',
    'LIQUIDEZ_E_ESTABILIDADE': 'Liquidez e estabilidade',
    'CAIXA_DE_CURTO_PRAZO': 'Caixa de curto prazo',
    'CRESCIMENTO_ACOES_BRASIL_GESTAO_ATIVA': 'Cresc. ações Brasil (gestão ativa)',
    'CRESCIMENTO_ACOES_BRASIL_FUNDAMENTOS': 'Cresc. ações Brasil (fundamentos)',
    'CRESCIMENTO_ACOES_EUA_EM_DOLAR': 'Cresc. ações EUA (USD)',
    'CRESCIMENTO_ACOES_EUA_EM_REAIS': 'Cresc. ações EUA (BRL)',
    'CRESCIMENTO_ACOES_GLOBAIS': 'Crescimento ações globais',
    'DIVERSIFICACAO_GLOBAL_MODERADA': 'Diversificação global moderada',
    'ASSIMETRIA_E_EXPOSICAO_A_CRIPTO': 'Assimetria e exposição a cripto',
    'PROTECAO_OURO_E_CAMBIO': 'Proteção ouro e câmbio',
    'PRESERVACAO_CAPITAL_E_LIQUIDEZ_EM_DOLAR': 'Preservação de capital em dólar',
    'RENDA_IMOBILIARIA_HIBRIDA': 'Renda imobiliária híbrida',
    'RENDA_IMOBILIARIA_LOGISTICA': 'Renda imobiliária logística',
    'RENDA_IMOBILIARIA_VIA_FOF': 'Renda imobiliária via FoF',
    'RENDA_IMOBILIARIA_SECURITIES_E_FOF': 'Renda imob. securities e FoF',
    'RENDA_IMOBILIARIA_MULTIESTRATEGIA': 'Renda imob. multiestratégia',
    'APOSENTADORIA_E_LONGO_PRAZO': 'Aposentadoria e longo prazo',
    'RENDA_PREFIXADA_COM_FLUXO_DE_CUPONS': 'Renda prefixada com fluxo de cupons',
}


_CATEGORIES = ['CDB','LCA','LCI','Tesouro Direto','ETF','Fundo Imobiliário','Fundos de Investimento','Previdência Privada','Crypto']


_TYPES      = ['POS','PRE','IPCA','Ouro','(nenhum)']


_BROKERS    = ['XP','Nubank','Nomad','Binance']


_INDEXERS   = ['CDI','SELIC','FIXED_RATE','IPCA','SP_500','FTSE_GLOBAL_ALL_CAP','LBMA_GOLD_PRICE',
               'ICE_0_3_MONTH_US_TREASURY_SECURITIES_INDEX','IAFD']


_ALLOCATION_GROUPS = ['RF_CDI','RF_PRE','RF_IPCA','RF_EXTERIOR','RESERVA_EMERGENCIA','CAIXA_TRANSITORIA',
                      'RV_ETF_BRASIL','RV_ETF_EXTERIOR','RV_OURO','RV_FUNDOS_ACOES','RV_FII','RV_CRYPTO',
                      'MULTIATIVO_GLOBAL','PREVIDENCIA']


_PURPOSES = ['RENDA_POS_FIXADA_E_ESTABILIDADE','TRAVAR_TAXA_ATE_O_VENCIMENTO','PROTECAO_INFLACAO_LONGO_PRAZO',
             'RESERVA_EMERGENCIA','RESERVA_EMERGENCIA_REMUNERADA','LIQUIDEZ_E_ESTABILIDADE','CAIXA_DE_CURTO_PRAZO',
             'CRESCIMENTO_ACOES_BRASIL_GESTAO_ATIVA','CRESCIMENTO_ACOES_BRASIL_FUNDAMENTOS',
             'CRESCIMENTO_ACOES_EUA_EM_DOLAR','CRESCIMENTO_ACOES_EUA_EM_REAIS','CRESCIMENTO_ACOES_GLOBAIS',
             'DIVERSIFICACAO_GLOBAL_MODERADA','ASSIMETRIA_E_EXPOSICAO_A_CRIPTO','PROTECAO_OURO_E_CAMBIO',
             'PRESERVACAO_CAPITAL_E_LIQUIDEZ_EM_DOLAR','RENDA_IMOBILIARIA_HIBRIDA','RENDA_IMOBILIARIA_LOGISTICA',
             'RENDA_IMOBILIARIA_VIA_FOF','RENDA_IMOBILIARIA_SECURITIES_E_FOF','RENDA_IMOBILIARIA_MULTIESTRATEGIA',
             'APOSENTADORIA_E_LONGO_PRAZO', 'RENDA_PREFIXADA_COM_FLUXO_DE_CUPONS']


IDEAL_FIELDS = [
    ('rendaFixa',       'Renda Fixa total'),
    ('rfCDI',           '  CDI / Pós-fixado'),
    ('rfPre',           '  Pré-Fixado'),
    ('rfIPCA',          '  IPCA+'),
    ('rfExterior',      '  RF Exterior (USD)'),
    ('rendaVariavel',   'Renda Variável total'),
    ('rvFII',           '  FII'),
    ('rvETFBrasil',     '  ETF Brasil'),
    ('rvETFExterior',   '  ETF Exterior'),
    ('rvOuro',          '  Ouro'),
    ('rvFundosAcoes',   '  Fundos de Ações'),
    ('rvCrypto',        '  Crypto'),
    ('multiAtivoGlobal','Multiativo Global'),
    ('previdencia',     'Previdência'),
]


def monthly_summary(history):
    """Retorna lista com uma entrada por mês (último registro do mês), ordenada crescente."""
    by_month = {}
    for entry in history:
        month = entry.get('date', '')[:7]  # 'YYYY-MM'
        if month:
            by_month[month] = entry  # sobrescreve — fica o último do mês
    return [by_month[m] for m in sorted(by_month)]


def broker_monthly_series(broker_order, months=12):
    """Retorna (dates, {broker: [totais mensais]}) alinhados, a partir de data/history.json."""
    hist_path = os.path.join(config.ROOT, 'data', 'history.json')
    try:
        with open(hist_path, encoding='utf-8') as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history = []
    monthly = monthly_summary(history) if history else []
    trim    = monthly[-months:]
    dates   = [m.get('date', '') for m in trim]
    series  = {b: [] for b in broker_order}
    for m in trim:
        bsum = {}
        for a in m.get('assets', []):
            b = a.get('broker', '?')
            bsum[b] = bsum.get(b, 0) + (a.get('balance') or 0)
        for b in broker_order:
            series[b].append(bsum.get(b, 0))
    return dates, series


SPARK_BLOCKS = ' ▁▂▃▄▅▆▇█'


def sparkline(values):
    """Mini-gráfico ASCII (1 caractere por valor), escala própria da série."""
    if not values:
        return ''
    lo, hi = min(values), max(values)
    if hi == lo:
        return SPARK_BLOCKS[4] * len(values)
    span = hi - lo
    return ''.join(SPARK_BLOCKS[min(8, int((v - lo) / span * 8) + 1)] for v in values)


def brl_fmt(v):
    s = f'{abs(v):,.2f}'.replace(',','X').replace('.',',').replace('X','.')
    return f'R$ {"-" if v < 0 else ""}{s}'


def investment_snapshot(inv):
    return {
        'name':     inv.get('name'),
        'category': inv.get('category'),
        'type':     inv.get('type'),
        'broker':   inv.get('broker'),
        'maturity': inv.get('maturity'),
        'balance':  round(inv.get('balance', 0), 4),
    }


def history_snapshot(data, total):
    return {
        'date':          data['lastUpdated'],
        'total':         round(total, 4),
        'totalWithFGTS': round(total + data['fgts'], 4),
        'totalInvested': round(total_invested(data), 4),
        # Custo em dólar e câmbio do dia: separam aporte de variação cambial (perf.py)
        'totalInvestedUSD': round(sum(i.get('investedUSD') or 0 for i in data['investments']), 4),
        'dollarRate':    data.get('dollarRate'),
        'assets':        [investment_snapshot(inv) for inv in data['investments']],
    }


def record_flow(data, inv, amount, usd=None, kind=None):
    """Registra dinheiro entrando (+, aporte) ou saindo (-, saque) da carteira.

    Fica em data['flows'] e vai para o disco no save. A rentabilidade (perf.py) usa
    esses lançamentos para separar aporte de rendimento: só o que passa por aqui conta
    como dinheiro novo; atualizar saldo é sempre rendimento (ou transferência entre ativos).

    Provento (dividendo, cupom) pago na conta corrente é uma saída com kind='provento':
    o saldo do ativo já caiu sozinho, e sem o lançamento essa queda contaria como perda.
    """
    from datetime import date as _date
    flow = {'date': _date.today().isoformat(), 'name': inv.get('name', ''),
            'broker': inv.get('broker', ''), 'amount': round(amount, 2)}
    if usd is not None:
        flow['usd'] = round(usd, 4)
    if kind:
        flow['kind'] = kind   # 'provento': dividendo/cupom pago para fora da carteira
    data.setdefault('flows', []).append(flow)
    return flow


def add_to_balance(inv, val, dol):
    """Soma `val` (na moeda do ativo) ao saldo e ao custo. Devolve o valor em R$.

    Base de Registrar aporte e do destino de uma transferência. O previousBalance
    acompanha, para que a variação na tela continue sendo só rendimento.
    """
    if 'investedUSD' in inv:
        inv['investedUSD'] = round(inv.get('investedUSD', 0) + val, 4)
        inv['balanceUSD']  = round(inv.get('balanceUSD', inv['investedUSD'] - val) + val, 4)
        inv['balance']     = round(inv['balanceUSD'] * dol, 4)
        brl = val * dol
    else:
        inv['invested'] = round(inv.get('invested', 0) + val, 2)
        inv['balance']  = round(inv['balance'] + val, 2)
        brl = val
    if 'previousBalance' in inv:
        inv['previousBalance'] = round(inv['previousBalance'] + brl, 4 if 'investedUSD' in inv else 2)
    return brl


def take_from_balance(inv, val, dol):
    """Tira `val` (na moeda do ativo) do saldo; o custo cai na mesma proporção.

    Base de Registrar saque e da origem de uma transferência. Devolve o valor em R$,
    ou None se `val` for maior que o saldo.
    """
    if 'investedUSD' in inv:
        cur = inv.get('balanceUSD', inv.get('investedUSD', 0))
        if val > cur:
            return None
        pct = val / cur if cur else 1.0
        inv['balanceUSD']  = round(cur - val, 4)
        inv['investedUSD'] = round(inv.get('investedUSD', 0) * (1 - pct), 4)
        inv['balance']     = round(inv['balanceUSD'] * dol, 4)
        brl, nd = val * dol, 4
    else:
        cur = inv['balance']
        if val > cur:
            return None
        pct = val / cur if cur else 1.0
        inv['balance'] = round(cur - val, 2)
        if 'invested' in inv:
            inv['invested'] = round(inv['invested'] * (1 - pct), 2)
        brl, nd = val, 2
    if 'previousBalance' in inv:
        inv['previousBalance'] = round(inv['previousBalance'] - brl, nd)
    return brl


def can_transfer(inv):
    """Cripto fica de fora: o saldo vem de quantidade × cotação, sem custo base."""
    return inv.get('category') != 'Crypto'


def transfer(data, src, dst, sent, received):
    """Move dinheiro entre ativos da carteira, sem lançamento (não é aporte nem saque).

    `sent` sai de `src` e `received` entra em `dst`, cada um na moeda do seu ativo.
    Devolve (enviado, recebido) em R$, ou None se `sent` passar do saldo de `src`.
    A diferença entre os dois (dinheiro novo, IR, taxa) fica para quem chama decidir.
    """
    dol = data.get('dollarRate', 1)
    if sent < 0 or received < 0 or src is dst:
        return None
    sent_brl = take_from_balance(src, sent, dol)
    if sent_brl is None:
        return None
    return sent_brl, add_to_balance(dst, received, dol)


def cash_asset(data, broker, usd=False):
    """Caixa da corretora (dinheiro parado esperando reinvestimento); cria se não existir."""
    name = f'Caixa {broker}'
    for inv in data['investments']:
        if asset_key(inv) == (name, broker):
            return inv
    inv = {'name': name, 'category': 'Caixa', 'type': None, 'broker': broker, 'maturity': None,
           'balance': 0.0, 'previousBalance': 0.0, 'indexer': None,
           'purpose': 'CAIXA_DE_CURTO_PRAZO', 'allocationGroup': 'CAIXA_TRANSITORIA',
           'liquidity': 'IMMEDIATE'}
    if usd:
        inv.update(investedUSD=0.0, balanceUSD=0.0)
    else:
        inv['invested'] = 0.0
    data['investments'].append(inv)
    return inv


def rename_asset(data, inv, name, broker):
    """Troca nome e/ou corretora do ativo. Devolve uma mensagem de erro, ou None.

    Os lançamentos do ativo e a lista de ativos da reserva acompanham o nome novo;
    as fotos do histórico ficam como estavam (registram o que era na época).
    """
    name = (name or '').strip()
    old = asset_key(inv)
    if not name:
        return 'O nome não pode ficar vazio'
    if (name, broker) == old:
        return None
    if any(i is not inv and asset_key(i) == (name, broker) for i in data['investments']):
        return f'Já existe {name} na {broker}'
    for f in data.get('flows', []):
        if (f.get('name'), f.get('broker')) == old:
            f['name'], f['broker'] = name, broker
    names = (data.get('emergencyReserve') or {}).get('assetNames')
    if names and old[0] in names and old[0] != name:
        # Só se nenhum outro ativo ainda usa o nome antigo (a lista é por nome)
        if not any(i is not inv and i.get('name') == old[0] for i in data['investments']):
            names[names.index(old[0])] = name
        elif name not in names:
            names.append(name)
    inv['name'], inv['broker'] = name, broker
    return None


def start_flow_log(data):
    """No save: a partir desta data os aportes/saques registrados estão completos."""
    data.setdefault('flows', [])
    data.setdefault('flowsSince', data['lastUpdated'])


def parse_maturity(value):
    """Data de vencimento (AAAA-MM-DD ou DD/MM/AAAA), ou None se ausente/inválida."""
    from datetime import datetime as _dt
    for f in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            return _dt.strptime(str(value), f).date()
        except ValueError:
            continue
    return None


def maturity_alerts(investments, today, days=90):
    """Ativos com saldo que vencem em até `days` dias (ou já venceram), do mais urgente."""
    out = []
    for inv in investments:
        due = parse_maturity(inv.get('maturity')) if inv.get('maturity') else None
        if due is None or not inv.get('balance'):
            continue
        left = (due - today).days
        if left <= days:
            out.append({'name': inv.get('name', ''), 'date': due, 'days': left,
                        'balance': inv['balance'], 'broker': inv.get('broker', '')})
    return sorted(out, key=lambda a: (a['days'], a['name']))
