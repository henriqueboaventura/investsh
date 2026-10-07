"""Infraestrutura dos testes de regressão.

Os testes são de caracterização: registram o comportamento atual (saída no
terminal, telas da TUI, arquivos gravados, chamadas de desenho da imagem) em
arquivos "golden" e falham se qualquer coisa mudar.

Pontos de entrada ficam centralizados em FINANCES_CMD / ANALYZE_CMD / App.setup:
numa reestruturação do código, só eles devem precisar mudar.

Atualizar goldens após uma mudança INTENCIONAL:  UPDATE_GOLDEN=1 pytest
"""
import difflib
import errno
import fcntl
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

import pyte

REPO = Path(__file__).resolve().parent.parent
# Código sob teste (padrão: este repositório). Permite testar uma cópia modificada.
SRC = Path(os.environ.get('INVESTSH_TEST_SRC', REPO))
TESTS = REPO / 'tests'
GOLDEN = TESTS / 'golden'
FIXTURES = TESTS / 'fixtures'
SITE = TESTS / 'site'   # sitecustomize.py: ambiente determinístico em todo processo Python

# ── Pontos de entrada (únicos lugares a ajustar numa reestruturação) ─────────
PKG_SRC = SRC / 'src'                       # vai para o PYTHONPATH dos processos testados
EXAMPLES = PKG_SRC / 'investsh' / 'examples'
FINANCES_CMD = ['-m', 'investsh']
ANALYZE_CMD = ['-m', 'investsh', 'analyze']

FROZEN_NOW = '2026-10-06T12:00:00'


def load_finances(root=None):
    """Módulo com as funções da carteira (para testes unitários).

    `root`: diretório de trabalho (com data/) para as funções que leem o histórico.
    """
    import importlib
    import types
    if str(PKG_SRC) not in sys.path:
        sys.path.insert(0, str(PKG_SRC))
    config = importlib.import_module('investsh.config')
    if root is not None:
        config.configure(root)
    ns = {}
    for name in ('investsh.term', 'investsh.core'):
        ns.update(vars(importlib.import_module(name)))
    return types.SimpleNamespace(**ns)



def _utf8_locale():
    """Locale UTF-8 disponível (macOS: en_US.UTF-8; Linux: C.UTF-8). Sem ele o curses descarta acentos."""
    import locale
    saved = locale.setlocale(locale.LC_CTYPE)
    try:
        for name in ('C.UTF-8', 'C.utf8', 'en_US.UTF-8', 'en_US.utf8'):
            try:
                locale.setlocale(locale.LC_CTYPE, name)
                return name
            except locale.Error:
                continue
    finally:
        locale.setlocale(locale.LC_CTYPE, saved)
    raise RuntimeError('nenhum locale UTF-8 disponível para os testes')


UTF8_LOCALE = _utf8_locale()

# Cache de fontes do matplotlib compartilhado entre execuções (montá-lo leva segundos)
MPL_CACHE = Path(os.environ.get('INVESTSH_TEST_MPLCACHE', Path(tempfile.gettempdir()) / 'investsh-tests-mpl'))


def assert_golden(name, actual):
    """Compara `actual` com tests/golden/<name>. UPDATE_GOLDEN=1 regrava."""
    path = GOLDEN / name
    if os.environ.get('UPDATE_GOLDEN') == '1':
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding='utf-8')
        return
    assert path.exists(), f'golden ausente: {path} (rode com UPDATE_GOLDEN=1)'
    expected = path.read_text(encoding='utf-8')
    if actual != expected:
        diff = ''.join(difflib.unified_diff(
            expected.splitlines(True), actual.splitlines(True),
            fromfile=f'golden/{name}', tofile='atual', n=2))
        raise AssertionError(f'Saída diferente do golden {name}:\n{diff[:6000]}')


