"""`investsh check`: procura inconsistências nos dados (investments.json e history.json).

Só lê: aponta o problema e onde corrigir, sem mudar nada. Erros são dados que quebram
cálculos; avisos são situações que costumam ser esquecimento (título vencido com saldo,
salto de saldo sem aporte...).
"""
import json
import os
from datetime import date

from .core import GROUP_META, asset_key, can_transfer, parse_maturity, brl_fmt, stale_assets

# Variação de saldo desde o save anterior, sem aporte/saque, que merece conferência
JUMP = 0.20

# Renda fixa com prazo: espera-se vencimento e taxa cadastrados
FIXED_INCOME = {'CDB', 'LCA', 'LCI', 'RDB', 'Tesouro Direto'}


def _label(inv):
    return f'{inv.get("name", "?")} ({inv.get("broker", "?")})'


def find_problems(data, history, today, stale_days=None):
    """Lista de {'level': 'erro'|'aviso', 'where': str, 'message': str}."""
    from .config import DEFAULT_STALE_DAYS
    stale_days = DEFAULT_STALE_DAYS if stale_days is None else stale_days
    out = []

    def add(level, where, message):
        out.append({'level': level, 'where': where, 'message': message})

    invs = data.get('investments', [])
    flows = data.get('flows', [])
    prev_save = _prev_save(history, data.get('lastUpdated') or '')

    # ── Ativos ────────────────────────────────────────────────────────────────
    seen = {}
    for inv in invs:
        key = asset_key(inv)
        if key in seen:
            add('erro', _label(inv), 'nome repetido na mesma corretora: renomeie um deles (Editar dados)')
        seen[key] = inv

    for inv in invs:
        where = _label(inv)
        bal = inv.get('balance')
        if not isinstance(bal, (int, float)):
            add('erro', where, 'sem saldo (balance)')
            continue
        if bal < 0:
            add('erro', where, f'saldo negativo: {brl_fmt(bal)}')

        mat = inv.get('maturity')
        due = parse_maturity(mat) if mat else None
        if mat and due is None:
            add('erro', where, f'vencimento inválido: "{mat}" (use AAAA-MM-DD)')
        elif due and due < today and bal > 0:
            add('aviso', where, f'venceu em {due.isoformat()} e ainda tem saldo de {brl_fmt(bal)}: '
                                'use Liquidar vencimento')

        group = inv.get('allocationGroup')
        if not group:
            add('aviso', where, 'sem grupo de alocação: fica fora das metas de alocação')
        elif group not in GROUP_META:
            add('aviso', where, f'grupo de alocação desconhecido: {group}')

        if inv.get('category') in FIXED_INCOME:
            # Liquidez imediata/diária (caixinha, CDB de liquidez) costuma não ter vencimento
            if not mat and inv.get('liquidity') not in ('IMMEDIATE', 'DAILY'):
                add('aviso', where, 'renda fixa sem vencimento')
            if not inv.get('rate'):
                add('aviso', where, 'renda fixa sem taxa (rate)')

        cost = inv.get('invested') or inv.get('investedUSD')
        if bal == 0 and cost and can_transfer(inv):
            add('aviso', where, 'saldo zerado com custo registrado: exclua ou liquide o ativo')

        # Salto de saldo desde o save anterior sem aporte/saque no meio (ex.: o saldo
        # anterior de outro ativo gravado neste por engano)
        prev = inv.get('previousBalance')
        moved = any((f.get('name'), f.get('broker')) == asset_key(inv) and f.get('date', '') > prev_save
                    for f in flows)
        if (isinstance(prev, (int, float)) and prev > 0 and can_transfer(inv) and not moved
                and abs(bal - prev) / prev > JUMP):
            add('aviso', where, f'saldo variou {(bal - prev) / prev * 100:+.0f}% desde o save anterior '
                                f'({brl_fmt(prev)} → {brl_fmt(bal)}) sem aporte nem saque: confira')

    for s in stale_assets(invs, history, today, stale_days):
        add('aviso', f'{s["name"]} ({s["broker"]})',
            f'saldo sem atualização há {s["days"]} dias (desde {s["since"].strftime("%d/%m/%Y")})')

    names = (data.get('emergencyReserve') or {}).get('assetNames') or []
    for n in names:
        if not any(i.get('name') == n for i in invs):
            add('aviso', 'Reserva de emergência', f'"{n}" está em assetNames mas não existe na carteira')

    # ── Lançamentos ───────────────────────────────────────────────────────────
    known = {asset_key(i) for i in invs}
    for snap in history:
        known |= {(a.get('name'), a.get('broker')) for a in snap.get('assets') or []}
    for f in flows:
        where = f'Lançamento {f.get("date", "?")} {f.get("name", "?")}'
        day = parse_maturity(f.get('date')) if f.get('date') else None
        if day is None:
            add('erro', where, f'data inválida: "{f.get("date")}"')
        elif day > today:
            add('aviso', where, 'data no futuro')
        amount = f.get('amount')
        if not isinstance(amount, (int, float)):
            add('erro', where, 'sem valor (amount)')
        elif amount == 0:
            add('aviso', where, 'valor zero')
        elif f.get('kind') == 'provento' and amount > 0:
            add('erro', where, 'provento com valor positivo (provento é saída: negativo)')
        if (f.get('name'), f.get('broker')) not in known:
            add('aviso', where, f'ativo {f.get("name")} ({f.get("broker")}) não existe nem existiu '
                                'no histórico: corrija na aba Lançamentos')

    for t in data.get('transfers', []):
        where = f'Transferência {t.get("date", "?")} {t.get("from", "?")} → {t.get("to", "?")}'
        if (parse_maturity(t.get('date')) if t.get('date') else None) is None:
            add('erro', where, f'data inválida: "{t.get("date")}"')
        if not isinstance(t.get('amount'), (int, float)) or t['amount'] < 0:
            add('erro', where, f'valor inválido: {t.get("amount")!r}')
        for n, b in (('from', 'fromBroker'), ('to', 'toBroker')):
            if (t.get(n), t.get(b)) not in known:
                add('aviso', where, f'ativo {t.get(n)} ({t.get(b)}) não existe nem existiu no histórico')

    # ── Histórico ─────────────────────────────────────────────────────────────
    dates = [s.get('date') for s in history]
    for d in sorted({d for d in dates if dates.count(d) > 1}):
        add('aviso', 'Histórico', f'mais de uma foto na data {d}')
    if dates != sorted(dates, key=lambda d: d or ''):
        add('aviso', 'Histórico', 'fotos fora de ordem de data')

    return out


