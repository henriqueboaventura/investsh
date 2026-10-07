"""Regressão do modo texto: `finances.py --menu`.

Cada cenário grava num golden a saída completa (com as cores, em forma legível)
e o estado final de data/.
"""
import re
import subprocess

import pytest

from support import assert_golden, strip_ansi

ANSI_NAMES = {'0': 'RST', '1': 'BLD', '2': 'DIM', '91': 'R', '92': 'G', '93': 'Y',
              '95': 'M', '96': 'C', '97': 'W'}


# Avisos do matplotlib que dependem da máquina (fontes instaladas, cache) — não são saída do app
ENV_NOISE = re.compile(r'^(findfont: .*|Matplotlib is building the font cache.*)\n', re.M)


def normalize_stderr(err):
    """Remove ruído de ambiente; traceback vira só a exceção final (formato muda entre Pythons)."""
    err = ENV_NOISE.sub('', err)
    if 'Traceback (most recent call last):' in err:
        last = [l for l in err.strip().splitlines() if l and not l.startswith(' ')][-1]
        err = err[:err.index('Traceback')] + f'Traceback → {last}\n'
    return err


def readable(app, proc):
    out = re.sub(r'\x1b\[(\d+)m', lambda m: '{' + ANSI_NAMES.get(m.group(1), m.group(1)) + '}',
                 proc.stdout)
    out = app.normalize(out)
    err = app.normalize(normalize_stderr(proc.stderr))
    return f'# exit={proc.returncode}\n# stderr:\n{err}# stdout:\n{out}'


def golden_run(app, name, stdin, with_data=True, **env):
    proc = app.menu(stdin, **env)
    text = readable(app, proc)
    if with_data:
        text += '\n' + app.data_snapshot()
    assert_golden(f'menu/{name}.txt', text)
    return proc


def index_of(app, option, name):
    """Índice que o menu mostra para `name` na listagem da opção (aporte/saque/remover)."""
    proc = app.menu([option, '', 'x'])
    for line in strip_ansi(proc.stdout).splitlines():
        m = re.match(r'\s*\[\s*(\d+)\]\s+\S+\s+(.*?)\s{2,}', line + '  ')
        if m and m.group(2).strip() == name:
            return m.group(1)
    raise AssertionError(f'{name} não listado na opção {option}')


# ── Visualização ─────────────────────────────────────────────────────────────

def test_view_demo(demo):
    golden_run(demo, 'view_demo', ['V', 'x'], with_data=False)


def test_view_edge(app):
    app.seed('edge')
    golden_run(app, 'view_edge', ['V', 'x'], with_data=False)


def test_view_reserve_above_max(demo):
    demo.edit(lambda d: d['emergencyReserve'].update(minimum=1000.0, target=2000.0, maximum=5000.0))
    golden_run(demo, 'view_reserve_above', ['V', 'x'], with_data=False)


def test_view_without_reserve_config_and_history(demo):
    (demo.data_dir / 'history.json').unlink()
    demo.edit(lambda d: d.pop('emergencyReserve'))
    golden_run(demo, 'view_no_reserve_no_history', ['V', 'x'], with_data=False)


def test_view_rates_unavailable(demo):
    golden_run(demo, 'view_rates_fail', ['V', 'x'], with_data=False, INVESTSH_TEST_RATES='fail')


def test_invalid_option_and_exit_without_saving(demo):
    before = demo.data_snapshot()
    golden_run(demo, 'invalid_option', ['zz', '9', 'x'], with_data=False)
    assert demo.data_snapshot() == before


# ── Primeira execução ────────────────────────────────────────────────────────

def test_first_run_empty_portfolio(app):
    # Sem matplotlib: o fluxo não depende da versão da biblioteca (ver teste abaixo)
    golden_run(app, 'first_run_empty', ['1', 'V', '0', 's'], INVESTSH_TEST_NO_MPL='1')


@pytest.mark.xfail(reason='BUG conhecido: com matplotlib recente (ex.: 3.11), salvar carteira vazia quebra '
                          'em generate_status_image (pie sem fatias) depois de gravar data/',
                   strict=False)
def test_save_empty_portfolio_with_matplotlib(app):
    proc = app.menu(['1', '0', 's'])
    assert proc.returncode == 0, proc.stderr


def test_first_run_default_choice_is_empty(app):
    golden_run(app, 'first_run_default', ['', 'x'])


def test_first_run_copy_examples(app):
    golden_run(app, 'first_run_examples', ['2', 'x'])


def test_first_run_quit(app):
    proc = golden_run(app, 'first_run_quit', ['x'])
    assert not (app.data_dir / 'investments.json').exists()
    assert proc.returncode == 0


# ── Atualização de saldos ────────────────────────────────────────────────────

