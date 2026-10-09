"""Rentabilidade descontando aportes, comparação com CDI/IPCA e alertas de vencimento."""
from datetime import date

import pytest

from investsh import core, perf


def snap(d, total, invested=None, usd=None, rate=None):
    s = {'date': d, 'total': total}
    if invested is not None:
        s['totalInvested'] = invested
    if usd is not None:
        s['totalInvestedUSD'] = usd
        s['dollarRate'] = rate
    return s


# ── Períodos entre fotos ─────────────────────────────────────────────────────

def test_period_without_flow():
    [p] = perf.periods([snap('2026-01-01', 1000, 1000), snap('2026-02-01', 1010, 1000)])
    assert p['start'] == date(2026, 1, 1) and p['end'] == date(2026, 2, 1)
    assert p['flow'] == 0
    assert p['r'] == pytest.approx(0.01)


def test_period_with_contribution_uses_modified_dietz():
    # aporte de 100 no período: ganho real = 1110 - 1000 - 100 = 10, sobre 1000 + 100/2
    [p] = perf.periods([snap('2026-01-01', 1000, 1000), snap('2026-02-01', 1110, 1100)])
    assert p['flow'] == 100
    assert p['r'] == pytest.approx(10 / 1050)


def test_dollar_move_is_not_a_contribution():
    # custo: R$ 1000 + US$ 100. Dólar 5,00 → 5,50 sem aporte: o custo em R$ sobe 50,
    # mas isso é câmbio, não aporte. Saldo 1500 → 1560: rendeu 60 sobre 1500 = 4%.
    p0 = snap('2026-01-01', 1500, 1000 + 100 * 5.0, usd=100, rate=5.0)
    p1 = snap('2026-02-01', 1560, 1000 + 100 * 5.5, usd=100, rate=5.5)
    [p] = perf.periods([p0, p1])
    assert p['flow'] == pytest.approx(0)
    assert p['r'] == pytest.approx(0.04)


def test_snapshots_without_invested_are_skipped():
    hist = [snap('2026-01-01', 900), snap('2026-01-15', 1000, 1000), snap('2026-02-01', 1010, 1000)]
    assert [p['start'] for p in perf.periods(hist)] == [date(2026, 1, 15)]


def test_same_day_snapshots_are_ignored():
    hist = [snap('2026-01-01', 1000, 1000), snap('2026-01-01', 1005, 1000), snap('2026-02-01', 1010, 1000)]
    [p] = perf.periods(hist)
    assert p['r'] == pytest.approx(1010 / 1005 - 1)


# ── Indicadores no mesmo período ─────────────────────────────────────────────

def test_cdi_compounds_business_days_in_period():
    cdi = {date(2026, 1, 1): 0.05, date(2026, 1, 2): 0.05, date(2026, 1, 5): 0.04}
    # período (01/01, 05/01]: 02/01 e 05/01 contam; 01/01 não
    assert perf.cdi_return(cdi, date(2026, 1, 1), date(2026, 1, 5)) == pytest.approx(1.0005 * 1.0004 - 1)


def test_ipca_is_prorated_by_calendar_days():
    ipca = {(2026, 1): 0.31, (2026, 2): 0.50}
    # 30 dias de janeiro (02 a 31) e 1 dia de fevereiro
    expected = 1.0031 ** (30 / 31) * 1.005 ** (1 / 28) - 1
    value, complete = perf.ipca_return(ipca, date(2026, 1, 1), date(2026, 2, 1))
    assert complete and value == pytest.approx(expected)


def test_ipca_missing_month_is_marked_incomplete():
    value, complete = perf.ipca_return({(2026, 1): 0.31}, date(2026, 1, 15), date(2026, 2, 10))
    assert not complete
    assert value == pytest.approx(1.0031 ** (16 / 31) - 1)   # só o que há de janeiro


# ── Resumo: meses, 12 meses, desde o início ──────────────────────────────────

