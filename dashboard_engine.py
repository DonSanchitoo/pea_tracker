import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import pandas as pd
import yfinance as yf

# --- PALETTE TERMINAL PRO ---
C_BG = "#000000"
C_PAPER = "#111111"
C_GRID = "#333333"
C_TEXT = "#eeeeee"
C_GREEN = "#00ff41"
C_RED = "#ff2a2a"
C_ORANGE = "#ff9f43"
C_CYAN = "#00d2d3"
C_PURPLE = "#a29bfe"
C_GREY = "#636e72"


def get_benchmark_data():
    try:
        bench = yf.Ticker("CW8.PA").history(period="1y")
        return bench['Close']
    except:
        return None


def calculate_kpis(df):
    if len(df) < 2: return 0, 0, 0, 0, pd.Series(dtype=float)

    # CAGR
    days = (pd.to_datetime(df['Date'].iloc[-1]) - pd.to_datetime(df['Date'].iloc[0])).days
    total_ret = df['Total_Return_Pct'].iloc[-1] / 100
    cagr = ((1 + total_ret) ** (365 / days)) - 1 if days > 0 else 0

    # Drawdown
    roll_max = df['Total_Value'].cummax()
    daily_drawdown = df['Total_Value'] / roll_max - 1.0
    max_drawdown = daily_drawdown.min()

    # Volatilité
    df['pct_change'] = df['Total_Value'].pct_change()
    volatility = df['pct_change'].std() * (252 ** 0.5)

    # Alpha
    bench = get_benchmark_data()
    alpha = 0
    if bench is not None and not bench.empty:
        bench_perf = (bench.iloc[-1] - bench.iloc[0]) / bench.iloc[0]
        my_perf = total_ret
        alpha = my_perf - bench_perf

    return cagr * 100, max_drawdown * 100, volatility * 100, alpha * 100, daily_drawdown


def add_info_marker(fig, row, col, text):
    """Place un bouton [?] discret À L'INTÉRIEUR du graphique"""

    # Détermine si on est sur un Pie Chart (domain) ou un Graphique normal (xy)
    ref_x = "paper" if (row == 2 and col == 1) else f"x{get_axis_index(row, col)} domain"
    ref_y = "paper" if (row == 2 and col == 1) else f"y{get_axis_index(row, col)} domain"

    # Coordonnées pour placer le point en haut à droite, DANS le cadre
    # Pour le Pie chart (Row 2 Col 1), on ajuste manuellement
    if row == 2 and col == 1:
        x_pos, y_pos = 0.05, 0.80
    else:
        x_pos, y_pos = 0.95, 0.95

    fig.add_annotation(
        xref=ref_x, yref=ref_y,
        x=x_pos, y=y_pos,
        text="[ ? ]",
        font=dict(color=C_CYAN, size=11, weight="bold"),
        bgcolor=C_PAPER,
        bordercolor=C_CYAN,
        borderwidth=1,
        showarrow=False,
        hovertext=text,
        opacity=0.8
    )


def get_axis_index(row, col):
    """Aide pour Plotly : retrouver le numéro d'axe selon la grille"""
    # Cette logique est simplifiée, Plotly gère souvent le mappage auto
    # Mais pour l'annotation domain, on laisse le standard "x domain"
    return ""