def test_update_all(demo):
    n = len(demo.read('investments.json')['investments'])
    answers = [''] * n
    answers[0] = 'abc\n23500'          # inválido, depois válido
    answers[1] = 's'                   # pular
    answers[2] = '13700,5'             # vírgula decimal
    answers[3] = '0'                   # zera saldo
    answers[n - 4] = '900'             # algum ativo em USD (SGOV/AOK/VT ficam antes das criptos)
    answers[n - 2] = '0.005'           # Bitcoin
    answers[n - 1] = 's'               # Ethereum: pular
    golden_run(demo, 'update_all', ['1', *answers, '0', 's'])


def test_update_single_flows(demo):
    golden_run(demo, 'update_single', [
        '2', 'tesouro', '0,2', '25000', '',     # múltiplos: seleciona 0 e 2
        '2', 'tesouro', '', '', '', '',          # múltiplos: Enter = todos
        '2', '3', '9999',                        # por número
        '2', 'bitcoin', '0.01',                  # cripto
        '2', 'VT', '1800',                       # ativo em USD
        '2', 'zzz',                              # não encontrado → lista
        '2', '',                                 # cancelar
        '0', 's',
    ])


# ── Aporte e saque ───────────────────────────────────────────────────────────

def test_aporte(demo):
    brl = index_of(demo, '3', 'CDB Banco Alfa 110% CDI')
    usd = index_of(demo, '3', 'SGOV')
    btc = index_of(demo, '6', 'Bitcoin')  # crypto não aparece na lista de aporte
    golden_run(demo, 'aporte', [
        '3', brl, '1000',
        '3', brl, '0,37',         # centavos: pega erro de arredondamento
        '3', usd, '150,5',
        '3', btc,                 # crypto → recusado
        '3', '999',               # índice inválido
        '3', brl, '0',            # valor zero → nada
        '3', '',                  # cancelar
        '0', 's',
    ])


def test_saque(demo):
    brl = index_of(demo, '4', 'LCA Banco Beta 95% CDI')
    usd = index_of(demo, '4', 'VT')
    golden_run(demo, 'saque', [
        '4', brl, '6380,09',
        '4', usd, '230.4',
        '4', brl, '999999',       # maior que o saldo
        '4', '999',
        '4', '',
        '0', 's',
    ])


def test_saque_without_cost_basis(app):
    app.seed('edge')
    idx = index_of(app, '4', 'Ativo sem custo base')
    golden_run(app, 'saque_sem_custo', ['4', idx, '1000', '0', 's'])


# ── Cadastro, remoção, parâmetros ────────────────────────────────────────────

def test_add_assets(demo):
    golden_run(demo, 'add_assets', [
        '5',
        'CDB Novo', '0', 'x', '0', '1', '2027-01-01', '0', '0', '0', '5000', '5100,25', 's',
        'ETF EUA', '4', '4', '2', '', '4', '7', '9', '300', 's',
        'Solana', '8', '4', '3', '', '9', '11', '13', '2,5', 's',
        'Debênture X', '0', '2', '1', '2031-05-15', '10', 'IPCA+DEB', '14', 'GRUPO_X', '23', 'MEU_OBJETIVO',
        '1000', '1000', 'n',
        '5', '',                  # nome vazio → volta ao menu
        '0', 's',
    ])


def test_remove_assets(demo):
    golden_run(demo, 'remove', ['6', '0, 99,abc,0', '6', '', '0', 's'])


def test_remove_multiple_assets(demo):
    # A ordem das mensagens "✗ Removido" vem de um set (varia entre versões do Python):
    # aqui só o resultado é verificado.
    names = [i['name'] for i in demo.read('investments.json')['investments']]
    a, b = index_of(demo, '6', 'Tesouro Selic 2029'), index_of(demo, '6', 'Bitcoin')
    proc = demo.menu(['6', f'{a},{b}', '0', 's'])
    out = strip_ansi(proc.stdout)
    assert out.count('✗ Removido:') == 2
    assert '✗ Removido: Tesouro Selic 2029' in out and '✗ Removido: Bitcoin' in out
    left = [i['name'] for i in demo.read('investments.json')['investments']]
    assert left == [n for n in names if n not in ('Tesouro Selic 2029', 'Bitcoin')]


def test_params(demo):
    answers = ['20000', '0,9', '', '7',            # FGTS, rendimento, aporte (mantém), FGTS a.a.
               '50', '', '12', '', '', '', '', '', '', '', '', '', '3', '',   # 14 metas
               '25000', '', 's']                    # reserva: mínimo, meta, máximo (s = pular)
    golden_run(demo, 'params', ['7', *answers, '0', 's'])


# ── Salvar ───────────────────────────────────────────────────────────────────

def test_save_declined(demo):
    before = demo.data_snapshot()
    golden_run(demo, 'save_declined', ['0', 'n'], with_data=False)
    assert demo.data_snapshot() == before


