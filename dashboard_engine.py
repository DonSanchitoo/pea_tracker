import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import pandas as pd
import yfinance as yf

# --- PALETTE TERMINAL PRO ---
C_BG = "#000000"  # Fond Noir
C_PAPER = "#0a0a0a"  # Fond Modules
C_GRID = "#1f1f1f"  # Grille
C_TEXT = "#e0e0e0"  # Texte
C_GREEN = "#00ff41"  # Gain / Hausse
C_RED = "#ff2a2a"  # Perte / Baisse
C_ORANGE = "#ff9f43"  # Titres
C_CYAN = "#00d2d3"  # Info / PRU
C_GREY = "#57606f"  # Benchmark / Secondaire
C_PURPLE = "#a29bfe"  # Alpha / Benchmark


def get_benchmark_data():
    """Récupère le MSCI World (CW8.PA) pour comparaison"""
    try:
        # On utilise l'ETF Amundi MSCI World comme référence PEA
        bench = yf.Ticker("CW8.PA").history(period="1y")
        return bench['Close']
    except:
        return None


def calculate_kpis(df):
    """Calcule CAGR, MDD, Volatilité et Alpha"""
    if len(df) < 2: return 0, 0, 0, 0, pd.Series(dtype=float)

    # 1. CAGR (Croissance Annuelle)
    days = (pd.to_datetime(df['Date'].iloc[-1]) - pd.to_datetime(df['Date'].iloc[0])).days
    total_ret = df['Total_Return_Pct'].iloc[-1] / 100
    cagr = ((1 + total_ret) ** (365 / days)) - 1 if days > 0 else 0

    # 2. Max Drawdown (MDD)
    roll_max = df['Total_Value'].cummax()
    daily_drawdown = df['Total_Value'] / roll_max - 1.0
    max_drawdown = daily_drawdown.min()

    # 3. Volatilité (Annualisée)
    df['pct_change'] = df['Total_Value'].pct_change()
    volatility = df['pct_change'].std() * (252 ** 0.5)

    # 4. Alpha (Surperformance vs Monde)
    # Comparaison simple sur la période totale
    bench = get_benchmark_data()
    alpha = 0
    if bench is not None and not bench.empty:
        bench_perf = (bench.iloc[-1] - bench.iloc[0]) / bench.iloc[0]
        my_perf = total_ret
        alpha = my_perf - bench_perf

    return cagr * 100, max_drawdown * 100, volatility * 100, alpha * 100, daily_drawdown


def add_info_marker(fig, row, col, text, title_text):
    """Ajoute le bouton 'i' et l'explication (Gère l'exception du Pie Chart)"""

    # --- CAS SPÉCIAL : PIE CHART (Row 2, Col 1) ---
    if row == 2 and col == 1:
        fig.add_annotation(
            xref="paper", yref="paper",
            x=0.02, y=0.83,  # Position manuelle car pas d'axes
            text=f"<b>{title_text}</b>",
            font=dict(color=C_ORANGE, size=14, family="Courier New"),
            showarrow=False
        )
        # Pas de bouton info interactif sur le Pie Chart pour éviter le bug domain
        return

    # --- CAS STANDARD (Tous les autres graphiques) ---
    # Cette partie manquait dans ton code !

    # 1. Le Marqueur Interactif (Gros point Cyan)
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode='markers',
        marker=dict(size=15, color=C_CYAN, symbol='circle'),
        name="INFO", showlegend=False, hoverinfo='text', hovertext=text
    ), row=row, col=col)

    # 2. Etiquette visuelle "[ ? ]"
    # On utilise "x domain" pour placer le bouton en haut à droite du graphique
    fig.add_annotation(
        xref=f"x domain", yref=f"y domain",
        x=0.98, y=1.1, text="[ ? ]",
        font=dict(color=C_CYAN, size=12, weight="bold"), showarrow=False,
        row=row, col=col, hovertext=text
    )


