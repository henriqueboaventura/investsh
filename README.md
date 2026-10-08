# investsh

Controle pessoal de investimentos no terminal, feito para o investidor
brasileiro. **100% local**, em Python puro: sem servidor, sem conta, sem dependências
obrigatórias. Seus dados ficam em arquivos JSON no seu computador.

- **Carteira** — patrimônio total, alocação atual vs. ideal, reserva de emergência, exposição
  por indexador e por objetivo, visão por corretora e gráficos de evolução no terminal
- **Rentabilidade vs CDI e IPCA** — quanto a carteira rendeu descontando os aportes, por mês,
  nos últimos 12 meses e desde o início, lado a lado com o CDI e o IPCA do mesmo período
  (dados do Banco Central)
- **Alertas de vencimento** — títulos que vencem nos próximos 90 dias (ou já venceram) aparecem
  no Sumário, com aviso ao abrir quando faltam 30 dias ou menos
- **Rotina mensal** — atualize saldos, registre aportes e saques, cadastre ativos; cada save
  guarda um snapshot no histórico
- **Cotações automáticas** — dólar ([AwesomeAPI](https://docs.awesomeapi.com.br/)) e cripto
  ([CoinGecko](https://www.coingecko.com/en/api)) recalculam esses ativos ao abrir
- **Resumo em imagem** — com `matplotlib`, gera um PNG da carteira a cada save
- **Análise com IA** — gera um prompt completo da carteira para colar no Claude ou outro assistente

![Resumo gerado com os dados de exemplo](docs/status-example.png)

---

## Começo rápido

Requisito: **Python 3.9+** (macOS ou Linux; no Windows, use o WSL). Instale com
[pipx](https://pipx.pypa.io), que coloca o comando `investsh` no seu PATH:

```bash
pipx install git+https://github.com/henriqueboaventura/investsh.git
```

Depois é só rodar, de qualquer pasta:

```bash
investsh
```

Seus dados ficam em **`~/.investsh/`**. Para usar outra pasta:

| Como | Exemplo |
|---|---|
| Opção `--dir` | `investsh --dir ~/minhas-financas` (ou `--dir .` para a pasta atual) |
| Variável de ambiente | `export INVESTSH_DIR=~/minhas-financas` |
| Link simbólico | `ln -s ~/minhas-financas ~/.investsh` (útil se a pasta é um repositório git em outro lugar) |

Na primeira execução o investsh cria `~/.investsh/data/investments.json` e pergunta:

- **Carteira vazia** (recomendado) — para começar a cadastrar seus ativos
- **Dados de exemplo** — uma carteira fictícia, para explorar antes de usar de verdade

Depois:

1. Tecle `p` (**Parâmetros**) e ajuste FGTS, aporte mensal, premissas de projeção,
   alocação ideal e faixa da reserva de emergência.
2. Tecle `n` (**Novo ativo**) para cadastrar cada investimento.
3. Tecle `w` para salvar.

> Prefere editar JSON à mão? Use [`src/investsh/examples/investments.json`](src/investsh/examples/investments.json)
> como modelo em `data/investments.json`.
> O formato está em [docs/DATA_FORMAT.md](docs/DATA_FORMAT.md).

Opcional — para o resumo em imagem, instale o matplotlib junto:

```bash
pipx inject investsh matplotlib
```

---

## Rotina mensal

```bash
investsh
```

| Tecla | Ação |
|---|---|
| `u` | Atualizar o saldo de todos os ativos, um a um (Enter mantém o valor) |
| `Enter` | Na aba Detalhe: atualizar saldo, aporte, saque ou excluir o ativo selecionado |
| `n` | Cadastrar novo ativo |
| `p` | Parâmetros |
| `/` | Buscar (aba Detalhe) |
| `s` `r` `a` `i` `o` `d` `b` `g` | Abas: Sumário, Rentabilidade, Alocação, Indexador, Objetivo, Detalhe, Brokers, Gráficos |
| `↑` `↓` / `j` `k` | Navegar |
| `R` | Recarregar do disco (após editar os arquivos por fora) |
| `w` | Salvar |
| `q` | Sair |

Ao salvar:

- `data/investments.json` é gravado e um snapshot vai para `data/history.json`
  (alimenta os gráficos de evolução);
- com `matplotlib` instalado, o resumo visual é gerado em `assets/status.png`;
- com o [commit automático](#versionar-seus-dados-com-git) ligado, os dados são commitados
  e enviados ao remoto.

Na tela interativa, a imagem e o commit/push rodam **em segundo plano**: a tela não trava
e você pode sair na hora, que o envio continua sozinho. A barra mostra `↻ enviando…` e
depois o resultado (`↑ push ok` ou `⚠ push falhou`). Se um envio falhar (ex.: sem
internet), o investsh avisa na próxima vez que abrir; para reenviar:

```bash
investsh sync     # gera a imagem e faz commit/push agora, mostrando o resultado
```

Sem terminal interativo, ou para scripts: `investsh --menu` abre um menu
numerado com as mesmas funções (opção `V` mostra a carteira completa).

---

## Análise com IA

```bash
investsh analyze
```

Gera um prompt com toda a carteira (alocação vs. ideal, desempenho, vencimentos, parâmetros)
e copia para o clipboard (macOS). Sem clipboard, salva em `analise_prompt.txt`. Cole numa
conversa nova no [claude.ai](https://claude.ai) ou no assistente que preferir. Lembre que
isso envia os dados da sua carteira para o serviço escolhido.

---

## Rentabilidade

A aba **Rentabilidade** (tecla `r`; no `--menu`, opção `V`) responde: *a carteira rendeu mais
que o CDI?* Para isso o investsh usa as fotos que cada save grava em `data/history.json`:

- entre dois saves, o rendimento desconta os aportes e saques do período (método de Dietz
  modificado: aportes contam pela metade do período);
- a variação do dólar no custo dos ativos em USD não conta como aporte;
- CDI e IPCA vêm da API pública do Banco Central, acumulados exatamente no mesmo período,
  e ficam em cache por 12 horas em `~/.cache/investsh` (sem internet, usa o cache);
- o IPCA de um mês só sai no mês seguinte: meses ainda não divulgados aparecem com `*`.

O cálculo começa no primeiro save com "total investido" registrado: quanto mais saves, mais
completo o histórico. Salvar uma vez por mês já basta para a visão mensal.

No **Sumário**, o *Histórico mensal* decompõe a variação do saldo de cada mês:
**Variação = Aportes + Saques + Valorização**, com a rentabilidade do mês ao lado. Para o
investsh separar aporte de rendimento, registre depósitos e resgates com **Registrar aporte**
e **Registrar saque** (em vez de só atualizar o saldo).

## Privacidade

- O investsh só lê e escreve arquivos locais. As únicas chamadas de rede são as cotações
  (AwesomeAPI e CoinGecko), que não recebem nenhum dado seu.
- Seus dados ficam em `~/.investsh/` (ou na pasta que você escolher), separados do código.
  Nada vai para o git a menos que você ligue o commit automático (abaixo).

### Versionar seus dados com git

Para ter histórico ou sincronizar entre computadores, faça da sua pasta de dados um
repositório git **privado** e crie nela um arquivo `investsh.toml`. Se o repositório já
existe em outro lugar, aponte o `~/.investsh` para ele com um link simbólico:

```bash
git clone git@github.com:voce/minhas-financas.git ~/minhas-financas   # privado!
ln -s ~/minhas-financas ~/.investsh
```

`~/.investsh/investsh.toml`:

```toml
[git]
auto_commit = true   # commit "update AAAA-MM" a cada save
push = true          # e envia para o remoto (false = só commit local)
```

A configuração vale só para essa pasta de dados: usar outra com `--dir` não commita nada.
Commits que não chegarem ao remoto (ex.: sem internet) são avisados ao abrir o investsh e
reenviados no próximo save ou com `investsh sync`.
Sem o arquivo (ou com `auto_commit = false`), o commit automático fica desligado.
Para ligar ou desligar temporariamente, por cima do arquivo: `FINANCES_AUTO_GIT=1` ou `0`.

O mesmo arquivo ajusta a janela dos alertas de vencimento (padrão: 90 dias):

```toml
[alerts]
maturity_days = 180
```

---

## Personalização

| O quê | Onde |
|---|---|
| Alocação ideal, reserva, FGTS, projeção | Tecla `p` no `investsh`, ou `data/investments.json` |
| Commit automático dos dados | `investsh.toml` na pasta de dados (ver [Privacidade](#versionar-seus-dados-com-git)) |
| Grupos de alocação | `GROUP_META` em `src/investsh/core.py` |
| Corretoras e ordem | `_BROKERS` e `BROKER_ORDER` em `src/investsh/core.py`; cores em `BR_C` (`image.py`) |
| Criptos com cotação automática | `CRYPTO_IDS` (IDs do CoinGecko) em `src/investsh/core.py` |

Ativos com `investedUSD` (ex.: corretora Nomad) são tratados como investimentos em dólar e
convertidos pela cotação do dia.

---

## Estrutura

```
├── src/investsh/
│   ├── cli.py            # Comando `investsh` (--menu, --dir, analyze, sync)
│   ├── app.py            # Carrega a carteira e abre o menu ou a TUI
│   ├── core.py           # Regras: classificação, custo base, reserva, histórico, R$
│   ├── perf.py           # Rentabilidade descontando aportes vs CDI/IPCA
│   ├── bench.py          # CDI e IPCA do Banco Central (com cache)
│   ├── quotes.py         # Cotações (dólar e cripto)
│   ├── menu.py           # Modo texto (--menu)
│   ├── tui.py            # Tela interativa (curses)
│   ├── image.py          # Imagem de resumo (matplotlib)
│   ├── storage.py        # Primeira execução, salvar, histórico
│   ├── sync.py           # Imagem + commit/push (em segundo plano na TUI; `investsh sync`)
│   ├── analyze.py        # Prompt de análise para IA
│   └── examples/         # Dados fictícios (ponto de partida)
├── tests/                # Testes de regressão (ver tests/README.md)
└── docs/
    └── DATA_FORMAT.md    # Formato dos arquivos JSON
```

Na pasta de dados (`~/.investsh`, ou a escolhida com `--dir` / `$INVESTSH_DIR`):

```
├── investsh.toml         # opcional: configuração (commit automático)
├── data/
│   ├── investments.json  # carteira atual
│   └── history.json      # snapshots a cada save
└── assets/status.png     # resumo em imagem (com matplotlib)
```

---

## Problemas comuns

**Caracteres estranhos, sem cores ou tela cortada** — use um terminal UTF‑8 com pelo menos
100 colunas, ou o modo texto: `investsh --menu`.

**`_curses` não encontrado (Windows)** — rode no WSL, ou use `--menu`.

**Cotações não atualizam** — as APIs públicas têm limite de requisições; espere um minuto e
abra de novo. Sem cotação, os saldos salvos continuam valendo.

**"pip install matplotlib → necessário para imagem"** — aviso apenas; tudo funciona sem ele,
só não gera o PNG.

---

## Contribuindo

O projeto tem uma suíte de regressão que cobre o menu, a TUI, a imagem e os cálculos:

```bash
git clone https://github.com/henriqueboaventura/investsh.git && cd investsh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest          # rápidos (~10s)
.venv/bin/pytest --all    # inclui a tela interativa (~1 min); é o que o CI roda
```

Detalhes em [tests/README.md](tests/README.md).

## Aviso

Ferramenta pessoal de organização, não recomendação de investimento. Confira sempre os saldos
nos extratos oficiais.

## Licença

[MIT](LICENSE)
