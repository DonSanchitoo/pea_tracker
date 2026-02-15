import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import smtplib
import os
from datetime import datetime, timedelta
from email.message import EmailMessage

# --- CONFIGURATION ---
MONTHLY_INVESTMENTS = {"ESE.PA": 250, "ETZ.PA": 140, "PAASI.PA": 60, "AI.PA": 0, "TTE.PA": 0}
TICKERS = list(MONTHLY_INVESTMENTS.keys())
STATE_FILE = "portfolio_state.csv"
HISTORY_FILE = "pea_history.csv"

# --- PALETTE "PRO TERMINAL" ---
C_BLACK = "#000000"
C_DARK_GREY = "#121212"
C_GRID = "#2a2a2a"
C_TEXT = "#e0e0e0"
C_GREEN = "#00ff41"  # Vert Terminal
C_RED = "#ff2a2a"  # Rouge Alerte
C_ORANGE = "#ff9f43"  # Couleur Accent
C_BLUE = "#0abde3"


def get_portfolio_state():
    if os.path.exists(STATE_FILE): return pd.read_csv(STATE_FILE, index_col="Ticker")
    data = {t: {"Quantity": 0.0, "Total_Invested": 0.0, "Last_Purchase_Month": 0} for t in TICKERS}
    return pd.DataFrame.from_dict(data, orient='index')


def update_portfolio(state, prices):
    today = datetime.now()
    if today.day >= 16:
        for t, amount in MONTHLY_INVESTMENTS.items():
            if amount > 0 and state.loc[t, "Last_Purchase_Month"] != today.month:
                state.loc[t, "Quantity"] += amount / prices[t]
                state.loc[t, "Total_Invested"] += amount
                state.loc[t, "Last_Purchase_Month"] = today.month
        state.to_csv(STATE_FILE)
    return state


def create_dashboard(df, state, prices):
    # Données
    labels = TICKERS
    values = [state.loc[t, "Quantity"] * prices[t] for t in TICKERS]
    gains = [(state.loc[t, "Quantity"] * prices[t]) - state.loc[t, "Total_Invested"] for t in TICKERS]

    # Structure Dashboard
    fig = make_subplots(
        rows=len(TICKERS) + 2, cols=2,
        column_widths=[0.35, 0.65],
        row_heights=[0.35, 0.35] + [0.3] * len(TICKERS),
        specs=[[{"type": "domain"}, {"type": "xy"}],
               [{"type": "xy"}, {"type": "xy"}]] + [[{"type": "xy", "colspan": 2}, None]] * len(TICKERS),
        subplot_titles=("ALLOCATION ACTIFS", "VALORISATION DU CAPITAL",
                        "P&L NET (EUR)", "PERFORMANCE HISTORIQUE (%)")
                       + tuple(f"ANALYSE TECHNIQUE : {t}" for t in TICKERS),
        vertical_spacing=0.06
    )

    # 1. Donut Chart (Répartition) - Style minimaliste
    fig.add_trace(go.Pie(labels=labels, values=values, hole=.6,
                         marker=dict(colors=['#2c3e50', '#34495e', '#576574', '#8395a7', '#95a5a6'],
                                     line=dict(color=C_BLACK, width=2)),
                         textinfo='label+percent', hoverinfo='label+value+percent'), row=1, col=1)

    # 2. Area Chart (Investi vs Valeur) - Lignes fines et précises
    fig.add_trace(go.Scatter(x=df['Date'], y=df['Total_Invested'], name="CAPITAL INVESTI",
                             line=dict(color='#636e72', width=1, dash='dash')), row=1, col=2)
    fig.add_trace(go.Scatter(x=df['Date'], y=df['Total_Value'], name="VALEUR MARCHÉ", fill='tonexty',
                             fillcolor='rgba(255, 159, 67, 0.1)',  # Transparence subtile
                             line=dict(color=C_ORANGE, width=1.5)), row=1, col=2)

    # 3. Bar Chart (Gains) - Barres fines
    fig.add_trace(go.Bar(x=labels, y=gains, marker_color=[C_GREEN if g > 0 else C_RED for g in gains],
                         marker_line_width=0, opacity=0.9, name="GAIN NET"), row=2, col=1)

    # 4. Perf % - Ligne néon
    fig.add_trace(go.Scatter(x=df['Date'], y=df['Total_Return_Pct'], name="ROI %",
                             line=dict(color=C_GREEN, width=1.5), mode='lines'), row=2, col=2)

    # 5. Chandeliers - Style Pro
    for i, t in enumerate(TICKERS):
        hist = yf.Ticker(t).history(period="6mo")
        fig.add_trace(
            go.Candlestick(x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'],
                           name=t,
                           increasing_line_color=C_GREEN, decreasing_line_color=C_RED,
                           increasing_fillcolor=C_GREEN, decreasing_fillcolor=C_RED), row=i + 3, col=1)

    # STYLE GLOBAL "TERMINAL"
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=C_BLACK,
        plot_bgcolor=C_DARK_GREY,
        font=dict(family="Courier New, monospace", size=11, color=C_TEXT),
        title_text=f"<span style='color:{C_ORANGE}; font-size:20px; letter-spacing:3px;'>GESTION PEA</span> <span style='color:#666'>| SYSTEME D'ANALYSE</span>",
        showlegend=False,
        height=450 * (len(TICKERS) + 2),
        margin=dict(l=30, r=30, t=80, b=30),
        hovermode="x unified"  # LE CROSSHAIR PRO
    )

    # Configuration des axes (Grilles fines)
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor=C_GRID, zeroline=False, showspikes=True, spikethickness=1,
                     spikedash='solid', spikecolor='#666', spikesnap='cursor')
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor=C_GRID, zeroline=False, showspikes=True, spikethickness=1,
                     spikedash='solid', spikecolor='#666')
    fig.update_xaxes(rangeslider_visible=False)  # Pas de slider moche en bas

    fig.write_html("index.html")


