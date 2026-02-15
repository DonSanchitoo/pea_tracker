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
    # Calcul des données pour les graphiques de répartition
    labels = TICKERS
    values = [state.loc[t, "Quantity"] * prices[t] for t in TICKERS]
    gains = [(state.loc[t, "Quantity"] * prices[t]) - state.loc[t, "Total_Invested"] for t in TICKERS]

    # Création du Dashboard avec une structure complexe
    # Ligne 1 : KPIs et Répartition | Ligne 2 : Croissance | Ligne 3+ : Chandeliers
    fig = make_subplots(
        rows=len(TICKERS) + 2, cols=2,
        column_widths=[0.4, 0.6],
        row_heights=[0.4, 0.4] + [0.3] * len(TICKERS),
        specs=[[{"type": "domain"}, {"type": "scatter"}],
               [{"type": "bar"}, {"type": "scatter"}]] + [[{"type": "candlestick", "colspan": 2}, None]] * len(TICKERS),
        subplot_titles=("Répartition du PEA", "Croissance du Patrimoine (EUR)",
                        "Gain/Perte par Actif (EUR)", "Performance Globale (%)")
                       + tuple(f"Analyse Technique : {t}" for t in TICKERS),
        vertical_spacing=0.03
    )

    # 1. Pie Chart (Répartition)
    fig.add_trace(go.Pie(labels=labels, values=values, hole=.4,
                         marker=dict(colors=['#2c3e50', '#34495e', '#7f8c8d', '#95a5a6', '#bdc3c7'])), row=1, col=1)

    # 2. Courbe Valeur vs Investi
    fig.add_trace(
        go.Scatter(x=df['Date'], y=df['Total_Invested'], name="Investi", line=dict(color='grey', dash='dash')), row=1,
        col=2)
    fig.add_trace(
        go.Scatter(x=df['Date'], y=df['Total_Value'], name="Valeur", fill='tonexty', line=dict(color='#2c3e50')), row=1,
        col=2)

    # 3. Bar Chart (Gains par actif)
    fig.add_trace(go.Bar(x=labels, y=gains, marker_color=['#27ae60' if g > 0 else '#e74c3c' for g in gains]), row=2,
                  col=1)

    # 4. Courbe Perf %
    fig.add_trace(
        go.Scatter(x=df['Date'], y=df['Total_Return_Pct'], name="Perf %", line=dict(color='#27ae60', width=3)), row=2,
        col=2)

    # 5. Chandeliers (OHLC)
    for i, t in enumerate(TICKERS):
        hist = yf.Ticker(t).history(period="6mo")
        fig.add_trace(
            go.Candlestick(x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close']),
            row=i + 3, col=1)

    fig.update_layout(height=400 * (len(TICKERS) + 2), template="plotly_white", showlegend=False,
                      xaxis_rangeslider_visible=False, title_text="TABLEAU DE BORD PEA HAUTE PRÉCISION")
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
        h_rows += f"<tr><td>{t}</td><td>{p:.2f}</td><td>{perf_7j:+.2f}%</td></tr>"

    state = update_portfolio(state, prices)
    for t in TICKERS:
        qty, inv = state.loc[t, "Quantity"], state.loc[t, "Total_Invested"]
        val = qty * prices[t]
        total_v += val;
        total_i += inv
        p_tot = ((val - inv) / inv * 100) if inv > 0 else 0
        g_rows += f"<tr><td>{t}</td><td>{inv:.2f}</td><td>{(val - inv):+.2f}</td><td>{p_tot:+.2f}%</td></tr>"

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
    msg['Subject'] = f"Rapport PEA - {datetime.now().strftime('%d/%m/%Y')}"
    msg['From'] = os.environ['EMAIL_USER'];
    msg['To'] = os.environ['EMAIL_RECEIVER']
    dash_url = f"https://{os.environ['GITHUB_ACTOR']}.github.io/{os.environ['GITHUB_REPOSITORY'].split('/')[-1]}/"

    html = f"""
    <html><body style="font-family: Arial; color: #333; padding: 20px;">
        <h2 style="border-bottom: 1px solid #333; padding-bottom: 10px;">Synthese PEA</h2>
        <div style="background: #f9f9f9; padding: 15px; border-radius: 5px; margin-bottom: 20px; border: 1px solid #eee;">
            <p style="margin: 5px 0;">Valeur Totale : <strong>{val:.2f} EUR</strong> | Investi : <strong>{inv:.2f} EUR</strong></p>
            <table width="100%" style="text-align: center; border-top: 1px solid #ddd; margin-top: 10px;">
                <tr style="font-size: 12px; color: #666;"><th>7 Jours</th><th>Trimestre</th><th>Annuel</th><th>Global</th></tr>
                <tr style="font-size: 16px; font-weight: bold;">
                    <td style="color:{'green' if p7 >= 0 else 'red'}">{p7:+.2f}%</td>
                    <td style="color:{'green' if p90 >= 0 else 'red'}">{p90:+.2f}%</td>
                    <td style="color:{'green' if p365 >= 0 else 'red'}">{p365:+.2f}%</td>
                    <td style="color:{'green' if perf >= 0 else 'red'}">{perf:+.2f}%</td>
                </tr>
            </table>
        </div>
        <table border="1" width="100%" style="border-collapse: collapse; margin-bottom: 20px; font-size: 14px;">{h_html}</table>
        <table border="1" width="100%" style="border-collapse: collapse; font-size: 14px;">{g_html}</table>
        <div style="margin-top: 20px; text-align: center; background: #2c3e50; padding: 15px; border-radius: 5px;">
            <a href="{dash_url}" style="color: white; text-decoration: none; font-weight: bold;">CONSULTER LE DASHBOARD INTERACTIF</a>
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