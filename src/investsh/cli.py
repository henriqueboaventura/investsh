"""Linha de comando: `investsh`, `investsh analyze`, `investsh check`, `investsh sync`."""
import argparse
import os
import sys

from . import __version__


def main(argv=None):
    from . import config
    parser = argparse.ArgumentParser(
        prog='investsh',
        description='Controle de investimentos no terminal. '
                    f'Pasta de dados: {config.default_dir()} (mude com --dir ou $INVESTSH_DIR).',
    )
    parser.add_argument('command', nargs='?', choices=['analyze', 'check', 'sync'],
                        help='analyze: gera um prompt de análise da carteira para IA; '
                             'check: procura inconsistências nos dados; '
                             'sync: gera a imagem e faz commit/push agora (ver investsh.toml)')
    parser.add_argument('--job', help=argparse.SUPPRESS)  # uso interno: sync em segundo plano
    parser.add_argument('--menu', action='store_true', help=argparse.SUPPRESS)   # removido na 1.0.0
    parser.add_argument('--dir', default=None,
                        help='pasta de dados (padrão: $INVESTSH_DIR, senão ~/.investsh); '
                             'use --dir . para a pasta atual')
    parser.add_argument('--version', action='version', version=f'investsh {__version__}')
    args = parser.parse_args(argv)
    if args.menu:
        parser.exit(2, 'investsh: o --menu (modo texto) foi removido na versão 1.0.0; '
                       'use a tela interativa: investsh\n')
    if args.dir is None:
        args.dir = config.default_dir()

    if args.command == 'analyze':
        from . import analyze
        analyze.main(os.path.abspath(os.path.expanduser(args.dir)))
        return

    if args.command == 'check':
        from . import check
        sys.exit(check.main(os.path.abspath(os.path.expanduser(args.dir))))

    try:
        config.configure(args.dir)
    except config.ConfigError as e:
        parser.exit(2, f'investsh: {e}\n')

    if args.command == 'sync':
        from . import sync
        if args.job:
            sync.background(args.job)
        else:
            sys.exit(sync.foreground())
    else:
        from . import app
        app.run()
