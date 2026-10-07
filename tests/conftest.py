import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from support import MPL_CACHE, PKG_SRC, App

# Testes unitários importam o pacote testado (não um investsh instalado)
sys.path.insert(0, str(PKG_SRC))


# ── Testes lentos ────────────────────────────────────────────────────────────
# Todo teste que dirige a tela interativa (fixture tui_factory) é "slow": cada
# tecla espera a tela assentar. `pytest` roda só os rápidos; `pytest --all`, tudo.

def pytest_addoption(parser):
    parser.addoption('--all', action='store_true',
                     help='inclui os testes lentos (tela interativa); o CI usa esta opção')


def pytest_configure(config):
    config.addinivalue_line('markers', 'slow: teste lento (tela interativa); rode com --all')
    # Com xdist, monta o cache de fontes do matplotlib uma vez antes dos workers,
    # em vez de vários processos montarem o mesmo cache ao mesmo tempo.
    if not hasattr(config, 'workerinput'):
        MPL_CACHE.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, '-c', 'import matplotlib.font_manager'],
                       env={**os.environ, 'MPLCONFIGDIR': str(MPL_CACHE), 'MPLBACKEND': 'Agg'},
                       capture_output=True)


def pytest_collection_modifyitems(config, items):
    for item in items:
        if 'tui_factory' in getattr(item, 'fixturenames', ()):
            item.add_marker(pytest.mark.slow)
    if config.getoption('--all'):
        return
    skip = pytest.mark.skip(reason='lento: rode com --all')
    for item in items:
        if 'slow' in item.keywords:
            item.add_marker(skip)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def app():
    """Projeto isolado em diretório temporário, ainda sem dados.

    Caminho curto e de tamanho fixo (/tmp/ish-XXXXXXXX/app): o programa imprime
    caminhos absolutos e, na TUI, o tamanho deles muda a quebra de linha.
    """
    base = Path(tempfile.mkdtemp(prefix='ish-', dir='/tmp'))
    root = base / 'app'
    root.mkdir()
    app = App(root).setup()
    yield app
    app.wait_sync()
    for path in app.sync_paths():
        Path(path).unlink(missing_ok=True)
    shutil.rmtree(base, ignore_errors=True)


@pytest.fixture
def demo(app):
    """Projeto isolado com a carteira de exemplo e histórico."""
    return app.seed('examples')


@pytest.fixture
def tui_factory(app):
    opened = []

    def make(**kwargs):
        t = app.tui(**kwargs)
        opened.append(t)
        return t
    yield make
    for t in opened:
        t.close()
