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


def _insights(cfg, panel, pos, plans, alloc, risk, recon, ghosts_pea, reserve=None):
    out = []
    al = cfg.get("alerts", {})
    eur = lambda v: f"{v:,.2f} €".replace(",", " ").replace(".", ",")
    pct = lambda v: f"{v * 100:.1f} %".replace(".", ",")

    parts = lambda k: f"{k} part{'s' if k > 1 else ''}"
    for p in plans:
        if not p.get("active") or p.get("shares") is None:
            continue
        n, s1, s2 = p["shares"], p["suggest"][0], p["suggest"][1]
        marge = f"marge de {p['margin'] * 100:.0f} % = 2 fois la variation mensuelle habituelle de son cours, recalculée chaque jour"
        quand = f" le {pd.Timestamp(p['next']).strftime('%d/%m')}" if p.get("next") else ""
        if n == 0:
            out.append(dict(level="alert", id="plan-zero", title=f"Plan {p['short']} : aucune part achetée",
                            text=f"À {eur(p['price'])} la part, tes {p['amount']:g} € ne suffisent plus pour une part : rien ne sera acheté{quand}, "
                                 f"tout ira dans ta réserve. Montant conseillé : {s1['amount']} € ({parts(s1['shares'])}), {marge}."))
        elif n <= 2 and p["room"] < p["margin"]:
            out.append(dict(level="warn", id="plan-marge", title=f"Plan {p['short']} : marge trop juste",
                            text=f"À {eur(p['price'])} la part, tes {p['amount']:g} € achètent {parts(n)}. Si le cours monte de plus de "
                                 f"{pct(p['room'])} d'ici l'exécution{quand}, le plan " + (f"n'en achète que {n - 1}. " if n > 1 else "n'achète plus rien. ") +
                                 f"Montant conseillé : {s1['amount']} € ({parts(s1['shares'])}) ou {s2['amount']} € ({parts(s2['shares'])}), {marge}."))
        elif p.get("residual_pct") and p["residual_pct"] * 100 >= al.get("plan_residual_pct", 10):
            if p["amount"] >= s1["amount"]:
                conseil = (f"Ton montant garde une bonne marge : la part peut monter de {pct(p['room'])} avant que le plan achète une part de moins. "
                           f"Pour réduire le reliquat : {s1['amount']} € ({parts(n)}) ; pour {parts(n + 1)} : {s2['amount']} € ({marge}).")
            else:
                conseil = f"Montant conseillé : {s1['amount']} € ({parts(s1['shares'])}) ou {s2['amount']} € ({parts(s2['shares'])}), {marge}."
            out.append(dict(level="warn", id="plan-residuel", title=f"Plan {p['short']} : {eur(p['residual'])} non investis par mois",
                            text=f"Le PEA n'achète que des parts entières. À {eur(p['price'])} la part, tes {p['amount']:g} € achètent {parts(n)} ; "
                                 f"le reste ({pct(p['residual_pct'])}) n'est pas perdu, il va dans ta réserve de liquidité. {conseil}"))
    auto = panel.ledger[(panel.ledger["source"] == "AUTO") & (panel.ledger["type"] == "BUY")]
    if len(auto):
        out.append(dict(level="info", id="auto", title=f"{len(auto)} achat(s) estimé(s) par le robot à vérifier",
                        text="Montant estimé au cours du jour (nombre de parts fiable). Pour être au centime, ouvre « Mes données », "
                             "corrige le montant avec celui affiché dans TR et passe la source à TR."))
    est = panel.ledger[panel.ledger["source"] == "ESTIME"]
    if len(est):
        TYP = {"TRANSFER_IN": "transfert entrant", "TRANSFER_OUT": "transfert sortant", "BUY": "achat", "SELL": "vente",
               "DIVIDEND": "dividende", "BONUS": "bonus", "FEE": "frais", "STAKING": "staking"}
        ops = est[est["type"] != "STAKING"]
        stk = est[est["type"] == "STAKING"]
        accts = sorted(set(est["account"]))
        bits = [f"{TYP.get(r.type, r.type.lower())} {cfg['assets'].get(r.ticker, {}).get('short', r.ticker)} du {pd.Timestamp(r.date).strftime('%d/%m/%Y')}"
                for r in ops.itertuples(index=False)]
        txt = ""
        if bits:
            txt += ("Opération estimée (date ou quantité à confirmer) : " if len(bits) == 1 else "Opérations estimées (date ou quantité à confirmer) : ") + ", ".join(bits) + ". "
        if len(stk):
            txt += f"{len(stk)} versement{'s' if len(stk) > 1 else ''} de staking calculé{'s' if len(stk) > 1 else ''} au taux paramétré (le dernier le {pd.Timestamp(stk['date'].max()).strftime('%d/%m/%Y')}). "
        if len(ops):
            txt += f"La courbe avant le {pd.Timestamp(ops['date'].max()).strftime('%d/%m/%Y')} est approximative. "
        txt += "Pour être exact, corrige ces lignes avec les montants TR dans « Mes données » et passe leur source à TR."
        out.append(dict(level="info", id="estime",
                        title=f"{len(est)} ligne{'s' if len(est) > 1 else ''} estimée{'s' if len(est) > 1 else ''} dans le registre ({', '.join(a.lower() if a == 'CRYPTO' else a for a in accts)})",
                        text=txt))
    rp = risk.get("PEA", {})
    if rp.get("dd_current") is not None and rp["dd_current"] * 100 <= al.get("drawdown_pct", -10):
        out.append(dict(level="alert", id="drawdown", title=f"PEA à {pct(rp['dd_current'])} de son plus haut",
                        text="Repli significatif. Aucun impact tant que tu ne vends pas : les plans achètent moins cher."))
    conc = alloc["concentration"]["pea"]
    if conc.get("top") and conc["top"] * 100 >= al.get("max_line_weight_pct", 90):
        big = max((p for p in pos if p["open"] and p["account"] == "PEA"), key=lambda p: p["value"])
        world = "Monde" in (big.get("asset_class") or "")
        out.append(dict(level="info" if world else "warn", id="concentration",
                        title=f"{big['short']} pèse {pct(conc['top'])} du PEA",
                        text="C'est un ETF Monde : concentration de produit, pas de risque, il contient plus de 1 000 sociétés."
                        if world else "Une seule ligne porte presque tout le PEA : une forte baisse de cette ligne se verrait directement sur le total."))
    if ghosts_pea and ghosts_pea.get("bench_final"):
        diff = ghosts_pea["wealth_final"] - ghosts_pea["bench_final"]
        held = panel.ledger[(panel.ledger["account"] == "PEA") & (panel.ledger["type"].isin(["BUY", "SELL", "TRANSFER_IN"]))]["ticker"]
        others = ", ".join(dict.fromkeys(cfg["assets"][t]["short"] for t in held if t != cfg["benchmark"]["ticker"] and t in cfg["assets"])) or "aucune"
        out.append(dict(level="good" if diff >= 0 else "info", id="fantome",
                        title=f"Tes choix vs 100 % {cfg['benchmark'].get('short', cfg['benchmark']['label'])} : {'+' if diff >= 0 else ''}{eur(diff)}",
                        text="Différence entre ton PEA réel (dividendes inclus) et le même argent, aux mêmes dates, placé uniquement "
                             f"sur {cfg['benchmark']['label']}. Positif = tes autres lignes ({others}) ont rapporté plus."))
    fee = alloc["fee_year"]
    if fee > 0:
        out.append(dict(level="info", id="frais", title=f"Frais de gestion ETF : ≈ {eur(fee)} par an",
                        text=f"Frais courants moyens pondérés {alloc['ter_weighted']:.2f} %. Ils sont déjà déduits du cours, rien à payer en plus.".replace(".", ",", 1)))
    if recon is not None:
        rdate = pd.Timestamp(recon["date"])
        age = int((panel.today - rdate).days)
        since = panel.ledger[(panel.ledger["date"] > rdate) & (panel.ledger["type"].isin(["BUY", "SELL", "TRANSFER_IN", "TRANSFER_OUT"]))]
        stale = age > al.get("recon_max_days", 40)
        quand = "aujourd'hui" if age == 0 else f"il y a {age} jour{'s' if age > 1 else ''}"
        if not recon["ok"]:
            out.append(dict(level="alert", id="recon", title="Écart avec Trade Republic",
                            text=f"Contrôle du {rdate.strftime('%d/%m/%Y')} : au moins une quantité, un PRU ou une performance diffère des écrans TR. "
                                 "Détail dans Transactions, contrôle TR."))
        elif stale:
            out.append(dict(level="warn", id="recon", title=f"Contrôle TR à refaire (dernier {quand})",
                            text=f"Le registre était conforme à TR le {rdate.strftime('%d/%m/%Y')}, mais {len(since)} opération{'s ont' if len(since) > 1 else ' a'} eu lieu depuis, "
                                 f"non vérifiée{'s' if len(since) > 1 else ''}. Saisis un relevé TR dans « Mes données », onglet Relevé TR (2 minutes)."))
        else:
            out.append(dict(level="good", id="recon", title="Registre conforme à Trade Republic",
                            text=f"Contrôle du {rdate.strftime('%d/%m/%Y')} ({quand}) : quantités, PRU et performances comparés aux écrans TR."
                                 + (f" {len(since)} opération{'s' if len(since) > 1 else ''} depuis, à vérifier au prochain relevé." if len(since) else "")))
    if reserve:
        best = [b for b in reserve["buyable"] if b["shares"] > 0]
        txt = (" · ".join(f"{b['shares']} part{'s' if b['shares'] > 1 else ''} {de(b['short'])}" for b in best[:3])
               if best else "pas encore de quoi acheter une part")
        out.append(dict(level="good" if best else "info", id="reserve", title=f"Réserve de liquidité PEA : {eur(reserve['balance'])}",
                        text=f"Disponible pour un achat ponctuel : {txt}. Elle grossit d'environ {eur(reserve['monthly_estimate'])} par mois "
                             "avec les reliquats de tes plans."))
    order = {"alert": 0, "warn": 1, "good": 2, "info": 3}
    return sorted(out, key=lambda x: order[x["level"]])


