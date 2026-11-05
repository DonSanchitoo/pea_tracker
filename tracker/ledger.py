"""Registre des opérations (data/transactions.csv) : lecture, contrôles et automatisations.

Automatisations (toutes ajoutées au registre avec source AUTO, modifiables ensuite) :
- plans d'épargne exécutés (toutes fréquences) ;
- dividendes encaissés (dates et montants Yahoo, versement 2 jours ouvrés après le détachement) ;
- récompenses de staking (taux annuel paramétrable, comptabilisées chaque mois).
Une ligne BUY sans quantité est un « ordre au montant » : la quantité est calculée au cours
du jour d'exécution (ou l'ordre reste « prévu » si la date est future).
"""
import math
import os

import pandas as pd

from .common import LEDGER_FILE

COLUMNS = ["date", "account", "type", "ticker", "quantity", "amount", "taxes", "source", "note"]
TYPES = {"BUY", "SELL", "DIVIDEND", "TRANSFER_IN", "TRANSFER_OUT", "STAKING", "BONUS", "FEE"}
QTY_TYPES = {"SELL", "TRANSFER_IN", "TRANSFER_OUT", "STAKING", "BONUS"}
DAY = pd.Timedelta(days=1)


class LedgerError(Exception):
    pass


def load_ledger(cfg, path=LEDGER_FILE):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise LedgerError(f"Colonnes manquantes dans transactions.csv : {missing}")
    df = df[COLUMNS].copy()
    df = df[df["date"].str.strip() != ""]
    df["line"] = range(2, len(df) + 2)
    try:
        df["date"] = pd.to_datetime(df["date"].str.strip(), format="%Y-%m-%d")
    except ValueError as e:
        raise LedgerError(f"Date invalide dans transactions.csv ({e}). Format attendu : AAAA-MM-JJ.")
    for c in ("quantity", "amount", "taxes"):
        df[c] = pd.to_numeric(df[c].str.strip().replace("", "0").str.replace(",", "."), errors="coerce").fillna(0.0)
    df["type"] = df["type"].str.strip().str.upper()
    df["account"] = df["account"].str.strip().str.upper()
    df["ticker"] = df["ticker"].str.strip()
    df["source"] = df["source"].str.strip().str.upper().replace("", "TR")
    df["budget"] = (df["type"] == "BUY") & (df["quantity"] <= 0)
    _validate(df, cfg)
    return df.sort_values(["date", "line"], kind="mergesort").reset_index(drop=True)


def _validate(df, cfg):
    errors = []
    assets = cfg["assets"]
    for _, r in df.iterrows():
        where = f"ligne {r['line']}"
        if r["type"] not in TYPES:
            errors.append(f"{where} : type inconnu « {r['type']} »")
        if r["ticker"] not in assets:
            errors.append(f"{where} : ticker « {r['ticker']} » absent de config.json")
            continue
        if assets[r["ticker"]]["account"] != r["account"]:
            errors.append(f"{where} : {r['ticker']} est rattaché au compte {assets[r['ticker']]['account']}, pas {r['account']}")
        if r["type"] in QTY_TYPES and r["quantity"] <= 0:
            errors.append(f"{where} : quantité manquante ou nulle")
        if r["type"] in {"BUY", "SELL", "DIVIDEND", "TRANSFER_IN", "FEE"} and r["amount"] <= 0:
            errors.append(f"{where} : montant manquant")
    held, unknown = {}, set()
    for _, r in df.sort_values(["date", "line"], kind="mergesort").iterrows():
        q = held.get(r["ticker"], 0.0)
        if r["type"] == "BUY" and r["budget"]:
            unknown.add(r["ticker"])
        elif r["type"] in {"BUY", "TRANSFER_IN", "STAKING", "BONUS"}:
            q += r["quantity"]
        elif r["type"] in {"SELL", "TRANSFER_OUT"}:
            if r["quantity"] > q + 1e-9 and r["ticker"] not in unknown:
                errors.append(f"ligne {r['line']} : vente de {r['quantity']} {r['ticker']} alors que seulement {q:g} détenus")
            q -= r["quantity"]
        held[r["ticker"]] = q
    if errors:
        raise LedgerError("Registre invalide :\n  - " + "\n  - ".join(errors))


# ---------------------------------------------------------------- dates et prix

def execution_date(year, month, day, trading_days):
    """Premier jour de bourse >= `day` du mois (Trade Republic décale au jour ouvré suivant)."""
    day = min(int(day), 28)
    target = pd.Timestamp(year=year, month=month, day=day)
    later = trading_days[trading_days >= target]
    if len(later):
        return later[0]
    d = target
    while d.weekday() >= 5:
        d += DAY
    return d


def plan_days(plan):
    days = plan.get("days") or [plan.get("day", 16)]
    return sorted(int(d) for d in days)


def plan_active_on(plan, d):
    if plan.get("active") is False:
        return False
    if plan.get("start") and d < pd.Timestamp(plan["start"]):
        return False
    if plan.get("end") and d > pd.Timestamp(plan["end"]):
        return False
    return True


