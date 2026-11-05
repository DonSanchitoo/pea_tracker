"""Calculs du dashboard : séries journalières, performance, risque, allocation, projections.

Conventions (détaillées dans aide.html) :
- Valeur = quantité réellement détenue x cours de clôture réel (non ajusté des splits).
- Flux externes = achats + transferts entrants - ventes - transferts sortants.
- Rendement journalier TWR : r = (V_t + D_t - V_t-1 - F_t) / (V_t-1 + F_t), flux en début
  de journée (les plans TR s'exécutent le matin). D = dividendes encaissés (- frais).
- PRU « méthode Trade Republic » : (montant payé - TTF) / quantité, coût moyen pondéré.
"""
import math

import numpy as np
import pandas as pd

from .prices import unadjusted, unadjusted_dividends

SCOPES = ("TOTAL", "PEA", "CRYPTO")


# ----------------------------------------------------------------- helpers

def _xirr(flows):
    """flows : liste (date, montant), montant > 0 = argent reçu. Retourne le TRI annuel ou None."""
    flows = [(d, a) for d, a in flows if abs(a) > 1e-9]
    if len(flows) < 2:
        return None
    t0 = min(d for d, _ in flows)
    ts = np.array([(d - t0).days / 365.0 for d, _ in flows])
    am = np.array([a for _, a in flows])

    def npv(r):
        return float(np.sum(am / (1 + r) ** ts))

    lo, hi = -0.99, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7:
            break
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return mid


def _asof(series, when):
    """Valeur de la série à la date `when` (dernière valeur connue)."""
    s = series[series.index <= when]
    return float(s.iloc[-1]) if len(s) else float("nan")


def _drawdown_info(idx):
    peak = idx.cummax()
    dd = idx / peak - 1
    if dd.empty:
        return dd, {}
    trough = dd.idxmin()
    peak_date = idx[:trough].idxmax()
    rec = idx[trough:][idx[trough:] >= idx[peak_date]]
    recovery = rec.index[0] if len(rec) else None
    return dd, {
        "mdd": float(dd.min()),
        "peak": peak_date.strftime("%Y-%m-%d"),
        "trough": trough.strftime("%Y-%m-%d"),
        "recovery": recovery.strftime("%Y-%m-%d") if recovery is not None else None,
        "current": float(dd.iloc[-1]),
        "days_under": int((idx.index[-1] - idx[:idx.index[-1]].idxmax()).days) if dd.iloc[-1] < 0 else 0,
    }


# ----------------------------------------------------------------- panel

