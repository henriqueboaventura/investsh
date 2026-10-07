"""Linha de comando: escolha do diretório de dados e subcomandos."""
import os
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


def test_unknown_command(app):
    proc = app.run(FINANCES_CMD, ['relatorio'])
    assert proc.returncode == 2
    assert 'invalid choice' in proc.stderr