def test_summary_rows():
    hist = [snap('2025-12-01', 1000, 1000), snap('2026-01-01', 1010, 1000),
            snap('2026-01-15', 1120, 1100), snap('2026-02-01', 1130, 1100)]
    cdi = {date(2025, 12, d): 0.04 for d in range(2, 32)}
    cdi.update({date(2026, 1, d): 0.05 for d in range(1, 32)})
    cdi.update({date(2026, 2, 1): 0.05})
    ipca = {(2025, 12): 0.5, (2026, 1): 0.3, (2026, 2): 0.4}
    s = perf.summary(hist, cdi, ipca, today=date(2026, 2, 3))

    r1 = 1010 / 1000 - 1                     # 01/12→01/01: meio em dezembro
    r2 = (1120 - 1010 - 100) / (1010 + 50)   # 01/01→15/01: meio em janeiro
    r3 = 1130 / 1120 - 1                     # 15/01→01/02: meio em janeiro
    months = {(m['year'], m['month']): m for m in s['months']}
    assert set(months) == {(2025, 12), (2026, 1)}
    assert months[(2025, 12)]['portfolio'] == pytest.approx(r1)
    assert months[(2026, 1)]['portfolio'] == pytest.approx((1 + r2) * (1 + r3) - 1)
    assert s['since_start']['portfolio'] == pytest.approx((1 + r1) * (1 + r2) * (1 + r3) - 1)
    assert s['since_start']['start'] == date(2025, 12, 1)
    assert s['since_start']['cdi'] == pytest.approx(1.0004 ** 30 * 1.0005 ** 32 - 1)
    jan = months[(2026, 1)]
    assert jan['pct_cdi'] == pytest.approx(jan['portfolio'] / jan['cdi'])


def test_summary_twelve_months_window():
    hist = [snap('2024-06-01', 1000, 1000), snap('2025-01-01', 1100, 1000), snap('2026-01-01', 1210, 1000)]
    s = perf.summary(hist, {}, {}, today=date(2026, 1, 10))
    # só o período que termina dentro dos últimos 12 meses entra
    assert s['last_12m']['portfolio'] == pytest.approx(0.10)
    assert s['last_12m']['start'] == date(2025, 1, 1)
    assert s['since_start']['portfolio'] == pytest.approx(0.21)


def test_summary_without_enough_history():
    s = perf.summary([snap('2026-01-01', 1000, 1000)], {}, {}, today=date(2026, 1, 2))
    assert s is None


def test_ipca_with_no_published_month_is_none():
    assert perf.ipca_return({}, date(2026, 9, 1), date(2026, 10, 1)) == (None, False)


def test_summary_without_benchmarks():
    hist = [snap('2026-01-01', 1000, 1000), snap('2026-02-01', 1010, 1000)]
    s = perf.summary(hist, None, None, today=date(2026, 2, 2))
    assert s['since_start']['portfolio'] == pytest.approx(0.01)
    assert s['since_start']['cdi'] is None and s['since_start']['pct_cdi'] is None


def test_history_snapshot_records_fx_basis():
    data = {'lastUpdated': '2026-10-06', 'fgts': 0, 'dollarRate': 5.0, 'investments': [
        {'name': 'A', 'invested': 100.0, 'balance': 100.0},
        {'name': 'B', 'investedUSD': 10.0, 'balance': 60.0}]}
    s = core.history_snapshot(data, 160.0)
    assert s['totalInvested'] == 150.0
    assert s['totalInvestedUSD'] == 10.0
    assert s['dollarRate'] == 5.0


# ── Vencimentos ──────────────────────────────────────────────────────────────

def test_maturity_alerts():
    invs = [
        {'name': 'Vence logo', 'maturity': '2026-10-20', 'balance': 100.0},
        {'name': 'Venceu', 'maturity': '2026-10-01', 'balance': 50.0},
        {'name': 'Venceu e foi resgatado', 'maturity': '2026-09-01', 'balance': 0.0},
        {'name': 'Longe', 'maturity': '2027-06-01', 'balance': 10.0},
        {'name': 'Formato BR', 'maturity': '15/12/2026', 'balance': 10.0},
        {'name': 'Sem data', 'maturity': None, 'balance': 10.0},
        {'name': 'Inválida', 'maturity': 'em breve', 'balance': 10.0},
    ]
    alerts = core.maturity_alerts(invs, today=date(2026, 10, 6), days=90)
    assert [(a['name'], a['days']) for a in alerts] == [
        ('Venceu', -5), ('Vence logo', 14), ('Formato BR', 70)]
    assert alerts[0]['date'] == date(2026, 10, 1)


# ── % do CDI só em períodos de 28 dias ou mais ───────────────────────────────

def test_pct_cdi_hidden_for_short_periods():
    hist = [snap('2026-10-01', 1000, 1000), snap('2026-10-07', 984, 1000)]
    cdi = {date(2026, 10, d): 0.05 for d in range(2, 8)}
    s = perf.summary(hist, cdi, None, today=date(2026, 10, 8))
    row = s['since_start']
    assert row['portfolio'] == pytest.approx(-0.016) and row['cdi'] > 0
    assert row['pct_cdi'] is None          # 6 dias: razão sem significado (seria ~-500%)


