"""Mail de synthèse (hebdomadaire et/ou lendemain d'exécution des plans)."""
import io
import os
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

import pandas as pd

MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]

C = dict(ink="#111827", text="#0b0b0b", text2="#4b5563", muted="#6b7280", border="#e5e7eb", bg="#f3f4f6",
         surface="#ffffff", surface2="#f8f9fa", up="#006300", down="#d03b3b", blue="#2a78d6", warn="#fab219")


# ------------------------------------------------------------------ formats
def _nb(v, d=2):
    s = f"{abs(v):,.{d}f}".replace(",", " ").replace(".", ",")
    return s


def eur(v, d=2):
    return "–" if v is None else f"{'−' if v < 0 else ''}{_nb(v, d)} €"


def eurS(v, d=2):
    return "–" if v is None else f"{'+' if v > 0 else '−' if v < 0 else ''}{_nb(v, d)} €"


def pctS(v, d=2):
    return "–" if v is None else f"{'+' if v > 0 else '−' if v < 0 else ''}{_nb(v * 100, d)} %"


def pct(v, d=1):
    return "–" if v is None else f"{_nb(v * 100, d)} %"


def _qty(q):
    return f"{int(round(q))}" if abs(q - round(q)) < 1e-9 else f"{q:.6f}".rstrip("0").replace(".", ",")


def col(v):
    return C["muted"] if v is None or abs(v) < 1e-12 else (C["up"] if v > 0 else C["down"])


def arrow(v):
    return "" if v is None or abs(v) < 1e-12 else ("▲ " if v > 0 else "▼ ")


def colored(v, f):
    return f'<span style="color:{col(v)};white-space:nowrap">{arrow(v)}{f(v)}</span>'


def dshort(s):
    d = pd.Timestamp(s)
    return d.strftime("%d/%m/%Y")


def dlong(s):
    d = pd.Timestamp(s)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


# ------------------------------------------------------------------ graphique
def chart_png(data):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    dates = pd.to_datetime(data["series"]["dates"])
    S = data["series"]["TOTAL"]
    start = pd.Timestamp(S["start"]) - pd.Timedelta(days=1)
    m = dates >= start
    x = dates[m]
    v = pd.Series(S["value"], index=dates)[m]
    inv = pd.Series(S["invested"], index=dates)[m]

    fig, ax = plt.subplots(figsize=(6.0, 2.5), dpi=200)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.fill_between(x, v.values, color=C["ink"], alpha=0.07, linewidth=0)
    ax.plot(x, v.values, color=C["ink"], linewidth=1.6, label="Valeur")
    ax.step(x, inv.values, where="post", color=C["muted"], linewidth=1.2, label="Capital investi net")
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(C["border"])
    ax.grid(axis="y", color="#eceef1", linewidth=0.8)
    ax.tick_params(colors=C["muted"], labelsize=7, length=0)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{_nb(y, 0)} €"))
    ticks = pd.date_range(x[0], x[-1], freq="2MS")
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{MONTHS[t.month - 1]} {str(t.year)[2:]}" for t in ticks])
    ax.set_xlim(x[0], x[-1])
    ax.set_ylim(bottom=0)
    leg = ax.legend(loc="upper left", frameon=False, fontsize=7, labelcolor=C["text2"])
    for h in leg.legend_handles:
        h.set_linewidth(2)
    fig.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


# ------------------------------------------------------------------ HTML
TD = f"padding:8px 10px;border-bottom:1px solid {C['border']};font-size:13px;"
TH = f"padding:7px 10px;background:{C['surface2']};border-bottom:1px solid {C['border']};font-size:11px;color:{C['muted']};font-weight:600;text-align:left;"


def _section(title, body, sub=""):
    return f"""
<tr><td style="padding:18px 20px 6px">
  <table width="100%" cellpadding="0" cellspacing="0"><tr>
    <td style="font-size:14px;font-weight:700;color:{C['text']}">{title}</td>
    <td align="right" style="font-size:11px;color:{C['muted']}">{sub}</td></tr></table>
</td></tr>
<tr><td style="padding:0 20px">{body}</td></tr>"""


def _table(headers, rows, aligns):
    th = "".join(f'<th style="{TH}text-align:{a}">{h}</th>' for h, a in zip(headers, aligns))
    trs = ""
    for r in rows:
        bold = r[0].startswith("<b>") if isinstance(r[0], str) else False
        trs += "<tr>" + "".join(
            f'<td style="{TD}text-align:{a};{"font-weight:700;background:" + C["surface2"] + ";" if bold else ""}">{c}</td>'
            for c, a in zip(r, aligns)) + "</tr>"
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {C["border"]};border-collapse:collapse;border-radius:6px">{th and "<tr>" + th + "</tr>"}{trs}</table>'


