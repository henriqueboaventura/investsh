# Testes

Testes de regressão por **caracterização**: registram o comportamento atual do
investsh em arquivos *golden* (`tests/golden/`) e falham se qualquer coisa mudar.
Servem de rede de segurança para refatorações.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest            # suíte completa (~3 min, a maior parte na TUI)
.venv/bin/pytest -k menu    # só um grupo
```

## O que é coberto

| Arquivo | O quê | Como |
|---|---|---|
| `test_core.py` | Cálculos: formatação, classificação, custo base, reserva, histórico | Unitário, valores calculados à mão |
| `test_menu.py` | Todos os fluxos do `--menu`, primeira execução, save, auto-git | Saída completa (com cores) + `data/` final |
| `test_tui.py` | Todas as abas, navegação, busca, ações, cadastro, parâmetros, save | Telas capturadas num terminal emulado (texto + mapa de estilos) |
| `test_status_image.py` | Imagem `assets/status.png` | Chamadas de desenho do matplotlib (pixels variam por máquina) |
| `test_analyze.py` | Prompt de análise, clipboard e fallback para arquivo | Prompt completo |

## Determinismo

Cada teste roda numa cópia do projeto em `/tmp/ish-XXXXXXXX/app`, via
`tests/harness.py`, que:

- congela data/hora em `2026-10-06 12:00` (`INVESTSH_TEST_NOW`);
- troca as APIs de cotação por valores fixos (USD 5,4321, BTC R$ 600.000…);
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
(`FINANCES_CMD`, `ANALYZE_CMD`, `App.setup`, `load_finances`). Ao mover o código
(ex.: para um pacote), ajuste só esses pontos: os goldens não devem mudar.

`INVESTSH_TEST_SRC=/outro/diretorio pytest` roda a suíte contra outra cópia do
código, útil para comparar versões.

## Bugs conhecidos

Encontrados ao escrever a suíte. Os goldens registram o comportamento **atual**;
ao corrigir um deles, regrave os goldens afetados e revise o diff.

| # | Onde | Bug | Teste que registra |
|---|---|---|---|
| 1 | Imagem | Com matplotlib recente (ex.: 3.11; a versão do Python 3.9 não quebra), salvar carteira vazia quebra (`pie` sem fatias) depois de gravar `data/`; no `--menu` o programa sai com erro | `test_save_empty_portfolio_with_matplotlib` (xfail) |
| 2 | TUI | Corrigido: o popup restaurava a tela byte a byte e deixava `^^^^@` no lugar de caracteres não-ASCII | `asset_actions`, `new_assets`, `field_editing` |
| 3 | TUI | Texto com acento digitado vira mojibake (`Debênture` → `DebÃªnture`): `curs_input` trata bytes UTF-8 como caracteres | `tui/new_assets.txt` |
| 4 | TUI | "Atualizar todos" (`u`) muda a quantidade de cripto mas não recalcula o saldo em R$ | `tui/update_all.txt` |
| 5 | Menu | Ao remover vários ativos, a ordem das mensagens "✗ Removido" é aleatória (itera um `set`) | `test_remove_multiple_assets` |
| 6 | TUI | `g` abre a aba Gráficos, então o atalho "g = topo" nunca executa | — |
| 7 | TUI | Avisos do matplotlib (stderr) aparecem desenhados por cima da tela durante o save | silenciado no `harness.py` |
