"""Ambiente determinístico para os testes, aplicado a TODO processo Python.

Os testes põem tests/site no PYTHONPATH, então o Python carrega este
sitecustomize ao iniciar qualquer processo, inclusive os que o investsh abre
em segundo plano. Antes do código do investsh rodar, ele:
- congela data/hora em INVESTSH_TEST_NOW (ISO 8601);
- substitui urllib.request.urlopen por respostas fixas de cotação
  (INVESTSH_TEST_RATES=ok | fail);
- opcionalmente grava as chamadas de desenho do matplotlib em
  INVESTSH_TEST_PLOTLOG (JSON), em vez de depender dos pixels do PNG;
- simula matplotlib ausente (INVESTSH_TEST_NO_MPL) ou ruído em stderr
  (INVESTSH_TEST_STDERR_NOISE); mede cobertura (INVESTSH_COVERAGE).

Fora dos testes (sem INVESTSH_TEST_NOW no ambiente) não faz nada.
"""
import os


def _install():
    import datetime as _dt
    import io
    import json
    import os
    import sys
    import urllib.request
    import importlib.util

    NOW = _dt.datetime.fromisoformat(os.environ.get('INVESTSH_TEST_NOW', '2026-10-06T12:00:00'))


    class FrozenDatetime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromisoformat(NOW.isoformat())

        @classmethod
        def today(cls):
            return cls.now()


    class FrozenDate(_dt.date):
        @classmethod
        def today(cls):
            return cls(NOW.year, NOW.month, NOW.day)


    _dt.datetime = FrozenDatetime
    _dt.date = FrozenDate

    FAKE_RESPONSES = {
        'economia.awesomeapi.com.br': {'USDBRL': {'bid': '5.4321'}},
        'api.coingecko.com': {
            'bitcoin': {'brl': 600000.0},
            'ethereum': {'brl': 20000.0},
            'dogecoin': {'brl': 1.1},
            'ripple': {'brl': 12.5},
        },
    }


    class _FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()


    def fake_urlopen(url, *args, **kwargs):
        url = getattr(url, 'full_url', url)
        if os.environ.get('INVESTSH_TEST_RATES', 'ok') == 'fail':
            raise urllib.error.URLError('rede desligada nos testes')
        for host, payload in FAKE_RESPONSES.items():
            if host in url:
                return _FakeResponse(json.dumps(payload).encode())
        raise AssertionError(f'URL inesperada nos testes: {url}')


    urllib.request.urlopen = fake_urlopen


    def _target_dir():
        """Diretório do pacote investsh testado, sem importá-lo."""
        spec = importlib.util.find_spec('investsh')
        return os.path.dirname(os.path.abspath(spec.origin))


    def _install_plot_logger(path):
        """Registra as chamadas de desenho relevantes (texto, barras, pizza, linhas)."""
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.axes
        import matplotlib.figure
        import matplotlib.pyplot as plt

        calls = []
        app_dir = _target_dir()

        def from_app():
            # Só registra chamadas feitas pelo código do investsh; as internas do
            # matplotlib (que um pie() ou plot() fazem) mudam entre versões.
            caller = os.path.abspath(sys._getframe(2).f_code.co_filename)
            return caller.startswith(app_dir + os.sep)

        def norm(v):
            if isinstance(v, float):
                return round(v, 4)
            if isinstance(v, (list, tuple)):
                return [norm(x) for x in v]
            if hasattr(v, 'tolist'):
                return norm(v.tolist())
            if isinstance(v, dict):
                return {k: norm(x) for k, x in sorted(v.items())}
            if isinstance(v, (str, int, bool)) or v is None:
                return v
            return repr(type(v).__name__)

        def wrap(cls, name):
            orig = getattr(cls, name)

            def logged(self, *args, **kwargs):
                if from_app():
                    calls.append({'call': f'{cls.__name__}.{name}', 'args': norm(list(args)),
                                  'kwargs': norm(kwargs)})
                return orig(self, *args, **kwargs)
            setattr(cls, name, logged)

        for name in ('text', 'plot', 'pie', 'barh', 'bar', 'fill_between', 'set_title',
                     'set_xlim', 'set_ylim', 'axhline', 'axvline', 'annotate', 'scatter',
                     'set_xticks', 'set_xticklabels', 'set_yticks', 'set_yticklabels', 'legend'):
            if hasattr(matplotlib.axes.Axes, name):
                wrap(matplotlib.axes.Axes, name)

        orig_figure = plt.figure

        def logged_figure(*args, **kwargs):
            if from_app():
                calls.append({'call': 'pyplot.figure', 'args': norm(list(args)), 'kwargs': norm(kwargs)})
            return orig_figure(*args, **kwargs)
        plt.figure = logged_figure

        orig_savefig = matplotlib.figure.Figure.savefig

        def logged_savefig(self, fname, *args, **kwargs):
            calls.append({'call': 'Figure.savefig', 'args': [os.path.basename(str(fname))],
                          'kwargs': norm(kwargs)})
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(calls, f, ensure_ascii=False, indent=1)
            return orig_savefig(self, fname, *args, **kwargs)
        matplotlib.figure.Figure.savefig = logged_savefig


    # Avisos de fonte do matplotlib dependem das fontes da máquina; vão para stderr e,
    # na TUI, aparecem desenhados na tela. Silenciados para os goldens serem portáveis.
    import logging
    logging.getLogger('matplotlib.font_manager').setLevel(logging.ERROR)

    if os.environ.get('INVESTSH_TEST_NO_MPL'):
        sys.modules['matplotlib'] = None  # simula matplotlib não instalado

    if os.environ.get('INVESTSH_TEST_STDERR_NOISE'):
        # Simula avisos que o matplotlib escreve em stderr durante a geração da imagem
        import warnings
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.figure
        _orig_savefig = matplotlib.figure.Figure.savefig

        def _noisy_savefig(self, *args, **kwargs):
            print('RUIDO-STDERR', file=sys.stderr)
            warnings.warn('RUIDO-WARNING')
            return _orig_savefig(self, *args, **kwargs)
        matplotlib.figure.Figure.savefig = _noisy_savefig

    if os.environ.get('INVESTSH_TEST_PLOTLOG'):
        _install_plot_logger(os.environ['INVESTSH_TEST_PLOTLOG'])

    if os.environ.get('INVESTSH_COVERAGE'):
        import atexit
        import coverage
        _cov = coverage.Coverage(data_file=os.environ['INVESTSH_COVERAGE'], data_suffix=True,
                                 source=[_target_dir()])
        _cov.start()
        atexit.register(lambda: (_cov.stop(), _cov.save()))


if os.environ.get('INVESTSH_TEST_NOW'):
    _install()
