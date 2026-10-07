"""Diretório de trabalho e opções de ambiente."""
import os


# Diretório de trabalho: contém data/ (seus dados) e assets/ (imagem de resumo).
# Padrão: diretório atual; o comando `investsh --dir` muda via configure().
ROOT = os.getcwd()


DATA = os.path.join(ROOT, 'data', 'investments.json')


EXAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'examples', 'investments.json')


def configure(base_dir):
    global ROOT, DATA
    ROOT = os.path.abspath(base_dir)
    DATA = os.path.join(ROOT, 'data', 'investments.json')


# Commit + push automático em data/ a cada save. Desligado por padrão para não
# publicar dados financeiros por acidente. Ative com FINANCES_AUTO_GIT=1.
AUTO_GIT = os.environ.get('FINANCES_AUTO_GIT', '').lower() in ('1', 'true', 'yes')