def _prev_save(history, last):
    """Data do save anterior ao último (início do período do previousBalance)."""
    dates = sorted({s.get('date') or '' for s in history if (s.get('date') or '') < last})
    return dates[-1] if dates else ''


def main(root, today=None):
    """Imprime os problemas encontrados. Devolve 1 se houver erro, senão 0."""
    from .term import R, Y, G, DIM, RST, BLD
    data_path = os.path.join(root, 'data', 'investments.json')
    hist_path = os.path.join(root, 'data', 'history.json')
    try:
        with open(data_path, encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f'investsh check: {data_path} não existe')
        return 1
    except json.JSONDecodeError as e:
        print(f'{R}✗ {data_path} não é um JSON válido: {e}{RST}')
        return 1
    try:
        with open(hist_path, encoding='utf-8') as f:
            history = json.load(f)
    except FileNotFoundError:
        history = []
    except json.JSONDecodeError as e:
        print(f'{R}✗ {hist_path} não é um JSON válido: {e}{RST}')
        return 1

    from . import config
    try:
        settings = config.load_file(os.path.join(root, config.CONFIG_FILE))
    except config.ConfigError as e:
        print(f'{R}✗ {e}{RST}')
        return 2
    stale_days = settings.get('alerts', {}).get('stale_days', config.DEFAULT_STALE_DAYS)
    problems = find_problems(data, history, today or date.today(), stale_days)
    errors = [p for p in problems if p['level'] == 'erro']
    warnings = [p for p in problems if p['level'] == 'aviso']
    if not problems:
        print(f'{G}✓ Nenhum problema encontrado{RST} {DIM}({data_path}){RST}')
        return 0
    print(f'{BLD}investsh check{RST}: {len(errors)} erro(s), {len(warnings)} aviso(s) {DIM}({data_path}){RST}')
    for title, items, mark, col in (('Erros', errors, '✗', R), ('Avisos', warnings, '⚠', Y)):
        if items:
            print(f'\n{col}{BLD}{title}{RST}')
            for p in items:
                print(f'  {col}{mark}{RST} {p["where"]}: {p["message"]}')
    return 1 if errors else 0