def de(name):
    """« de PEA Monde » / « d'Asie Émergente »."""
    return ("d'" if name[:1].upper() in "AEIOUYÉÈÊH" else "de ") + name


def top_news(items, pos, plans, k=5, days=7):
    """Le vrai top 5 de la semaine sur tes positions : réputation de la source, fraîcheur, pertinence,
    pondérés par le poids de la ligne dans ton portefeuille ; 2 articles max par ligne et par source."""
    from datetime import datetime, timedelta, timezone
    limit = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    weight = {p["ticker"]: p["weight_total"] for p in pos if p["open"]}
    for pl in plans:
        if pl.get("active"):
            weight.setdefault(pl["ticker"], 0.02)
    def rank(n):
        w = max([weight.get(t, 0) for t in n["tickers"]] or [0])
        return n["score"] + 8 * w ** 0.5 + (2 if len([t for t in n["tickers"] if t in weight]) > 1 else 0)
    mine = sorted([n for n in items if n["date"] >= limit and any(t in weight for t in n["tickers"])], key=rank, reverse=True)
    out, per_line, per_src = [], {}, {}
    for n in mine:
        main = max((t for t in n["tickers"] if t in weight), key=lambda t: weight[t])
        if per_line.get(main, 0) >= 2 or per_src.get(n["source"], 0) >= 2:
            continue
        out.append(dict(n, main=main))
        per_line[main] = per_line.get(main, 0) + 1
        per_src[n["source"]] = per_src.get(n["source"], 0) + 1
        if len(out) == k:
            break
    if len(out) < k:
        for n in sorted([n for n in items if n["date"] >= limit and n not in mine], key=lambda x: -x["score"]):
            out.append(dict(n, main=n["tickers"][0]))
            if len(out) == k:
                break
    return out