def build_html(cfg, data, kind, added, cid):
    k = data["kpi"]
    per = {sc: {p["key"]: p for p in data["periods"][sc]} for sc in data["periods"]}
    url = cfg.get("dashboard_url", "#")
    today = data["meta"]["today"]
    asof = data["meta"]["asof"].get("PEA", today)
    titles = {"weekly": "Synthèse hebdomadaire", "dca": "Plans d'épargne exécutés", "weekly+dca": "Synthèse hebdomadaire et plans exécutés",
              "test": "Mail de test"}
    w = per["TOTAL"]["1S"]

    # hero
    hero = f"""
<tr><td style="padding:20px 20px 4px">
  <div style="font-size:12px;color:{C['muted']}">Valeur totale (PEA + crypto) au {dshort(asof)}</div>
  <div style="font-size:34px;font-weight:700;color:{C['text']};letter-spacing:-0.5px;margin-top:2px">{eur(k['TOTAL']['value'])}</div>
  <div style="font-size:13px;margin-top:2px">{colored(w['pnl'], eurS)} <span style="color:{C['muted']}">({pctS(w['twr'])}) sur 7 jours</span></div>
</td></tr>"""

    def tile(label, value, sub):
        return f"""<td width="25%" valign="top" style="padding:10px 12px;border:1px solid {C['border']};background:{C['surface']}">
          <div style="font-size:11px;color:{C['muted']}">{label}</div>
          <div style="font-size:16px;font-weight:700;color:{C['text']};margin-top:3px;white-space:nowrap">{value}</div>
          <div style="font-size:11px;color:{C['text2']};margin-top:2px">{sub}</div></td>"""

    tiles = f"""
<tr><td style="padding:12px 20px 0">
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse"><tr>
  {tile("PEA", eur(k['PEA']['value']), colored(per['PEA']['1S']['twr'], pctS) + " 7 j")}
  {tile("Crypto", eur(k['CRYPTO']['value']) if 'CRYPTO' in k else '–', (colored(per['CRYPTO']['1S']['twr'], pctS) + " 7 j") if 'CRYPTO' in per else '')}
  {tile("Plus-value totale", colored(k['TOTAL']['pnl'], eurS), pctS(k['TOTAL']['roi']) + " du versé")}
  {tile("Capital investi", eur(k['TOTAL']['invested'], 0), "TRI " + pctS(k['TOTAL']['xirr'], 1) + "/an")}
</tr></table></td></tr>"""

    body = hero + tiles

    # plans exécutés
    if "dca" in kind or kind == "test":
        plan_t = {p["ticker"] for p in cfg["plans"]}
        month = pd.Timestamp(today).strftime("%Y-%m")
        if kind == "test":  # test : derniers plans exécutés, quel que soit le mois
            month = max(t["date"] for t in data["transactions"] if t["type"] == "BUY" and t["ticker"] in plan_t)[:7]
        rows, tot = [], 0.0
        execd = [t for t in data["transactions"] if t["type"] == "BUY" and t["date"][:7] == month and t["ticker"] in plan_t]
        for t in sorted(execd, key=lambda t: t["ticker"]):
            src = "estimé" if t["source"] == "AUTO" else "TR"
            rows.append([t["short"], dshort(t["date"]), (f"{t['quantity']:g}" if t["account"] == "PEA" else f"{t['quantity']:.6f}").replace(".", ","),
                         eur(t["price"], 4 if (t["price"] or 0) < 10 else 2), eur(t["amount"]), src])
            tot += t["amount"]
        rows.append(["<b>Total investi</b>", "", "", "", f"<b>{eur(tot)}</b>", ""])
        note = ""
        if any(t["source"] == "AUTO" for t in execd):
            note = (f'<div style="font-size:12px;color:{C["text2"]};margin-top:8px">Montants <b>estimés</b> au cours du jour '
                    f'(nombre de parts exact dans 14 cas sur 14 jusqu\'ici). Pour être au centime, remplace-les par les montants TR '
                    f'dans <code>data/transactions.csv</code> et passe la source à TR. <a href="{url}aide.html#maj" style="color:{C["blue"]}">Comment faire</a></div>')
        resid = [p for p in data["plans"] if p.get("residual_pct") and p["residual_pct"] >= 0.1]
        if resid:
            p = resid[0]
            note += (f'<div style="font-size:12px;color:{C["text2"]};margin-top:6px">⚠ Plan {p["short"]} : ≈ {eur(p["residual"])} '
                     f'non investis par mois (parts entières). Montant conseillé : {" ou ".join(str(s["amount"]) + " €" for s in p["suggest"])}.</div>')
        last = max((t["date"] for t in execd), default=today)
        body += _section(f"Plans exécutés le {dshort(last)}",
                         _table(["Ligne", "Date", "Quantité", "Prix", "Montant", "Source"], rows, ["left", "left", "right", "right", "right", "left"]) + note)

    # graphique
    body += _section("Évolution depuis l'ouverture",
                     f'<img src="cid:{cid}" width="600" alt="Valeur et capital investi depuis l\'ouverture" style="display:block;width:100%;max-width:600px;height:auto;border:1px solid {C["border"]};border-radius:6px">')

    # performance
    prow = []
    for key, lab in (("1S", "7 jours"), ("1M", "1 mois"), ("YTD", "Depuis le 1er janv."), ("Origine", "Depuis l'ouverture")):
        p = per["PEA"][key]
        prow.append([lab, colored(p["twr"], pctS), colored(p["pnl"], eurS), colored(p.get("bench"), pctS),
                     colored((p["twr"] - p["bench"]) if p.get("bench") is not None else None, pctS)])
    body += _section("Performance du PEA", _table(["Période", "Perf. (TWR)", "Gain €", data["meta"]["benchmark"], "Écart"], prow,
                                                  ["left", "right", "right", "right", "right"]), "vs " + data["meta"]["benchmark"])

    # positions
    rows = []
    for p in data["positions"]:
        if not p["open"]:
            continue
        rows.append([f'<span style="color:{C["text"]}">{p["short"]}</span><br><span style="font-size:11px;color:{C["muted"]}">{p["account"]} · {_qty(p["qty"])} × {eur(p["price"], 3 if p["price"] < 10 else 2)}</span>',
                     eur(p["value"]), pct(p["weight_total"]),
                     f'{colored(p["unreal"], eurS)}<br><span style="font-size:11px">{colored(p["unreal_pct"], pctS)}</span>',
                     colored(p["week_pct"], pctS)])
    rows.append(["<b>Total</b>", f"<b>{eur(k['TOTAL']['value'])}</b>", "100 %", colored(k["TOTAL"]["unreal"], eurS), ""])
    body += _section("Positions", _table(["Ligne", "Valeur", "Poids", "+/- latente", "7 jours"], rows, ["left", "right", "right", "right", "right"]),
                     "PRU et performance comme TR")

    # risque
    r = data["risk"]["PEA"]
    risk = f"""<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse"><tr>
      {tile("Drawdown actuel", pctS(r.get('dd_current'), 1), "max " + pctS(r.get('dd_mdd'), 1))}
      {tile("Volatilité", pct(r.get('vol')), "annualisée")}
      {tile("VaR 95 % 1 jour", eur(r.get('var95_eur')), "1 jour sur 20, au moins")}
      {tile("Sharpe", _nb(r['sharpe'], 2) if r.get('sharpe') is not None else '–', "vs Livret A")}
    </tr></table>"""
    body += _section("Risque du PEA", risk)

    # à surveiller
    ins = [i for i in data["insights"] if i["level"] in ("alert", "warn")][:3]
    if ins:
        items = "".join(f'<div style="padding:8px 0;border-bottom:1px solid {C["border"]}"><b style="font-size:13px">{i["title"]}</b>'
                        f'<div style="font-size:12px;color:{C["text2"]};margin-top:2px">{i["text"]}</div></div>' for i in ins)
        body += _section("À surveiller", items)

    # agenda
    ev = "".join(f'<tr><td style="{TD}color:{C["muted"]};white-space:nowrap">{dshort(e["date"])}</td><td style="{TD}">{e["label"]}<br>'
                 f'<span style="font-size:11px;color:{C["muted"]}">{e["detail"]}</span></td><td style="{TD}text-align:right">{eur(e["amount"]) if e.get("amount") is not None else ""}</td></tr>'
                 for e in data["events"][:3])
    body += _section("Agenda", f'<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {C["border"]};border-collapse:collapse">{ev}</table>')

    f = data["fiscal"]
    cta = f"""
<tr><td style="padding:22px 20px 8px" align="center">
  <a href="{url}" style="background:#111111;color:#ffffff;text-decoration:none;font-weight:700;font-size:14px;padding:12px 26px;border-radius:6px;display:inline-block">Ouvrir le dashboard</a>
  <div style="font-size:12px;margin-top:8px"><a href="{url}aide.html" style="color:{C['blue']}">Guide des indicateurs</a></div>
</td></tr>
<tr><td style="padding:10px 20px 20px;font-size:11px;color:{C['muted']};line-height:1.5">
  PEA ouvert le {dshort(f['opened'])} · exonération d'impôt sur le revenu dans {f['days_left']} jours ({dshort(f['maturity'])}).<br>
  Cours de clôture Euronext du {dshort(asof)} : l'appli TR affiche un cours en continu, d'où un écart possible de quelques euros.
</td></tr>"""

    pre = f"{eur(k['TOTAL']['value'])} · {pctS(w['twr'])} sur 7 jours · plus-value {eurS(k['TOTAL']['pnl'])}"
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta name="color-scheme" content="light"><title>{titles[kind]}</title></head>
<body style="margin:0;padding:0;background:{C['bg']};font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:{C['text']}">
<div style="display:none;max-height:0;overflow:hidden">{pre}</div>
<table width="100%" cellpadding="0" cellspacing="0" style="background:{C['bg']}"><tr><td align="center" style="padding:20px 10px">
<table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;background:{C['surface']};border:1px solid {C['border']};border-radius:8px">
<tr><td style="padding:14px 20px;border-bottom:1px solid {C['border']}">
  <table width="100%" cellpadding="0" cellspacing="0"><tr>
    <td style="font-size:15px;font-weight:800;letter-spacing:-0.3px"><span style="display:inline-block;background:#111;color:#fff;border-radius:4px;padding:1px 6px;margin-right:6px">P</span>pea·tracker</td>
    <td align="right" style="font-size:12px;color:{C['muted']}">{titles[kind]} · {dlong(today)}</td></tr></table>