class Panel:
    """Toutes les séries journalières dérivées du registre et des cours."""

    def __init__(self, cfg, ledger, ohlc, actions, today):
        self.cfg = cfg
        self.ledger = ledger
        self.today = pd.Timestamp(today)
        self.assets = cfg["assets"]
        self.tickers = sorted(set(ledger["ticker"]))
        self.bench_ticker = cfg["benchmark"]["ticker"]
        start = ledger["date"].min()
        self.cal = pd.date_range(start - pd.Timedelta(days=1), self.today, freq="D")

        # cours réels par ticker (index = jours de cotation)
        plan_t = {p["ticker"] for p in cfg.get("plans", []) if p["ticker"] in cfg["assets"]}
        self.raw = {t: unadjusted(ohlc, actions, t) for t in set(self.tickers) | {self.bench_ticker} | plan_t}
        self.actions = actions
        close = {}
        for t, df in self.raw.items():
            s = df["close"] if len(df) else pd.Series(dtype=float)
            s = s.reindex(s.index.union(self.cal)).sort_index().ffill().bfill()
            close[t] = s.reindex(self.cal)
        self.close = pd.DataFrame(close)

        bidx = self.raw.get(self.bench_ticker)
        td = bidx.index if bidx is not None and len(bidx) else self.cal[self.cal.weekday < 5]
        self.trading_days = pd.DatetimeIndex(sorted(td))
        self._ledger_timelines()
        self._scope_series()

    # -- états par ligne (quantité, coût, réalisé...) après chaque opération
    def _ledger_timelines(self):
        st = {t: dict(qty=0.0, cost=0.0, realized=0.0, div=0.0, cash_in=0.0, cash_out=0.0, taxes=0.0)
              for t in self.tickers}
        recs = []
        for r in self.ledger.itertuples(index=False):
            s = st[r.ticker]
            q, a = float(r.quantity), float(r.amount)
            if r.type == "BUY":
                s["qty"] += q
                s["cost"] += a - float(r.taxes)
                s["cash_in"] += a
                s["taxes"] += float(r.taxes)
            elif r.type == "TRANSFER_IN":
                s["qty"] += q
                s["cost"] += a
                s["cash_in"] += a
            elif r.type in ("STAKING", "BONUS"):
                s["qty"] += q
            elif r.type in ("SELL", "TRANSFER_OUT"):
                out = s["cost"] * q / s["qty"] if s["qty"] else 0.0
                s["realized"] += a - out
                s["cost"] -= out
                s["qty"] -= q
                s["cash_out"] += a
            elif r.type == "DIVIDEND":
                s["div"] += a
            elif r.type == "FEE":
                s["div"] -= a
            s["qty"] = round(s["qty"], 9)
            if abs(s["qty"]) < 1e-9:
                s["qty"], s["cost"] = 0.0, 0.0
            recs.append(dict(date=r.date, ticker=r.ticker, **s))
        self.final_state = st
        rec = pd.DataFrame(recs)
        self.tl = {}
        for field in ("qty", "cost", "realized", "div", "cash_in", "cash_out", "taxes"):
            p = rec.pivot_table(index="date", columns="ticker", values=field, aggfunc="last")
            p = p.reindex(p.index.union(self.cal)).sort_index().ffill().reindex(self.cal).fillna(0.0)
            self.tl[field] = p.reindex(columns=self.tickers, fill_value=0.0)

        lg = self.ledger
        def daily(mask, sign=1.0):
            d = lg[mask].pivot_table(index="date", columns="ticker", values="amount", aggfunc="sum")
            return (d.reindex(self.cal).fillna(0.0) * sign).reindex(columns=self.tickers, fill_value=0.0)
        self.f_in = daily(lg["type"].isin(["BUY", "TRANSFER_IN"]))
        self.f_out = daily(lg["type"].isin(["SELL", "TRANSFER_OUT"]))
        self.d_div = daily(lg["type"] == "DIVIDEND") - daily(lg["type"] == "FEE")
        self.value = self.tl["qty"] * self.close[self.tickers]
        # part des achats payée par des dividendes réinvestis (pas de l'argent versé)
        from .ledger import dividend_reinvestment
        self.reinv_row, self.div_pending = dividend_reinvestment(self.cfg, lg, self.trading_days)
        rv = lg.assign(reinv=self.reinv_row)
        rv = rv[rv["reinv"] > 0].pivot_table(index="date", columns="ticker", values="reinv", aggfunc="sum") if (rv["reinv"] > 0).any() else pd.DataFrame()
        self.reinv = rv.reindex(self.cal).fillna(0.0).reindex(columns=self.tickers, fill_value=0.0)

    def scope_tickers(self, scope):
        if scope == "TOTAL":
            return self.tickers
        return [t for t in self.tickers if self.assets[t]["account"] == scope]

    def _scope_series(self):
        self.s = {}
        for sc in SCOPES:
            tk = self.scope_tickers(sc)
            if not tk:
                continue
            V = self.value[tk].sum(axis=1)
            F = (self.f_in[tk] - self.f_out[tk]).sum(axis=1)
            D = self.d_div[tk].sum(axis=1)
            R = self.reinv[tk].sum(axis=1)  # dividendes réinvestis : flux interne, pas de l'argent versé
            Vp = V.shift(1).fillna(0.0)
            den = Vp + F
            num = V + D - Vp - F
            r = pd.Series(np.where(den.abs() >= 1.0, num / den.where(den.abs() >= 1.0, 1.0), 0.0), index=self.cal)
            idx = (1 + r).cumprod()
            active = (V > 0) | (F != 0)
            start = active.idxmax() if active.any() else self.cal[-1]
            cost = self.tl["cost"][tk].sum(axis=1)
            self.s[sc] = dict(
                V=V, F=F, D=D, r=r, I=idx, start=start,
                invested=(F - R).cumsum(), F_ext=F - R, reinv=R.cumsum(), pending=D.cumsum() - R.cumsum(),
                div=D.cumsum(), cost=cost,
                realized=self.tl["realized"][tk].sum(axis=1),
                cash_in=(self.f_in[tk].sum(axis=1) - R).cumsum(),
                pnl=V - F.cumsum() + D.cumsum(),
                unreal=V - cost,
            )

    # -- dates d'échantillonnage pour le risque
    def samples(self, scope):
        st = self.s[scope]["start"]
        if scope == "CRYPTO":
            d = self.cal[self.cal >= st - pd.Timedelta(days=1)]
        else:
            td = self.trading_days[(self.trading_days >= st) & (self.trading_days <= self.today)]
            d = pd.DatetimeIndex([st - pd.Timedelta(days=1)]).append(td)
        return d

    def asof_date(self, scope):
        if scope == "CRYPTO":
            return self.today
        td = self.trading_days[self.trading_days <= self.today]
        return td[-1] if len(td) else self.today


# ----------------------------------------------------------------- métriques