def _events(cfg, panel, plans, divs, fiscal, planned):
    ev = []
    nxt = {}
    for p in plans:
        if p.get("next"):
            nxt.setdefault(p["next"], []).append(p)
    for d, ps in nxt.items():
        ev.append(dict(date=d, kind="plan", label="Exécution des plans",
                       detail=" + ".join(f"{p['short']} {p['amount']:g} €" for p in ps),
                       amount=sum(p["amount"] for p in ps)))
    for o in planned:
        ev.append(dict(date=o["date"], kind="ordre", label=f"Versement prévu : {cfg['assets'][o['ticker']]['short']}",
                       detail=o.get("note") or "Achat au montant, quantité calculée le jour venu", amount=o["amount"]))
    for dv in divs["next"]:
        ev.append(dict(date=dv["ex_date"], kind="dividende", label=f"Détachement {dv['short']} (estimé)",
                       detail=f"≈ {dv['per_share']:.2f} € × {dv.get('qty', 0):g} action{'s' if dv.get('qty', 0) > 1 else ''}, versé 2 jours ouvrés après".replace(".", ",", 1),
                       amount=dv["amount"]))
    ev.append(dict(date=fiscal["maturity"], kind="fiscal", label="PEA : 5 ans, exonération d'impôt sur le revenu",
                   detail="Seuls les prélèvements sociaux restent dus sur les gains", amount=None))
    return sorted(ev, key=lambda e: e["date"])


