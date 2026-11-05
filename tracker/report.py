"""Assemble toutes les données du dashboard et les écrit dans data/dashboard.js."""
import json
import math

import numpy as np
import pandas as pd

from . import analytics as an
from .common import DASHBOARD_JS, HISTORY_FILE


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        v = float(o)
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 6)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m-%d")
    return o


def _r2(series):
    return [round(float(v), 2) for v in series.values]


def _insights(cfg, panel, pos, plans, alloc, risk, recon, ghosts_pea):
    out = []
    al = cfg.get("alerts", {})
    eur = lambda v: f"{v:,.2f} €".replace(",", " ").replace(".", ",")
    pct = lambda v: f"{v * 100:.1f} %".replace(".", ",")

    for p in plans:
        if p.get("residual_pct") and p["residual_pct"] * 100 >= al.get("plan_residual_pct", 10):
            sug = " ou ".join(f"{s['amount']} € ({s['shares']} part{'s' if s['shares'] > 1 else ''})" for s in p["suggest"])
            out.append(dict(level="warn", id="plan-residuel", title=f"Plan {p['short']} : {eur(p['residual'])} non investis par mois",
                            text=f"Le PEA n'achète que des parts entières. À {eur(p['price'])} la part, tes {p['amount']} € "
                                 f"achètent {p['shares']} part{'s' if p['shares'] > 1 else ''} et laissent {pct(p['residual_pct'])} du montant de côté. "
                                 f"Montant conseillé : {sug} (marge de 2 % incluse)."))
    auto = panel.ledger[panel.ledger["source"] == "AUTO"]
    if len(auto):
        out.append(dict(level="info", id="auto", title=f"{len(auto)} opération(s) estimée(s) par le robot",
                        text="Les montants des plans du mois sont estimés. Remplace-les par le montant exact affiché dans TR "
                             "(colonne amount de data/transactions.csv) et passe la source à TR."))
    est = panel.ledger[panel.ledger["source"] == "ESTIME"]
    if len(est):
        out.append(dict(level="info", id="estime", title="Historique crypto partiellement estimé",
                        text="Les 2 transferts ETH entrants (date et quantité exactes inconnues) et le staking sont estimés. "
                             "La valeur et le coût actuels sont calés sur TR ; seule la courbe avant le 20/08/2026 est approximative."))
    rp = risk.get("PEA", {})
    if rp.get("dd_current") is not None and rp["dd_current"] * 100 <= al.get("drawdown_pct", -10):
        out.append(dict(level="alert", id="drawdown", title=f"PEA à {pct(rp['dd_current'])} de son plus haut",
                        text="Repli significatif. Aucun impact tant que tu ne vends pas : les plans achètent moins cher."))
    conc = alloc["concentration"]["pea"]
    if conc.get("top") and conc["top"] * 100 >= al.get("max_line_weight_pct", 90):
        out.append(dict(level="info", id="concentration", title="Une ligne dépasse 90 % du PEA",
                        text="Si c'est un ETF Monde, c'est une concentration de produit, pas de risque : il contient ~1 400 sociétés."))
    if ghosts_pea and ghosts_pea.get("bench_final"):
        diff = ghosts_pea["wealth_final"] - ghosts_pea["bench_final"]
        out.append(dict(level="good" if diff >= 0 else "info", id="fantome",
                        title=f"Tes choix vs 100 % MSCI World : {'+' if diff >= 0 else ''}{eur(diff)}",
                        text="Différence entre ton PEA réel (dividendes inclus) et le même argent, aux mêmes dates, placé uniquement "
                             "sur le MSCI World. Positif = tes lignes hors MSCI World (Asie, actions, trade iShares) ont rapporté plus."))
    fee = alloc["fee_year"]
    if fee > 0:
        out.append(dict(level="info", id="frais", title=f"Frais de gestion ETF : ≈ {eur(fee)} par an",
                        text=f"Frais courants moyens pondérés {alloc['ter_weighted']:.2f} %. Ils sont déjà déduits du cours, rien à payer en plus.".replace(".", ",", 1)))
    if recon is not None:
        out.append(dict(level="good" if recon["ok"] else "alert", id="recon",
                        title="Registre conforme à Trade Republic" if recon["ok"] else "Écart avec Trade Republic",
                        text=f"Contrôle du {pd.Timestamp(recon['date']).strftime('%d/%m/%Y')} : quantités, PRU et performances comparés aux écrans TR."))
    order = {"alert": 0, "warn": 1, "good": 2, "info": 3}
    return sorted(out, key=lambda x: order[x["level"]])


def _events(cfg, panel, plans, divs, fiscal):
    ev = []
    nxt = {}
    for p in plans:
        nxt.setdefault(p["next"], []).append(p)
    for d, ps in nxt.items():
        ev.append(dict(date=d, kind="plan", label="Exécution des plans",
                       detail=" + ".join(f"{p['short']} {p['amount']:g} €" for p in ps),
                       amount=sum(p["amount"] for p in ps)))
    for dv in divs["next"]:
        ev.append(dict(date=dv["ex_date"], kind="dividende", label=f"Détachement {dv['short']} (estimé)",
                       detail=f"≈ {dv['per_share']:.2f} € x {dv.get('qty', 0):g} action(s), versement quelques jours après".replace(".", ",", 1),
                       amount=dv["amount"]))
    ev.append(dict(date=fiscal["maturity"], kind="fiscal", label="PEA : 5 ans, exonération d'impôt sur le revenu",
                   detail="Seuls les prélèvements sociaux restent dus sur les gains", amount=None))
    return sorted(ev, key=lambda e: e["date"])