def risk_metrics(panel, scope, rf):
    s = panel.s[scope]
    dates = panel.samples(scope)
    ann = 365 if scope == "CRYPTO" else 252
    I = s["I"].reindex(dates)
    rets = I.pct_change().dropna()
    days = max((dates[-1] - dates[0]).days, 1)
    twr = float(I.iloc[-1] / I.iloc[0] - 1)
    twr_ann = (1 + twr) ** (365 / days) - 1 if days >= 30 else None
    vol = float(rets.std(ddof=1) * math.sqrt(ann)) if len(rets) > 5 else None
    dd, ddi = _drawdown_info(I)
    rf_d = (1 + rf) ** (1 / ann) - 1
    downside = np.minimum(rets - rf_d, 0)
    dn = float(math.sqrt((downside ** 2).mean()) * math.sqrt(ann)) if len(rets) > 5 else None
    out = dict(
        start=s["start"].strftime("%Y-%m-%d"), days=days, n_obs=int(len(rets)), ann_factor=ann,
        twr=twr, twr_ann=twr_ann, vol=vol,
        sharpe=(twr_ann - rf) / vol if (vol and twr_ann is not None) else None,
        sortino=(twr_ann - rf) / dn if (dn and twr_ann is not None) else None,
        calmar=(twr_ann / abs(ddi["mdd"])) if (twr_ann is not None and ddi.get("mdd")) else None,
        best=dict(v=float(rets.max()), d=rets.idxmax().strftime("%Y-%m-%d")) if len(rets) else None,
        worst=dict(v=float(rets.min()), d=rets.idxmin().strftime("%Y-%m-%d")) if len(rets) else None,
        pct_up=float((rets > 0).mean()) if len(rets) else None,
        **{f"dd_{k}": v for k, v in ddi.items()},
    )
    if len(rets) > 20:
        q = float(rets.quantile(0.05))
        V_now = float(s["V"].iloc[-1])
        out.update(var95=-q, var95_eur=-q * V_now, cvar95=-float(rets[rets <= q].mean()),
                   cvar95_eur=-float(rets[rets <= q].mean()) * V_now)
    # benchmark
    bt = panel.bench_ticker
    if scope != "CRYPTO" and bt in panel.close:
        B = panel.close[bt].reindex(dates)
        b = B.pct_change().dropna()
        j = rets.index.intersection(b.index)
        x, y = rets[j], b[j]
        btwr = float(B.iloc[-1] / B.iloc[0] - 1)
        bann = (1 + btwr) ** (365 / days) - 1 if days >= 30 else None
        out["bench_twr"] = btwr
        out["bench_twr_ann"] = bann
        if len(j) > 20 and y.var() > 0:
            beta = float(np.cov(x, y, ddof=1)[0, 1] / y.var(ddof=1))
            te = float((x - y).std(ddof=1) * math.sqrt(ann))
            out.update(
                beta=beta, corr=float(np.corrcoef(x, y)[0, 1]), te=te,
                alpha=(twr_ann - (rf + beta * (bann - rf))) if (twr_ann is not None and bann is not None) else None,
                ir=((twr_ann - bann) / te) if (te and twr_ann is not None and bann is not None) else None,
            )
    series = dict(
        dates=[d.strftime("%Y-%m-%d") for d in dates],
        dd=[round(float(v), 6) for v in dd.values],
        rvol=[None if pd.isna(v) else round(float(v), 6)
              for v in (rets.rolling(21).std(ddof=1) * math.sqrt(ann)).reindex(dates).values],
    )
    if len(rets) > 5:
        lo = math.floor(rets.min() * 200) / 2
        hi = math.ceil(rets.max() * 200) / 2
        edges = np.arange(lo, hi + 0.5, 0.5)
        if len(edges) < 2:
            edges = np.array([lo, lo + 0.5])
        cnt, e = np.histogram(rets * 100, bins=edges)
        series["hist"] = dict(edges=[round(float(v), 2) for v in e], counts=[int(c) for c in cnt])
    return out, series


def period_table(panel, scope):
    s = panel.s[scope]
    end = panel.asof_date(scope)
    first = s["start"] - pd.Timedelta(days=1)
    I, P = s["I"], s["pnl"]
    B = panel.close[panel.bench_ticker] if panel.bench_ticker in panel.close else None
    samples = panel.samples(scope)
    prev = samples[samples < end]
    windows = [
        ("1J", prev[-1] if len(prev) else first),
        ("1S", end - pd.Timedelta(days=7)),
        ("1M", end - pd.DateOffset(months=1)),
        ("3M", end - pd.DateOffset(months=3)),
        ("6M", end - pd.DateOffset(months=6)),
        ("YTD", pd.Timestamp(year=end.year - 1, month=12, day=31)),
        ("1A", end - pd.DateOffset(years=1)),
        ("Origine", first),
    ]
    rows = []
    for key, st in windows:
        partial = st < first
        st = max(st, first)
        row = dict(key=key, start=st.strftime("%Y-%m-%d"), partial=bool(partial and key != "Origine"),
                   twr=_asof(I, end) / _asof(I, st) - 1,
                   pnl=_asof(P, end) - _asof(P, st),
                   value_change=_asof(s["V"], end) - _asof(s["V"], st))
        if B is not None and scope != "CRYPTO":
            row["bench"] = _asof(B, end) / _asof(B, st) - 1
        rows.append(row)
    return rows


