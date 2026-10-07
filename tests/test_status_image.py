"""Regressão da imagem de resumo (assets/status.png).

Pixels variam com fontes e versão do matplotlib, então o golden registra as
chamadas de desenho (textos, valores, cores, posições) feitas para montar a imagem.
"""
import json

import pytest

from support import assert_golden

pytest.importorskip('matplotlib')


def render(app, tmp_path, stdin):
    log = tmp_path / 'plot.json'
    proc = app.menu(stdin, INVESTSH_TEST_PLOTLOG=log)
    png = app.root / 'assets' / 'status.png'
    assert png.read_bytes()[:4] == b'\x89PNG'
    return proc, json.loads(log.read_text(encoding='utf-8'))


def golden(name, calls):
    lines = [json.dumps(c, ensure_ascii=False, sort_keys=True) for c in calls]
    assert_golden(f'image/{name}.jsonl', '\n'.join(lines) + '\n')


def test_image_demo(demo, tmp_path):
    proc, calls = render(demo, tmp_path, ['0', 's'])
    assert proc.returncode == 0
    golden('demo', calls)


def test_image_edge(app, tmp_path):
    app.seed('edge')
    proc, calls = render(app, tmp_path, ['0', 's'])
    assert proc.returncode == 0
    golden('edge', calls)


def test_image_without_history(demo, tmp_path):
    (demo.data_dir / 'history.json').unlink()
    proc, calls = render(demo, tmp_path, ['0', 's'])
    assert proc.returncode == 0
    golden('no_history', calls)


def test_image_after_losses(demo, tmp_path):
    # Saldos caem: variação negativa muda cores e sinais na imagem
    n = len(demo.read('investments.json')['investments'])
    answers = ['1000'] * (n - 2) + ['0.0001', '0.001']
    proc, calls = render(demo, tmp_path, ['1', *answers, '0', 's'])
    assert proc.returncode == 0
    golden('losses', calls)


def test_image_empty_portfolio(app, tmp_path):
    proc, calls = render(app, tmp_path, ['1', '0', 's'])
    assert proc.returncode == 0
    golden('empty', calls)
