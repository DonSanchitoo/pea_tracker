"""Récupération des cours Yahoo Finance avec cache local.

Les cours Yahoo sont ajustés des splits / attributions gratuites. Comme le
registre garde les quantités réellement détenues, on « dé-ajuste » les cours
antérieurs à chaque split pour valoriser l'historique au vrai prix du jour.
"""
import json
import os
import time

import pandas as pd

from .common import ACTIONS_FILE, PRICES_FILE

COLS = ["date", "ticker", "open", "high", "low", "close"]


def _fetch_one(ticker, start):
    import yfinance as yf

    last_err = None
    for wait in (0, 3, 8, 20):
        if wait:
            time.sleep(wait)
        try:
            tk = yf.Ticker(ticker)
            h = tk.history(start=start, auto_adjust=False, actions=True)
            if h is None or h.empty:
                raise RuntimeError("historique vide")
            idx = h.index
            if getattr(idx, "tz", None) is not None:
                idx = idx.tz_localize(None)
            h.index = idx.normalize()
            h = h[~h.index.duplicated(keep="last")]
            ohlc = pd.DataFrame({
                "date": h.index.strftime("%Y-%m-%d"),
                "ticker": ticker,
                "open": h["Open"].values,
                "high": h["High"].values,
                "low": h["Low"].values,
                "close": h["Close"].values,
            }).dropna(subset=["close"])
            splits = {d.strftime("%Y-%m-%d"): float(v) for d, v in h.get("Stock Splits", pd.Series(dtype=float)).items() if v and v != 0}
            divs = {d.strftime("%Y-%m-%d"): float(v) for d, v in h.get("Dividends", pd.Series(dtype=float)).items() if v and v != 0}
            return ohlc, {"splits": splits, "dividends": divs}
        except Exception as e:  # réseau, rate-limit Yahoo...
            last_err = e
    raise RuntimeError(f"{ticker}: {last_err}")


def load_cache():
    ohlc = pd.read_csv(PRICES_FILE) if os.path.exists(PRICES_FILE) else pd.DataFrame(columns=COLS)
    actions = {}
    if os.path.exists(ACTIONS_FILE):
        with open(ACTIONS_FILE, encoding="utf-8") as f:
            actions = json.load(f)
    return ohlc, actions


def update_prices(tickers, start, fetch=True):
    """Met à jour le cache pour `tickers` depuis `start`. Retourne (ohlc, actions, warnings)."""
    ohlc, actions = load_cache()
    warnings = []
    if fetch:
        for t in tickers:
            try:
                new, act = _fetch_one(t, start)
                ohlc = pd.concat([ohlc[ohlc["ticker"] != t], new], ignore_index=True)
                actions[t] = act
            except Exception as e:
                warnings.append(f"Cours non mis à jour pour {t} ({e}). Utilisation du cache.")
        ohlc = ohlc.sort_values(["ticker", "date"]).reset_index(drop=True)
        out = ohlc.copy()
        for c in ("open", "high", "low", "close"):
            out[c] = out[c].astype(float).round(5)
        out[COLS].to_csv(PRICES_FILE, index=False)
        with open(ACTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(actions, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
    missing = [t for t in tickers if t not in set(ohlc["ticker"])]
    for t in missing:
        warnings.append(f"Aucun cours disponible pour {t}.")
    return ohlc, actions, warnings


def split_factor(actions, ticker, dates):
    """Facteur multiplicatif à appliquer aux cours Yahoo pour retrouver le cours réel du jour."""
    f = pd.Series(1.0, index=dates)
    for d, ratio in actions.get(ticker, {}).get("splits", {}).items():
        f[f.index < pd.Timestamp(d)] *= ratio
    return f


def unadjusted(ohlc, actions, ticker):
    """OHLC réel (non ajusté des splits) d'un ticker, indexé par date."""
    df = ohlc[ohlc["ticker"] == ticker].copy()
    if df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    df.index = pd.to_datetime(df["date"])
    df = df[["open", "high", "low", "close"]].astype(float)
    f = split_factor(actions, ticker, df.index)
    return df.mul(f, axis=0)


def unadjusted_dividends(actions, ticker):
    divs = actions.get(ticker, {}).get("dividends", {})
    if not divs:
        return pd.Series(dtype=float)
    s = pd.Series(divs, dtype=float)
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()
    return s * split_factor(actions, ticker, s.index)
