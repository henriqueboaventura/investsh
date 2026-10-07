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