@pytest.mark.parametrize('end, shown', [('2026-02-28', False), ('2026-03-01', True)])
def test_pct_cdi_minimum_days(end, shown):
    # 01/02 → 28/02 = 27 dias (oculto); 01/02 → 01/03 = 28 dias (mostrado)
    hist = [snap('2026-02-01', 1000, 1000), snap(end, 1010, 1000)]
    cdi = {date(2026, 2, d): 0.05 for d in range(2, 29)}
    cdi[date(2026, 3, 1)] = 0.05
    row = perf.summary(hist, cdi, None, today=date(2026, 3, 2))['since_start']
    assert (row['pct_cdi'] is not None) is shown


# ── Histórico mensal: variação = aportes + saques + valorização ──────────────

def test_monthly_breakdown():
    hist = [
        snap('2026-01-20', 1000, 1000),
        snap('2026-02-05', 1300, 1300),   # aporte 300, sem rendimento
        snap('2026-02-20', 1110, 1100),   # saque 200; rendimento 10
        snap('2026-03-20', 1120, 1100),   # rendimento 10
    ]
    rows = {r['month']: r for r in perf.monthly(hist)}
    jan, feb, mar = rows['2026-01'], rows['2026-02'], rows['2026-03']
    assert jan['total'] == 1000 and jan['change'] is None and not jan['has_flows']
    assert feb['total'] == 1110 and feb['change'] == 110
    assert feb['contributions'] == 300 and feb['withdrawals'] == -200
    assert feb['gain'] == pytest.approx(10)
    assert feb['change'] == pytest.approx(feb['contributions'] + feb['withdrawals'] + feb['gain'])
    assert feb['r'] == pytest.approx((1 + 0) * (1 + 10 / (1300 - 100)) - 1)
    assert mar['contributions'] == 0 and mar['withdrawals'] == 0 and mar['gain'] == pytest.approx(10)


def test_monthly_dollar_move_is_gain_not_withdrawal():
    hist = [snap('2026-09-14', 1500, 1000 + 100 * 5.0, usd=100, rate=5.0),
            snap('2026-10-07', 1450, 1000 + 100 * 4.5, usd=100, rate=4.5)]
    oct_ = perf.monthly(hist)[-1]
    assert oct_['contributions'] == 0 and oct_['withdrawals'] == 0
    assert oct_['gain'] == pytest.approx(-50)       # perda com o dólar é rendimento negativo


def test_monthly_without_cost_basis_shows_only_change():
    hist = [snap('2026-07-15', 1000), snap('2026-08-15', 1050), snap('2026-09-14', 1100, 1050),
            snap('2026-10-07', 1110, 1050)]
    rows = {r['month']: r for r in perf.monthly(hist)}
    assert rows['2026-08']['change'] == 50 and not rows['2026-08']['has_flows']
    assert rows['2026-08']['r'] is None
    # setembro: o save anterior (agosto) não tem custo → sem decomposição
    assert rows['2026-09']['change'] == 50 and not rows['2026-09']['has_flows']
    assert rows['2026-10']['has_flows'] and rows['2026-10']['gain'] == pytest.approx(10)


def test_monthly_uses_last_save_of_each_month():
    hist = [snap('2026-01-05', 1000, 1000), snap('2026-01-25', 1020, 1000), snap('2026-02-10', 1030, 1000)]
    rows = perf.monthly(hist)
    assert [r['month'] for r in rows] == ['2026-01', '2026-02']
    assert rows[0]['total'] == 1020 and rows[1]['change'] == 10


def test_invalid_dates_are_ignored():
    hist = [snap('2026-01-01', 1000, 1000), snap('2026-13-01', 5000, 1000), snap(None, 1, 1),
            snap('2026-02-01', 1010, 1000)]
    assert [r['month'] for r in perf.monthly(hist)] == ['2026-01', '2026-02']
    assert perf.periods(hist)[0]['r'] == pytest.approx(0.01)


# ── Lançamentos de aporte/saque (flows) ──────────────────────────────────────

def flow(d, amount):
    return {'date': d, 'name': 'X', 'broker': 'XP', 'amount': amount}


def test_explicit_flows_replace_cost_basis():
    # Sem total investido nas fotos: a partir de flowsSince valem os lançamentos
    hist = [snap('2026-01-01', 1000), snap('2026-02-01', 1110)]
    [p] = perf.periods(hist, [flow('2026-01-15', 100)], since='2026-01-01')
    assert p['flow'] == 100 and p['inflow'] == 100 and p['outflow'] == 0
    assert p['r'] == pytest.approx(10 / 1050)


