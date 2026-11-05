"""Exposition des lignes par pays et par secteur (transparence des ETF).

Source live : la fiche justETF de chaque ETF (par ISIN), qui publie les 4 premiers pays et secteurs
et le reste regroupé en « Autre » (mise à jour mensuelle par l'émetteur). Rafraîchie chaque semaine,
gardée dans data/exposure.json. Le reste « Autre » est réparti selon la répartition indicative de
config.json (countries / sectors) ; sans source live, c'est cette répartition indicative qui sert.
"""
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone

from .common import DATA_DIR

EXPO_FILE = os.path.join(DATA_DIR, "exposure.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) pea-tracker", "Accept-Language": "fr-FR,fr"}

# pays -> grande zone (pour les barres « par zone »)
REGION = {
    "États-Unis": "Amérique du Nord", "Canada": "Amérique du Nord",
    "France": "France",
    "Grande-Bretagne": "Europe", "Suisse": "Europe", "Allemagne": "Europe", "Pays-Bas": "Europe", "Danemark": "Europe",
    "Suède": "Europe", "Italie": "Europe", "Espagne": "Europe", "Finlande": "Europe", "Belgique": "Europe", "Norvège": "Europe",
    "Irlande": "Europe", "Autriche": "Europe", "Portugal": "Europe", "Luxembourg": "Europe", "Pologne": "Europe",
    "Japon": "Japon",
    "Australie": "Pacifique développé", "Hong Kong": "Pacifique développé", "Singapour": "Pacifique développé", "Nouvelle-Zélande": "Pacifique développé",
    "Chine": "Chine", "Taïwan": "Taïwan", "Inde": "Inde", "Corée du Sud": "Corée du Sud",
    "Indonésie": "Autres émergents", "Malaisie": "Autres émergents", "Thaïlande": "Autres émergents", "Philippines": "Autres émergents",
    "Brésil": "Autres émergents", "Mexique": "Autres émergents", "Afrique du Sud": "Autres émergents", "Arabie saoudite": "Autres émergents",
    "Émirats arabes unis": "Autres émergents", "Qatar": "Autres émergents", "Koweït": "Autres émergents", "Turquie": "Autres émergents",
    "Chili": "Autres émergents", "Pérou": "Autres émergents", "Colombie": "Autres émergents", "Grèce": "Autres émergents", "Vietnam": "Autres émergents",
}
OTHER = {"autre", "autres"}


def _parse(text):
    t = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)))
    m = re.search(r" Pays ((?:[^%]{2,40}? \d+,\d+% )+)(?:Afficher plus )?Secteurs ((?:[^%]{2,60}? \d+,\d+% )+)(?:Afficher plus )?État : (\d\d/\d\d/\d{4})", t)
    if not m:
        return None
    pairs = lambda g: {a.strip(): float(b.replace(",", ".")) for a, b in re.findall(r"(.+?) (\d+,\d+)% ", g)}
    return {"countries": pairs(m.group(1)), "sectors": pairs(m.group(2)), "date": m.group(3)}


def load():
    if os.path.exists(EXPO_FILE):
        with open(EXPO_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def update(cfg, fetch=True, max_age_days=7):
    data = load()
    if not fetch:
        return data, []
    import requests
    warnings, changed = [], False
    now = datetime.now(timezone.utc)
    for t, a in cfg["assets"].items():
        if a.get("kind") != "ETF" or not a.get("isin"):
            continue
        old = data.get(t, {})
        try:
            if old.get("fetched_at") and now - datetime.strptime(old["fetched_at"], "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc) < timedelta(days=max_age_days):
                continue
        except ValueError:
            pass
        try:
            r = requests.get(f"https://www.justetf.com/fr/etf-profile.html?isin={a['isin']}", headers=UA, timeout=30)
            r.raise_for_status()
            p = _parse(r.text)
            data[t] = dict(p or {}, fetched_at=now.strftime("%Y-%m-%d %H:%M UTC"), source="justETF" if p else None,
                           url=f"https://www.justetf.com/fr/etf-profile.html?isin={a['isin']}")
            changed = True
        except Exception as e:
            warnings.append(f"Exposition {a['short']} non mise à jour ({str(e)[:60]}), dernière version gardée.")
    if changed:
        with open(EXPO_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
    return data, warnings


def _merge(live, indicative):
    """Top live + « Autre » réparti selon la répartition indicative (hors pays/secteurs déjà en top)."""
    if not live:
        return dict(indicative or {})
    top = {k: v for k, v in live.items() if k.lower() not in OTHER}
    rest = max(100 - sum(top.values()), 0)
    pool = {k: v for k, v in (indicative or {}).items() if k not in top and k.lower() not in OTHER}
    tot = sum(pool.values())
    out = dict(top)
    if rest > 0.01:
        if tot > 0:
            for k, v in pool.items():
                out[k] = out.get(k, 0) + rest * v / tot
        else:
            out["Autres"] = out.get("Autres", 0) + rest
    return out


def effective(cfg, live):
    """Pour chaque ligne : pays, secteurs, zones (en % de la ligne) et provenance."""
    out = {}
    for t, a in cfg["assets"].items():
        lv = live.get(t) or {}
        has_live = bool(lv.get("countries"))
        if a.get("account") == "CRYPTO" or a.get("kind") == "Crypto":
            countries, sectors = {}, {"Crypto-actifs": 100}
        else:
            countries = _merge(lv.get("countries"), a.get("countries"))
            sectors = _merge(lv.get("sectors"), a.get("sectors")) or {"Non renseigné": 100}
        if countries:
            zones = {}
            for c, w in countries.items():
                z = REGION.get(c, "Autres")
                zones[z] = zones.get(z, 0) + w
        else:
            zones = dict(a.get("zones") or {"Crypto (hors zone)": 100})
        out[t] = dict(countries=countries, sectors=sectors, zones=zones,
                      source=(f"justETF, état au {lv['date']}" if has_live else
                              "secteur et pays de l'entreprise" if a.get("kind") == "Action" else
                              "hors pays (crypto)" if a.get("kind") == "Crypto" else "répartition indicative (config.json)"),
                      url=lv.get("url"))
    return out
