"""Diretório de trabalho e configuração (investsh.toml e variáveis de ambiente)."""
import os
import sys

try:
    import tomllib
except ImportError:  # Python < 3.11
    import tomli as tomllib


# Pasta de dados: contém data/ (seus dados), assets/ (imagem de resumo) e,
# opcionalmente, investsh.toml. Escolhida por default_dir() / `investsh --dir`.
DEFAULT_DIR = os.path.join('~', '.investsh')


def default_dir():
    """Pasta de dados quando --dir não é passado: $INVESTSH_DIR, senão ~/.investsh."""
    return os.path.expanduser(os.environ.get('INVESTSH_DIR') or DEFAULT_DIR)


ROOT = default_dir()

DATA = os.path.join(ROOT, 'data', 'investments.json')

EXAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'examples', 'investments.json')

CONFIG_FILE = 'investsh.toml'

# Commit automático de data/ a cada save, e push em seguida. Desligado por padrão
# para não publicar dados financeiros por acidente. Liga por pasta de dados em
# investsh.toml ([git] auto_commit = true); FINANCES_AUTO_GIT=1/0 sobrepõe.
AUTO_GIT = False
GIT_PUSH = True

# Chaves aceitas em investsh.toml: seção → {chave: tipo}
SCHEMA = {'git': {'auto_commit': bool, 'push': bool}}


class ConfigError(Exception):
    pass


def configure(base_dir):
    """Define o diretório de trabalho e carrega a configuração dele."""
    global ROOT, DATA, AUTO_GIT, GIT_PUSH
    ROOT = os.path.abspath(os.path.expanduser(base_dir))
    DATA = os.path.join(ROOT, 'data', 'investments.json')
    git = load_file(os.path.join(ROOT, CONFIG_FILE)).get('git', {})
    AUTO_GIT = git.get('auto_commit', False)
    GIT_PUSH = git.get('push', True)
    env = os.environ.get('FINANCES_AUTO_GIT', '').strip().lower()
    if env in ('1', 'true', 'yes'):
        AUTO_GIT = True
    elif env in ('0', 'false', 'no'):
        AUTO_GIT = False


def load_file(path):
    """Lê e valida investsh.toml. Arquivo ausente = configuração vazia."""
    try:
        with open(path, 'rb') as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f'{CONFIG_FILE} inválido: {e}') from None
    out = {}
    for section, values in raw.items():
        if section not in SCHEMA or not isinstance(values, dict):
            print(f'{CONFIG_FILE}: chave desconhecida ignorada: {section}', file=sys.stderr)
            continue
        out[section] = {}
        for key, value in values.items():
            kind = SCHEMA[section].get(key)
            if kind is None:
                print(f'{CONFIG_FILE}: chave desconhecida ignorada: {section}.{key}', file=sys.stderr)
            elif not isinstance(value, kind):
                raise ConfigError(f'{CONFIG_FILE}: {section}.{key} deve ser true ou false')
            else:
                out[section][key] = value
    return out
