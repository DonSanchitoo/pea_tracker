"""Actualités par ligne (français et anglais) via les flux RSS de Google Actualités.

Pour chaque ligne détenue ou ayant un plan actif : une recherche FR et une recherche EN sur 7 jours
(mots-clés dans config.json, assets.<ticker>.news). Les articles sont classés par réputation de la
source (presse financière de référence en tête), fraîcheur et pertinence, puis dédoublonnés.
En cas d'échec réseau, les dernières actus connues sont conservées (data/news.json).
"""
import email.utils
import json
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote_plus

from .common import DATA_DIR

NEWS_FILE = os.path.join(DATA_DIR, "news.json")
UA = {"User-Agent": "Mozilla/5.0 (pea-tracker; +https://github.com/DonSanchitoo/pea_tracker)"}

# Réputation des sources (10 = référence). Les sources absentes valent 2.
SOURCES = {
    # anglais
    "bloomberg": 10, "reuters": 10, "financial times": 10, "the wall street journal": 10, "wsj": 10,
    "the economist": 9, "barron's": 8, "cnbc": 8, "nikkei asia": 8, "morningstar": 7, "marketwatch": 7,
    "associated press": 7, "ap news": 7, "bbc": 7, "fortune": 6, "yahoo finance": 6, "the guardian": 6,
    "south china morning post": 7, "coindesk": 8, "the block": 7, "decrypt": 6, "cointelegraph": 6,
    "business insider": 5, "forbes": 5, "investing.com": 5, "etf.com": 6, "seeking alpha": 4,
    "kiplinger": 5, "axios": 6, "the motley fool": 3, "benzinga": 3, "cryptoslate": 4, "fxstreet": 4,
    # français
    "les echos": 10, "le monde": 9, "l'agefi": 9, "agefi": 9, "investir": 8, "le figaro": 8, "boursorama": 8,
    "la tribune": 7, "bfm bourse": 7, "bfm business": 7, "bfmtv": 6, "zonebourse": 7, "capital": 6,
    "challenges": 6, "le revenu": 6, "mieux vivre votre argent": 6, "moneyvox": 6, "l'usine nouvelle": 6,
    "le point": 5, "l'express": 5, "tradingsat": 5, "abc bourse": 5, "cryptoast": 5, "journal du coin": 5,
    "journal du coin (jdc)": 5, "cointribune": 4, "france 24": 6, "franceinfo": 6, "afp": 8, "ouest-france": 4,
    "le parisien": 4, "20 minutes": 3, "café de la bourse": 4, "investing.com france": 5,
}
JUNK = re.compile(r"\b(stage|internship|intern|alternance|cdi|cdd|job|jobs|recrute|recrutement|hiring|h/f|horoscope)\b", re.I)
EDITIONS = {"fr": "hl=fr&gl=FR&ceid=FR:fr", "en": "hl=en-US&gl=US&ceid=US:en"}


def _norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"[^a-z0-9 ]", "", "".join(c for c in s if not unicodedata.combining(c)))


def _family(title):
    """Clé de dédoublonnage : 5 premiers mots sans chiffres (« Current price of Ethereum for Nov. 5 »...)."""
    words = _norm(re.sub(r"\d+", " ", title)).split()
    return " ".join(words[:5])


def source_weight(src):
    return SOURCES.get((src or "").strip().lower(), 2)


def _fetch(query, lang):
    import requests
    url = f"https://news.google.com/rss/search?q={quote_plus(query + ' when:7d')}&{EDITIONS[lang]}"
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src_el = it.find("source")
        src = (src_el.text or "").strip() if src_el is not None else ""
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].strip()
        try:
            dt = email.utils.parsedate_to_datetime(it.findtext("pubDate"))
        except (TypeError, ValueError):
            continue
        out.append(dict(title=title, source=src, url=it.findtext("link"), date=dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        lang=lang, _dt=dt))
    return out


def _keywords(query):
    words = re.findall(r'"([^"]+)"|(\b[^\s"()]+\b)', query)
    kws = [a or b for a, b in words]
    return [_norm(k) for k in kws if k and k.upper() not in ("OR", "AND") and len(k) > 2]


def _score(item, kws, now):
    age_h = max((now - item["_dt"]).total_seconds() / 3600, 0)
    rel = 3 if any(k and k in _norm(item["title"]) for k in kws) else 0
    return source_weight(item["source"]) * 2 + max(0, 7 - age_h / 24) * 1.5 + rel


def load():
    if os.path.exists(NEWS_FILE):
        with open(NEWS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"items": [], "updated_at": None}


def update(cfg, panel, fetch=True):
    previous = load()
    if not fetch:
        return previous
    now = datetime.now(timezone.utc)
    held = {t for t, s in panel.final_state.items() if s["qty"] > 1e-9}
    planned = {p["ticker"] for p in cfg["plans"] if p.get("active", True) is not False}
    targets = [(t, cfg["assets"][t]) for t in sorted(held | planned) if t in cfg["assets"]]
    per_line = int(cfg.get("news", {}).get("per_line", 4))
    queries = [("MARCHE", cfg.get("news", {}).get("market", {}))] + [(t, a.get("news") or {"fr": f'"{a["name"]}"', "en": f'"{a["name"]}"'}) for t, a in targets]
    items, errors = [], 0
    for key, q in queries:
        for lang in ("fr", "en"):
            query = q.get(lang)
            if not query:
                continue
            try:
                found = _fetch(query, lang)
            except Exception:
                errors += 1
                continue
            kws = _keywords(query)
            for it in found:
                it["score"] = round(_score(it, kws, now), 2)
                it["ticker"] = key
            found.sort(key=lambda x: -x["score"])
            seen, kept = set(), 0
            for it in found:
                k = _family(it["title"])
                if k in seen or JUNK.search(it["title"]) or "wall street journal" in it["title"].lower():
                    continue
                seen.add(k)
                items.append(it)
                kept += 1
                if kept >= per_line:
                    break
    if not items:
        return previous
    # dédoublonnage global : un même article cité pour plusieurs lignes garde toutes ses lignes
    merged = {}
    for it in sorted(items, key=lambda x: -x["score"]):
        k = _family(it["title"])
        if k in merged:
            if it["ticker"] not in merged[k]["tickers"]:
                merged[k]["tickers"].append(it["ticker"])
            continue
        it = dict(it)
        it["tickers"] = [it.pop("ticker")]
        it.pop("_dt", None)
        merged[k] = it
    out = {"updated_at": now.strftime("%Y-%m-%d %H:%M UTC"), "errors": errors,
           "items": sorted(merged.values(), key=lambda x: -x["score"])}
    with open(NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return out
