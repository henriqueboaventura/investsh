"""Gera prompt de análise da carteira e copia pro clipboard. Cole no claude.ai."""

import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

# Diretório de trabalho (contém data/); o comando `investsh analyze --dir` muda.
BASE = Path.cwd()


def load_portfolio():
    with open(BASE / "data" / "investments.json") as f:
        return json.load(f)


# allocationGroup (fonte de verdade, ver GROUP_META no finances.py) → classes
# usadas neste relatório. Ativos sem allocationGroup caem na heurística antiga.
_GROUP_TO_CLASS = {
    "RF_CDI": "RF_CDI", "RESERVA_EMERGENCIA": "RF_CDI", "CAIXA_TRANSITORIA": "RF_CDI",
    "RF_PRE": "RF_PRE", "RF_IPCA": "RF_IPCA",
    "RV_ETF_BRASIL": "RV_ETF", "RV_ETF_EXTERIOR": "RV_ETF", "RV_OURO": "RV_OURO",
    "RV_FUNDOS_ACOES": "RV_FUNDOS", "RV_FII": "RV_FII", "RV_CRYPTO": "RV_CRYPTO",
    "PREVIDENCIA": "PREVIDENCIA",
}


def normalize_ideal(ideal):
    """Alocação ideal com a chave agregada rvETF (Brasil + Exterior)."""
    ideal = dict(ideal)
    ideal.setdefault("rvETF", ideal.get("rvETFBrasil", 0) + ideal.get("rvETFExterior", 0))
    for k in ("rendaFixa", "rendaVariavel", "previdencia", "rfCDI", "rfPre", "rfIPCA",
              "rvOuro", "rvFundosAcoes", "rvFII", "rvCrypto"):
        ideal.setdefault(k, 0)
    return ideal


def classify(inv):
    group = inv.get("allocationGroup")
    if group:
        return _GROUP_TO_CLASS.get(group, "OUTROS")
    cat = inv.get("category", "")
    typ = inv.get("type", "")
    if typ == "POS":    return "RF_CDI"
    if typ == "PRE":    return "RF_PRE"
    if typ == "IPCA":   return "RF_IPCA"
    if cat == "Fundo Imobiliário":      return "RV_FII"
    if cat == "Fundos de Investimento": return "RV_FUNDOS"
    if cat == "ETF" and typ == "Ouro":  return "RV_OURO"
    if cat == "ETF":                    return "RV_ETF"
    if cat == "Previdência Privada":    return "PREVIDENCIA"
    if cat == "Crypto":                 return "RV_CRYPTO"
    return "OUTROS"


def compute(data):
    invs = data["investments"]
    ideal = normalize_ideal(data["idealAllocation"])
    fgts = data["fgts"]
    today = date.today()

    keys = ["RF_CDI", "RF_PRE", "RF_IPCA", "RV_FII", "RV_ETF",
            "RV_OURO", "RV_FUNDOS", "RV_CRYPTO", "PREVIDENCIA", "OUTROS"]
    buckets = {k: [] for k in keys}
    for inv in invs:
        buckets[classify(inv)].append(inv)

    totals = {k: sum(i["balance"] for i in v) for k, v in buckets.items()}
    ptotal = sum(totals.values())

    def pct(v): return round(v / ptotal * 100, 1) if ptotal else 0

    rf  = totals["RF_CDI"] + totals["RF_PRE"] + totals["RF_IPCA"]
    rv  = sum(totals[k] for k in ["RV_FII", "RV_ETF", "RV_OURO", "RV_FUNDOS", "RV_CRYPTO"])
    prv = totals["PREVIDENCIA"]

    actual = {
        "rendaFixa": pct(rf), "rendaVariavel": pct(rv), "previdencia": pct(prv),
        "rfCDI": pct(totals["RF_CDI"]), "rfPre": pct(totals["RF_PRE"]), "rfIPCA": pct(totals["RF_IPCA"]),
        "rvETF": pct(totals["RV_ETF"]), "rvOuro": pct(totals["RV_OURO"]),
        "rvFundosAcoes": pct(totals["RV_FUNDOS"]), "rvFII": pct(totals["RV_FII"]),
        "rvCrypto": pct(totals["RV_CRYPTO"]),
    }
    deviations = {k: round(actual.get(k, 0) - ideal.get(k, 0), 1) for k in ideal}

    perf = []
    for inv in invs:
        invested = inv.get("invested")
        if invested and invested > 0:
            gain = inv["balance"] - invested
            perf.append({
                "name": inv["name"], "class": classify(inv),
                "balance": round(inv["balance"], 2), "invested": round(invested, 2),
                "gain": round(gain, 2), "gain_pct": round(gain / invested * 100, 1),
            })

    alerts = []
    for inv in invs:
        mat = inv.get("maturity")
        if not mat:
            continue
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                mat_date = datetime.strptime(mat, fmt).date()
                days = (mat_date - today).days
                label = "VENCIDO" if days < 0 else f"vence em {days}d"
                if days <= 180:
                    alerts.append({"name": inv["name"], "maturity": mat, "label": label, "days": days})
                break
            except ValueError:
                continue
    alerts.sort(key=lambda x: x["days"])

    return {
        "portfolio_total": round(ptotal, 2),
        "grand_total": round(ptotal + fgts, 2),
        "fgts": fgts,
        "totals": {k: round(v, 2) for k, v in totals.items()},
        "actual": actual, "ideal": ideal, "deviations": deviations,
        "perf": sorted(perf, key=lambda x: x["gain_pct"], reverse=True),
        "alerts": alerts,
        "last_updated": data["lastUpdated"],
        "dollar_rate": data["dollarRate"],
        "proj": data["projectionParams"],
        "assets": invs,
        "num_assets": len(invs),
    }


