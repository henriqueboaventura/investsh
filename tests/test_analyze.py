"""Regressão do gerador de prompt de análise (analyze.py)."""
import os
import stat

from support import ANALYZE_CMD, assert_golden


def fake_pbcopy(tmp_path):
    """Diretório com um `pbcopy` falso que grava o que recebe."""
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    out = tmp_path / 'clipboard.txt'
    script = bindir / 'pbcopy'
    script.write_text(f'#!/bin/sh\ncat > "{out}"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return bindir, out


def run_analyze(app, path):
    proc = app.run(ANALYZE_CMD, PATH=path)
    assert proc.stderr == ''
    return proc


def test_prompt_copied_to_clipboard(demo, tmp_path):
    bindir, clip = fake_pbcopy(tmp_path)
    proc = run_analyze(demo, f'{bindir}{os.pathsep}/usr/bin:/bin')
    assert proc.returncode == 0
    assert_golden('analyze/demo_stdout.txt', demo.normalize(proc.stdout))
    assert_golden('analyze/demo_prompt.txt', clip.read_text(encoding='utf-8'))
    assert not (demo.root / 'analise_prompt.txt').exists()


def test_prompt_saved_to_file_without_clipboard(demo, tmp_path):
    empty = tmp_path / 'empty-bin'
    empty.mkdir()
    proc = run_analyze(demo, str(empty))
    assert proc.returncode == 0
    assert_golden('analyze/no_clipboard_stdout.txt', demo.normalize(proc.stdout))
    saved = (demo.root / 'analise_prompt.txt').read_text(encoding='utf-8')
    assert_golden('analyze/demo_prompt.txt', saved)  # mesmo conteúdo do clipboard


def test_prompt_edge_dataset(app, tmp_path):
    app.seed('edge')
    bindir, clip = fake_pbcopy(tmp_path)
    proc = run_analyze(app, f'{bindir}{os.pathsep}/usr/bin:/bin')
    assert proc.returncode == 0
    assert_golden('analyze/edge_stdout.txt', app.normalize(proc.stdout))
    assert_golden('analyze/edge_prompt.txt', clip.read_text(encoding='utf-8'))