PRESETS = [
    {"ticker": "PUST.PA", "name": "Amundi PEA Nasdaq-100 UCITS ETF Acc", "short": "Nasdaq-100", "isin": "FR0011871110", "account": "PEA", "kind": "ETF",
     "asset_class": "Actions Monde (ETF)", "ter": 0.30, "zones": {"Amérique du Nord": 98, "Autres": 2}, "news": {"fr": "Nasdaq", "en": "Nasdaq 100 OR \"Nasdaq Composite\""}},
    {"ticker": "PSP5.PA", "name": "Amundi PEA S&P 500 UCITS ETF Acc", "short": "S&P 500", "isin": "FR0011871128", "account": "PEA", "kind": "ETF",
     "asset_class": "Actions Monde (ETF)", "ter": 0.15, "zones": {"Amérique du Nord": 100}, "news": {"fr": "\"S&P 500\" OR \"Wall Street\"", "en": "\"S&P 500\""}},
    {"ticker": "ESE.PA", "name": "BNP Paribas Easy S&P 500 UCITS ETF EUR C", "short": "S&P 500 (BNP)", "isin": "FR0011550185", "account": "PEA", "kind": "ETF",
     "asset_class": "Actions Monde (ETF)", "ter": 0.15, "zones": {"Amérique du Nord": 100}, "news": {"fr": "\"S&P 500\" OR \"Wall Street\"", "en": "\"S&P 500\""}},
    {"ticker": "ETZ.PA", "name": "BNP Paribas Easy Stoxx Europe 600 UCITS ETF EUR C", "short": "Europe 600", "isin": "FR0011550193", "account": "PEA", "kind": "ETF",
     "asset_class": "Actions Europe (ETF)", "ter": 0.20, "zones": {"Europe": 100}, "news": {"fr": "\"Stoxx 600\" OR \"bourses européennes\"", "en": "\"Stoxx 600\" OR \"European stocks\""}},
    {"ticker": "PCEU.PA", "name": "Amundi PEA MSCI Europe UCITS ETF Acc", "short": "MSCI Europe", "isin": "", "account": "PEA", "kind": "ETF",
     "asset_class": "Actions Europe (ETF)", "ter": 0.15, "zones": {"Europe": 100}, "news": {"fr": "\"bourses européennes\"", "en": "\"European stocks\""}},
    {"ticker": "C40.PA", "name": "Amundi CAC 40 ESG UCITS ETF DR (C)", "short": "CAC 40", "isin": "FR0007052782", "account": "PEA", "kind": "ETF",
     "asset_class": "Actions françaises", "ter": 0.25, "zones": {"France": 100}, "news": {"fr": "\"CAC 40\"", "en": "\"CAC 40\""}},
    {"ticker": "PAEEM.PA", "name": "Amundi PEA Émergent (MSCI Emerging) UCITS ETF Acc", "short": "Émergents", "isin": "FR0013412020", "account": "PEA", "kind": "ETF",
     "asset_class": "Actions Asie émergente (ETF)", "ter": 0.30, "zones": {"Chine": 25, "Taïwan": 20, "Inde": 19, "Corée du Sud": 10, "Autres émergents": 26},
     "news": {"fr": "\"pays émergents\" OR \"marchés émergents\"", "en": "\"emerging markets\""}},
    {"ticker": "PTPXE.PA", "name": "Amundi PEA Japon (TOPIX) UCITS ETF Acc", "short": "Japon", "isin": "", "account": "PEA", "kind": "ETF",
     "asset_class": "Actions Monde (ETF)", "ter": 0.20, "zones": {"Japon": 100}, "news": {"fr": "\"Bourse de Tokyo\" OR Nikkei", "en": "Nikkei OR \"Japanese stocks\""}},
    {"ticker": "CW8.PA", "name": "Amundi MSCI World Swap UCITS ETF EUR Acc", "short": "MSCI World (CW8)", "isin": "LU1681043599", "account": "PEA", "kind": "ETF",
     "asset_class": "Actions Monde (ETF)", "ter": 0.38, "zones": {"Amérique du Nord": 74, "Europe": 16, "Japon": 5.5, "Pacifique développé": 2.5, "Autres": 2},
     "news": {"fr": "\"MSCI World\"", "en": "\"MSCI World\""}},
    {"ticker": "BTC-EUR", "name": "Bitcoin", "short": "Bitcoin", "isin": "", "account": "CRYPTO", "kind": "Crypto",
     "asset_class": "Crypto-actifs", "ter": 0, "zones": {"Crypto (hors zone)": 100}, "news": {"fr": "Bitcoin", "en": "Bitcoin price OR \"bitcoin ETF\""}},
    {"ticker": "SOL-EUR", "name": "Solana", "short": "Solana", "isin": "", "account": "CRYPTO", "kind": "Crypto",
     "asset_class": "Crypto-actifs", "ter": 0, "zones": {"Crypto (hors zone)": 100}, "news": {"fr": "Solana", "en": "Solana price"}},
]


