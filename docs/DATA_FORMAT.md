# Formato dos dados

Todos os dados ficam em `data/` (fora do git por padrão). Exemplos completos em
[`src/investsh/examples/`](../src/investsh/examples). Você pode editar os arquivos à
mão ou usar o `investsh`, que escreve exatamente este formato.

Datas usam `YYYY-MM-DD`. Valores monetários estão em reais (BRL), exceto campos com
sufixo `USD`.

## `data/investments.json`

```jsonc
{
  "lastUpdated": "2026-10-01",
  "dollarRate": 5.40,            // atualizado pelo investsh ao buscar cotações
  "fgts": 18500.0,               // saldo do FGTS (entra só no "total com FGTS")
  "idealAllocation": { ... },    // ver abaixo
  "emergencyReserve": { ... },   // ver abaixo
  "projectionParams": {
    "monthlyReturn": 0.008,        // 0,8% a.m.
    "fgtsAnnualReturn": 0.06,      // 6% a.a.
    "monthlyContribution": 1500.0  // aporte mensal
  },
  "investments": [ ... ],
  "flowsSince": "2026-10-01",    // a partir desta data, `flows` está completo
  "flows": [ ... ]               // aportes e saques (ver abaixo)
}
```

### `flows`

Dinheiro que entrou (+, aporte) ou saiu (−, saque) da carteira, gravado por *Registrar
aporte/saque* e ao criar ou excluir ativo com saldo. A rentabilidade usa estes lançamentos
nos períodos a partir de `flowsSince` (definido no primeiro save); antes disso, usa a
variação de `totalInvested` no histórico.

```json
{ "date": "2026-10-06", "name": "SGOV", "broker": "Nomad", "amount": -271.61, "usd": -50.0 }
```

- `amount` — valor em R$ (ativos em dólar: convertido pela cotação do dia).
- `usd` — opcional, o valor em dólar do lançamento.
- Um lançamento com a data de um save já está na foto daquele dia.

### `idealAllocation`

Percentuais (0–100). Os quatro primeiros são as classes principais e devem somar 100;
os demais são as subclasses, também em % da carteira total.

| Chave | Significado |
|---|---|
| `rendaFixa`, `rendaVariavel`, `multiAtivoGlobal`, `previdencia` | Classes principais |
| `rfCDI`, `rfPre`, `rfIPCA`, `rfExterior` | Subclasses de renda fixa |
| `rvETFBrasil`, `rvETFExterior`, `rvFundosAcoes`, `rvFII`, `rvOuro`, `rvCrypto` | Subclasses de renda variável |

### `emergencyReserve`

```jsonc
{
  "minimum": 20000.0, "target": 30000.0, "maximum": 40000.0,
  "assetNames": ["Tesouro Selic 2029"],  // opcional; sem ele, valem os ativos
                                         // com allocationGroup RESERVA_EMERGENCIA
  "excludeFromAllocation": true          // reserva fora do cálculo de alocação
}
```

### Cada investimento

Campos comuns:

| Campo | Obrigatório | Descrição |
|---|---|---|
| `name` | sim | Nome único do ativo |
| `category` | sim | `CDB`, `LCA`, `LCI`, `RDB`, `Tesouro Direto`, `ETF`, `Fundo Imobiliário`, `Fundos de Investimento`, `Previdência Privada`, `Crypto` (ou outro texto) |
| `type` | não | `POS`, `PRE`, `IPCA`, `Ouro` ou `null` |
| `broker` | sim | Corretora/banco (`XP`, `Nubank`, `Nomad`, `Binance` têm cores próprias; outros funcionam) |
| `maturity` | não | Vencimento, ou `null` |
| `balance` | sim | Saldo atual em BRL |
| `invested` | não | Custo/valor aplicado em BRL (base para rentabilidade) |
| `previousBalance` | não | Saldo no save anterior — preenchido pelo `investsh` |
| `allocationGroup` | recomendado | Classe de alocação, ver tabela abaixo |
| `indexer` | não | `CDI`, `SELIC`, `FIXED_RATE`, `IPCA`, `SP_500`, `FTSE_GLOBAL_ALL_CAP`, `LBMA_GOLD_PRICE`, `ICE_0_3_MONTH_US_TREASURY_SECURITIES_INDEX`, `IAFD` ou `null` |
| `purpose` | não | Objetivo financeiro, ex. `RESERVA_EMERGENCIA`, `PROTECAO_INFLACAO_LONGO_PRAZO`, `APOSENTADORIA_E_LONGO_PRAZO` (lista completa em `_PURPOSES` no `src/investsh/core.py`; outros textos são aceitos) |
| `rate` | não | `{"kind": "PERCENT_CDI" \| "ANNUAL_FIXED" \| "IPCA_PLUS", "value": 110.0}` |
| `liquidity` | não | `IMMEDIATE`, `DAILY`, `DAILY_MARKET_PRICE`, `AT_MATURITY` |
| `taxExempt`, `fgcEligible` | não | Booleanos |

