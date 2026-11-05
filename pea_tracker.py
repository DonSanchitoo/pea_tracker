"""PEA Tracker : cours, paramètres live, opérations automatiques, dashboard, actus et mail.

Usage :
  python pea_tracker.py                    # mise à jour complète (pas de mail)
  python pea_tracker.py --mail auto        # + mail hebdo le lundi, mail « plans exécutés » le lendemain d'une exécution
  python pea_tracker.py --mail weekly|dca  # force un type de mail ; « test » = mail de test (hors calendrier)
  python pea_tracker.py --no-fetch         # aucun appel réseau : cache des cours, paramètres et actus
  python pea_tracker.py --preview DIR      # écrit le mail (HTML + PNG) dans DIR sans l'envoyer
"""
import argparse
import os
import sys

import pandas as pd

from tracker import catalog
from tracker import ledger as lg
from tracker import news as newsmod
from tracker import params as pm
from tracker import report
from tracker.analytics import Panel
from tracker.common import RECON_FILE, load_config, load_state, now_local, save_state
from tracker.prices import unadjusted, unadjusted_dividends, update_prices


def run(args):
    cfg = load_config()
    now = now_local(cfg)
    today = pd.Timestamp(now.date())
    fetch = not args.no_fetch

    # 0. Paramètres live (inflation, Livret A, prélèvements sociaux, €STR)
    live, warnings = pm.update_live(fetch)
    params = pm.resolve(cfg, live)
    warnings += catalog.update(fetch)  # instruments recherchables dans « Mes données » (hebdomadaire)

    # 1. Cours
    ledger = lg.load_ledger(cfg)
    active_plans = [p for p in cfg["plans"] if p.get("active", True) is not False]
    tickers = sorted((set(ledger["ticker"]) | {p["ticker"] for p in active_plans} | {cfg["benchmark"]["ticker"]})
                     & (set(cfg["assets"]) | {cfg["benchmark"]["ticker"]}))
    start = (ledger["date"].min() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    ohlc, actions, w = update_prices(tickers, start, fetch=fetch)
    warnings += w
    bench = unadjusted(ohlc, actions, cfg["benchmark"]["ticker"])
    trading_days = pd.DatetimeIndex(sorted(bench.index))
    by_ticker = {t: unadjusted(ohlc, actions, t) for t in tickers}

    # 2. Opérations automatiques : plans, dividendes, staking
    added = lg.auto_record_plans(cfg, ledger, by_ticker, trading_days, now)
    divs = {t: unadjusted_dividends(actions, t) for t in tickers}
    added += lg.auto_dividends(cfg, ledger, divs, today)
    added += lg.auto_staking(cfg, ledger, today)
    if added:
        lg.append_rows(added)
        for r in added:
            print(f"Ajout automatique : {r['date']} {r['type']} {r['ticker']} {r['quantity']} / {r['amount']} €")
        ledger = lg.load_ledger(cfg)
    ledger, planned = lg.resolve_budget_orders(cfg, ledger, by_ticker, now)
    for w in warnings:
        print("ATTENTION :", w)

    # 3. Calculs, actus, dashboard
    panel = Panel(cfg, ledger, ohlc, actions, today)
    recon = pd.read_csv(RECON_FILE, dtype=str, keep_default_na=False) if os.path.exists(RECON_FILE) else None
    news = newsmod.update(cfg, panel, fetch=fetch)
    data = report.build(cfg, ledger, panel, recon, warnings, now, params=params, news=news, planned=planned)
    report.write_dashboard(data)
    report.write_history(panel)
    k = data["kpi"]
    print(f"Dashboard généré ({data['meta']['generated_at']}) : total {k['TOTAL']['value']:.2f} € | "
          f"PEA {k['PEA']['value']:.2f} € | crypto {k.get('CRYPTO', {}).get('value', 0):.2f} € | "
          f"{len(news.get('items', []))} actus")

    # 4. Mail
    kind, dca_date = decide_mail(args.mail, cfg, data, today, panel.trading_days)
    if kind or args.preview:
        from tracker import mailer
        kind = kind or "weekly"
        msg = mailer.build_message(cfg, data, panel, kind, added, dca_date)
        if args.preview:
            mailer.write_preview(msg, args.preview)
            print(f"Aperçu du mail ({kind}) écrit dans {args.preview}")
        else:
            mailer.send(msg)
            if kind == "test":  # un mail de test ne compte pas dans le calendrier
                print("Mail de test envoyé.")
                return 0
            st = load_state()
            if "weekly" in kind:
                st["last_weekly_mail"] = today.strftime("%Y-%m-%d")
            if "dca" in kind and dca_date is not None:
                st["last_dca_exec"] = dca_date.strftime("%Y-%m-%d")
            save_state(st)
            print(f"Mail envoyé ({kind}).")
    return 0


def last_execution(cfg, today, trading_days, max_days=4):
    """Dernière exécution de plan dans les `max_days` jours précédant aujourd'hui (exclu)."""
    best = None
    for p in cfg["plans"]:
        for ex in lg.plan_executions(p, today - pd.Timedelta(days=max_days), today - pd.Timedelta(days=1), trading_days):
            best = ex if best is None or ex > best else best
    return best


def decide_mail(mode, cfg, data, today, trading_days):
    """Retourne (type de mail ou None, date d'exécution des plans concernée)."""
    if mode in (None, "none"):
        return None, None
    ex = last_execution(cfg, today, trading_days)
    if mode == "test":
        plan_t = {p["ticker"] for p in cfg["plans"]}
        dates = [t["date"] for t in data["transactions"] if t["type"] == "BUY" and t["ticker"] in plan_t]
        return "test", (pd.Timestamp(max(dates)) if dates else None)
    if mode in ("weekly", "dca", "weekly+dca"):
        return mode, ex
    st = load_state()
    kinds = []
    if today.weekday() == 0 and st.get("last_weekly_mail") != today.strftime("%Y-%m-%d"):
        kinds.append("weekly")
    if ex is not None and st.get("last_dca_exec") != ex.strftime("%Y-%m-%d"):
        kinds.append("dca")
    return ("+".join(kinds) if kinds else None), ex


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mail", choices=["none", "auto", "weekly", "dca", "weekly+dca", "test"], default="none")
    p.add_argument("--no-fetch", action="store_true", help="aucun appel réseau, utiliser les caches")
    p.add_argument("--preview", metavar="DIR", help="écrire le mail dans DIR au lieu de l'envoyer")
    try:
        sys.exit(run(p.parse_args()))
    except lg.LedgerError as e:
        print(e)
        sys.exit(2)
