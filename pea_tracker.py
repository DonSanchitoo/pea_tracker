import yfinance as yf
import pandas as pd
import smtplib
import os
from datetime import datetime, timedelta
from email.message import EmailMessage
# IMPORT DU NOUVEAU MOTEUR
import dashboard_engine as dash_v2

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

    # Récupération données + Tableau Marché (Mail)
    for t in TICKERS:
        h = yf.Ticker(t).history(period="1y")
        p = h['Close'].iloc[-1]
        prices[t] = p
        perf_7j = ((p - h['Close'].iloc[-5]) / h['Close'].iloc[-5]) * 100
        color = "#009933" if perf_7j >= 0 else "#cc0000"
        h_rows += f"<tr><td style='border-bottom:1px solid #ddd; padding:8px;'><b>{t}</b></td><td style='border-bottom:1px solid #ddd; padding:8px;'>{p:.2f} €</td><td style='border-bottom:1px solid #ddd; padding:8px; color:{color};'><b>{perf_7j:+.2f}%</b></td></tr>"

    state = update_portfolio(state, prices)

    # Calculs Portefeuille + Tableau Positions (Mail)
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

    # Mise à jour historique
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

    # On garde ton style Mail "Pro" validé précédemment
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
                    <th width="25%">7 JOURS</th><th width="25%">TRIMESTRE</th><th width="25%">1 AN</th><th width="25%" style="background-color:#ff9f43;">GLOBAL</th>
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
                <a href="{dash_url}" style="background-color:#1a1a1a; color:white; padding:12px 25px; text-decoration:none; font-family:'Courier New', monospace; font-weight:bold; font-size:14px; border:1px solid #ff9f43;">>> Dashboard PEA</a>
            </div>
            <p style="text-align:center; font-size:10px; color:#999; margin-top:20px;">KPI (CAGR, MDD, PRU) sur le dashboard.</p>
        </div>
    </body></html>"""
    msg.add_alternative(html, subtype='html')
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
        s.login(os.environ['EMAIL_USER'], os.environ['EMAIL_PASS']);
        s.send_message(msg)


if __name__ == "__main__":
    h, g, p, p7, p90, p365, v, inv, df, state, prices = run_tracker()

    # C'EST ICI QUE LA MAGIE OPERE : On appelle le moteur V2
    dash_v2.generate_dashboard_v2(df, state, prices)

    send_email(h, g, p, p7, p90, p365, v, inv)