def dump_json(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + '\n'


class App:
    """Cópia isolada do projeto num diretório temporário."""

    def __init__(self, root: Path):
        self.root = root

    # ── preparação ──────────────────────────────────────────────────────────
    def setup(self):
        (self.root / 'data').mkdir()
        return self

    @property
    def data_dir(self):
        return self.root / 'data'

    def seed(self, dataset='examples', history=True):
        """Copia um conjunto de dados para data/ (examples ou tests/fixtures/<nome>)."""
        src = EXAMPLES if dataset == 'examples' else FIXTURES / dataset
        shutil.copy(src / 'investments.json', self.data_dir / 'investments.json')
        if history and (src / 'history.json').exists():
            shutil.copy(src / 'history.json', self.data_dir / 'history.json')
        return self

    def read(self, name):
        return json.loads((self.data_dir / name).read_text(encoding='utf-8'))

    def write(self, name, obj):
        (self.data_dir / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2),
                                          encoding='utf-8')

    def edit(self, fn, name='investments.json'):
        d = self.read(name)
        fn(d)
        self.write(name, d)

    def sync_paths(self):
        """Lock e arquivo de estado do trabalho em segundo plano desta pasta."""
        from investsh import sync
        return sync.state_paths(self.root)

    def wait_sync(self, timeout=60):
        """Espera o commit/push/imagem em segundo plano (se houver) terminar."""
        _, path = self.sync_paths()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                state = json.loads(Path(path).read_text(encoding='utf-8'))
            except (FileNotFoundError, ValueError):
                return None
            if state.get('state') == 'done':
                return state
            time.sleep(0.1)
        raise AssertionError(f'segundo plano não terminou em {timeout}s: {state}')

    def data_snapshot(self):
        """Estado de data/ e assets/ para golden: JSONs completos + existência do PNG."""
        self.wait_sync()
        out = []
        for name in ('investments.json', 'history.json'):
            p = self.data_dir / name
            out.append(f'### data/{name}\n')
            out.append(dump_json(json.loads(p.read_text(encoding='utf-8'))) if p.exists() else '(ausente)\n')
        png = self.root / 'assets' / 'status.png'
        is_png = png.exists() and png.read_bytes()[:4] == b'\x89PNG'
        out.append(f'### assets/status.png: {"PNG" if is_png else "ausente"}\n')
        return ''.join(out)

    # ── execução ────────────────────────────────────────────────────────────
    @property
    def home(self):
        """HOME falso dos processos testados: o ~/.investsh real nunca é tocado."""
        return self.root.parent / 'home'

    def env(self, **extra):
        """Ambiente dos processos testados. Valor None em `extra` remove a variável."""
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('FINANCES_', 'INVESTSH_')) or k == 'INVESTSH_COVERAGE'}
        self.home.mkdir(exist_ok=True)
        env.update({
            'HOME': str(self.home),
            'INVESTSH_DIR': str(self.root),   # pasta de dados do teste (padrão seria ~/.investsh)
            'INVESTSH_TEST_NOW': FROZEN_NOW,
            'INVESTSH_TEST_RATES': 'ok',
            'PYTHONPATH': os.pathsep.join([str(SITE), str(PKG_SRC)]),
            'PYTHONIOENCODING': 'utf-8',
            'PYTHONDONTWRITEBYTECODE': '1',
            # do_remove itera um set: sem semente fixa a ordem das mensagens varia
            'PYTHONHASHSEED': '0',
            'MPLBACKEND': 'Agg',
            'MPLCONFIGDIR': str(MPL_CACHE),
            'LC_ALL': UTF8_LOCALE,
            'LANG': UTF8_LOCALE,
        })
        for k, v in extra.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = str(v)
        return env

    def normalize(self, text):
        # mais longo primeiro: /private/tmp/... (macOS) contém /tmp/...
        for p in sorted({str(self.root), os.path.realpath(self.root)}, key=len, reverse=True):
            text = text.replace(p, '<APP>')
        return text

    def run(self, cmd, args=(), stdin='', **env):
        proc = subprocess.run(
            [sys.executable, *cmd, *args],
            input=stdin, capture_output=True, text=True, cwd=self.root,
            env=self.env(**env), timeout=60,
        )
        return proc

    def menu(self, stdin, **env):
        """Executa `finances --menu` com as respostas dadas (uma por linha)."""
        if isinstance(stdin, (list, tuple)):
            stdin = '\n'.join(stdin) + '\n'
        proc = self.run(FINANCES_CMD, ['--menu'], stdin=stdin, **env)
        return proc

    def tui(self, cols=140, rows=45, **env):
        return TUI(self, cols, rows, env)


