"""Cores ANSI e perguntas no terminal (modo --menu)."""


G  = '\033[92m'


R  = '\033[91m'


Y  = '\033[93m'


M  = '\033[95m'


C  = '\033[96m'


W  = '\033[97m'


DIM= '\033[2m'


RST= '\033[0m'


BLD= '\033[1m'


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


def _ask_choice(prompt, options):
    for i, o in enumerate(options):
        print(f'  {DIM}[{i}]{RST} {o}')
    while True:
        raw = input(f'  {C}{prompt}{RST}: ').strip()
        if raw.isdigit() and int(raw) < len(options):
            return options[int(raw)]
        print(f'  {Y}  Digite um número de 0 a {len(options)-1}{RST}')