def build(cfg, ledger, panel, recon_df, warnings, now, params=None, news=None, planned=None, expo=None):
    planned = planned or []
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
    alloc = an.allocation(panel, pos, expo)
    plans = an.plans_info(panel, pos)
    divs = an.dividend_info(panel, pos)
    for d in divs["next"]:
        d["qty"] = next(p["qty"] for p in pos if p["ticker"] == d["ticker"])
    fiscal = an.fiscal_info(panel)
    sim = an.sim_defaults(panel, pos)
    reserve = an.cash_reserve(panel, pos)
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
                       taxes=float(r.taxes), source=r.source, note=r.note, funding=getattr(r, "funding", ""),
                       price=(float(r.amount) - float(r.taxes)) / float(r.quantity) if r.quantity and r.type in ("BUY", "SELL", "TRANSFER_IN") else None))
    tx.reverse()

    assets_meta = {t: dict(short=a["short"], name=a["name"], slot=a.get("slot", 8), account=a["account"])
                   for t, a in cfg["assets"].items()}
    # configuration éditable depuis le dashboard (sans les blocs calculés à l'exécution)
    editable = {k: v for k, v in cfg.items() if k not in ("tax", "risk_free", "inflation")}

    staking = []
    for t, a in cfg["assets"].items():
        st = a.get("staking") or {}
        if st.get("rate"):
            q = float(ledger[(ledger["ticker"] == t) & (ledger["type"] == "STAKING")]["quantity"].sum())
            p = next((x for x in pos if x["ticker"] == t), None)
            staking.append(dict(ticker=t, short=a["short"], rate=st["rate"], since=st.get("since"), qty=q,
                                value=q * p["price"] if p else None))

    news = news or {"items": []}
    data = dict(
        meta=dict(generated_at=now.strftime("%Y-%m-%d %H:%M"), today=panel.today.strftime("%Y-%m-%d"),
                  asof={sc: kpi[sc]["asof"] for sc in scopes}, dashboard_url=cfg.get("dashboard_url"),
                  repo=cfg.get("repo", "DonSanchitoo/pea_tracker"),
                  warnings=warnings, benchmark=cfg["benchmark"]["label"], rf_label=cfg["risk_free"]["label"],
                  rf=rf, scopes=scopes, inflation=cfg.get("inflation")),
        assets=assets_meta,
        kpi=kpi, risk=risk, risk_series=risk_series, periods=periods, monthly=monthly, ghosts=ghosts_d,
        series=series, positions=pos, position_series=an.position_series(panel),
        allocation=alloc, plans=plans, dividends=divs, fiscal=fiscal, sim=sim, staking=staking,
        reconciliation=recon, transactions=tx, planned=planned, reserve=reserve,
        params=params or {}, config=editable, presets=PRESETS,
        safety={t: round(an.safety_margin(panel, t), 4) for t in cfg["assets"]},
        news=dict(updated_at=news.get("updated_at"), items=news.get("items", [])[:120],
                  top=top_news(news.get("items", []), pos, plans)),
        insights=_insights(cfg, panel, pos, plans, alloc, risk, recon, ghosts_d.get("PEA"), reserve),
        events=_events(cfg, panel, plans, divs, fiscal, planned),
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
