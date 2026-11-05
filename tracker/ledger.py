"""Registre des opérations (data/transactions.csv) : lecture, contrôles, plans automatiques."""
import math
import os

import pandas as pd

from .common import LEDGER_FILE

COLUMNS = ["date", "account", "type", "ticker", "quantity", "amount", "taxes", "source", "note"]
TYPES = {"BUY", "SELL", "DIVIDEND", "TRANSFER_IN", "TRANSFER_OUT", "STAKING", "BONUS", "FEE"}
QTY_TYPES = {"BUY", "SELL", "TRANSFER_IN", "TRANSFER_OUT", "STAKING", "BONUS"}


class LedgerError(Exception):
    pass


def load_ledger(cfg, path=LEDGER_FILE):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise LedgerError(f"Colonnes manquantes dans transactions.csv : {missing}")
    df = df[COLUMNS].copy()
    df["line"] = range(2, len(df) + 2)
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d")
    for c in ("quantity", "amount", "taxes"):
        df[c] = pd.to_numeric(df[c].replace("", "0").str.replace(",", "."), errors="coerce").fillna(0.0)
    df["type"] = df["type"].str.strip().str.upper()
    df["account"] = df["account"].str.strip().str.upper()
    df["ticker"] = df["ticker"].str.strip()
    df["source"] = df["source"].str.strip().str.upper().replace("", "TR")
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
    held = {}
    for _, r in df.sort_values(["date", "line"], kind="mergesort").iterrows():
        q = held.get(r["ticker"], 0.0)
        if r["type"] in {"BUY", "TRANSFER_IN", "STAKING", "BONUS"}:
            q += r["quantity"]
        elif r["type"] in {"SELL", "TRANSFER_OUT"}:
            if r["quantity"] > q + 1e-9:
                errors.append(f"ligne {r['line']} : vente de {r['quantity']} {r['ticker']} alors que seulement {q:g} détenus")
            q -= r["quantity"]
        held[r["ticker"]] = q
    if errors:
        raise LedgerError("Registre invalide :\n  - " + "\n  - ".join(errors))


# ---------------------------------------------------------------- plans auto

def execution_date(year, month, day, trading_days):
    """Premier jour de bourse >= `day` du mois (Trade Republic décale au jour ouvré suivant)."""
    target = pd.Timestamp(year=year, month=month, day=day)
    later = trading_days[trading_days >= target]
    if len(later):
        return later[0]
    # Pas encore de cours : prochain jour de semaine
    d = target
    while d.weekday() >= 5:
        d += pd.Timedelta(days=1)
    return d


def _fmt_qty(q):
    return f"{q:.6f}".rstrip("0").rstrip(".")


def auto_record_plans(cfg, ledger, ohlc_by_ticker, trading_days, now):
    """Ajoute au registre les exécutions de plan non encore saisies.

    PEA : Trade Republic n'achète que des parts entières. Nombre de parts =
    plancher(montant / prix estimé), prix estimé = (ouverture + plus haut) / 2,
    règle calée sur les 14 exécutions réelles de mars à octobre 2026 (14/14 bons
    nombres de parts, écart de montant < 0,60 €).
    Crypto : quantité fractionnée = montant / cours moyen du jour.
    Retourne la liste des lignes ajoutées (dict).
    """
    today = pd.Timestamp(now.date())
    after_close = now.hour * 60 + now.minute >= 17 * 60 + 45
    added = []
    for plan in cfg["plans"]:
        t, amount, day = plan["ticker"], float(plan["amount"]), int(plan.get("day", 16))
        acc = cfg["assets"][t]["account"]
        buys = ledger[(ledger["ticker"] == t) & (ledger["type"] == "BUY")]["date"]
        # sans date de début, le plan n'est enregistré qu'à partir du mois en cours
        start = pd.Timestamp(plan["start"]) if plan.get("start") else today.replace(day=1)
        # mois courant et précédent (rattrapage si un run a sauté)
        months = [(today - pd.DateOffset(months=1)), today]
        for m in months:
            ex = execution_date(m.year, m.month, day, trading_days)
            if ex < start or ex > today or (ex == today and not after_close):
                continue
            # déjà saisi (par toi ou par le robot) : achat de la ligne entre J-2 et J+4
            if ((buys >= ex - pd.Timedelta(days=2)) & (buys <= ex + pd.Timedelta(days=4))).any():
                continue
            px = ohlc_by_ticker.get(t)
            if px is None or ex not in px.index:
                continue
            row = px.loc[ex]
            if acc == "PEA":
                est = (row["open"] + row["high"]) / 2
                n = math.floor(amount / est)
                if n <= 0:
                    continue
                qty, amt = n, round(n * est, 2)
                note = f"Plan d'épargne (estimé : {n} parts à ~{est:.4f} €) : remplace par le montant TR"
            else:
                est = (row["open"] + row["high"] + row["low"] + row["close"]) / 4
                qty, amt = round(amount / est, 6), amount
                note = f"Plan d'épargne (quantité estimée au cours moyen ~{est:.2f} €)"
            added.append({
                "date": ex.strftime("%Y-%m-%d"), "account": acc, "type": "BUY", "ticker": t,
                "quantity": qty, "amount": amt, "taxes": 0, "source": "AUTO", "note": note,
            })
            buys = pd.concat([buys, pd.Series([ex])], ignore_index=True)
    return added


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
        for r in rows:
            note = str(r["note"]).replace(",", ";")
            f.write(",".join([
                r["date"], r["account"], r["type"], r["ticker"], _fmt_qty(float(r["quantity"])),
                f"{float(r['amount']):.2f}", f"{float(r['taxes']):g}", r["source"], note,
            ]) + "\n")