def plan_month_ok(plan, year, month):
    every = max(int(plan.get("every", 1) or 1), 1)
    st = pd.Timestamp(plan["start"]) if plan.get("start") else pd.Timestamp(year=year, month=month, day=1)
    return ((year - st.year) * 12 + month - st.month) % every == 0


def plan_executions(plan, first, last, trading_days):
    """Dates d'exécution d'un plan entre deux dates (incluses)."""
    out = []
    m = pd.Timestamp(year=first.year, month=first.month, day=1)
    while m <= last:
        if plan_month_ok(plan, m.year, m.month):
            for d in plan_days(plan):
                ex = execution_date(m.year, m.month, d, trading_days)
                if first <= ex <= last and plan_active_on(plan, ex):
                    out.append(ex)
        m += pd.DateOffset(months=1)
    return sorted(set(out))


def next_execution(plan, today, trading_days, include_today=True):
    horizon = today + pd.DateOffset(months=13)
    for ex in plan_executions(plan, today, horizon, trading_days):
        if ex > today or (include_today and ex == today):
            return ex
    return None


def monthly_equivalent(plan):
    if plan.get("active") is False:
        return 0.0
    every = max(int(plan.get("every", 1) or 1), 1)
    return float(plan["amount"]) * len(plan_days(plan)) / every


def _est_price(row, account):
    if account == "PEA":
        return (row["open"] + row["high"]) / 2
    return (row["open"] + row["high"] + row["low"] + row["close"]) / 4


def _fill(account, budget, row):
    """Quantité et montant estimés pour un ordre au montant."""
    est = _est_price(row, account)
    if account == "PEA":
        n = math.floor(budget / est)
        return n, round(n * est, 2), est
    return round(budget / est, 6), round(budget, 2), est


def _after_close(now):
    return now.hour * 60 + now.minute >= 17 * 60 + 45


# ---------------------------------------------------------------- plans auto

def auto_record_plans(cfg, ledger, ohlc_by_ticker, trading_days, now):
    """Ajoute au registre les exécutions de plan non encore saisies (mois courant et précédent).

    PEA : parts entières, nombre = plancher(montant / prix estimé), prix estimé = (ouverture + plus haut) / 2,
    règle calée sur les 14 exécutions réelles de mars à octobre 2026 (14/14 bons nombres de parts).
    Crypto : quantité = montant / cours moyen du jour.
    """
    today = pd.Timestamp(now.date())
    added = []
    for plan in cfg["plans"]:
        t, amount = plan["ticker"], float(plan["amount"])
        if t not in cfg["assets"]:
            continue
        acc = cfg["assets"][t]["account"]
        buys = ledger[(ledger["ticker"] == t) & (ledger["type"] == "BUY")]["date"]
        start = pd.Timestamp(plan["start"]) if plan.get("start") else today.replace(day=1)
        first = max(start, (today - pd.DateOffset(months=1)).replace(day=1))
        for ex in plan_executions(plan, first, today, trading_days):
            if ex == today and not _after_close(now):
                continue
            if ((buys >= ex - 2 * DAY) & (buys <= ex + 4 * DAY)).any():
                continue
            px = ohlc_by_ticker.get(t)
            if px is None or ex not in px.index:
                continue
            qty, amt, est = _fill(acc, amount, px.loc[ex])
            if qty <= 0:
                continue
            note = (f"Plan d'épargne (estimé : {qty:g} parts à ~{est:.4f} €) : remplace par le montant TR" if acc == "PEA"
                    else f"Plan d'épargne (quantité estimée au cours moyen ~{est:.2f} €)")
            added.append(dict(date=ex.strftime("%Y-%m-%d"), account=acc, type="BUY", ticker=t,
                              quantity=qty, amount=amt, taxes=0, source="AUTO", note=note))
            buys = pd.concat([buys, pd.Series([ex])], ignore_index=True)
    return added


# ---------------------------------------------------------------- dividendes auto

def _business_days_after(d, n):
    while n:
        d += DAY
        if d.weekday() < 5:
            n -= 1
    return d


def auto_dividends(cfg, ledger, dividends_by_ticker, today):
    """Dividendes détachés sur des titres détenus, versés (détachement + 2 jours ouvrés) et non saisis."""
    added = []
    for t, divs in dividends_by_ticker.items():
        if t not in cfg["assets"] or divs is None or divs.empty:
            continue
        a = cfg["assets"][t]
        lg = ledger[ledger["ticker"] == t]
        if lg.empty:
            continue
        existing = lg[lg["type"] == "DIVIDEND"]["date"]
        withholding = float(a.get("dividend_tax", 0) or 0)
        for ex, per_share in divs.items():
            ex = pd.Timestamp(ex).normalize()
            pay = _business_days_after(ex, 2)
            if pay > today or ex < lg["date"].min():
                continue
            before = lg[lg["date"] < ex]
            qty = before[before["type"].isin(["BUY", "TRANSFER_IN", "STAKING", "BONUS"])]["quantity"].sum() - \
                before[before["type"].isin(["SELL", "TRANSFER_OUT"])]["quantity"].sum()
            if qty <= 1e-9:
                continue
            if ((existing >= ex - DAY) & (existing <= ex + 12 * DAY)).any():
                continue
            amount = round(per_share * qty * (1 - withholding), 2)
            if amount <= 0:
                continue
            added.append(dict(date=pay.strftime("%Y-%m-%d"), account=a["account"], type="DIVIDEND", ticker=t,
                              quantity=0, amount=amount, taxes=0, source="AUTO",
                              note=f"Dividende détaché le {ex.strftime('%d/%m/%Y')} : {per_share:.4f} € x {qty:g}"))
    return added