def test_withdrawal_counts_the_cash_not_the_cost_share():
    # Saque de 1000 de um ativo com saldo 1100 e custo 1000: o custo cai só 909,09.
    # Pelo custo, sobravam 90,91 de "perda"; pelo lançamento, o rendimento é zero.
    hist = [snap('2026-01-01', 1100, 1000), snap('2026-02-01', 100, 1000 * (1 - 1000 / 1100))]
    [by_cost] = perf.periods(hist)
    assert by_cost['r'] < -0.1
    [p] = perf.periods(hist, [flow('2026-01-20', -1000)], since='2026-01-01')
    assert p['flow'] == -1000 and p['r'] == pytest.approx(0)


def test_flow_on_snapshot_day_belongs_to_that_snapshot():
    # Aporte e save no mesmo dia: o aporte já está na foto de 01/02
    hist = [snap('2026-01-01', 1000), snap('2026-02-01', 1100), snap('2026-03-01', 1110)]
    p1, p2 = perf.periods(hist, [flow('2026-02-01', 100)], since='2026-01-01')
    assert p1['flow'] == 100 and p2['flow'] == 0


def test_cost_basis_before_flows_since():
    # Até flowsSince: variação do total investido; depois: lançamentos
    hist = [snap('2026-01-01', 1000, 1000), snap('2026-02-01', 1110, 1100),
            snap('2026-03-01', 1300, 1100)]
    flows = [flow('2026-01-10', 999), flow('2026-02-10', 180)]   # o de janeiro é ignorado
    p1, p2 = perf.periods(hist, flows, since='2026-02-01')
    assert p1['flow'] == 100 and p2['flow'] == 180


def test_monthly_shows_gross_contributions_and_withdrawals():
    # Transferência registrada como saque + aporte: aparecem os dois, a valorização não muda
    hist = [snap('2026-01-31', 1000), snap('2026-02-28', 1010)]
    flows = [flow('2026-02-10', -300), flow('2026-02-10', 300)]
    [_, feb] = perf.monthly(hist, flows, since='2026-01-31')
    assert feb['contributions'] == 300 and feb['withdrawals'] == -300
    assert feb['gain'] == pytest.approx(10) and feb['r'] == pytest.approx(0.01)


def test_invalid_flows_are_ignored():
    hist = [snap('2026-01-01', 1000), snap('2026-02-01', 1010)]
    flows = [flow('2026-13-01', 50), {'date': '2026-01-10', 'amount': 'x'}, {}]
    [p] = perf.periods(hist, flows, since='2026-01-01')
    assert p['flow'] == 0


def test_record_flow_and_start_flow_log():
    data = {'investments': [], 'lastUpdated': '2026-10-06'}
    core.record_flow(data, {'name': 'SGOV', 'broker': 'Nomad'}, -271.6051, usd=-50)
    assert data['flows'] == [{'date': date.today().isoformat(), 'name': 'SGOV', 'broker': 'Nomad',
                              'amount': -271.61, 'usd': -50}]
    core.start_flow_log(data)
    assert data['flowsSince'] == '2026-10-06'
    data['lastUpdated'] = '2026-11-01'
    core.start_flow_log(data)
    assert data['flowsSince'] == '2026-10-06'      # não avança depois de iniciado


def test_dividends_paid_out_count_as_return():
    # FII de 1000 paga 10 de provento: o saldo cai para 990, mas rendeu 0 (não -1%)
    hist = [snap('2026-01-01', 1000), snap('2026-02-01', 990)]
    prov = [{'date': '2026-01-15', 'amount': -10, 'kind': 'provento'}]
    [p] = perf.periods(hist, prov, since='2026-01-01')
    assert p['dividends'] == -10 and p['outflow'] == 0 and p['r'] == pytest.approx(0, abs=1e-12)
    [_, feb] = perf.monthly(hist, prov, since='2026-01-01')
    assert feb['dividends'] == -10 and feb['withdrawals'] == 0 and feb['gain'] == pytest.approx(0)


def test_record_flow_kind():
    data = {'investments': []}
    core.record_flow(data, {'name': 'KNRI11', 'broker': 'XP'}, -68.2, kind='provento')
    assert data['flows'][0]['kind'] == 'provento' and data['flows'][0]['amount'] == -68.2
