#!/usr/bin/env python3
"""Cashflow CLI — uso: python3 scripts/cashflow.py

Importa extratos bancários em formato OFX (conta corrente e fatura de cartão,
qualquer banco que exporte OFX 1.x/SGML) e mantém um livro-caixa mensal
categorizado em data/cashflow.json.
"""
import json, os, re, sys, uuid
from datetime import datetime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DATA = os.path.join(ROOT, 'data', 'cashflow.json')

# ── ANSI colors (mesma paleta do finances.py) ──────────────────────────────────
G  = '\033[92m'
R  = '\033[91m'
Y  = '\033[93m'
M  = '\033[95m'
C  = '\033[96m'
W  = '\033[97m'
DIM= '\033[2m'
RST= '\033[0m'
BLD= '\033[1m'

# ── Categorias ──────────────────────────────────────────────────────────────
# (label, tipo) — tipo: income | expense | neutral
# 'neutral' fica de fora dos totais de entrada/saída (transferências internas,
# pagamento de fatura de cartão, ajustes) mas continua registrado.
CATEGORIES = {
    'SALARIO':                 ('Salário',                   'income'),
    'RENDA_EXTRA':              ('Renda Extra / Freelance',   'income'),
    'REEMBOLSO':                ('Reembolso',                 'income'),
    'OUTRAS_ENTRADAS':          ('Outras Entradas',           'income'),
    'MORADIA':                  ('Moradia',                   'expense'),
    'MERCADO':                  ('Mercado',                   'expense'),
    'ALIMENTACAO':              ('Alimentação',               'expense'),
    'TRANSPORTE':               ('Transporte',                'expense'),
    'SAUDE':                    ('Saúde',                     'expense'),
    'COMPRAS_ONLINE':           ('Compras Online',            'expense'),
    'ASSINATURAS':              ('Assinaturas',               'expense'),
    'LAZER':                    ('Lazer',                     'expense'),
    'EDUCACAO':                 ('Educação',                  'expense'),
    'FINANCIAMENTO_DIVIDA':     ('Financiamento / Dívida',    'expense'),
    'IMPOSTOS_TAXAS':           ('Impostos e Taxas',          'expense'),
    'TRANSFERENCIA_TERCEIROS':  ('Transferência a Terceiros', 'expense'),
    'OUTRAS_SAIDAS':            ('Outras Saídas',             'expense'),
    'TRANSFERENCIA_PROPRIA':    ('Transferência Própria',     'neutral'),
    'FAMILIA':                  ('Movimentação com Família',  'neutral'),
    'CARTAO_FATURA':            ('Pagamento de Fatura',       'neutral'),
    'AJUSTE_CARTAO':            ('Ajuste de Cartão',          'neutral'),
    'A_CATEGORIZAR':            ('A Categorizar',             'pending'),
}
CATEGORY_KEYS = [k for k in CATEGORIES if k != 'A_CATEGORIZAR']


# Regras padrão de categorização por palavra-chave (checadas em ordem, na
# descrição em maiúsculas). Regras aprendidas em `merchantRules` têm prioridade.
DEFAULT_RULES = [
    (['pagamento de fatura', 'pagamento recebido'], 'CARTAO_FATURA'),
    (['estorno de', 'crédito de', 'credito de', 'desconto antecipa', 'reversão de desconto', 'reversao de desconto'], 'AJUSTE_CARTAO'),
    (['proventos'], 'SALARIO'),
    (['rende fácil', 'rende facil', 'aplicação', 'aplicacao rdb', 'resgate rdb'], 'TRANSFERENCIA_PROPRIA'),
    (['amazon', 'mercadolivre', 'mercadoli', 'aliexpress', 'shopee', 'netshoes', 'magazine luiza', 'americanas', 'vivara', 'mlp*'], 'COMPRAS_ONLINE'),
    (['ifood', 'pizzaria', 'lanchonete', 'restaurante', 'churrascaria', 'cafeteria'], 'ALIMENTACAO'),
    (['posto ', 'uberrides', 'uber ', '99app', 'combustivel', 'combustível'], 'TRANSPORTE'),
    (['farmacia', 'farmácia', 'drogaria', 'clinica', 'clínica', 'hospital'], 'SAUDE'),
    (['spotify', 'netflix', 'apple.com', 'youtub', 'wellhub', 'anthropic', 'claude', 'icloud', 'disney', 'hbo', 'paddle.net', 'claro ', 'net servi', 'vivo fibra'], 'ASSINATURAS'),
    (['condominio', 'condomínio', 'aluguel', 'energia', 'agua e esgoto', 'saneamento'], 'MORADIA'),
    (['aymore', 'aymoré', 'financiamento'], 'FINANCIAMENTO_DIVIDA'),
    (['iof', 'municipio de', 'município de', 'prefeitura', 'tarifa', 'juros'], 'IMPOSTOS_TAXAS'),
    (['supermercado', 'supermecado', 'mercado ', 'atacad', 'bazar'], 'MERCADO'),
]

MONTHS_PT = ['', 'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']

# ── Helpers gerais ──────────────────────────────────────────────────────────
def fmt(v):
    return f'R$ {v:>12,.2f}'