def build_prompt(m):
    ia, aa, dev = m["ideal"], m["actual"], m["deviations"]

    alloc_table = f"""\
Categoria            | Atual  | Ideal  | Desvio
---------------------|--------|--------|--------
Renda Fixa Total     | {aa['rendaFixa']:5.1f}% | {ia['rendaFixa']:5.1f}% | {dev['rendaFixa']:+.1f}%
  CDI/Pós-fixado    | {aa['rfCDI']:5.1f}% | {ia['rfCDI']:5.1f}% | {dev['rfCDI']:+.1f}%
  Pré-Fixado        | {aa['rfPre']:5.1f}% | {ia['rfPre']:5.1f}% | {dev['rfPre']:+.1f}%
  IPCA+             | {aa['rfIPCA']:5.1f}% | {ia['rfIPCA']:5.1f}% | {dev['rfIPCA']:+.1f}%
Renda Variável Total | {aa['rendaVariavel']:5.1f}% | {ia['rendaVariavel']:5.1f}% | {dev['rendaVariavel']:+.1f}%
  FII               | {aa['rvFII']:5.1f}% | {ia['rvFII']:5.1f}% | {dev['rvFII']:+.1f}%
  ETF               | {aa['rvETF']:5.1f}% | {ia['rvETF']:5.1f}% | {dev['rvETF']:+.1f}%
  Ouro              | {aa['rvOuro']:5.1f}% | {ia['rvOuro']:5.1f}% | {dev['rvOuro']:+.1f}%
  Fundos de Ações   | {aa['rvFundosAcoes']:5.1f}% | {ia['rvFundosAcoes']:5.1f}% | {dev['rvFundosAcoes']:+.1f}%
  Crypto            | {aa['rvCrypto']:5.1f}% | {ia['rvCrypto']:5.1f}% | {dev['rvCrypto']:+.1f}%
Previdência          | {aa['previdencia']:5.1f}% | {ia['previdencia']:5.1f}% | {dev['previdencia']:+.1f}%"""

    alerts_str = "\n".join(
        f"  - {a['name']}: {a['label']} (venc. {a['maturity']})"
        for a in m["alerts"]
    ) or "  Nenhum."

    perf_str = "\n".join(
        f"  - {p['name']} [{p['class']}]: {p['gain_pct']:+.1f}%"
        f"  (investido R${p['invested']:,.0f} → atual R${p['balance']:,.0f}, ganho R${p['gain']:,.0f})"
        for p in m["perf"]
    )

    return f"""Você é um analista sênior de investimentos brasileiro com 20 anos de experiência em gestão de patrimônio pessoal. Faça uma análise profunda e honesta da carteira abaixo. Seja direto — se algo está errado, diga com números concretos.

CONTEXTO DE MERCADO (mai/2026):
- SELIC: ~14,75% a.a. | CDI: ~14,65% a.a. | IPCA 12m: ~5,5% a.a.
- USD/BRL: R$ {m['dollar_rate']}

PATRIMÔNIO (atualizado: {m['last_updated']})
- Investimentos líquidos: R$ {m['portfolio_total']:,.2f}
- FGTS:                   R$ {m['fgts']:,.2f}
- Total com FGTS:         R$ {m['grand_total']:,.2f}
- Número de ativos:       {m['num_assets']}

VALORES POR CLASSE
- RF CDI (pós-fixado):   R$ {m['totals']['RF_CDI']:,.2f}
- RF Pré-fixado:         R$ {m['totals']['RF_PRE']:,.2f}
- RF IPCA+:              R$ {m['totals']['RF_IPCA']:,.2f}
- FII:                   R$ {m['totals']['RV_FII']:,.2f}
- ETF:                   R$ {m['totals']['RV_ETF']:,.2f}
- Ouro:                  R$ {m['totals']['RV_OURO']:,.2f}
- Fundos de Ações:       R$ {m['totals']['RV_FUNDOS']:,.2f}
- Crypto:                R$ {m['totals']['RV_CRYPTO']:,.2f}
- Previdência Privada:   R$ {m['totals']['PREVIDENCIA']:,.2f}

ALOCAÇÃO ATUAL vs IDEAL
{alloc_table}

ALERTAS DE VENCIMENTO (vencidos + próximos 6 meses)
{alerts_str}

PERFORMANCE POR ATIVO (ordenado por ganho %)
{perf_str}

PARÂMETROS DE PROJEÇÃO
- Retorno mensal estimado: {m['proj']['monthlyReturn']*100:.2f}% ({m['proj']['monthlyReturn']*1200:.1f}% a.a.)
- Aporte mensal: R$ {m['proj']['monthlyContribution']:,.0f}

LISTA COMPLETA DE ATIVOS (JSON)
{json.dumps(m['assets'], ensure_ascii=False, indent=2)}

---

Produza um relatório completo em português com estas seções:

## 1. Diagnóstico Geral
Saúde geral da carteira: pontos fortes e problemas críticos. Seja direto.

## 2. Análise de Alocação
Para cada desvio significativo (>3pp): o que significa em R$, impacto no risco/retorno, se é justificável.

## 3. Alertas e Urgências
Ativos vencidos, em prejuízo, concentrações de risco. O que precisa de atenção imediata.

## 4. Análise de Performance
Quais ativos performam bem ou mal e por quê. Comparativo com benchmarks (CDI, IPCA+, IBOV, S&P 500).

## 5. Sugestão de Aporte (R$ {m['proj']['monthlyContribution']:,.0f}/mês)
Onde concentrar o próximo aporte para rebalancear. Seja específico com percentuais e valores.

## 6. Estratégia de Crescimento (próximos 12 meses)
3 a 5 ações concretas considerando vencimentos, rebalanceamento e cenário atual.

## 7. Projeção Patrimonial
Com R$ {m['proj']['monthlyContribution']:,.0f}/mês e {m['proj']['monthlyReturn']*1200:.1f}% a.a., quando atinge R$ 1.000.000?
Mostre 3 cenários: pessimista (-2pp), base, otimista (+2pp).

Use linguagem técnica mas acessível. Números concretos em todo lugar.
"""