# ── TUI via pseudo-terminal + emulador de terminal ──────────────────────────
KEY = {
    # Setas no modo "application cursor" (SS3), que o curses ativa com keypad(True)
    'enter': '\r', 'esc': '\x1b', 'bs': '\x7f', 'up': '\x1bOA', 'down': '\x1bOB',
    'right': '\x1bOC', 'left': '\x1bOD', 'home': '\x1bOH', 'end': '\x1bOF',
    'pgdn': '\x1b[6~', 'pgup': '\x1b[5~',
}


class Screen(pyte.Screen):
    """pyte.Screen com o que falta no pyte 0.8 para emular fielmente o curses.

    O curses rola regiões da tela com CSI S/T (SU/SD), que o pyte ignora: sem
    isso a tela emulada fica com linhas sobrepostas que um terminal real não mostra.
    Qualquer outro comando não suportado é registrado em `unsupported` e faz o
    teste falhar, em vez de gravar uma tela errada no golden.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unsupported = []

    def _margins(self):
        m = self.margins
        return (m.top, m.bottom) if m else (0, self.lines - 1)

    def scroll_up(self, count=None, *args, **kwargs):
        top, bottom = self._margins()
        for _ in range(count or 1):
            for y in range(top, bottom):
                self.buffer[y] = self.buffer[y + 1]
            self.buffer.pop(bottom, None)
        self.dirty.update(range(self.lines))

    def scroll_down(self, count=None, *args, **kwargs):
        top, bottom = self._margins()
        for _ in range(count or 1):
            for y in range(bottom, top, -1):
                self.buffer[y] = self.buffer[y - 1]
            self.buffer.pop(top, None)
        self.dirty.update(range(self.lines))

    def debug(self, *args, **kwargs):
        # O parser do pyte chama debug() sem dizer o comando: pega do frame dele
        import sys
        f = sys._getframe(1).f_locals
        if f.get('char') in ('=', '>'):
            return  # ESC = / ESC >: modo do teclado numérico, não afeta a tela
        if f.get('char') == 't':
            return  # CSI 22/23 t (XTWINOPS): guarda/restaura o título da janela
        self.unsupported.append({k: f.get(k) for k in ('char', 'code', 'params', 'private') if k in f})


class Stream(pyte.ByteStream):
    csi = {**pyte.ByteStream.csi, 'S': 'scroll_up', 'T': 'scroll_down'}


class TUI:
    def __init__(self, app, cols, rows, env):
        self.app = app
        self.screen = Screen(cols, rows)
        self.stream = Stream(self.screen)
        self.frames = []
        term = os.environ.get('INVESTSH_TEST_TERM', 'xterm-256color')
        full_env = app.env(TERM=term, ESCDELAY='25', LINES=rows, COLUMNS=cols, **env)
        pid, fd = pty.fork()
        if pid == 0:  # filho
            os.chdir(app.root)
            os.execve(sys.executable, [sys.executable, *FINANCES_CMD], full_env)
        self.pid, self.fd = pid, fd
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
        self.exit_status = None
        self.raw = b''
        self.wait_ready()

    # Textos que indicam que o investsh já está esperando teclas: a barra de abas
    # da TUI, ou a pergunta de primeira execução (antes do curses assumir o terminal).
    READY = ('Sumário   Alocação', 'Escolha [1]:')

    def wait_ready(self, timeout=60):
        """Espera a tela inicial. Teclas enviadas antes disso passam pelo modo de
        linha do terminal (antes do curses) e se perdem; sob carga, o início demora."""
        start = time.time()
        while not any(r in self.text() for r in self.READY):
            if self.exit_status is not None or time.time() - start > timeout:
                raise AssertionError(f'investsh não ficou pronto:\n{self.text()}')
            self._read(0.05)
        self.settle()

    def _read(self, timeout):
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return False
        try:
            data = os.read(self.fd, 65536)
        except OSError as e:
            if e.errno == errno.EIO:  # processo terminou
                self._reap()
                return None
            raise
        if not data:
            self._reap()
            return None
        self.raw += data
        self.stream.feed(data)
        return True

    def _reap(self):
        if self.exit_status is None:
            _, status = os.waitpid(self.pid, 0)
            self.exit_status = os.waitstatus_to_exitcode(status)

    def settle(self, quiet=0.35, min_wait=0.05, max_wait=15.0):
        """Lê a saída até a tela ficar estável por `quiet` segundos."""
        start = time.time()
        last = time.time()
        while time.time() - start < max_wait:
            got = self._read(0.05)
            if got is None:
                return
            if got:
                last = time.time()
            elif time.time() - last >= quiet and time.time() - start >= min_wait:
                return

    def _drain(self):
        while self._read(0) is True:
            pass

    def press(self, *keys, quiet=0.3, until=None, timeout=20.0):
        """Envia teclas e espera a tela estabilizar (ou o texto `until` aparecer)."""
        for k in keys:
            seq = KEY.get(k, k)
            if self.exit_status is not None:
                raise AssertionError(f'TUI já terminou (status {self.exit_status}) ao enviar {k!r}')
            os.write(self.fd, seq.encode())
            if seq == '\x1b':
                # Esc isolado: espera a TUI processar, senão o curses junta com a próxima tecla
                self.settle(quiet=0.15, min_wait=0.1)
            else:
                time.sleep(0.01)
                self._drain()
        if until is not None:
            self.wait_for(until, timeout)
        self.settle(quiet=quiet)
        return self

    def wait_for(self, text, timeout=20.0):
        start = time.time()
        while text not in self.text():
            if time.time() - start > timeout:
                raise AssertionError(f'texto {text!r} não apareceu na tela:\n{self.text()}')
            if self._read(0.05) is None:
                break
        return self

    def type(self, text):
        return self.press(*list(text))

    def clear_field(self, n=20):
        return self.press(*(['bs'] * n))

    def fill(self, text):
        """Apaga o valor pré-preenchido do campo, digita `text` e confirma."""
        return self.clear_field().type(text).press('enter')

    def text(self):
        return '\n'.join(line.rstrip() for line in self.screen.display).rstrip() + '\n'

    # Cor de frente → letra; negrito → maiúscula; vídeo reverso/fundo → '=' ou '#'
    FG = {'default': '.', 'green': 'g', 'red': 'r', 'cyan': 'c', 'magenta': 'm',
          'yellow': 'y', 'black': 'k', 'white': 'w', 'blue': 'b',
          'brightgreen': 'g', 'brightred': 'r', 'brightcyan': 'c', 'brightmagenta': 'm',
          'brightyellow': 'y', 'brightwhite': 'w', 'brightblack': 'k', 'brightblue': 'b'}

    def styles(self):
        """Mapa de estilos, alinhado com text(): torna visíveis cores, seleção e barras."""
        lines = []
        for y in range(self.screen.lines):
            row = self.screen.buffer[y]
            out = []
            for x in range(self.screen.columns):
                ch = row[x]
                if ch.reverse or ch.bg != 'default':
                    out.append('#' if ch.bold else '=')
                elif ch.data == ' ':
                    out.append(' ')
                else:
                    c = self.FG.get(ch.fg, '?')
                    out.append(c.upper() if ch.bold and c != '.' else ('*' if ch.bold else c))
            lines.append(''.join(out).rstrip())
        return '\n'.join(lines).rstrip() + '\n'

    def snap(self, label, styles=True):
        frame = f'=== {label} ===\n{self.app.normalize(self.text())}'
        if styles:
            frame += f'--- estilos ---\n{self.styles()}'
        self.frames.append(frame)
        return self

    def golden(self):
        assert not self.screen.unsupported, f'sequências não emuladas: {self.screen.unsupported[:5]}'
        return ''.join(self.frames)

    def wait_exit(self, timeout=20):
        start = time.time()
        while self.exit_status is None and time.time() - start < timeout:
            if self._read(0.1) is None:
                break
        if self.exit_status is None:
            os.kill(self.pid, signal.SIGKILL)
            self._reap()
            raise AssertionError('TUI não terminou')
        return self.exit_status

    def close(self):
        if self.exit_status is None:
            try:
                os.kill(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self._reap()
        try:
            os.close(self.fd)
        except OSError:
            pass


ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def strip_ansi(s):
    return ANSI_RE.sub('', s)
