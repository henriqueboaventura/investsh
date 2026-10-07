"""Cotações automáticas: USD/BRL (AwesomeAPI) e cripto (CoinGecko)."""
import json, urllib.request

from .term import G, Y, RST, print_header
from .core import CRYPTO_IDS


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