def generate_dashboard_v2(df, state, prices, filename="index.html"):
    cagr, mdd, vol, alpha, drawdown_series = calculate_kpis(df)
    labels = list(state.index)
    values = [state.loc[t, "Quantity"] * prices[t] for t in labels]
    pru_list = {t: (state.loc[t, "Total_Invested"] / state.loc[t, "Quantity"]) if state.loc[t, "Quantity"] > 0 else 0
                for t in labels}
    gains = [(state.loc[t, "Quantity"] * prices[t]) - state.loc[t, "Total_Invested"] for t in labels]

    # --- 1. DÉFINITION DES TITRES (AVANT CRÉATION) ---
    # Ces titres seront ANCRÉS aux graphiques. Ils ne bougeront pas.
    titles = [
                 "", "",  # Ligne 1 : KPIs (vide)
                 "RÉPARTITION DU CAPITAL", "VALORISATION (INVESTI vs RÉEL)",  # Ligne 2
                 "GAINS/PERTES NETS (EUR)", "COMPARATIF (PEA vs MONDE)",  # Ligne 3
                 "STRESS TEST : DRAWDOWN (CHUTES)", ""  # Ligne 4 (Full width)
             ] + [f"ANALYSE : {t}" for t in labels]  # Lignes 5+

    # --- 2. CRÉATION DE LA GRILLE ---
    fig = make_subplots(
        rows=4 + len(labels), cols=2,
        column_widths=[0.35, 0.65],
        row_heights=[0.10, 0.20, 0.20, 0.15] + [0.25] * len(labels),
        specs=[[{"type": "domain", "colspan": 2}, None],  # 1. KPIs
               [{"type": "domain"}, {"type": "xy"}],  # 2. Pie + Area
               [{"type": "xy"}, {"type": "xy"}],  # 3. Bar + Line
               [{"type": "xy", "colspan": 2}, None]] +  # 4. Drawdown
              [[{"type": "xy", "colspan": 2}, None]] * len(labels),  # 5+. Candles
        subplot_titles=titles,  # <--- C'est ici que la magie opère
        vertical_spacing=0.08  # Plus d'espace pour éviter le chevauchement
    )

    # --- 3. CONTENU DES GRAPHIQUES ---

    # A. KPI HEADER
    # On utilise des annotations fixes en haut de page
    kpi_data = [
        (df['Total_Value'].iloc[-1], "VALEUR NETTE", "Argent disponible si vous vendiez tout maintenant.", C_GREEN,
         "€"),
        (cagr, "CAGR (ANNUEL)", "Rendement moyen par an.<br>Equivalent au taux d'un livret bancaire.", C_CYAN, "%"),
        (alpha, "ALPHA", "Votre performance MOINS celle du marché.<br>Si positif : Vous êtes meilleur qu'un ETF.",
         C_PURPLE, "pts"),
        (mdd, "MAX DRAWDOWN",
         "La plus grosse 'claque' reçue par le portefeuille.<br>Ex: -20% signifie que vous avez déjà vu votre compte fondre de 20% au pire moment.",
         C_RED, "%"),
        (vol, "VOLATILITÉ", "Est-ce que ça bouge beaucoup ?<br><10%: Calme.<br>>20%: Montagnes russes.", "#f1c40f", "%")
    ]
    for i, (val, name, info, color, suffix) in enumerate(kpi_data):
        pos_x = (i / len(kpi_data)) + 0.1
        fig.add_annotation(xref="paper", yref="paper", x=pos_x, y=1.00,
                           text=f"<span style='font-size:11px; color:{C_GREY}'>{name}</span><br><span style='font-size:20px; color:{color}'><b>{val:,.2f}{suffix}</b></span>",
                           showarrow=False, hovertext=info, bgcolor=C_BG, bordercolor=C_GRID, borderwidth=1,
                           opacity=0.9)

    # B. REPARTITION (Pie)
    fig.add_trace(go.Pie(labels=labels, values=values, hole=.5, marker=dict(colors=['#2c3e50', '#34495e', '#576574']),
                         textinfo='percent'), row=2, col=1)
    add_info_marker(fig, 2, 1,
                    "<b>Diversification</b><br>Montre la part de chaque action.<br>Attention si une part dépasse 30%.")

    # C. VALORISATION (Area)
    fig.add_trace(
        go.Scatter(x=df['Date'], y=df['Total_Invested'], name="Investi", line=dict(color=C_GREY, width=1, dash='dot')),
        row=2, col=2)
    fig.add_trace(go.Scatter(x=df['Date'], y=df['Total_Value'], name="Valeur", fill='tonexty',
                             line=dict(color=C_GREEN, width=1.5)), row=2, col=2)
    add_info_marker(fig, 2, 2,
                    "<b>Enrichissement</b><br>Zone Grise : L'argent sorti de votre poche.<br>Zone Verte : La valeur réelle.<br>L'écart est votre bénéfice.")

    # D. GAINS NETS (Bar)
    fig.add_trace(go.Bar(x=labels, y=gains, marker_color=[C_GREEN if g > 0 else C_RED for g in gains], name="P/L"),
                  row=3, col=1)
    add_info_marker(fig, 3, 1,
                    "<b>Bilan par ligne</b><br>Combien d'Euros chaque action vous a rapporté (ou coûté) depuis l'achat.")

    # E. COMPARATIF (Line)
    bench = get_benchmark_data()
    if bench is not None:
        b_norm = (bench / bench.iloc[0] - 1) * 100
        fig.add_trace(go.Scatter(x=df['Date'], y=df['Total_Return_Pct'], name="PEA", line=dict(color=C_GREEN, width=2)),
                      row=3, col=2)
        fig.add_trace(go.Scatter(x=bench.index, y=b_norm, name="Monde", line=dict(color=C_PURPLE, width=1, dash='dot')),
                      row=3, col=2)
    add_info_marker(fig, 3, 2,
                    "<b>La course</b><br>Vert : Vous.<br>Violet : Le Marché (ETF Monde).<br>Le but est d'être au-dessus de la ligne violette.")

    # F. DRAWDOWN (Area Red)
    fig.add_trace(
        go.Scatter(x=df['Date'], y=drawdown_series * 100, fill='tozeroy', name="DD", line=dict(color=C_RED, width=1)),
        row=4, col=1)
    add_info_marker(fig, 4, 1,
                    "<b>Profondeur de la chute</b><br>Si la courbe est à -10%, cela veut dire que votre portefeuille vaut 10% de moins<br>que son record historique (le 'Plus Haut').")

    # G. CHANDELIERS
    for i, t in enumerate(labels):
        row_idx = 5 + i
        hist = yf.Ticker(t).history(period="6mo")

        # Candles
        fig.add_trace(go.Candlestick(
            x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'],
            name=t, increasing_line_color=C_GREEN, decreasing_line_color=C_RED
        ), row=row_idx, col=1)

        # PRU (seulement si pertinent)
        my_pru = pru_list[t]
        if my_pru > 1:
            fig.add_trace(go.Scatter(
                x=[hist.index[0], hist.index[-1]], y=[my_pru, my_pru],
                mode='lines', line=dict(color=C_CYAN, width=1, dash='dash'), name="PRU"
            ), row=row_idx, col=1)

            pru_txt = f"Ligne Bleue = Votre Prix d'achat ({my_pru:.2f}€)."
        else:
            pru_txt = "Pas encore d'achat, donc pas de ligne PRU."

        add_info_marker(fig, row_idx, 1,
                        f"<b>Analyse Technique {t}</b><br>{pru_txt}<br>Si les bougies sont au-dessus de la ligne bleue, vous gagnez de l'argent.")

    # --- 4. STYLE FINAL & NETTOYAGE ---

    # On force la couleur des titres générés par subplot_titles
    fig.update_annotations(font=dict(color=C_ORANGE, size=14, family="Courier New"))

    # On cache le bouton [?] générique pour ne garder que ceux placés manuellement
    # (Astuce: subplot_titles crée aussi des annotations, on ne veut pas les toucher,
    # donc on cible spécifiquement nos markers si besoin, mais ici le style global est OK)

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=C_BG, plot_bgcolor=C_PAPER,
        font=dict(family="Courier New, monospace", size=11, color=C_TEXT),
        title_text=f"<span style='color:{C_ORANGE}; font-size:24px; letter-spacing:2px;'>DASHBOARD PEA</span>",
        showlegend=False,
        height=1400 + (350 * len(labels)),
        margin=dict(l=30, r=30, t=100, b=50),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#2d3436", font_size=12, font_family="Arial")  # Arial pour lisibilité tooltip
    )

    # Suppression des petits sliders en bas des graphiques
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor=C_GRID, rangeslider_visible=False)
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor=C_GRID)

    fig.write_html(filename)
    return True