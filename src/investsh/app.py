"""Orquestração: carrega a carteira e abre o menu ou a TUI."""
import json, os, io, contextlib

from . import config
from .term import G, Y, C, W, DIM, RST, BLD, fmt
from .quotes import fetch_rates
from .menu import (
    do_update, do_add, do_update_single, do_aporte, do_saque, do_remove, do_params, do_view,
)
from .tui import run_tui
from .storage import do_save, first_run


def run(menu=False):
    if os.path.isfile(config.DATA):
        with open(config.DATA, encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = first_run()

    if menu:
        # Modo texto clássico (útil em ambientes sem TTY ou para scripting)
        total_before = sum(i['balance'] for i in data['investments'])
        pre_balances = {i['name']: i['balance'] for i in data['investments']}

        print(f'\n{BLD}{G}╔══════════════════════════════════════╗')
        print(f'║    investsh — Atualização Mensal     ║')
        print(f'╚══════════════════════════════════════╝{RST}')
        print(f'\n{DIM}Arquivo: {config.DATA}{RST}')
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
