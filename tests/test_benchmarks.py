"""CDI/IPCA do Banco Central: cache local e funcionamento sem internet."""
import pytest

from support import strip_ansi


def view(app, **env):
    proc = app.menu(['V', 'x'], **env)
    assert proc.returncode == 0, proc.stderr
    out = strip_ansi(proc.stdout)
    return out[out.index('▸ Rentabilidade'):out.index('▸ Alocação')]


def test_rentabilidade_in_menu_view(demo):
    section = view(demo)
    assert 'Desde 01/10/2025' in section
    assert '% do CDI' in section
    assert 'indisponíveis' not in section


def test_cache_is_outside_data_folder(demo):
    view(demo)
    cache = demo.home / '.cache' / 'investsh'
    assert (cache / 'cdi.json').exists() and (cache / 'ipca.json').exists()
    assert not list(demo.root.rglob('cdi.json'))


def test_offline_uses_cache(demo):
    online = view(demo)
    offline = view(demo, INVESTSH_TEST_RATES='fail')
    assert offline == online


def test_offline_without_cache(demo):
    section = view(demo, INVESTSH_TEST_RATES='fail')
    assert 'CDI/IPCA indisponíveis (sem conexão com o Banco Central e sem cache)' in section
    assert 'Desde 01/10/2025' in section          # a carteira continua calculada


def test_ipca_not_yet_published_is_flagged(demo):
    # No ambiente de testes o IPCA só existe até agosto/2026
    assert '* IPCA dos meses ainda não divulgados fica de fora do acumulado.' in view(demo)


def test_insufficient_history(app):
    app.seed('examples', history=False)
    assert 'Precisa de dois saves com total investido' in view(app)


@pytest.mark.parametrize('days, expected', [(90, False), (500, True)])
def test_maturity_window_from_config(demo, days, expected):
    (demo.root / 'investsh.toml').write_text(f'[alerts]\nmaturity_days = {days}\n', encoding='utf-8')
    out = strip_ansi(demo.menu(['V', 'x']).stdout)
    # LCA Banco Beta vence em 20/11/2027: só aparece com janela de 500 dias
    assert (f'Vencimentos (próximos {days} dias)' in out) is expected
    assert ('LCA Banco Beta 95% CDI' in out.split('▸ Alocação')[0]) is expected


@pytest.mark.parametrize('value, message', [
    ('"90"', 'alerts.maturity_days deve ser um número inteiro'),
    ('true', 'alerts.maturity_days deve ser um número inteiro'),
    ('-1', 'alerts.maturity_days não pode ser negativo'),
])
def test_invalid_maturity_days(demo, value, message):
    (demo.root / 'investsh.toml').write_text(f'[alerts]\nmaturity_days = {value}\n', encoding='utf-8')
    proc = demo.menu(['x'])
    assert proc.returncode == 2
    assert message in proc.stderr


@pytest.mark.parametrize('status', ['404', '200'])
def test_ipca_not_published_in_whole_period_is_not_an_error(app, status):
    # Histórico só em set/out 2026: nenhum IPCA divulgado ainda (o falso só tem até agosto)
    app.seed('examples', history=False)
    app.write('history.json', [
        {'date': '2026-09-14', 'total': 1000.0, 'totalInvested': 1000.0},
        {'date': '2026-10-05', 'total': 1012.0, 'totalInvested': 1000.0},
    ])
    section = view(app, INVESTSH_TEST_BCB_EMPTY=status)
    assert 'indisponíve' not in section
    assert '+1.20%' in section and '—*' in section
    assert '* IPCA dos meses ainda não divulgados' in section