Valores de `allocationGroup`:

| Grupo | Classe | Chave em `idealAllocation` |
|---|---|---|
| `RF_CDI` | Renda Fixa | `rfCDI` |
| `RF_PRE` | Renda Fixa | `rfPre` |
| `RF_IPCA` | Renda Fixa | `rfIPCA` |
| `RF_EXTERIOR` | Renda Fixa | `rfExterior` |
| `RESERVA_EMERGENCIA` | Renda Fixa | — (card próprio) |
| `CAIXA_TRANSITORIA` | Renda Fixa | — |
| `RV_ETF_BRASIL` | Renda Variável | `rvETFBrasil` |
| `RV_ETF_EXTERIOR` | Renda Variável | `rvETFExterior` |
| `RV_FUNDOS_ACOES` | Renda Variável | `rvFundosAcoes` |
| `RV_FII` | Renda Variável | `rvFII` |
| `RV_OURO` | Renda Variável | `rvOuro` |
| `RV_CRYPTO` | Renda Variável | `rvCrypto` |
| `MULTIATIVO_GLOBAL` | Multiativo Global | — |
| `PREVIDENCIA` | Previdência | — |

#### Casos especiais

**Ativos em dólar** — use `investedUSD` (custo) e `balanceUSD` (saldo) em vez de `invested`.
O `balance` em BRL é recalculado com a cotação do dia.

```json
{ "name": "VT", "category": "ETF", "broker": "Nomad", "investedUSD": 1500.0,
  "balanceUSD": 1730.40, "balance": 9344.16, "allocationGroup": "RV_ETF_EXTERIOR" }
```

**Cripto** — use `quantity` (em unidades da moeda) e, opcionalmente, `averagePrice` (preço médio
em BRL). O `name` precisa ser uma chave de `CRYPTO_IDS` (`Bitcoin`, `Ethereum`, `Dogecoin`,
`XRP`) para a cotação automática funcionar — adicione outras moedas nesse mapa no
`src/investsh/core.py`, com o ID do CoinGecko.

```json
{ "name": "Bitcoin", "category": "Crypto", "broker": "Binance", "quantity": 0.0045,
  "averagePrice": 480000.0, "balance": 2790.0, "allocationGroup": "RV_CRYPTO" }
```

## `data/history.json`

Lista de snapshots, um por data de save. O `investsh` adiciona/atualiza automaticamente.

```json
[
  { "date": "2026-09-01", "total": 198000.0, "totalWithFGTS": 216400.0, "totalInvested": 185000.0 },
  { "date": "2026-10-01", "total": 205576.35, "totalWithFGTS": 224076.35, "totalInvested": 190000.0,
    "totalInvestedUSD": 2700.0, "dollarRate": 5.40,
    "assets": [ { "name": "...", "category": "...", "type": "...", "broker": "...", "maturity": null, "balance": 0 } ] }
]
```

Campos opcionais (fotos antigas podem não ter):

- `totalInvested` — custo total; base da rentabilidade antes de `flowsSince` (ver `flows`).
- `totalInvestedUSD` e `dollarRate` — custo em dólar e câmbio do dia: separam aporte de
  variação cambial no cálculo da rentabilidade.
- `assets` — saldos por ativo, usados nos gráficos por corretora.
