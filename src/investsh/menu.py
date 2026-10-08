"""Ações do modo texto (--menu): atualizar, aportar, sacar, cadastrar, visualizar."""
from .term import (
    G, R, Y, M, C, W, DIM, RST, BLD, fmt, gain_str, ask, ask_float, ask_yes, print_sep,
    print_header, _ask_choice,
)
from .core import (
    BROKER_ORDER, sort_key, classify, cost_basis, total_invested, alloc_investments,
    reserva_status, IX_LABEL, PURPOSE_LABEL, _CATEGORIES, _TYPES, _BROKERS, _INDEXERS,
    _ALLOCATION_GROUPS, _PURPOSES, IDEAL_FIELDS, broker_monthly_series, sparkline, brl_fmt,
    maturity_alerts,
)
from . import config, perf


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
        to_remove = []  # lista (sem repetição) para as mensagens saírem na ordem digitada
        for x in raw.split(','):
            x = x.strip()
            if x.isdigit():
                idx = int(x)
                if idx < len(sorted_invs) and sorted_invs[idx]['name'] not in to_remove:
                    to_remove.append(sorted_invs[idx]['name'])
        data['investments'] = [inv for inv in invs if inv['name'] not in to_remove]
        for n in to_remove:
            print(f'  {R}✗ Removido: {n}{RST}')


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

    # ── Rentabilidade vs CDI/IPCA ─────────────────────────────────────────────
    import datetime as _dt
    print_header('Rentabilidade')
    summary, note = perf.load(_dt.date.today())
    colors = {'header': DIM, 'sep': DIM, 'label': '', 'pos': G, 'neg': R, 'dim': DIM}
    for line in perf.table(summary, note)[1:]:          # [0] é o título (já no cabeçalho)
        print('  ' + ''.join(f'{colors[kind]}{text}{RST}' for text, kind in line) if line else '')

    # ── Vencimentos ───────────────────────────────────────────────────────────
    alerts = maturity_alerts(invs, _dt.date.today(), config.MATURITY_DAYS)
    if alerts:
        print_header(f'Vencimentos (próximos {config.MATURITY_DAYS} dias)')
        for a in alerts:
            col = R if a['days'] < 0 else (Y if a['days'] <= 30 else '')
            when = (f'venceu há {-a["days"]} dia(s)' if a['days'] < 0 else
                    'vence hoje' if a['days'] == 0 else f'vence em {a["days"]} dia(s)')
            print(f'  {a["name"][:38]:<38}  {DIM}{a["date"]:%d/%m/%Y}{RST}  '
                  f'{col}{when:<18}{RST}  {brl_fmt(a["balance"]):>14}')

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
