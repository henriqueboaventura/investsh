# Testes

Testes de regressão por **caracterização**: registram o comportamento atual do
investsh em arquivos *golden* (`tests/golden/`) e falham se qualquer coisa mudar.
Servem de rede de segurança para refatorações.

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest            # rápidos: cálculos, menu, CLI, configuração (~10s)
.venv/bin/pytest --all      # tudo, inclusive a tela interativa (~1 min); o CI usa este
.venv/bin/pytest -n0 -k menu --all   # um grupo, sem paralelismo (melhor para depurar)
```

Os testes rodam em paralelo (`pytest-xdist`, `-n auto` no `pytest.ini`): cada um usa
uma pasta isolada. Todo teste que dirige a tela interativa (fixture `tui_factory`) é
marcado como `slow` automaticamente e só roda com `--all`.

## O que é coberto

| Arquivo | O quê | Como |
|---|---|---|
| `test_perf.py` | Rentabilidade descontando aportes, câmbio, CDI/IPCA proporcionais, vencimentos | Unitário, valores calculados à mão |
| `test_benchmarks.py` | CDI/IPCA na tela, cache, sem internet, janela de vencimentos no `investsh.toml` | Banco Central falso no `sitecustomize` |
| `test_core.py` | Cálculos: formatação, classificação, custo base, reserva, histórico | Unitário, valores calculados à mão |
| `test_menu.py` | Todos os fluxos do `--menu`, primeira execução, save, auto-git | Saída completa (com cores) + `data/` final |
| `test_tui.py` | Todas as abas, navegação, busca, ações, cadastro, parâmetros, save | Telas capturadas num terminal emulado (texto + mapa de estilos) |
| `test_status_image.py` | Imagem `assets/status.png` | Chamadas de desenho do matplotlib (pixels variam por máquina) |
| `test_analyze.py` | Prompt de análise, clipboard e fallback para arquivo | Prompt completo |
| `test_config_file.py` | `investsh.toml`: commit/push automático, validação, variável de ambiente por cima | Repositório git real com remoto |
| `test_background_sync.py` | Save da TUI não espera o push (remoto lento de verdade), fila de saves, falha + aviso + `investsh sync` | Repositório git real com hook que atrasa ou recusa o push |
| `test_cli.py` | Pasta de dados (`--dir`, `$INVESTSH_DIR`, padrão `~/.investsh`, `~`), `--version`, subcomandos | Asserções |

## Determinismo

Cada teste roda numa pasta temporária `/tmp/ish-XXXXXXXX/app` (via `INVESTSH_DIR`, com um
`HOME` falso ao lado: o seu `~/.investsh` nunca é tocado), com `tests/site` no
`PYTHONPATH`. O `tests/site/sitecustomize.py` é carregado pelo Python em **todo**
processo iniciado pelos testes (inclusive os de segundo plano do investsh) e:

- congela data/hora em `2026-10-06 12:00` (`INVESTSH_TEST_NOW`);
- troca as APIs de cotação por valores fixos (USD 5,4321, BTC R$ 600.000…) e a do Banco
  Central por CDI 0,05% ao dia útil e IPCA 0,40% ao mês (divulgado até ago/2026);
  `INVESTSH_TEST_RATES=fail` simula rede fora;
- fixa `PYTHONHASHSEED` e remove avisos de fontes do matplotlib da saída.

A TUI roda num pseudo-terminal 140×45 (ou 80×24) e a tela é lida com
[pyte](https://github.com/selectel/pyte). No golden, cada tela vem com um
**mapa de estilos** alinhado ao texto: letra = cor (`g` verde, `r` vermelho,
`c` ciano, `m` magenta, `y` amarelo, `.` padrão), maiúscula = negrito,
`=`/`#` = vídeo reverso (barras e linha selecionada).

## Quando um teste falha

O erro mostra o diff entre o golden e a saída atual.

- **Mudança não intencional** → é regressão: corrija o código.
- **Mudança intencional** (texto novo, layout, correção de bug) → regrave e
  revise o diff no git antes de commitar:

  ```bash
  UPDATE_GOLDEN=1 .venv/bin/pytest
  git diff tests/golden
  ```

## Reestruturação do código

Os pontos de entrada estão centralizados em `tests/support.py`
(`PKG_SRC`, `FINANCES_CMD`, `ANALYZE_CMD`, `App.setup`, `load_finances`). Ao mover
o código, ajuste só esses pontos: os goldens não devem mudar.

Os processos testados rodam `python -m investsh` com `src/` no `PYTHONPATH`, ou
seja, testam o código do repositório (não um investsh instalado).

`INVESTSH_TEST_SRC=/outro/diretorio pytest` roda a suíte contra outra cópia do
código, útil para comparar versões.

## Bugs encontrados pela suíte

Todos corrigidos, um commit por bug, com o diff dos goldens limitado ao efeito
da correção. A coluna da direita aponta o teste que protege contra a volta do bug.

| # | Onde | Bug | Teste |
|---|---|---|---|
| 1 | Imagem, menu, TUI | carteira vazia ou com saldos zerados quebrava a imagem (`pie` sem fatias) e as telas (divisão por zero) | `test_save_empty_portfolio_with_matplotlib`, `view_zero_balances`, `tui/zero_balances` |
| 2 | TUI | o popup restaurava a tela byte a byte e deixava `^^^^@` no lugar de caracteres não-ASCII | `asset_actions`, `new_assets`, `field_editing` |
| 3 | TUI | texto com acento digitado (campos e busca) virava mojibake (`Debênture` → `DebÃªnture`) | `tui/accented_input.txt`, `tui/new_assets.txt` |
| 4 | TUI | "atualizar todos" (`u`) mudava a quantidade de cripto sem recalcular o saldo em R$ | `tui/update_all.txt` |
| 5 | Menu | ao remover vários ativos, a ordem das mensagens "✗ Removido" era aleatória (itera um `set`) | `menu/remove_multiple.txt` |
| 6 | TUI | o atalho "g = topo" nunca executava (`g` é a aba Gráficos); agora é Home (e End = fim, além de G) | `tui/tabs.txt`, `tui/detail_search.txt` |
| 7 | TUI | avisos do matplotlib (stderr) apareciam desenhados por cima da tela durante o save | `test_save_keeps_stderr_off_screen` |
