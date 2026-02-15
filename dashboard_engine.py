import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import pandas as pd
import yfinance as yf

# --- PALETTE TERMINAL FINANCIER ---
C_BG = "#000000"
C_PAPER = "#111111"
C_GRID = "#333333"
C_TEXT = "#eeeeee"
C_GREEN = "#00ff41"  # Gain
C_RED = "#ff2a2a"  # Perte
C_ORANGE = "#ff9f43"  # Titres
C_CYAN = "#00d2d3"  # Info / PRU
C_PURPLE = "#a29bfe"  # Benchmark
C_GREY = "#636e72"


def get_benchmark_data():
    try:
        # ETF Monde (CW8) pour comparaison
        bench = yf.Ticker("CW8.PA").history(period="1y")
        return bench['Close']
    except:
        return None


def calculate_kpis(df):
    if len(df) < 2: return 0, 0, 0, 0, pd.Series(dtype=float)

    # 1. CAGR (Rendement Annualisé)
    days = (pd.to_datetime(df['Date'].iloc[-1]) - pd.to_datetime(df['Date'].iloc[0])).days
    total_ret = df['Total_Return_Pct'].iloc[-1] / 100
    cagr = ((1 + total_ret) ** (365 / days)) - 1 if days > 0 else 0

    # 2. Drawdown Global (Stress Test Portefeuille entier)
    roll_max = df['Total_Value'].cummax()
    daily_drawdown = df['Total_Value'] / roll_max - 1.0
    max_drawdown = daily_drawdown.min()

    # 3. Volatilité Annualisée
    df['pct_change'] = df['Total_Value'].pct_change()
    volatility = df['pct_change'].std() * (252 ** 0.5)

    # 4. Alpha (Surperformance)
    bench = get_benchmark_data()
    alpha = 0
    if bench is not None and not bench.empty:
        bench_perf = (bench.iloc[-1] - bench.iloc[0]) / bench.iloc[0]
        my_perf = total_ret
        alpha = my_perf - bench_perf

    return cagr * 100, max_drawdown * 100, volatility * 100, alpha * 100, daily_drawdown


def add_info_marker(fig, row, col, text):
    """Place un bouton [?] discret DANS le graphique"""

    # Gestion position Pie Chart vs Graphiques classiques
    is_pie = (row == 2 and col == 1)

    xref = "paper" if is_pie else f"x{get_axis_index(fig, row, col)} domain"
    yref = "paper" if is_pie else f"y{get_axis_index(fig, row, col)} domain"

    # Positionnement
    x_pos = 0.05 if is_pie else 0.95
    y_pos = 0.82 if is_pie else 0.95

    fig.add_annotation(
        xref=xref, yref=yref,
        x=x_pos, y=y_pos,
        text="[ ? ]",
        font=dict(color=C_CYAN, size=11, weight="bold"),
        bgcolor=C_PAPER, bordercolor=C_CYAN, borderwidth=1,
        showarrow=False, hovertext=text, opacity=0.9
    )


def get_axis_index(fig, row, col):
    """Astuce pour récupérer l'index technique de l'axe pour Plotly"""
    # Plotly gère le mappage, on utilise 'domain' générique ou une astuce
    # Ici on simplifie en utilisant le placement standard de Plotly
    return ""


