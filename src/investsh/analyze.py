"""Gera prompt de análise da carteira e copia pro clipboard. Cole no claude.ai.

O prompt leva os mesmos números das telas do investsh: alocação vs ideal, rentabilidade
(carteira, por classe e por ativo) contra CDI e IPCA, lançamentos dos últimos meses,
vencimentos, renda fixa líquida de IR, reserva de emergência, saldos desatualizados,
avisos do `investsh check` e projeção pela taxa fixa e pela rentabilidade real.
"""

import json
import subprocess
from datetime import date
from pathlib import Path

from . import perf, tax
from .config import DEFAULT_STALE_DAYS
from .core import (GROUP_META, MILESTONES, alloc_investments, brl_fmt, classify, cost_basis,
                   maturity_alerts, milestone_label, parse_maturity, projection,
                   reserva_status, stale_assets)

# Diretório de trabalho (contém data/); o comando `investsh analyze --dir` muda.
BASE = Path.cwd()

# Classes principais da alocação ideal (as subclasses vêm de GROUP_META)
MAIN_IDEAL = {'Renda Fixa': 'rendaFixa', 'Renda Variável': 'rendaVariavel',
              'Multiativo Global': 'multiAtivoGlobal', 'Previdência': 'previdencia'}


def load_portfolio():
    with open(BASE / "data" / "investments.json", encoding="utf-8") as f:
        return json.load(f)