def monthly_returns(panel, scope):
    s = panel.s[scope]
    I, P = s["I"], s["pnl"]
    start = s["start"]
    out = []
    prev_i, prev_p = 1.0, 0.0
    for m in pd.period_range(start.to_period("M"), panel.today.to_period("M"), freq="M"):
        end = min(m.end_time.normalize(), panel.today)
        i, p = _asof(I, end), _asof(P, end)
        out.append(dict(month=str(m), ret=i / prev_i - 1, pnl=p - prev_p,
                        flows=float(s["F_ext"][(s["F_ext"].index.to_period("M") == m)].sum())))
        prev_i, prev_p = i, p
    return out


def xirr_scope(panel, scope):
    s = panel.s[scope]
    flows = []
    for d in s["F"].index:
        f, dv = float(s["F"][d]), float(s["D"][d])
        if f:
            flows.append((d, -f))
        if dv:
            flows.append((d, dv))
    flows.append((panel.today, float(s["V"].iloc[-1])))
    return _xirr(flows)


def ghosts(panel, scope, rf):
    s = panel.s[scope]
    # argent réellement versé, et patrimoine = titres + dividendes pas encore réinvestis
    F, V, Dc = s["F_ext"], s["V"], s["pending"]
    out = dict(dates=[d.strftime("%Y-%m-%d") for d in panel.cal], wealth=[round(float(v), 2) for v in (V + Dc)])
    bt = panel.bench_ticker
    if bt in panel.close:
        pb = panel.close[bt]
        units = (F / pb).cumsum()
        g = units * pb
        out["bench"] = [round(float(v), 2) for v in g]
        out["bench_final"] = float(g.iloc[-1])
    k = (1 + rf) ** (1 / 365)
    bal, liv = 0.0, []
    for f in F.values:
        bal = bal * k + float(f)
        liv.append(round(bal, 2))
    out["livret"] = liv
    out["livret_final"] = liv[-1]
    out["wealth_final"] = float((V + Dc).iloc[-1])
    return out


# ----------------------------------------------------------------- positions

def positions(panel):
    cfg, today = panel.cfg, panel.today
    tot_val = float(panel.value.iloc[-1].sum())
    acc_val = {a: float(panel.value.iloc[-1][panel.scope_tickers(a)].sum()) for a in ("PEA", "CRYPTO")}
    out = []
    for t in panel.tickers:
        a = panel.assets[t]
        st = panel.final_state[t]
        raw = panel.raw.get(t)
        px = raw["close"] if raw is not None and len(raw) else pd.Series(dtype=float)
        px = px[px.index <= today]
        price = float(px.iloc[-1]) if len(px) else float("nan")
        qty = st["qty"]
        value = qty * price
        week_ref = _asof(px, px.index[-1] - pd.Timedelta(days=7)) if len(px) else float("nan")
        first_tx = panel.ledger[panel.ledger["ticker"] == t]["date"].min()
        d = dict(
            ticker=t, name=a["name"], short=a["short"], tr_name=a.get("tr_name", a["name"]), isin=a.get("isin", ""),
            account=a["account"], kind=a["kind"], asset_class=a["asset_class"], slot=a.get("slot", 8),
            ter=a.get("ter", 0), open=qty > 1e-9, qty=qty, cost=st["cost"],
            pru=st["cost"] / qty if qty > 1e-9 else None,
            price=price, price_date=px.index[-1].strftime("%Y-%m-%d") if len(px) else None,
            value=value, unreal=value - st["cost"] if qty > 1e-9 else 0.0,
            unreal_pct=(value / st["cost"] - 1) if qty > 1e-9 and st["cost"] > 0 else None,
            realized=st["realized"], dividends=st["div"], taxes=st["taxes"],
            cash_in=st["cash_in"], cash_out=st["cash_out"],
            pnl_total=value + st["cash_out"] + st["div"] - st["cash_in"],
            day_pct=float(px.iloc[-1] / px.iloc[-2] - 1) if len(px) > 1 else None,
            week_pct=float(px.iloc[-1] / week_ref - 1) if len(px) and week_ref == week_ref else None,
            weight_total=value / tot_val if tot_val else 0,
            weight_account=value / acc_val[a["account"]] if acc_val.get(a["account"]) else 0,
            fee_year=value * a.get("ter", 0) / 100,
            first_date=first_tx.strftime("%Y-%m-%d"),
            spark=[round(float(v), 4) for v in px.iloc[-30:].values],
        )
        out.append(d)
    out.sort(key=lambda d: (not d["open"], d["account"] != "PEA", -d["value"]))
    return out


