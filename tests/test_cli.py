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


def test_dir_option(app):
    d = other_dir(app)
    proc = app.run(FINANCES_CMD, ['--menu', '--dir', str(d)], stdin='0\ns\n')
    out = strip_ansi(proc.stdout)
    assert proc.returncode == 0, proc.stderr
    assert f'Arquivo: {d}/data/investments.json' in out
    assert (d / 'data' / 'history.json').exists()
    assert not (app.data_dir / 'investments.json').exists()


def test_dir_from_environment(app):
    d = other_dir(app)
    proc = app.run(FINANCES_CMD, ['--menu'], stdin='0\ns\n', INVESTSH_DIR=d)
    assert proc.returncode == 0, proc.stderr
    assert (d / 'data' / 'history.json').exists()


def test_dir_option_wins_over_environment(app):
    d = other_dir(app)
    proc = app.run(FINANCES_CMD, ['--menu', '--dir', str(d)], stdin='0\ns\n',
                   INVESTSH_DIR=app.root / 'nao-existe')
    assert proc.returncode == 0, proc.stderr
    assert (d / 'data' / 'history.json').exists()


def test_analyze_dir_option(app, tmp_path):
    d = other_dir(app)
    empty = tmp_path / 'empty-bin'
    empty.mkdir()
    proc = app.run(ANALYZE_CMD, ['--dir', str(d)], PATH=empty)
    assert proc.returncode == 0, proc.stderr
    assert (d / 'analise_prompt.txt').exists()


def test_default_dir_is_home_investsh(app):
    proc = app.run(FINANCES_CMD, ['--menu'], stdin='1\nx\n', INVESTSH_DIR=None)
    out = strip_ansi(proc.stdout)
    assert proc.returncode == 0, proc.stderr
    default = app.home / '.investsh'
    assert f'Não encontrei {default}/data/investments.json.' in out
    assert (default / 'data' / 'investments.json').exists()
    assert not (app.data_dir / 'investments.json').exists()


def test_current_dir_not_used_by_default(demo):
    # Rodar dentro de uma pasta com dados não usa essa pasta: o padrão é ~/.investsh
    proc = demo.run(FINANCES_CMD, ['--menu'], stdin='x\n', INVESTSH_DIR=None)
    assert proc.returncode == 0, proc.stderr
    assert 'Bem-vindo ao investsh!' in strip_ansi(proc.stdout)
    assert not (demo.home / '.investsh').exists()


def test_dir_dot_uses_current_dir(demo):
    proc = demo.run(FINANCES_CMD, ['--menu', '--dir', '.'], stdin='x\n', INVESTSH_DIR=None)
    out = strip_ansi(proc.stdout)
    assert proc.returncode == 0, proc.stderr
    assert 'Bem-vindo' not in out
    assert 'Total atual:        R$   205,576.35' in out


def test_tilde_expansion(app):
    for args, env in ((['--dir', '~/carteira-a'], {}), ([], {'INVESTSH_DIR': '~/carteira-b'})):
        proc = app.run(FINANCES_CMD, ['--menu', *args], stdin='1\nx\n', **env)
        assert proc.returncode == 0, proc.stderr
    assert (app.home / 'carteira-a' / 'data' / 'investments.json').exists()
    assert (app.home / 'carteira-b' / 'data' / 'investments.json').exists()


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