def gc(v):
    return G if v >= 0 else R

def ask(prompt, default=None):
    hint = f' [{default}]' if default is not None else ''
    raw = input(f'{C}{prompt}{hint}{RST}: ').strip()
    return raw if raw else default

def ask_float(prompt, default=None):
    while True:
        raw = ask(prompt, default)
        if raw is None:
            return None
        try:
            return float(str(raw).replace('.', '').replace(',', '.')) if ',' in str(raw) else float(raw)
        except ValueError:
            print(f'{Y}  Valor inválido.{RST}')

def ask_choice(prompt, options, labels=None):
    labels = labels or options
    for i, lbl in enumerate(labels):
        print(f'  {DIM}[{i}]{RST} {lbl}')
    while True:
        raw = input(f'  {C}{prompt}{RST}: ').strip()
        if raw.isdigit() and int(raw) < len(options):
            return options[int(raw)]
        print(f'  {Y}  Digite um número de 0 a {len(options)-1}{RST}')

def print_sep(width=60):
    print(f'{DIM}{"─"*width}{RST}')

def print_header(text):
    print(f'\n{BLD}{W}▸ {text}{RST}')
    print_sep()

# ── Parser OFX (genérico, tolera SGML sem tags de fechamento) ──────────────────
def _tags(block):
    d = {}
    for m in re.finditer(r'<([A-Z0-9.]+)>([^<\r\n]*)', block):
        tag, val = m.group(1), m.group(2).strip()
        if tag not in d:
            d[tag] = val
    return d

