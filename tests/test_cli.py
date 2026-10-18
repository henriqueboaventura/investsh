"""Linha de comando: escolha do diretório de dados e subcomandos."""
import shutil

from support import ANALYZE_CMD, EXAMPLES, FINANCES_CMD, strip_ansi


def other_dir(app):
    d = app.root / 'outra' / 'carteira'
    (d / 'data').mkdir(parents=True)
    shutil.copy(EXAMPLES / 'investments.json', d / 'data' / 'investments.json')
    return d


def test_version(app):
    from investsh import __version__
    proc = app.run(FINANCES_CMD, ['--version'])
    assert proc.returncode == 0
    assert proc.stdout.strip() == f'investsh {__version__}'


def check(app, *args, **env):
    """`investsh check` diz qual investments.json leu: serve para conferir a pasta escolhida."""
    proc = app.run(FINANCES_CMD, ['check', *args], **env)
    return proc, strip_ansi(proc.stdout)


def test_dir_option(app):
    d = other_dir(app)
    proc, out = check(app, '--dir', str(d))
    assert proc.returncode == 0, proc.stderr
    assert f'({d}/data/investments.json)' in out


def test_dir_from_environment(app):
    d = other_dir(app)
    proc, out = check(app, INVESTSH_DIR=d)
    assert proc.returncode == 0, proc.stderr
    assert f'({d}/data/investments.json)' in out


def test_dir_option_wins_over_environment(app):
    d = other_dir(app)
    proc, out = check(app, '--dir', str(d), INVESTSH_DIR=app.root / 'nao-existe')
    assert proc.returncode == 0, proc.stderr
    assert f'({d}/data/investments.json)' in out


def test_analyze_dir_option(app, tmp_path):
    d = other_dir(app)
    empty = tmp_path / 'empty-bin'
    empty.mkdir()
    proc = app.run(ANALYZE_CMD, ['--dir', str(d)], PATH=empty)
    assert proc.returncode == 0, proc.stderr
    assert (d / 'analise_prompt.txt').exists()


def test_default_dir_is_home_investsh(app):
    proc, out = check(app, INVESTSH_DIR=None)
    assert f'{app.home}/.investsh/data/investments.json não existe' in out


def test_current_dir_not_used_by_default(demo):
    # Rodar dentro de uma pasta com dados não usa essa pasta: o padrão é ~/.investsh
    proc, out = check(demo, INVESTSH_DIR=None)
    assert f'{demo.home}/.investsh/data/investments.json não existe' in out


def test_dir_dot_uses_current_dir(demo):
    proc, out = check(demo, '--dir', '.', INVESTSH_DIR=None)
    assert proc.returncode == 0, proc.stderr
    assert demo.normalize(out).endswith('(<APP>/data/investments.json)\n')   # /tmp ou /private/tmp


def test_tilde_expansion(app):
    for args, env in ((['--dir', '~/carteira-a'], {}), ([], {'INVESTSH_DIR': '~/carteira-b'})):
        proc, out = check(app, *args, **env)
        name = 'carteira-a' if args else 'carteira-b'
        assert f'{app.home}/{name}/data/investments.json não existe' in out


def test_menu_was_removed(app):
    proc = app.run(FINANCES_CMD, ['--menu'])
    assert proc.returncode == 2
    assert 'o --menu (modo texto) foi removido na versão 1.0.0' in proc.stderr


def test_help_shows_data_dir(app):
    proc = app.run(FINANCES_CMD, ['--help'], INVESTSH_DIR=None, COLUMNS=200)
    assert proc.returncode == 0
    assert f'Pasta de dados: {app.home}/.investsh' in proc.stdout


def test_analyze_default_dir(app, tmp_path):
    default = app.home / '.investsh'
    (default / 'data').mkdir(parents=True)
    shutil.copy(EXAMPLES / 'investments.json', default / 'data' / 'investments.json')
    empty = tmp_path / 'empty-bin'
    empty.mkdir()
    proc = app.run(ANALYZE_CMD, PATH=empty, INVESTSH_DIR=None)
    assert proc.returncode == 0, proc.stderr
    assert (default / 'analise_prompt.txt').exists()


def test_unknown_command(app):
    proc = app.run(FINANCES_CMD, ['relatorio'])
    assert proc.returncode == 2
    assert 'invalid choice' in proc.stderr