def calculate_period_perf(df, days):
    if len(df) < 2: return 0.0
    target_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    past = df[df['Date'] <= target_date]
    if past.empty: past = df.iloc[[0]]
    return df['Total_Return_Pct'].iloc[-1] - past['Total_Return_Pct'].iloc[-1]


def run_tracker():
    state = get_portfolio_state()
    prices = {}
    h_rows, g_rows = "", ""
    total_v, total_i = 0, 0

    for t in TICKERS:
        h = yf.Ticker(t).history(period="1y")
        p = h['Close'].iloc[-1]
        prices[t] = p
        perf_7j = ((p - h['Close'].iloc[-5]) / h['Close'].iloc[-5]) * 100
        # HTML Mail
        color = "#009933" if perf_7j >= 0 else "#cc0000"
        h_rows += f"<tr><td style='border-bottom:1px solid #ddd; padding:8px;'><b>{t}</b></td><td style='border-bottom:1px solid #ddd; padding:8px;'>{p:.2f} €</td><td style='border-bottom:1px solid #ddd; padding:8px; color:{color};'><b>{perf_7j:+.2f}%</b></td></tr>"

    state = update_portfolio(state, prices)
    for t in TICKERS:
        qty, inv = state.loc[t, "Quantity"], state.loc[t, "Total_Invested"]
        val = qty * prices[t]
        total_v += val;
        total_i += inv
        p_tot = ((val - inv) / inv * 100) if inv > 0 else 0
        gain_eur = val - inv
        color_p = "#009933" if p_tot >= 0 else "#cc0000"
        g_rows += f"<tr><td style='border-bottom:1px solid #ddd; padding:8px;'><b>{t}</b></td><td style='border-bottom:1px solid #ddd; padding:8px;'>{inv:.2f} €</td><td style='border-bottom:1px solid #ddd; padding:8px; color:{color_p};'>{gain_eur:+.2f} €</td><td style='border-bottom:1px solid #ddd; padding:8px; color:{color_p};'><b>{p_tot:+.2f}%</b></td></tr>"

    perf_g = round(((total_v - total_i) / total_i * 100), 2) if total_i > 0 else 0
    new_row = {"Date": datetime.now().strftime("%Y-%m-%d"), "Total_Invested": round(total_i, 2),
               "Total_Value": round(total_v, 2), "Total_Return_Pct": perf_g}
    for t in TICKERS: new_row[t] = round(prices[t], 2)

    df = pd.concat([pd.read_csv(HISTORY_FILE), pd.DataFrame([new_row])]).drop_duplicates('Date')
    df.to_csv(HISTORY_FILE, index=False)

    return h_rows, g_rows, perf_g, calculate_period_perf(df, 7), calculate_period_perf(df, 90), calculate_period_perf(
        df, 365), round(total_v, 2), round(total_i, 2), df, state, prices


