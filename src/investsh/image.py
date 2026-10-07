"""Imagem de resumo da carteira (assets/status.png), via matplotlib."""
import json, os
from datetime import datetime

from . import config
from .term import G, Y, RST
from .core import (
    BROKER_ORDER, sort_key, GROUP_META, classify, alloc_investments, monthly_summary,
    broker_monthly_series, brl_fmt,
)


def generate_status_image(data):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec
        import math
    except ImportError:
        print(f'{Y}  pip install matplotlib  →  necessário para imagem{RST}')
        return

    invs  = data['investments']
    total = sum(i['balance'] for i in invs)
    prev  = sum(i.get('previousBalance', i['balance']) for i in invs)
    delta = total - prev
    dpct  = (delta / prev * 100) if prev > 0 else 0
    fgts  = data.get('fgts', 0)
    date  = data.get('lastUpdated', '')
    dolar = data.get('dollarRate', 1)
    sign  = '+' if delta >= 0 else ''

    def alloc_main(inv):
        grp = inv.get('allocationGroup')
        if grp == 'RV_CRYPTO': return 'Crypto'
        meta = GROUP_META.get(grp)
        return meta['main'] if meta else 'Renda Fixa'

    main_alloc = {}
    for i in alloc_investments(data):
        k = alloc_main(i)
        main_alloc[k] = main_alloc.get(k, 0) + i['balance']
    main_alloc  = dict(sorted(main_alloc.items(), key=lambda x: -x[1]))
    alloc_total = sum(main_alloc.values())

    broker_agg = {}
    for i in invs:
        b = i.get('broker', '?')
        broker_agg[b] = broker_agg.get(b, 0) + i['balance']
    broker_agg = dict(sorted(broker_agg.items(), key=lambda x: x[1]))

    hist_path = os.path.join(config.ROOT, 'data', 'history.json')
    try:
        with open(hist_path, encoding='utf-8') as f:
            history = json.load(f)
    except FileNotFoundError:
        history = []
    monthly    = monthly_summary(history) if history else []
    evo_dates  = [m.get('date', '') for m in monthly[-12:]]
    evo_totals = [m.get('total', 0) for m in monthly[-12:]]

    aportes_now, valorizacao_now = None, None
    if len(monthly) >= 2 and 'totalInvested' in monthly[-1] and 'totalInvested' in monthly[-2]:
        aportes_now     = monthly[-1]['totalInvested'] - monthly[-2]['totalInvested']
        valorizacao_now = delta - aportes_now

    broker_order = sorted(broker_agg.keys(), key=lambda b: BROKER_ORDER.get(b, 99))
    _, broker_series = broker_monthly_series(broker_order)

    def mmyy(d):
        try:
            return datetime.strptime(d, '%Y-%m-%d').strftime('%m/%y')
        except (ValueError, TypeError):
            return d[5:7] + '/' + d[2:4] if len(d) >= 7 else d

    ALLOC_C = {'Renda Fixa':'#3b82f6','Renda Variável':'#0dcea8','Multiativo Global':'#c084fc',
               'Previdência':'#a78bfa','Crypto':'#f59e0b'}
    BR_C    = {'XP':'#3b82f6','Nubank':'#9333ea','Nomad':'#22d3ee','Binance':'#f59e0b'}

    bg    = '#080d1a'
    surf  = '#0f1729'
    textc = '#e8edf5'
    dim   = '#4d6a8a'
    green = '#0dcea8'
    red   = '#f43f5e'
    dcol  = green if delta >= 0 else red

    # Build asset-table rows up front so we can size the figure to fit content.
    rows = []   # (broker, inv_or_None, is_header)
    for broker in sorted(set(i.get('broker','') for i in invs),
                         key=lambda b: BROKER_ORDER.get(b, 99)):
        broker_invs = [i for i in sorted(invs, key=sort_key)
                       if i.get('broker') == broker]
        if not broker_invs:
            continue
        broker_total = sum(i['balance'] for i in broker_invs)
        rows.append(('header', broker, broker_total))
        for inv in broker_invs:
            rows.append(('asset', inv, None))

    n_rows  = len(rows)
    font_sz = max(6.5, min(9.5, 9.5 - max(0, n_rows - 25) * 0.05))

    # ── Portrait layout sized for phone screens ─────────────────────────────
    show_broker_evo = len(evo_dates) >= 2 and len(broker_order) >= 2

    W = 9.0
    h_stats      = 1.75
    h_evo        = 2.15 if len(evo_totals) >= 2 else 0.95
    h_donut      = 1.75 + 0.24 * len(main_alloc)
    h_broker     = 0.75 + 0.34 * max(1, len(broker_agg))
    h_broker_evo = (2.15 if show_broker_evo else 0.95)
    h_table      = 0.65 + 0.225 * (n_rows + 1)
    H = h_stats + h_evo + h_donut + h_broker + h_broker_evo + h_table + 0.3

    fig = plt.figure(figsize=(W, H), facecolor=bg, dpi=130)
    gs  = GridSpec(6, 1, figure=fig,
                   left=0.03, right=0.97, top=0.995, bottom=0.005,
                   hspace=0.14,
                   height_ratios=[h_stats, h_evo, h_donut, h_broker, h_broker_evo, h_table])

    # ── Panel 1: Stats ────────────────────────────────────────────────────────
    ax0 = fig.add_subplot(gs[0, 0])
    ax0.set_facecolor(surf)
    ax0.set_xlim(0, 1); ax0.set_ylim(0, 1)
    ax0.axis('off')

    pad = 0.035
    ax0.text(pad, 0.90, 'investsh', color=textc, fontsize=17,
             fontweight='bold', va='top')
    ax0.text(1 - pad, 0.90, date, color=dim, fontsize=10.5, va='top', ha='right')
    ax0.axhline(0.76, xmin=0.02, xmax=0.98, color=dim, linewidth=0.4, alpha=0.4)

    ax0.text(pad, 0.66, 'Patrimônio', color=dim, fontsize=9.5, va='top')
    ax0.text(pad, 0.56, brl_fmt(total), color=textc, fontsize=23,
             fontweight='bold', va='top', family='monospace')
    ax0.text(pad, 0.28, f'{sign}{brl_fmt(delta)}  ({sign}{dpct:.2f}%)', color=dcol,
             fontsize=12, va='top')
    if valorizacao_now is not None:
        vzs = '+' if valorizacao_now >= 0 else ''
        aps = '+' if aportes_now     >= 0 else ''
        ax0.text(pad, 0.16, f'Valoriz. {vzs}{brl_fmt(valorizacao_now)}  ·  Aportes {aps}{brl_fmt(aportes_now)}'
                 .replace('$', r'\$'),  # dois "R$" viram mathtext sem escape
                 color=dim, fontsize=8.3, va='top')
    else:
        ax0.text(pad, 0.16, 'vs última atualização', color=dim, fontsize=9, va='top')

    col2 = 0.58
    ax0.text(col2, 0.66, 'c/ FGTS', color=dim, fontsize=9.5, va='top')
    ax0.text(col2, 0.56, brl_fmt(total + fgts), color=textc, fontsize=15,
             fontweight='600', va='top', family='monospace')
    ax0.text(col2, 0.28, f'{len(invs)} ativos', color=dim, fontsize=11, va='top')
    ax0.text(col2, 0.16, f'FGTS: {brl_fmt(fgts)}', color=dim, fontsize=11, va='top')

    # ── Panel 2: Evolução patrimonial ───────────────────────────────────────
    ax1e = fig.add_subplot(gs[1, 0])
    ax1e.set_facecolor(bg)

    if len(evo_totals) >= 2:
        xs = list(range(len(evo_totals)))
        ax1e.plot(xs, evo_totals, color=green, linewidth=2, marker='o', markersize=3.5,
                  markerfacecolor=green, markeredgecolor=bg, zorder=3)
        ax1e.fill_between(xs, evo_totals, min(evo_totals) * 0.98, color=green, alpha=0.10)
        ax1e.set_xticks(xs)
        ax1e.set_xticklabels([mmyy(d) for d in evo_dates], color=dim, fontsize=8.5)
        ax1e.tick_params(axis='y', colors=dim, labelsize=8.5, length=0)
        for sp in ax1e.spines.values():
            sp.set_visible(False)
        ax1e.grid(axis='y', color=dim, alpha=0.15, linewidth=0.5)
        ax1e.margins(x=0.03, y=0.18)
        last = evo_totals[-1]
        ax1e.annotate(brl_fmt(last), (xs[-1], last), textcoords='offset points',
                      xytext=(0, 8), ha='right', color=green, fontsize=9.5, fontweight='bold')
    else:
        ax1e.axis('off')
        ax1e.text(0.5, 0.5, 'Histórico insuficiente para gráfico de evolução',
                  color=dim, fontsize=10, ha='center', va='center')

    ax1e.set_title('Evolução Patrimonial', color=dim, fontsize=10.5, pad=6, loc='left')

    # ── Panel 3: Donut ────────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[2, 0])
    ax1.set_facecolor(bg)

    labels  = list(main_alloc.keys())
    sizes   = list(main_alloc.values())
    colors1 = [ALLOC_C.get(l, '#888') for l in labels]

    cy, radius = 0.40, 0.70
    if alloc_total <= 0:
        # Carteira vazia (ou só saldos zerados): pie() não aceita fatias zeradas
        ax1.axis('off')
        ax1.text(0.5, 0.5, 'Sem saldo para mostrar a alocação',
                 color=dim, fontsize=10, ha='center', va='center')
        wedges, sizes, main_alloc = [], [], {}
    else:
        wedges, _ = ax1.pie(sizes, colors=colors1, startangle=90, radius=radius,
                            center=(0, cy),
                            wedgeprops=dict(width=0.52, edgecolor=bg, linewidth=2.5))
        ax1.set_aspect('equal')

    for wedge, val in zip(wedges, sizes):
        pct = val / alloc_total * 100
        if pct < 3:
            continue   # avoid label clutter on tiny slices
        angle = math.radians((wedge.theta2 + wedge.theta1) / 2)
        r = radius * 0.72
        ax1.text(r * math.cos(angle), cy + r * math.sin(angle),
                 f'{pct:.0f}%', ha='center', va='center',
                 fontsize=10.5, color=textc, fontweight='bold')

    n_leg      = len(main_alloc)
    legend_top = cy - radius - 0.28
    for i, (lbl, val) in enumerate(main_alloc.items()):
        y = legend_top - i * 0.24
        ax1.plot([-0.95], [y], 's', color=colors1[i], markersize=7)
        ax1.text(-0.86, y, f'{lbl}    {val/alloc_total*100:.1f}%', color=colors1[i],
                 fontsize=10, va='center', ha='left', fontweight='bold')

    if alloc_total > 0:
        ax1.set_xlim(-1.1, 1.1)
        ax1.set_ylim(legend_top - n_leg * 0.24 - 0.05, cy + radius + 0.15)
    ax1.set_title('Alocação', color=dim, fontsize=10.5, pad=4, loc='left')

    # ── Panel 4: Broker bars ──────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[3, 0])
    ax2.set_facecolor(bg)

    bnames  = list(broker_agg.keys())
    bvals   = list(broker_agg.values())
    bcolors = [BR_C.get(b, '#888') for b in bnames]

    bars    = ax2.barh(bnames, bvals, color=bcolors, height=0.5, edgecolor='none')
    ax2.tick_params(colors=textc, labelsize=10.5, length=0)
    ax2.xaxis.set_visible(False)
    for sp in ax2.spines.values():
        sp.set_visible(False)

    max_val = max(bvals) if bvals and max(bvals) > 0 else 1
    for bar, val in zip(bars, bvals):
        pct = val / total * 100 if total else 0
        ax2.text(max_val * 0.01, bar.get_y() + bar.get_height() / 2,
                 f'  {pct:.1f}%   {brl_fmt(val)}',
                 va='center', ha='left', color=textc, fontsize=10)

    ax2.set_xlim(0, max_val * 1.02)
    ax2.set_title('Por Corretora', color=dim, fontsize=10.5, pad=4, loc='left')

    # ── Panel 5: Evolução por corretora ─────────────────────────────────────
    ax2e = fig.add_subplot(gs[4, 0])
    ax2e.set_facecolor(bg)

    if show_broker_evo:
        xs = list(range(len(evo_dates)))
        for b in broker_order:
            series = broker_series[b]
            color  = BR_C.get(b, '#888')
            ax2e.plot(xs, series, color=color, linewidth=2, marker='o', markersize=3,
                      markerfacecolor=color, markeredgecolor=bg, label=b, zorder=3)
        ax2e.set_xticks(xs)
        ax2e.set_xticklabels([mmyy(d) for d in evo_dates], color=dim, fontsize=8.5)
        ax2e.tick_params(axis='y', colors=dim, labelsize=8.5, length=0)
        for sp in ax2e.spines.values():
            sp.set_visible(False)
        ax2e.grid(axis='y', color=dim, alpha=0.15, linewidth=0.5)
        ax2e.margins(x=0.03, y=0.35)
        ax2e.legend(loc='upper left', ncol=min(len(broker_order), 4),
                    frameon=False, fontsize=9, labelcolor='linecolor',
                    handlelength=1.2, handletextpad=0.5, columnspacing=1.2)
    else:
        ax2e.axis('off')
        ax2e.text(0.5, 0.5, 'Histórico insuficiente para evolução por corretora',
                  color=dim, fontsize=10, ha='center', va='center')

    ax2e.set_title('Evolução por Corretora', color=dim, fontsize=10.5, pad=6, loc='left')

    # ── Panel 6: Detail table (full width) ─────────────────────────────────
    ax3 = fig.add_subplot(gs[5, 0])
    ax3.set_facecolor(bg)
    ax3.axis('off')
    ax3.set_xlim(0, 1)

    row_h = 1.0 / (n_rows + 1)   # +1 for column header; rows/n_rows/font_sz built above

    # Column x positions (normalized 0-1)
    COL = {'name': 0.01, 'cat': 0.36, 'bal': 0.56, 'gain': 0.72, 'delta': 0.84}

    # Header row
    y = 1.0 - row_h * 0.5
    for label, x in [('Ativo', COL['name']), ('Categoria', COL['cat']),
                      ('Saldo', COL['bal']), ('Ganho%', COL['gain']),
                      ('Δ Mês', COL['delta'])]:
        ax3.text(x, y, label, color=dim, fontsize=font_sz,
                 va='center', ha='left', fontweight='bold')
    ax3.axhline(1.0 - row_h, color=dim, linewidth=0.4, alpha=0.5)

    for idx, row in enumerate(rows):
        y = 1.0 - row_h * (idx + 1.5)

        if row[0] == 'header':
            _, broker, btotal = row
            bcol = BR_C.get(broker, '#888')
            pct  = btotal / total * 100 if total else 0
            ax3.text(COL['name'], y,
                     f'── {broker}   {brl_fmt(btotal)}  ({pct:.1f}%)',
                     color=bcol, fontsize=font_sz, va='center',
                     fontweight='bold')
            ax3.axhline(y - row_h * 0.45, color=dim, linewidth=0.3, alpha=0.3)
            continue

        inv = row[1]
        bal  = inv['balance']
        prev_bal = inv.get('previousBalance', bal)
        cat  = inv.get('category', '') or '—'
        _, sub = classify(inv)

        # gain%
        if cat == 'Crypto':
            gain_s, gain_c = '—', dim
        elif 'investedUSD' in inv:
            iv = inv['investedUSD'] * dolar
            g  = bal - iv
            gp = g / iv * 100 if iv else 0
            gain_s = f'{gp:+.1f}%'
            gain_c = green if g >= 0 else red
        else:
            iv = inv.get('invested', bal)
            g  = bal - iv
            gp = g / iv * 100 if iv else 0
            gain_s = f'{gp:+.1f}%'
            gain_c = green if g >= 0 else red

        # delta mês
        md = bal - prev_bal
        if abs(md) < 0.01:
            delta_s, delta_c = '—', dim
        else:
            delta_s = f'{"+" if md >= 0 else ""}{brl_fmt(md)}'
            delta_c = green if md >= 0 else red

        name_s = inv['name'][:32]
        ax3.text(COL['name'], y, name_s, color=textc, fontsize=font_sz, va='center')
        ax3.text(COL['cat'],  y, sub,    color=dim,   fontsize=font_sz, va='center')
        ax3.text(COL['bal'],  y, brl_fmt(bal), color=textc, fontsize=font_sz,
                 va='center', family='monospace')
        ax3.text(COL['gain'], y, gain_s,  color=gain_c,  fontsize=font_sz, va='center')
        ax3.text(COL['delta'],y, delta_s, color=delta_c, fontsize=font_sz, va='center')

    ax3.set_ylim(0, 1)
    ax3.set_title('Ativos', color=dim, fontsize=10.5, pad=4, loc='left')

    # ── Save ─────────────────────────────────────────────────────────────────
    assets_dir = os.path.join(config.ROOT, 'assets')
    os.makedirs(assets_dir, exist_ok=True)
    img_path = os.path.join(assets_dir, 'status.png')
    fig.savefig(img_path, dpi=130, bbox_inches='tight',
                facecolor=bg, edgecolor='none')
    plt.close(fig)
    print(f'{G}✓ Imagem gerada: assets/status.png{RST}')