def generate_dashboard_v2(df, state, prices, filename="index.html"):
    cagr, mdd, vol, alpha, drawdown_series = calculate_kpis(df)
    labels = list(state.index)
    values = [state.loc[t, "Quantity"] * prices[t] for t in labels]
    pru_list = {t: (state.loc[t, "Total_Invested"] / state.loc[t, "Quantity"]) if state.loc[t, "Quantity"] > 0 else 0
                for t in labels}
    gains = [(state.loc[t, "Quantity"] * prices[t]) - state.loc[t, "Total_Invested"] for t in labels]

    # STRUCTURE COMPLEXE (Grille)
    titles_list = ["", "",  # Vide pour les KPIs
                   "ALLOCATION D'ACTIFS", "CROISSANCE PATRIMOINE",
                   "CONTRIBUTION P&L (EUR)", "PERFORMANCE vs MONDE",
                   "HISTORIQUE DES CHUTES (Drawdown)"] + [f"ANALYSE TECHNIQUE : {t}" for t in labels]

    # --- B. CRÉATION DE LA GRILLE ---
    fig = make_subplots(
        rows=4 + len(labels), cols=2,
        column_widths=[0.35, 0.65],
        row_heights=[0.12, 0.22, 0.22, 0.15] + [0.25] * len(labels),
        specs=[[{"type": "domain", "colspan": 2}, None],  # 1. KPIs
               [{"type": "domain"}, {"type": "xy"}],  # 2. Pie + Value
               [{"type": "xy"}, {"type": "xy"}],  # 3. Bar Gains + Perf
               [{"type": "xy", "colspan": 2}, None]] +  # 4. Drawdown
              [[{"type": "xy", "colspan": 2}, None]] * len(labels),  # 5+. Candles
        subplot_titles=titles_list,  # TITRES AUTOMATIQUES
        vertical_spacing=0.06
    )

    # --- 1. KPIs HEADERS (AVEC ECHELLES DE VALEUR) ---
    kpis = [
        (df['Total_Value'].iloc[-1], "VALEUR NETTE",
         "<b>TOTAL PORTEFEUILLE</b><br>Somme cash investi + gains.<br>Montant disponible.", C_GREEN, "€"),
        (cagr, "CAGR (Annuel)",
         "<b>RENDEMENT ANNUALISÉ</b><br>🔴 < 3% : Faible<br>🟡 4-7% : Bon<br>🟢 > 8% : Excellent", C_CYAN, "%"),
        (alpha, "ALPHA (vs Monde)",
         "<b>SURPERFORMANCE</b><br>🟢 Positif : Vous battez le marché<br>🔴 Négatif : ETF fait mieux", C_PURPLE, "% pts"),
        (mdd, "MAX DRAWDOWN",
         "<b>RISQUE MAX</b><br>🟢 0 à -10% : Normal<br>🟡 -10 à -20% : Correction<br>🔴 > -20% : Krach", C_RED, "%"),
        (vol, "VOLATILITÉ",
         "<b>NERVOSITÉ</b><br>🟢 < 10% : Calme<br>🔴 > 20% : Agressif", "#f1c40f", "%")
    ]

    # CETTE BOUCLE MANQUAIT DANS TON CODE :
    for i, (val, name, info, color, suffix) in enumerate(kpis):
        pos_x = (i / len(kpis)) + 0.1
        fig.add_annotation(
            xref="paper", yref="paper", x=pos_x, y=0.98,
            text=f"<span style='font-size:11px; color:{C_GREY}'>{name}</span><br><span style='font-size:22px; color:{color}'><b>{val:,.2f}{suffix}</b></span>",
            showarrow=False, align="center", hovertext=info
        )

    # --- 2. ALLOCATION & VALEUR ---
    # Pie
    fig.add_trace(go.Pie(labels=labels, values=values, hole=.6,
                         marker=dict(colors=['#2c3e50', '#34495e', '#576574', '#8395a7']),
                         textinfo='percent', hoverinfo='label+value+percent'), row=2, col=1)
    add_info_marker(fig, 2, 1, "<b>Répartition du risque :</b><br>Pourcentage de chaque actif.", "ALLOCATION")

    # Area Chart (Value)
    fig.add_trace(
        go.Scatter(x=df['Date'], y=df['Total_Invested'], name="Investi", line=dict(color=C_GREY, width=1, dash='dot')),
        row=2, col=2)
    fig.add_trace(go.Scatter(x=df['Date'], y=df['Total_Value'], name="Valeur", fill='tonexty',
                             line=dict(color=C_GREEN, width=1.5)), row=2, col=2)
    add_info_marker(fig, 2, 2, "<b>Patrimoine :</b><br>Zone Grise = Votre argent.<br>Zone Verte = Intérêts composés.",
                    "PATRIMOINE")

    # --- 3. GAINS & BENCHMARK ---
    # Bar Chart (P&L)
    fig.add_trace(go.Bar(x=labels, y=gains, marker_color=[C_GREEN if g > 0 else C_RED for g in gains], name="P/L"),
                  row=3, col=1)
    add_info_marker(fig, 3, 1, "<b>P&L Net :</b><br>Gains ou pertes en Euros.", "P&L NET (EUR)")

    # Perf vs Benchmark
    bench = get_benchmark_data()
    if bench is not None:
        b_norm = (bench / bench.iloc[0] - 1) * 100
        fig.add_trace(
            go.Scatter(x=df['Date'], y=df['Total_Return_Pct'], name="Mon PEA", line=dict(color=C_GREEN, width=2)),
            row=3, col=2)
        fig.add_trace(
            go.Scatter(x=bench.index, y=b_norm, name="MSCI World", line=dict(color=C_PURPLE, width=1, dash='dot')),
            row=3, col=2)
    add_info_marker(fig, 3, 2, "<b>Le Match :</b><br>Verte = Vous.<br>Violette = Le Marché.", "PERF vs MONDE")

    # --- 4. RISQUE (DRAWDOWN) ---
    fig.add_trace(go.Scatter(x=df['Date'], y=drawdown_series * 100, fill='tozeroy', name="Drawdown",
                             line=dict(color=C_RED, width=1)), row=4, col=1)
    add_info_marker(fig, 4, 1, "<b>Stress Test :</b><br>Distance par rapport au record historique.",
                    "HISTORIQUE DES CHUTES")

    # --- 5+. CHANDELIERS & PRU ---
    for i, t in enumerate(labels):
        row_idx = 5 + i
        hist = yf.Ticker(t).history(period="6mo")

        # 1. Bougies
        fig.add_trace(go.Candlestick(
            x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'],
            name=t, increasing_line_color=C_GREEN, decreasing_line_color=C_RED
        ), row=row_idx, col=1)

        # 2. Ligne PRU (Seulement si logique)
        my_pru = pru_list[t]
        if my_pru > 1:
            fig.add_trace(go.Scatter(
                x=[hist.index[0], hist.index[-1]], y=[my_pru, my_pru],
                mode='lines', line=dict(color=C_CYAN, width=1, dash='dash'), name="PRU"
            ), row=row_idx, col=1)

        # 3. Info Bulle
        add_info_marker(fig, row_idx, 1, f"Analyse de {t}.<br>Ligne Bleue = PRU ({my_pru:.2f}€).", "")

    # --- STYLE ---
    # Force tous les titres en ORANGE
    fig.update_annotations(font=dict(color=C_ORANGE, size=14, family="Courier New"))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=C_BG, plot_bgcolor=C_PAPER,
        font=dict(family="Courier New, monospace", size=11, color=C_TEXT),
        title_text=f"<span style='color:{C_ORANGE}; font-size:20px;'>DASHBOARD PEA</span> <span style='color:#666'>| ANALYTICS</span>",
        showlegend=False,
        height=1400 + (300 * len(labels)),
        margin=dict(l=20, r=20, t=80, b=20),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#2d3436", font_size=12, font_family="Courier New")
    )
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor=C_GRID, rangeslider_visible=False)
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor=C_GRID)

    fig.write_html(filename)
    return True