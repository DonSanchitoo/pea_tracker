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

# --- COULEURS BLOOMBERG ---
BB_ORANGE = "#ff793f"
BB_BLACK = "#1e1e1e"
BB_GREEN = "#2ecc71"
BB_RED = "#ff5252"


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

    # Structure Dashboard
    fig = make_subplots(
        rows=len(TICKERS) + 2, cols=2,
        column_widths=[0.4, 0.6],
        row_heights=[0.3, 0.3] + [0.25] * len(TICKERS),
        specs=[[{"type": "domain"}, {"type": "scatter"}],
               [{"type": "bar"}, {"type": "scatter"}]] + [[{"type": "candlestick", "colspan": 2}, None]] * len(TICKERS),
        subplot_titles=("ALLOCATION D'ACTIFS", "VALORISATION DU PORTEFEUILLE",
                        "GAIN NET PAR ACTIF (EUR)", "PERFORMANCE CUMULEE (%)")
                       + tuple(f"ANALYSE TECHNIQUE : {t}" for t in TICKERS),
        vertical_spacing=0.04
    )

    # 1. Pie Chart (Répartition)
    fig.add_trace(
        go.Pie(labels=labels, values=values, hole=.5, marker=dict(colors=['#34495e', '#576574', '#8395a7', '#c8d6e5'])),
        row=1, col=1)

    # 2. Courbe Patrimoine (Investi vs Valeur)
    fig.add_trace(go.Scatter(x=df['Date'], y=df['Total_Invested'], name="CAPITAL INVESTI",
                             line=dict(color='#7f8c8d', width=1, dash='dot')), row=1, col=2)
    fig.add_trace(go.Scatter(x=df['Date'], y=df['Total_Value'], name="VALEUR LIQUIDATIVE", fill='tonexty',
                             line=dict(color=BB_ORANGE, width=2)), row=1, col=2)

    # 3. Bar Chart (Gains)
    gains = [(state.loc[t, "Quantity"] * prices[t]) - state.loc[t, "Total_Invested"] for t in TICKERS]
    fig.add_trace(
        go.Bar(x=labels, y=gains, marker_color=[BB_GREEN if g > 0 else BB_RED for g in gains], name="P/L EUR"), row=2,
        col=1)

    # 4. Perf %
    fig.add_trace(
        go.Scatter(x=df['Date'], y=df['Total_Return_Pct'], name="PERFORMANCE %", line=dict(color=BB_GREEN, width=2)),
        row=2, col=2)

    # 5. Chandeliers
    for i, t in enumerate(TICKERS):
        hist = yf.Ticker(t).history(period="6mo")
        fig.add_trace(
            go.Candlestick(x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'],
                           name=t,
                           increasing_line_color=BB_GREEN, decreasing_line_color=BB_RED), row=i + 3, col=1)

    # STYLE BLOOMBERG TERMINAL (DARK)
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#000000",
        plot_bgcolor="#121212",
        font=dict(family="Courier New, monospace", size=12, color="#ecf0f1"),
        title_text="<b style='color:#ff793f'>BLOOMBERG TERMINAL</b> | PORTFOLIO ANALYTICS",
        title_font_size=20,
        showlegend=False,
        height=400 * (len(TICKERS) + 2),
        margin=dict(l=40, r=40, t=80, b=40)
    )
    # Suppression du range slider pour le look pro
    fig.update_xaxes(rangeslider_visible=False)
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
        # Lignes du tableau (HTML pur)
        color = "green" if perf_7j >= 0 else "red"
        h_rows += f"<tr><td style='border:1px solid #ddd; padding:8px;'><b>{t}</b></td><td style='border:1px solid #ddd; padding:8px;'>{p:.2f} €</td><td style='border:1px solid #ddd; padding:8px; color:{color};'><b>{perf_7j:+.2f}%</b></td></tr>"

    state = update_portfolio(state, prices)
    for t in TICKERS:
        qty, inv = state.loc[t, "Quantity"], state.loc[t, "Total_Invested"]
        val = qty * prices[t]
        total_v += val;
        total_i += inv
        p_tot = ((val - inv) / inv * 100) if inv > 0 else 0
        gain_eur = val - inv
        # Lignes du tableau (HTML pur)
        color_p = "green" if p_tot >= 0 else "red"
        g_rows += f"<tr><td style='border:1px solid #ddd; padding:8px;'><b>{t}</b></td><td style='border:1px solid #ddd; padding:8px;'>{inv:.2f} €</td><td style='border:1px solid #ddd; padding:8px; color:{color_p};'>{gain_eur:+.2f} €</td><td style='border:1px solid #ddd; padding:8px; color:{color_p};'><b>{p_tot:+.2f}%</b></td></tr>"

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
    msg['Subject'] = f"MARKET UPDATE - {datetime.now().strftime('%d/%m/%Y')}"
    msg['From'] = os.environ['EMAIL_USER'];
    msg['To'] = os.environ['EMAIL_RECEIVER']
    dash_url = f"https://{os.environ['GITHUB_ACTOR']}.github.io/{os.environ['GITHUB_REPOSITORY'].split('/')[-1]}/"

    # STYLE CSS BLOOMBERG MAIL
    table_style = "width:100%; border-collapse:collapse; margin-top:10px; font-size:13px;"
    th_style = "background-color:black; color:white; padding:10px; text-align:left; border:1px solid black;"

    html = f"""
    <html><body style="font-family: 'Arial', sans-serif; color: #333; padding: 0; margin:0; background-color:#f4f4f4;">

        <div style="background-color:black; color:white; padding:15px; text-align:center;">
            <h2 style="margin:0; font-family:'Courier New', monospace; letter-spacing:2px; color:#ff793f;">BLOOMBERG <span style="color:white;">REPORT</span></h2>
        </div>

        <div style="padding:20px; background-color:white; max-width:650px; margin:20px auto; border:1px solid #ccc; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">

            <h3 style="border-bottom: 2px solid #ff793f; padding-bottom: 5px; margin-top:0;">1. SYNTHÈSE PATRIMONIALE</h3>
            <div style="display:flex; justify-content:space-between; background:#f9f9f9; padding:15px; border:1px solid #ddd;">
                <div>
                    <span style="font-size:11px; color:#666; text-transform:uppercase;">Valeur Actuelle</span><br>
                    <span style="font-size:18px; font-weight:bold;">{val:,.2f} EUR</span>
                </div>
                <div>
                    <span style="font-size:11px; color:#666; text-transform:uppercase;">Investissement Total</span><br>
                    <span style="font-size:18px; font-weight:bold;">{inv:,.2f} EUR</span>
                </div>
                <div>
                    <span style="font-size:11px; color:#666; text-transform:uppercase;">Plus-Value Latente</span><br>
                    <span style="font-size:18px; font-weight:bold; color:{'#27ae60' if (val - inv) >= 0 else '#c0392b'};">{(val - inv):+,.2f} EUR</span>
                </div>
            </div>

            <table style="{table_style} text-align:center;">
                <thead>
                    <tr>
                        <th style="{th_style} text-align:center;">7 JOURS</th>
                        <th style="{th_style} text-align:center;">TRIMESTRE</th>
                        <th style="{th_style} text-align:center;">1 AN</th>
                        <th style="{th_style} text-align:center; background-color:#ff793f;">GLOBAL</th>
                    </tr>
                </thead>
                <tbody>
                    <tr style="font-weight:bold; font-size:14px; background-color:#fcfcfc;">
                        <td style="padding:10px; border:1px solid #ddd; color:{'green' if p7 >= 0 else 'red'}">{p7:+.2f}%</td>
                        <td style="padding:10px; border:1px solid #ddd; color:{'green' if p90 >= 0 else 'red'}">{p90:+.2f}%</td>
                        <td style="padding:10px; border:1px solid #ddd; color:{'green' if p365 >= 0 else 'red'}">{p365:+.2f}%</td>
                        <td style="padding:10px; border:1px solid #ddd; color:{'green' if perf >= 0 else 'red'}">{perf:+.2f}%</td>
                    </tr>
                </tbody>
            </table>

            <h3 style="border-bottom: 2px solid #333; padding-bottom: 5px; margin-top:30px;">2. MOUVEMENTS HEBDOMADAIRES</h3>
            <table style="{table_style}">
                <thead>
                    <tr>
                        <th style="{th_style}">ACTIF</th>
                        <th style="{th_style}">PRIX (EUR)</th>
                        <th style="{th_style}">VAR. 7J (%)</th>
                    </tr>
                </thead>
                <tbody>{h_html}</tbody>
            </table>

            <h3 style="border-bottom: 2px solid #333; padding-bottom: 5px; margin-top:30px;">3. POSITIONS & RENDEMENTS</h3>
            <table style="{table_style}">
                <thead>
                    <tr>
                        <th style="{th_style}">ACTIF</th>
                        <th style="{th_style}">PRU TOTAL</th>
                        <th style="{th_style}">GAIN (EUR)</th>
                        <th style="{th_style}">PERF (%)</th>
                    </tr>
                </thead>
                <tbody>{g_html}</tbody>
            </table>

            <div style="margin-top:30px; text-align:center;">
                <a href="{dash_url}" style="background-color:#ff793f; color:white; padding:15px 30px; text-decoration:none; font-weight:bold; border-radius:3px; display:inline-block;">
                    ACCÉDER AU TERMINAL INTERACTIF &rarr;
                </a>
            </div>

            <p style="text-align:center; font-size:10px; color:#999; margin-top:20px;">
                Données fournies par Yahoo Finance. Généré automatiquement via GitHub Actions.
            </p>
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