def position_series(panel):
    out = {}
    for t in panel.tickers:
        raw = panel.raw.get(t)
        if raw is None or raw.empty:
            continue
        lg = panel.ledger[panel.ledger["ticker"] == t]
        start = lg["date"].min() - pd.Timedelta(days=14)
        px = raw["close"][(raw.index >= start) & (raw.index <= panel.today)]
        qty = panel.tl["qty"][t].reindex(px.index, method="ffill").fillna(0)
        cost = panel.tl["cost"][t].reindex(px.index, method="ffill").fillna(0)
        pru = [round(float(c / q), 4) if q > 1e-9 else None for c, q in zip(cost.values, qty.values)]
        marks = []
        for r in lg.itertuples(index=False):
            if r.type in ("BUY", "SELL", "TRANSFER_IN", "TRANSFER_OUT") and r.quantity:
                marks.append(dict(date=r.date.strftime("%Y-%m-%d"), type=r.type, qty=float(r.quantity),
                                  amount=float(r.amount), price=round((float(r.amount) - float(r.taxes)) / float(r.quantity), 4),
                                  source=r.source))
        out[t] = dict(dates=[d.strftime("%Y-%m-%d") for d in px.index],
                      price=[round(float(v), 4) for v in px.values], pru=pru,
                      qty=[round(float(v), 6) for v in qty.values], marks=marks)
    return out


# ----------------------------------------------------------------- allocation

def allocation(panel, pos):
    cfg = panel.cfg
    open_pos = [p for p in pos if p["open"]]
    total = sum(p["value"] for p in open_pos)
    pea = [p for p in open_pos if p["account"] == "PEA"]
    pea_total = sum(p["value"] for p in pea)

    def group(items, key):
        g = {}
        for p in items:
            g[p[key]] = g.get(p[key], 0) + p["value"]
        return [dict(label=k, value=v, weight=v / total if total else 0) for k, v in sorted(g.items(), key=lambda x: -x[1])]

    zones = {}
    for p in open_pos:
        for z, w in panel.assets[p["ticker"]].get("zones", {}).items():
            zones[z] = zones.get(z, 0) + p["value"] * w / 100
    zones_l = [dict(label=k, value=v, weight=v / total) for k, v in sorted(zones.items(), key=lambda x: -x[1])]

    def conc(items, tot):
        w = [p["value"] / tot for p in items] if tot else []
        hhi = sum(x * x for x in w)
        return dict(hhi=hhi, n_eff=(1 / hhi) if hhi else None, top=max(w) if w else None)

    from .ledger import monthly_equivalent
    pea_plans = [dict(pl, amount=monthly_equivalent(pl)) for pl in cfg["plans"]
                 if pl["ticker"] in cfg["assets"] and cfg["assets"][pl["ticker"]]["account"] == "PEA" and _plan_live(pl, panel.today)]
    plan_tot = sum(pl["amount"] for pl in pea_plans)
    vs_plan = []
    for p in pea:
        amt = sum(x["amount"] for x in pea_plans if x["ticker"] == p["ticker"])
        vs_plan.append(dict(ticker=p["ticker"], short=p["short"], slot=p["slot"],
                            actual=p["value"] / pea_total if pea_total else 0,
                            plan=(amt / plan_tot) if plan_tot else 0.0))
    return dict(
        total=total,
        by_account=group(open_pos, "account"),
        by_class=group(open_pos, "asset_class"),
        by_zone=zones_l,
        concentration=dict(total=conc(open_pos, total), pea=conc(pea, pea_total)),
        vs_plan=vs_plan,
        fee_year=sum(p["fee_year"] for p in open_pos),
        ter_weighted=(sum(p["fee_year"] for p in open_pos) / total * 100) if total else 0,
    )


# ----------------------------------------------------------------- plans & événements

def _plan_live(pl, today):
    return pl.get("active", True) is not False and (not pl.get("end") or pd.Timestamp(pl["end"]) >= today)


def freq_label(pl):
    from .ledger import plan_days
    days = plan_days(pl)
    every = int(pl.get("every", 1) or 1)
    d = " et ".join(str(x) for x in days)
    if len(days) > 1:
        base = f"{len(days)} fois par mois (le {d})"
    else:
        base = f"le {d}"
    if every == 1:
        return base if len(days) > 1 else f"Chaque mois, {base}"
    if every == 3:
        return f"Chaque trimestre, {base}"
    return f"Tous les {every} mois, {base}"


def _last_price(panel, t):
    raw = panel.raw.get(t)
    if raw is None or raw.empty:
        return float("nan")
    s = raw["close"][raw.index <= panel.today]
    return float(s.iloc[-1]) if len(s) else float("nan")


def plans_info(panel, pos):
    from .ledger import monthly_equivalent, next_execution, plan_days
    cfg, today = panel.cfg, panel.today
    rows = []
    for i, pl in enumerate(cfg["plans"]):
        t = pl["ticker"]
        if t not in cfg["assets"]:
            continue
        a = cfg["assets"][t]
        price = _last_price(panel, t)
        done_today = ((panel.ledger["date"] == today) & (panel.ledger["ticker"] == t) & (panel.ledger["type"] == "BUY")).any()
        live = _plan_live(pl, today)
        ex = next_execution(pl, today, panel.trading_days, include_today=not done_today) if live else None
        row = dict(index=i, id=pl.get("id"), ticker=t, short=a["short"], account=a["account"], amount=float(pl["amount"]),
                   days=plan_days(pl), every=int(pl.get("every", 1) or 1), start=pl.get("start"), end=pl.get("end"),
                   active=live, freq=freq_label(pl), monthly=monthly_equivalent(pl) if live else 0.0,
                   next=ex.strftime("%Y-%m-%d") if ex is not None else None,
                   days_to=int((ex - today).days) if ex is not None else None, price=price)
        if a["account"] == "PEA" and price == price and price > 0:
            n = math.floor(pl["amount"] / (price * 1.002))
            inv = n * price
            row.update(shares=n, invested=inv, residual=pl["amount"] - inv,
                       residual_pct=(pl["amount"] - inv) / pl["amount"],
                       suggest=[dict(shares=k, amount=math.ceil(k * price * 1.02)) for k in (max(n, 1), max(n, 1) + 1)])
        else:
            row.update(shares=None, invested=float(pl["amount"]), residual=0.0, residual_pct=0.0)
        rows.append(row)
    return rows