def parse_ofx(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        text = f.read()
    is_card = '<CCACCTFROM>' in text or '<CREDITCARDMSGSRSV1>' in text
    account = 'cartao' if is_card else 'conta'
    org_m = re.search(r'<ORG>([^<\r\n]*)', text)
    org = org_m.group(1).strip() if org_m else ''
    rows = []
    for block in text.split('<STMTTRN>')[1:]:
        f_ = _tags(block)
        fitid, amt, dt = f_.get('FITID', ''), f_.get('TRNAMT', ''), f_.get('DTPOSTED', '')
        if not fitid or not amt or len(dt) < 8:
            continue
        try:
            amount = round(float(amt), 2)
        except ValueError:
            continue
        if amount == 0:
            continue
        rows.append({
            'date': f'{dt[0:4]}-{dt[4:6]}-{dt[6:8]}',
            'amount': amount,
            'account': account,
            'org': org,
            'fitid': fitid,
            'name': f_.get('NAME', ''),
            'memo': f_.get('MEMO', ''),
        })
    return rows

BB_GENERIC_NAMES = {'pix - enviado', 'pix - recebido', 'pix enviado', 'pix recebido', 'ted', 'doc'}
NU_PREFIXES = [
    'Transferência recebida pelo Pix - ',
    'Transferência enviada pelo Pix - ',
    'Pagamento de boleto efetuado - ',
]
INSTALLMENT_RE = re.compile(r'^(.*?)\s*-\s*Parcela\s*(\d+)/(\d+)$', re.I)

def build_description(name, memo):
    if name and memo:
        raw = memo if name.strip().lower() in BB_GENERIC_NAMES else f'{name} - {memo}'
    else:
        raw = memo or name or ''
    for p in NU_PREFIXES:
        if raw.startswith(p):
            raw = raw[len(p):]
            break
    raw = re.sub(r'^\d{2}/\d{2}\s+\d{2}:\d{2}\s*', '', raw)
    raw = re.sub(r'\s*\(Transfer[êe]ncia[^)]*\)?\s*$', '', raw, flags=re.I)
    raw = re.split(r'\s+-\s+(?=[\d•])', raw)[0]
    raw = re.sub(r'\s+\d{6,}$', '', raw)
    raw = raw.strip(' -').strip()
    return raw or (name or memo or '(sem descrição)')

def extract_installment(desc):
    m = INSTALLMENT_RE.match(desc)
    if m:
        return m.group(1).strip(), {'current': int(m.group(2)), 'total': int(m.group(3))}
    return desc, None

def guess_category(desc, rules):
    u = desc.upper()
    for token, cat in rules.get('merchantRules', {}).items():
        if token in u:
            return cat
    # Nomes do titular (transferências entre contas próprias) e sobrenomes de
    # família (movimentações com parentes) — configurados em data/cashflow.json.
    if any(tok.upper() in u for tok in rules.get('ownNames', []) if tok):
        return 'TRANSFERENCIA_PROPRIA'
    if any(s.upper() in u for s in rules.get('familySurnames', []) if s):
        return 'FAMILIA'
    for keywords, cat in DEFAULT_RULES:
        if any(kw.upper() in u for kw in keywords):
            return cat
    return 'A_CATEGORIZAR'

def make_id(account, fitid, date, amount, description):
    return f'{account}|{fitid}|{date}|{amount}|{description}'

def import_ofx_file(data, path):
    """Importa um OFX pra dentro de `data` (in-place). Retorna (added, skipped, pending)."""
    rows = parse_ofx(path)

    # Contagem de ocorrências prévias por id-base, pra suportar (raros) casos
    # em que o banco reaproveita o mesmo FITID em lançamentos idênticos
    # (ex.: dois estornos de mesmo valor no mesmo dia) sem descartar nenhum.
    existing_bases = {}
    for t in data['transactions']:
        base = t['id'].split('#')[0]
        existing_bases[base] = existing_bases.get(base, 0) + 1

    added, skipped, pending = 0, 0, 0
    batch_seen = {}
    for r in rows:
        desc = build_description(r['name'], r['memo'])
        desc, installment = extract_installment(desc)
        base = make_id(r['account'], r['fitid'], r['date'], r['amount'], desc)
        batch_seen[base] = batch_seen.get(base, 0) + 1
        occurrence = batch_seen[base]
        if occurrence <= existing_bases.get(base, 0):
            skipped += 1
            continue
        tid = base if occurrence == 1 else f'{base}#{occurrence}'
        category = guess_category(desc, data)
        if category == 'A_CATEGORIZAR':
            pending += 1
        data['transactions'].append({
            'id': tid,
            'date': r['date'],
            'description': desc,
            'amount': r['amount'],
            'account': r['account'],
            'category': category,
            'installment': installment,
            'source': os.path.basename(path),
        })
        added += 1

    data['transactions'].sort(key=lambda t: (t['date'], t['account']))
    return added, skipped, pending

def add_manual_transaction(data, date, desc, amount, account, category):
    tid = f'manual|{date}|{desc}|{amount}|{uuid.uuid4().hex[:8]}'
    data['transactions'].append({
        'id': tid, 'date': date, 'description': desc, 'amount': round(amount, 2),
        'account': account, 'category': category, 'installment': None, 'source': 'manual',
    })
    data['transactions'].sort(key=lambda t: (t['date'], t['account']))
    return tid

# ── Importação ──────────────────────────────────────────────────────────────
def do_import(data):
    print_header('Importar Extrato (OFX)')
    path = ask('  Caminho do arquivo .ofx (Enter para cancelar)')
    if not path:
        return
    path = os.path.expanduser(path.strip().strip('"').strip("'"))
    if not os.path.isfile(path):
        print(f'{R}  Arquivo não encontrado: {path}{RST}')
        return

    try:
        added, skipped, pending = import_ofx_file(data, path)
    except Exception as e:
        print(f'{R}  Erro ao ler OFX: {e}{RST}')
        return

    print(f'\n  {G}✓ {added} lançamento(s) importado(s){RST}  {DIM}({skipped} já existiam){RST}')
    if pending:
        print(f'  {Y}⚠ {pending} ficaram como "A Categorizar" — use a opção de categorização.{RST}')

# ── Categorização ─────────────────────────────────────────────────────────────
def act_categorize_pending(data):
    pending = [t for t in data['transactions'] if t['category'] == 'A_CATEGORIZAR']
    if not pending:
        print(f'\n  {G}Nenhum lançamento pendente de categorização.{RST}')
        return
    print_header(f'Categorizar Pendentes ({len(pending)})')
    print(f'{DIM}  Enter/s = pular · q = parar{RST}')
    labels = [f'{CATEGORIES[k][0]} ({k})' for k in CATEGORY_KEYS]
    for t in pending:
        print()
        print_sep(40)
        sign = '+' if t['amount'] >= 0 else '-'
        print(f'  {t["date"]}  {DIM}[{t["account"]}]{RST}  {sign}{fmt(abs(t["amount"]))}')
        print(f'  {BLD}{t["description"]}{RST}')
        raw = input(f'  {C}Categoria (número, Enter=pular, q=sair){RST}: ').strip()
        if raw.lower() == 'q':
            break
        if raw == '' or raw.lower() == 's':
            continue
        if not (raw.isdigit() and int(raw) < len(CATEGORY_KEYS)):
            print(f'  {Y}  Opção inválida, pulando.{RST}')
            continue
        cat = CATEGORY_KEYS[int(raw)]
        t['category'] = cat
        if ask('  Lembrar essa categoria para descrições parecidas? (s/n)', 's').lower().startswith('s'):
            data.setdefault('merchantRules', {})[t['description'].upper()] = cat
        continue
    else:
        return
    print(f'  {DIM}Interrompido. Progresso mantido.{RST}')

def _print_category_menu():
    for i, k in enumerate(CATEGORY_KEYS):
        print(f'  {DIM}[{i}]{RST} {CATEGORIES[k][0]}')

def act_recategorize_search(data):
    print_header('Buscar e Recategorizar')
    term = ask('  Buscar por trecho da descrição')
    if not term:
        return
    matches = [t for t in data['transactions'] if term.lower() in t['description'].lower()]
    if not matches:
        print(f'  {Y}Nenhum lançamento encontrado.{RST}')
        return
    matches.sort(key=lambda t: t['date'], reverse=True)
    for i, t in enumerate(matches[:30]):
        cat_label = CATEGORIES.get(t['category'], (t['category'],))[0]
        print(f'  {DIM}[{i}]{RST} {t["date"]}  {fmt(t["amount"])}  {t["description"]}  {M}→ {cat_label}{RST}')
    raw = input(f'  {C}Editar qual? (número, Enter=cancelar){RST}: ').strip()
    if not (raw.isdigit() and int(raw) < len(matches[:30])):
        return
    t = matches[int(raw)]
    print(f'\n  Nova categoria para: {BLD}{t["description"]}{RST}')
    _print_category_menu()
    new_cat = ask_choice('Escolha', CATEGORY_KEYS)
    t['category'] = new_cat
    if ask('  Lembrar essa categoria para descrições parecidas? (s/n)', 's').lower().startswith('s'):
        data.setdefault('merchantRules', {})[t['description'].upper()] = new_cat

# ── Lançamento manual ───────────────────────────────────────────────────────
def do_add_manual(data):
    print_header('Adicionar Lançamento Manual')
    date = ask('  Data (YYYY-MM-DD)', datetime.now().strftime('%Y-%m-%d'))
    desc = ask('  Descrição')
    if not desc:
        print(f'  {Y}Cancelado.{RST}')
        return
    amount = ask_float('  Valor (negativo = saída, positivo = entrada)')
    if amount is None:
        print(f'  {Y}Cancelado.{RST}')
        return
    print(f'\n  {M}Conta:{RST}')
    account = ask_choice('Escolha', ['conta', 'cartao'], ['Conta corrente', 'Cartão de crédito'])
    print(f'\n  {M}Categoria:{RST}')
    _print_category_menu()
    category = ask_choice('Escolha', CATEGORY_KEYS)
    add_manual_transaction(data, date, desc, amount, account, category)
    print(f'\n  {G}✓ Lançamento adicionado.{RST}')

# ── Resumo mensal ─────────────────────────────────────────────────────────────
def available_months(data):
    return sorted({t['date'][:7] for t in data['transactions']})

def do_summary(data):
    months = available_months(data)
    if not months:
        print(f'\n  {Y}Nenhum lançamento importado ainda.{RST}')
        return
    print_header('Resumo Mensal')
    month = ask('  Mês (YYYY-MM)', months[-1])
    txns = [t for t in data['transactions'] if t['date'].startswith(month)]
    if not txns:
        print(f'  {Y}Sem lançamentos em {month}.{RST}')
        return

    income  = sum(t['amount'] for t in txns if CATEGORIES.get(t['category'], (None,'expense'))[1] == 'income')
    expense = sum(t['amount'] for t in txns if CATEGORIES.get(t['category'], (None,'expense'))[1] == 'expense')
    neutral = sum(t['amount'] for t in txns if CATEGORIES.get(t['category'], (None,'expense'))[1] == 'neutral')
    pending = sum(1 for t in txns if t['category'] == 'A_CATEGORIZAR')
    saldo = income + expense

    y, m = month.split('-')
    print(f'\n  {BLD}{MONTHS_PT[int(m)]}/{y}{RST}')
    print(f'  Entradas:  {G}{fmt(income)}{RST}')
    print(f'  Saídas:    {R}{fmt(expense)}{RST}')
    print(f'  Saldo:     {gc(saldo)}{fmt(saldo)}{RST}')
    print(f'  {DIM}(neutro/interno: {fmt(neutral)}{" · " + str(pending) + " pendente(s)" if pending else ""}){RST}')

    by_cat = {}
    for t in txns:
        if CATEGORIES.get(t['category'], (None, 'expense'))[1] != 'expense':
            continue
        by_cat[t['category']] = by_cat.get(t['category'], 0) + t['amount']
    if by_cat:
        print(f'\n  {BLD}Por categoria (saídas){RST}')
        for cat, val in sorted(by_cat.items(), key=lambda kv: kv[1]):
            label = CATEGORIES[cat][0]
            print(f'    {label:<28} {fmt(val)}')

def brl_fmt(v):
    s = f'{abs(v):,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f'R$ {"-" if v < 0 else ""}{s}'

# ── TUI (curses) ────────────────────────────────────────────────────────────
CAT_LETTERS = list('abcdefghijklmnopqrstuvwxyz')

def cat_type(cat):
    return CATEGORIES.get(cat, (cat, 'expense'))[1]

def cat_label(cat):
    return CATEGORIES.get(cat, (cat, cat))[0]

def run_tui(data):
    import curses

    dirty      = [False]
    status_msg = ['']

    # ── widgets genéricos (não dependem de color pairs) ─────────────────────
    def curs_input(stdscr, prompt, default='', numeric=False):
        """Input na barra inferior. Enter → valor (default se vazio). Esc → None."""
        h, w = stdscr.getmaxyx()
        curses.curs_set(1)
        buf = list(str(default) if default not in (None, '') else '')
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
                        return float(default) if default not in (None, '') else 0.0
                    try:
                        return float(val.replace(',', '.'))
                    except ValueError:
                        buf = list(str(default)); pos = len(buf); continue
                return val if val else default
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
                if not numeric or c in '0123456789.,-':
                    buf.insert(pos, c); pos += 1

    def popup_menu(stdscr, title, options):
        """Popup centralizado navegável (↑↓ + Enter, ou tecla direta). Esc → None."""
        h, w   = stdscr.getmaxyx()
        inner  = max(len(title), max(len(f' [{k}] {l} ') for k, l in options))
        pw, ph = inner + 4, len(options) + 4
        py, px = max(1, (h - ph) // 2), max(0, (w - pw) // 2)

        saved = []
        for r in range(py, min(py + ph + 1, h)):
            row_save = []
            for c in range(px, min(px + pw + 1, w)):
                try:
                    row_save.append(stdscr.inch(r, c))
                except curses.error:
                    row_save.append(ord(' '))
            saved.append(row_save)

        sel, result = 0, None
        while True:
            try:
                stdscr.addstr(py,     px, '┌' + '─' * (pw - 2) + '┐')
                stdscr.addstr(py + 1, px, '│' + ' ' * (pw - 2) + '│')
                stdscr.addstr(py + 1, px + 1 + (pw - 2 - len(title)) // 2, title, curses.A_BOLD)
                stdscr.addstr(py + 2, px, '├' + '─' * (pw - 2) + '┤')
                for i, (k, lbl) in enumerate(options):
                    row = py + 3 + i
                    stdscr.addstr(row, px, '│' + ' ' * (pw - 2) + '│')
                    label = f' [{k}] {lbl} '
                    attr  = curses.A_REVERSE | curses.A_BOLD if i == sel else 0
                    stdscr.addstr(row, px + 1, label[:pw - 2], attr)
                stdscr.addstr(py + 3 + len(options), px, '└' + '─' * (pw - 2) + '┘')
            except curses.error:
                pass
            stdscr.refresh()
            ch = stdscr.getch()
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

        for ri, row_save in enumerate(saved):
            r = py + ri
            if r >= h: break
            for ci, ch_saved in enumerate(row_save):
                c = px + ci
                if c >= w: break
                try:
                    stdscr.addch(r, c, ch_saved & 0xFF, ch_saved & ~0xFF)
                except curses.error:
                    pass
        stdscr.refresh()
        return result

    def _app(stdscr):
        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()
        stdscr.keypad(True)

        curses.init_pair(1, curses.COLOR_GREEN,   -1)
        curses.init_pair(2, curses.COLOR_RED,     -1)
        curses.init_pair(3, curses.COLOR_CYAN,    -1)
        curses.init_pair(4, curses.COLOR_YELLOW,  -1)
        curses.init_pair(5, curses.COLOR_BLACK,   curses.COLOR_CYAN)

        GRN  = curses.color_pair(1)
        RED  = curses.color_pair(2)
        CYN  = curses.color_pair(3)
        YLW  = curses.color_pair(4)
        HBAR = curses.color_pair(5)
        BOLD = curses.A_BOLD
        DIM  = curses.A_DIM
        REV  = curses.A_REVERSE

        TABS     = [('r', 'Resumo'), ('l', 'Lançamentos'), ('p', 'Pendentes'), ('h', 'Histórico')]
        TAB_KEYS = {k for k, _ in TABS}

        ml    = sorted({t['date'][:7] for t in data['transactions']})
        month = [ml[-1] if ml else datetime.now().strftime('%Y-%m')]
        tab      = ['r']
        scrolls  = {'r': 0, 'l': 0, 'p': 0, 'h': 0}
        search   = ['']
        srch_act = [False]
        sel_idx  = [0]
        lines    = [[]]
        selectbl = [[]]

        def seg(text, attr=0): return (text, attr)
        def row(segs, txn=None): return {'segs': segs, 'txn': txn}

        def month_txns():
            return [t for t in data['transactions'] if t['date'].startswith(month[0])]

        def monthly_agg():
            months = sorted({t['date'][:7] for t in data['transactions']})
            out = []
            for m in months:
                txns = [t for t in data['transactions'] if t['date'].startswith(m)]
                income  = sum(t['amount'] for t in txns if cat_type(t['category']) == 'income')
                expense = sum(t['amount'] for t in txns if cat_type(t['category']) == 'expense')
                out.append({'month': m, 'income': income, 'expense': expense, 'saldo': income + expense})
            return out

        def shift_month(delta):
            y, m = (int(x) for x in month[0].split('-'))
            m += delta
            while m < 1:  m += 12; y -= 1
            while m > 12: m -= 12; y += 1
            month[0] = f'{y:04d}-{m:02d}'

        # ── builders ─────────────────────────────────────────────────────────
        def build_resumo():
            txns = month_txns()
            y, mm = month[0].split('-')
            out = [row([seg(f' {MONTHS_PT[int(mm)]}/{y} ', BOLD | CYN)]), row([])]
            if not txns:
                out.append(row([seg('Sem lançamentos neste mês.  (i = importar OFX)', DIM)]))
                return out, []
            income  = sum(t['amount'] for t in txns if cat_type(t['category']) == 'income')
            expense = sum(t['amount'] for t in txns if cat_type(t['category']) == 'expense')
            neutral = sum(t['amount'] for t in txns if cat_type(t['category']) == 'neutral')
            pending = sum(1 for t in txns if t['category'] == 'A_CATEGORIZAR')
            saldo   = income + expense
            out.append(row([seg('Entradas    ', 0), seg(f'{brl_fmt(income):>16}', GRN | BOLD)]))
            out.append(row([seg('Saídas      ', 0), seg(f'{brl_fmt(expense):>16}', RED | BOLD)]))
            out.append(row([seg('Saldo       ', 0), seg(f'{brl_fmt(saldo):>16}', (GRN if saldo >= 0 else RED) | BOLD)]))
            out.append(row([seg(f'(neutro/interno: {brl_fmt(neutral)})', DIM)]))
            if pending:
                out.append(row([seg(f'⚠ {pending} pendente(s) de categoria — aba Pendentes (tecla p)', YLW)]))
            out.append(row([]))
            out.append(row([seg('Por categoria (saídas)', BOLD)]))
            by_cat = {}
            for t in txns:
                if cat_type(t['category']) != 'expense':
                    continue
                by_cat[t['category']] = by_cat.get(t['category'], 0) + t['amount']
            if by_cat:
                maxv = max(abs(v) for v in by_cat.values()) or 1
                for cat, val in sorted(by_cat.items(), key=lambda kv: kv[1]):
                    barlen = max(1, int(abs(val) / maxv * 22))
                    out.append(row([
                        seg(f'  {cat_label(cat):<24}', 0),
                        seg('█' * barlen, RED),
                        seg(f' {brl_fmt(val)}', DIM),
                    ]))
            else:
                out.append(row([seg('  Sem gastos categorizados ainda.', DIM)]))
            return out, []

        def build_lista(only_pending=False):
            txns = month_txns()
            if only_pending:
                txns = [t for t in txns if t['category'] == 'A_CATEGORIZAR']
            q = search[0].lower()
            if q:
                txns = [t for t in txns if q in t['description'].lower()]
            txns = sorted(txns, key=lambda t: t['date'])
            out, sel = [], []
            if not txns:
                out.append(row([seg('Nada aqui.', DIM)]))
                return out, sel
            for t in txns:
                icon     = '🏦' if t['account'] == 'conta' else '💳'
                amt_attr = GRN if t['amount'] >= 0 else RED
                cat      = t['category']
                cat_attr = (YLW | BOLD) if cat == 'A_CATEGORIZAR' else DIM
                segs = [
                    seg(f'{t["date"][5:]}  ', DIM),
                    seg(f'{icon} '),
                    seg(f'{t["description"][:34]:<36}'),
                    seg(f'{brl_fmt(t["amount"]):>14}  ', amt_attr),
                    seg(cat_label(cat), cat_attr),
                ]
                out.append(row(segs, t))
                sel.append((len(out) - 1, t))
            return out, sel

        def build_historico():
            agg = monthly_agg()
            out = [row([seg(' Histórico Mensal — Entradas x Saídas ', BOLD | CYN)]), row([])]
            if not agg:
                out.append(row([seg('Sem lançamentos ainda.  (i = importar OFX)', DIM)]))
                return out, []
            maxv = max(max(abs(a['income']), abs(a['expense'])) for a in agg) or 1
            for a in agg:
                y, mm = a['month'].split('-')
                lbl = f'{MONTHS_PT[int(mm)]}/{y}'
                saldo = a['saldo']
                out.append(row([
                    seg(f'{lbl:<10}', BOLD),
                    seg(f'saldo {brl_fmt(saldo):>16}', (GRN if saldo >= 0 else RED) | BOLD),
                ]))
                ilen = max(1, int(abs(a['income']) / maxv * 30)) if a['income'] else 0
                elen = max(1, int(abs(a['expense']) / maxv * 30)) if a['expense'] else 0
                out.append(row([seg('  Entradas  ', DIM), seg('█' * ilen, GRN), seg(f'  {brl_fmt(a["income"])}', DIM)]))
                out.append(row([seg('  Saídas    ', DIM), seg('█' * elen, RED), seg(f'  {brl_fmt(a["expense"])}', DIM)]))
                out.append(row([]))
            out.append(row([seg('Projeção', BOLD)]))
            if len(agg) >= 2:
                sample = agg[-3:]
                avg = sum(a['saldo'] for a in sample) / len(sample)
                out.append(row([seg(f'  Baseado na média de saldo dos últimos {len(sample)} mês(es):  ', DIM),
                                 seg(f'{brl_fmt(avg)}/mês', (GRN if avg >= 0 else RED) | BOLD)]))
                out.append(row([]))
                y, mm = (int(x) for x in agg[-1]['month'].split('-'))
                for _ in range(3):
                    mm += 1
                    if mm > 12: mm = 1; y += 1
                    lbl2 = f'{MONTHS_PT[mm]}/{y}'
                    out.append(row([seg(f'  {lbl2:<10}', 0), seg(f'{brl_fmt(avg):>16}', GRN if avg >= 0 else RED)]))
            else:
                out.append(row([seg('  Precisa de pelo menos 2 meses de histórico pra projetar.', DIM)]))
            return out, []

        builders = {
            'r': build_resumo,
            'l': lambda: build_lista(False),
            'p': lambda: build_lista(True),
            'h': build_historico,
        }

        def refresh():
            out, sel = builders[tab[0]]()
            lines[0] = out
            selectbl[0] = sel
            scrolls[tab[0]] = 0
            sel_idx[0] = max(0, min(sel_idx[0], len(sel) - 1)) if sel else 0

        def ensure_visible(ch):
            if not selectbl[0]:
                return
            li = selectbl[0][sel_idx[0]][0]
            t = tab[0]
            if li < scrolls[t]:
                scrolls[t] = li
            elif li >= scrolls[t] + ch:
                scrolls[t] = li - ch + 1

        # ── ações ────────────────────────────────────────────────────────────
        def popup_category(title='Categoria'):
            options = [(CAT_LETTERS[i], cat_label(k)) for i, k in enumerate(CATEGORY_KEYS)]
            choice = popup_menu(stdscr, title, options)
            if choice is None:
                return None
            return CATEGORY_KEYS[CAT_LETTERS.index(choice)]

        def act_import():
            path = curs_input(stdscr, 'Caminho do .ofx (Esc cancela)')
            if not path:
                return
            path = os.path.expanduser(str(path).strip().strip('"').strip("'"))
            if not os.path.isfile(path):
                status_msg[0] = f'Arquivo não encontrado: {path}'
                return
            try:
                added, skipped, pending = import_ofx_file(data, path)
            except Exception as e:
                status_msg[0] = f'Erro ao ler OFX: {e}'
                return
            dirty[0] = True
            status_msg[0] = f'{added} importado(s) · {skipped} já existia(m) · {pending} pendente(s)'
            ml2 = sorted({t['date'][:7] for t in data['transactions']})
            if ml2:
                month[0] = ml2[-1]

        def act_manual():
            date = curs_input(stdscr, 'Data (YYYY-MM-DD)', default=datetime.now().strftime('%Y-%m-%d'))
            if date is None: return
            desc = curs_input(stdscr, 'Descrição')
            if not desc: return
            amount = curs_input(stdscr, 'Valor (negativo = saída)', numeric=True)
            if amount is None: return
            acc = popup_menu(stdscr, 'Conta', [('c', 'Conta corrente'), ('t', 'Cartão de crédito')])
            if acc is None: return
            cat = popup_category()
            if cat is None: return
            add_manual_transaction(data, date, desc, amount, 'conta' if acc == 'c' else 'cartao', cat)
            dirty[0] = True
            status_msg[0] = 'Lançamento adicionado.'

        def act_recategorize(txn):
            new_cat = popup_category(txn['description'][:30])
            if new_cat is None:
                return
            txn['category'] = new_cat
            dirty[0] = True
            remember = popup_menu(stdscr, 'Lembrar regra?', [('y', 'Sim, categorizar assim sempre'), ('n', 'Não')])
            if remember == 'y':
                data.setdefault('merchantRules', {})[txn['description'].upper()] = new_cat
            status_msg[0] = f'→ {cat_label(new_cat)}'

        def save_inplace():
            save_data(data, quiet=True)
            dirty[0] = False
            status_msg[0] = 'Salvo.'

        refresh()

        # ── loop principal ───────────────────────────────────────────────────
        while True:
            h, w = stdscr.getmaxyx()
            stdscr.erase()
            t = tab[0]

            n_pend = sum(1 for x in data['transactions'] if x['category'] == 'A_CATEGORIZAR')
            hdr = f' Cashflow   {len(data["transactions"])} lançamentos   {n_pend} pendente(s) '
            stdscr.addstr(0, 0, ' ' * (w - 1), HBAR)
            try: stdscr.addstr(0, 0, hdr[:w], HBAR | BOLD)
            except curses.error: pass

            tx = 1
            for tk, tlbl in TABS:
                ts = f' {tlbl} '
                attr = (HBAR | BOLD) if tk == t else DIM
                if tx + len(ts) < w:
                    try: stdscr.addstr(1, tx, ts, attr)
                    except curses.error: pass
                tx += len(ts) + 1

            content_h = h - 4
            cur_lines = lines[0]
            scroll = scrolls[t]
            n = len(cur_lines)
            for i, r in enumerate(cur_lines[scroll:scroll + content_h]):
                y = 2 + i
                if y >= h - 1: break
                is_sel = (t in ('l', 'p') and selectbl[0] and sel_idx[0] < len(selectbl[0])
                          and selectbl[0][sel_idx[0]][0] == scroll + i)
                x = 0
                for txt, attr in r['segs']:
                    if x >= w - 1: break
                    chunk = txt[:w - 1 - x]
                    try: stdscr.addstr(y, x, chunk, (attr | REV) if is_sel else attr)
                    except curses.error: pass
                    x += len(chunk)
                if is_sel and x < w - 1:
                    try: stdscr.addstr(y, x, ' ' * (w - 1 - x), REV)
                    except curses.error: pass

            end = min(scroll + content_h, n)
            pos = f' {month[0]}  {scroll+1}-{end}/{n} '
            if status_msg[0]:
                hint = f' {status_msg[0]}'
                status_msg[0] = ''
            elif srch_act[0]:
                hint = f' Buscar: {search[0]}█  Esc limpar  Enter confirmar'
            elif t in ('l', 'p'):
                hint = ' r/l/p/h tabs  ←→ mês  j/k navega  Enter categoriza  / busca  i importa  n manual  w salva  q sai'
            else:
                hint = ' r/l/p/h tabs  ←→ mês  j/k scroll  i importa  n manual  w salva  q sai'
            try:
                stdscr.addstr(h - 1, 0, ' ' * (w - 1), REV)
                stdscr.addstr(h - 1, 0, hint[:max(0, w - len(pos))], REV)
                stdscr.addstr(h - 1, max(0, w - len(pos)), pos[:w - 1], REV | BOLD)
            except curses.error: pass

            stdscr.refresh()
            key = stdscr.getch()

            if srch_act[0]:
                if key == 27:
                    search[0] = ''; srch_act[0] = False; refresh()
                elif key in (10, 13, curses.KEY_ENTER):
                    srch_act[0] = False
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    search[0] = search[0][:-1]; refresh()
                elif 32 <= key < 256:
                    search[0] += chr(key); refresh()
                continue

            if key == ord('q'):
                if dirty[0]:
                    choice = popup_menu(stdscr, 'Alterações não salvas', [
                        ('s', 'Salvar e sair'), ('q', 'Sair sem salvar'), ('c', 'Cancelar'),
                    ])
                    if choice == 's':
                        save_inplace(); break
                    elif choice == 'q':
                        break
                else:
                    break
            elif key == curses.KEY_RESIZE:
                pass
            elif key == ord('w'):
                save_inplace()
            elif key == ord('i'):
                act_import(); refresh()
            elif key == ord('n'):
                act_manual(); refresh()
            elif key == ord('/') and t in ('l', 'p'):
                srch_act[0] = True
            elif key in (curses.KEY_LEFT, ord('[')):
                shift_month(-1); refresh()
            elif key in (curses.KEY_RIGHT, ord(']')):
                shift_month(1); refresh()
            elif 0 <= key < 256 and chr(key) in TAB_KEYS:
                new = chr(key)
                if new != t:
                    tab[0] = new; search[0] = ''; srch_act[0] = False; refresh()
            elif key in (ord('j'), curses.KEY_DOWN):
                if t in ('l', 'p') and selectbl[0]:
                    sel_idx[0] = min(sel_idx[0] + 1, len(selectbl[0]) - 1)
                    ensure_visible(content_h)
                else:
                    scrolls[t] = min(scrolls[t] + 1, max(0, n - content_h))
            elif key in (ord('k'), curses.KEY_UP):
                if t in ('l', 'p') and selectbl[0]:
                    sel_idx[0] = max(0, sel_idx[0] - 1)
                    ensure_visible(content_h)
                else:
                    scrolls[t] = max(0, scrolls[t] - 1)
            elif key in (curses.KEY_NPAGE, ord(' ')):
                scrolls[t] = min(scrolls[t] + content_h, max(0, n - content_h))
            elif key == curses.KEY_PPAGE:
                scrolls[t] = max(0, scrolls[t] - content_h)
            elif key in (10, 13, curses.KEY_ENTER) and t in ('l', 'p') and selectbl[0]:
                _, txn = selectbl[0][sel_idx[0]]
                act_recategorize(txn)
                refresh()

    curses.wrapper(_app)

# ── Main ──────────────────────────────────────────────────────────────────────
def load_data():
    if os.path.isfile(DATA):
        with open(DATA, encoding='utf-8') as f:
            d = json.load(f)
    else:
        d = {'lastUpdated': None, 'ownNames': [], 'familySurnames': [],
             'merchantRules': {}, 'transactions': []}
    d.setdefault('ownNames', [])
    d.setdefault('familySurnames', [])
    d.setdefault('merchantRules', {})
    d.setdefault('transactions', [])
    return d

def save_data(data, quiet=False):
    data['lastUpdated'] = datetime.now().strftime('%Y-%m-%d')
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if not quiet:
        print(f'\n  {G}✓ Salvo em {DATA}{RST}')

def run_menu(data):
    print(f'\n{BLD}{G}╔══════════════════════════════════════╗')
    print(f'║      Cashflow — Fluxo de Caixa       ║')
    print(f'╚══════════════════════════════════════╝{RST}')
    print(f'{DIM}Arquivo: {DATA}{RST}')
    print(f'Lançamentos: {W}{len(data["transactions"])}{RST}')

    MENU = {
        '1': ('Importar extrato (OFX)',            lambda: do_import(data)),
        '2': ('Categorizar pendentes',              lambda: act_categorize_pending(data)),
        '3': ('Buscar e recategorizar',             lambda: act_recategorize_search(data)),
        '4': ('Resumo mensal',                      lambda: do_summary(data)),
        '5': ('Adicionar lançamento manual',        lambda: do_add_manual(data)),
    }

    while True:
        print(f'\n{BLD}{W}O que deseja fazer?{RST}')
        for k, (label, _) in MENU.items():
            print(f'  {C}[{k}]{RST} {label}')
        print(f'  {C}[0]{RST} Salvar e sair')
        print(f'  {C}[x]{RST} Sair sem salvar')

        choice = input(f'\n{C}Escolha{RST}: ').strip()

        if choice == '0':
            save_data(data)
            break
        elif choice.lower() == 'x':
            print(f'\n{Y}Saindo sem salvar.{RST}\n')
            break
        elif choice in MENU:
            MENU[choice][1]()
        else:
            print(f'{Y}  Opção inválida.{RST}')

if __name__ == '__main__':
    data = load_data()
    if '--menu' in sys.argv:
        run_menu(data)
    else:
        run_tui(data)
