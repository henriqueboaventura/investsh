"""Primeira execução, salvar carteira e histórico, commit automático."""
import json, os, sys
from datetime import datetime

from . import config, sync
from .term import G, R, Y, C, W, DIM, RST, BLD, fmt, ask_yes, print_header
from .core import brl_fmt, history_snapshot, start_flow_log
from .image import generate_status_image


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
        prev = pre_balances.get(inv['name'])
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

    start_flow_log(data)
    write_json(config.DATA, data)
    print(f'\n{G}{BLD}✓ Salvo em {config.DATA}{RST}')

    hist_path = os.path.join(config.ROOT, 'data', 'history.json')
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

    write_json(hist_path, history)
    print(msg)


    generate_status_image(data)

    # Auto-commit (opcional — ver investsh.toml no README)
    if config.AUTO_GIT:
        import subprocess
        month = datetime.now().strftime('%Y-%m')
        try:
            subprocess.run(['git', '-C', config.ROOT, 'add',
                            'data/investments.json', 'data/history.json',
                            'assets/'], check=True)
            result = subprocess.run(
                ['git', '-C', config.ROOT, 'commit', '-m', f'update {month}'],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                print(f'{G}✓ Commit criado: update {month}{RST}')
            else:
                # Nada para commitar (sem mudanças nos arquivos)
                print(f'{DIM}  Git: {result.stdout.strip() or result.stderr.strip()}{RST}')
            # Push mesmo sem commit novo: envia commits pendentes de saves anteriores
            if config.GIT_PUSH:
                subprocess.run(['git', '-C', config.ROOT, 'push'], check=True)
                print(f'{G}✓ Push concluído{RST}')
        except FileNotFoundError:
            print(f'{Y}  git não encontrado, commit pulado.{RST}')
        except subprocess.CalledProcessError as e:
            print(f'{Y}  Erro no git: {e}{RST}')

    print()
    return True


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