def dividend_info(panel, pos):
    today = panel.today
    out_next = []
    for p in pos:
        if not p["open"] or p["kind"] != "Action":
            continue
        dv = unadjusted_dividends(panel.actions, p["ticker"])
        dv = dv[dv.index > today - pd.Timedelta(days=400)]
        if dv.empty:
            continue
        last = dv[dv.index > today - pd.Timedelta(days=370)]
        freq = max(len(last), 1)
        step = pd.Timedelta(days=round(365 / freq))
        nxt = dv.index[-1] + step
        while nxt < today:
            nxt += step
        out_next.append(dict(ticker=p["ticker"], short=p["short"], ex_date=nxt.strftime("%Y-%m-%d"),
                             per_share=float(dv.iloc[-1]), amount=float(dv.iloc[-1]) * p["qty"], freq=freq))
    lg = panel.ledger[panel.ledger["type"] == "DIVIDEND"]
    received = [dict(date=r.date.strftime("%Y-%m-%d"), ticker=r.ticker, short=panel.assets[r.ticker]["short"],
                     amount=float(r.amount)) for r in lg.itertuples(index=False)]
    ttm = float(lg[lg["date"] > today - pd.Timedelta(days=365)]["amount"].sum())
    payers_cost = sum(p["cost"] for p in pos if p["open"] and p["kind"] == "Action")
    return dict(received=received, total=float(lg["amount"].sum()), ttm=ttm,
                yield_on_cost=(ttm / payers_cost) if payers_cost else None,
                forward=sum(d["amount"] * d["freq"] for d in out_next), next=sorted(out_next, key=lambda d: d["ex_date"]))


def fiscal_info(panel):
    cfg, today = panel.cfg, panel.today
    acc = cfg["accounts"]["PEA"]
    opened = pd.Timestamp(acc["opened"])
    mat = pd.Timestamp(acc["fiscal_maturity"])
    s = panel.s["PEA"]
    gain = float(s["pnl"].iloc[-1])
    value = float(s["V"].iloc[-1])
    tx = cfg["tax"]
    pfu = tx["ps_rate"] + tx["ir_rate_pfu"]
    tax_now = max(gain, 0) * pfu
    tax_after = max(gain, 0) * tx["ps_rate"]
    deposits = float(s["invested"].iloc[-1])
    return dict(
        opened=opened.strftime("%Y-%m-%d"), maturity=mat.strftime("%Y-%m-%d"),
        days_left=max(int((mat - today).days), 0),
        progress=min(max((today - opened).days / max((mat - opened).days, 1), 0), 1),
        gain=gain, value=value, pfu_rate=pfu, ps_rate=tx["ps_rate"],
        tax_now=tax_now, net_now=value + float(s["div"].iloc[-1]) - tax_now,
        tax_after=tax_after, net_after=value + float(s["div"].iloc[-1]) - tax_after,
        saving=tax_now - tax_after,
        deposits=deposits, ceiling=acc.get("deposit_ceiling", 150000),
        ceiling_used=deposits / acc.get("deposit_ceiling", 150000),
    )


