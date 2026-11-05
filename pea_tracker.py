"""PEA Tracker : met à jour les cours, enregistre les plans, régénère le dashboard, envoie le mail.

Usage :
  python pea_tracker.py                    # mise à jour cours + plans + dashboard (pas de mail)
  python pea_tracker.py --mail auto        # + mail hebdo le lundi, mail plan le lendemain de l'exécution
  python pea_tracker.py --mail weekly|dca  # force un type de mail
  python pea_tracker.py --no-fetch         # utilise uniquement le cache de cours
  python pea_tracker.py --preview DIR      # écrit le mail (HTML + PNG) dans DIR sans l'envoyer
"""
import argparse
import os
import sys

import pandas as pd

from tracker import ledger as lg
from tracker import report
from tracker.analytics import Panel
from tracker.common import RECON_FILE, load_config, load_state, now_local, save_state
from tracker.prices import unadjusted, update_prices


def run(args):
    cfg = load_config()
    now = now_local(cfg)
    today = pd.Timestamp(now.date())
    ledger = lg.load_ledger(cfg)
    tickers = sorted(set(ledger["ticker"]) | {p["ticker"] for p in cfg["plans"]} | {cfg["benchmark"]["ticker"]})
    start = (ledger["date"].min() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    ohlc, actions, warnings = update_prices(tickers, start, fetch=not args.no_fetch)
    for w in warnings:
        print("ATTENTION :", w)

    # 1. Plans d'épargne exécutés et pas encore saisis
    bench = unadjusted(ohlc, actions, cfg["benchmark"]["ticker"])
    trading_days = pd.DatetimeIndex(sorted(bench.index))
    by_ticker = {t: unadjusted(ohlc, actions, t) for t in tickers}
    added = lg.auto_record_plans(cfg, ledger, by_ticker, trading_days, now)
    if added:
        lg.append_rows(added)
        for r in added:
            print(f"Plan enregistré (AUTO) : {r['date']} {r['ticker']} {r['quantity']} pour {r['amount']} €")
        ledger = lg.load_ledger(cfg)

    # 2. Calculs + dashboard
    panel = Panel(cfg, ledger, ohlc, actions, today)
    recon = pd.read_csv(RECON_FILE, dtype=str, keep_default_na=False) if os.path.exists(RECON_FILE) else None
    data = report.build(cfg, ledger, panel, recon, warnings, now)
    report.write_dashboard(data)
    report.write_history(panel)
    k = data["kpi"]
    print(f"Dashboard généré ({data['meta']['generated_at']}) : total {k['TOTAL']['value']:.2f} € | "
          f"PEA {k['PEA']['value']:.2f} € | crypto {k.get('CRYPTO', {}).get('value', 0):.2f} €")

    # 3. Mail
    kind = decide_mail(args.mail, cfg, data, today)
    if kind or args.preview:
        from tracker import mailer
        kind = kind or "weekly"
        msg = mailer.build_message(cfg, data, panel, kind, added)
        if args.preview:
            mailer.write_preview(msg, args.preview)
            print(f"Aperçu du mail ({kind}) écrit dans {args.preview}")
        else:
            mailer.send(msg)
            st = load_state()
            if "weekly" in kind:
                st["last_weekly_mail"] = today.strftime("%Y-%m-%d")
            if "dca" in kind:
                st["last_dca_mail"] = today.strftime("%Y-%m")
            save_state(st)
            print(f"Mail envoyé ({kind}).")
    return 0


def decide_mail(mode, cfg, data, today):
    """Retourne None, 'weekly', 'dca' ou 'weekly+dca'."""
    if mode in (None, "none"):
        return None
    if mode in ("weekly", "dca", "weekly+dca"):
        return mode
    st = load_state()
    kinds = []
    if today.weekday() == 0 and st.get("last_weekly_mail") != today.strftime("%Y-%m-%d"):
        kinds.append("weekly")
    # mail plan : le premier jour ouvré qui suit l'exécution du mois (tolérance 4 jours si un run saute)
    plan_day = {p["ticker"]: int(p.get("day", 16)) for p in cfg["plans"]}
    month_buys = [t for t in data["transactions"] if t["type"] == "BUY"
                  and t["date"][:7] == today.strftime("%Y-%m")
                  and t["ticker"] in plan_day and int(t["date"][8:10]) >= plan_day[t["ticker"]]]
    if month_buys and st.get("last_dca_mail") != today.strftime("%Y-%m"):
        ex = max(pd.Timestamp(t["date"]) for t in month_buys)
        if ex < today and (today - ex).days <= 4:
            kinds.append("dca")
    return "+".join(kinds) if kinds else None


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mail", choices=["none", "auto", "weekly", "dca", "weekly+dca"], default="none")
    p.add_argument("--no-fetch", action="store_true", help="ne pas interroger Yahoo, utiliser le cache")
    p.add_argument("--preview", metavar="DIR", help="écrire le mail dans DIR au lieu de l'envoyer")
    try:
        sys.exit(run(p.parse_args()))
    except lg.LedgerError as e:
        print(e)
        sys.exit(2)