# ---------------------------------------------------------------- staking auto

def auto_staking(cfg, ledger, today):
    """Récompenses de staking du mois écoulé, comptabilisées le 1er du mois suivant."""
    added = []
    for t, a in cfg["assets"].items():
        st = a.get("staking") or {}
        rate = float(st.get("rate", 0) or 0)
        if rate <= 0:
            continue
        lg = ledger[ledger["ticker"] == t]
        since = pd.Timestamp(st.get("since") or (lg["date"].min() if len(lg) else today))
        booked = set(lg[(lg["type"] == "STAKING") & (lg["source"] == "AUTO")]["date"])
        events = [(r.date, (r.quantity if r.type in ("BUY", "TRANSFER_IN", "STAKING", "BONUS") else -r.quantity))
                  for r in lg.itertuples(index=False) if r.type in ("BUY", "TRANSFER_IN", "STAKING", "BONUS", "SELL", "TRANSFER_OUT")]
        m = since.replace(day=1)
        while True:
            m_end = (m + pd.DateOffset(months=1)) - DAY
            book = m_end + DAY
            if book > today:
                break
            if book not in booked:
                reward = 0.0
                d = max(m, since)
                while d <= m_end:
                    q = sum(x for dt, x in events if dt <= d)
                    reward += max(q, 0) * rate / 365
                    d += DAY
                if reward > 0:
                    reward = round(reward, 8)
                    added.append(dict(date=book.strftime("%Y-%m-%d"), account=a["account"], type="STAKING", ticker=t,
                                      quantity=reward, amount=0, taxes=0, source="AUTO",
                                      note=f"Staking {m.strftime('%m/%Y')} estimé à {rate * 100:.2f} %/an"))
                    events.append((book, reward))
            m += pd.DateOffset(months=1)
    return added


# ---------------------------------------------------------------- ordres au montant

def resolve_budget_orders(cfg, ledger, ohlc_by_ticker, now):
    """Remplace les achats sans quantité par leur exécution estimée. Retourne (registre, ordres prévus)."""
    today = pd.Timestamp(now.date())
    if not ledger["budget"].any():
        return ledger, []
    planned, rows = [], []
    for r in ledger.to_dict("records"):
        if not r["budget"]:
            rows.append(r)
            continue
        acc = cfg["assets"][r["ticker"]]["account"]
        px = ohlc_by_ticker.get(r["ticker"])
        exec_days = px.index[px.index >= r["date"]] if px is not None and len(px) else []
        ex = exec_days[0] if len(exec_days) else None
        ready = ex is not None and (ex < today or (ex == today and _after_close(now)))
        if not ready:
            planned.append(dict(date=r["date"].strftime("%Y-%m-%d"), ticker=r["ticker"], account=acc,
                                amount=float(r["amount"]), note=r["note"]))
            continue
        qty, amt, est = _fill(acc, float(r["amount"]), px.loc[ex])
        if qty <= 0:
            planned.append(dict(date=r["date"].strftime("%Y-%m-%d"), ticker=r["ticker"], account=acc,
                                amount=float(r["amount"]), note="Montant inférieur au prix d'une part"))
            continue
        r = dict(r)
        r.update(date=ex, quantity=qty, amount=amt, source="AUTO",
                 note=(r["note"] + " · " if r["note"] else "") + f"budget {float(r['amount']):.2f} €, {qty:g} au cours estimé {est:.4f} €")
        rows.append(r)
    out = pd.DataFrame(rows, columns=ledger.columns)
    out["date"] = pd.to_datetime(out["date"])
    return out.sort_values(["date", "line"], kind="mergesort").reset_index(drop=True), planned


# ---------------------------------------------------------------- écriture

def _fmt_qty(q):
    return f"{q:.8f}".rstrip("0").rstrip(".") if q else ""


def append_rows(rows, path=LEDGER_FILE):
    """Ajoute des lignes en fin de fichier sans réécrire l'existant (diff minimal)."""
    if not rows:
        return
    with open(path, "rb+") as f:
        f.seek(0, os.SEEK_END)
        if f.tell():
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                f.write(b"\n")
    with open(path, "a", encoding="utf-8") as f:
        for r in sorted(rows, key=lambda x: x["date"]):
            note = str(r["note"]).replace(",", ";")
            f.write(",".join([
                r["date"], r["account"], r["type"], r["ticker"], _fmt_qty(float(r["quantity"])),
                f"{float(r['amount']):.2f}", f"{float(r['taxes']):g}", r["source"], note,
            ]) + "\n")