def build(cfg, ledger, panel, recon_df, warnings, now):
    rf = cfg["risk_free"]["rate"]
    scopes = [s for s in an.SCOPES if s in panel.s]
    pos = an.positions(panel)
    risk, risk_series, periods, monthly, xirr, ghosts_d = {}, {}, {}, {}, {}, {}
    for sc in scopes:
        risk[sc], risk_series[sc] = an.risk_metrics(panel, sc, rf)
        periods[sc] = an.period_table(panel, sc)
        monthly[sc] = an.monthly_returns(panel, sc)
        xirr[sc] = an.xirr_scope(panel, sc)
        if sc != "CRYPTO":
            ghosts_d[sc] = an.ghosts(panel, sc, rf)
    alloc = an.allocation(panel, pos)
    plans = an.plans_info(panel, pos)
    divs = an.dividend_info(panel, pos)
    for d in divs["next"]:
        d["qty"] = next(p["qty"] for p in pos if p["ticker"] == d["ticker"])
    fiscal = an.fiscal_info(panel)
    proj = an.projection(panel)
    recon = an.reconciliation(panel, recon_df)

    kpi = {}
    for sc in scopes:
        s = panel.s[sc]
        kpi[sc] = dict(
            value=float(s["V"].iloc[-1]), invested=float(s["invested"].iloc[-1]), cost=float(s["cost"].iloc[-1]),
            unreal=float(s["unreal"].iloc[-1]),
            unreal_pct=float(s["V"].iloc[-1] / s["cost"].iloc[-1] - 1) if s["cost"].iloc[-1] else None,
            realized=float(s["realized"].iloc[-1]), dividends=float(s["div"].iloc[-1]),
            pnl=float(s["pnl"].iloc[-1]),
            roi=float(s["pnl"].iloc[-1] / s["cash_in"].iloc[-1]) if s["cash_in"].iloc[-1] else None,
            cash_in=float(s["cash_in"].iloc[-1]),
            twr=risk[sc]["twr"], twr_ann=risk[sc]["twr_ann"], xirr=xirr[sc],
            start=s["start"].strftime("%Y-%m-%d"), asof=panel.asof_date(sc).strftime("%Y-%m-%d"),
            taxes=float(panel.tl["taxes"][panel.scope_tickers(sc)].iloc[-1].sum()),
        )

    series = dict(dates=[d.strftime("%Y-%m-%d") for d in panel.cal])
    for sc in scopes:
        s = panel.s[sc]
        series[sc] = dict(value=_r2(s["V"]), invested=_r2(s["invested"]), cost=_r2(s["cost"]), pnl=_r2(s["pnl"]),
                          twr=[round(float(v), 6) for v in s["I"].values], start=s["start"].strftime("%Y-%m-%d"))
    if panel.bench_ticker in panel.close:
        series["bench"] = [round(float(v), 4) for v in panel.close[panel.bench_ticker].values]
    series["by_line"] = {t: _r2(panel.value[t]) for t in panel.tickers}

    tx = []
    for r in ledger.itertuples(index=False):
        tx.append(dict(date=r.date.strftime("%Y-%m-%d"), account=r.account, type=r.type, ticker=r.ticker,
                       short=cfg["assets"][r.ticker]["short"], quantity=float(r.quantity), amount=float(r.amount),
                       taxes=float(r.taxes), source=r.source, note=r.note,
                       price=(float(r.amount) - float(r.taxes)) / float(r.quantity) if r.quantity and r.type in ("BUY", "SELL", "TRANSFER_IN") else None))
    tx.reverse()

    assets_meta = {t: dict(short=a["short"], name=a["name"], slot=a.get("slot", 8), account=a["account"])
                   for t, a in cfg["assets"].items()}

    data = dict(
        meta=dict(generated_at=now.strftime("%Y-%m-%d %H:%M"), today=panel.today.strftime("%Y-%m-%d"),
                  asof={sc: kpi[sc]["asof"] for sc in scopes}, dashboard_url=cfg.get("dashboard_url"),
                  warnings=warnings, benchmark=cfg["benchmark"]["label"], rf_label=cfg["risk_free"]["label"],
                  rf=rf, scopes=scopes),
        assets=assets_meta,
        kpi=kpi, risk=risk, risk_series=risk_series, periods=periods, monthly=monthly, ghosts=ghosts_d,
        series=series, positions=pos, position_series=an.position_series(panel),
        allocation=alloc, plans=plans, dividends=divs, fiscal=fiscal, projection=proj,
        reconciliation=recon, transactions=tx,
        insights=_insights(cfg, panel, pos, plans, alloc, risk, recon, ghosts_d.get("PEA")),
        events=_events(cfg, panel, plans, divs, fiscal),
    )
    return _clean(data)


def write_dashboard(data):
    with open(DASHBOARD_JS, "w", encoding="utf-8") as f:
        f.write("/* Généré automatiquement par pea_tracker.py : ne pas modifier à la main. */\n")
        f.write("window.PEA_DATA = ")
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        f.write(";\n")


def write_history(panel):
    rows = dict(date=[d.strftime("%Y-%m-%d") for d in panel.cal])
    for sc in an.SCOPES:
        if sc not in panel.s:
            continue
        s = panel.s[sc]
        p = sc.lower()
        rows[f"{p}_value"] = _r2(s["V"])
        rows[f"{p}_invested"] = _r2(s["invested"])
        rows[f"{p}_pnl"] = _r2(s["pnl"])
        rows[f"{p}_twr_pct"] = [round((float(v) - 1) * 100, 3) for v in s["I"].values]
    pd.DataFrame(rows).iloc[1:].to_csv(HISTORY_FILE, index=False)
