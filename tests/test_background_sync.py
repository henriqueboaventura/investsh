"""Save na TUI não trava: imagem e commit/push rodam em segundo plano."""
import stat
import subprocess
import time

import pytest

from support import FINANCES_CMD, strip_ansi

SLOW_PUSH = 4  # segundos que o remoto de teste leva para aceitar um push


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def set_remote_hook(remote, body):
    hook = remote / 'hooks' / 'pre-receive'
    if body is None:
        hook.unlink(missing_ok=True)
        return
    hook.write_text(f'#!/bin/sh\n{body}\n')
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def repo(demo, tmp_path):
    remote = tmp_path / 'remote.git'
    git('init', '-q', '--bare', str(remote), cwd=tmp_path)
    for args in (('init', '-q', '-b', 'main'), ('config', 'user.email', 't@e.com'),
                 ('config', 'user.name', 'T'), ('add', 'data'), ('commit', '-q', '-m', 'seed'),
                 ('remote', 'add', 'origin', str(remote)), ('push', '-q', '-u', 'origin', 'main')):
        git(*args, cwd=demo.root)
    (demo.root / 'investsh.toml').write_text('[git]\nauto_commit = true\n', encoding='utf-8')
    demo.remote = remote
    demo.seed_sha = git('rev-parse', 'HEAD', cwd=demo.root)
    return demo


def remote_unchanged(app):
    return git('rev-parse', 'main', cwd=app.remote) == app.seed_sha


def pushed(app):
    return git('rev-parse', 'main', cwd=app.remote) == git('rev-parse', 'HEAD', cwd=app.root)


def commits(app):
    return int(git('rev-list', '--count', 'HEAD', cwd=app.root))


def edit_and_save(t, value, quit=False):
    t.press('d', 'enter', 'u').fill(value)
    start = time.time()
    if quit:
        t.press('q', 's', quiet=0.1)
    else:
        t.press('w', 's', until='✓ Salvo', quiet=0.1)
    return time.time() - start


def test_save_returns_before_slow_push(repo, tui_factory):
    set_remote_hook(repo.remote, f'sleep {SLOW_PUSH}')
    t = tui_factory()
    elapsed = edit_and_save(t, '1000')
    assert elapsed < SLOW_PUSH / 2, f'save esperou o push ({elapsed:.1f}s)'
    assert '↻ enviando…' in t.text()
    assert remote_unchanged(repo)   # push ainda em andamento

    t.wait_for('push ok', timeout=SLOW_PUSH + 15)   # a barra se atualiza sozinha
    assert pushed(repo)
    t.press('q')
    assert t.wait_exit() == 0


def test_quit_does_not_wait_for_push(repo, tui_factory):
    set_remote_hook(repo.remote, f'sleep {SLOW_PUSH}')
    t = tui_factory()
    start = time.time()
    edit_and_save(t, '1000', quit=True)
    assert t.wait_exit() == 0
    assert time.time() - start < SLOW_PUSH / 2, 'sair esperou o push'
    assert remote_unchanged(repo)   # push ainda em andamento

    state = repo.wait_sync(timeout=SLOW_PUSH + 15)   # continua após a TUI fechar
    assert state['ok'] and state['message'] == '↑ push ok'
    assert pushed(repo) and commits(repo) == 2


def test_consecutive_saves_are_queued(repo, tui_factory):
    set_remote_hook(repo.remote, 'sleep 1')
    t = tui_factory()
    edit_and_save(t, '1000')
    edit_and_save(t, '2000')
    t.wait_for('push ok', timeout=30)
    t.press('q')
    assert t.wait_exit() == 0
    repo.wait_sync()
    assert commits(repo) == 3 and pushed(repo)
    bal = [i for i in repo.read('investments.json')['investments'] if i['name'] == 'CDB Banco Alfa 110% CDI']
    assert bal[0]['balance'] == 2000.0
    assert '"balance": 2000.0' in git('show', 'HEAD:data/investments.json', cwd=repo.root)


def test_failed_push_is_reported_and_retried(repo, tui_factory):
    set_remote_hook(repo.remote, 'exit 1')
    t = tui_factory()
    edit_and_save(t, '1000')
    t.wait_for('push falhou', timeout=30)
    t.press('q')
    assert t.wait_exit() == 0
    assert commits(repo) == 2 and remote_unchanged(repo)

    # Ao abrir de novo: aviso de commit não enviado
    t2 = tui_factory()
    assert '⚠ 1 commit(s) não enviado(s) ao remoto — rode: investsh sync' in t2.text()
    t2.press('q')
    assert t2.wait_exit() == 0

    # investsh sync reenvia
    set_remote_hook(repo.remote, None)
    proc = repo.run(FINANCES_CMD, ['sync'])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == '↑ push ok'
    assert pushed(repo)

    t3 = tui_factory()
    assert 'não enviado' not in t3.text()
    t3.press('q')
    assert t3.wait_exit() == 0


def test_sync_command_failure_exit_code(repo):
    set_remote_hook(repo.remote, 'exit 1')
    proc = repo.run(FINANCES_CMD, ['sync'])
    assert proc.returncode == 1
    assert proc.stdout.strip() == '⚠ push falhou'


def test_sync_command_without_git(demo):
    proc = demo.run(FINANCES_CMD, ['sync'])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == '✓ imagem atualizada'
    assert (demo.root / 'assets' / 'status.png').read_bytes()[:4] == b'\x89PNG'


def test_sync_command_nothing_to_do(demo):
    proc = demo.run(FINANCES_CMD, ['sync'], INVESTSH_TEST_NO_MPL='1')
    assert proc.returncode == 0, proc.stderr
    assert 'nada a fazer' in proc.stdout


def test_image_generated_in_background_without_git(demo, tui_factory):
    t = tui_factory()
    edit_and_save(t, '1000')
    t.press('q')
    assert t.wait_exit() == 0
    demo.wait_sync()
    assert (demo.root / 'assets' / 'status.png').read_bytes()[:4] == b'\x89PNG'
    assert '↻' not in strip_ansi(t.text())   # sem git: nada de "enviando" na barra
