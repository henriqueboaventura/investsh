"""Cores ANSI e cabeçalhos para a saída de texto (primeira execução, check, cotações)."""

G   = '\033[92m'
R   = '\033[91m'
Y   = '\033[93m'
C   = '\033[96m'
W   = '\033[97m'
DIM = '\033[2m'
RST = '\033[0m'
BLD = '\033[1m'


def print_sep(char='─', width=60):
    print(f'{DIM}{char * width}{RST}')


def print_header(text):
    print(f'\n{BLD}{W}▸ {text}{RST}')
    print_sep()
