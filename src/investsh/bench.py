"""CDI e IPCA da API pública do Banco Central (SGS), com cache local.

Séries: 12 = CDI diário (% ao dia), 433 = IPCA mensal (% no mês). O cache fica em
$XDG_CACHE_HOME/investsh (padrão ~/.cache/investsh), fora da pasta de dados, e vale
12 horas. Sem internet, usa o cache mesmo antigo; sem cache, o indicador fica
indisponível e a tela mostra só a carteira.

A API às vezes leva dezenas de segundos para responder: a TUI lê só o cache
(offline=True) e busca em segundo plano.
"""
import json
import os
import time
import urllib.error
import urllib.request
from datetime import date

SERIES = {'cdi': 12, 'ipca': 433}
URL = ('https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados'
       '?formato=json&dataInicial={start}&dataFinal={end}')
MAX_AGE = 12 * 3600


def cache_dir():
    base = os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache')
    return os.path.join(base, 'investsh')


def _fetch(code, start, end):
    url = URL.format(code=code, start=start.strftime('%d/%m/%Y'), end=end.strftime('%d/%m/%Y'))
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            rows = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404 and _not_found(e.read()):
            return []
        raise
    if isinstance(rows, dict) and _not_found(json.dumps(rows).encode()):
        return []
    if not isinstance(rows, list):
        raise ValueError('resposta inesperada do Banco Central')
    return rows


def _not_found(body):
    """Período sem nenhum valor publicado (ex.: IPCA do mês ainda não divulgado).

    A API responde {"erro": {... "Value(s) not found"}}, às vezes com HTTP 404 e às
    vezes com HTTP 200. Não é falha de conexão: o resultado é uma série vazia.
    """
    return b'not found' in body.lower()


def _rows(name, start, today, offline=False):
    path = os.path.join(cache_dir(), f'{name}.json')
    try:
        with open(path, encoding='utf-8') as f:
            cached = json.load(f)
    except (FileNotFoundError, ValueError):
        cached = None
    if offline:
        # Só o cache, mesmo antigo, desde que cubra o início pedido
        ok = cached and cached.get('start', '9999') <= start.isoformat()
        return cached['rows'] if ok else None
    if (cached and cached.get('start', '9999') <= start.isoformat()
            and cached.get('end') == today.isoformat()
            and time.time() - cached.get('fetched_at', 0) < MAX_AGE):
        return cached['rows']
    try:
        rows = _fetch(SERIES[name], start, today)
    except Exception:
        return cached['rows'] if cached else None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'start': start.isoformat(), 'end': today.isoformat(),
                   'fetched_at': time.time(), 'rows': rows}, f)
    os.replace(tmp, path)
    return rows


def _date(s):
    d, m, y = s.split('/')
    return date(int(y), int(m), int(d))


def cdi(start, today, offline=False):
    """{data: CDI do dia em %} desde `start`, ou None se indisponível."""
    rows = _rows('cdi', start, today, offline)
    return None if rows is None else {_date(r['data']): float(r['valor']) for r in rows}


def ipca(start, today, offline=False):
    """{(ano, mês): IPCA do mês em %} desde o mês de `start`, ou None se indisponível."""
    rows = _rows('ipca', date(start.year, start.month, 1), today, offline)
    if rows is None:
        return None
    out = {}
    for r in rows:
        d = _date(r['data'])
        out[(d.year, d.month)] = float(r['valor'])
    return out
