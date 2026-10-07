"""Linha de comando: `investsh`, `investsh --menu`, `investsh analyze`."""
import argparse
import os
import sys

from . import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='investsh',
        description='Controle de investimentos no terminal. Os dados ficam em DIR/data/.',
    )
    parser.add_argument('command', nargs='?', choices=['analyze', 'sync'],
                        help='analyze: gera um prompt de análise da carteira para IA; '
                             'sync: gera a imagem e faz commit/push agora (ver investsh.toml)')
    parser.add_argument('--job', help=argparse.SUPPRESS)  # uso interno: sync em segundo plano
    parser.add_argument('--menu', action='store_true',
                        help='menu de texto numerado em vez da tela interativa')
    parser.add_argument('--dir', default=os.environ.get('INVESTSH_DIR', '.'),
                        help='diretório com data/ e assets/ (padrão: atual, ou $INVESTSH_DIR)')
    parser.add_argument('--version', action='version', version=f'investsh {__version__}')
    args = parser.parse_args(argv)

    if args.command == 'analyze':
        from . import analyze
        analyze.main(os.path.abspath(args.dir))
        return

    from . import config
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
        app.run(menu=args.menu)
