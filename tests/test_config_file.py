"""Configuração por pasta de dados: investsh.toml."""
import subprocess

import pytest

from support import FINANCES_CMD, strip_ansi


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(demo, tmp_path):
    """Pasta de dados dentro de um repositório git com remoto."""
    remote = tmp_path / 'remote.git'
    git('init', '-q', '--bare', str(remote), cwd=tmp_path)
    git('init', '-q', '-b', 'main', cwd=demo.root)
    git('config', 'user.email', 't@e.com', cwd=demo.root)
    git('config', 'user.name', 'T', cwd=demo.root)
    git('add', 'data', cwd=demo.root)
    git('commit', '-q', '-m', 'seed', cwd=demo.root)
    git('remote', 'add', 'origin', str(remote), cwd=demo.root)
    git('push', '-q', '-u', 'origin', 'main', cwd=demo.root)
    demo.remote = remote
    return demo


def write_config(app, text):
    (app.root / 'investsh.toml').write_text(text, encoding='utf-8')


def save(app, **env):
    """Altera um saldo e salva pelo --menu."""
    return app.menu(['2', 'bova', '9900', '0', 's'], **env)


def commits(app):
    return int(git('rev-list', '--count', 'HEAD', cwd=app.root))


def remote_head(app):
    return git('rev-parse', 'main', cwd=app.remote).strip()


def test_auto_commit_and_push_from_file(repo):
    write_config(repo, '[git]\nauto_commit = true\npush = true\n')
    proc = save(repo)
    out = strip_ansi(proc.stdout)
    assert proc.returncode == 0, proc.stderr
    assert '✓ Commit criado: update 2026-10' in out
    assert '✓ Push concluído' in out
    assert commits(repo) == 2
    assert remote_head(repo) == git('rev-parse', 'HEAD', cwd=repo.root).strip()


def test_push_defaults_to_true(repo):
    write_config(repo, '[git]\nauto_commit = true\n')
    save(repo)
    assert commits(repo) == 2
    assert remote_head(repo) == git('rev-parse', 'HEAD', cwd=repo.root).strip()


def test_commit_without_push(repo):
    before = remote_head(repo)
    write_config(repo, '# só local\n[git]\nauto_commit = true\npush = false\n')
    proc = save(repo)
    out = strip_ansi(proc.stdout)
    assert proc.returncode == 0, proc.stderr
    assert '✓ Commit criado: update 2026-10' in out
    assert 'Push concluído' not in out
    assert commits(repo) == 2
    assert remote_head(repo) == before


def test_disabled_in_file(repo):
    write_config(repo, '[git]\nauto_commit = false\n')
    save(repo)
    assert commits(repo) == 1


def test_no_file_means_off(repo):
    save(repo)
    assert commits(repo) == 1


def test_environment_overrides_file(repo):
    write_config(repo, '[git]\nauto_commit = true\n')
    save(repo, FINANCES_AUTO_GIT='0')
    assert commits(repo) == 1


def test_environment_enables_without_file(repo):
    save(repo, FINANCES_AUTO_GIT='1')
    assert commits(repo) == 2


def sub_data_dir(repo):
    other = repo.root / 'sub'
    (other / 'data').mkdir(parents=True)
    (other / 'data' / 'investments.json').write_bytes((repo.data_dir / 'investments.json').read_bytes())
    return other


def test_file_read_from_dir_option(repo):
    other = sub_data_dir(repo)
    (other / 'investsh.toml').write_text('[git]\nauto_commit = true\npush = false\n', encoding='utf-8')
    proc = repo.run(FINANCES_CMD, ['--menu', '--dir', str(other)], stdin='0\ns\n')
    assert proc.returncode == 0, proc.stderr
    assert '✓ Commit criado: update 2026-10' in strip_ansi(proc.stdout)
    assert commits(repo) == 2


def test_file_in_current_dir_ignored_with_dir_option(repo):
    # Um investsh.toml em outra pasta não afeta a pasta de dados escolhida
    other = sub_data_dir(repo)
    write_config(repo, '[git]\nauto_commit = true\n')
    proc = repo.run(FINANCES_CMD, ['--menu', '--dir', str(other)], stdin='0\ns\n')
    assert proc.returncode == 0, proc.stderr
    assert commits(repo) == 1


@pytest.mark.parametrize('text, message', [
    ('[git\nauto_commit = true\n', 'investsh.toml inválido'),
    ('[git]\nauto_commit = "sim"\n', 'git.auto_commit deve ser true ou false'),
    ('[git]\npush = 1\n', 'git.push deve ser true ou false'),
])
def test_invalid_config_stops_before_touching_data(demo, text, message):
    write_config(demo, text)
    before = demo.data_snapshot()
    proc = demo.menu(['0', 's'])
    assert proc.returncode == 2
    assert message in proc.stderr
    assert 'Traceback' not in proc.stderr
    assert demo.data_snapshot() == before


def test_unknown_keys_warn(demo):
    write_config(demo, '[git]\nauto_commit = false\nautocommit = true\n\n[outra]\nx = 1\n')
    proc = demo.menu(['x'])
    assert proc.returncode == 0
    assert 'investsh.toml: chave desconhecida ignorada: git.autocommit' in proc.stderr
    assert 'investsh.toml: chave desconhecida ignorada: outra' in proc.stderr


def test_tui_commit_without_push_status(repo, tui_factory):
    before = remote_head(repo)
    write_config(repo, '[git]\nauto_commit = true\npush = false\n')
    t = tui_factory()
    t.press('d', 'enter', 'u').fill('1').press('w', 's', until='✓ commit (sem push)')
    assert '✓ commit (sem push)' in t.text()
    t.press('q')
    assert t.wait_exit() == 0
    assert commits(repo) == 2
    assert remote_head(repo) == before
