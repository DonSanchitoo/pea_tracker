import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import pandas as pd
import yfinance as yf

# --- PALETTE INSTITUTIONNELLE (DARK MODE) ---
C_BG = "#000000"  # Fond Noir
C_PAPER = "#111111"  # Fond Graphiques
C_GRID = "#2d3436"  # Grille
C_TEXT = "#ecf0f1"  # Texte
C_GREEN = "#00ff41"  # Profit
C_RED = "#ff2a2a"  # Perte / Drawdown
C_ORANGE = "#ff9f43"  # Titres / Focus
C_CYAN = "#00d2d3"  # Info / KPI
C_PURPLE = "#a29bfe"  # Benchmark
C_GREY = "#636e72"  # Neutre


# --- CORRECTION 1 : BENCHMARK DYNAMIQUE ---
def get_benchmark_data(start_date=None):
    try:
        # Benchmark: MSCI World (CW8.PA)
        # Si une date est fournie, on s'aligne, sinon 1 an par défaut
        if start_date:
            # On convertit en string YYYY-MM-DD au cas où
            start_str = pd.to_datetime(start_date).strftime('%Y-%m-%d')
            bench = yf.Ticker("CW8.PA").history(start=start_str)
        else:
            bench = yf.Ticker("CW8.PA").history(period="1y")
        return bench['Close']
    except:
        return None


def calculate_kpis(df):
    if len(df) < 2: return 0, 0, 0, 0, pd.Series(dtype=float)

    # 1. CAGR (Croissance Annuelle Lissée)
    days = (pd.to_datetime(df['Date'].iloc[-1]) - pd.to_datetime(df['Date'].iloc[0])).days
    total_ret = df['Total_Return_Pct'].iloc[-1] / 100
    cagr = ((1 + total_ret) ** (365 / days)) - 1 if days > 0 else 0

    # 2. Drawdown Global (Stress Test)
    roll_max = df['Total_Value'].cummax()
    daily_drawdown = df['Total_Value'] / roll_max - 1.0
    max_drawdown = daily_drawdown.min()

    # 3. Volatilité
    df['pct_change'] = df['Total_Value'].pct_change()
    volatility = df['pct_change'].std() * (252 ** 0.5)

    # 4. Alpha (vs Monde)
    # Correction : On passe la date de début du portfolio pour avoir une comparaison juste
    start_date = df['Date'].iloc[0]
    bench = get_benchmark_data(start_date)

    alpha = 0
    if bench is not None and not bench.empty:
        bench_perf = (bench.iloc[-1] - bench.iloc[0]) / bench.iloc[0]
        my_perf = total_ret
        alpha = my_perf - bench_perf

    return cagr * 100, max_drawdown * 100, volatility * 100, alpha * 100, daily_drawdown


def add_info_marker(fig, row, col, text):
    """Ajoute un bouton [?] dans le coin du graphique"""
    # Détection Pie Chart (Domain) vs XY
    is_pie = (row == 1 and col == 1)

    xref = "paper" if is_pie else f"x{get_axis_index(row, col)} domain"
    yref = "paper" if is_pie else f"y{get_axis_index(row, col)} domain"

    # Positionnement précis dans le coin haut-droit
    x_pos = 0.05 if is_pie else 0.96
    y_pos = 0.90 if is_pie else 0.96

    fig.add_annotation(
        xref=xref, yref=yref, x=x_pos, y=y_pos,
        text="[?]", font=dict(color=C_CYAN, size=11, weight="bold", family="Arial"),
        bgcolor=C_PAPER, bordercolor=C_CYAN, borderwidth=1, opacity=0.8,
        showarrow=False, hovertext=text
    )


# --- CORRECTION 2 : MAPPING DES AXES PLOTLY ---
def get_axis_index(row, col):
    # Mapping corrigé : Le Pie Chart (1,1) ne consomme pas d'axe XY.
    # L'indexation XY commence donc au graphique suivant (1,2).

    # Ligne 1, Col 2 -> C'est le 1er graph XY -> "" (vide = axis 1)
    if row == 1 and col == 2: return ""

    # Ligne 2, Col 1 -> C'est le 2ème graph XY -> "2"
    if row == 2 and col == 1: return "2"

    # Ligne 2, Col 2 -> C'est le 3ème graph XY -> "3"
    if row == 2 and col == 2: return "3"

    # Ligne 3 (Colspan) -> C'est le 4ème graph XY -> "4"
    if row == 3: return "4"

    return ""