def copy_to_clipboard(text):
    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
        return True
    except Exception:
        return False


def main(base=None):
    global BASE
    if base is not None:
        BASE = Path(base)
    data = load_portfolio()
    m = compute(data)
    prompt = build_prompt(m)

    chars = len(prompt)
    tokens_est = chars // 4

    print(f"\nCarteira: {m['last_updated']} | R$ {m['portfolio_total']:,.2f} | {m['num_assets']} ativos")
    print(f"Prompt gerado: ~{tokens_est:,} tokens ({chars:,} caracteres)")

    copied = copy_to_clipboard(prompt)

    if copied:
        print("\nPrompt copiado para o clipboard!")
        print("Abra claude.ai e cole (Cmd+V) numa conversa nova.")
    else:
        # fallback: salva em arquivo
        out = BASE / "analise_prompt.txt"
        out.write_text(prompt, encoding="utf-8")
        print(f"\nNão foi possível copiar. Prompt salvo em: {out}")
        print("Abra o arquivo, selecione tudo e cole no claude.ai.")

    if m["alerts"]:
        vencidos = [a for a in m["alerts"] if a["label"] == "VENCIDO"]
        if vencidos:
            print(f"\n⚠  {len(vencidos)} ativo(s) VENCIDO(S) detectado(s):")
            for a in vencidos:
                print(f"   - {a['name']} (venc. {a['maturity']})")

