#!/usr/bin/env python3
"""investsh — carteira de investimentos. Uso: python3 scripts/finances.py [--menu]"""
import json, os, sys, io, contextlib, urllib.request
from datetime import datetime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DATA = os.path.join(ROOT, 'data', 'investments.json')
EXAMPLE = os.path.join(ROOT, 'examples', 'investments.json')

# Commit + push automático em data/ a cada save. Desligado por padrão para não
# publicar dados financeiros por acidente. Ative com FINANCES_AUTO_GIT=1.
AUTO_GIT = os.environ.get('FINANCES_AUTO_GIT', '').lower() in ('1', 'true', 'yes')

# ── ANSI colors ───────────────────────────────────────────────────────────────
G  = '\033[92m'
R  = '\033[91m'
Y  = '\033[93m'
M  = '\033[95m'
C  = '\033[96m'
W  = '\033[97m'
DIM= '\033[2m'
RST= '\033[0m'
BLD= '\033[1m'

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

def fmt(v):
    return f'R$ {v:>12,.2f}'

def gain_str(balance, invested):
    if invested is None or invested == 0:
        return ''
    g   = balance - invested
    pct = (g / invested) * 100
    col = G if g >= 0 else R
    return f'{col}({("+" if g>=0 else "")}{g:,.2f} / {pct:+.1f}%){RST}'

def ask(prompt, default=None, validator=None):
    hint = f' [{default}]' if default is not None else ''
    while True:
        raw = input(f'{C}{prompt}{hint}{RST}: ').strip()
        if raw == '' and default is not None:
            return default
        if raw.lower() in ('s', 'skip', ''):
            return None
        try:
            val = validator(raw) if validator else raw
            return val
        except (ValueError, TypeError):
            print(f'{Y}  Valor inválido. Tente novamente.{RST}')

def ask_float(prompt, default=None):
    return ask(prompt, default, lambda v: float(v.replace(',', '.')))

def ask_yes(prompt):
    r = input(f'{C}{prompt} (s/n){RST}: ').strip().lower()
    return r in ('s', 'sim', 'y', 'yes')

def print_sep(char='─', width=60):
    print(f'{DIM}{char * width}{RST}')

def print_header(text):
    print(f'\n{BLD}{W}▸ {text}{RST}')
    print_sep()

# ── Cotações automáticas ──────────────────────────────────────────────────────
def fetch_rates(data):
    dolar        = data.get('dollarRate', 5.0)
    crypto_prices = {}

    print_header('Cotações Automáticas')

    # USD/BRL
    try:
        with urllib.request.urlopen(
            'https://economia.awesomeapi.com.br/json/last/USD-BRL', timeout=6
        ) as resp:
            fx = json.loads(resp.read())
        dolar = float(fx['USDBRL']['bid'])
        data['dollarRate'] = dolar
        # Recalcula Nomad em BRL imediatamente
        for inv in data['investments']:
            if inv.get('investedUSD') is not None:
                usd_val = inv.get('balanceUSD', inv['investedUSD'])
                inv['balance'] = round(usd_val * dolar, 4)
        print(f'  {G}✓ USD/BRL: {dolar:.4f}{RST}')
    except Exception as e:
        print(f'  {Y}⚠ Dólar indisponível ({e.__class__.__name__}), usando {dolar:.4f}{RST}')

    # Crypto
    cg_ids = ','.join(CRYPTO_IDS.values())
    try:
        url = (f'https://api.coingecko.com/api/v3/simple/price'
               f'?ids={cg_ids}&vs_currencies=brl')
        with urllib.request.urlopen(url, timeout=6) as resp:
            prices = json.loads(resp.read())
        for name, cg_id in CRYPTO_IDS.items():
            if cg_id in prices:
                crypto_prices[name] = prices[cg_id]['brl']
        if crypto_prices:
            items = '  '.join(f'{n}: R$ {p:,.0f}' for n, p in crypto_prices.items())
            print(f'  {G}✓ Crypto: {items}{RST}')
    except Exception as e:
        print(f'  {Y}⚠ Crypto indisponível ({e.__class__.__name__}){RST}')

    return dolar, crypto_prices

# ── Ações ─────────────────────────────────────────────────────────────────────
def do_update(data, dolar, crypto_prices):
    invs = data['investments']
    print_header('Atualizar Saldos')
    print(f'{DIM}  Enter = manter | s = pular | número = novo valor{RST}\n')

    current_broker = None
    for inv in sorted(invs, key=sort_key):
        bal      = inv['balance']
        cat      = inv.get('category') or ''
        typ      = inv.get('type') or ''
        broker   = inv.get('broker', '')
        invested = inv.get('invested')
        inv_usd  = inv.get('investedUSD')
        qty      = inv.get('quantity')

        if broker != current_broker:
            current_broker = broker
            print(f'\n  {M}{BLD}── {broker} ──{RST}')

        if qty is not None:
            inv_str = f'{qty} unid.'
        elif inv_usd is not None:
            inv_str = f'${inv_usd:,.2f} USD'
        elif invested is not None:
            inv_str = fmt(invested)
        else:
            inv_str = '—'

        gs = gain_str(bal, invested)
        print(f'    {W}{inv["name"][:45]:<45}{RST}')
        print(f'    {DIM}  {cat:20} {typ:5} | invest: {inv_str:<18} | saldo: {fmt(bal)} {gs}{RST}')

        if cat == 'Crypto':
            new_qty = ask_float(f'    Qtd.', default=qty)
            if new_qty is not None:
                inv['quantity'] = new_qty
                price = crypto_prices.get(inv['name'])
                if price:
                    inv['balance'] = round(new_qty * price, 4)
                    print(f'    {G}→ BRL: {fmt(inv["balance"])} (@ R$ {price:,.2f}/un){RST}')
                else:
                    print(f'    {Y}⚠ Cotação não disponível, saldo não atualizado.{RST}')

        elif inv_usd is not None:
            cur_usd = inv.get('balanceUSD', inv_usd)
            print(f'    {DIM}  → BRL: {fmt(inv["balance"])} (@ {dolar:.4f}) / Investido: USD {inv_usd:.2f} / Atual: USD {cur_usd:.2f}{RST}')
            new_usd = ask_float(f'    Novo valor USD atual (Enter = manter)', default=None)
            if new_usd is not None:
                inv['balanceUSD'] = new_usd
                inv['balance'] = round(new_usd * dolar, 4)
                print(f'    {G}→ BRL: {fmt(inv["balance"])}{RST}')

        else:
            new_bal = ask_float(f'    Saldo', default=bal)
            if new_bal is not None:
                inv['balance'] = new_bal

        print()


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

def _ask_choice(prompt, options):
    for i, o in enumerate(options):
        print(f'  {DIM}[{i}]{RST} {o}')
    while True:
        raw = input(f'  {C}{prompt}{RST}: ').strip()
        if raw.isdigit() and int(raw) < len(options):
            return options[int(raw)]
        print(f'  {Y}  Digite um número de 0 a {len(options)-1}{RST}')

def do_add(data, dolar):
    invs = data['investments']
    print_header('Adicionar Novo Ativo')
    while True:
        print()
        name = ask('  Nome do ativo')
        if not name:
            break

        print(f'\n  {M}Categoria:{RST}')
        category = _ask_choice('Escolha', _CATEGORIES)
        print(f'\n  {M}Tipo / Subcategoria:{RST}')
        typ_s    = _ask_choice('Escolha', _TYPES)
        typ      = None if typ_s == '(nenhum)' else typ_s
        print(f'\n  {M}Corretora:{RST}')
        broker   = _ask_choice('Escolha', _BROKERS)
        maturity = ask('  Vencimento (YYYY-MM-DD ou Enter para nenhum)', default=None)

        print(f'\n  {M}Indexador:{RST}')
        indexer = _ask_choice('Escolha', _INDEXERS + ['(nenhum)', 'Outro (digitar)'])
        if indexer == 'Outro (digitar)':
            indexer = ask('  Indexador (texto livre)')
        elif indexer == '(nenhum)':
            indexer = None

        print(f'\n  {M}Grupo de Alocação:{RST}')
        allocation_group = _ask_choice('Escolha', _ALLOCATION_GROUPS + ['Outro (digitar)'])
        if allocation_group == 'Outro (digitar)':
            allocation_group = ask('  Grupo de Alocação (texto livre)')

        print(f'\n  {M}Objetivo:{RST}')
        purpose = _ask_choice('Escolha', _PURPOSES + ['Outro (digitar)'])
        if purpose == 'Outro (digitar)':
            purpose = ask('  Objetivo (texto livre)')

        new_inv = {
            'name':            name,
            'category':        category,
            'type':            typ,
            'broker':          broker,
            'maturity':        maturity,
            'indexer':         indexer,
            'purpose':         purpose,
            'allocationGroup': allocation_group,
        }

        if category == 'Crypto':
            qty = ask_float('  Quantidade (unidades)')
            new_inv['quantity'] = qty or 0
            new_inv['balance']  = 0
        elif broker == 'Nomad':
            usd = ask_float('  Valor em USD')
            new_inv['investedUSD'] = usd or 0
            new_inv['balance']     = round((usd or 0) * dolar, 4)
            print(f'  {G}→ BRL: {fmt(new_inv["balance"])}{RST}')
        else:
            invested = ask_float('  Valor investido (custo base)')
            balance  = ask_float('  Saldo atual')
            new_inv['invested'] = invested or 0
            new_inv['balance']  = balance or 0

        invs.append(new_inv)
        print(f'  {G}✓ Ativo adicionado!{RST}')

        if not ask_yes('  Adicionar outro?'):
            break


def do_update_single(data, dolar, crypto_prices):
    invs = sorted(data['investments'], key=sort_key)
    print_header('Atualizar Ativo Específico')

    # Busca por nome ou número
    q = input(f'{C}  Buscar (nome ou número){RST}: ').strip()
    if not q:
        return

    # Filtra por número ou substring case-insensitive
    if q.isdigit():
        idx = int(q)
        matches = [invs[idx]] if idx < len(invs) else []
    else:
        ql = q.lower()
        matches = [i for i in invs if ql in i['name'].lower()]

    if not matches:
        print(f'  {Y}Nenhum ativo encontrado para "{q}".{RST}')
        # Lista para ajudar
        print(f'\n{DIM}  Ativos disponíveis:{RST}')
        for i, inv in enumerate(invs):
            print(f'  {DIM}[{i:2d}]{RST} {inv.get("broker",""):<8} {inv["name"][:45]}')
        return

    if len(matches) > 1:
        print(f'\n  {Y}Múltiplos ativos encontrados:{RST}')
        for i, inv in enumerate(matches):
            print(f'  {DIM}[{i}]{RST} {inv.get("broker",""):<8} {inv["name"][:45]}  {fmt(inv["balance"])}')
        sel = input(f'\n  {C}Número(s) separados por vírgula (Enter = todos){RST}: ').strip()
        if sel:
            idxs = {int(x.strip()) for x in sel.split(',') if x.strip().isdigit()}
            matches = [matches[i] for i in sorted(idxs) if i < len(matches)]

    print(f'{DIM}  Enter = manter | s = pular | número = novo valor{RST}\n')
    for inv in matches:
        bal      = inv['balance']
        cat      = inv.get('category') or ''
        typ      = inv.get('type') or ''
        broker   = inv.get('broker', '')
        invested = inv.get('invested')
        inv_usd  = inv.get('investedUSD')
        qty      = inv.get('quantity')

        if qty is not None:
            inv_str = f'{qty} unid.'
        elif inv_usd is not None:
            inv_str = f'${inv_usd:,.2f} USD'
        elif invested is not None:
            inv_str = fmt(invested)
        else:
            inv_str = '—'

        gs = gain_str(bal, invested)
        print(f'  {M}{BLD}── {broker} ──{RST}')
        print(f'    {W}{inv["name"][:45]:<45}{RST}')
        print(f'    {DIM}  {cat:20} {typ:5} | invest: {inv_str:<18} | saldo: {fmt(bal)} {gs}{RST}')

        if cat == 'Crypto':
            new_qty = ask_float(f'    Qtd.', default=qty)
            if new_qty is not None:
                inv['quantity'] = new_qty
                price = crypto_prices.get(inv['name'])
                if price:
                    inv['balance'] = round(new_qty * price, 4)
                    print(f'    {G}→ BRL: {fmt(inv["balance"])} (@ R$ {price:,.2f}/un){RST}')
                else:
                    print(f'    {Y}⚠ Cotação não disponível, saldo não atualizado.{RST}')

        elif inv_usd is not None:
            cur_usd = inv.get('balanceUSD', inv_usd)
            print(f'    {DIM}  → BRL: {fmt(inv["balance"])} (@ {dolar:.4f}) / Investido: USD {inv_usd:.2f} / Atual: USD {cur_usd:.2f}{RST}')
            new_usd = ask_float(f'    Novo valor USD atual (Enter = manter)', default=None)
            if new_usd is not None:
                inv['balanceUSD'] = new_usd
                inv['balance'] = round(new_usd * dolar, 4)
                print(f'    {G}→ BRL: {fmt(inv["balance"])}{RST}')

        else:
            new_bal = ask_float(f'    Saldo', default=bal)
            if new_bal is not None:
                inv['balance'] = new_bal

        print()