def generate_dashboard_v2(df, state, prices, filename="index.html"):
    # Calculs
    cagr, mdd, vol, alpha, drawdown_series = calculate_kpis(df)
    labels = list(state.index)
    values = [state.loc[t, "Quantity"] * prices[t] for t in labels]
    gains = [(state.loc[t, "Quantity"] * prices[t]) - state.loc[t, "Total_Invested"] for t in labels]

    # --- 1. TITRES PRO (ANGLAIS FINANCIER) ---
    titles = [
        "PORTFOLIO EXPOSURE (WEIGHTS)",  # Row 1 Col 1
        "NET ASSET VALUE (NAV) HISTORY",  # Row 1 Col 2
        "P&L ATTRIBUTION (EUR)",  # Row 2 Col 1
        "ALPHA GENERATION vs BENCHMARK",  # Row 2 Col 2
        "RISK PROFILE : HISTORICAL DRAWDOWN"  # Row 3 Full
    ]

    # --- 2. GRID LAYOUT (FIXE A4) ---
    fig = make_subplots(
        rows=3, cols=2,
        column_widths=[0.4, 0.6],
        row_heights=[0.35, 0.35, 0.30],
        specs=[
            [{"type": "domain"}, {"type": "xy"}],  # Row 1
            [{"type": "xy"}, {"type": "xy"}],  # Row 2
            [{"type": "xy", "colspan": 2}, None]  # Row 3
        ],
        subplot_titles=titles,
        vertical_spacing=0.1,
        horizontal_spacing=0.08
    )

    # --- 3. KPI HEADER (ANNOTATIONS) ---
    kpi_data = [
        (df['Total_Value'].iloc[-1], "NET EQUITY", "Valeur de liquidation totale.", C_GREEN, "€"),
        (cagr, "CAGR", "Croissance annuelle moyenne (Lissée).", C_CYAN, "%"),
        (alpha, "ALPHA", "Surperformance vs MSCI World (CW8).", C_PURPLE, "pts"),
        (mdd, "MAX DRAWDOWN", "Risque Max Historique (Pire chute).", C_RED, "%"),
        (vol, "VOLATILITY", "Volatilité (Nervosité 30j).", "#f1c40f", "%")
    ]

    # Placement des KPIs tout en haut
    for i, (val, name, info, color, suffix) in enumerate(kpi_data):
        pos_x = (i / len(kpi_data)) + 0.08
        fig.add_annotation(xref="paper", yref="paper", x=pos_x, y=1.12,
                           text=f"<span style='font-size:10px; color:{C_GREY}; font-family:Arial'>{name}</span><br><span style='font-size:18px; color:{color}'><b>{val:,.2f}{suffix}</b></span>",
                           showarrow=False, hovertext=info, bgcolor=C_BG, borderwidth=0)

    # --- CHART 1: EXPOSURE (Pie) ---
    fig.add_trace(go.Pie(labels=labels, values=values, hole=.5,
                         marker=dict(colors=['#2c3e50', '#34495e', '#576574', '#7f8c8d', '#95a5a6']),
                         textinfo='label+percent', hoverinfo='label+value+percent'), row=1, col=1)
    add_info_marker(fig, 1, 1, "<b>Exposition</b><br>Pondération des actifs.<br>Gérer le risque de concentration.")

    # --- CHART 2: NAV HISTORY (Area) ---
    fig.add_trace(go.Scatter(x=df['Date'], y=df['Total_Invested'], name="Invested Capital",
                             line=dict(color=C_GREY, width=1, dash='dot')), row=1, col=2)
    fig.add_trace(go.Scatter(x=df['Date'], y=df['Total_Value'], name="Net Asset Value", fill='tonexty',
                             line=dict(color=C_GREEN, width=1.5)), row=1, col=2)
    add_info_marker(fig, 1, 2,
                    "<b>NAV Evolution</b><br>Gris: Capital versé.<br>Vert: Valeur de marché.<br>L'écart est le profit cumulé.")

    # --- CHART 3: P&L ATTRIBUTION (Bar) ---
    fig.add_trace(go.Bar(x=labels, y=gains, marker_color=[C_GREEN if g > 0 else C_RED for g in gains],
                         name="P&L Contribution"), row=2, col=1)
    add_info_marker(fig, 2, 1, "<b>Attribution</b><br>Contribution nette en Euros par position.")

    # --- CHART 4: ALPHA vs BENCHMARK (Line) ---
    # Correction : Appel avec la date de début pour aligner les courbes
    start_date = df['Date'].iloc[0]
    bench = get_benchmark_data(start_date)

    if bench is not None:
        # On s'assure que le bench commence bien à la date souhaitée (slicing de sécurité)
        bench = bench[bench.index >= pd.to_datetime(start_date)]
        # Normalisation base 0
        b_norm = (bench / bench.iloc[0] - 1) * 100

        fig.add_trace(go.Scatter(x=df['Date'], y=df['Total_Return_Pct'], name="Portfolio",
                                 line=dict(color=C_GREEN, width=2)), row=2, col=2)
        fig.add_trace(go.Scatter(x=bench.index, y=b_norm, name="MSCI World Index",
                                 line=dict(color=C_PURPLE, width=1, dash='dot')), row=2, col=2)
    add_info_marker(fig, 2, 2, "<b>Alpha Generation</b><br>Capacité à battre l'indice de référence (MSCI World).")

    # --- CHART 5: RISK PROFILE (Full Width Area) ---
    fig.add_trace(go.Scatter(x=df['Date'], y=drawdown_series * 100, fill='tozeroy', name="Drawdown",
                             line=dict(color=C_RED, width=1)), row=3, col=1)
    add_info_marker(fig, 3, 1, "<b>Risk Profile</b><br>Profondeur des pertes depuis le sommet historique.")

    # --- STYLING FINAL (A4 Format) ---
    # Force Titres Orange
    fig.update_annotations(font=dict(color=C_ORANGE, size=12, family="Courier New"))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=C_BG, plot_bgcolor=C_PAPER,
        font=dict(family="Courier New, monospace", size=10, color=C_TEXT),
        # Titre Principal
        title=dict(
            text=f"<span style='color:{C_ORANGE}; font-size:22px; letter-spacing:3px;'>INVESTMENT MEMORANDUM</span> <span style='font-size:12px; color:{C_GREY}'>| ONE-PAGE REPORT</span>",
            y=0.98
        ),
        showlegend=False,
        height=900,  # Hauteur A4 Paysage standard
        margin=dict(l=40, r=40, t=140, b=40),  # Marge haute pour les KPIs
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#2d3436", font_size=11, font_family="Arial")
    )

    # Grilles fines style terminal
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor=C_GRID, zeroline=False)
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor=C_GRID, zeroline=False)

    fig.write_html(filename)
    return True