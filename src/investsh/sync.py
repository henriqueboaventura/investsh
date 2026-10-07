"""Imagem de resumo + commit/push, em primeiro plano (`investsh sync`) ou em segundo plano.

Na TUI, salvar só grava os JSON; o resto (gerar a imagem, que carrega o matplotlib,
e o commit/push, que depende da rede) roda num processo separado. Assim a tela não
trava e sair do investsh é imediato: o processo continua mesmo após a TUI fechar.

Saves seguidos entram em fila (um lock por pasta de dados). O andamento fica num
arquivo de estado no diretório temporário, que a TUI consulta para mostrar o resultado.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime

from . import config


def state_paths(root=None):
    """(lock, estado) desta pasta de dados, no diretório temporário."""
    key = hashlib.sha1(os.path.realpath(root or config.ROOT).encode()).hexdigest()[:12]
    base = os.path.join(tempfile.gettempdir(), f'investsh-{key}')
    return base + '.lock', base + '.json'


def needed():
    """Há trabalho para o segundo plano? (imagem, se houver matplotlib, e/ou git)"""
    return config.AUTO_GIT or importlib.util.find_spec('matplotlib') is not None


def run():
    """Gera a imagem e, se configurado, faz commit (e push). Retorna (ok, mensagem)."""
    from .image import generate_status_image
    with open(config.DATA, encoding='utf-8') as f:
        data = json.load(f)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            generate_status_image(data)
        except Exception:
            pass

    if not config.AUTO_GIT:
        return True, ''
    month = datetime.now().strftime('%Y-%m')
    git = ['git', '-C', config.ROOT]
    try:
        subprocess.run(git + ['add', 'data/investments.json', 'data/history.json', 'assets/'],
                       check=True, capture_output=True)
        subprocess.run(git + ['commit', '-m', f'update {month}'], capture_output=True)
        if not config.GIT_PUSH:
            return True, '✓ commit (sem push)'
        # Push mesmo sem commit novo: envia commits pendentes de saves anteriores
        push = subprocess.run(git + ['push'], capture_output=True, text=True)
        return (True, '↑ push ok') if push.returncode == 0 else (False, '⚠ push falhou')
    except Exception:
        return False, '⚠ git falhou'


def _write_state(state):
    _, path = state_paths()
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f)
    os.replace(tmp, path)


def read_state():
    try:
        with open(state_paths()[1], encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def start():
    """Dispara o trabalho em segundo plano e retorna na hora o id do job."""
    job = str(time.time_ns())
    _write_state({'job': job, 'state': 'queued'})
    subprocess.Popen(
        [sys.executable, '-m', 'investsh', 'sync', '--dir', config.ROOT, '--job', job],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,  # sobrevive ao fechar a TUI ou o terminal
    )
    return job


def background(job):
    """Corpo do processo de segundo plano: espera a vez (lock) e registra o resultado."""
    import fcntl
    lock_path, _ = state_paths()
    with open(lock_path, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            ok, message = run()
        except Exception as e:
            ok, message = False, f'⚠ erro: {e.__class__.__name__}'
        # Se outro save entrou na fila enquanto este rodava, o estado é dele
        state = read_state()
        if state is None or state.get('job') == job:
            _write_state({'job': job, 'state': 'done', 'ok': ok, 'message': message})


def foreground():
    """`investsh sync`: faz o mesmo trabalho agora, mostrando o resultado."""
    import fcntl
    lock_path, _ = state_paths()
    with open(lock_path, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ok, message = run()
    if not config.AUTO_GIT:
        message = '✓ imagem atualizada' if importlib.util.find_spec('matplotlib') else \
            'nada a fazer: sem matplotlib e sem commit automático (investsh.toml)'
    print(message)
    return 0 if ok else 1


def busy():
    """Algum processo de segundo plano está rodando nesta pasta agora?"""
    import fcntl
    lock_path, _ = state_paths()
    try:
        with open(lock_path, 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
    except BlockingIOError:
        return True


def unpushed():
    """Quantos commits locais ainda não foram para o remoto (None se não se aplica)."""
    if not (config.AUTO_GIT and config.GIT_PUSH):
        return None
    r = subprocess.run(['git', '-C', config.ROOT, 'rev-list', '--count', '@{upstream}..HEAD'],
                       capture_output=True, text=True)
    return int(r.stdout) if r.returncode == 0 and r.stdout.strip().isdigit() else None