def test_save_unchanged_twice_same_day(demo):
    golden_run(demo, 'save_twice_1', ['0', 's'])
    golden_run(demo, 'save_twice_2', ['2', 'bova', '9900', '0', 's'])


def test_save_without_history_file(demo):
    (demo.data_dir / 'history.json').unlink()
    golden_run(demo, 'save_no_history', ['0', 's'])


def test_save_auto_git(demo, tmp_path):
    remote = tmp_path / 'remote.git'
    git = lambda *a, cwd=demo.root: subprocess.run(['git', *a], cwd=cwd, check=True,
                                                    capture_output=True, text=True).stdout
    git('init', '-q', '--bare', str(remote), cwd=tmp_path)
    git('init', '-q', '-b', 'main')
    git('config', 'user.email', 'test@example.com')
    git('config', 'user.name', 'Test')
    git('add', 'data')
    git('commit', '-q', '-m', 'seed')
    git('remote', 'add', 'origin', str(remote))
    git('push', '-q', '-u', 'origin', 'main')

    proc = demo.menu(['2', 'bova', '9900', '0', 's'], FINANCES_AUTO_GIT='1')
    out = strip_ansi(proc.stdout)
    assert proc.returncode == 0, proc.stderr
    assert '✓ Commit criado: update 2026-10' in out
    assert '✓ Push concluído' in out
    assert git('log', '-1', '--format=%s') == 'update 2026-10\n'
    assert sorted(git('show', '--name-only', '--format=', 'HEAD').split()) == [
        'assets/status.png', 'data/history.json', 'data/investments.json']
    assert git('rev-parse', 'HEAD') == git('rev-parse', 'main', cwd=remote)

    # Sem mudanças no mesmo dia: nada a commitar, mas o push roda mesmo assim
    proc = demo.menu(['0', 's'], FINANCES_AUTO_GIT='1')
    assert '✓ Push concluído' in strip_ansi(proc.stdout)
    assert git('rev-list', '--count', 'HEAD') == '2\n'  # seed + update


def test_save_auto_git_outside_repo(demo):
    proc = demo.menu(['0', 's'], FINANCES_AUTO_GIT='1')
    assert proc.returncode == 0
    assert 'Erro no git' in strip_ansi(proc.stdout)


def test_auto_git_off_by_default(demo, tmp_path):
    subprocess.run(['git', 'init', '-q'], cwd=demo.root, check=True)
    demo.menu(['0', 's'])
    log = subprocess.run(['git', 'log'], cwd=demo.root, capture_output=True, text=True)
    assert log.returncode != 0  # nenhum commit criado


@pytest.mark.parametrize('value', ['true', 'yes', 'TRUE'])
def test_auto_git_accepts_truthy_values(demo, value):
    proc = demo.menu(['0', 's'], FINANCES_AUTO_GIT=value)
    assert 'Erro no git' in strip_ansi(proc.stdout)  # tentou usar git (fora de repo)


# ── Casos-limite ─────────────────────────────────────────────────────────────

def test_updates_edge_rates_unavailable(app):
    app.seed('edge')
    n = len(app.read('investments.json')['investments'])
    answers = [''] * n
    answers[n - 2] = '0.02'   # Bitcoin (Binance vem antes da corretora desconhecida): sem cotação
    golden_run(app, 'update_edge_rates_fail', [
        '1', *answers,
        '2', 'bitcoin', '0.03',
        '2', 'sem custo', '2900',
        '0', 's',
    ], INVESTSH_TEST_RATES='fail')


def test_aporte_saque_edge(app):
    app.seed('edge')
    btc = index_of(app, '6', 'Bitcoin')
    usd = index_of(app, '4', 'ETF USD sem balanceUSD')
    brl = index_of(app, '4', 'Reserva CDB')
    golden_run(app, 'aporte_saque_edge', [
        '3', '',                                  # lista do aporte (ativo sem custo base fica de fora)
        '4', btc,                                 # cripto: recusado
        '4', usd, '0',                            # zero: nada
        '4', usd, '999',                          # maior que o saldo em USD
        '4', usd, '50',
        '4', brl, '0',
        '0', 's',
    ])


def test_save_without_matplotlib(demo):
    golden_run(demo, 'save_no_matplotlib', ['0', 's'], INVESTSH_TEST_NO_MPL='1')
    assert not (demo.root / 'assets' / 'status.png').exists()


def test_save_auto_git_without_git_installed(demo, tmp_path):
    empty = tmp_path / 'empty-bin'
    empty.mkdir()
    proc = demo.menu(['0', 's'], FINANCES_AUTO_GIT='1', PATH=empty)
    assert proc.returncode == 0
    assert 'git não encontrado, commit pulado.' in strip_ansi(proc.stdout)