def send_email(h_html, g_html, perf, p7, p90, p365, val, inv):
    msg = EmailMessage()
    msg['Subject'] = f"SYNTHESE PEA - {datetime.now().strftime('%d/%m/%Y')}"
    msg['From'] = os.environ['EMAIL_USER'];
    msg['To'] = os.environ['EMAIL_RECEIVER']
    dash_url = f"https://{os.environ['GITHUB_ACTOR']}.github.io/{os.environ['GITHUB_REPOSITORY'].split('/')[-1]}/"

    # CSS Mail
    th_style = "background-color:#1a1a1a; color:white; padding:10px; text-align:left; font-size:12px; font-weight:normal; letter-spacing:1px;"

    html = f"""
    <html><body style="font-family: Arial, sans-serif; color: #333; margin:0; padding:0; background-color:#f4f4f4;">

        <div style="background-color:black; padding:20px; text-align:center; border-bottom: 3px solid #ff9f43;">
            <span style="color:white; font-family:'Courier New', monospace; font-size:24px; font-weight:bold; letter-spacing:2px;">GESTION PEA</span>
        </div>

        <div style="max-width:600px; margin:20px auto; background:white; padding:20px; box-shadow:0 0 10px rgba(0,0,0,0.1);">

            <h3 style="margin-top:0; border-bottom:1px solid #eee; padding-bottom:10px; font-size:14px; color:#666;">SYNTHÈSE PATRIMONIALE</h3>

            <table width="100%" cellspacing="0" cellpadding="10" style="background-color:#f8f9fa; border:1px solid #ddd; text-align:center; margin-bottom:20px;">
                <tr>
                    <td width="33%" style="border-right:1px solid #ddd;">
                        <div style="font-size:10px; color:#666; text-transform:uppercase;">VALEUR</div>
                        <div style="font-size:16px; font-weight:bold; color:#000;">{val:,.2f} €</div>
                    </td>
                    <td width="33%" style="border-right:1px solid #ddd;">
                        <div style="font-size:10px; color:#666; text-transform:uppercase;">INVESTI</div>
                        <div style="font-size:16px; font-weight:bold; color:#000;">{inv:,.2f} €</div>
                    </td>
                    <td width="33%">
                        <div style="font-size:10px; color:#666; text-transform:uppercase;">PLUS-VALUE</div>
                        <div style="font-size:16px; font-weight:bold; color:{'#009933' if (val - inv) >= 0 else '#cc0000'};">{(val - inv):+,.2f} €</div>
                    </td>
                </tr>
            </table>

            <table width="100%" cellspacing="0" cellpadding="8" style="margin-bottom:30px; border-collapse:collapse;">
                <tr style="background-color:#1a1a1a; color:white; font-size:11px;">
                    <th width="25%">7 JOURS</th>
                    <th width="25%">TRIMESTRE</th>
                    <th width="25%">1 AN</th>
                    <th width="25%" style="background-color:#ff9f43;">GLOBAL</th>
                </tr>
                <tr style="text-align:center; font-size:14px; font-weight:bold; background-color:#fff; border-bottom:1px solid #ccc;">
                    <td style="padding:10px; color:{'#009933' if p7 >= 0 else '#cc0000'}">{p7:+.2f}%</td>
                    <td style="padding:10px; color:{'#009933' if p90 >= 0 else '#cc0000'}">{p90:+.2f}%</td>
                    <td style="padding:10px; color:{'#009933' if p365 >= 0 else '#cc0000'}">{p365:+.2f}%</td>
                    <td style="padding:10px; background-color:#fff3e0; color:{'#d35400' if perf >= 0 else '#c0392b'}">{perf:+.2f}%</td>
                </tr>
            </table>

            <div style="font-size:14px; margin-bottom:5px; font-weight:bold;">MARCHÉ (7J)</div>
            <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse; margin-bottom:20px; font-size:13px;">
                <thead><tr><th style="{th_style}">ACTIF</th><th style="{th_style}">PRIX</th><th style="{th_style}">VAR.</th></tr></thead>
                <tbody>{h_html}</tbody>
            </table>

            <div style="font-size:14px; margin-bottom:5px; font-weight:bold;">POSITIONS</div>
            <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse; margin-bottom:30px; font-size:13px;">
                <thead><tr><th style="{th_style}">ACTIF</th><th style="{th_style}">INVESTI</th><th style="{th_style}">GAIN</th><th style="{th_style}">ROI</th></tr></thead>
                <tbody>{g_html}</tbody>
            </table>

            <div style="text-align:center;">
                <a href="{dash_url}" style="background-color:#1a1a1a; color:white; padding:12px 25px; text-decoration:none; font-family:'Courier New', monospace; font-weight:bold; font-size:14px; border:1px solid #ff9f43;">
                    >> ACCÉDER AU TERMINAL
                </a>
            </div>
        </div>
    </body></html>"""
    msg.add_alternative(html, subtype='html')
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
        s.login(os.environ['EMAIL_USER'], os.environ['EMAIL_PASS']);
        s.send_message(msg)


if __name__ == "__main__":
    h, g, p, p7, p90, p365, v, inv, df, state, prices = run_tracker()
    create_dashboard(df, state, prices)
    send_email(h, g, p, p7, p90, p365, v, inv)