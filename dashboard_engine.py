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
    if len(df) < 2: return 0, 0, 0, 0, pd.Series()

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
    """Ajoute le bouton 'i' et l'explication"""
    # Titre de la section avec icône
    fig.add_annotation(
        xref=f"x{row} domain" if row == 1 else f"x{row} domain",  # Subtilité Plotly
        yref=f"y{row} domain" if row > 1 else "y domain",
        x=0, y=1.1, text=f"<b>{title_text}</b>",
        font=dict(color=C_ORANGE, size=14, family="Courier New"),
        showarrow=False, row=row, col=col
    )
    # Marqueur interactif
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode='markers',
        marker=dict(size=12, color=C_CYAN, symbol='circle-open'),
        name="INFO", showlegend=False, hoverinfo='text', hovertext=text
    ), row=row, col=col)

    # "Faux" bouton visuel pour guider la souris
    fig.add_annotation(
        xref=f"x{row} domain", yref=f"y{row} domain" if row > 1 else "y domain",
        x=0.98, y=1.1, text="ⓘ INFO",
        font=dict(color=C_CYAN, size=10), showarrow=False,
        row=row, col=col,
        hovertext=text
    )


def generate_dashboard_v2(df, state, prices, filename="index.html"):
    cagr, mdd, vol, alpha, drawdown_series = calculate_kpis(df)
    labels = list(state.index)
    values = [state.loc[t, "Quantity"] * prices[t] for t in labels]
    pru_list = {t: (state.loc[t, "Total_Invested"] / state.loc[t, "Quantity"]) if state.loc[t, "Quantity"] > 0 else 0
                for t in labels}
    gains = [(state.loc[t, "Quantity"] * prices[t]) - state.loc[t, "Total_Invested"] for t in labels]

    # STRUCTURE COMPLEXE (Grille)
    rows = 4 + len(labels)
    fig = make_subplots(
        rows=rows, cols=2,
        column_widths=[0.35, 0.65],
        row_heights=[0.12, 0.22, 0.22, 0.15] + [0.20] * len(labels),
        specs=[[{"type": "domain", "colspan": 2}, None],  # 1. KPIs
               [{"type": "domain"}, {"type": "xy"}],  # 2. Pie + Value
               [{"type": "xy"}, {"type": "xy"}],  # 3. Bar Gains + Perf vs Bench
               [{"type": "xy", "colspan": 2}, None]] +  # 4. Drawdown
              [[{"type": "xy", "colspan": 2}, None]] * len(labels),  # 5+. Candles
        vertical_spacing=0.05
    )

    # --- 1. KPIs HEADERS (AVEC ECHELLES DE VALEUR) ---
    kpis = [
        (df['Total_Value'].iloc[-1], "VALEUR NETTE",
         "<b>TOTAL PORTEFEUILLE</b><br>" +
         "Somme de votre cash investi et de vos gains.<br>" +
         "Montant disponible aujourd'hui.",
         C_GREEN, "€"),

        (cagr, "CAGR (Annuel)",
         "<b>RENDEMENT ANNUALISÉ</b><br>" +
         "Moyenne de croissance par an (lissée).<br><br>" +
         "<b>Comparaison</b><br>" +
         "🔴 < 3% : Niveau Livret A<br>" +
         "🟡 4% à 7% : Bon rendement<br>" +
         "🟢 > 8% : Excellent",
         C_CYAN, "%"),

        (alpha, "ALPHA (vs Monde)",
         "<b>SURPERFORMANCE</b><br>" +
         "Comparaison face à un ETF Monde (CW8).<br><br>" +
         "<b>Lecture :</b><br>" +
         "🟢 Positif : Bravo, on bat le marché !<br>" +
         "🔴 Négatif : Un ETF fait mieux.<br>" +
         "<i>Cherchez l'Alpha est difficile sur le long terme.</i>",
         C_PURPLE, "% pts"),

        (mdd, "MAX DRAWDOWN",
         "<b>RISQUE MAXIMUM</b><br>" +
         "La chute la plus violente subie depuis un sommet historique.<br><br>" +
         "<b>Échelle:</b><br>" +
         "🟢 0% à -10% : Normal<br>" +
         "🟡 -10% à -20% : Correction de marché <br>" +
         "🔴 Au-delà de -20% : Krach",
         C_RED, "%"),

        (vol, "VOLATILITÉ",
         "<b>NERVOSITÉ (Risque)</b><br>" +
         "Amplitude des mouvements quotidiens.<br><br>" +
         "<b>Interprétation :</b><br>" +
         "🟢 < 10% : Calme<br>" +
         "🟡 10% à 15% : Standard<br>" +
         "🔴 > 20% : Agressif",
         "#f1c40f", "%")
    ]

    # --- 2. ALLOCATION & VALEUR ---
    # Pie
    fig.add_trace(go.Pie(labels=labels, values=values, hole=.6,
                         marker=dict(colors=['#2c3e50', '#34495e', '#576574', '#8395a7']),
                         textinfo='percent', hoverinfo='label+value+percent'), row=2, col=1)
    add_info_marker(fig, 2, 1,
                    "<b>Répartition :</b><br>Pourcentage de chaque actif du portefeuille.<br>Vérifiez qu'aucune ligne ne dépasse 30% pour limiter le risque.",
                    "ALLOCATION")

    # Area Chart (Value)
    fig.add_trace(
        go.Scatter(x=df['Date'], y=df['Total_Invested'], name="Investi", line=dict(color=C_GREY, width=1, dash='dot')),
        row=2, col=2)
    fig.add_trace(go.Scatter(x=df['Date'], y=df['Total_Value'], name="Valeur", fill='tonexty',
                             line=dict(color=C_GREEN, width=1.5)), row=2, col=2)
    add_info_marker(fig, 2, 2,
                    "<b>Création de Richesse :</b><br>Zone Grise = Effort d'épargne.<br>Zone Verte = Les intérêts composés.<br>L'écart grandissant est votre enrichissement.",
                    "PATRIMOINE")

    # --- 3. GAINS & BENCHMARK ---
    # Bar Chart (P&L)
    fig.add_trace(go.Bar(x=labels, y=gains, marker_color=[C_GREEN if g > 0 else C_RED for g in gains], name="P/L"),
                  row=3, col=1)
    add_info_marker(fig, 3, 1,
                    "<b>Contribution en Euros :</b><br>Performance par actif.",
                    "P&L NET (EUR)")

    # Perf vs Benchmark
    bench = get_benchmark_data()
    if bench is not None:
        # Normalisation pour comparer base 0
        b_norm = (bench / bench.iloc[0] - 1) * 100
        # On aligne les dates (simplification graphique)
        fig.add_trace(
            go.Scatter(x=df['Date'], y=df['Total_Return_Pct'], name="Mon PEA", line=dict(color=C_GREEN, width=2)),
            row=3, col=2)
        fig.add_trace(
            go.Scatter(x=bench.index, y=b_norm, name="MSCI World", line=dict(color=C_PURPLE, width=1, dash='dot')),
            row=3, col=2)
    add_info_marker(fig, 3, 2,
                    "<b>Le Match vs Le Marché :</b><br>Ligne Verte = Votre Performance.<br>Ligne Violette = ETF Monde.<br>Si la verte est au-dessus = gestion bonne.",
                    "PERF vs MONDE")

    # --- 4. RISQUE (DRAWDOWN) ---
    fig.add_trace(go.Scatter(x=df['Date'], y=drawdown_series * 100, fill='tozeroy', name="Drawdown",
                             line=dict(color=C_RED, width=1)), row=4, col=1)
    add_info_marker(fig, 4, 1,
                    "<b>Stress Test (Drawdown) :</b><br>Si la courbe touche 0 = record historique.<br> -10%, -> +11% pour revenir à l'équilibre.",
                    "HISTORIQUE DES CHUTES")

    # --- 5+. CHANDELIERS & PRU ---
    for i, t in enumerate(labels):
        row_idx = 5 + i
        hist = yf.Ticker(t).history(period="6mo")

        # Candles
        fig.add_trace(go.Candlestick(
            x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'],
            name=t, increasing_line_color=C_GREEN, decreasing_line_color=C_RED
        ), row=row_idx, col=1)

        # Ligne de PRU
        my_pru = pru_list[t]
        fig.add_trace(go.Scatter(
            x=[hist.index[0], hist.index[-1]], y=[my_pru, my_pru],
            mode='lines', line=dict(color=C_CYAN, width=1, dash='dash'), name="PRU"
        ), row=row_idx, col=1)

        # Info
        txt = f"<b>{t} :</b><br>Ligne Bleue = Prix d'Achat (PRU).<br>bougies sont au-dessus : <b>Zone de Gain</b>.<br>Si les bougies sont en dessous : <b>Zone de Perte</b>."
        add_info_marker(fig, row_idx, 1, txt, f"TECHNIQUE : {t}")

    # --- STYLE ---
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=C_BG, plot_bgcolor=C_PAPER,
        font=dict(family="Courier New, monospace", size=11, color=C_TEXT),
        title_text=f"<span style='color:{C_ORANGE}; font-size:20px;'>DASHBOARD PEA</span> <span style='color:#666'>| ANALYTICS</span>",
        showlegend=False,
        height=1400 + (300 * len(labels)),
        margin=dict(l=20, r=20, t=80, b=20),
        hovermode="x unified"
    )
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor=C_GRID, rangeslider_visible=False)
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor=C_GRID)

    fig.write_html(filename)
    return True