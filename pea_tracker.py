import yfinance as yf
import pandas as pd
import smtplib
import os
from datetime import datetime
from email.message import EmailMessage

# --- CONFIGURATION DES TICKERS ---
TICKERS = ["PAASI.PA", "ETZ.PA", "ESE.PA", "AI.PA", "TTE.PA"]
CSV_FILE = "pea_history.csv"


def format_perf(val):
    color = "#27ae60" if val >= 0 else "#e74c3c"
    sign = "+" if val >= 0 else ""
    return f'<span style="color: {color}; font-weight: bold;">{sign}{val:.2f}%</span>'


def run_tracker():
    date_today = datetime.now().strftime("%Y-%m-%d")
    row_data = {"Date": date_today}
    table_rows_html = ""

    for ticker in TICKERS:
        stock = yf.Ticker(ticker)
        # On prend 2 ans pour avoir assez de recul pour le calcul annuel
        hist = stock.history(period="2y")

        if hist.empty: continue

        current_price = hist['Close'].iloc[-1]

        # 1. Préparation de la ligne pour le CSV
        row_data[ticker] = round(current_price, 2)

        # 2. Calcul des perfs pour le mail
        # (On utilise des indices fixes pour simuler les périodes boursières)
        perf_7j = ((current_price - hist['Close'].iloc[-5]) / hist['Close'].iloc[-5]) * 100
        perf_1m = ((current_price - hist['Close'].iloc[-21]) / hist['Close'].iloc[-21]) * 100
        perf_1y = ((current_price - hist['Close'].iloc[-252]) / hist['Close'].iloc[-252]) * 100

        table_rows_html += f"""
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #eee;"><b>{ticker}</b></td>
            <td style="padding: 10px; border-bottom: 1px solid #eee;">{current_price:.2f} €</td>
            <td style="padding: 10px; border-bottom: 1px solid #eee;">{format_perf(perf_7j)}</td>
            <td style="padding: 10px; border-bottom: 1px solid #eee;">{format_perf(perf_1m)}</td>
            <td style="padding: 10px; border-bottom: 1px solid #eee;">{format_perf(perf_1y)}</td>
        </tr>
        """

    # --- SAUVEGARDE DANS LE CSV (Format Large) ---
    df_new = pd.DataFrame([row_data])
    if not os.path.isfile(CSV_FILE):
        df_new.to_csv(CSV_FILE, index=False)
    else:
        # On s'assure que les colonnes sont dans le bon ordre lors de l'ajout
        df_old = pd.read_csv(CSV_FILE)
        df_final = pd.concat([df_old, df_new], ignore_index=True)
        df_final.to_csv(CSV_FILE, index=False)

    return table_rows_html


def send_email(table_body):
    msg = EmailMessage()
    msg['Subject'] = f"🚀 Ton Rapport PEA - {datetime.now().strftime('%d/%m/%Y')}"
    msg['From'] = os.environ['EMAIL_USER']
    msg['To'] = os.environ['EMAIL_RECEIVER']

    content = f"""
    <html>
    <body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #f4f7f6; padding: 20px;">
        <div style="max-width: 600px; margin: auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.1);">
            <h2 style="color: #2c3e50; text-align: center; border-bottom: 2px solid #3498db; padding-bottom: 10px;">PEA Tracker Pro</h2>
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="text-align: left; color: #7f8c8d; font-size: 0.9em;">
                        <th style="padding: 10px;">ACTIF</th>
                        <th style="padding: 10px;">PRIX</th>
                        <th style="padding: 10px;">HEBDO</th>
                        <th style="padding: 10px;">MOIS</th>
                        <th style="padding: 10px;">1 AN</th>
                    </tr>
                </thead>
                <tbody>
                    {table_body}
                </tbody>
            </table>
            <p style="margin-top: 25px; font-size: 0.8em; color: #bdc3c7; text-align: center;">
                Données Yahoo Finance • Mis à jour le {datetime.now().strftime('%d/%m/%Y %H:%M')}
            </p>
        </div>
    </body>
    </html>
    """
    msg.add_alternative(content, subtype='html')

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(os.environ['EMAIL_USER'], os.environ['EMAIL_PASS'])
        smtp.send_message(msg)


if __name__ == "__main__":
    html_rows = run_tracker()
    send_email(html_rows)