def do_aporte(data):
    invs = data['investments']
    print_header('Registrar Aporte')
    sorted_invs = sorted(invs, key=sort_key)
    for i, inv in enumerate(sorted_invs):
        if inv.get('category') == 'Crypto':
            continue
        cat = inv.get('category', '') or '—'
        if 'investedUSD' in inv:
            inv_str = f'${inv["investedUSD"]:,.2f} USD'
        elif 'invested' in inv:
            inv_str = fmt(inv['invested'])
        else:
            continue
        print(f'  {DIM}[{i:2d}]{RST} {inv.get("broker",""):<8} {inv["name"][:38]:<38} {DIM}custo base: {inv_str}{RST}')

    raw = input(f'\n  {C}Número do ativo (Enter = cancelar){RST}: ').strip()
    if not raw or not raw.isdigit():
        return
    idx = int(raw)
    if idx >= len(sorted_invs):
        print(f'  {Y}Índice inválido.{RST}')
        return

    inv = sorted_invs[idx]
    if inv.get('category') == 'Crypto':
        print(f'  {Y}Crypto não suporta aporte (sem custo base).{RST}')
        return

    dol = data.get('dollarRate', 1)
    if 'investedUSD' in inv:
        cur_usd = inv.get('investedUSD', 0)
        val = ask_float(f'  Aporte em USD (custo base atual: ${cur_usd:,.2f})')
        if val and val > 0:
            inv['investedUSD'] = round(cur_usd + val, 4)
            inv['balanceUSD']  = round(inv.get('balanceUSD', cur_usd) + val, 4)
            inv['balance']     = round(inv['balanceUSD'] * dol, 4)
            if 'previousBalance' in inv:
                inv['previousBalance'] = round(inv['previousBalance'] + val * dol, 4)
            print(f'  {G}✓ Custo base: ${cur_usd:,.2f} + ${val:,.2f} = ${inv["investedUSD"]:,.2f} USD{RST}')
            print(f'  {G}✓ Saldo BRL:  {fmt(inv["balance"])}{RST}')
    elif 'invested' in inv:
        cur = inv.get('invested', 0)
        cur_bal = inv.get('balance', 0)
        val = ask_float(f'  Aporte em R$ (custo base atual: {fmt(cur)})')
        if val and val > 0:
            inv['invested'] = round(cur + val, 2)
            inv['balance']  = round(cur_bal + val, 2)
            if 'previousBalance' in inv:
                inv['previousBalance'] = round(inv['previousBalance'] + val, 2)
            print(f'  {G}✓ Custo base: {fmt(cur)} + {fmt(val)} = {fmt(inv["invested"])}{RST}')
            print(f'  {G}✓ Saldo:      {fmt(cur_bal)} + {fmt(val)} = {fmt(inv["balance"])}{RST}')
    else:
        print(f'  {Y}Ativo sem campo de custo base.{RST}')


def do_saque(data):
    invs = data['investments']
    print_header('Registrar Saque')
    sorted_invs = sorted(invs, key=sort_key)
    for i, inv in enumerate(sorted_invs):
        if inv.get('category') == 'Crypto':
            continue
        if 'investedUSD' in inv:
            bal_str = f'${inv.get("balanceUSD", 0):,.2f} USD'
        else:
            bal_str = fmt(inv['balance'])
        print(f'  {DIM}[{i:2d}]{RST} {inv.get("broker",""):<8} {inv["name"][:38]:<38} {DIM}saldo: {bal_str}{RST}')

    raw = input(f'\n  {C}Número do ativo (Enter = cancelar){RST}: ').strip()
    if not raw or not raw.isdigit():
        return
    idx = int(raw)
    if idx >= len(sorted_invs):
        print(f'  {Y}Índice inválido.{RST}')
        return

    inv = sorted_invs[idx]
    if inv.get('category') == 'Crypto':
        print(f'  {Y}Crypto: ajuste a quantidade diretamente em "Atualizar ativo".{RST}')
        return

    if 'investedUSD' in inv:
        cur_bal_usd = inv.get('balanceUSD', inv.get('investedUSD', 0))
        val = ask_float(f'  Valor sacado em USD (saldo atual: ${cur_bal_usd:,.2f})')
        if not val or val <= 0:
            return
        if val > cur_bal_usd:
            print(f'  {Y}Valor maior que o saldo disponível.{RST}')
            return
        pct = val / cur_bal_usd
        inv['balanceUSD']  = round(cur_bal_usd - val, 4)
        inv['investedUSD'] = round(inv.get('investedUSD', 0) * (1 - pct), 4)
        inv['balance']     = round(inv['balanceUSD'] * data.get('dollarRate', 1), 4)
        print(f'  {G}✓ Saque: ${val:,.2f} USD ({pct*100:.1f}% do saldo){RST}')
        print(f'  {G}✓ Novo saldo: ${inv["balanceUSD"]:,.2f} USD | Custo base: ${inv["investedUSD"]:,.2f} USD{RST}')
    else:
        cur_bal = inv['balance']
        val = ask_float(f'  Valor sacado em R$ (saldo atual: {fmt(cur_bal)})')
        if not val or val <= 0:
            return
        if val > cur_bal:
            print(f'  {Y}Valor maior que o saldo disponível.{RST}')
            return
        pct = val / cur_bal
        old_invested = inv.get('invested', 0)
        inv['balance'] = round(cur_bal - val, 2)
        if 'invested' in inv:
            inv['invested'] = round(old_invested * (1 - pct), 2)
        if 'previousBalance' in inv:
            inv['previousBalance'] = round(inv['previousBalance'] - val, 2)
        if 'invested' in inv:
            print(f'  {G}✓ Saque: {fmt(val)} ({pct*100:.1f}% do saldo){RST}')
            print(f'  {G}✓ Novo saldo: {fmt(inv["balance"])} | Custo base: {fmt(old_invested)} → {fmt(inv["invested"])}{RST}')
        else:
            print(f'  {G}✓ Saque: {fmt(val)} | Novo saldo: {fmt(inv["balance"])}{RST}')


def do_remove(data):
    invs = data['investments']
    print_header('Remover Ativo')
    sorted_invs = sorted(invs, key=sort_key)
    for i, inv in enumerate(sorted_invs):
        print(f'  {DIM}[{i:2d}]{RST} {inv.get("broker",""):<8} {inv["name"][:40]:<40} {fmt(inv["balance"])}')
    raw = input(f'\n  {C}Números separados por vírgula (Enter = cancelar){RST}: ').strip()
    if raw:
        to_remove = set()
        for x in raw.split(','):
            x = x.strip()
            if x.isdigit():
                idx = int(x)
                if idx < len(sorted_invs):
                    to_remove.add(sorted_invs[idx]['name'])
        data['investments'] = [inv for inv in invs if inv['name'] not in to_remove]
        for n in to_remove:
            print(f'  {R}✗ Removido: {n}{RST}')


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

def do_params(data):
    print_header('Parâmetros')

    print(f'\n  {M}FGTS{RST}')
    print(f'  Valor atual: {W}{fmt(data["fgts"])}{RST}')
    novo_fgts = ask_float('  Novo valor (Enter = manter)', default=data['fgts'])
    if novo_fgts is not None:
        data['fgts'] = novo_fgts
        print(f'  {G}✓ FGTS {fmt(novo_fgts)}{RST}')

    p = data['projectionParams']
    print(f'\n  {M}Projeção{RST}')
    print(f'  Rendimento mensal:     {W}{p["monthlyReturn"]*100:.2f}%{RST}')
    print(f'  Aporte mensal:         {W}{fmt(p["monthlyContribution"])}{RST}')
    print(f'  Rendimento FGTS a.a.:  {W}{p.get("fgtsAnnualReturn", 0.0605)*100:.2f}%{RST}')

    nr = ask_float(f'  Novo rendimento % (Enter = manter)', default=p['monthlyReturn']*100)
    if nr is not None:
        p['monthlyReturn'] = nr / 100
        print(f'  {G}✓ Rendimento {nr:.2f}%{RST}')

    na = ask_float(f'  Novo aporte mensal (Enter = manter)', default=p['monthlyContribution'])
    if na is not None:
        p['monthlyContribution'] = na
        print(f'  {G}✓ Aporte {fmt(na)}{RST}')

    nf = ask_float(f'  Novo rendimento FGTS a.a. % (Enter = manter)', default=p.get('fgtsAnnualReturn', 0.0605)*100)
    if nf is not None:
        p['fgtsAnnualReturn'] = nf / 100
        print(f'  {G}✓ Rendimento FGTS {nf:.2f}%{RST}')

    ia = data.setdefault('idealAllocation', {})
    print(f'\n  {M}Metas de alocação (Enter = manter){RST}')
    for key, label in IDEAL_FIELDS:
        cur = ia.get(key, 0.0)
        val = ask_float(f'  {label:<26} atual {cur:.1f}%', default=cur)
        if val is not None and val != cur:
            ia[key] = round(val, 1)
            print(f'  {G}✓ {label.strip()}: {val:.1f}%{RST}')

    er = data.setdefault('emergencyReserve', {})
    print(f'\n  {M}Reserva de Emergência (Enter = manter){RST}')
    for key, label in (('minimum', 'Mínimo'), ('target', 'Meta'), ('maximum', 'Máximo')):
        cur = er.get(key, 0.0)
        val = ask_float(f'  {label:<26} atual {fmt(cur)}', default=cur)
        if val is not None and val != cur:
            er[key] = val
            print(f'  {G}✓ {label}: {fmt(val)}{RST}')


def do_view(data):
    invs  = data['investments']
    total = sum(i['balance'] for i in invs)
    fgts  = data.get('fgts', 0)
    ideal = data.get('idealAllocation', {})
    dolar = data.get('dollarRate', 1)

    # ── Resumo ────────────────────────────────────────────────────────────────
    print_header('Resumo')
    prev_total   = sum(i.get('previousBalance', i['balance']) for i in invs)
    t_inv        = total_invested(data)
    inv_com_hist = 0.0
    for i in invs:
        cb = cost_basis(i, dolar)
        if cb is not None and abs(i['balance'] - cb) > 0.01:
            inv_com_hist += cb
    valorizacao  = total - t_inv
    val_pct      = valorizacao / inv_com_hist * 100 if inv_com_hist else 0
    month_gain   = total - prev_total
    month_pct    = month_gain / prev_total * 100 if prev_total else 0
    vcol = G if valorizacao >= 0 else R
    mcol = G if month_gain  >= 0 else R

    print(f'  Total:          {W}{brl_fmt(total):>16}{RST}')
    print(f'  Total c/ FGTS:  {W}{brl_fmt(total + fgts):>16}{RST}')
    print(f'  Total aportado: {DIM}{brl_fmt(t_inv):>16}{RST}')
    print(f'  Valorização:    {vcol}{brl_fmt(valorizacao):>16}  ({val_pct:+.1f}%){RST}')
    print(f'  Variação mês:   {mcol}{brl_fmt(month_gain):>16}  ({month_pct:+.1f}%){RST}')

    # ── Alocação ──────────────────────────────────────────────────────────────
    print_header('Alocação')

    cls_ideal_key = {
        'Renda Fixa':        'rendaFixa',
        'Renda Variável':    'rendaVariavel',
        'Multiativo Global': 'multiAtivoGlobal',
        'Previdência':       'previdencia',
    }
    sub_ideal_key = {
        'CDI':             'rfCDI',
        'Pré-Fixado':      'rfPre',
        'IPCA':            'rfIPCA',
        'RF Exterior (USD)': 'rfExterior',
        'FII':             'rvFII',
        'Fundos de Ações': 'rvFundosAcoes',
        'ETF Brasil':      'rvETFBrasil',
        'ETF Exterior':    'rvETFExterior',
        'Ouro':            'rvOuro',
        'Crypto':          'rvCrypto',
    }
    cls_col = {'Renda Fixa': C, 'Renda Variável': G, 'Multiativo Global': Y, 'Previdência': M, 'Outros': Y}

    alloc_invs  = alloc_investments(data)
    alloc_total = sum(i['balance'] for i in alloc_invs)

    groups = {}
    for inv in alloc_invs:
        cls, sub = classify(inv)
        groups.setdefault(cls, {}).setdefault(sub, 0)
        groups[cls][sub] += inv['balance']

    print(f'  {DIM}{"Categoria/Sub":<30}  {"Saldo":>14}  {"Atual":>6}  {"Ideal":>6}  {"Diff":>6}{RST}')
    print_sep(width=70)

    for cls in ['Renda Fixa', 'Renda Variável', 'Multiativo Global', 'Previdência', 'Outros']:
        if cls not in groups:
            continue
        cls_total = sum(groups[cls].values())
        cls_pct   = cls_total / alloc_total * 100 if alloc_total else 0
        cls_ideal = ideal.get(cls_ideal_key.get(cls, ''), 0)
        diff      = cls_pct - cls_ideal
        dcol      = (G if abs(diff) < 2 else R) if cls_ideal else DIM
        col       = cls_col.get(cls, W)
        ideal_s   = f'{cls_ideal:.1f}%' if cls_ideal else '—'
        diff_s    = f'{diff:+.1f}%'     if cls_ideal else '—'

        print(f'  {col}{BLD}{cls:<30}{RST}  {W}{brl_fmt(cls_total):>14}{RST}  {cls_pct:>5.1f}%  {DIM}{ideal_s:>6}{RST}  {dcol}{diff_s:>6}{RST}')

        for sub, sub_bal in sorted(groups[cls].items(), key=lambda x: -x[1]):
            sub_pct   = sub_bal / alloc_total * 100 if alloc_total else 0
            sub_ideal = ideal.get(sub_ideal_key.get(sub, ''), 0)
            diff_sub  = sub_pct - sub_ideal
            dcol_sub  = (G if abs(diff_sub) < 2 else R) if sub_ideal else DIM
            ideal_s2  = f'{sub_ideal:.1f}%' if sub_ideal else '—'
            diff_s2   = f'{diff_sub:+.1f}%' if sub_ideal else '—'

            print(f'  {DIM}  {sub:<28}{RST}  {brl_fmt(sub_bal):>14}  {sub_pct:>5.1f}%  {DIM}{ideal_s2:>6}{RST}  {dcol_sub}{diff_s2:>6}{RST}')

    rs = reserva_status(data)
    if rs:
        rtotal, mn, tg, mx, msg, kind = rs
        col = {'below': R, 'above': Y, 'ok': G}[kind]
        print_header('Reserva de Emergência')
        print(f'  {col}{brl_fmt(rtotal)}{RST}  '
              f'{DIM}(mín {brl_fmt(mn)} · meta {brl_fmt(tg)} · máx {brl_fmt(mx)}){RST}')
        print(f'  {col}{msg}{RST}')

    # ── Exposição por indexador ──────────────────────────────────────────────
    print_header('Exposição por Indexador')
    idx_agg = {}
    for inv in invs:
        raw = inv.get('indexer')
        k   = IX_LABEL.get(raw, raw) if raw else 'Sem indexador'
        idx_agg[k] = idx_agg.get(k, 0) + inv['balance']
    for k, bal in sorted(idx_agg.items(), key=lambda x: -x[1]):
        pct = bal / total * 100 if total else 0
        print(f'  {W}{k:<22}{RST}  {brl_fmt(bal):>14}  {pct:>5.1f}%')

    # ── Por objetivo financeiro ───────────────────────────────────────────────
    print_header('Por Objetivo Financeiro')
    pur_agg = {}
    for inv in invs:
        raw = inv.get('purpose')
        k   = PURPOSE_LABEL.get(raw, raw) if raw else 'Sem objetivo'
        pur_agg[k] = pur_agg.get(k, 0) + inv['balance']
    for k, bal in sorted(pur_agg.items(), key=lambda x: -x[1]):
        pct = bal / total * 100 if total else 0
        print(f'  {W}{k:<36}{RST}  {brl_fmt(bal):>14}  {pct:>5.1f}%')

    # ── Evolução por corretora ───────────────────────────────────────────────
    broker_order = sorted(set(i.get('broker', '') for i in invs) - {''},
                          key=lambda b: BROKER_ORDER.get(b, 99))
    dates, series = broker_monthly_series(broker_order)
    if len(dates) >= 2 and broker_order:
        print_header('Evolução por Corretora')
        span = f'{dates[0][:7]} → {dates[-1][:7]}'
        print(f'  {DIM}{span}{RST}')
        for b in broker_order:
            vals = series[b]
            first, last = vals[0], vals[-1]
            d    = last - first
            dpct = d / first * 100 if first else 0
            col  = G if d >= 0 else R
            print(f'  {W}{b:<10}{RST} {C}{sparkline(vals)}{RST}  '
                  f'{brl_fmt(last):>14}  {col}{"+" if d >= 0 else ""}{dpct:.1f}%{RST}')

    # ── Ativos por corretora ──────────────────────────────────────────────────
    print_header('Ativos por Corretora')

    current_broker = None
    for inv in sorted(invs, key=sort_key):
        broker = inv.get('broker', '')
        if broker != current_broker:
            current_broker = broker
            broker_total = sum(i['balance'] for i in invs if i.get('broker') == broker)
            print(f'\n  {M}{BLD}── {broker}  {brl_fmt(broker_total)} ({broker_total/total*100 if total else 0:.1f}%) ──{RST}')
            print(f'  {DIM}{"Nome":<40}  {"Categoria":<22}  {"Saldo":>14}  Ganho%  Δ Mês{RST}')
            print_sep(width=95)

        bal  = inv['balance']
        prev = inv.get('previousBalance', bal)
        _, sub = classify(inv)

        cb = cost_basis(inv, dolar)
        if cb:
            g   = bal - cb
            gp  = g / cb * 100
            col = G if g >= 0 else R
            gain_disp = f'{col}{gp:+.1f}%{RST}'
        else:
            gain_disp = f'{DIM}—{RST}'

        md = bal - prev
        md_disp = f'{DIM}—{RST}' if abs(md) < 0.01 else (
            f'{G if md >= 0 else R}{("+" if md >= 0 else "")}{brl_fmt(md)}{RST}'
        )

        cat_str = inv.get('category', '') or '—'
        print(f'  {inv["name"][:40]:<40}  {DIM}{cat_str:<22}{RST}  {brl_fmt(bal):>14}  {gain_disp}  {md_disp}')

    print()