def load_history():
    try:
        with open(BASE / "data" / "history.json", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return []


def benchmarks(history, data, today):
    """(cdi, ipca) do Banco Central (cache de 12 h; sem rede, o cache antigo ou None)."""
    from . import bench
    ps = perf.periods(history, data.get("flows"), data.get("flowsSince"))
    if not ps:
        return None, None
    start = ps[0]["start"]
    return bench.cdi(start, today), bench.ipca(start, today)


def _pct(v, plus=True):
    if v is None:
        return "—"
    return f"{v * 100:+.2f}%" if plus else f"{v * 100:.0f}%"


def _brl(v):
    return brl_fmt(v)


def allocation(data):
    """Linhas (rótulo, saldo, % atual, % ideal) por classe e subclasse, como a aba Alocação."""
    ideal = data.get("idealAllocation", {})
    invs = alloc_investments(data)
    total = sum(i["balance"] for i in invs)
    groups = {}
    for inv in invs:
        main, sub = classify(inv)
        groups.setdefault(main, {}).setdefault(sub, 0.0)
        groups[main][sub] += inv["balance"]
    sub_ideal = {m["label"]: m["ideal"] for m in GROUP_META.values()}
    rows = []
    for main in [*MAIN_IDEAL, "Outros"]:
        if main not in groups:
            continue
        bal = sum(groups[main].values())
        rows.append((main, bal, bal / total * 100 if total else 0, ideal.get(MAIN_IDEAL.get(main))))
        for sub, sb in sorted(groups[main].items(), key=lambda x: -x[1]):
            rows.append((f"  {sub}", sb, sb / total * 100 if total else 0,
                         ideal.get(sub_ideal.get(sub) or "")))
    return rows, total


def compute(data, history=None, today=None, cdi=None, ipca=None):
    history = history or []
    today = today or date.today()
    invs = data["investments"]
    dol = data.get("dollarRate", 1)
    flows, since = data.get("flows") or [], data.get("flowsSince")

    alloc_rows, alloc_total = allocation(data)

    assets = []
    for inv in invs:
        cost = cost_basis(inv, dol)
        assets.append({
            "name": inv["name"], "broker": inv.get("broker", ""), "class": classify(inv)[1],
            "category": inv.get("category"), "balance": round(inv["balance"], 2),
            "invested": round(cost, 2) if cost else None,
            "gain_pct": round((inv["balance"] - cost) / cost * 100, 1) if cost else None,
            "maturity": inv.get("maturity"), "rate": inv.get("rate"),
            "liquidity": inv.get("liquidity"), "usd": "investedUSD" in inv,
        })

    summary = perf.summary(history, cdi, ipca, today, flows, since)
    by_class = perf.breakdown(history, data, cdi, today) if summary else []

    # Vencimentos: por ano (saldo que vence) e os alertas dos próximos 6 meses
    by_year = {}
    for inv in invs:
        due = parse_maturity(inv.get("maturity")) if inv.get("maturity") else None
        if due and inv.get("balance"):
            by_year[due.year] = by_year.get(due.year, 0.0) + inv["balance"]
    alerts = [{"name": a["name"], "maturity": a["date"].isoformat(), "days": a["days"],
               "label": "VENCIDO" if a["days"] < 0 else f"vence em {a['days']}d"}
              for a in maturity_alerts(invs, today, 180)]

    fixed = []
    for inv in invs:
        r = tax.redeem_today(inv, history, today) if inv.get("balance") else None
        if r:
            n = tax.net_rate(inv, history, today)
            rt = inv.get("rate") or {}
            fixed.append({"name": inv["name"], "broker": inv.get("broker", ""),
                          "rate": tax.rate_label(rt["kind"], rt["value"])
                          if isinstance(rt.get("value"), (int, float)) else None,
                          "net_rate": tax.rate_label(*n) if n else None,
                          "gross": r["gross"], "tax": round(r["ir"] + r["iof"], 2), "net": r["net"]})

    params = data.get("projectionParams") or {}
    real = perf.real_monthly_rate(history, flows, since, today) if history else None
    fgts = data.get("fgts", 0)
    ptotal = sum(i["balance"] for i in invs)
    proj = {"fixed": projection(ptotal, fgts, params, params.get("monthlyReturn", 0), today)}
    if real:
        proj["real"] = projection(ptotal, fgts, params, real[0], today)

    from .check import find_problems
    problems = find_problems(data, history, today)

    return {
        "today": today,
        "portfolio_total": round(ptotal, 2),
        "grand_total": round(ptotal + fgts, 2),
        "fgts": fgts,
        "alloc_rows": alloc_rows, "alloc_total": alloc_total,
        "reserve": reserva_status(data),
        "summary": summary, "by_class": by_class,
        "monthly": perf.monthly(history, flows, since)[-12:] if history else [],
        "by_year": dict(sorted(by_year.items())), "alerts": alerts,
        "fixed": fixed,
        "stale": stale_assets(invs, history, today, DEFAULT_STALE_DAYS),
        "problems": problems,
        "params": params, "real": real, "proj": proj,
        "last_updated": data["lastUpdated"],
        "dollar_rate": data["dollarRate"],
        "assets": assets,
        "num_assets": len(invs),
    }


def _alloc_table(m):
    lines = ["Classe                          | Saldo            | Atual  | Ideal  | Desvio",
             "--------------------------------|------------------|--------|--------|-------"]
    for label, bal, pct, ideal in m["alloc_rows"]:
        ideal_s = f"{ideal:5.1f}%" if ideal else "    — "
        dev_s = f"{pct - ideal:+.1f}pp" if ideal else "—"
        lines.append(f"{label:<32}| {_brl(bal):>16} | {pct:5.1f}% | {ideal_s} | {dev_s}")
    return "\n".join(lines)


def _perf_section(m):
    s = m["summary"]
    if not s:
        return "  Sem histórico suficiente (precisa de dois saves com aporte conhecido)."
    st = s["since_start"]
    out = ["Período                       | Carteira | CDI      | IPCA     | % do CDI",
           "------------------------------|----------|----------|----------|---------"]

    def line(label, row):
        ipca = _pct(row["ipca"]) + ("*" if not row["ipca_complete"] else "")
        return (f"{label:<30}| {_pct(row['portfolio']):>8} | {_pct(row['cdi']):>8} | "
                f"{ipca:>8} | {_pct(row['pct_cdi'], plus=False):>7}")

    out.append(line(f"Desde {st['start']:%d/%m/%Y} ({(st['end'] - st['start']).days} dias)", st))
    if s["last_12m"] and s["last_12m"]["start"] != st["start"]:
        out.append(line("Últimos 12 meses", s["last_12m"]))
    for r in reversed(s["months"][-12:]):
        out.append(line(f"{perf.MESES[r['month']]}/{r['year']}", r))
    out.append("(* IPCA de meses ainda não divulgados fica de fora; — = indisponível ou período curto)")
    return "\n".join(out)


def _class_section(m):
    if not m["by_class"]:
        return "  Sem dados por ativo (precisa dos lançamentos registrados: flowsSince)."
    out = []
    for c in m["by_class"]:
        r = c["row"]
        out.append(f"- {c['label']}: {_pct(r['portfolio'])} (CDI {_pct(r['cdi'])}, "
                   f"{_pct(r['pct_cdi'], plus=False)} do CDI)")
        for a in c["assets"]:
            ar = a["row"]
            out.append(f"    - {a['name']} ({a['broker']}), desde {ar['start']:%d/%m/%Y}: "
                       f"{_pct(ar['portfolio'])} (CDI {_pct(ar['cdi'])}, "
                       f"{_pct(ar['pct_cdi'], plus=False)} do CDI)")
    return "\n".join(out)


def _flows_section(m):
    rows = [r for r in m["monthly"] if r["has_flows"]]
    if not rows:
        return "  Sem lançamentos registrados."
    out = ["Mês     | Saldo final      | Aportes      | Saques       | Proventos    | Valorização",
           "--------|------------------|--------------|--------------|--------------|-------------"]
    for r in rows:
        out.append(f"{r['month']} | {_brl(r['total']):>16} | {_brl(r['contributions']):>12} | "
                   f"{_brl(r['withdrawals']):>12} | {_brl(r['dividends']):>12} | {_brl(r['gain']):>12}")
    return "\n".join(out)


def _fixed_section(m):
    if not m["fixed"]:
        return "  Nenhum título de renda fixa com custo conhecido."
    out = []
    for f in m["fixed"]:
        rate = f" | taxa {f['rate']}" if f["rate"] else ""
        if f["rate"] and f["net_rate"]:
            rate += f" (líquida de IR no vencimento: {f['net_rate']})"
        out.append(f"- {f['name']} ({f['broker']}){rate}: bruto {_brl(f['gross'])}, "
                   f"IR+IOF {_brl(f['tax'])}, líquido {_brl(f['net'])}")
    return "\n".join(out)


def _maturity_section(m):
    years = "\n".join(f"- {y}: {_brl(v)}" for y, v in m["by_year"].items()) or "  Nenhum."
    alerts = "\n".join(f"- {a['name']}: {a['label']} (venc. {a['maturity']})"
                       for a in m["alerts"]) or "  Nenhum."
    return f"Saldo que vence por ano:\n{years}\n\nVencidos e próximos 6 meses:\n{alerts}"


def _quality_section(m):
    out = []
    for s in m["stale"]:
        out.append(f"- {s['name']} ({s['broker']}): saldo sem atualização há {s['days']} dias")
    for p in m["problems"]:
        if "sem atualização" in p["message"]:
            continue    # já listado acima
        out.append(f"- [{p['level']}] {p['where']}: {p['message']}")
    return "\n".join(out) or "  Nenhum problema encontrado."


def _projection_section(m):
    p, real = m["params"], m["real"]
    mr = p.get("monthlyReturn", 0)
    cols = [("Taxa fixa", mr, m["proj"]["fixed"])]
    if real:
        cols.append(("Real 12m", real[0], m["proj"]["real"]))
    out = [f"Aporte mensal: {_brl(p.get('monthlyContribution', 0))}"]
    for label, rate, _ in cols:
        out.append(f"- {label}: {rate * 100:.2f}% a.m. ({((1 + rate) ** 12 - 1) * 100:.1f}% a.a.)")
    if not real:
        out.append(f"- Real: indisponível (precisa de {perf.MIN_DAYS_REAL_RATE} dias de histórico)")
    out.append("")
    out.append("Meta        | " + " | ".join(f"{label} c/ FGTS | {label} s/ FGTS" for label, _, _ in cols))
    for ms in MILESTONES:
        cells = []
        for _, _, (com, sem) in cols:
            for hit in (com.get(ms), sem.get(ms)):
                cells.append(f"{hit[0]} ({hit[1]}m)" if hit else "—")
        out.append(f"{milestone_label(ms):<11} | " + " | ".join(cells))
    return "\n".join(out)


def build_prompt(m):
    rs = m["reserve"]
    reserve = (f"{_brl(rs[0])} (mín {_brl(rs[1])}, meta {_brl(rs[2])}, máx {_brl(rs[3])}): {rs[4]}"
               if rs else "não configurada")
    contribution = m["params"].get("monthlyContribution", 0)

    return f"""Você é um analista sênior de investimentos brasileiro com 20 anos de experiência em gestão de patrimônio pessoal. Faça uma análise profunda e honesta da carteira abaixo. Seja direto — se algo está errado, diga com números concretos.

Data da análise: {m['today']:%d/%m/%Y}. Use o cenário de mercado atual que você conhecer (Selic, CDI, IPCA, câmbio); o CDI e o IPCA históricos abaixo são do Banco Central.

PATRIMÔNIO (atualizado: {m['last_updated']})
- Investimentos:   {_brl(m['portfolio_total'])}
- FGTS:            {_brl(m['fgts'])}
- Total com FGTS:  {_brl(m['grand_total'])}
- Ativos:          {m['num_assets']}
- USD/BRL:         {m['dollar_rate']}
- Reserva de emergência: {reserve}

ALOCAÇÃO ATUAL vs IDEAL (sem a reserva de emergência; base {_brl(m['alloc_total'])})
{_alloc_table(m)}

RENTABILIDADE DA CARTEIRA (descontando aportes, método de Dietz modificado)
{_perf_section(m)}

RENTABILIDADE POR CLASSE E POR ATIVO (últimos 12 meses)
{_class_section(m)}

APORTES, SAQUES E PROVENTOS (por mês)
{_flows_section(m)}

VENCIMENTOS
{_maturity_section(m)}

RENDA FIXA: RESGATE HOJE, LÍQUIDO DE IR E IOF
{_fixed_section(m)}

QUALIDADE DOS DADOS (avisos do investsh)
{_quality_section(m)}

PROJEÇÃO PATRIMONIAL
{_projection_section(m)}

LISTA COMPLETA DE ATIVOS (JSON; invested = custo base em R$, gain_pct = ganho sobre o custo)
{json.dumps(m['assets'], ensure_ascii=False, indent=2)}

---

Produza um relatório completo em português com estas seções:

## 1. Diagnóstico Geral
Saúde geral da carteira: pontos fortes e problemas críticos. Seja direto.

## 2. Análise de Alocação
Para cada desvio significativo (>3pp): o que significa em R$, impacto no risco/retorno, se é justificável.

## 3. Alertas e Urgências
Ativos vencidos ou vencendo, em prejuízo, concentrações de risco (inclusive por emissor e limite do FGC), dados que parecem errados. O que precisa de atenção imediata.

## 4. Análise de Performance
Carteira vs CDI e IPCA. Quais classes e ativos puxam para cima ou para baixo e por quê; compare com benchmarks (CDI, IPCA+, IBOV, S&P 500).

## 5. Sugestão de Aporte ({_brl(contribution)}/mês)
Onde concentrar o próximo aporte para rebalancear. Seja específico com percentuais e valores.

## 6. Estratégia de Crescimento (próximos 12 meses)
3 a 5 ações concretas considerando vencimentos (reinvestimento e IR), rebalanceamento e cenário atual.

## 7. Projeção Patrimonial
Comente a projeção pela taxa fixa e pela rentabilidade real. A taxa fixa é realista? Mostre 3 cenários para chegar a R$ 1.000.000: pessimista, base e otimista.

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
    history = load_history()
    today = date.today()
    cdi, ipca = benchmarks(history, data, today)
    m = compute(data, history, today, cdi, ipca)
    prompt = build_prompt(m)

    chars = len(prompt)
    tokens_est = chars // 4

    print(f"\nCarteira: {m['last_updated']} | R$ {m['portfolio_total']:,.2f} | {m['num_assets']} ativos")
    print(f"Prompt gerado: ~{tokens_est:,} tokens ({chars:,} caracteres)")
    if m["summary"] and (cdi is None or ipca is None):
        print("CDI/IPCA indisponíveis (sem conexão com o Banco Central e sem cache): "
              "a rentabilidade vai sem a comparação")

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