def sim_defaults(panel, pos):
    """Point de départ du simulateur (côté navigateur) : ton portefeuille réel ligne par ligne."""
    from .ledger import monthly_equivalent
    cfg, today = panel.cfg, panel.today
    pc = cfg.get("projection", {})
    cd = pc.get("class_defaults", {})
    plans = [pl for pl in cfg["plans"] if pl["ticker"] in cfg["assets"] and _plan_live(pl, today)]
    tickers = [p["ticker"] for p in pos if p["open"]] + [pl["ticker"] for pl in plans]
    lines, seen = [], set()
    for t in tickers:
        if t in seen:
            continue
        seen.add(t)
        a = cfg["assets"][t]
        p = next((x for x in pos if x["ticker"] == t), None)
        d = dict(cd.get("default", {"return": 0.06, "vol": 0.18, "yield": 0}))
        d.update(cd.get(a.get("asset_class"), {}))
        d.update(a.get("projection", {}))
        raw = panel.raw.get(t)
        hist_vol = None
        if raw is not None and len(raw) > 60:
            r = raw["close"].pct_change().dropna().iloc[-252:]
            hist_vol = float(r.std() * math.sqrt(365 if a["account"] == "CRYPTO" else 252))
        price = _last_price(panel, t)
        if a.get("kind") == "Action":
            dv = unadjusted_dividends(panel.actions, t)
            dv = dv[dv.index > today - pd.Timedelta(days=366)]
            if len(dv) and price == price and price > 0:
                d["yield"] = float(dv.sum() / price)
        lines.append(dict(ticker=t, short=a["short"], account=a["account"], asset_class=a.get("asset_class"),
                          slot=a.get("slot", 8), value=p["value"] if (p and p["open"]) else 0.0,
                          monthly=sum(monthly_equivalent(pl) for pl in plans if pl["ticker"] == t),
                          price=price if price == price else None,
                          ret=d["return"], vol=d["vol"], yld=d.get("yield", 0), hist_vol=hist_vol))
    inv = {acc: float(panel.s[acc]["invested"].iloc[-1]) for acc in ("PEA", "CRYPTO") if acc in panel.s}
    divs = {acc: float(panel.s[acc]["div"].iloc[-1]) for acc in ("PEA", "CRYPTO") if acc in panel.s}
    return dict(today=today.strftime("%Y-%m-%d"), lines=lines, invested=inv, dividends=divs,
                inflation=cfg.get("inflation", 0.02), ps_rate=cfg["tax"]["ps_rate"], ir_rate=cfg["tax"]["ir_rate_pfu"],
                maturity=cfg["accounts"]["PEA"]["fiscal_maturity"], years=int(pc.get("years", 20)), class_defaults=cd)


def cash_reserve(panel, pos):
    """Réserve de liquidité du PEA : point de départ relevé dans TR, puis
    + reliquat de chaque exécution de plan (montant du plan - montant investi, parts entières)
    + ventes du PEA (+ dividendes seulement si include_dividends : chez TR ils sont réinvestis au plan suivant)
    + / - ajouts et retraits manuels (argent mis de côté ailleurs...)
    - achats payés avec la réserve (colonne funding = reserve)."""
    from .ledger import plan_executions
    cfg, today = panel.cfg, panel.today
    cr = cfg["accounts"]["PEA"].get("cash_reserve")
    if not cr:
        return None
    start = pd.Timestamp(cr["date"])
    lg = panel.ledger
    pea = lg[(lg["account"] == "PEA") & (lg["date"] > start)]
    moves = []
    name = lambda t: cfg["assets"].get(t, {}).get("short", t)
    for pl in cfg["plans"]:
        t = pl["ticker"]
        if cfg["assets"].get(t, {}).get("account") != "PEA":
            continue
        for ex in plan_executions(pl, start + pd.Timedelta(days=1), today, panel.trading_days):
            rows = pea[(pea["ticker"] == t) & (pea["type"] == "BUY") & (pea["funding"] != "reserve")
                       & ((pea["date"] - ex).abs() <= pd.Timedelta(days=2))]
            if rows.empty:
                continue  # plan pas encore enregistré, ou échoué (aucun argent ne bouge)
            left = float(pl["amount"]) + float(panel.reinv_row.loc[rows.index].sum()) - float(rows["amount"].sum())
            if left > 0.005:
                n = float(rows["quantity"].sum())
                moves.append(dict(date=ex.strftime("%Y-%m-%d"), kind="plan", amount=left,
                                  label=f"Reliquat du plan {name(t)} ({pl['amount']:g} € → {n:g} part{'s' if n > 1 else ''} pour {rows['amount'].sum():.2f} €)"))
    for r in pea.itertuples(index=False):
        if r.type == "DIVIDEND" and cr.get("include_dividends", False):
            moves.append(dict(date=r.date.strftime("%Y-%m-%d"), kind="dividende", amount=float(r.amount), label=f"Dividende {name(r.ticker)}"))
        elif r.type == "SELL" and cr.get("include_sales", True):
            moves.append(dict(date=r.date.strftime("%Y-%m-%d"), kind="vente", amount=float(r.amount), label=f"Vente {name(r.ticker)}"))
        elif r.type == "FEE":
            moves.append(dict(date=r.date.strftime("%Y-%m-%d"), kind="frais", amount=-float(r.amount), label=f"Frais {name(r.ticker)}"))
        elif r.type == "BUY" and r.funding == "reserve":
            moves.append(dict(date=r.date.strftime("%Y-%m-%d"), kind="achat", amount=-float(r.amount),
                              label=f"Achat {name(r.ticker)} payé avec la réserve ({r.quantity:g} part{'s' if r.quantity > 1 else ''})"))
    for adj in cr.get("adjustments", []):
        d = pd.Timestamp(adj["date"])
        if d < start or d > today or not adj.get("amount"):
            continue
        amt = float(adj["amount"])
        moves.append(dict(date=d.strftime("%Y-%m-%d"), kind="manuel", amount=amt,
                          label=(adj.get("note") or ("Ajout manuel" if amt > 0 else "Retrait manuel"))))
    moves.sort(key=lambda m: m["date"])
    bal, hist = float(cr["amount"]), [dict(date=start.strftime("%Y-%m-%d"), balance=float(cr["amount"]))]
    for m in moves:
        bal += m["amount"]
        m["balance"] = bal
        hist.append(dict(date=m["date"], balance=bal))
    # ce que la réserve permet d'acheter tout de suite (parts entières)
    buy, seen = [], set()
    tick = [p["ticker"] for p in pos if p["open"] and p["account"] == "PEA"] + \
        [pl["ticker"] for pl in cfg["plans"] if cfg["assets"].get(pl["ticker"], {}).get("account") == "PEA" and _plan_live(pl, today)]
    for t in tick:
        if t in seen:
            continue
        seen.add(t)
        price = _last_price(panel, t)
        if price == price and price > 0:
            n = math.floor(bal / price + 1e-9)
            buy.append(dict(ticker=t, short=name(t), price=price, shares=n, cost=n * price, missing=max(price * (n + 1) - bal, 0)))
    monthly = 0.0
    for pl in cfg["plans"]:
        a = cfg["assets"].get(pl["ticker"], {})
        if a.get("account") != "PEA" or not _plan_live(pl, today):
            continue
        price = _last_price(panel, pl["ticker"])
        if price == price and price > 0:
            from .ledger import monthly_equivalent
            n = math.floor(pl["amount"] / price + 1e-9)
            if n > 0:
                monthly += (pl["amount"] - n * price) * monthly_equivalent(pl) / pl["amount"]
    week = today - pd.Timedelta(days=7)
    return dict(start_date=start.strftime("%Y-%m-%d"), start_amount=float(cr["amount"]), balance=bal,
                week_change=sum(m["amount"] for m in moves if pd.Timestamp(m["date"]) > week),
                monthly_estimate=monthly, moves=list(reversed(moves)), history=hist,
                buyable=sorted(buy, key=lambda b: -b["cost"]), note=cr.get("note", ""))


