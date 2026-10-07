import shutil
import tempfile
from pathlib import Path

import pytest

import sys

from support import PKG_SRC, App

# Testes unitários importam o pacote testado (não um investsh instalado)
sys.path.insert(0, str(PKG_SRC))


@pytest.fixture
def app():
    """Projeto isolado em diretório temporário, ainda sem dados.

    Caminho curto e de tamanho fixo (/tmp/ish-XXXXXXXX/app): o programa imprime
    caminhos absolutos e, na TUI, o tamanho deles muda a quebra de linha.
    """
    base = Path(tempfile.mkdtemp(prefix='ish-', dir='/tmp'))
    root = base / 'app'
    root.mkdir()
    yield App(root).setup()
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
