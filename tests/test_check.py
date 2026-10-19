"""`investsh check`: inconsistências nos dados, com valores montados à mão."""
from datetime import date

from support import FINANCES_CMD, strip_ansi

TODAY = date(2026, 10, 18)


def check():
    import importlib
    import sys
    from support import PKG_SRC
    if str(PKG_SRC) not in sys.path:
        sys.path.insert(0, str(PKG_SRC))
    return importlib.import_module('investsh.check')


def asset(**kw):
    base = {'name': 'CDB', 'category': 'CDB', 'broker': 'XP', 'balance': 100.0, 'invested': 90.0,
            'maturity': '2028-01-01', 'rate': {'kind': 'PERCENT_CDI', 'value': 100.0},
            'allocationGroup': 'RF_CDI'}
    base.update(kw)
    return base


def problems(investments=(), flows=(), history=(), **extra):
    data = {'investments': list(investments), 'flows': list(flows), 'lastUpdated': '2026-10-18', **extra}
    return [(p['level'], p['where'], p['message']) for p in check().find_problems(data, list(history), TODAY)]


def test_clean_data_has_no_problems():
    assert problems([asset()]) == []


def test_asset_errors():
    found = problems([asset(), asset(balance=-5.0), asset(name='X', maturity='2028-13-01'),
                      asset(name='Y', balance=None)])
    assert ('erro', 'CDB (XP)', 'nome repetido na mesma corretora: renomeie um deles (Editar dados)') in found
    assert ('erro', 'CDB (XP)', 'saldo negativo: R$ -5,00') in found
    assert ('erro', 'X (XP)', 'vencimento inválido: "2028-13-01" (use AAAA-MM-DD)') in found
    assert ('erro', 'Y (XP)', 'sem saldo (balance)') in found


def test_matured_with_balance_and_zeroed_asset():
    found = problems([asset(maturity='2026-10-15'), asset(name='Z', balance=0.0, maturity='2026-10-01')])
    assert found == [
        ('aviso', 'CDB (XP)', 'venceu em 2026-10-15 e ainda tem saldo de R$ 100,00: use Liquidar vencimento'),
        ('aviso', 'Z (XP)', 'saldo zerado com custo registrado: exclua ou liquide o ativo'),
    ]


def test_fixed_income_without_rate_or_maturity():
    found = problems([asset(rate=None, maturity=None),
                      asset(name='Caixinha', maturity=None, liquidity='DAILY')])
    assert found == [('aviso', 'CDB (XP)', 'renda fixa sem vencimento'),
                     ('aviso', 'CDB (XP)', 'renda fixa sem taxa (rate)')]


def test_allocation_group_and_reserve_names():
    found = problems([asset(allocationGroup=None), asset(name='B', allocationGroup='XYZ')],
                     emergencyReserve={'assetNames': ['Sumiu']})
    assert found == [
        ('aviso', 'CDB (XP)', 'sem grupo de alocação: fica fora das metas de alocação'),
        ('aviso', 'B (XP)', 'grupo de alocação desconhecido: XYZ'),
        ('aviso', 'Reserva de emergência', '"Sumiu" está em assetNames mas não existe na carteira'),
    ]


def test_balance_jump_without_flow():
    # O bug do CDB C6: saldo anterior de outro ativo gravado neste (+45% sem aporte)
    history = [{'date': '2026-10-01'}, {'date': '2026-10-18'}]
    jump = asset(balance=22163.88, previousBalance=15250.29)
    assert problems([jump], history=history) == [
        ('aviso', 'CDB (XP)', 'saldo variou +45% desde o save anterior '
                              '(R$ 15.250,29 → R$ 22.163,88) sem aporte nem saque: confira')]
    # Com um aporte no período, a variação está explicada
    flow = {'date': '2026-10-10', 'name': 'CDB', 'broker': 'XP', 'amount': 6900.0}
    assert problems([jump], flows=[flow], history=history) == []
    # Cripto oscila: fica de fora
    assert problems([asset(category='Crypto', balance=200.0, previousBalance=100.0)], history=history) == []


def test_flow_problems():
    flows = [
        {'date': '2026-13-01', 'name': 'CDB', 'broker': 'XP', 'amount': 10.0},
        {'date': '2026-11-01', 'name': 'CDB', 'broker': 'XP', 'amount': 10.0},
        {'date': '2026-10-01', 'name': 'CDB', 'broker': 'XP', 'amount': 0},
        {'date': '2026-10-01', 'name': 'CDB', 'broker': 'XP', 'amount': 5.0, 'kind': 'provento'},
        {'date': '2026-10-01', 'name': 'Velho', 'broker': 'XP', 'amount': -5.0},
        {'date': '2026-10-01', 'name': 'Typo', 'broker': 'XP', 'amount': -5.0},
    ]
    history = [{'date': '2026-09-01', 'assets': [{'name': 'Velho', 'broker': 'XP'}]}]
    assert [p[2] for p in problems([asset()], flows=flows, history=history)] == [
        'data inválida: "2026-13-01"',
        'data no futuro',
        'valor zero',
        'provento com valor positivo (provento é saída: negativo)',
        'ativo Typo (XP) não existe nem existiu no histórico: corrija na aba Lançamentos',
    ]


def test_history_dates():
    found = problems(history=[{'date': '2026-10-01'}, {'date': '2026-09-01'}, {'date': '2026-09-01'}])
    assert found == [('aviso', 'Histórico', 'mais de uma foto na data 2026-09-01'),
                     ('aviso', 'Histórico', 'fotos fora de ordem de data')]


def test_cli_exit_codes(app):
    app.seed('examples')
    proc = app.run(FINANCES_CMD, ['check'])
    out = strip_ansi(proc.stdout)
    assert proc.returncode == 0, proc.stderr
    assert 'erro(s)' in out or 'Nenhum problema' in out
    app.edit(lambda d: d['investments'][0].update(maturity='31-02-2030'))
    proc = app.run(FINANCES_CMD, ['check'])
    assert proc.returncode == 1
    assert 'vencimento inválido: "31-02-2030"' in strip_ansi(proc.stdout)


def test_cli_without_data(app):
    proc = app.run(FINANCES_CMD, ['check'])
    assert proc.returncode == 1
    assert 'não existe' in proc.stdout


def test_stale_balance_warning():
    history = [{'date': '2026-08-01', 'assets': [{'name': 'CDB', 'broker': 'XP', 'balance': 100.0}]}]
    assert problems([asset()], history=history) == [
        ('aviso', 'CDB (XP)', 'saldo sem atualização há 78 dias (desde 01/08/2026)')]


def test_cli_reads_stale_days_from_config(app):
    app.seed('examples')
    (app.root / 'investsh.toml').write_text('[alerts]\nstale_days = 1\n', encoding='utf-8')
    proc = app.run(FINANCES_CMD, ['check'])
    assert 'saldo sem atualização há' in strip_ansi(proc.stdout)