# ----------------------------------------------------------------- réconciliation TR

def reconciliation(panel, recon):
    if recon is None or recon.empty:
        return None
    recon = recon.copy()
    recon["day"] = recon["snapshot"].str[:10]
    last_day = recon["day"].max()
    rows = recon[recon["day"] == last_day]
    when = pd.Timestamp(last_day)
    checks = []
    tl_qty = panel.tl["qty"]
    tl_cost = panel.tl["cost"]

    def at(df, t):
        s = df[t] if t in df else pd.Series(dtype=float)
        return _asof(s, when) if len(s) else float("nan")

    for r in rows.itertuples(index=False):
        if r.scope != "POSITION":
            continue
        t = r.ticker
        q_l, c_l = at(tl_qty, t), at(tl_cost, t)
        def num(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None
        q_tr, pru_tr, val_tr, gain_tr, perf_tr = num(r.quantity), num(r.pru), num(r.value), num(r.gain), num(r.perf_pct)
        item = dict(ticker=t, short=panel.assets[t]["short"], snapshot=r.snapshot, value_tr=val_tr, checks=[])
        if q_tr is not None:
            item["checks"].append(dict(label="Quantité", tr=q_tr, ledger=q_l, ok=abs(q_tr - q_l) < 1e-6))
        if pru_tr is not None and q_l:
            item["checks"].append(dict(label="PRU", tr=pru_tr, ledger=c_l / q_l, ok=abs(pru_tr - c_l / q_l) < 0.006))
        if perf_tr is not None and val_tr and c_l:
            perf_l = (val_tr / c_l - 1) * 100
            item["checks"].append(dict(label="Performance %", tr=perf_tr, ledger=perf_l, ok=abs(perf_tr - perf_l) < 0.02))
        if gain_tr is not None and val_tr is not None:
            item["checks"].append(dict(label="Coût de revient", tr=val_tr - gain_tr, ledger=c_l, ok=abs(val_tr - gain_tr - c_l) < 0.02))
        if val_tr is not None and q_l:
            close = _asof(panel.raw[t]["close"], when) if t in panel.raw and len(panel.raw[t]) else float("nan")
            item["price_tr"] = val_tr / q_l
            item["price_close"] = close
        checks.append(item)
    accounts = []
    for r in rows.itertuples(index=False):
        if r.scope != "ACCOUNT":
            continue
        tk = panel.scope_tickers(r.ticker) if r.ticker in ("PEA", "CRYPTO", "TOTAL") else []
        tr_sum = sum(c["value_tr"] or 0 for c in checks if c["ticker"] in tk)
        val_close = sum(at(tl_qty, t) * _asof(panel.close[t], when) for t in tk)
        accounts.append(dict(scope=r.ticker, value_tr=float(r.value), positions_tr=tr_sum,
                             value_close=val_close))
    ok = all(c["ok"] for it in checks for c in it["checks"])
    return dict(date=last_day, ok=ok, positions=checks, accounts=accounts)