def generate_dashboard_v2(df, state, prices, filename="index.html"):
    cagr, mdd, vol, alpha, drawdown_series = calculate_kpis(df)
    labels = list(state.index)
    values = [state.loc[t, "Quantity"] * prices[t] for t in labels]
    pru_list = {t: (state.loc[t, "Total_Invested"] / state.loc[t, "Quantity"]) if state.loc[t, "Quantity"] > 0 else 0
                for t in labels}
    gains = [(state.loc[t, "Quantity"] * prices[t]) - state.loc[t, "Total_Invested"] for t in labels]

    # --- 1. DÉFINITION DES TITRES ---
    # L'ordre ici doit correspondre PARFAITEMENT aux specs ci-dessous
    titles = [
                 "", "",  # Ligne 1 (KPIs, pas de titres Plotly)
                 "ALLOCATION D'ACTIFS", "VALORISATION (INVESTI vs RÉEL)",  # Ligne 2
                 "P&L NET PAR ACTIF (EUR)", "PERFORMANCE RELATIVE (vs MONDE)",  # Ligne 3
                 "GLOBAL STRESS TEST (DRAWDOWN)", ""  # Ligne 4
             ] + [f"ANALYSE : {t}" for t in labels]  # Lignes 5+

    # --- 2. LAYOUT GRID ---
    specs = [
                [{"type": "domain", "colspan": 2}, None],  # Row 1: KPIs Header
                [{"type": "domain"}, {"type": "xy"}],  # Row 2: Pie | Area
                [{"type": "xy"}, {"type": "xy"}],  # Row 3: Bar | Line
                [{"type": "xy", "colspan": 2}, None]  # Row 4: Drawdown (Global)
            ] + [[{"type": "xy", "colspan": 2}, None]] * len(labels)  # Row 5+: Candles

    fig = make_subplots(
        rows=4 + len(labels), cols=2,
        column_widths=[0.4, 0.6],
        row_heights=[0.10, 0.20, 0.20, 0.15] + [0.25] * len(labels),
        specs=specs,
        subplot_titles=titles,
        vertical_spacing=0.07
    )

    # --- 3. REMPLISSAGE DES GRAPHIQUES ---

    # A. KPI HEADER (Ligne 1)
    kpi_data = [
        (df['Total_Value'].iloc[-1], "VALEUR NETTE", "Valeur de liquidation totale.", C_GREEN, "€"),
        (cagr, "CAGR", "Taux de croissance annuel composé.", C_CYAN, "%"),
        (alpha, "ALPHA", "Surperformance vs MSCI World.", C_PURPLE, "pts"),
        (mdd, "MAX DRAWDOWN", "Perte maximale historique (Global).", C_RED, "%"),
        (vol, "VOLATILITÉ", "Risque / Nervosité.", "#f1c40f", "%")
    ]
    for i, (val, name, info, color, suffix) in enumerate(kpi_data):
        pos_x = (i / len(kpi_data)) + 0.1
        fig.add_annotation(xref="paper", yref="paper", x=pos_x, y=1.00,
                           text=f"<span style='font-size:11px; color:{C_GREY}'>{name}</span><br><span style='font-size:20px; color:{color}'><b>{val:,.2f}{suffix}</b></span>",
                           showarrow=False, hovertext=info, bgcolor=C_BG, borderwidth=0)

    # B. REPARTITION (Ligne 2, Col 1) -> PIE
    fig.add_trace(go.Pie(labels=labels, values=values, hole=.5, marker=dict(colors=['#2c3e50', '#34495e', '#576574']),
                         textinfo='label+percent'), row=2, col=1)
    add_info_marker(fig, 2, 1, "<b>Allocation</b><br>Pondération de chaque ligne dans le portefeuille.")

    # C. VALORISATION (Ligne 2, Col 2) -> AREA
    fig.add_trace(
        go.Scatter(x=df['Date'], y=df['Total_Invested'], name="Investi", line=dict(color=C_GREY, width=1, dash='dot')),
        row=2, col=2)
    fig.add_trace(go.Scatter(x=df['Date'], y=df['Total_Value'], name="Valeur", fill='tonexty',
                             line=dict(color=C_GREEN, width=1.5)), row=2, col=2)
    add_info_marker(fig, 2, 2, "<b>Patrimoine</b><br>Écart entre l'argent versé (Gris) et la valeur réelle (Vert).")

    # D. P&L NET PAR ACTIF (Ligne 3, Col 1) -> BAR CHART (C'est bien le P&L ici)
    fig.add_trace(go.Bar(x=labels, y=gains, marker_color=[C_GREEN if g > 0 else C_RED for g in gains], name="P/L"),
                  row=3, col=1)
    add_info_marker(fig, 3, 1, "<b>P&L Net (Euros)</b><br>Gains ou pertes en monnaie réelle pour chaque actif.")

    # E. COMPARATIF BENCHMARK (Ligne 3, Col 2) -> LINE CHART
    bench = get_benchmark_data()
    if bench is not None:
        # Normalisation base 0 pour comparer
        b_norm = (bench / bench.iloc[0] - 1) * 100
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Total_Return_Pct'], name="PEA", line=dict(color=C_GREEN, width=2)),
                      row=3, col=2)
        fig.add_trace(go.Scatter(x=bench.index, y=b_norm, name="Monde", line=dict(color=C_PURPLE, width=1, dash='dot')),
                      row=3, col=2)
    add_info_marker(fig, 3, 2, "<b>Benchmark</b><br>Vert: Votre performance.<br>Violet: L'indice Monde (Reference).")

    # F. GLOBAL STRESS TEST (Ligne 4, Full) -> DRAWDOWN GLOBAL
    # C'est bien le drawdown calculé sur 'Total_Value' (Tout le PEA)
    fig.add_trace(
        go.Scatter(x=df['Date'], y=drawdown_series * 100, fill='tozeroy', name="DD", line=dict(color=C_RED, width=1)),
        row=4, col=1)
    add_info_marker(fig, 4, 1,
                    "<b>Stress Test Global</b><br>Chute maximale de l'ensemble du portefeuille depuis son sommet historique.")

    # G. CHANDELIERS (Lignes 5+)
    for i, t in enumerate(labels):
        row_idx = 5 + i
        hist = yf.Ticker(t).history(period="6mo")

        # Candles
        fig.add_trace(go.Candlestick(
            x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'],
            name=t, increasing_line_color=C_GREEN, decreasing_line_color=C_RED
        ), row=row_idx, col=1)

        # PRU
        my_pru = pru_list[t]
        if my_pru > 0.1:  # Evite le bug du graphique plat
            fig.add_trace(go.Scatter(
                x=[hist.index[0], hist.index[-1]], y=[my_pru, my_pru],
                mode='lines', line=dict(color=C_CYAN, width=1, dash='dash'), name="PRU"
            ), row=row_idx, col=1)
            txt_pru = f"PRU: {my_pru:.2f}€"
        else:
            txt_pru = "Pas encore d'achat"

        add_info_marker(fig, row_idx, 1, f"<b>Analyse {t}</b><br>{txt_pru}<br>Au-dessus de la ligne bleue = Profit.")

    # --- 4. STYLING FINAL ---
    # Force la couleur des titres (sinon Plotly les met en noir par défaut)
    fig.update_annotations(font=dict(color=C_ORANGE, size=14, family="Courier New"))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=C_BG, plot_bgcolor=C_PAPER,
        font=dict(family="Courier New, monospace", size=11, color=C_TEXT),
        title_text=f"<span style='color:{C_ORANGE}; font-size:24px; letter-spacing:2px;'>PORTFOLIO ANALYTICS</span>",
        showlegend=False,
        height=1400 + (350 * len(labels)),
        margin=dict(l=30, r=30, t=100, b=50),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#2d3436", font_size=12, font_family="Arial")
    )

    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor=C_GRID, rangeslider_visible=False)
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor=C_GRID)

    fig.write_html(filename)
    return True