def run_tui(data, crypto_prices=None):
    """Full-screen TUI: browse, search, and edit investments."""
    import curses
    crypto_prices = crypto_prices or {}

    pre_balances = {i['name']: i['balance'] for i in data['investments']}
    total_before = [sum(pre_balances.values())]
    status_msg   = ['']  # shown in bottom bar after save
    dirty        = [False]  # True quando há alterações não salvas

    # Migrate Nomad assets: add balanceUSD if missing
    dol = data.get('dollarRate', 1)
    for inv in data['investments']:
        if inv.get('investedUSD') is not None and 'balanceUSD' not in inv:
            inv['balanceUSD'] = round(inv['balance'] / dol, 4) if dol else inv['investedUSD']

    # ── helpers ───────────────────────────────────────────────────────────────

    def curs_input(stdscr, prompt, default='', numeric=False):
        """Bottom-bar text input. Enter → value ('' if empty). Esc → None."""
        h, w = stdscr.getmaxyx()
        curses.curs_set(1)
        buf = list(str(default) if default != '' else '')
        pos = len(buf)
        while True:
            text = ''.join(buf)
            bar  = f' {prompt}: {text} '
            try:
                stdscr.addstr(h - 1, 0, ' ' * (w - 1), curses.A_REVERSE)
                stdscr.addstr(h - 1, 0, bar[:w - 1], curses.A_REVERSE)
                stdscr.move(h - 1, min(len(f' {prompt}: ') + pos, w - 2))
            except curses.error:
                pass
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (10, 13, curses.KEY_ENTER):
                curses.curs_set(0)
                val = ''.join(buf).strip()
                if numeric:
                    if not val:
                        return default if default != '' else 0.0
                    try:
                        return float(val.replace(',', '.'))
                    except ValueError:
                        buf = list(str(default)); pos = len(buf); continue
                return val
            elif ch == 27:
                curses.curs_set(0)
                return None
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                if pos > 0:
                    buf.pop(pos - 1); pos -= 1
            elif ch == curses.KEY_LEFT:
                pos = max(0, pos - 1)
            elif ch == curses.KEY_RIGHT:
                pos = min(len(buf), pos + 1)
            elif 32 <= ch < 256:
                c = chr(ch)
                if not numeric or c in '0123456789.,':
                    buf.insert(pos, c); pos += 1

    def popup_menu(stdscr, title, options):
        """Centered popup em janela própria. Returns key or None (Esc)."""
        h, w    = stdscr.getmaxyx()
        inner   = max(len(title), max(len(f' [{k}] {l} ') for k, l in options))
        pw, ph  = inner + 4, len(options) + 4
        py, px  = max(1, (h - ph) // 2), max(0, (w - pw) // 2)

        # Janela separada: ao fechar, o curses redesenha o que estava por baixo
        # (touchwin), sem precisar salvar/restaurar caracteres manualmente.
        win = curses.newwin(max(1, min(ph, h - py)), max(1, min(pw, w - px)), py, px)
        win.keypad(True)

        sel    = 0
        result = None
        while True:
            try:
                win.addstr(0, 0, '┌' + '─' * (pw - 2) + '┐')
                win.addstr(1, 0, '│' + ' ' * (pw - 2) + '│')
                win.addstr(1, 1 + (pw - 2 - len(title)) // 2, title, curses.A_BOLD)
                win.addstr(2, 0, '├' + '─' * (pw - 2) + '┤')
                for i, (k, lbl) in enumerate(options):
                    row = 3 + i
                    win.addstr(row, 0, '│' + ' ' * (pw - 2) + '│')
                    label = f' [{k}] {lbl} '
                    attr  = curses.A_REVERSE | curses.A_BOLD if i == sel else 0
                    win.addstr(row, 1, label[:pw - 2], attr)
                win.addstr(3 + len(options), 0, '└' + '─' * (pw - 2) + '┘')
            except curses.error:
                pass
            win.refresh()
            ch = win.getch()
            if ch in (10, 13, curses.KEY_ENTER):
                result = options[sel][0]; break
            elif ch == 27:
                result = None; break
            elif ch in (curses.KEY_UP, ord('k')):
                sel = max(0, sel - 1)
            elif ch in (curses.KEY_DOWN, ord('j')):
                sel = min(len(options) - 1, sel + 1)
            elif 0 <= ch < 256:
                for k, _ in options:
                    if chr(ch) == k:
                        result = k; break
                else:
                    continue
                break

        del win
        stdscr.touchwin()
        stdscr.refresh()

        return result

    # ── actions ───────────────────────────────────────────────────────────────

    def act_update_balance(stdscr, inv):
        cat = inv.get('category', '')
        if cat == 'Crypto':
            val = curs_input(stdscr, f'Qtd  {inv["name"]}', default=inv.get('quantity', 0), numeric=True)
            if val is None: return False
            inv['quantity'] = val
            price = crypto_prices.get(inv['name'])
            if price:
                inv['balance'] = round(val * price, 4)
            dirty[0] = True
        elif 'investedUSD' in inv:
            cur_usd = inv.get('balanceUSD', inv['investedUSD'])
            val = curs_input(stdscr, f'USD atual  {inv["name"][:30]}', default=cur_usd, numeric=True)
            if val is None: return False
            inv['balanceUSD'] = val
            inv['balance']    = round(val * data.get('dollarRate', 1), 4)
            dirty[0] = True
        else:
            val = curs_input(stdscr, f'Saldo  {inv["name"][:33]}', default=inv['balance'], numeric=True)
            if val is None: return False
            inv['balance'] = val
            dirty[0] = True
        return True

    def act_aporte(stdscr, inv):
        cat = inv.get('category', '')
        if cat == 'Crypto':
            return False  # crypto não tem custo base
        dol = data.get('dollarRate', 1)
        if 'investedUSD' in inv:
            cur_usd = inv.get('investedUSD', 0)
            val = curs_input(stdscr, f'Aporte USD  {inv["name"][:30]}', default=0.0, numeric=True)
            if val is None or val <= 0: return False
            inv['investedUSD'] = round(cur_usd + val, 4)
            inv['balanceUSD']  = round(inv.get('balanceUSD', cur_usd) + val, 4)
            inv['balance']     = round(inv['balanceUSD'] * dol, 4)
            if 'previousBalance' in inv:
                inv['previousBalance'] = round(inv['previousBalance'] + val * dol, 4)
            dirty[0] = True
        else:
            cur = inv.get('invested', 0)
            val = curs_input(stdscr, f'Aporte R$  {inv["name"][:33]}', default=0.0, numeric=True)
            if val is None or val <= 0: return False
            inv['invested'] = round(cur + val, 2)
            inv['balance']  = round(inv['balance'] + val, 2)
            if 'previousBalance' in inv:
                inv['previousBalance'] = round(inv['previousBalance'] + val, 2)
            dirty[0] = True
        return True

    def act_saque(stdscr, inv):
        cat = inv.get('category', '')
        if cat == 'Crypto':
            return False  # crypto: ajuste pela quantidade
        dol = data.get('dollarRate', 1)
        if 'investedUSD' in inv:
            cur_bal_usd = inv.get('balanceUSD', inv.get('investedUSD', 0))
            val = curs_input(stdscr, f'Saque USD  {inv["name"][:30]}', default=0.0, numeric=True)
            if val is None or val <= 0 or val > cur_bal_usd: return False
            pct = val / cur_bal_usd
            inv['balanceUSD']  = round(cur_bal_usd - val, 4)
            inv['investedUSD'] = round(inv.get('investedUSD', 0) * (1 - pct), 4)
            inv['balance']     = round(inv['balanceUSD'] * dol, 4)
            if 'previousBalance' in inv:
                inv['previousBalance'] = round(inv['previousBalance'] - val * dol, 4)
            dirty[0] = True
        else:
            cur_bal = inv['balance']
            val = curs_input(stdscr, f'Saque R$  {inv["name"][:33]}', default=0.0, numeric=True)
            if val is None or val <= 0 or val > cur_bal: return False
            pct = val / cur_bal
            inv['balance']  = round(cur_bal - val, 2)
            if 'invested' in inv:
                inv['invested'] = round(inv['invested'] * (1 - pct), 2)
            if 'previousBalance' in inv:
                inv['previousBalance'] = round(inv['previousBalance'] - val, 2)
            dirty[0] = True
        return True

    def act_delete(stdscr, inv):
        choice = popup_menu(stdscr, inv['name'][:32], [
            ('s', 'Sim, excluir'),
            ('n', 'Cancelar'),
        ])
        if choice == 's':
            data['investments'] = [i for i in data['investments'] if i is not inv]
            dirty[0] = True
            return True
        return False

    CATEGORIES = [
        'CDB', 'LCA', 'LCI', 'Tesouro Direto', 'ETF',
        'Fundo Imobiliário', 'Fundos de Investimento',
        'Previdência Privada', 'Crypto',
    ]
    TYPES = ['POS', 'PRE', 'IPCA', 'Ouro', '(nenhum)']
    BROKERS = ['XP', 'Nubank', 'Nomad', 'Binance']
    INDEXERS = _INDEXERS + ['(nenhum)', 'Outro (digitar)']
    ALLOCATION_GROUPS = _ALLOCATION_GROUPS + ['Outro (digitar)']
    PURPOSES = _PURPOSES + ['Outro (digitar)']

    def act_new_asset(stdscr):
        name = curs_input(stdscr, 'Nome do ativo')
        if not name: return False

        cat_choice = popup_menu(stdscr, 'Categoria',
                                [(str(i), c) for i, c in enumerate(CATEGORIES)])
        if cat_choice is None: return False
        category = CATEGORIES[int(cat_choice)]

        typ_choice = popup_menu(stdscr, 'Tipo / Subcategoria',
                                [(str(i), t) for i, t in enumerate(TYPES)])
        if typ_choice is None: return False
        typ_s = TYPES[int(typ_choice)]
        typ = None if typ_s == '(nenhum)' else typ_s

        broker_choice = popup_menu(stdscr, 'Corretora',
                                   [(str(i), b) for i, b in enumerate(BROKERS)])
        if broker_choice is None: return False
        broker = BROKERS[int(broker_choice)]

        maturity_s = curs_input(stdscr, 'Vencimento YYYY-MM-DD  (Enter = nenhum)', default='')
        maturity = maturity_s.strip() if maturity_s else None

        idx_choice = popup_menu(stdscr, 'Indexador',
                                [(str(i), v) for i, v in enumerate(INDEXERS)])
        if idx_choice is None: return False
        indexer = INDEXERS[int(idx_choice)]
        if indexer == 'Outro (digitar)':
            indexer = curs_input(stdscr, 'Indexador')
            if indexer is None: return False
            indexer = indexer.strip() or None
        elif indexer == '(nenhum)':
            indexer = None

        grp_choice = popup_menu(stdscr, 'Grupo de Alocação',
                                [(str(i), v) for i, v in enumerate(ALLOCATION_GROUPS)])
        if grp_choice is None: return False
        allocation_group = ALLOCATION_GROUPS[int(grp_choice)]
        if allocation_group == 'Outro (digitar)':
            allocation_group = curs_input(stdscr, 'Grupo de Alocação')
            if not allocation_group: return False
            allocation_group = allocation_group.strip()

        pur_choice = popup_menu(stdscr, 'Objetivo',
                                [(str(i), v) for i, v in enumerate(PURPOSES)])
        if pur_choice is None: return False
        purpose = PURPOSES[int(pur_choice)]
        if purpose == 'Outro (digitar)':
            purpose = curs_input(stdscr, 'Objetivo')
            if purpose is None: return False
            purpose = purpose.strip() or None

        new_inv = {
            'name': name, 'category': category, 'type': typ, 'broker': broker, 'maturity': maturity,
            'indexer': indexer, 'purpose': purpose, 'allocationGroup': allocation_group,
        }

        if category == 'Crypto':
            qty = curs_input(stdscr, 'Quantidade', default=0.0, numeric=True)
            if qty is None: return False
            new_inv['quantity'] = qty
            new_inv['balance']  = 0.0
        elif broker == 'Nomad':
            invested_usd = curs_input(stdscr, 'Custo base USD', default=0.0, numeric=True)
            if invested_usd is None: return False
            cur_usd = curs_input(stdscr, 'Valor atual USD', default=invested_usd, numeric=True)
            if cur_usd is None: return False
            new_inv['investedUSD'] = invested_usd
            new_inv['balanceUSD']  = cur_usd
            new_inv['balance']     = round(cur_usd * data.get('dollarRate', 1), 4)
        else:
            invested = curs_input(stdscr, 'Custo base', default=0.0, numeric=True)
            if invested is None: return False
            balance = curs_input(stdscr, 'Saldo atual', default=0.0, numeric=True)
            if balance is None: return False
            new_inv['invested'] = invested
            new_inv['balance']  = balance

        data['investments'].append(new_inv)
        pre_balances[name] = new_inv['balance']
        dirty[0] = True
        return True

    def act_params(stdscr):
        fgts = curs_input(stdscr, 'FGTS', default=data.get('fgts', 0), numeric=True)
        if fgts is None: return False
        data['fgts'] = fgts

        p  = data['projectionParams']
        mr = curs_input(stdscr, 'Rendimento mensal %', default=round(p['monthlyReturn'] * 100, 2), numeric=True)
        if mr is None: return False
        p['monthlyReturn'] = mr / 100

        mc = curs_input(stdscr, 'Aporte mensal', default=p['monthlyContribution'], numeric=True)
        if mc is None: return False
        p['monthlyContribution'] = mc

        fa = curs_input(stdscr, 'Rendimento FGTS a.a. %',
                         default=round(p.get('fgtsAnnualReturn', 0.0605) * 100, 2), numeric=True)
        if fa is None: return False
        p['fgtsAnnualReturn'] = fa / 100

        ia = data.setdefault('idealAllocation', {})
        for key, label in IDEAL_FIELDS:
            cur = ia.get(key, 0.0)
            val = curs_input(stdscr, f'Meta {label.strip()} %', default=cur, numeric=True)
            if val is None: return False
            ia[key] = round(val, 1)

        er = data.setdefault('emergencyReserve', {})
        for key, label in (('minimum', 'Reserva mínima'), ('target', 'Reserva meta'), ('maximum', 'Reserva máxima')):
            cur = er.get(key, 0.0)
            val = curs_input(stdscr, label, default=cur, numeric=True)
            if val is None: return False
            er[key] = val

        dirty[0] = True
        return True

    def act_update_all(stdscr):
        invs  = sorted(data['investments'], key=sort_key)
        dolar = data.get('dollarRate', 1)
        total = len(invs)
        BOLD  = curses.A_BOLD
        DIM   = curses.A_DIM
        REV   = curses.A_REVERSE

        for idx, inv in enumerate(invs):
            h, w = stdscr.getmaxyx()
            stdscr.erase()

            name    = inv['name']
            broker  = inv.get('broker', '')
            cat     = inv.get('category', '')
            bal     = inv['balance']
            qty     = inv.get('quantity')
            inv_usd = inv.get('investedUSD')
            invested = inv.get('invested')
            _, sub  = classify(inv)

            # header
            pat = sum(i['balance'] for i in data['investments'])
            hdr = f' Atualizar Saldos   {idx+1}/{total}   {brl_fmt(pat)} '
            try:
                stdscr.addstr(0, 0, ' ' * (w - 1), REV)
                stdscr.addstr(0, 0, hdr[:w], REV | BOLD)
            except curses.error: pass

            # asset info
            y = 2
            def put(text, attr=0):
                nonlocal y
                try: stdscr.addstr(y, 4, text[:w - 6], attr)
                except curses.error: pass
                y += 1

            put(f'{broker}  ·  {sub}', DIM)
            put(name, BOLD)
            y += 1
            if qty is not None:
                put(f'Quantidade atual:   {qty}')
            elif inv_usd is not None:
                cur_usd = inv.get('balanceUSD', inv_usd)
                put(f'Investido:  USD {inv_usd:.2f}   Atual: USD {cur_usd:.2f}')
                put(f'Em BRL:  {brl_fmt(bal)}   (@ {dolar:.4f})', DIM)
            else:
                put(f'Saldo atual:   {brl_fmt(bal)}')
                if invested:
                    g  = bal - invested
                    gp = g / invested * 100 if invested else 0
                    put(f'Investido:  {brl_fmt(invested)}   Ganho: {brl_fmt(g)} ({gp:+.1f}%)', DIM)

            # preview of next assets
            if idx + 1 < total:
                y += 1
                try: stdscr.addstr(y, 4, '── próximos ──', DIM)
                except curses.error: pass
                y += 1
                for nxt in invs[idx + 1: idx + 4]:
                    try: stdscr.addstr(y, 4, f'{nxt.get("broker",""):<8}  {nxt["name"][:w-18]}', DIM)
                    except curses.error: pass
                    y += 1

            # bottom hint
            try:
                hint = ' Enter = manter valor atual   Esc = parar '
                stdscr.addstr(h - 1, 0, ' ' * (w - 1), REV)
                stdscr.addstr(h - 1, 0, hint[:w - 1], REV)
            except curses.error: pass

            stdscr.refresh()

            # prompt
            if cat == 'Crypto':
                prompt  = f'Qtd  {name[:37]}'
                default = qty if qty is not None else 0.0
            elif inv_usd is not None:
                prompt  = f'USD atual  {name[:32]}'
                default = inv.get('balanceUSD', inv_usd)
            else:
                prompt  = f'Saldo  {name[:35]}'
                default = bal

            val = curs_input(stdscr, prompt, default=default, numeric=True)
            if val is None: break   # Esc = stop early

            if cat == 'Crypto':
                inv['quantity'] = val
            elif inv_usd is not None:
                inv['balanceUSD'] = val
                inv['balance']    = round(val * dolar, 4)
            else:
                inv['balance'] = val
            dirty[0] = True

        return True

    # ── main curses app ───────────────────────────────────────────────────────

    def _app(stdscr):
        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()
        stdscr.keypad(True)

        curses.init_pair(1, curses.COLOR_GREEN,   -1)
        curses.init_pair(2, curses.COLOR_RED,     -1)
        curses.init_pair(3, curses.COLOR_CYAN,    -1)
        curses.init_pair(4, curses.COLOR_MAGENTA, -1)
        curses.init_pair(5, curses.COLOR_YELLOW,  -1)
        curses.init_pair(6, curses.COLOR_BLACK,   curses.COLOR_CYAN)
        curses.init_pair(7, curses.COLOR_BLACK,   curses.COLOR_WHITE)

        GRN  = curses.color_pair(1)
        RED  = curses.color_pair(2)
        CYN  = curses.color_pair(3)
        MAG  = curses.color_pair(4)
        YLW  = curses.color_pair(5)
        HBAR = curses.color_pair(6)
        TABA = curses.color_pair(7)
        BOLD = curses.A_BOLD
        DIM  = curses.A_DIM
        REV  = curses.A_REVERSE

        TABS     = [('s', 'Sumário'), ('a', 'Alocação'), ('i', 'Indexador'), ('o', 'Objetivo'),
                    ('d', 'Detalhe'), ('b', 'Brokers'), ('g', 'Gráficos')]
        TAB_KEYS = {k for k, _ in TABS}

        tab      = ['s']
        scrolls  = {'s': 0, 'a': 0, 'i': 0, 'o': 0, 'd': 0, 'b': 0, 'g': 0}
        search   = ['']
        srch_act = [False]   # search bar open
        det_sel  = [0]       # cursor index into selectbl
        lines    = [[]]      # list of {'segs': [...], 'inv': inv_or_None}
        selectbl = [[]]      # [(line_idx, inv), ...] for navigable rows

        def seg(text, attr=0): return (text, attr)
        def row(segs, inv=None): return {'segs': segs, 'inv': inv}

        # ── builders ──────────────────────────────────────────────────────────

        def build_summary():
            out   = []
            invs  = data['investments']
            total = sum(i['balance'] for i in invs)
            fgts  = data.get('fgts', 0)
            dolar = data.get('dollarRate', 1)
            prev  = sum(i.get('previousBalance', i['balance']) for i in invs)
            t_inv = total_invested(data)
            t_inv_hist = 0.0
            for i in invs:
                cb = cost_basis(i, dolar)
                if cb is not None and abs(i['balance'] - cb) > 0.01:
                    t_inv_hist += cb
            valz  = total - t_inv
            vpct  = valz / t_inv_hist * 100 if t_inv_hist else 0
            month = total - prev
            mpct  = month / prev  * 100 if prev  else 0
            vc    = GRN if valz  >= 0 else RED
            mc    = GRN if month >= 0 else RED

            out += [row([]), row([seg('  Patrimônio', CYN | BOLD)]),
                    row([seg(f'  {brl_fmt(total)}', BOLD)]),
                    row([seg(f'  {brl_fmt(total + fgts)} com FGTS', DIM)]),
                    row([]),
                    row([seg('  Total aportado ', CYN), seg(brl_fmt(t_inv), DIM)]),
                    row([seg('  Valorização    ', CYN), seg(brl_fmt(valz), vc | BOLD), seg(f'  ({vpct:+.1f}%)', vc)]),
                    row([seg('  Variação mês   ', CYN), seg(brl_fmt(month), mc | BOLD), seg(f'  ({mpct:+.1f}%)', mc)]),
                    row([]),
                    row([seg(f'  FGTS:    {brl_fmt(fgts)}', DIM)]),
                    row([seg(f'  Ativos:  {len(invs)}', DIM)]),
                    row([seg(f'  USD/BRL: {dolar:.4f}', DIM)])]
            # Monthly history table
            hist_path = os.path.join(ROOT, 'data', 'history.json')
            try:
                with open(hist_path, encoding='utf-8') as hf:
                    history = json.load(hf)
                monthly = monthly_summary(history)
                if len(monthly) >= 1:
                    out.append(row([]))
                    out.append(row([seg('  Histórico mensal', CYN | BOLD)]))
                    out.append(row([seg(
                        f"  {'Mês':<8}  {'Total':>14}  {'Valorização':>13}  {'Aportes':>13}  {'%':>7}", DIM)]))
                    out.append(row([seg('  ' + '─' * 63, DIM)]))
                    recent = monthly[-12:]
                    for i, h in enumerate(reversed(recent)):
                        prev_h = recent[len(recent) - i - 2] if i < len(recent) - 1 else None
                        prev_t = prev_h['total'] if prev_h else h['total']
                        dt   = h.get('date', '—')[:7]
                        tot  = h.get('total', 0)
                        md   = tot - prev_t
                        mp   = md / prev_t * 100 if prev_t else 0
                        mc2  = GRN if md >= 0 else RED
                        ps   = f'{mp:+.1f}%'

                        if prev_h is not None and 'totalInvested' in h and 'totalInvested' in prev_h:
                            aportes     = h['totalInvested'] - prev_h['totalInvested']
                            valorizacao = md - aportes
                            vc2  = GRN if valorizacao >= 0 else RED
                            apc  = GRN if aportes     >= 0 else RED
                            vs   = f'{("+" if valorizacao>=0 else "")}{brl_fmt(valorizacao)}'
                            aps  = f'{("+" if aportes>=0 else "")}{brl_fmt(aportes)}'
                        else:
                            vc2, apc = DIM, DIM
                            vs, aps  = f'{("+" if md>=0 else "")}{brl_fmt(md)}', 's/dados'

                        out.append(row([
                            seg(f'  {dt:<8}', 0),
                            seg(f'  {brl_fmt(tot):>14}', 0),
                            seg(f'  {vs:>13}', vc2 if i > 0 else DIM),
                            seg(f'  {aps:>13}', apc if i > 0 else DIM),
                            seg(f'  {ps:>7}', mc2 if i > 0 else DIM),
                        ]))
            except (FileNotFoundError, json.JSONDecodeError):
                pass

            # Projection milestones
            p      = data.get('projectionParams', {})
            mr     = p.get('monthlyReturn', 0)
            mc     = p.get('monthlyContribution', 0)
            fa     = p.get('fgtsAnnualReturn', 0.0605)
            fgts_r = (1 + fa) ** (1 / 12) - 1
            milestones = [700_000, 800_000, 1_000_000, 1_500_000, 2_000_000]
            hits_com  = {}   # com FGTS
            hits_sem  = {}   # sem FGTS
            import datetime as _dt
            start  = _dt.date.today()
            inv_v  = total + mc
            fgts_v = fgts
            for mo in range(1, 241):
                year  = start.year + (start.month - 1 + mo) // 12
                month = (start.month - 1 + mo) % 12 + 1
                dt    = f'{year}-{month:02d}'
                com   = inv_v + fgts_v
                sem   = inv_v
                for m in milestones:
                    if m not in hits_com and com >= m:
                        hits_com[m] = (dt, mo)
                    if m not in hits_sem and sem >= m:
                        hits_sem[m] = (dt, mo)
                inv_v  = inv_v  * (1 + mr) + mc
                fgts_v = fgts_v * (1 + fgts_r)

            def fmt_hit(hit):
                if hit[1] is None: return '—'
                return f'{hit[0]} ({hit[1]}m)'

            out.append(row([]))
            out.append(row([seg('  Projeção', CYN | BOLD)]))
            out.append(row([seg(f"  {'Meta':>10}  {'c/ FGTS':<18}  {'s/ FGTS':<18}", DIM)]))
            out.append(row([seg('  ' + '─' * 50, DIM)]))
            for m in milestones:
                label   = f'R$ {m/1e6:.1f}M' if m >= 1_000_000 else f'R$ {m/1e3:.0f}K'
                hit_com = hits_com.get(m, ('—', None))
                hit_sem = hits_sem.get(m, ('—', None))
                col_com = 0   if hit_com[1] else DIM
                col_sem = 0   if hit_sem[1] else DIM
                out.append(row([
                    seg(f'  {label:>10}', 0),
                    seg(f'  {fmt_hit(hit_com):<18}', col_com),
                    seg(f'  {fmt_hit(hit_sem):<18}', col_sem),
                ]))

            return out, []

        def build_allocation():
            out   = []
            invs  = data['investments']
            ideal = data.get('idealAllocation', {})
            alloc_invs  = alloc_investments(data)
            total       = sum(i['balance'] for i in alloc_invs)
            cls_ik = {'Renda Fixa': 'rendaFixa', 'Renda Variável': 'rendaVariavel',
                      'Multiativo Global': 'multiAtivoGlobal', 'Previdência': 'previdencia'}
            sub_ik = {
                'CDI': 'rfCDI', 'Pré-Fixado': 'rfPre', 'IPCA': 'rfIPCA', 'RF Exterior (USD)': 'rfExterior',
                'FII': 'rvFII', 'Fundos de Ações': 'rvFundosAcoes',
                'ETF Brasil': 'rvETFBrasil', 'ETF Exterior': 'rvETFExterior', 'Ouro': 'rvOuro', 'Crypto': 'rvCrypto',
            }
            cls_col = {'Renda Fixa': CYN, 'Renda Variável': GRN, 'Multiativo Global': YLW,
                       'Previdência': MAG, 'Outros': YLW}
            groups  = {}
            for inv in alloc_invs:
                cls, sub = classify(inv)
                groups.setdefault(cls, {}).setdefault(sub, 0)
                groups[cls][sub] += inv['balance']

            out.append(row([]))
            out.append(row([seg(f"  {'Categoria/Sub':<30}  {'Saldo':>14}  {'Atual':>6}  {'Ideal':>6}  {'Diff':>6}", DIM)]))
            out.append(row([seg('  ' + '─' * 65, DIM)]))
            for cls in ['Renda Fixa', 'Renda Variável', 'Multiativo Global', 'Previdência', 'Outros']:
                if cls not in groups: continue
                ct   = sum(groups[cls].values())
                cp   = ct / total * 100 if total else 0
                ci   = ideal.get(cls_ik.get(cls, ''), 0)
                diff = cp - ci
                dc   = GRN if abs(diff) < 2 else RED
                col  = cls_col.get(cls, 0)
                out.append(row([]))
                out.append(row([
                    seg(f'  {cls:<30}', col | BOLD), seg(f'  {brl_fmt(ct):>14}', BOLD),
                    seg(f'  {cp:>5.1f}%', 0),
                    seg(f'  {f"{ci:.1f}%" if ci else "—":>6}', DIM),
                    seg(f'  {f"{diff:+.1f}%" if ci else "—":>6}', dc),
                ]))
                for sub, sb in sorted(groups[cls].items(), key=lambda x: -x[1]):
                    sp  = sb / total * 100 if total else 0
                    si  = ideal.get(sub_ik.get(sub, ''), 0)
                    ds  = sp - si
                    dcs = GRN if abs(ds) < 2 else RED
                    out.append(row([
                        seg(f'    {sub:<28}', DIM), seg(f'  {brl_fmt(sb):>14}', 0),
                        seg(f'  {sp:>5.1f}%', 0),
                        seg(f'  {f"{si:.1f}%" if si else "—":>6}', DIM),
                        seg(f'  {f"{ds:+.1f}%" if si else "—":>6}', dcs),
                    ]))
            rs = reserva_status(data)
            if rs:
                rtotal, mn, tg, mx, msg, kind = rs
                rc = {'below': RED, 'above': YLW, 'ok': GRN}[kind]
                out.append(row([]))
                out.append(row([seg('  ── Reserva de Emergência ──', MAG | BOLD)]))
                out.append(row([seg('  ' + brl_fmt(rtotal), rc | BOLD)]))
                out.append(row([seg(f'  mín {brl_fmt(mn)} · meta {brl_fmt(tg)} · máx {brl_fmt(mx)}', DIM)]))
                out.append(row([seg(f'  {msg}', rc)]))
            return out, []

        def build_detail(query=''):
            out  = []
            sel  = []
            invs = data['investments']
            tot  = sum(i['balance'] for i in invs)
            dol  = data.get('dollarRate', 1)
            q    = query.lower()
            curb = None
            _, tw = stdscr.getmaxyx()
            nw    = max(15, min(40, tw - 1 - 67))
            sepw  = nw + 50
            for inv in sorted(invs, key=sort_key):
                name   = inv.get('name', '')
                broker = inv.get('broker', '')
                _, sub = classify(inv)
                if q and q not in name.lower() and q not in broker.lower() and q not in sub.lower():
                    continue
                if broker != curb:
                    curb = broker
                    bt   = sum(i['balance'] for i in invs if i.get('broker') == broker)
                    out += [row([]),
                            row([seg(f'  ── {broker}  {brl_fmt(bt)} ({bt/tot*100 if tot else 0:.1f}%) ──', MAG | BOLD)]),
                            row([seg(f'  {"Nome":<{nw}}  {"Categoria":<22}  {"Saldo":>14}  {"G%":>7}  {"Δ Mês":>14}', DIM)]),
                            row([seg('  ' + '─' * sepw, DIM)])]
                bal  = inv['balance']
                prev = inv.get('previousBalance', bal)
                cb = cost_basis(inv, dol)
                if cb:
                    g  = bal - cb; gp = g / cb * 100
                    gs = f'{gp:+.1f}%'; gc = GRN if g >= 0 else RED
                else:
                    gs, gc = '—', DIM
                md = bal - prev
                ms = f'{("+" if md>=0 else "")}{brl_fmt(md)}' if abs(md) >= 0.01 else '—'
                mc = (GRN if md >= 0 else RED) if abs(md) >= 0.01 else DIM
                sel.append((len(out), inv))
                out.append(row([
                    seg(f'  {name[:nw]:<{nw}}  ', 0), seg(f'{(inv.get("category","") or "—"):<22}', DIM),
                    seg(f'  {brl_fmt(bal):>14}', 0),
                    seg(f'  {gs:>7}', gc), seg(f'  {ms:>14}', mc),
                ], inv))
            return out, sel

        def build_brokers():
            out  = []
            invs = data['investments']
            tot  = sum(i['balance'] for i in invs)
            agg  = {}
            for inv in invs:
                b = inv.get('broker') or '?'
                agg[b] = agg.get(b, 0) + inv['balance']
            out.append(row([]))
            out.append(row([seg(f"  {'Broker':<12}  {'Saldo':>14}  {'%':>6}  Barra", DIM)]))
            out.append(row([seg('  ' + '─' * 50, DIM)]))
            for b, bal in sorted(agg.items(), key=lambda x: -x[1]):
                pct = bal / tot * 100 if tot else 0
                out.append(row([seg(f'  {b:<12}', CYN), seg(f'  {brl_fmt(bal):>14}', 0),
                                seg(f'  {pct:>5.1f}%  ', 0), seg('█' * int(pct / 2), GRN)]))
            out.append(row([seg('  ' + '─' * 50, DIM)]))
            out.append(row([seg(f'  {"Total":<12}  {brl_fmt(tot):>14}  {"100%":>6}', BOLD)]))
            return out, []

        def build_indexer():
            out  = []
            invs = data['investments']
            tot  = sum(i['balance'] for i in invs)
            agg  = {}
            for inv in invs:
                raw = inv.get('indexer')
                k   = IX_LABEL.get(raw, raw) if raw else 'Sem indexador'
                agg[k] = agg.get(k, 0) + inv['balance']
            out.append(row([]))
            out.append(row([seg(f"  {'Indexador':<22}  {'Saldo':>14}  {'%':>6}  Barra", DIM)]))
            out.append(row([seg('  ' + '─' * 62, DIM)]))
            for k, bal in sorted(agg.items(), key=lambda x: -x[1]):
                pct = bal / tot * 100 if tot else 0
                out.append(row([seg(f'  {k[:22]:<22}', CYN), seg(f'  {brl_fmt(bal):>14}', 0),
                                seg(f'  {pct:>5.1f}%  ', 0), seg('█' * int(pct / 2), GRN)]))
            out.append(row([seg('  ' + '─' * 62, DIM)]))
            out.append(row([seg(f'  {"Total":<22}  {brl_fmt(tot):>14}  {"100%":>6}', BOLD)]))
            return out, []

        def build_purpose():
            out  = []
            invs = data['investments']
            tot  = sum(i['balance'] for i in invs)
            agg  = {}
            for inv in invs:
                raw = inv.get('purpose')
                k   = PURPOSE_LABEL.get(raw, raw) if raw else 'Sem objetivo'
                agg[k] = agg.get(k, 0) + inv['balance']
            out.append(row([]))
            out.append(row([seg(f"  {'Objetivo':<36}  {'Saldo':>14}  {'%':>6}  Barra", DIM)]))
            out.append(row([seg('  ' + '─' * 76, DIM)]))
            for k, bal in sorted(agg.items(), key=lambda x: -x[1]):
                pct = bal / tot * 100 if tot else 0
                out.append(row([seg(f'  {k[:36]:<36}', CYN), seg(f'  {brl_fmt(bal):>14}', 0),
                                seg(f'  {pct:>5.1f}%  ', 0), seg('█' * int(pct / 2), GRN)]))
            out.append(row([seg('  ' + '─' * 76, DIM)]))
            out.append(row([seg(f'  {"Total":<36}  {brl_fmt(tot):>14}  {"100%":>6}', BOLD)]))
            return out, []

        def build_charts():
            out   = []
            invs  = data['investments']
            total = sum(i['balance'] for i in alloc_investments(data))
            ideal = data.get('idealAllocation', {})

            # ── Historical line chart ─────────────────────────────────
            hist_path = os.path.join(ROOT, 'data', 'history.json')
            out.append(row([]))
            out.append(row([seg('  Evolução Patrimonial', CYN | BOLD)]))
            out.append(row([]))
            try:
                with open(hist_path, encoding='utf-8') as hf:
                    history = json.load(hf)
                monthly = monthly_summary(history)
                if len(monthly) >= 2:
                    recent = monthly[-18:]
                    vals   = [h.get('total', 0) for h in recent]
                    dates  = [h.get('date', '')[:7]  for h in recent]
                    n      = len(vals)
                    chart_h = 10
                    col_w   = 4
                    vmin    = min(vals) * 0.97
                    vmax    = max(vals) * 1.01
                    vrange  = vmax - vmin if vmax != vmin else 1

                    def _vrow(v):
                        return int(round((vmax - v) / vrange * (chart_h - 1)))

                    rows_data = [_vrow(v) for v in vals]

                    for r_idx in range(chart_h):
                        y_val = vmax - (r_idx / (chart_h - 1)) * vrange
                        if r_idx in (0, chart_h // 2, chart_h - 1):
                            y_lbl = f'{brl_fmt(y_val):>16}'
                        else:
                            y_lbl = ' ' * 16
                        segs = [seg(f'  {y_lbl} │', DIM)]
                        for c_idx in range(n):
                            cr      = rows_data[c_idx]
                            is_last = (c_idx == n - 1)
                            if cr == r_idx:
                                segs.append(seg('●', (GRN | BOLD) if is_last else (CYN | BOLD)))
                                segs.append(seg(' ' * (col_w - 1), 0))
                            elif c_idx > 0 and min(rows_data[c_idx - 1], cr) < r_idx < max(rows_data[c_idx - 1], cr):
                                segs.append(seg('│' + ' ' * (col_w - 1), DIM))
                            else:
                                segs.append(seg(' ' * col_w, 0))
                        out.append(row(segs))

                    out.append(row([seg('  ' + ' ' * 18 + '└' + '─' * (n * col_w), DIM)]))
                    step        = max(1, n // 6)
                    label_segs  = [seg('  ' + ' ' * 19)]
                    for i, d in enumerate(dates):
                        if i == 0 or i == n - 1 or i % step == 0:
                            label_segs.append(seg((d[5:7] + '/' + d[2:4]).ljust(col_w)[:col_w], DIM))
                        else:
                            label_segs.append(seg(' ' * col_w, 0))
                    out.append(row(label_segs))
                else:
                    out.append(row([seg('  Histórico insuficiente (mínimo 2 meses)', DIM)]))
            except (FileNotFoundError, json.JSONDecodeError):
                out.append(row([seg('  Sem histórico disponível', DIM)]))

            out.append(row([]))
            out.append(row([seg('  ' + '─' * 55, DIM)]))
            out.append(row([]))

            # ── Broker evolution multi-line chart ──────────────────────
            BROKER_COLORS = [CYN, MAG, YLW, GRN]
            broker_order2 = sorted({(i.get('broker') or '?') for i in invs},
                                   key=lambda b: BROKER_ORDER.get(b, 99))
            out.append(row([seg('  Evolução por Corretora', CYN | BOLD)]))
            out.append(row([]))
            b_dates, b_series = broker_monthly_series(broker_order2, months=18)
            if len(b_dates) >= 2 and broker_order2:
                legend_segs = [seg('  ')]
                for i, b in enumerate(broker_order2):
                    bcol = BROKER_COLORS[i % len(BROKER_COLORS)]
                    legend_segs.append(seg('● ', bcol | BOLD))
                    legend_segs.append(seg(f'{b}   ', 0))
                out.append(row(legend_segs))
                out.append(row([]))

                n2       = len(b_dates)
                chart_h2 = 8
                col_w2   = 5
                all_vals = [v for s in b_series.values() for v in s]
                vmin2    = min(all_vals) * 0.95 if all_vals else 0
                vmax2    = max(all_vals) * 1.03 if all_vals else 1
                vrange2  = vmax2 - vmin2 if vmax2 != vmin2 else 1

                def _vrow2(v):
                    return int(round((vmax2 - v) / vrange2 * (chart_h2 - 1)))

                rows_per_broker = {b: [_vrow2(v) for v in b_series[b]] for b in broker_order2}

                for r_idx in range(chart_h2):
                    y_val = vmax2 - (r_idx / (chart_h2 - 1)) * vrange2
                    if r_idx in (0, chart_h2 // 2, chart_h2 - 1):
                        y_lbl = f'{brl_fmt(y_val):>16}'
                    else:
                        y_lbl = ' ' * 16
                    segs = [seg(f'  {y_lbl} │', DIM)]
                    for c_idx in range(n2):
                        hits = [bi for bi, b in enumerate(broker_order2)
                                if rows_per_broker[b][c_idx] == r_idx]
                        if len(hits) == 1:
                            segs.append(seg('●', BROKER_COLORS[hits[0] % len(BROKER_COLORS)] | BOLD))
                        elif len(hits) > 1:
                            segs.append(seg('✚', BOLD))
                        else:
                            segs.append(seg(' ', 0))
                        segs.append(seg(' ' * (col_w2 - 1), 0))
                    out.append(row(segs))

                out.append(row([seg('  ' + ' ' * 18 + '└' + '─' * (n2 * col_w2), DIM)]))
                step2       = max(1, n2 // 6)
                label_segs2 = [seg('  ' + ' ' * 19)]
                for i, d in enumerate(b_dates):
                    if i == 0 or i == n2 - 1 or i % step2 == 0:
                        label_segs2.append(seg((d[5:7] + '/' + d[2:4]).ljust(col_w2)[:col_w2], DIM))
                    else:
                        label_segs2.append(seg(' ' * col_w2, 0))
                out.append(row(label_segs2))
            else:
                out.append(row([seg('  Histórico insuficiente (mínimo 2 meses)', DIM)]))

            out.append(row([]))
            out.append(row([seg('  ' + '─' * 55, DIM)]))
            out.append(row([]))

            # ── Allocation bar chart ──────────────────────────────────
            out.append(row([seg('  Alocação por Subcategoria', CYN | BOLD)]))
            out.append(row([seg(f"  {'Subcategoria':<24}  {'':30}  {'%':>6}  {'Saldo':>16}  Meta", DIM)]))
            out.append(row([]))
            sub_ik  = {
                'CDI': 'rfCDI', 'Pré-Fixado': 'rfPre', 'IPCA': 'rfIPCA', 'RF Exterior (USD)': 'rfExterior',
                'FII': 'rvFII', 'Fundos de Ações': 'rvFundosAcoes',
                'ETF Brasil': 'rvETFBrasil', 'ETF Exterior': 'rvETFExterior', 'Ouro': 'rvOuro', 'Crypto': 'rvCrypto',
            }
            groups  = {}
            for inv in alloc_investments(data):
                _, sub = classify(inv)
                groups[sub] = groups.get(sub, 0) + inv['balance']
            max_bal = max(groups.values()) if groups else 1
            bar_max = 30
            for sub, bal in sorted(groups.items(), key=lambda x: -x[1]):
                pct     = bal / total * 100 if total else 0
                n_bars  = int(bal / max_bal * bar_max) if max_bal else 0
                si      = ideal.get(sub_ik.get(sub, ''), 0)
                diff    = pct - si if si else 0
                bc      = GRN if not si or abs(diff) < 2 else YLW
                dc      = (GRN if abs(diff) < 2 else RED) if si else DIM
                meta_s  = f'  meta {si:.1f}%  ({diff:+.1f}%)' if si else ''
                out.append(row([
                    seg(f'  {sub[:24]:<24}', DIM),
                    seg('█' * n_bars, bc),
                    seg(' ' * (bar_max - n_bars), 0),
                    seg(f'  {pct:>5.1f}%', dc),
                    seg(f'  {brl_fmt(bal):>16}', 0),
                    seg(meta_s, DIM),
                ]))
            return out, []

        builders = {'s': build_summary, 'a': build_allocation, 'i': build_indexer, 'o': build_purpose,
                    'd': lambda: build_detail(search[0]), 'b': build_brokers, 'g': build_charts}

        def refresh():
            t = tab[0]
            out, sel    = builders[t]()
            lines[0]    = out
            selectbl[0] = sel
            scrolls[t]  = 0
            det_sel[0]  = max(0, min(det_sel[0], len(sel) - 1)) if sel else 0

        def ensure_visible(ch):
            if not selectbl[0]: return
            li = selectbl[0][det_sel[0]][0]
            t  = tab[0]
            if li < scrolls[t]:
                scrolls[t] = li
            elif li >= scrolls[t] + ch:
                scrolls[t] = li - ch + 1

        refresh()

        # ── draw / event loop ─────────────────────────────────────────────────
        while True:
            h, w = stdscr.getmaxyx()
            stdscr.erase()
            t = tab[0]

            # top bar
            total    = sum(i['balance'] for i in data['investments'])
            hdr_text = f' investsh   {brl_fmt(total)}   {data["lastUpdated"]}   USD {data["dollarRate"]:.4f} '
            stdscr.addstr(0, 0, ' ' * (w - 1), HBAR)
            try: stdscr.addstr(0, 0, hdr_text[:w], HBAR | BOLD)
            except curses.error: pass

            # tab bar
            tx = 1
            for tk, tlbl in TABS:
                ts   = f' {tlbl} '
                attr = TABA | BOLD if tk == t else DIM
                if tx + len(ts) < w:
                    try: stdscr.addstr(1, tx, ts, attr)
                    except curses.error: pass
                tx += len(ts) + 1

            # content
            content_h = h - 4
            cur_lines = lines[0]
            scroll    = scrolls[t]
            n         = len(cur_lines)
            for i, r in enumerate(cur_lines[scroll:scroll + content_h]):
                y    = 2 + i
                if y >= h - 1: break
                is_s = (t == 'd' and selectbl[0] and det_sel[0] < len(selectbl[0])
                        and selectbl[0][det_sel[0]][0] == scroll + i)
                x = 0
                for txt, attr in r['segs']:
                    if x >= w - 1: break
                    chunk = txt[:w - 1 - x]
                    try: stdscr.addstr(y, x, chunk, (attr | REV) if is_s else attr)
                    except curses.error: pass
                    x += len(chunk)
                if is_s and x < w - 1:
                    try: stdscr.addstr(y, x, ' ' * (w - 1 - x), REV)
                    except curses.error: pass

            # bottom bar
            end = min(scroll + content_h, n)
            pos = f' {scroll+1}-{end}/{n} '
            if status_msg[0]:
                hint = f' {status_msg[0]}'
                status_msg[0] = ''
            elif srch_act[0]:
                hint = f' Buscar: {search[0]}█  Esc limpar  Enter confirmar'
            elif t == 'd':
                hint = ' /buscar  ↑↓ navegar  Enter ação  u atualizar todos  n novo  p params  w salvar  q sair'
            else:
                hint = ' s/a/d/b tabs   j/↓ k/↑ scroll   u atualizar todos   n novo   p params   w salvar   q sair'
            try:
                stdscr.addstr(h - 1, 0, ' ' * (w - 1), REV)
                stdscr.addstr(h - 1, 0, hint[:w - len(pos)], REV)
                stdscr.addstr(h - 1, w - len(pos), pos, REV | BOLD)
            except curses.error: pass

            stdscr.refresh()
            key = stdscr.getch()

            # ── search mode ───────────────────────────────────────────────────
            if srch_act[0]:
                if key == 27:
                    search[0] = ''; srch_act[0] = False; refresh()
                elif key in (10, 13, curses.KEY_ENTER):
                    srch_act[0] = False
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    search[0] = search[0][:-1]
                    out, sel = build_detail(search[0])
                    lines[0] = out; selectbl[0] = sel; det_sel[0] = 0; scrolls['d'] = 0
                elif 32 <= key < 256:
                    search[0] += chr(key)
                    out, sel = build_detail(search[0])
                    lines[0] = out; selectbl[0] = sel; det_sel[0] = 0; scrolls['d'] = 0
                continue

            # ── normal mode ───────────────────────────────────────────────────
            def save_inplace():
                ok, msg = do_save_tui(data, total_before[0], pre_balances)
                pre_balances.clear()
                pre_balances.update({i['name']: i['balance'] for i in data['investments']})
                total_before[0] = sum(pre_balances.values())
                dirty[0] = False
                status_msg[0] = msg
                refresh()

            if key == ord('q'):
                if dirty[0]:
                    choice = popup_menu(stdscr, 'Alterações não salvas', [
                        ('s', 'Salvar e sair'),
                        ('q', 'Sair sem salvar'),
                        ('c', 'Cancelar'),
                    ])
                    if choice == 's':
                        save_inplace(); break
                    elif choice == 'q':
                        break
                else:
                    break
            elif key == curses.KEY_RESIZE:
                pass
            elif key == ord('r'):
                data.clear()
                with open(DATA, encoding='utf-8') as f:
                    data.update(json.load(f))
                refresh()
            elif key == ord('w'):
                choice = popup_menu(stdscr, 'Salvar alterações?', [('s', 'Salvar'), ('c', 'Cancelar')])
                if choice == 's':
                    save_inplace()
            elif key == ord('u'):
                if act_update_all(stdscr): refresh()
            elif key == ord('n'):
                if act_new_asset(stdscr): refresh()
            elif key == ord('p'):
                if act_params(stdscr): refresh()
            elif key == ord('/') and t == 'd':
                srch_act[0] = True
            elif 0 <= key < 256 and chr(key) in TAB_KEYS:
                new = chr(key)
                if new != t:
                    tab[0] = new; search[0] = ''; srch_act[0] = False; refresh()
            elif key in (ord('j'), curses.KEY_DOWN):
                if t == 'd' and selectbl[0]:
                    det_sel[0] = min(det_sel[0] + 1, len(selectbl[0]) - 1)
                    ensure_visible(content_h)
                else:
                    scrolls[t] = min(scrolls[t] + 1, max(0, n - content_h))
            elif key in (ord('k'), curses.KEY_UP):
                if t == 'd' and selectbl[0]:
                    det_sel[0] = max(0, det_sel[0] - 1)
                    ensure_visible(content_h)
                else:
                    scrolls[t] = max(0, scrolls[t] - 1)
            elif key in (curses.KEY_NPAGE, ord(' ')):
                scrolls[t] = min(scrolls[t] + content_h, max(0, n - content_h))
                if t == 'd': det_sel[0] = min(det_sel[0], max(0, len(selectbl[0]) - 1))
            elif key == curses.KEY_PPAGE:
                scrolls[t] = max(0, scrolls[t] - content_h)
                if t == 'd': det_sel[0] = max(0, det_sel[0] - content_h)
            elif key == ord('g'):
                scrolls[t] = 0; det_sel[0] = 0
            elif key == ord('G'):
                scrolls[t] = max(0, n - content_h)
                det_sel[0] = max(0, len(selectbl[0]) - 1)
            elif key in (10, 13, curses.KEY_ENTER) and t == 'd' and selectbl[0]:
                _, inv = selectbl[0][det_sel[0]]
                options = [('u', f'Atualizar saldo  {brl_fmt(inv["balance"])}')]
                if inv.get('category') != 'Crypto':
                    options.append(('a', 'Registrar aporte'))
                    options.append(('s', 'Registrar saque'))
                options += [('x', 'Excluir'), ('c', 'Cancelar')]
                choice = popup_menu(stdscr, inv['name'][:32], options)
                if choice == 'u':
                    if act_update_balance(stdscr, inv): refresh()
                elif choice == 'a':
                    if act_aporte(stdscr, inv): refresh()
                elif choice == 's':
                    if act_saque(stdscr, inv): refresh()
                elif choice == 'x':
                    if act_delete(stdscr, inv):
                        det_sel[0] = max(0, det_sel[0] - 1); refresh()

    curses.wrapper(_app)


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
    hist_path = os.path.join(ROOT, 'data', 'history.json')
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
        'assets':        [investment_snapshot(inv) for inv in data['investments']],
    }

def generate_status_image(data):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec
        import math
    except ImportError:
        print(f'{Y}  pip install matplotlib  →  necessário para imagem{RST}')
        return

    invs  = data['investments']
    total = sum(i['balance'] for i in invs)
    prev  = sum(i.get('previousBalance', i['balance']) for i in invs)
    delta = total - prev
    dpct  = (delta / prev * 100) if prev > 0 else 0
    fgts  = data.get('fgts', 0)
    date  = data.get('lastUpdated', '')
    dolar = data.get('dollarRate', 1)
    sign  = '+' if delta >= 0 else ''

    def alloc_main(inv):
        grp = inv.get('allocationGroup')
        if grp == 'RV_CRYPTO': return 'Crypto'
        meta = GROUP_META.get(grp)
        return meta['main'] if meta else 'Renda Fixa'

    main_alloc = {}
    for i in alloc_investments(data):
        k = alloc_main(i)
        main_alloc[k] = main_alloc.get(k, 0) + i['balance']
    main_alloc  = dict(sorted(main_alloc.items(), key=lambda x: -x[1]))
    alloc_total = sum(main_alloc.values())

    broker_agg = {}
    for i in invs:
        b = i.get('broker', '?')
        broker_agg[b] = broker_agg.get(b, 0) + i['balance']
    broker_agg = dict(sorted(broker_agg.items(), key=lambda x: x[1]))

    hist_path = os.path.join(ROOT, 'data', 'history.json')
    try:
        with open(hist_path, encoding='utf-8') as f:
            history = json.load(f)
    except FileNotFoundError:
        history = []
    monthly    = monthly_summary(history) if history else []
    evo_dates  = [m.get('date', '') for m in monthly[-12:]]
    evo_totals = [m.get('total', 0) for m in monthly[-12:]]

    aportes_now, valorizacao_now = None, None
    if len(monthly) >= 2 and 'totalInvested' in monthly[-1] and 'totalInvested' in monthly[-2]:
        aportes_now     = monthly[-1]['totalInvested'] - monthly[-2]['totalInvested']
        valorizacao_now = delta - aportes_now

    broker_order = sorted(broker_agg.keys(), key=lambda b: BROKER_ORDER.get(b, 99))
    _, broker_series = broker_monthly_series(broker_order)

    def mmyy(d):
        try:
            return datetime.strptime(d, '%Y-%m-%d').strftime('%m/%y')
        except (ValueError, TypeError):
            return d[5:7] + '/' + d[2:4] if len(d) >= 7 else d

    ALLOC_C = {'Renda Fixa':'#3b82f6','Renda Variável':'#0dcea8','Multiativo Global':'#c084fc',
               'Previdência':'#a78bfa','Crypto':'#f59e0b'}
    BR_C    = {'XP':'#3b82f6','Nubank':'#9333ea','Nomad':'#22d3ee','Binance':'#f59e0b'}

    bg    = '#080d1a'
    surf  = '#0f1729'
    textc = '#e8edf5'
    dim   = '#4d6a8a'
    green = '#0dcea8'
    red   = '#f43f5e'
    dcol  = green if delta >= 0 else red

    # Build asset-table rows up front so we can size the figure to fit content.
    rows = []   # (broker, inv_or_None, is_header)
    for broker in sorted(set(i.get('broker','') for i in invs),
                         key=lambda b: BROKER_ORDER.get(b, 99)):
        broker_invs = [i for i in sorted(invs, key=sort_key)
                       if i.get('broker') == broker]
        if not broker_invs:
            continue
        broker_total = sum(i['balance'] for i in broker_invs)
        rows.append(('header', broker, broker_total))
        for inv in broker_invs:
            rows.append(('asset', inv, None))

    n_rows  = len(rows)
    font_sz = max(6.5, min(9.5, 9.5 - max(0, n_rows - 25) * 0.05))

    # ── Portrait layout sized for phone screens ─────────────────────────────
    show_broker_evo = len(evo_dates) >= 2 and len(broker_order) >= 2

    W = 9.0
    h_stats      = 1.75
    h_evo        = 2.15 if len(evo_totals) >= 2 else 0.95
    h_donut      = 1.75 + 0.24 * len(main_alloc)
    h_broker     = 0.75 + 0.34 * max(1, len(broker_agg))
    h_broker_evo = (2.15 if show_broker_evo else 0.95)
    h_table      = 0.65 + 0.225 * (n_rows + 1)
    H = h_stats + h_evo + h_donut + h_broker + h_broker_evo + h_table + 0.3

    fig = plt.figure(figsize=(W, H), facecolor=bg, dpi=130)
    gs  = GridSpec(6, 1, figure=fig,
                   left=0.03, right=0.97, top=0.995, bottom=0.005,
                   hspace=0.14,
                   height_ratios=[h_stats, h_evo, h_donut, h_broker, h_broker_evo, h_table])

    # ── Panel 1: Stats ────────────────────────────────────────────────────────
    ax0 = fig.add_subplot(gs[0, 0])
    ax0.set_facecolor(surf)
    ax0.set_xlim(0, 1); ax0.set_ylim(0, 1)
    ax0.axis('off')

    pad = 0.035
    ax0.text(pad, 0.90, 'investsh', color=textc, fontsize=17,
             fontweight='bold', va='top')
    ax0.text(1 - pad, 0.90, date, color=dim, fontsize=10.5, va='top', ha='right')
    ax0.axhline(0.76, xmin=0.02, xmax=0.98, color=dim, linewidth=0.4, alpha=0.4)

    ax0.text(pad, 0.66, 'Patrimônio', color=dim, fontsize=9.5, va='top')
    ax0.text(pad, 0.56, brl_fmt(total), color=textc, fontsize=23,
             fontweight='bold', va='top', family='monospace')
    ax0.text(pad, 0.28, f'{sign}{brl_fmt(delta)}  ({sign}{dpct:.2f}%)', color=dcol,
             fontsize=12, va='top')
    if valorizacao_now is not None:
        vzs = '+' if valorizacao_now >= 0 else ''
        aps = '+' if aportes_now     >= 0 else ''
        ax0.text(pad, 0.16, f'Valoriz. {vzs}{brl_fmt(valorizacao_now)}  ·  Aportes {aps}{brl_fmt(aportes_now)}'
                 .replace('$', r'\$'),  # dois "R$" viram mathtext sem escape
                 color=dim, fontsize=8.3, va='top')
    else:
        ax0.text(pad, 0.16, 'vs última atualização', color=dim, fontsize=9, va='top')

    col2 = 0.58
    ax0.text(col2, 0.66, 'c/ FGTS', color=dim, fontsize=9.5, va='top')
    ax0.text(col2, 0.56, brl_fmt(total + fgts), color=textc, fontsize=15,
             fontweight='600', va='top', family='monospace')
    ax0.text(col2, 0.28, f'{len(invs)} ativos', color=dim, fontsize=11, va='top')
    ax0.text(col2, 0.16, f'FGTS: {brl_fmt(fgts)}', color=dim, fontsize=11, va='top')

    # ── Panel 2: Evolução patrimonial ───────────────────────────────────────
    ax1e = fig.add_subplot(gs[1, 0])
    ax1e.set_facecolor(bg)

    if len(evo_totals) >= 2:
        xs = list(range(len(evo_totals)))
        ax1e.plot(xs, evo_totals, color=green, linewidth=2, marker='o', markersize=3.5,
                  markerfacecolor=green, markeredgecolor=bg, zorder=3)
        ax1e.fill_between(xs, evo_totals, min(evo_totals) * 0.98, color=green, alpha=0.10)
        ax1e.set_xticks(xs)
        ax1e.set_xticklabels([mmyy(d) for d in evo_dates], color=dim, fontsize=8.5)
        ax1e.tick_params(axis='y', colors=dim, labelsize=8.5, length=0)
        for sp in ax1e.spines.values():
            sp.set_visible(False)
        ax1e.grid(axis='y', color=dim, alpha=0.15, linewidth=0.5)
        ax1e.margins(x=0.03, y=0.18)
        last = evo_totals[-1]
        ax1e.annotate(brl_fmt(last), (xs[-1], last), textcoords='offset points',
                      xytext=(0, 8), ha='right', color=green, fontsize=9.5, fontweight='bold')
    else:
        ax1e.axis('off')
        ax1e.text(0.5, 0.5, 'Histórico insuficiente para gráfico de evolução',
                  color=dim, fontsize=10, ha='center', va='center')

    ax1e.set_title('Evolução Patrimonial', color=dim, fontsize=10.5, pad=6, loc='left')

    # ── Panel 3: Donut ────────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[2, 0])
    ax1.set_facecolor(bg)

    labels  = list(main_alloc.keys())
    sizes   = list(main_alloc.values())
    colors1 = [ALLOC_C.get(l, '#888') for l in labels]

    cy, radius = 0.40, 0.70
    if alloc_total <= 0:
        # Carteira vazia (ou só saldos zerados): pie() não aceita fatias zeradas
        ax1.axis('off')
        ax1.text(0.5, 0.5, 'Sem saldo para mostrar a alocação',
                 color=dim, fontsize=10, ha='center', va='center')
        wedges, sizes, main_alloc = [], [], {}
    else:
        wedges, _ = ax1.pie(sizes, colors=colors1, startangle=90, radius=radius,
                            center=(0, cy),
                            wedgeprops=dict(width=0.52, edgecolor=bg, linewidth=2.5))
        ax1.set_aspect('equal')

    for wedge, val in zip(wedges, sizes):
        pct = val / alloc_total * 100
        if pct < 3:
            continue   # avoid label clutter on tiny slices
        angle = math.radians((wedge.theta2 + wedge.theta1) / 2)
        r = radius * 0.72
        ax1.text(r * math.cos(angle), cy + r * math.sin(angle),
                 f'{pct:.0f}%', ha='center', va='center',
                 fontsize=10.5, color=textc, fontweight='bold')

    n_leg      = len(main_alloc)
    legend_top = cy - radius - 0.28
    for i, (lbl, val) in enumerate(main_alloc.items()):
        y = legend_top - i * 0.24
        ax1.plot([-0.95], [y], 's', color=colors1[i], markersize=7)
        ax1.text(-0.86, y, f'{lbl}    {val/alloc_total*100:.1f}%', color=colors1[i],
                 fontsize=10, va='center', ha='left', fontweight='bold')

    if alloc_total > 0:
        ax1.set_xlim(-1.1, 1.1)
        ax1.set_ylim(legend_top - n_leg * 0.24 - 0.05, cy + radius + 0.15)
    ax1.set_title('Alocação', color=dim, fontsize=10.5, pad=4, loc='left')

    # ── Panel 4: Broker bars ──────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[3, 0])
    ax2.set_facecolor(bg)

    bnames  = list(broker_agg.keys())
    bvals   = list(broker_agg.values())
    bcolors = [BR_C.get(b, '#888') for b in bnames]

    bars    = ax2.barh(bnames, bvals, color=bcolors, height=0.5, edgecolor='none')
    ax2.tick_params(colors=textc, labelsize=10.5, length=0)
    ax2.xaxis.set_visible(False)
    for sp in ax2.spines.values():
        sp.set_visible(False)

    max_val = max(bvals) if bvals else 1
    for bar, val in zip(bars, bvals):
        pct = val / total * 100 if total else 0
        ax2.text(max_val * 0.01, bar.get_y() + bar.get_height() / 2,
                 f'  {pct:.1f}%   {brl_fmt(val)}',
                 va='center', ha='left', color=textc, fontsize=10)

    ax2.set_xlim(0, max_val * 1.02)
    ax2.set_title('Por Corretora', color=dim, fontsize=10.5, pad=4, loc='left')

    # ── Panel 5: Evolução por corretora ─────────────────────────────────────
    ax2e = fig.add_subplot(gs[4, 0])
    ax2e.set_facecolor(bg)

    if show_broker_evo:
        xs = list(range(len(evo_dates)))
        for b in broker_order:
            series = broker_series[b]
            color  = BR_C.get(b, '#888')
            ax2e.plot(xs, series, color=color, linewidth=2, marker='o', markersize=3,
                      markerfacecolor=color, markeredgecolor=bg, label=b, zorder=3)
        ax2e.set_xticks(xs)
        ax2e.set_xticklabels([mmyy(d) for d in evo_dates], color=dim, fontsize=8.5)
        ax2e.tick_params(axis='y', colors=dim, labelsize=8.5, length=0)
        for sp in ax2e.spines.values():
            sp.set_visible(False)
        ax2e.grid(axis='y', color=dim, alpha=0.15, linewidth=0.5)
        ax2e.margins(x=0.03, y=0.35)
        ax2e.legend(loc='upper left', ncol=min(len(broker_order), 4),
                    frameon=False, fontsize=9, labelcolor='linecolor',
                    handlelength=1.2, handletextpad=0.5, columnspacing=1.2)
    else:
        ax2e.axis('off')
        ax2e.text(0.5, 0.5, 'Histórico insuficiente para evolução por corretora',
                  color=dim, fontsize=10, ha='center', va='center')

    ax2e.set_title('Evolução por Corretora', color=dim, fontsize=10.5, pad=6, loc='left')

    # ── Panel 6: Detail table (full width) ─────────────────────────────────
    ax3 = fig.add_subplot(gs[5, 0])
    ax3.set_facecolor(bg)
    ax3.axis('off')
    ax3.set_xlim(0, 1)

    row_h = 1.0 / (n_rows + 1)   # +1 for column header; rows/n_rows/font_sz built above

    # Column x positions (normalized 0-1)
    COL = {'name': 0.01, 'cat': 0.36, 'bal': 0.56, 'gain': 0.72, 'delta': 0.84}

    # Header row
    y = 1.0 - row_h * 0.5
    for label, x in [('Ativo', COL['name']), ('Categoria', COL['cat']),
                      ('Saldo', COL['bal']), ('Ganho%', COL['gain']),
                      ('Δ Mês', COL['delta'])]:
        ax3.text(x, y, label, color=dim, fontsize=font_sz,
                 va='center', ha='left', fontweight='bold')
    ax3.axhline(1.0 - row_h, color=dim, linewidth=0.4, alpha=0.5)

    for idx, row in enumerate(rows):
        y = 1.0 - row_h * (idx + 1.5)

        if row[0] == 'header':
            _, broker, btotal = row
            bcol = BR_C.get(broker, '#888')
            pct  = btotal / total * 100 if total else 0
            ax3.text(COL['name'], y,
                     f'── {broker}   {brl_fmt(btotal)}  ({pct:.1f}%)',
                     color=bcol, fontsize=font_sz, va='center',
                     fontweight='bold')
            ax3.axhline(y - row_h * 0.45, color=dim, linewidth=0.3, alpha=0.3)
            continue

        inv = row[1]
        bal  = inv['balance']
        prev_bal = inv.get('previousBalance', bal)
        cat  = inv.get('category', '') or '—'
        _, sub = classify(inv)

        # gain%
        if cat == 'Crypto':
            gain_s, gain_c = '—', dim
        elif 'investedUSD' in inv:
            iv = inv['investedUSD'] * dolar
            g  = bal - iv
            gp = g / iv * 100 if iv else 0
            gain_s = f'{gp:+.1f}%'
            gain_c = green if g >= 0 else red
        else:
            iv = inv.get('invested', bal)
            g  = bal - iv
            gp = g / iv * 100 if iv else 0
            gain_s = f'{gp:+.1f}%'
            gain_c = green if g >= 0 else red

        # delta mês
        md = bal - prev_bal
        if abs(md) < 0.01:
            delta_s, delta_c = '—', dim
        else:
            delta_s = f'{"+" if md >= 0 else ""}{brl_fmt(md)}'
            delta_c = green if md >= 0 else red

        name_s = inv['name'][:32]
        ax3.text(COL['name'], y, name_s, color=textc, fontsize=font_sz, va='center')
        ax3.text(COL['cat'],  y, sub,    color=dim,   fontsize=font_sz, va='center')
        ax3.text(COL['bal'],  y, brl_fmt(bal), color=textc, fontsize=font_sz,
                 va='center', family='monospace')
        ax3.text(COL['gain'], y, gain_s,  color=gain_c,  fontsize=font_sz, va='center')
        ax3.text(COL['delta'],y, delta_s, color=delta_c, fontsize=font_sz, va='center')

    ax3.set_ylim(0, 1)
    ax3.set_title('Ativos', color=dim, fontsize=10.5, pad=4, loc='left')

    # ── Save ─────────────────────────────────────────────────────────────────
    assets_dir = os.path.join(ROOT, 'assets')
    os.makedirs(assets_dir, exist_ok=True)
    img_path = os.path.join(assets_dir, 'status.png')
    fig.savefig(img_path, dpi=130, bbox_inches='tight',
                facecolor=bg, edgecolor='none')
    plt.close(fig)
    print(f'{G}✓ Imagem gerada: assets/status.png{RST}')


def do_save_tui(data, total_before, pre_balances):
    """Silent save for TUI mode — no prints, no prompts. Returns (ok, msg)."""
    import contextlib, io as _io
    invs        = data['investments']
    total_after = sum(i['balance'] for i in invs)

    data['lastUpdated'] = datetime.now().strftime('%Y-%m-%d')

    for inv in invs:
        prev = pre_balances.get(inv['name'])
        if prev is None:
            inv.setdefault('previousBalance', inv['balance'])
        elif round(inv['balance'], 4) != round(prev, 4):
            inv['previousBalance'] = prev

    with open(DATA, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    hist_path = os.path.join(ROOT, 'data', 'history.json')
    try:
        with open(hist_path, encoding='utf-8') as f:
            history = json.load(f)
    except FileNotFoundError:
        history = []

    today    = data['lastUpdated']
    snapshot = history_snapshot(data, total_after)
    existing = next((i for i, h in enumerate(history) if h.get('date') == today), None)
    if existing is None:
        history.append(snapshot)
    else:
        history[existing] = {**history[existing], **snapshot}

    with open(hist_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    with contextlib.redirect_stdout(_io.StringIO()):
        try:
            generate_status_image(data)
        except Exception:
            pass

    git_msg = ''
    if AUTO_GIT:
        import subprocess
        month = datetime.now().strftime('%Y-%m')
        try:
            subprocess.run(['git', '-C', ROOT, 'add',
                            'data/investments.json', 'data/history.json', 'assets/'],
                           check=True, capture_output=True)
            subprocess.run(['git', '-C', ROOT, 'commit', '-m', f'update {month}'],
                           capture_output=True)
            push = subprocess.run(['git', '-C', ROOT, 'push'], capture_output=True, text=True)
            git_msg = '  ↑ push ok' if push.returncode == 0 else '  ⚠ push falhou'
        except Exception:
            git_msg = '  ⚠ git falhou'

    delta = total_after - total_before
    sign  = '+' if delta >= 0 else ''
    return True, f'✓ Salvo  ({sign}{brl_fmt(delta)}){git_msg}'


def do_save(data, total_before, pre_balances):
    invs        = data['investments']
    total_after = sum(i['balance'] for i in invs)
    delta       = total_after - total_before

    data['lastUpdated'] = datetime.now().strftime('%Y-%m-%d')

    print_header('Resumo')
    print(f'  Antes:    {fmt(total_before)}')
    print(f'  Depois:   {fmt(total_after)}')
    delta_col = G if delta >= 0 else R
    print(f'  Variação: {delta_col}{("+" if delta>=0 else "")}{fmt(delta)}{RST}')
    print(f'  FGTS:     {fmt(data["fgts"])}')
    print(f'  Total c/ FGTS: {W}{fmt(total_after + data["fgts"])}{RST}')
    print()

    if not ask_yes('Salvar alterações?'):
        print(f'\n{Y}Nenhuma alteração salva.{RST}\n')
        return False

    # Persiste o saldo anterior de cada ativo (base para "variação" no app)
    # Só atualiza previousBalance quando o saldo mudou; ativos inalterados
    # mantêm o previousBalance anterior para que a variação acumulada apareça.
    for inv in data['investments']:
        prev = pre_balances.get(inv['name'])
        if prev is None:
            # Ativo novo adicionado nesta sessão
            inv.setdefault('previousBalance', inv['balance'])
        elif round(inv['balance'], 4) != round(prev, 4):
            # Saldo mudou → registra o valor anterior
            inv['previousBalance'] = prev
        # else: inalterado → mantém previousBalance existente

    with open(DATA, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'\n{G}{BLD}✓ Salvo em {DATA}{RST}')

    hist_path = os.path.join(ROOT, 'data', 'history.json')
    try:
        with open(hist_path, encoding='utf-8') as f:
            history = json.load(f)
    except FileNotFoundError:
        history = []

    today = data['lastUpdated']
    snapshot = history_snapshot(data, total_after)
    existing = next((i for i, h in enumerate(history) if h.get('date') == today), None)
    if existing is None:
        history.append(snapshot)
        msg = f'{G}✓ Histórico: {len(history)} snapshot(s){RST}'
    else:
        history[existing] = {**history[existing], **snapshot}
        msg = f'{G}✓ Histórico atualizado para hoje ({today}){RST}'

    with open(hist_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(msg)


    generate_status_image(data)

    # Auto-commit (opcional — ver FINANCES_AUTO_GIT no README)
    if AUTO_GIT:
        import subprocess
        month = datetime.now().strftime('%Y-%m')
        try:
            subprocess.run(['git', '-C', ROOT, 'add',
                            'data/investments.json', 'data/history.json',
                            'assets/'], check=True)
            result = subprocess.run(
                ['git', '-C', ROOT, 'commit', '-m', f'update {month}'],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                print(f'{G}✓ Commit criado: update {month}{RST}')
            else:
                # Nada para commitar (sem mudanças nos arquivos)
                print(f'{DIM}  Git: {result.stdout.strip() or result.stderr.strip()}{RST}')
            # Push sempre — também envia commits locais pendentes de saves anteriores
            subprocess.run(['git', '-C', ROOT, 'push'], check=True)
            print(f'{G}✓ Push concluído{RST}')
        except FileNotFoundError:
            print(f'{Y}  git não encontrado, commit pulado.{RST}')
        except subprocess.CalledProcessError as e:
            print(f'{Y}  Erro no git: {e}{RST}')

    print()
    return True

# ── Main ──────────────────────────────────────────────────────────────────────
def empty_portfolio():
    """Carteira vazia com os mesmos parâmetros do exemplo (alocação ideal etc.)."""
    with open(EXAMPLE, encoding='utf-8') as f:
        d = json.load(f)
    d['lastUpdated'] = datetime.now().strftime('%Y-%m-%d')
    d['fgts'] = 0.0
    d['emergencyReserve'].pop('assetNames', None)  # reserva = ativos com allocationGroup RESERVA_EMERGENCIA
    d['investments'] = []
    return d

def first_run():
    """Cria data/investments.json na primeira execução."""
    print(f'\n{BLD}{G}Bem-vindo ao investsh!{RST}')
    print(f'{DIM}Não encontrei {DATA}.{RST}\n')
    print(f'  {C}[1]{RST} Começar com carteira vazia {DIM}(recomendado){RST}')
    print(f'  {C}[2]{RST} Copiar dados de exemplo {DIM}(para explorar o app){RST}')
    print(f'  {C}[x]{RST} Sair')
    choice = input(f'\n{C}Escolha{RST} [1]: ').strip().lower() or '1'
    if choice == '1':
        d = empty_portfolio()
    elif choice == '2':
        with open(EXAMPLE, encoding='utf-8') as f:
            d = json.load(f)
    else:
        sys.exit(0)
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print(f'{G}✓ Criado {DATA}{RST}')
    print(f'{DIM}  Ajuste alocação ideal, reserva e projeção em "Parâmetros".{RST}\n')
    return d

if os.path.isfile(DATA):
    with open(DATA, encoding='utf-8') as f:
        data = json.load(f)
else:
    data = first_run()

if '--menu' in sys.argv:
    # Modo texto clássico (útil em ambientes sem TTY ou para scripting)
    total_before = sum(i['balance'] for i in data['investments'])
    pre_balances = {i['name']: i['balance'] for i in data['investments']}

    print(f'\n{BLD}{G}╔══════════════════════════════════════╗')
    print(f'║    investsh — Atualização Mensal     ║')
    print(f'╚══════════════════════════════════════╝{RST}')
    print(f'\n{DIM}Arquivo: {DATA}{RST}')
    print(f'Última atualização: {W}{data["lastUpdated"]}{RST}')
    print(f'Total atual:        {W}{fmt(sum(i["balance"] for i in data["investments"]))}{RST}')
    print(f'FGTS:               {W}{fmt(data["fgts"])}{RST}')

    dolar, crypto_prices = fetch_rates(data)

    MENU = {
        '1': ('Atualizar saldos (todos)',   lambda: do_update(data, dolar, crypto_prices)),
        '2': ('Atualizar ativo específico', lambda: do_update_single(data, dolar, crypto_prices)),
        '3': ('Registrar aporte',           lambda: do_aporte(data)),
        '4': ('Registrar saque',            lambda: do_saque(data)),
        '5': ('Adicionar novo ativo',       lambda: do_add(data, dolar)),
        '6': ('Remover ativo',              lambda: do_remove(data)),
        '7': ('Parâmetros',                 lambda: do_params(data)),
        'V': ('Visualizar (terminal)',      lambda: do_view(data)),
    }

    while True:
        print(f'\n{BLD}{W}O que deseja fazer?{RST}')
        for k, (label, _) in MENU.items():
            print(f'  {C}[{k}]{RST} {label}')
        print(f'  {C}[0]{RST} Salvar e sair')
        print(f'  {C}[x]{RST} Sair sem salvar')

        choice = input(f'\n{C}Escolha{RST}: ').strip()

        if choice == '0':
            do_save(data, total_before, pre_balances)
            break
        elif choice.lower() == 'x':
            print(f'\n{Y}Saindo sem salvar.{RST}\n')
            break
        elif choice in MENU:
            MENU[choice][1]()
        else:
            print(f'{Y}  Opção inválida.{RST}')

else:
    # Modo padrão: TUI curses
    with contextlib.redirect_stdout(io.StringIO()):
        dolar, crypto_prices = fetch_rates(data)
    for inv in data['investments']:
        if inv.get('category') == 'Crypto':
            price = crypto_prices.get(inv['name'])
            if price and inv.get('quantity') is not None:
                inv['balance'] = round(inv['quantity'] * price, 4)
    run_tui(data, crypto_prices)
