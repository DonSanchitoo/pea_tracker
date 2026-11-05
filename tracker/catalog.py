"""Catalogue des instruments sélectionnables dans « Mes données » (recherche par nom, ticker, ISIN).

Sources (sans clé d'API), rafraîchies chaque semaine :
- Euronext : toutes les actions de Paris (Euronext Paris + Growth) et tous les ETF cotés à Paris ;
- CoinGecko : les 150 premières cryptos par capitalisation.
Le ticker Yahoo est dérivé du mnémonique (AI -> AI.PA, SOL -> SOL-EUR). Le robot vérifie ensuite
que Yahoo connaît bien le ticker choisi.
"""
import csv
import io
import json
import os
from datetime import datetime, timedelta, timezone

from .common import DATA_DIR

CATALOG_FILE = os.path.join(DATA_DIR, "catalog.json")
UA = {"User-Agent": "Mozilla/5.0 (pea-tracker; +https://github.com/DonSanchitoo/pea_tracker)"}
EURONEXT = [
    ("https://live.euronext.com/en/pd_es/data/stocks/download?mics=XPAR%2CALXP", "Action"),
    ("https://live.euronext.com/en/pd_es/data/track/download?mics=XPAR", "ETF"),
]
# Euronext abrège les noms (« AM NSDQ 100 PEA ») : mots-clés étendus pour la recherche
ABBR = {
    "AM": "amundi", "AMU": "amundi", "NSDQ": "nasdaq", "NASD": "nasdaq", "NDX": "nasdaq 100", "SP": "s&p 500", "S&P": "s&p 500",
    "BNPP": "bnp paribas easy", "BNP": "bnp paribas", "ISH": "ishares", "ISHS": "ishares", "LYX": "lyxor amundi", "XTR": "xtrackers",
    "WLD": "world monde", "WRLD": "world monde", "WORLD": "world monde", "MONDE": "world monde", "EM": "emerging emergents",
    "EMERG": "emerging emergents", "EMRG": "emerging emergents", "EUROP": "europe", "EUR": "euro europe", "JAP": "japan japon",
    "JPN": "japan japon", "JAPAN": "japan japon", "US": "usa etats-unis", "USA": "usa etats-unis", "TECH": "technologie tech",
    "DIV": "dividende dividend", "GOV": "obligations government", "STX": "stoxx", "STOXX": "stoxx europe", "CAC": "cac 40 france",
    "ASIA": "asie asia", "ASIP": "asie asia pacifique", "CHIN": "chine china", "INDIA": "inde india", "SMALL": "small cap petites",
    "SC": "small cap petites", "SEMIC": "semi-conducteurs semiconductors", "HEALTH": "sante health", "ENERG": "energie energy",
}
COINGECKO = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=eur&order=market_cap_desc&per_page=150&page=1"


def _euronext(url, kind):
    import requests
    r = requests.get(url, headers=UA, timeout=40)
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")
    out = []
    for row in csv.reader(io.StringIO(text), delimiter=";"):
        if len(row) < 5 or len(row[1]) != 12 or not row[1][:2].isalpha():
            continue
        name, isin, sym, market = row[0].strip(), row[1].strip(), row[2].strip(), row[3].strip()
        if not sym or row[4].strip() not in ("EUR", ""):
            continue
        toks = [t.strip(".,()") for t in name.upper().split()]
        extra = " ".join(ABBR[t] for t in toks if t in ABBR)
        price = None
        for col in (13, 8):
            try:
                price = float(row[col].replace(",", "")) if len(row) > col and row[col] not in ("", "-") else None
            except ValueError:
                price = None
            if price:
                break
        out.append({"s": f"{sym}.PA", "n": name, "i": isin, "t": kind, "m": market, "k": extra, "p": price})
    return out


def _coingecko():
    import requests
    r = requests.get(COINGECKO, headers=UA, timeout=40)
    r.raise_for_status()
    stable = {"usdt", "usdc", "dai", "fdusd", "usde", "tusd", "eurc", "pyusd", "usds", "busd"}
    return [{"s": f"{c['symbol'].upper()}-EUR", "n": c["name"], "i": "", "t": "Crypto", "m": "Crypto", "p": c.get("current_price")}
            for c in r.json() if c.get("symbol") and c["symbol"].lower() not in stable]


def update(fetch=True, max_age_days=7, force=False):
    """Rafraîchit le catalogue s'il a plus de `max_age_days` jours. Retourne une liste d'avertissements."""
    if not fetch:
        return []
    if os.path.exists(CATALOG_FILE) and not force:
        with open(CATALOG_FILE, encoding="utf-8") as f:
            old = json.load(f)
        try:
            age = datetime.now(timezone.utc) - datetime.strptime(old["updated_at"], "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
            if age < timedelta(days=max_age_days):
                return []
        except (KeyError, ValueError):
            pass
    items, warnings = [], []
    for url, kind in EURONEXT:
        try:
            items += _euronext(url, kind)
        except Exception as e:
            warnings.append(f"Catalogue Euronext ({kind}) non mis à jour : {str(e)[:80]}")
    try:
        items += _coingecko()
    except Exception as e:
        warnings.append(f"Catalogue crypto non mis à jour : {str(e)[:80]}")
    if len(items) < 100:
        return warnings + ["Catalogue incomplet : ancienne version conservée."]
    seen, uniq = set(), []
    for it in items:
        if it["s"] not in seen:
            seen.add(it["s"])
            uniq.append(it)
    with open(CATALOG_FILE, "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "items": uniq},
                  f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    return warnings
