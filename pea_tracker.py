import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import smtplib
import os
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid

# --- CONFIGURATION ---
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


def create_chart():
    if not os.path.exists(HISTORY_FILE): return False
    df = pd.read_csv(HISTORY_FILE)
    if len(df) < 2: return False
    plt.figure(figsize=(10, 5))
    plt.plot(df['Date'], df['Total_Return_Pct'], color='#2c3e50', linewidth=1.5)
    plt.title("Evolution de la performance globale (%)", fontsize=12)
    plt.grid(True, linestyle=':', alpha=0.5)
    plt.tight_layout()
    plt.savefig("chart.png")
    plt.close()
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

    hist_row.update({"Total_Invested": round(total_i, 2), "Total_Value": round(total_v, 2),
                     "Total_Return_Pct": round(((total_v - total_i) / total_i * 100), 2) if total_i > 0 else 0})

    df_new = pd.DataFrame([hist_row])
    if not os.path.exists(HISTORY_FILE):
        df_new.to_csv(HISTORY_FILE, index=False)
    else:
        pd.concat([pd.read_csv(HISTORY_FILE), df_new]).to_csv(HISTORY_FILE, index=False)

    return h_rows, g_rows, hist_row["Total_Return_Pct"], hist_row["Total_Value"]


def send_email(h_html, g_html, perf, val):
    msg = EmailMessage()
    msg['Subject'] = f"Rapport PEA - {datetime.now().strftime('%d/%m/%Y')}"
    msg['From'] = os.environ['EMAIL_USER']
    msg['To'] = os.environ['EMAIL_RECEIVER']
    c_id = make_msgid()

    html = f"""
    <html>
    <body style="font-family: 'Helvetica', 'Arial', sans-serif; color: #333; line-height: 1.6;">
        <h2 style="border-bottom: 1px solid #333; padding-bottom: 10px;">Suivi du Portefeuille PEA</h2>

        <p>Performance globale : <strong>{perf:+.2f}%</strong><br>Valeur liquidative totale : <strong>{val:.2f} EUR</strong></p>

        <h3>Variation court terme</h3>
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse; width: 100%;">
            <tr style="background-color: #f2f2f2;">
                <th>Actif</th><th>Prix de cloture (EUR)</th><th>Variation 7j (%)</th>
            </tr>
            {h_html}
        </table>

        <h3>Performance historique (Depuis achat)</h3>
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse; width: 100%;">
            <tr style="background-color: #f2f2f2;">
                <th>Actif</th><th>Total investi (EUR)</th><th>Plus-value latente (EUR)</th><th>Performance (%)</th>
            </tr>
            {g_html}
        </table>

        <h3>Graphique de performance</h3>
        <img src="cid:{c_id[1:-1]}" style="width: 100%; max-width: 600px; margin-top: 20px;">

        <p style="font-size: 11px; color: #666; margin-top: 30px; border-top: 1px solid #eee;">
            Rapport genere de maniere automatique. Sources : Yahoo Finance.
        </p>
    </body>
    </html>"""
    msg.add_alternative(html, subtype='html')
    with open("chart.png", 'rb') as f: msg.get_payload()[0].add_related(f.read(), 'image', 'png', cid=c_id)
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
        s.login(os.environ['EMAIL_USER'], os.environ['EMAIL_PASS'])
        s.send_message(msg)


if __name__ == "__main__":
    h, g, p, v = run_tracker()
    create_chart()
    send_email(h, g, p, v)