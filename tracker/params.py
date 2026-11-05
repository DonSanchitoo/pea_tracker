"""Paramètres économiques et fiscaux : valeur live (sources officielles) ou valeur manuelle.

Chaque paramètre de config.json["params"] a un mode :
- "auto"   : la valeur live est utilisée dès qu'elle est disponible, sinon la valeur de secours ;
- "manual" : la valeur saisie est toujours utilisée (la valeur live reste affichée pour info).
Les dernières valeurs live sont gardées dans data/live_params.json (utilisées si une source tombe).
"""
import html
import json
import os
import re
from datetime import datetime, timezone

from .common import DATA_DIR

LIVE_FILE = os.path.join(DATA_DIR, "live_params.json")
UA = {"User-Agent": "Mozilla/5.0 (pea-tracker; +https://github.com/DonSanchitoo/pea_tracker)"}


def _get(url, timeout=25):
    import requests
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r


def _text(url):
    raw = _get(url).text
    t = re.sub(r"<[^>]+>", " ", raw)
    return html.unescape(re.sub(r"\s+", " ", t))


def _pct(s):
    return float(s.replace(",", ".")) / 100


def fetch_inflation():
    url = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_minr"
           "?geo=FR&unit=RCH_A&coicop18=TOTAL&lastTimePeriod=1&format=JSON")
    d = _get(url).json()
    period = list(d["dimension"]["time"]["category"]["index"])[0]
    value = list(d["value"].values())[0] / 100
    return value, f"Eurostat, IPCH France, glissement sur 12 mois ({period})", "https://ec.europa.eu/eurostat/databrowser/view/prc_hicp_minr/default/table"


def fetch_livret_a():
    url = "https://www.service-public.gouv.fr/particuliers/vosdroits/F2365"
    m = re.search(r"taux d.int[ée]r[êe]t annuel du livret A est de (\d+(?:,\d+)?) ?%", _text(url), re.I)
    if not m:
        raise ValueError("taux introuvable sur la page")
    v = _pct(m.group(1))
    if not 0 <= v <= 0.1:
        raise ValueError(f"valeur aberrante {v}")
    return v, "service-public.gouv.fr (Livret A)", url


def fetch_ps_rate():
    url = "https://www.service-public.gouv.fr/particuliers/vosdroits/F2329"
    m = re.search(r"Pr[ée]l[èe]vement de solidarit[ée] \d+(?:,\d+)? ?% TOTAL (\d+(?:,\d+)?) ?%", _text(url), re.I)
    if not m:
        raise ValueError("taux introuvable sur la page")
    v = _pct(m.group(1))
    if not 0.15 <= v <= 0.25:
        raise ValueError(f"valeur aberrante {v}")
    return v, "service-public.gouv.fr (prélèvements sociaux sur revenus de placement)", url


def fetch_estr():
    url = "https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT?lastNObservations=1&format=csvdata"
    lines = _get(url).text.strip().splitlines()
    head, row = lines[0].split(","), lines[-1].split(",")
    v = float(row[head.index("OBS_VALUE")]) / 100
    return v, f"BCE, €STR du {row[head.index('TIME_PERIOD')]}", "https://data.ecb.europa.eu/main-figures/ecb-interest-rates-and-exchange-rates/euro-short-term-rate"


FETCHERS = {"inflation": fetch_inflation, "livret_a": fetch_livret_a, "ps_rate": fetch_ps_rate, "estr": fetch_estr}


def load_live():
    if os.path.exists(LIVE_FILE):
        with open(LIVE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def update_live(fetch=True):
    live = load_live()
    warnings = []
    if fetch:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        for key, fn in FETCHERS.items():
            try:
                v, label, url = fn()
                live[key] = {"value": round(v, 6), "source": label, "url": url, "fetched_at": now}
            except Exception as e:
                warnings.append(f"Paramètre live « {key} » non mis à jour ({str(e)[:80]}), dernière valeur connue utilisée.")
        with open(LIVE_FILE, "w", encoding="utf-8") as f:
            json.dump(live, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
    return live, warnings


def resolve(cfg, live):
    """Valeurs effectives + traçabilité. Injecte aussi les blocs historiques cfg['tax'] et cfg['risk_free']."""
    out = {}
    for key, p in cfg.get("params", {}).items():
        lv = live.get(key)
        use_live = p.get("mode", "manual") == "auto" and lv is not None
        out[key] = {
            "label": p.get("label", key), "mode": p.get("mode", "manual"),
            "manual": p.get("value"), "live": lv["value"] if lv else None,
            "live_source": lv.get("source") if lv else None, "live_url": lv.get("url") if lv else None,
            "live_date": lv.get("fetched_at") if lv else None,
            "value": lv["value"] if use_live else p.get("value"),
            "origin": "live" if use_live else "manuel",
        }
    v = lambda k, d: out.get(k, {}).get("value", d)
    cfg["tax"] = {"ps_rate": v("ps_rate", 0.186), "ir_rate_pfu": v("ir_rate_pfu", 0.128), "ttf_rate": v("ttf_rate", 0.004)}
    cfg["risk_free"] = {"label": "Livret A", "rate": v("livret_a", 0.017)}
    cfg["inflation"] = v("inflation", 0.02)
    return out
