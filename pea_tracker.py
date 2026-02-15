import yfinance as yf
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import smtplib
import os
from datetime import datetime
from email.message import EmailMessage

# --- CONFIGURATION DU PORTEFEUILLE ---
MONTHLY_INVESTMENTS = {
    "ESE.PA": 250, "ETZ.PA": 140, "PAASI.PA": 60, "AI.PA": 0, "TTE.PA": 0
}
TICKERS = list(MONTHLY_INVESTMENTS.keys())
STATE_FILE = "portfolio_state.csv"
HISTORY_FILE = "pea_history.csv"


def get_portfolio_state():
    if os.path.exists(STATE_FILE):
        return pd.read_csv(STATE_FILE, index_col="Ticker")
    data = {t: {"Quantity": 0.0, "Total_Invested": 0.0, "Last_Purchase_Month": 0} for t in TICKERS}
    return pd.DataFrame.from_dict(data, orient='index')


def update_portfolio(state, prices):
    today = datetime.now()
    updated = False
    if today.day >= 16:
        for t, amount in MONTHLY_INVESTMENTS.items():
            if amount > 0 and state.loc[t, "Last_Purchase_Month"] != today.month:
                qty = amount / prices[t]
                state.loc[t, "Quantity"] += qty
                state.loc[t, "Total_Invested"] += amount
                state.loc[t, "Last_Purchase_Month"] = today.month
                updated = True
    if updated: state.to_csv(STATE_FILE)
    return state


def create_visuals():
    if not os.path.exists(HISTORY_FILE): return False
    df = pd.read_csv(HISTORY_FILE)
    if len(df) < 2: return False

    # 1. Graphique Statique Global
    sns.set_theme(style="whitegrid")
    plt.figure(figsize=(10, 5))
    sns.lineplot(data=df, x='Date', y='Total_Return_Pct', color='#2c3e50', linewidth=2)
    plt.title("Evolution de la performance globale (%)", fontsize=12, fontweight='bold')
    plt.ylabel("Performance (%)")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig("chart.png", dpi=120)
    plt.close()

    # 2. Planche de graphiques individuels (PNG pour mobile)
    fig, axes = plt.subplots(len(TICKERS), 1, figsize=(10, 3 * len(TICKERS)))
    if len(TICKERS) == 1: axes = [axes]
    for i, t in enumerate(TICKERS):
        sns.lineplot(data=df, x='Date', y=t, ax=axes[i], color='#2c3e50')
        axes[i].set_title(f"Historique Prix : {t}", fontsize=10, fontweight='bold')
        axes[i].set_ylabel("EUR")
        axes[i].tick_params(axis='x', rotation=45)
    plt.tight_layout()
    plt.savefig("details.png", dpi=100)
    plt.close()

    # 3. Tableau de bord interactif (HTML pour PC)
    plotly_fig = make_subplots(rows=1, cols=1)
    plotly_fig.add_trace(
        go.Scatter(x=df['Date'], y=df['Total_Value'], name="Valeur PEA", fill='tonexty', line=dict(color='#2c3e50')))
    plotly_fig.update_layout(template="plotly_white", title="Analyse Patrimoniale")
    plotly_fig.write_html("dashboard_interactif.html")
    return True


def run_tracker():
    state = get_portfolio_state()
    prices = {}
    h_rows, g_rows = "", ""
    total_v, total_i = 0, 0

    for t in TICKERS:
        h = yf.Ticker(t).history(period="5d")
        p = h['Close'].iloc[-1]
        prices[t] = p
        perf_7j = ((p - h['Close'].iloc[0]) / h['Close'].iloc[0]) * 100
        h_rows += f"<tr><td>{t}</td><td>{p:.2f}</td><td>{perf_7j:+.2f}%</td></tr>"

    state = update_portfolio(state, prices)
    hist_row = {"Date": datetime.now().strftime("%Y-%m-%d")}

    for t in TICKERS:
        p = prices[t]
        qty, inv = state.loc[t, "Quantity"], state.loc[t, "Total_Invested"]
        val = qty * p
        total_v += val
        total_i += inv
        hist_row[t] = round(p, 2)
        p_tot = ((val - inv) / inv * 100) if inv > 0 else 0
        g_rows += f"<tr><td>{t}</td><td>{inv:.2f}</td><td>{(val - inv):+.2f}</td><td>{p_tot:+.2f}%</td></tr>"

    perf_g = round(((total_v - total_i) / total_i * 100), 2) if total_i > 0 else 0
    hist_row.update({"Total_Invested": round(total_i, 2), "Total_Value": round(total_v, 2), "Total_Return_Pct": perf_g})

    pd.concat([pd.read_csv(HISTORY_FILE), pd.DataFrame([hist_row])]).to_csv(HISTORY_FILE, index=False)
    return h_rows, g_rows, perf_g, round(total_v, 2), round(total_i, 2)


