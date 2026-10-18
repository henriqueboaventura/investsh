"""Primeira execução e save da TUI (carteira, histórico; imagem e git em segundo plano)."""
import json, os, sys
from datetime import datetime

from . import config, sync
from .term import G, Y, C, DIM, RST, BLD
from .core import asset_key, brl_fmt, history_snapshot, start_flow_log


def write_json(path, obj):
    """Grava de forma atômica: quem lê (ex.: o git em segundo plano) nunca vê arquivo pela metade."""
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def do_save_tui(data, total_before, pre_balances):
    """Save da TUI: sem prints nem perguntas. Retorna (ok, msg, job do segundo plano ou None)."""
    invs        = data['investments']
    total_after = sum(i['balance'] for i in invs)

    data['lastUpdated'] = datetime.now().strftime('%Y-%m-%d')

    for inv in invs:
        prev = pre_balances.get(asset_key(inv))
        if prev is None:
            inv.setdefault('previousBalance', inv['balance'])
        elif round(inv['balance'], 4) != round(prev, 4):
            inv['previousBalance'] = prev

    start_flow_log(data)
    write_json(config.DATA, data)

    hist_path = os.path.join(config.ROOT, 'data', 'history.json')
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

    write_json(hist_path, history)

    # Imagem e commit/push vão para o segundo plano: a TUI não trava (ver sync.py)
    job = sync.start() if sync.needed() else None

    delta = total_after - total_before
    sign  = '+' if delta >= 0 else ''
    return True, f'✓ Salvo  ({sign}{brl_fmt(delta)})', job


def empty_portfolio():
    """Carteira vazia com os mesmos parâmetros do exemplo (alocação ideal etc.)."""
    with open(config.EXAMPLE, encoding='utf-8') as f:
        d = json.load(f)
    d['lastUpdated'] = datetime.now().strftime('%Y-%m-%d')
    d['fgts'] = 0.0
    d['emergencyReserve'].pop('assetNames', None)  # reserva = ativos com allocationGroup RESERVA_EMERGENCIA
    d['investments'] = []
    return d


def first_run():
    """Cria data/investments.json na primeira execução."""
    print(f'\n{BLD}{G}Bem-vindo ao investsh!{RST}')
    print(f'{DIM}Não encontrei {config.DATA}.{RST}\n')
    print(f'  {C}[1]{RST} Começar com carteira vazia {DIM}(recomendado){RST}')
    print(f'  {C}[2]{RST} Copiar dados de exemplo {DIM}(para explorar o app){RST}')
    print(f'  {C}[x]{RST} Sair')
    choice = input(f'\n{C}Escolha{RST} [1]: ').strip().lower() or '1'
    if choice == '1':
        d = empty_portfolio()
    elif choice == '2':
        with open(config.EXAMPLE, encoding='utf-8') as f:
            d = json.load(f)
    else:
        sys.exit(0)
    os.makedirs(os.path.dirname(config.DATA), exist_ok=True)
    write_json(config.DATA, d)
    print(f'{G}✓ Criado {config.DATA}{RST}')
    print(f'{DIM}  Ajuste alocação ideal, reserva e projeção em "Parâmetros".{RST}\n')
    return d
