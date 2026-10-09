"""Tela interativa (curses)."""
import json, os

from . import config, sync
from .core import (
    BROKER_ORDER, sort_key, classify, cost_basis, total_invested, alloc_investments,
    reserva_status, IX_LABEL, PURPOSE_LABEL, _CATEGORIES, _TYPES, _BROKERS, _INDEXERS,
    _ALLOCATION_GROUPS, _PURPOSES, IDEAL_FIELDS, monthly_summary, broker_monthly_series, brl_fmt,
    maturity_alerts, record_flow,
)
from .storage import do_save_tui
from . import perf

# Vencimentos a até tantos dias geram aviso ao abrir (a lista completa fica no Sumário)
URGENT_DAYS = 30


def maturity_text(a):
    """'vence em 12 dias' / 'vence hoje' / 'venceu há 3 dias'."""
    if a['days'] < 0:
        return f'venceu há {-a["days"]} dia(s)'
    return 'vence hoje' if a['days'] == 0 else f'vence em {a["days"]} dia(s)'


def run_tui(data, crypto_prices=None):
    """Full-screen TUI: browse, search, and edit investments."""
    import curses
    crypto_prices = crypto_prices or {}

    pre_balances = {i['name']: i['balance'] for i in data['investments']}
    total_before = [sum(pre_balances.values())]
    status_msg   = ['']  # shown in bottom bar after save
    dirty        = [False]  # True quando há alterações não salvas
    pending_sync = [None]   # {'job', 'msg'}: commit/push rodando em segundo plano

    # CDI/IPCA do Banco Central: a API às vezes leva dezenas de segundos. A busca roda
    # numa thread desde a abertura; a aba Rentabilidade lê o cache e se redesenha no fim.
    import threading
    def _fetch_benchmarks():
        try:
            perf.load(_dt.date.today())
        except Exception:
            pass   # sem rede etc.: a aba mostra "indisponível"; nada vai para a tela
    bench_fetch = threading.Thread(target=_fetch_benchmarks, daemon=True)

    # Avisos ao abrir: vencimentos próximos e commits que não chegaram ao remoto
    import datetime as _dt
    warnings = []
    urgent = [a for a in maturity_alerts(data['investments'], _dt.date.today(), config.MATURITY_DAYS)
              if a['days'] <= URGENT_DAYS]
    if urgent:
        warnings.append(f'⚠ {len(urgent)} ativo(s) vencem em até {URGENT_DAYS} dias ou já venceram '
                        f'(veja o Sumário)')
    if not sync.busy():
        n_unpushed = sync.unpushed()
        if n_unpushed:
            warnings.append(f'⚠ {n_unpushed} commit(s) não enviado(s) ao remoto — '
                            f'rode: investsh sync')
    status_msg[0] = '   '.join(warnings)

    # Migrate Nomad assets: add balanceUSD if missing
    dol = data.get('dollarRate', 1)
    for inv in data['investments']:
        if inv.get('investedUSD') is not None and 'balanceUSD' not in inv:
            inv['balanceUSD'] = round(inv['balance'] / dol, 4) if dol else inv['investedUSD']

    # ── helpers ───────────────────────────────────────────────────────────────

    def read_key(win):
        """Lê uma tecla como (código, caractere). get_wch() decodifica UTF-8, então
        letras acentuadas chegam inteiras; teclas especiais vêm só com o código."""
        ch = win.get_wch()
        if isinstance(ch, str):
            return ord(ch), ch
        return ch, None

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
            ch, char = read_key(stdscr)
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
            elif char is not None and char.isprintable():
                if not numeric or char in '0123456789.,':
                    buf.insert(pos, char); pos += 1

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
            record_flow(data, inv, val * dol, usd=val)
            dirty[0] = True
        else:
            cur = inv.get('invested', 0)
            val = curs_input(stdscr, f'Aporte R$  {inv["name"][:33]}', default=0.0, numeric=True)
            if val is None or val <= 0: return False
            inv['invested'] = round(cur + val, 2)
            inv['balance']  = round(inv['balance'] + val, 2)
            if 'previousBalance' in inv:
                inv['previousBalance'] = round(inv['previousBalance'] + val, 2)
            record_flow(data, inv, val)
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
            record_flow(data, inv, -val * dol, usd=-val)
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
            record_flow(data, inv, -val)
            dirty[0] = True
        return True

    def act_delete(stdscr, inv):
        if inv.get('balance'):
            # Saldo que sai da carteira é saque; se foi para outro ativo, não
            choice = popup_menu(stdscr, inv['name'][:32], [
                ('s', f'Excluir: saldo de {brl_fmt(inv["balance"])} foi sacado'),
                ('t', 'Excluir: saldo foi para outro ativo'),
                ('n', 'Cancelar'),
            ])
        else:
            choice = popup_menu(stdscr, inv['name'][:32], [
                ('s', 'Sim, excluir'),
                ('n', 'Cancelar'),
            ])
        if choice in ('s', 't'):
            if choice == 's' and inv.get('balance'):
                usd = inv.get('balanceUSD') if 'investedUSD' in inv else None
                record_flow(data, inv, -inv['balance'], usd=-usd if usd else None)
            data['investments'] = [i for i in data['investments'] if i is not inv]
            dirty[0] = True
            return True
        return False

    # Mesmas listas do --menu (core.py): um só lugar para incluir corretoras etc.
    CATEGORIES = _CATEGORIES
    TYPES = _TYPES
    BROKERS = _BROKERS
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

        if new_inv['balance'] > 0:
            # Dinheiro novo é aporte; saldo vindo de outro ativo (ou já existente), não
            origin = popup_menu(stdscr, f'Saldo inicial {brl_fmt(new_inv["balance"])}', [
                ('a', 'Aporte: dinheiro novo na carteira'),
                ('t', 'Veio de outro ativo / já existia'),
            ])
            if origin is None: return False
            if origin == 'a':
                usd = new_inv.get('balanceUSD')
                record_flow(data, new_inv, new_inv['balance'], usd=usd)

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
                price = crypto_prices.get(inv['name'])
                if price:
                    inv['balance'] = round(val * price, 4)
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

        TABS     = [('s', 'Sumário'), ('r', 'Rentabilidade'), ('a', 'Alocação'), ('i', 'Indexador'),
                    ('o', 'Objetivo'), ('d', 'Detalhe'), ('b', 'Brokers'), ('g', 'Gráficos')]
        TAB_KEYS = {k for k, _ in TABS}

        tab      = ['s']
        scrolls  = {k: 0 for k, _ in TABS}
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

            # Vencimentos próximos (ou já vencidos com saldo)
            import datetime as _dt
            alerts = maturity_alerts(invs, _dt.date.today(), config.MATURITY_DAYS)
            if alerts:
                out.append(row([]))
                out.append(row([seg(f'  Vencimentos (próximos {config.MATURITY_DAYS} dias)', CYN | BOLD)]))
                for a in alerts:
                    col = RED if a['days'] < 0 else (YLW if a['days'] <= URGENT_DAYS else 0)
                    out.append(row([
                        seg(f'  {a["name"][:38]:<38}', 0),
                        seg(f'  {a["date"]:%d/%m/%Y}', DIM),
                        seg(f'  {maturity_text(a):<18}', col | (BOLD if col else 0)),
                        seg(f'  {brl_fmt(a["balance"]):>14}', 0),
                    ]))
            # Histórico mensal: variação = aportes + saques + valorização
            hist_path = os.path.join(config.ROOT, 'data', 'history.json')
            try:
                with open(hist_path, encoding='utf-8') as hf:
                    months = perf.monthly(json.load(hf), *perf.flow_log(data))[-12:]
            except (FileNotFoundError, json.JSONDecodeError):
                months = []
            if months:
                def cents(v):   # resíduos de ponto flutuante (ex.: -0,0000001) viram 0
                    return None if v is None else (round(v, 2) or 0.0)

                def money(v):
                    v = cents(v)
                    return '—' if v is None else f'{"+" if v > 0 else ""}{brl_fmt(v)}'

                def sign_col(v):
                    v = cents(v)
                    return DIM if v is None else (GRN if v >= 0 else RED)

                out.append(row([]))
                out.append(row([seg('  Histórico mensal', CYN | BOLD)]))
                out.append(row([seg(
                    f"  {'Mês':<8}  {'Saldo':>14}  {'Variação':>14}  {'Aportes':>13}  {'Saques':>13}"
                    f"  {'Valorização':>14}  {'Rentab.':>7}", DIM)]))
                out.append(row([seg('  ' + '─' * 101, DIM)]))
                for m in reversed(months):
                    r = '—' if m['r'] is None else f"{m['r'] * 100:+.1f}%"
                    out.append(row([
                        seg(f"  {m['month']:<8}", 0),
                        seg(f"  {brl_fmt(m['total']):>14}", 0),
                        seg(f"  {money(m['change']):>14}", sign_col(m['change'])),
                        seg(f"  {money(m['contributions']):>13}",
                            CYN if cents(m['contributions']) else DIM),
                        seg(f"  {money(m['withdrawals']):>13}",
                            YLW if cents(m['withdrawals']) else DIM),
                        seg(f"  {money(m['gain']):>14}", sign_col(m['gain'])),
                        seg(f"  {r:>7}", sign_col(m['r'])),
                    ]))
                if any(m['change'] is not None and not m['has_flows'] for m in months):
                    out.append(row([seg('  — meses antes do custo total ser registrado nos saves: '
                                        'só saldo e variação', DIM)]))

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

        def build_perf():
            import datetime as _dt
            summary, note = perf.load(_dt.date.today(), offline=True,
                                      loading=bench_fetch.is_alive())
            kinds = {'title': CYN | BOLD, 'header': DIM, 'sep': DIM, 'label': 0,
                     'pos': GRN, 'neg': RED, 'dim': DIM}
            out = [row([])]
            for line in perf.table(summary, note):
                out.append(row([seg('  ')] + [seg(text, kinds[kind]) for text, kind in line]))
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
            hist_path = os.path.join(config.ROOT, 'data', 'history.json')
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

        builders = {'s': build_summary, 'r': build_perf, 'a': build_allocation, 'i': build_indexer,
                    'o': build_purpose,
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

        bench_fetch.start()
        bench_pending = [True]
        refresh()

        # ── draw / event loop ─────────────────────────────────────────────────
        while True:
            # CDI/IPCA chegaram: redesenha a Rentabilidade sem perder a rolagem
            if bench_pending[0] and not bench_fetch.is_alive():
                bench_pending[0] = False
                if tab[0] == 'r':
                    keep = scrolls['r']
                    refresh()
                    scrolls['r'] = min(keep, max(0, len(lines[0]) - 1))

            # Resultado do commit/push em segundo plano, quando terminar
            if pending_sync[0]:
                st = sync.read_state()
                if st and st.get('job') == pending_sync[0]['job'] and st.get('state') == 'done':
                    status_msg[0] = f"{pending_sync[0]['msg']}  {st.get('message', '')}".rstrip()
                    pending_sync[0] = None
                elif not status_msg[0]:
                    status_msg[0] = pending_sync[0]['msg'] + (
                        '  ↻ enviando…' if config.GIT_PUSH else '  ↻ commit…')

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
                hint = f' {status_msg[0]}'   # fica até a próxima tecla
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
            # Com envio ou busca pendente, acorda a cada 250 ms para atualizar a tela
            stdscr.timeout(250 if pending_sync[0] or bench_pending[0] else -1)
            try:
                key, kchar = read_key(stdscr)
            except curses.error:   # timeout sem tecla
                continue
            stdscr.timeout(-1)
            status_msg[0] = ''

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
                elif kchar is not None and kchar.isprintable():
                    search[0] += kchar
                    out, sel = build_detail(search[0])
                    lines[0] = out; selectbl[0] = sel; det_sel[0] = 0; scrolls['d'] = 0
                continue

            # ── normal mode ───────────────────────────────────────────────────
            def save_inplace():
                ok, msg, job = do_save_tui(data, total_before[0], pre_balances)
                pre_balances.clear()
                pre_balances.update({i['name']: i['balance'] for i in data['investments']})
                total_before[0] = sum(pre_balances.values())
                dirty[0] = False
                if job and config.AUTO_GIT:
                    pending_sync[0] = {'job': job, 'msg': msg}   # barra mostra o andamento
                else:
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
            elif key == ord('R'):   # recarregar do disco ('r' é a aba Rentabilidade)
                data.clear()
                with open(config.DATA, encoding='utf-8') as f:
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
            elif key == curses.KEY_HOME:  # 'g' é a aba Gráficos
                scrolls[t] = 0; det_sel[0] = 0
            elif key in (ord('G'), curses.KEY_END):
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