def send_email(h_html, g_html, perf, val, invested):
    gain_abs = val - invested
    msg = EmailMessage()
    msg['Subject'] = f"Rapport PEA - {datetime.now().strftime('%d/%m/%Y')}"
    msg['From'] = os.environ['EMAIL_USER']
    msg['To'] = os.environ['EMAIL_RECEIVER']

    cid_global = "perf_global"
    cid_details = "perf_details"

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333; padding: 20px; line-height: 1.5;">
        <h2 style="border-bottom: 1px solid #333; padding-bottom: 10px;">Suivi du Portefeuille PEA</h2>

        <div style="background-color: #f9f9f9; padding: 15px; border: 1px solid #eee; border-radius: 5px; margin-bottom: 20px;">
            <p style="margin: 2px 0;">Valeur totale : <strong>{val:.2f} EUR</strong></p>
            <p style="margin: 2px 0;">Total investi : <strong>{invested:.2f} EUR</strong></p>
            <p style="margin: 2px 0;">Performance globale : <strong>{perf:+.2f}%</strong></p>
            <p style="margin: 2px 0;">Rendement net : <strong style="color: {'#27ae60' if gain_abs >= 0 else '#e74c3c'};">{gain_abs:+.2f} EUR</strong></p>
        </div>

        <h3 style="font-size: 16px;">Variation court terme (7j)</h3>
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse; width: 100%; font-size: 14px;">
            <tr style="background-color: #f2f2f2;"><th>Actif</th><th>Prix (EUR)</th><th>Variation (%)</th></tr>
            {h_html}
        </table>

        <h3 style="font-size: 16px; margin-top: 20px;">Performance historique par ligne</h3>
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse; width: 100%; font-size: 14px;">
            <tr style="background-color: #f2f2f2;"><th>Actif</th><th>Investi (EUR)</th><th>Gain/Perte (EUR)</th><th>Perf (%)</th></tr>
            {g_html}
        </table>

        <h3 style="font-size: 16px; margin-top: 20px;">Evolution Globale (%)</h3>
        <img src="cid:{cid_global}" style="width: 100%; max-width: 600px;">

        <h3 style="font-size: 16px; margin-top: 20px;">Historique par Actif (Prix)</h3>
        <img src="cid:{cid_details}" style="width: 100%; max-width: 600px;">

        <p style="font-size: 11px; color: #666; margin-top: 20px; border-top: 1px solid #eee; padding-top: 10px;">Rapport genere automatiquement.</p>
    </body>
    </html>"""

    msg.add_alternative(html, subtype='html')

    # Intégration des deux images
    for cid, filename in [(cid_global, "chart.png"), (cid_details, "details.png")]:
        with open(filename, 'rb') as img:
            msg.get_payload()[0].add_related(img.read(), maintype='image', subtype='png', cid=f"<{cid}>")

    if os.path.exists("dashboard_interactif.html"):
        with open("dashboard_interactif.html", "rb") as f:
            msg.add_attachment(f.read(), maintype='text', subtype='html', filename="Analyse_PC.html")

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
        s.login(os.environ['EMAIL_USER'], os.environ['EMAIL_PASS'])
        s.send_message(msg)


if __name__ == "__main__":
    h, g, p, v, i = run_tracker()
    create_visuals()
    send_email(h, g, p, v, i)