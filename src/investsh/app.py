"""Orquestração: carrega a carteira e abre a TUI."""
import json, os, io, contextlib

from . import config
from .quotes import fetch_rates
from .tui import run_tui
from .storage import first_run


def run():
    if os.path.isfile(config.DATA):
        with open(config.DATA, encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = first_run()

    with contextlib.redirect_stdout(io.StringIO()):
        dolar, crypto_prices = fetch_rates(data)
    for inv in data['investments']:
        if inv.get('category') == 'Crypto':
            price = crypto_prices.get(inv['name'])
            if price and inv.get('quantity') is not None:
                inv['balance'] = round(inv['quantity'] * price, 4)
    run_tui(data, crypto_prices)