</td></tr>
{body}
{cta}
</table></td></tr></table></body></html>"""


def build_text(cfg, data, kind):
    k = data["kpi"]
    w = {p["key"]: p for p in data["periods"]["TOTAL"]}["1S"]
    lines = [f"PEA Tracker : {dlong(data['meta']['today'])}", "",
             f"Valeur totale : {eur(k['TOTAL']['value'])} ({eurS(w['pnl'])} sur 7 jours)",
             f"PEA : {eur(k['PEA']['value'])} | Crypto : {eur(k.get('CRYPTO', {}).get('value', 0))}",
             f"Plus-value totale : {eurS(k['TOTAL']['pnl'])} ({pctS(k['TOTAL']['roi'])} du versé)", "",
             f"Dashboard : {cfg.get('dashboard_url', '')}"]
    return "\n".join(lines)


def build_message(cfg, data, panel, kind, added):
    cid = make_msgid(domain="pea-tracker")[1:-1]
    html = build_html(cfg, data, kind, added, cid)
    png = chart_png(data)
    k = data["kpi"]["TOTAL"]
    w = {p["key"]: p for p in data["periods"]["TOTAL"]}["1S"]
    d = pd.Timestamp(data["meta"]["today"]).strftime("%d/%m")
    if kind == "test":
        subject = f"[Test] PEA · {eur(k['value'], 0)} · synthèse + plans exécutés"
    elif kind == "dca":
        subject = f"PEA · plans exécutés · {eur(k['value'], 0)} ({pctS(k['roi'], 1)} au total)"
    else:
        subject = f"PEA · {eur(k['value'], 0)} · {pctS(w['twr'], 1)} sur 7 j · synthèse du {d}"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("EMAIL_USER", "pea-tracker@example.invalid")
    msg["To"] = os.environ.get("EMAIL_RECEIVER", os.environ.get("EMAIL_USER", "pea-tracker@example.invalid"))
    msg.set_content(build_text(cfg, data, kind))
    msg.add_alternative(html, subtype="html")
    msg.get_payload()[1].add_related(png, maintype="image", subtype="png", cid=f"<{cid}>", filename="evolution.png")
    msg._pea_preview = (html, png, cid)
    return msg


def write_preview(msg, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    html, png, cid = msg._pea_preview
    with open(os.path.join(out_dir, "evolution.png"), "wb") as f:
        f.write(png)
    with open(os.path.join(out_dir, "mail.html"), "w", encoding="utf-8") as f:
        f.write(html.replace(f"cid:{cid}", "evolution.png"))
    with open(os.path.join(out_dir, "subject.txt"), "w", encoding="utf-8") as f:
        f.write(msg["Subject"] + "\n")


def send(msg):
    user, pwd = os.environ["EMAIL_USER"], os.environ["EMAIL_PASS"]
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pwd)
        s.send_message(msg)
