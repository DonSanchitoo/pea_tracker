/* PEA Tracker : rendu du dashboard à partir de data/dashboard.js (window.PEA_DATA). */
(function () {
  'use strict';
  const D = window.PEA_DATA;
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  if (!D) {
    $('.content').innerHTML = '<div class="warn-banner">Données absentes. Lance <code>python pea_tracker.py</code> pour générer <code>data/dashboard.js</code>.</div>';
    return;
  }

  // ------------------------------------------------------------ état & stockage
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* stockage indisponible */ } },
  };
  const VIEWS = ['overview', 'performance', 'risque', 'positions', 'allocation', 'crypto', 'projection', 'transactions', 'news', 'donnees'];
  const SCOPE_LABEL = { TOTAL: 'Consolidé', PEA: 'PEA', CRYPTO: 'Crypto' };
  const state = {
    scope: D.meta.scopes.includes(store.get('pea-scope', 'TOTAL')) ? store.get('pea-scope', 'TOTAL') : 'TOTAL',
    period: store.get('pea-period', 'MAX'),
    view: 'overview', ovMode: 'value', pos: null, pjH: 'mat', posMode: store.get('pea-posmode', 'line'), posInt: 'D',
  };
  const charts = {};

  // ------------------------------------------------------------ formats
  const NF = {};
  const nf = (d) => (NF[d] = NF[d] || new Intl.NumberFormat('fr-FR', { minimumFractionDigits: d, maximumFractionDigits: d }));
  const isNum = (v) => typeof v === 'number' && isFinite(v);
  const eur = (v, d = 2) => (isNum(v) ? nf(d).format(v) + ' €' : '–');
  const eurS = (v, d = 2) => (isNum(v) ? (v > 0 ? '+' : v < 0 ? '−' : '') + nf(d).format(Math.abs(v)) + ' €' : '–');
  const pct = (v, d = 2) => (isNum(v) ? nf(d).format(v * 100) + ' %' : '–');
  const pctS = (v, d = 2) => (isNum(v) ? (v > 0 ? '+' : v < 0 ? '−' : '') + nf(d).format(Math.abs(v * 100)) + ' %' : '–');
  const num = (v, d = 2) => (isNum(v) ? nf(d).format(v) : '–');
  const qty = (q) => (isNum(q) ? (Math.abs(q - Math.round(q)) < 1e-9 ? nf(0).format(q) : new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 6 }).format(q)) : '–');
  const cls = (v) => (!isNum(v) || Math.abs(v) < 1e-12 ? 'flat' : v > 0 ? 'up' : 'down');
  const arrow = (v) => (!isNum(v) || Math.abs(v) < 1e-12 ? '' : v > 0 ? '▲ ' : '▼ ');
  const dPct = (v, d = 2) => `<span class="${cls(v)}">${arrow(v)}${pctS(v, d)}</span>`;
  const dEur = (v, d = 2) => `<span class="${cls(v)}">${arrow(v)}${eurS(v, d)}</span>`;
  const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
  const parseISO = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
  const iso = (dt) => `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
  const dShort = (s) => { if (!s) return '–'; const d = parseISO(s); return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`; };
  const dLong = (s) => { const d = typeof s === 'string' ? parseISO(s) : s; return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`; };
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const cv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const slot = (s) => cv('--s' + (s || 8));
  const assetColor = (t) => slot((D.assets[t] || {}).slot);
  const help = (id) => `<a class="help" href="aide.html#${id}" title="Explication">?</a>`;

  // ------------------------------------------------------------ fenêtres de temps
  function addMonths(s, n) { const d = parseISO(s); const day = d.getDate(); d.setDate(1); d.setMonth(d.getMonth() + n); const last = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate(); d.setDate(Math.min(day, last)); return iso(d); }
  function windowStart(last, first) {
    let s;
    switch (state.period) {
      case '1M': s = addMonths(last, -1); break;
      case '3M': s = addMonths(last, -3); break;
      case '6M': s = addMonths(last, -6); break;
      case 'YTD': s = `${parseISO(last).getFullYear() - 1}-12-31`; break;
      case '1A': s = addMonths(last, -12); break;
      default: s = first;
    }
    return s < first ? first : s;
  }
  const dayBefore = (s) => { const d = parseISO(s); d.setDate(d.getDate() - 1); return iso(d); };
  function idxFrom(dates, from) { let i = dates.findIndex((d) => d >= from); return i < 0 ? dates.length - 1 : i; }
  function scopeWindow(scope) {
    const dates = D.series.dates;
    const first = dayBefore(D.series[scope].start);
    const ws = windowStart(dates[dates.length - 1], first < dates[0] ? dates[0] : first);
    return { i0: idxFrom(dates, ws), dates };
  }

  // ------------------------------------------------------------ ECharts
  function mk(id) {
    const el = document.getElementById(id);
    if (!el || !window.echarts) return null;
    let c = charts[id];
    if (c && c.getDom() !== el) { c.dispose(); c = null; }
    if (!c) { c = echarts.init(el, null, { renderer: 'canvas' }); charts[id] = c; }
    return c;
  }
  function timeLabel(spanDays) {
    return (v) => { const d = new Date(v); return spanDays > 1100 ? String(d.getFullYear()) : spanDays > 150 ? `${MONTHS[d.getMonth()]} ${String(d.getFullYear()).slice(2)}` : `${d.getDate()} ${MONTHS[d.getMonth()]}`; };
  }
  function base(extra) {
    const o = {
      animation: false,
      textStyle: { fontFamily: cv('--font') || 'system-ui', color: cv('--text-2') },
      grid: { left: 8, right: 14, top: 12, bottom: 4, containLabel: true },
      tooltip: {
        trigger: 'axis', confine: true, backgroundColor: cv('--surface'), borderColor: cv('--border-strong'), borderWidth: 1,
        textStyle: { color: cv('--text'), fontSize: 12 }, extraCssText: 'box-shadow:0 4px 14px rgba(0,0,0,.12);border-radius:6px;',
        axisPointer: { type: 'line', lineStyle: { color: cv('--muted'), width: 1 } },
      },
    };
    return Object.assign(o, extra || {});
  }
  function xTime(spanDays) {
    return { type: 'time', splitNumber: window.innerWidth < 640 ? 3 : 6, axisLine: { lineStyle: { color: cv('--axis') } }, axisTick: { show: false }, splitLine: { show: false },
      axisLabel: { color: cv('--muted'), fontSize: 11, hideOverlap: true, formatter: timeLabel(spanDays) } };
  }
  function yVal(fmt, extra) {
    return Object.assign({ type: 'value', scale: false, axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: cv('--grid'), width: 1 } },
      axisLabel: { color: cv('--muted'), fontSize: 11, formatter: fmt } }, extra || {});
  }
  const axEur = (v) => (Math.abs(v) >= 10000 ? nf(0).format(v / 1000) + ' k€' : nf(0).format(v) + ' €');
  const axPct = (v) => nf(Math.abs(v) < 0.1 && v !== 0 ? 1 : 0).format(v * 100) + ' %';
  function tip(fmt) {
    return (ps) => {
      ps = Array.isArray(ps) ? ps : [ps];
      if (!ps.length) return '';
      const d = new Date(ps[0].axisValue != null ? ps[0].axisValue : ps[0].value[0]);
      let h = `<div style="font-weight:650;margin-bottom:4px">${dLong(d)}</div>`;
      ps.forEach((p) => {
        const v = Array.isArray(p.value) ? p.value[1] : p.value;
        if (v == null) return;
        h += `<div style="display:flex;justify-content:space-between;gap:14px"><span>${p.marker}${esc(p.seriesName)}</span><b style="font-variant-numeric:tabular-nums">${fmt(v, p)}</b></div>`;
      });
      return h;
    };
  }
  function line(name, data, color, o) {
    return Object.assign({ name, type: 'line', data, showSymbol: false, symbolSize: 8, lineStyle: { width: 2, color }, itemStyle: { color, borderColor: cv('--surface'), borderWidth: 2 },
      emphasis: { disabled: true } }, o || {});
  }
  const wash = (color, a = 0.1) => ({ color: hexA(color, a) });
  function hexA(hex, a) {
    const h = hex.replace('#', '');
    if (h.length !== 6) return hex;
    return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
  }
  function legend(id, items) {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = items.map((it) => `<span><i class="${it.sq ? 'sq' : ''}" style="background:${it.color}"></i>${esc(it.label)}</span>`).join('');
  }
  const spanDays = (a, b) => (parseISO(b) - parseISO(a)) / 864e5;

  // ------------------------------------------------------------ chrome
  function renderChrome() {
    $$('#scope-seg button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.scope === state.scope)));
    $$('#period-seg button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.period === state.period)));
    const asof = D.meta.asof[state.scope] || D.meta.today;
    $('#asof').innerHTML = `Cours au <b>${dShort(asof)}</b> · généré le ${esc(D.meta.generated_at.replace(' ', ' à '))}`;
    if (D.meta.warnings && D.meta.warnings.length) {
      $('#warnings').innerHTML = `<div class="warn-banner"><b>Données partielles :</b> ${D.meta.warnings.map(esc).join(' · ')}</div>`;
    }
    const nextPlan = D.events.find((e) => e.kind === 'plan');
    const f = D.fiscal;
    $('#side-foot').innerHTML = `
      ${nextPlan ? `<div class="side-card"><div class="lbl">Prochaine exécution</div>
        <div class="row"><span class="big">${dLong(nextPlan.date)}</span><span class="lbl">J−${Math.max(0, Math.round(spanDays(D.meta.today, nextPlan.date)))}</span></div>
        <div class="lbl" style="margin-top:2px">${eur(nextPlan.amount, 0)} · ${esc(nextPlan.detail)}</div></div>` : ''}
      ${D.reserve ? `<a class="side-card" href="#donnees/reserve" style="text-decoration:none;display:block"><div class="lbl">Réserve de liquidité PEA</div>
        <div class="row"><span class="big">${eur(D.reserve.balance)}</span><span class="lbl">≈ +${eur(D.reserve.monthly_estimate, 0)}/mois</span></div></a>` : ''}
      <div class="side-card"><div class="lbl">Échéance fiscale PEA</div>
        <div class="row"><span class="big">${dShort(f.maturity)}</span><span class="lbl">${nf(0).format(f.days_left)} j</span></div>
        <div class="meter"><div style="width:${(f.progress * 100).toFixed(1)}%"></div></div>
        <div class="lbl">${pct(f.progress, 0)} du chemin vers l'exonération d'IR</div></div>
      <a class="btn" href="#donnees">Mettre à jour mes données</a>`;
    const open = D.positions.filter((p) => p.open);
    const items = open.map((p) => `<span class="item"><b>${esc(p.short)}</b>${eur(p.price, p.price > 1000 ? 0 : 2)} <span class="${p.day_pct >= 0 ? 'tu' : 'td'}">${arrow(p.day_pct)}${pctS(p.day_pct)}</span></span>`).join('');
    const k = D.kpi.TOTAL;
    $('#ticker').innerHTML = `${items}<span class="item"><b>Total</b>${eur(k.value)}</span>${items}<span class="item"><b>Total</b>${eur(k.value)}</span>`;
  }

  // ------------------------------------------------------------ VUE D'ENSEMBLE
  function kpiTile(o) {
    return `<div class="kpi ${o.hero ? 'hero' : ''}"><div class="lbl"><span>${o.label}</span>${o.help ? help(o.help) : ''}</div>
      <div class="val">${o.value}</div><div class="delta">${o.delta || '&nbsp;'}</div></div>`;
  }
  function renderOverview() {
    const sc = state.scope, k = D.kpi[sc], per = D.periods[sc];
    const p1 = per.find((p) => p.key === '1J');
    $('#ov-kpis').innerHTML = [
      kpiTile({ hero: true, label: `Valeur ${sc === 'TOTAL' ? 'totale (PEA + crypto)' : sc === 'PEA' ? 'du PEA' : 'du wallet crypto'}`, help: 'valeur', value: eur(k.value),
        delta: `${dEur(p1.pnl)} (${pctS(p1.twr)}) sur 1 séance` }),
      kpiTile({ label: 'Plus-value totale', help: 'gain-total', value: `<span class="${cls(k.pnl)}">${eurS(k.pnl)}</span>`, delta: `${pctS(k.roi)} du capital investi` }),
      kpiTile({ label: 'Plus-value latente (TR)', help: 'latente', value: `<span class="${cls(k.unreal)}">${eurS(k.unreal)}</span>`, delta: `${pctS(k.unreal_pct)} vs PRU` }),
      kpiTile({ label: 'Capital investi net', help: 'investi', value: eur(k.invested), delta: `depuis le ${dShort(k.start)}` }),
      kpiTile({ label: 'Performance TWR', help: 'twr', value: `<span class="${cls(k.twr)}">${pctS(k.twr)}</span>`, delta: k.twr_ann != null ? `${pctS(k.twr_ann)} / an` : 'non annualisée' }),
      kpiTile({ label: 'TRI annualisé', help: 'tri', value: `<span class="${cls(k.xirr)}">${pctS(k.xirr)}</span>`, delta: 'rendement réel de tes euros' }),
    ].join('');

    renderEvolution();

    $('#ov-insights').innerHTML = D.insights.map((i) => `<div class="ins ${i.level}"><span class="ic">${{ alert: '!', warn: '!', good: '✓', info: 'i' }[i.level]}</span>
      <div><b>${esc(i.title)}</b><p>${esc(i.text)}</p></div></div>`).join('') || '<div class="empty">Rien à signaler.</div>';

    const pos = D.positions.filter((p) => p.open && (sc === 'TOTAL' || p.account === sc));
    const tot = pos.reduce((a, p) => a + p.value, 0);
    const totUnreal = pos.reduce((a, p) => a + p.unreal, 0);
    const totCost = pos.reduce((a, p) => a + p.cost, 0);
    $('#ov-pos-sub').textContent = `${pos.length} lignes ouvertes`;
    $('#ov-positions').innerHTML = `<table class="t"><thead><tr><th>Ligne</th><th class="n">Qté</th><th class="n">PRU</th><th class="n">Cours</th><th class="n">Valeur</th><th class="n">Poids</th><th class="n">+/- latente</th><th class="n">1 jour</th></tr></thead><tbody>
      ${pos.map((p) => `<tr data-t="${esc(p.ticker)}" style="cursor:pointer"><td><div class="name"><span class="dot" style="background:${assetColor(p.ticker)}"></span><div>${esc(p.short)}<small>${esc(p.account)} · ${esc(p.kind)}</small></div></div></td>
        <td class="n">${qty(p.qty)}</td><td class="n">${eur(p.pru, p.pru > 1000 ? 2 : 2)}</td><td class="n">${eur(p.price, p.price < 10 ? 3 : 2)}</td><td class="n">${eur(p.value)}</td>
        <td class="n">${pct(tot ? p.value / tot : 0, 1)}</td><td class="n">${dEur(p.unreal)}<br><small class="${cls(p.unreal_pct)}">${pctS(p.unreal_pct)}</small></td><td class="n">${dPct(p.day_pct)}</td></tr>`).join('')}
      <tr class="total"><td>Total</td><td></td><td></td><td></td><td class="n">${eur(tot)}</td><td class="n">100 %</td><td class="n">${dEur(totUnreal)}<br><small class="${cls(totUnreal)}">${pctS(totCost ? tot / totCost - 1 : 0)}</small></td><td></td></tr>
      </tbody></table>`;
    $$('#ov-positions tr[data-t]').forEach((tr) => tr.addEventListener('click', () => { state.pos = tr.dataset.t; location.hash = '#positions'; }));

    $('#ov-alloc').innerHTML = allocBlock(pos, tot);

    const showB = sc !== 'CRYPTO';
    $('#ov-per-sub').textContent = showB ? `vs ${D.meta.benchmark}` : '';
    $('#ov-periods').innerHTML = periodTable(per, showB, true);

    $('#ov-events').innerHTML = D.events.slice(0, 6).map((e) => `<li><span class="d">${dShort(e.date)}</span><span class="l">${esc(e.label)}<small>${esc(e.detail)}</small></span><span class="num">${e.amount != null ? eur(e.amount) : ''}</span></li>`).join('');

    renderReconMini();
    renderReserve();
    const topN = D.news.top && D.news.top.length ? D.news.top.concat((D.news.items || []).filter((n) => !D.news.top.find((t) => t.url === n.url)).slice(0, 3)) : (D.news.items || []).slice(0, 8);
    $('#ov-news').innerHTML = newsItems(topN) || '<div class="empty">Pas encore d\'actus : elles arrivent au prochain passage du robot.</div>';
  }

  function renderReserve() {
    const R = D.reserve;
    if (!R) { $('#ov-reserve').innerHTML = '<div class="empty">Réserve non configurée (Mes données › Paramètres).</div>'; return; }
    $('#ov-reserve-sub').textContent = `non investie · depuis le ${dShort(R.start_date)}`;
    const wk = Math.abs(R.week_change) > 0.004 ? `${dEur(R.week_change)} cette semaine · ` : '';
    $('#ov-reserve').innerHTML = `<div style="font-size:28px;font-weight:650;letter-spacing:-0.01em">${eur(R.balance)}</div>
      <div style="font-size:12px;color:var(--text-2);margin-top:2px">${wk}≈ +${eur(R.monthly_estimate)} / mois avec les reliquats des plans</div>
      <table class="t compact" style="margin-top:10px"><thead><tr><th>Achetable maintenant</th><th class="n">Parts</th><th class="n">Coût</th></tr></thead><tbody>
      ${R.buyable.map((b) => `<tr><td><div class="name"><span class="dot" style="background:${assetColor(b.ticker)}"></span>${esc(b.short)}</div></td><td class="n">${b.shares}</td>
        <td class="n">${b.shares ? eur(b.cost) : `<small style="color:var(--muted)">il manque ${eur(b.missing)}</small>`}</td></tr>`).join('')}</tbody></table>
      <table class="t compact" style="margin-top:6px"><thead><tr><th>Derniers mouvements</th><th class="n">Montant</th></tr></thead><tbody>
      ${R.moves.slice(0, 4).map((m) => `<tr><td style="white-space:normal">${dShort(m.date)} · ${esc(m.label)}</td><td class="n">${dEur(m.amount)}</td></tr>`).join('') ||
        `<tr><td colspan="2" style="white-space:normal;color:var(--muted)">Départ : ${eur(R.start_amount)} relevés dans TR le ${dShort(R.start_date)}. Les reliquats des prochains plans s'ajouteront ici.</td></tr>`}</tbody></table>
      <div class="actions" style="margin-top:8px"><a class="btn sm" href="#donnees/reserve">+ Ajouter / − retirer</a><a class="btn sm" href="#donnees/versement">Investir la réserve</a></div>
      <div class="note">Reliquats des plans et ventes du PEA s'ajoutent seuls ; les dividendes non (TR les réinvestit au plan suivant).</div>`;
  }

  function allocBlock(pos, tot) {
    const segs = pos.map((p) => { const w = tot ? p.value / tot : 0; return `<div style="flex:${w};background:${assetColor(p.ticker)};color:${(D.assets[p.ticker].slot === 4) ? '#0b0b0b' : '#fff'}" title="${esc(p.short)} ${pct(w, 1)}">${w > 0.09 ? pct(w, 0) : ''}</div>`; }).join('');
    const rows = pos.map((p) => `<tr><td><div class="name"><span class="dot" style="background:${assetColor(p.ticker)}"></span>${esc(p.short)}</div></td><td class="n">${eur(p.value)}</td><td class="n">${pct(tot ? p.value / tot : 0, 1)}</td></tr>`).join('');
    return `<div class="segbar" role="img" aria-label="Répartition par ligne">${segs}</div><table class="t compact"><tbody>${rows}</tbody></table>`;
  }

  function periodTable(rows, showBench, compact) {
    return `<table class="t ${compact ? 'compact' : ''}"><thead><tr><th>Période</th>${compact ? '' : '<th>Depuis le</th>'}<th class="n">Perf. (TWR)</th><th class="n">Gain €</th>${showBench ? `<th class="n">${esc(D.meta.benchmark)}</th><th class="n">Écart</th>` : ''}</tr></thead><tbody>
      ${rows.map((r) => `<tr><td>${r.key}${r.partial ? ' <small style="color:var(--muted)">(depuis l\'origine)</small>' : ''}</td>${compact ? '' : `<td>${dShort(r.start)}</td>`}<td class="n">${dPct(r.twr)}</td><td class="n">${dEur(r.pnl)}</td>
        ${showBench ? `<td class="n">${dPct(r.bench)}</td><td class="n">${dPct(isNum(r.bench) ? r.twr - r.bench : null)}</td>` : ''}</tr>`).join('')}</tbody></table>`;
  }

  function renderEvolution() {
    const sc = state.scope, S = D.series[sc];
    const { i0, dates } = scopeWindow(sc);
    const ds = dates.slice(i0);
    const span = spanDays(ds[0], ds[ds.length - 1]);
    const c = mk('ov-chart');
    if (!c) return;
    const ink = cv('--ink'), mut = cv('--muted');
    let series, yfmt, tfmt, leg;
    if (state.ovMode === 'value') {
      series = [
        line('Valeur', ds.map((d, i) => [d, S.value[i0 + i]]), ink, { areaStyle: wash(ink, 0.07) }),
        line('Capital investi net', ds.map((d, i) => [d, S.invested[i0 + i]]), mut, { step: 'end', lineStyle: { width: 1.5, color: mut } }),
      ];
      yfmt = axEur; tfmt = (v) => eur(v);
      leg = [{ label: 'Valeur', color: ink }, { label: 'Capital investi net', color: mut }];
    } else if (state.ovMode === 'pnl') {
      series = [line('Plus-value totale', ds.map((d, i) => [d, S.pnl[i0 + i]]), ink, { areaStyle: wash(ink, 0.07) })];
      yfmt = axEur; tfmt = (v) => eurS(v);
      leg = [];
    } else {
      const b0 = S.twr[i0];
      series = [line(`Mon ${sc === 'TOTAL' ? 'portefeuille' : sc}`, ds.map((d, i) => [d, S.twr[i0 + i] / b0 - 1]), ink)];
      leg = [{ label: `Mon ${sc === 'TOTAL' ? 'portefeuille' : sc}`, color: ink }];
      if (sc !== 'CRYPTO' && D.series.bench) {
        const bb = D.series.bench[i0];
        series.push(line(D.meta.benchmark, ds.map((d, i) => [d, D.series.bench[i0 + i] / bb - 1]), slot(1)));
        leg.push({ label: D.meta.benchmark, color: slot(1) });
      }
      yfmt = axPct; tfmt = (v) => pctS(v);
    }
    legend('ov-legend', leg);
    c.setOption(base({ xAxis: xTime(span), yAxis: yVal(yfmt, { scale: state.ovMode === 'value' ? false : true }), series, tooltip: Object.assign(base().tooltip, { formatter: tip(tfmt) }) }), true);
  }

  function renderReconMini() {
    const R = D.reconciliation;
    if (!R) { $('#ov-recon').innerHTML = '<div class="empty">Aucun relevé TR saisi.</div>'; return; }
    $('#ov-recon-sub').textContent = `relevé du ${dShort(R.date)}`;
    const rows = R.positions.map((p) => {
      const ok = p.checks.every((c) => c.ok);
      const q = p.checks.find((c) => c.label === 'Quantité');
      const pru = p.checks.find((c) => c.label === 'PRU' || c.label === 'Coût de revient' || c.label === 'Performance %');
      return `<tr><td><div class="name"><span class="check ${ok ? 'ok' : 'ko'}">${ok ? '✓' : '!'}</span>${esc(p.short)}</div></td>
        <td class="n">${q ? qty(q.tr) : '–'}</td><td class="n">${pru ? (pru.label === 'Performance %' ? nf(2).format(pru.tr) + ' %' : eur(pru.tr)) : '–'}</td><td class="n">${eur(p.value_tr)}</td></tr>`;
    }).join('');
    const acc = R.accounts.map((a) => `<tr class="total"><td>${a.scope === 'TOTAL' ? 'Total' : a.scope === 'CRYPTO' ? 'Crypto' : 'PEA'} (écran TR)</td><td></td><td></td><td class="n">${eur(a.value_tr)}</td></tr>`).join('');
    $('#ov-recon').innerHTML = `<table class="t compact"><thead><tr><th>Ligne</th><th class="n">Qté TR</th><th class="n">PRU · perf · coût</th><th class="n">Valeur TR</th></tr></thead><tbody>${rows}${acc}</tbody></table>
      <div class="note" style="padding:0 12px 10px">✓ = quantité, PRU et performance du registre identiques à TR. ${R.ok ? 'Tout concorde.' : '<b>Au moins un écart à vérifier.</b>'}</div>`;
  }

  // ------------------------------------------------------------ PERFORMANCE
  function kgrid(items) {
    return items.map((o) => `<div class="kpi"><div class="lbl"><span>${o.label}</span>${o.help ? help(o.help) : ''}</div><div class="val">${o.value}</div><div class="delta">${o.delta || '&nbsp;'}</div></div>`).join('');
  }
  function renderPerformance() {
    const sc = state.scope, k = D.kpi[sc], r = D.risk[sc];
    $('#perf-sub').textContent = `${SCOPE_LABEL[sc]} · depuis le ${dShort(k.start)} · cours au ${dShort(k.asof)}`;
    $('#perf-kpis').innerHTML = kgrid([
      { label: 'Valeur', help: 'valeur', value: eur(k.value) },
      { label: 'Capital investi net', help: 'investi', value: eur(k.invested), delta: `versé ${eur(k.cash_in, 0)}` },
      { label: 'Plus-value latente', help: 'latente', value: `<span class="${cls(k.unreal)}">${eurS(k.unreal)}</span>`, delta: pctS(k.unreal_pct) },
      { label: 'Plus-values réalisées', help: 'realise', value: `<span class="${cls(k.realized)}">${eurS(k.realized)}</span>` },
      { label: 'Dividendes encaissés', help: 'dividendes', value: eur(k.dividends) },
      { label: 'Gain total', help: 'gain-total', value: `<span class="${cls(k.pnl)}">${eurS(k.pnl)}</span>`, delta: `${pctS(k.roi)} du versé` },
      { label: 'TWR cumulée', help: 'twr', value: `<span class="${cls(k.twr)}">${pctS(k.twr)}</span>` },
      { label: 'TWR annualisée', help: 'twr', value: `<span class="${cls(k.twr_ann)}">${pctS(k.twr_ann)}</span>` },
      { label: 'TRI annualisé', help: 'tri', value: `<span class="${cls(k.xirr)}">${pctS(k.xirr)}</span>` },
      ...(sc !== 'CRYPTO' ? [{ label: `${D.meta.benchmark} (même période)`, help: 'benchmark', value: `<span class="${cls(r.bench_twr)}">${pctS(r.bench_twr)}</span>`, delta: `${pctS(r.bench_twr_ann)} / an` }] : []),
      { label: 'Taxes payées (TTF)', help: 'frais', value: eur(k.taxes) },
    ]);

    // cumulée vs indice vs livret
    const S = D.series[sc];
    const { i0, dates } = scopeWindow(sc);
    const ds = dates.slice(i0), span = spanDays(ds[0], ds[ds.length - 1]);
    const ink = cv('--ink'), mut = cv('--muted');
    const t0 = S.twr[i0];
    const ser = [line('Mon ' + (sc === 'TOTAL' ? 'portefeuille' : sc), ds.map((d, i) => [d, S.twr[i0 + i] / t0 - 1]), ink)];
    const leg = [{ label: 'Mon ' + (sc === 'TOTAL' ? 'portefeuille' : sc), color: ink }];
    if (sc !== 'CRYPTO' && D.series.bench) {
      const b0 = D.series.bench[i0];
      ser.push(line(D.meta.benchmark, ds.map((d, i) => [d, D.series.bench[i0 + i] / b0 - 1]), slot(1)));
      leg.push({ label: D.meta.benchmark, color: slot(1) });
    }
    ser.push(line(`${D.meta.rf_label} (${pct(D.meta.rf, 1)})`, ds.map((d) => [d, Math.pow(1 + D.meta.rf, spanDays(ds[0], d) / 365) - 1]), mut, { lineStyle: { width: 1.5, color: mut } }));
    leg.push({ label: `${D.meta.rf_label} (${pct(D.meta.rf, 1)})`, color: mut });
    legend('perf-legend', leg);
    const c = mk('perf-chart');
    if (c) c.setOption(base({ xAxis: xTime(span), yAxis: yVal(axPct, { scale: true }), series: ser, tooltip: Object.assign(base().tooltip, { formatter: tip((v) => pctS(v)) }) }), true);

    // contribution
    const pos = D.positions.filter((p) => sc === 'TOTAL' || p.account === sc).slice().sort((a, b) => b.pnl_total - a.pnl_total);
    const mx = Math.max(...pos.map((p) => Math.abs(p.pnl_total)), 1);
    $('#perf-contrib').innerHTML = pos.map((p) => {
      const w = Math.abs(p.pnl_total) / mx * 50;
      const col = p.pnl_total >= 0 ? `rgb(${cv('--div-pos')})` : `rgb(${cv('--div-neg')})`;
      return `<div class="hbar" style="grid-template-columns:minmax(90px,130px) 1fr 76px"><span>${esc(p.short)}${p.open ? '' : ' <small style="color:var(--muted)">(soldée)</small>'}</span>
        <div class="track"><div style="position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:var(--axis)"></div>
        <div class="fill" style="position:absolute;height:14px;${p.pnl_total >= 0 ? `left:50%;border-radius:0 4px 4px 0` : `right:50%;border-radius:4px 0 0 4px`};width:${w}%;background:${col}"></div></div>
        <span class="v ${cls(p.pnl_total)}">${eurS(p.pnl_total)}</span></div>`;
    }).join('') + `<div class="note">Gain total par ligne = valeur + ventes + dividendes − achats. Somme = ${eurS(D.kpi[sc].pnl)}.</div>`;

    // fantômes
    const G = D.ghosts[sc];
    if (G) {
      const gi0 = idxFrom(G.dates, ds[0]);
      const gds = G.dates.slice(gi0);
      const gser = [line('Mon portefeuille (dividendes inclus)', gds.map((d, i) => [d, G.wealth[gi0 + i]]), ink)];
      const gl = [{ label: 'Mon portefeuille', color: ink }];
      if (G.bench) { gser.push(line(`100 % ${D.meta.benchmark}`, gds.map((d, i) => [d, G.bench[gi0 + i]]), slot(1))); gl.push({ label: `100 % ${D.meta.benchmark}`, color: slot(1) }); }
      gser.push(line(`100 % ${D.meta.rf_label}`, gds.map((d, i) => [d, G.livret[gi0 + i]]), mut, { lineStyle: { width: 1.5, color: mut } }));
      gl.push({ label: `100 % ${D.meta.rf_label}`, color: mut });
      legend('ghost-legend', gl);
      const gc = mk('ghost-chart');
      if (gc) gc.setOption(base({ xAxis: xTime(spanDays(gds[0], gds[gds.length - 1])), yAxis: yVal(axEur, { scale: true }), series: gser, tooltip: Object.assign(base().tooltip, { formatter: tip((v) => eur(v)) }) }), true);
      const dB = G.wealth_final - (G.bench_final || 0), dL = G.wealth_final - G.livret_final;
      $('#ghost-note').innerHTML = `Aujourd'hui : <b>${eur(G.wealth_final)}</b> réels vs ${eur(G.bench_final)} en ${esc(D.meta.benchmark)} (<span class="${cls(dB)}">${eurS(dB)}</span>) et ${eur(G.livret_final)} sur ${esc(D.meta.rf_label)} (<span class="${cls(dL)}">${eurS(dL)}</span>).`;
    } else {
      legend('ghost-legend', []);
      const gc = mk('ghost-chart'); if (gc) gc.clear();
      $('#ghost-note').textContent = 'Non calculé pour la crypto seule : choisis Consolidé ou PEA.';
    }

    $('#perf-periods').innerHTML = periodTable(D.periods[sc], sc !== 'CRYPTO', false);
    renderMonthly(sc);
    renderFlows(sc);
  }

  function renderMonthly(sc) {
    const M = D.monthly[sc];
    const years = [...new Set(M.map((m) => m.month.slice(0, 4)))];
    const cap = Math.max(0.04, ...M.map((m) => Math.abs(m.ret)));
    const cell = (m) => {
      if (!m) return '<td class="n" style="color:var(--muted)">·</td>';
      const a = 0.08 + 0.55 * Math.min(Math.abs(m.ret) / cap, 1);
      const bg = `rgba(${m.ret >= 0 ? cv('--div-pos') : cv('--div-neg')},${a.toFixed(2)})`;
      return `<td class="n" style="background:${bg}" title="Versé ${eur(m.flows, 0)}">${pctS(m.ret, 1)}<br><small style="color:var(--text-2)">${eurS(m.pnl, 0)}</small></td>`;
    };
    $('#perf-monthly').innerHTML = `<table class="t heat"><thead><tr><th>Année</th>${MONTHS.map((m) => `<th class="n">${m}</th>`).join('')}<th class="n">Année</th></tr></thead><tbody>
      ${years.map((y) => {
        const ms = M.filter((m) => m.month.startsWith(y));
        const yr = ms.reduce((a, m) => a * (1 + m.ret), 1) - 1;
        const pnl = ms.reduce((a, m) => a + m.pnl, 0);
        return `<tr><td><b>${y}</b></td>${MONTHS.map((_, i) => cell(ms.find((m) => +m.month.slice(5, 7) === i + 1))).join('')}<td class="n"><b class="${cls(yr)}">${pctS(yr, 1)}</b><br><small>${eurS(pnl, 0)}</small></td></tr>`;
      }).join('')}</tbody></table>
      <div class="note" style="padding:0 12px 10px">Bleu = mois positif, rouge = négatif, intensité = ampleur. Ligne du haut : performance TWR du mois ; dessous : gain ou perte en euros.</div>`;
  }

  function renderFlows(sc) {
    const M = D.monthly[sc];
    const c = mk('flows-chart');
    if (!c) return;
    const cats = M.map((m) => { const [y, mm] = m.month.split('-'); return `${MONTHS[+mm - 1]} ${y.slice(2)}`; });
    legend('flows-legend', [{ label: 'Versé net', color: slot(1), sq: true }, { label: 'Gain / perte du mois', color: slot(3), sq: true }]);
    c.setOption(base({
      tooltip: Object.assign(base().tooltip, { axisPointer: { type: 'shadow', shadowStyle: { color: hexA('#888888', 0.08) } },
        formatter: (ps) => `<div style="font-weight:650;margin-bottom:4px">${ps[0].axisValue}</div>` + ps.map((p) => `<div style="display:flex;justify-content:space-between;gap:14px"><span>${p.marker}${p.seriesName}</span><b>${eurS(p.value)}</b></div>`).join('') }),
      xAxis: { type: 'category', data: cats, axisTick: { show: false }, axisLine: { lineStyle: { color: cv('--axis') } }, axisLabel: { color: cv('--muted'), fontSize: 11, hideOverlap: true } },
      yAxis: yVal(axEur),
      series: [
        { name: 'Versé net', type: 'bar', data: M.map((m) => m.flows), barMaxWidth: 18, barGap: '15%', itemStyle: { color: slot(1), borderRadius: [4, 4, 0, 0] } },
        { name: 'Gain / perte du mois', type: 'bar', data: M.map((m) => ({ value: m.pnl, itemStyle: { borderRadius: m.pnl >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4] } })), barMaxWidth: 18, itemStyle: { color: slot(3) } },
      ],
    }), true);
  }

  // ------------------------------------------------------------ RISQUE
  function renderRisk() {
    const sc = state.scope, r = D.risk[sc], k = D.kpi[sc];
    const yr = r.ann_factor === 365 ? '365 j' : '252 séances';
    $('#risk-sub').textContent = `${SCOPE_LABEL[sc]} · ${r.n_obs} observations journalières depuis le ${dShort(r.start)} · annualisation ${yr}`;
    const items = [
      { label: 'Volatilité annualisée', help: 'volatilite', value: pct(r.vol, 1) },
      { label: 'Max drawdown', help: 'drawdown', value: `<span class="down">${pctS(r.dd_mdd, 1)}</span>`, delta: r.dd_trough ? `${dShort(r.dd_peak)} → ${dShort(r.dd_trough)}` : '' },
      { label: 'Drawdown actuel', help: 'drawdown', value: `<span class="${r.dd_current < 0 ? 'down' : 'flat'}">${pctS(r.dd_current, 1)}</span>`, delta: r.dd_days_under ? `${r.dd_days_under} j sous le sommet` : 'au plus haut' },
      { label: 'Ratio de Sharpe', help: 'sharpe', value: num(r.sharpe), delta: `vs ${esc(D.meta.rf_label)} ${pct(D.meta.rf, 1)}` },
      { label: 'Ratio de Sortino', help: 'sortino', value: num(r.sortino) },
      { label: 'Ratio de Calmar', help: 'calmar', value: num(r.calmar) },
      { label: 'VaR 95 % (1 jour)', help: 'var', value: `<span class="down">−${eur(r.var95_eur)}</span>`, delta: `${pct(r.var95)} de la valeur` },
      { label: 'CVaR 95 % (1 jour)', help: 'var', value: `<span class="down">−${eur(r.cvar95_eur)}</span>`, delta: `${pct(r.cvar95)} en moyenne` },
      { label: 'Meilleure séance', help: 'distribution', value: dPct(r.best && r.best.v), delta: r.best ? dShort(r.best.d) : '' },
      { label: 'Pire séance', help: 'distribution', value: dPct(r.worst && r.worst.v), delta: r.worst ? dShort(r.worst.d) : '' },
      { label: 'Séances positives', help: 'distribution', value: pct(r.pct_up, 0) },
    ];
    if (sc !== 'CRYPTO') {
      items.push(
        { label: `Bêta vs ${D.meta.benchmark}`, help: 'beta', value: num(r.beta) },
        { label: 'Corrélation', help: 'beta', value: num(r.corr) },
        { label: 'Alpha de Jensen', help: 'alpha', value: dPct(r.alpha), delta: 'par an' },
        { label: 'Tracking error', help: 'tracking', value: pct(r.te, 1) },
        { label: "Ratio d'information", help: 'tracking', value: num(r.ir) },
      );
    }
    $('#risk-kpis').innerHTML = kgrid(items);

    const RS = D.risk_series[sc];
    const { dates } = scopeWindow(sc);
    const first = dayBefore(D.series[sc].start);
    const ws = windowStart(dates[dates.length - 1], first);
    const j0 = idxFrom(RS.dates, ws);
    const ds = RS.dates.slice(j0), span = spanDays(ds[0], ds[ds.length - 1]);
    const red = cv('--critical');
    const c = mk('dd-chart');
    if (c) c.setOption(base({ xAxis: xTime(span), yAxis: yVal(axPct, { max: 0 }),
      series: [line('Drawdown', ds.map((d, i) => [d, RS.dd[j0 + i]]), red, { areaStyle: wash(red, 0.12), lineStyle: { width: 1.5, color: red } })],
      tooltip: Object.assign(base().tooltip, { formatter: tip((v) => pctS(v)) }) }), true);
    const rv = mk('rvol-chart');
    if (rv) rv.setOption(base({ xAxis: xTime(span), yAxis: yVal(axPct),
      series: [line('Volatilité 21 séances', ds.map((d, i) => [d, RS.rvol[j0 + i]]), cv('--ink'))],
      tooltip: Object.assign(base().tooltip, { formatter: tip((v) => pct(v, 1)) }) }), true);
    const H = RS.hist;
    const hc = mk('hist-chart');
    if (hc && H) {
      const cats = H.counts.map((_, i) => H.edges[i]);
      hc.setOption(base({
        tooltip: Object.assign(base().tooltip, { axisPointer: { type: 'shadow', shadowStyle: { color: hexA('#888888', 0.08) } },
          formatter: (ps) => `${nf(1).format(H.edges[ps[0].dataIndex])} % à ${nf(1).format(H.edges[ps[0].dataIndex + 1])} % : <b>${ps[0].value} séance(s)</b>` }),
        xAxis: { type: 'category', data: cats.map((e) => nf(1).format(e)), axisTick: { show: false }, axisLine: { lineStyle: { color: cv('--axis') } }, axisLabel: { color: cv('--muted'), fontSize: 10, hideOverlap: true, formatter: (v) => v + ' %' } },
        yAxis: yVal((v) => v),
        series: [{ type: 'bar', name: 'Séances', barCategoryGap: '8%', data: H.counts.map((n, i) => ({ value: n, itemStyle: { color: H.edges[i] + 0.25 < 0 ? `rgb(${cv('--div-neg')})` : `rgb(${cv('--div-pos')})`, borderRadius: [3, 3, 0, 0] } })) }],
      }), true);
    }
  }

  // ------------------------------------------------------------ POSITIONS
  function renderPositions() {
    const pos = D.positions;
    if (!state.pos || !pos.find((p) => p.ticker === state.pos)) state.pos = pos[0].ticker;
    const tot = D.kpi.TOTAL.value;
    $('#pos-table').innerHTML = `<table class="t"><thead><tr><th>Ligne</th><th>Compte</th><th class="n">Quantité</th><th class="n">PRU</th><th class="n">Cours</th><th class="n">Valeur</th><th class="n">Poids</th>
      <th class="n">+/- latente</th><th class="n">%</th><th class="n">1 jour</th><th class="n">1 sem.</th><th class="n">Réalisé</th><th class="n">Dividendes</th><th class="n">Gain total</th><th class="n">Frais/an</th></tr></thead><tbody>
      ${pos.map((p) => `<tr data-t="${esc(p.ticker)}" class="${p.open ? '' : 'closed'} ${p.ticker === state.pos ? 'sel' : ''}" style="cursor:pointer">
        <td><div class="name"><span class="dot" style="background:${assetColor(p.ticker)}"></span><div>${esc(p.short)}${p.open ? '' : ' (soldée)'}<small>${esc(p.isin || p.ticker)}</small></div></div></td>
        <td>${esc(p.account)}</td><td class="n">${p.open ? qty(p.qty) : '–'}</td><td class="n">${p.open ? eur(p.pru) : '–'}</td>
        <td class="n">${eur(p.price, p.price < 10 ? 3 : 2)}</td><td class="n">${p.open ? eur(p.value) : '–'}</td><td class="n">${p.open ? pct(p.value / tot, 1) : '–'}</td>
        <td class="n">${p.open ? dEur(p.unreal) : '–'}</td><td class="n">${p.open ? dPct(p.unreal_pct) : '–'}</td>
        <td class="n">${dPct(p.day_pct)}</td><td class="n">${dPct(p.week_pct)}</td><td class="n">${p.realized ? dEur(p.realized) : '–'}</td>
        <td class="n">${p.dividends ? eur(p.dividends) : '–'}</td><td class="n">${dEur(p.pnl_total)}</td><td class="n">${p.fee_year ? eur(p.fee_year) : '–'}</td></tr>`).join('')}
      </tbody></table>`;
    $$('#pos-table tr[data-t]').forEach((tr) => tr.addEventListener('click', () => { state.pos = tr.dataset.t; renderPositions(); }));
    renderPositionChart(state.pos);
  }

  function aggregate(dates, ohlc, step) {
    if (step === 'D') return { dates, ohlc };
    const out = { dates: [], ohlc: [] };
    const key = (d) => (step === 'M' ? d.slice(0, 7) : (() => { const x = parseISO(d); const day = (x.getDay() + 6) % 7; x.setDate(x.getDate() - day); return iso(x); })());
    let cur = null, k0 = null;
    dates.forEach((d, i) => {
      const [o, c, l, h] = ohlc[i]; const k = key(d);
      if (k !== k0) { if (cur) { out.dates.push(cur.d); out.ohlc.push([cur.o, cur.c, cur.l, cur.h]); } cur = { d, o, c, l, h }; k0 = k; }
      else { cur.c = c; cur.l = Math.min(cur.l, l); cur.h = Math.max(cur.h, h); cur.d = d; }
    });
    if (cur) { out.dates.push(cur.d); out.ohlc.push([cur.o, cur.c, cur.l, cur.h]); }
    return out;
  }
  function renderTradingView(t) {
    const S = D.position_series[t];
    const box = $('#pos-tv');
    const dark = document.documentElement.getAttribute('data-theme') === 'dark' || (!document.documentElement.getAttribute('data-theme') && matchMedia('(prefers-color-scheme: dark)').matches);
    const sym = (S && S.tv) || t;
    const key = sym + (dark ? 'd' : 'l');
    if (box.dataset.k === key) return;
    box.dataset.k = key;
    box.innerHTML = '<div class="tradingview-widget-container" style="height:100%;width:100%"><div class="tradingview-widget-container__widget" style="height:100%;width:100%"></div></div>';
    const s = document.createElement('script');
    s.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    s.async = true;
    s.text = JSON.stringify({ symbol: sym, interval: { D: 'D', W: 'W', M: 'M' }[state.posInt] || 'D', timezone: 'Europe/Paris', theme: dark ? 'dark' : 'light', style: '1', locale: 'fr',
      width: '100%', height: 460, allow_symbol_change: true, withdateranges: true, hide_side_toolbar: false, details: false, calendar: false, support_host: 'https://www.tradingview.com' });
    box.firstElementChild.appendChild(s);
    $('#pos-note').innerHTML = `Graphique TradingView en direct (cotation différée de 15 min) : ${esc(sym)}. <a href="https://www.tradingview.com/chart/?symbol=${encodeURIComponent(sym)}" target="_blank" rel="noopener">Ouvrir dans TradingView</a>. Ton PRU et tes achats sont dans les vues Courbe et Chandeliers.`;
  }

  function renderPositionChart(t) {
    const p = D.positions.find((x) => x.ticker === t);
    const S = D.position_series[t];
    $$('#pos-mode button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.m === state.posMode)));
    $$('#pos-int button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.i === state.posInt)));
    $('#pos-int').style.display = state.posMode === 'line' ? 'none' : '';
    $('#pos-tv').style.display = state.posMode === 'tv' ? '' : 'none';
    $('#pos-chart').style.display = state.posMode === 'tv' ? 'none' : '';
    $('#pos-legend').style.display = state.posMode === 'tv' ? 'none' : '';
    $('#pos-note').innerHTML = '';
    $('#pos-title').textContent = `${p.short} : cours et PRU`;
    const lg = D.transactions.filter((x) => x.ticker === t);
    $('#pos-detail').innerHTML = `<table class="t compact"><tbody>
      ${[
        ['Nom', esc(p.name)], ['ISIN / ticker', esc(p.isin || '–') + ' · ' + esc(p.ticker)], ['Nom chez TR', esc(p.tr_name)], ['Compte', esc(p.account)], ['Classe', esc(p.asset_class)],
        ['Première opération', dShort(p.first_date)], ['Quantité', p.open ? qty(p.qty) : 'soldée'], ['PRU (méthode TR)', p.open ? eur(p.pru, 4) : '–'],
        ['Cours', `${eur(p.price, 4)} <small style="color:var(--muted)">(${dShort(p.price_date)})</small>`], ['Valeur', eur(p.value)],
        ['Coût de revient', eur(p.cost)], ['Plus-value latente', p.open ? `${dEur(p.unreal)} (${pctS(p.unreal_pct)})` : '–'],
        ['Plus-value réalisée', dEur(p.realized)], ['Dividendes', eur(p.dividends)], ['TTF payée', eur(p.taxes)],
        ['Gain total', dEur(p.pnl_total)], ['Frais courants (TER)', p.ter ? `${nf(2).format(p.ter)} % · ≈ ${eur(p.fee_year)} / an` : '–'], ['Opérations', String(lg.length)],
      ].map(([a, b]) => `<tr><td style="color:var(--muted)">${a}</td><td class="n" style="white-space:normal">${b}</td></tr>`).join('')}</tbody></table>`;
    if (state.posMode === 'tv') { renderTradingView(t); return; }
    const c = mk('pos-chart');
    if (!c || !S) return;
    if (state.posMode === 'candle' && S.ohlc) { renderCandles(c, p, S); return; }
    let i0 = 0;
    if (state.period !== 'MAX') i0 = idxFrom(S.dates, windowStart(S.dates[S.dates.length - 1], S.dates[0]));
    const ds = S.dates.slice(i0);
    const ink = cv('--ink');
    const buys = S.marks.filter((m) => (m.type === 'BUY' || m.type === 'TRANSFER_IN') && m.date >= ds[0]);
    const sells = S.marks.filter((m) => (m.type === 'SELL' || m.type === 'TRANSFER_OUT') && m.date >= ds[0]);
    const ser = [
      line('Cours', ds.map((d, i) => [d, S.price[i0 + i]]), ink),
      line('PRU', ds.map((d, i) => [d, S.pru[i0 + i]]), slot(2), { step: 'end', lineStyle: { width: 2, color: slot(2) }, connectNulls: false }),
      { name: 'Achats', type: 'scatter', symbolSize: 9, data: buys.map((m) => [m.date, m.price, m]), itemStyle: { color: slot(1), borderColor: cv('--surface'), borderWidth: 2 }, z: 5 },
    ];
    const leg = [{ label: 'Cours', color: ink }, { label: 'PRU', color: slot(2) }, { label: 'Achats', color: slot(1), sq: true }];
    if (sells.length) {
      ser.push({ name: 'Ventes', type: 'scatter', symbolSize: 9, data: sells.map((m) => [m.date, m.price, m]), itemStyle: { color: slot(8), borderColor: cv('--surface'), borderWidth: 2 }, z: 5 });
      leg.push({ label: 'Ventes', color: slot(8), sq: true });
    }
    legend('pos-legend', leg);
    const dec = p.price < 10 ? 3 : 2;
    c.setOption(base({
      xAxis: xTime(spanDays(ds[0], ds[ds.length - 1])), yAxis: yVal((v) => nf(dec > 2 ? 2 : 0).format(v) + ' €', { scale: true }), series: ser,
      tooltip: Object.assign(base().tooltip, { formatter: (ps) => {
        ps = Array.isArray(ps) ? ps : [ps];
        const d = new Date(ps[0].axisValue != null ? ps[0].axisValue : ps[0].value[0]);
        let h = `<div style="font-weight:650;margin-bottom:4px">${dLong(d)}</div>`;
        ps.forEach((x) => {
          if (x.seriesType === 'scatter') { const m = x.value[2]; h += `<div>${x.marker}${x.seriesName} : ${qty(m.qty)} à ${eur(m.price, dec)} = ${eur(m.amount)}${m.source !== 'TR' ? ' (' + m.source + ')' : ''}</div>`; }
          else if (x.value[1] != null) h += `<div style="display:flex;justify-content:space-between;gap:14px"><span>${x.marker}${x.seriesName}</span><b>${eur(x.value[1], dec)}</b></div>`;
        });
        return h;
      } }),
    }), true);
  }

  function renderCandles(c, p, S) {
    let i0 = 0;
    if (state.period !== 'MAX') i0 = idxFrom(S.dates, windowStart(S.dates[S.dates.length - 1], S.dates[0]));
    const agg = aggregate(S.dates.slice(i0), S.ohlc.slice(i0), state.posInt);
    const pruAt = (d) => { const j = S.dates.indexOf(d); return j >= 0 ? S.pru[j] : null; };
    const up = cv('--good'), down = cv('--critical');
    const dec = p.price < 10 ? 3 : 2;
    const buys = S.marks.filter((m) => (m.type === 'BUY' || m.type === 'TRANSFER_IN') && m.date >= agg.dates[0]);
    legend('pos-legend', [{ label: 'Hausse (creux)', color: up, sq: true }, { label: 'Baisse (plein)', color: down, sq: true }, { label: 'PRU', color: slot(2) }, { label: 'Achats', color: slot(1), sq: true }]);
    c.setOption({
      animation: false,
      textStyle: { fontFamily: cv('--font') || 'system-ui', color: cv('--text-2') },
      grid: { left: 8, right: 14, top: 12, bottom: 56, containLabel: true },
      tooltip: { trigger: 'axis', confine: true, axisPointer: { type: 'cross', lineStyle: { color: cv('--muted') } }, backgroundColor: cv('--surface'), borderColor: cv('--border-strong'),
        textStyle: { color: cv('--text'), fontSize: 12 },
        formatter: (ps) => {
          const k = ps.find((x) => x.seriesType === 'candlestick'); if (!k) return '';
          const [o, cl, l, h] = agg.ohlc[k.dataIndex]; const d = agg.dates[k.dataIndex];
          const var_ = cl / o - 1;
          let s = `<b>${state.posInt === 'D' ? dLong(d) : (state.posInt === 'W' ? 'Semaine du ' : '') + dLong(d)}</b><br>Ouverture ${eur(o, dec)} · Clôture ${eur(cl, dec)} <span class="${cls(var_)}">${pctS(var_)}</span><br>Plus haut ${eur(h, dec)} · Plus bas ${eur(l, dec)}`;
          const pr = ps.find((x) => x.seriesName === 'PRU'); if (pr && pr.value != null) s += `<br>PRU ${eur(pr.value, dec)}`;
          return s;
        } },
      xAxis: { type: 'category', data: agg.dates, boundaryGap: true, axisTick: { show: false }, axisLine: { lineStyle: { color: cv('--axis') } },
        axisLabel: { color: cv('--muted'), fontSize: 11, hideOverlap: true, formatter: (v) => { const d = parseISO(v); return `${d.getDate()} ${MONTHS[d.getMonth()]}${state.posInt === 'M' || agg.dates.length > 200 ? ' ' + String(d.getFullYear()).slice(2) : ''}`; } } },
      yAxis: yVal((v) => nf(dec > 2 ? 2 : 0).format(v) + '\u00a0€', { scale: true }),
      dataZoom: [{ type: 'inside', start: agg.dates.length > 120 ? 100 - 12000 / agg.dates.length : 0, end: 100 },
        { type: 'slider', height: 22, bottom: 8, borderColor: cv('--border'), fillerColor: hexA('#2a78d6', 0.12), textStyle: { color: cv('--muted') }, dataBackground: { lineStyle: { color: cv('--muted') }, areaStyle: { color: cv('--surface-3') } } }],
      series: [
        { name: p.short, type: 'candlestick', data: agg.ohlc, barMaxWidth: 12,
          itemStyle: { color: cv('--surface'), color0: down, borderColor: up, borderColor0: down, borderWidth: 1.2 } },
        { name: 'PRU', type: 'line', step: 'end', showSymbol: false, data: agg.dates.map(pruAt), lineStyle: { width: 2, color: slot(2) }, itemStyle: { color: slot(2) }, connectNulls: false, z: 3 },
        { name: 'Achats', type: 'scatter', symbolSize: 9, z: 4, itemStyle: { color: slot(1), borderColor: cv('--surface'), borderWidth: 2 },
          data: buys.map((m) => { const j = agg.dates.findIndex((d) => d >= m.date); return j >= 0 ? [j, m.price] : null; }).filter(Boolean) },
      ],
    }, true);
    $('#pos-note').innerHTML = `Bougies ${state.posInt === 'D' ? 'journalières' : state.posInt === 'W' ? 'hebdomadaires' : 'mensuelles'} Euronext (ou ETH-EUR) : corps creux = hausse, plein = baisse. Molette ou curseur pour zoomer.`;
  }

  // ------------------------------------------------------------ ALLOCATION
  function hbars(items, color, total) {
    const mx = Math.max(...items.map((i) => i.weight), 0.0001);
    return items.map((i) => `<div class="hbar"><span>${esc(i.label)}</span><div class="track"><div class="fill" style="width:${(i.weight / mx * 100).toFixed(1)}%;background:${color}"></div></div><span class="v">${pct(i.weight, 1)}</span></div>`).join('') +
      (total ? `<div class="note">Total ${eur(total)}</div>` : '');
  }
  function renderAllocation() {
    const A = D.allocation;
    const sc = (A.scoped && A.scoped[state.scope]) ? state.scope : 'TOTAL';
    const Z = (A.scoped && A.scoped[sc]) || { total: A.total, classes: A.by_class, zones: A.by_zone, sectors: A.total_sectors || [], countries: A.pea_countries || [] };
    const pos = D.positions.filter((p) => p.open && (sc === 'TOTAL' || p.account === sc));
    const tot = Z.total;
    $$('.al-scope').forEach((x) => { x.textContent = { TOTAL: 'consolidé (PEA + crypto)', PEA: 'PEA', CRYPTO: 'crypto' }[sc]; });
    $('#al-lines').innerHTML = `<div class="segbar">${pos.map((p) => { const w = p.value / tot; return `<div style="flex:${w};background:${assetColor(p.ticker)};color:${D.assets[p.ticker].slot === 4 ? '#0b0b0b' : '#fff'}" title="${esc(p.short)} ${pct(w, 1)}">${w > 0.09 ? pct(w, 0) : ''}</div>`; }).join('')}</div>
      <table class="t compact"><thead><tr><th>Ligne</th><th class="n">Valeur</th><th class="n">Poids total</th><th class="n">Poids dans son compte</th></tr></thead><tbody>
      ${pos.map((p) => `<tr><td><div class="name"><span class="dot" style="background:${assetColor(p.ticker)}"></span>${esc(p.short)}</div></td><td class="n">${eur(p.value)}</td><td class="n">${pct(p.weight_total, 1)}</td><td class="n">${pct(p.weight_account, 1)} <small style="color:var(--muted)">${esc(p.account)}</small></td></tr>`).join('')}
      </tbody></table>
      <div class="note">Concentration : nombre effectif de lignes <b>${num(A.concentration.total.n_eff, 1)}</b> (consolidé), <b>${num(A.concentration.pea.n_eff, 1)}</b> (PEA). <a href="aide.html#concentration">C'est quoi ?</a></div>`;
    $('#al-class').innerHTML = hbars(Z.classes, slot(1), tot);
    const stocks = pos.filter((p) => p.kind === 'Action').map((p) => p.short);
    const sNote = stocks.length ? `${stocks.length > 1 ? stocks.slice(0, -1).join(', ') + ' et ' + stocks[stocks.length - 1] + ' sont comptées dans le pays de leur siège' : stocks[0] + ' est comptée dans le pays de son siège'}, même si l'activité est mondiale.` : '';
    $('#al-zones').innerHTML = hbars(Z.zones, slot(1)) + (sNote ? `<div class="note">${esc(sNote)}</div>` : '');
    $('#al-sectors').innerHTML = hbars(Z.sectors, slot(1)) + `<div class="note">${sourcesNote(A, sc)}</div>`;
    $('#al-countries').innerHTML = Z.countries.length ? hbars(Z.countries.slice(0, 12), slot(1)) : '<div class="empty">La crypto n\'a pas de pays.</div>';
    renderMap(Z, tot);
    $('#al-plan').innerHTML = `<div class="legend"><span><i class="sq" style="background:${slot(1)}"></i>Réel (valeur)</span><span><i class="sq" style="background:${cv('--muted')}"></i>Part des versements du plan</span></div>` +
      A.vs_plan.map((r) => `<div style="padding:6px 0;border-bottom:1px solid var(--border)"><div style="display:flex;justify-content:space-between;font-size:12px"><span>${esc(r.short)}</span><span class="num">${pct(r.actual, 1)} <span style="color:var(--muted)">/ ${pct(r.plan, 1)}</span></span></div>
        <div class="segbar thin" style="margin:4px 0 2px"><div style="flex:${r.actual};background:${slot(1)}"></div><div style="flex:${Math.max(1 - r.actual, 0)};background:var(--surface-3)"></div></div>
        <div class="segbar thin" style="margin:2px 0"><div style="flex:${r.plan};background:${cv('--muted')}"></div><div style="flex:${Math.max(1 - r.plan, 0)};background:var(--surface-3)"></div></div></div>`).join('') +
      `<div class="note">Les lignes sans plan (actions) ne reçoivent plus d'argent : leur poids baisse mécaniquement à chaque versement.</div>`;
    $('#al-plans').innerHTML = `<table class="t"><thead><tr><th>Plan</th><th class="n">Montant</th><th>Prochaine exécution</th><th class="n">Cours actuel</th><th class="n">Parts achetées (est.)</th><th class="n">Investi (est.)</th><th class="n">Non investi</th><th>Montant conseillé</th></tr></thead><tbody>
      ${D.plans.filter((p) => p.active).map((p) => `<tr><td><div class="name"><span class="dot" style="background:${assetColor(p.ticker)}"></span><div>${esc(p.short)}<small>${esc(p.freq)}</small></div></div></td><td class="n">${eur(p.amount, 0)}</td><td>${p.next ? `${dShort(p.next)} <small style="color:var(--muted)">J−${p.days_to}</small>` : '–'}</td>
        <td class="n">${eur(p.price, p.price < 10 ? 3 : 2)}</td><td class="n">${p.shares != null ? p.shares : 'fractionné'}</td><td class="n">${eur(p.invested)}</td>
        <td class="n">${p.residual > 0.005 ? `<span class="${p.residual_pct >= 0.1 ? 'down' : 'flat'}">${eur(p.residual)} (${pct(p.residual_pct, 1)})</span>` : '–'}</td>
        <td>${p.suggest && p.residual_pct >= 0.05 ? p.suggest.map((s) => `${s.amount} € → ${s.shares} part${s.shares > 1 ? 's' : ''}`).join(' · ') : '<span style="color:var(--muted)">OK</span>'}</td></tr>`).join('')}
      <tr class="total"><td>Total par mois</td><td class="n">${eur(D.plans.reduce((a, p) => a + p.monthly, 0), 0)}</td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
      </tbody></table>`;
  }

  function sourcesNote(A, sc) {
    return 'Sources : ' + (A.expo_sources || []).filter((x) => x.ticker && D.assets[x.ticker] && (sc === 'TOTAL' || D.assets[x.ticker].account === sc))
      .map((x) => `${esc(x.short)} : ${x.url && /justETF/.test(x.source) ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.source)}</a>` : esc(x.source)}`).join(' · ') +
      '. justETF publie les 4 premiers pays et secteurs ; le reste suit la répartition indicative de l\'indice.';
  }
  // noms des pays (français, comme justETF) -> noms du fond de carte
  const MAP_NAMES = { 'États-Unis': 'United States', 'Japon': 'Japan', 'Grande-Bretagne': 'United Kingdom', 'Canada': 'Canada', 'France': 'France', 'Suisse': 'Switzerland',
    'Allemagne': 'Germany', 'Australie': 'Australia', 'Pays-Bas': 'Netherlands', 'Danemark': 'Denmark', 'Suède': 'Sweden', 'Italie': 'Italy', 'Espagne': 'Spain',
    'Finlande': 'Finland', 'Belgique': 'Belgium', 'Israël': 'Israel', 'Norvège': 'Norway', 'Irlande': 'Ireland', 'Nouvelle-Zélande': 'New Zealand', 'Autriche': 'Austria',
    'Portugal': 'Portugal', 'Chine': 'China', 'Taïwan': 'Taiwan', 'Inde': 'India', 'Corée du Sud': 'Korea', 'Indonésie': 'Indonesia', 'Malaisie': 'Malaysia',
    'Thaïlande': 'Thailand', 'Philippines': 'Philippines', 'Brésil': 'Brazil', 'Mexique': 'Mexico', 'Afrique du Sud': 'South Africa', 'Arabie saoudite': 'Saudi Arabia',
    'Pologne': 'Poland', 'Luxembourg': 'Luxembourg', 'Turquie': 'Turkey', 'Chili': 'Chile', 'Grèce': 'Greece', 'Vietnam': 'Vietnam' };
  let worldLoading = null;
  function loadWorld() {
    if (window.echarts && echarts.getMap && echarts.getMap('world')) return Promise.resolve(true);
    if (!worldLoading) worldLoading = fetch('https://cdn.jsdelivr.net/npm/echarts@4.9.0/map/json/world.json').then((r) => r.json()).then((j) => { echarts.registerMap('world', j); return true; }).catch(() => false);
    return worldLoading;
  }
  function renderMap(Z, tot) {
    const list = Z.countries || [];
    const note = $('#al-map-note');
    const off = list.filter((x) => !MAP_NAMES[x.label]);
    const mapped = list.reduce((a, x) => a + x.value, 0);
    const outside = tot - mapped;
    note.innerHTML = [off.length ? `Hors carte (petits territoires) : ${off.map((x) => `${esc(x.label)} ${pct(x.weight, 1)}`).join(', ')}.` : '',
      outside > 0.5 ? `Sans pays (crypto) : ${pct(outside / tot, 1)} (${eur(outside, 0)}).` : ''].filter(Boolean).join(' ');
    loadWorld().then((ok) => {
      const c = mk('al-map');
      if (!c) return;
      if (!ok) { c.clear(); note.innerHTML = 'Fond de carte indisponible (hors connexion) : voir « Pays du PEA ».'; return; }
      const data = list.filter((x) => MAP_NAMES[x.label]).map((x) => ({ name: MAP_NAMES[x.label], value: +(x.weight * 100).toFixed(2), fr: x.label, eur: x.value }));
      const max = Math.max(...data.map((d) => d.value), 1);
      const dark = document.documentElement.getAttribute('data-theme') === 'dark' || (!document.documentElement.getAttribute('data-theme') && matchMedia('(prefers-color-scheme: dark)').matches);
      c.setOption({
        animation: false,
        tooltip: { trigger: 'item', backgroundColor: cv('--surface'), borderColor: cv('--border-strong'), textStyle: { color: cv('--text'), fontSize: 12 },
          formatter: (p) => (p.data ? `<b>${esc(p.data.fr)}</b><br>${nf(1).format(p.data.value)} % · ${eur(p.data.eur, 0)}` : `${esc(p.name)} : 0 %`) },
        visualMap: { type: 'continuous', min: 0, max: Math.ceil(max), left: 8, bottom: 8, itemHeight: 110, calculable: false, text: [`${Math.ceil(max)} %`, '0 %'],
          textStyle: { color: cv('--muted'), fontSize: 11 }, inRange: { color: dark ? ['#184f95', '#3987e5', '#9ec5f4'] : ['#cde2fb', '#5598e7', '#104281'] } },
        series: [{ type: 'map', map: 'world', roam: true, scaleLimit: { min: 1, max: 8 }, zoom: 1.15, center: [15, 25],
          itemStyle: { areaColor: cv('--surface-3'), borderColor: cv('--surface'), borderWidth: 0.6 },
          emphasis: { label: { show: false }, itemStyle: { areaColor: cv('--s2') } }, select: { disabled: true }, data }],
      }, true);
    });
  }

  // ------------------------------------------------------------ CRYPTO
  function renderCrypto() {
    if (!D.kpi.CRYPTO) { $('#cr-kpis').innerHTML = '<div class="empty">Pas de crypto.</div>'; return; }
    const k = D.kpi.CRYPTO, r = D.risk.CRYPTO;
    const eth = D.positions.find((p) => p.account === 'CRYPTO' && p.open) || D.positions.find((p) => p.account === 'CRYPTO');
    const stak = D.transactions.filter((t) => t.ticker === eth.ticker && t.type === 'STAKING').reduce((a, t) => a + t.quantity, 0);
    const sk = (D.staking || []).find((x) => x.ticker === eth.ticker);
    $('#cr-sub').textContent = `${eth.name} · depuis le ${dShort(k.start)} · cours au ${dShort(eth.price_date)}`;
    $('#cr-kpis').innerHTML = kgrid([
      { label: 'Valeur', help: 'valeur', value: eur(k.value) },
      { label: 'Quantité', value: qty(eth.qty) + ' ETH', delta: `dont staking ${qty(stak)}` },
      { label: 'PRU', help: 'latente', value: eur(eth.pru) },
      { label: 'Coût de revient', value: eur(k.cost) },
      { label: 'Plus-value', help: 'latente', value: `<span class="${cls(k.unreal)}">${eurS(k.unreal)}</span>`, delta: pctS(k.unreal_pct) },
      { label: 'TRI annualisé', help: 'tri', value: dPct(k.xirr) },
      { label: 'Volatilité', help: 'volatilite', value: pct(r.vol, 0), delta: 'annualisée (365 j)' },
      { label: 'Max drawdown', help: 'drawdown', value: `<span class="down">${pctS(r.dd_mdd, 1)}</span>` },
      { label: 'Staking', help: 'staking', value: eur(stak * eth.price), delta: sk ? `${pct(sk.rate)} / an, ajouté chaque mois` : 'récompenses cumulées' },
      { label: 'Plan', value: eur(D.plans.filter((p) => p.ticker === eth.ticker && p.active).reduce((a, p) => a + p.monthly, 0), 0) + ' / mois' },
    ]);
    const S = D.series.CRYPTO;
    const { i0, dates } = scopeWindow('CRYPTO');
    const ds = dates.slice(i0), span = spanDays(ds[0], ds[ds.length - 1]);
    const ink = cv('--ink'), mut = cv('--muted');
    legend('cr-legend', [{ label: 'Valeur', color: ink }, { label: 'Coût de revient', color: mut }]);
    const c = mk('cr-chart');
    if (c) c.setOption(base({ xAxis: xTime(span), yAxis: yVal(axEur), tooltip: Object.assign(base().tooltip, { formatter: tip((v) => eur(v)) }),
      series: [line('Valeur', ds.map((d, i) => [d, S.value[i0 + i]]), ink, { areaStyle: wash(ink, 0.07) }), line('Coût de revient', ds.map((d, i) => [d, S.cost[i0 + i]]), mut, { step: 'end', lineStyle: { width: 1.5, color: mut } })] }), true);
    // cours vs PRU : réutilise le graphique de position
    const P = D.position_series[eth.ticker];
    let j0 = state.period === 'MAX' ? 0 : idxFrom(P.dates, windowStart(P.dates[P.dates.length - 1], P.dates[0]));
    const pds = P.dates.slice(j0);
    legend('cr-legend2', [{ label: 'Cours ETH', color: ink }, { label: 'PRU', color: slot(2) }, { label: 'Achats / transferts', color: slot(1), sq: true }]);
    const c2 = mk('cr-chart2');
    if (c2) c2.setOption(base({ xAxis: xTime(spanDays(pds[0], pds[pds.length - 1])), yAxis: yVal(axEur, { scale: true }), tooltip: Object.assign(base().tooltip, { formatter: tip((v) => eur(v)) }),
      series: [line('Cours ETH', pds.map((d, i) => [d, P.price[j0 + i]]), ink), line('PRU', pds.map((d, i) => [d, P.pru[j0 + i]]), slot(2), { step: 'end' }),
        { name: 'Achats', type: 'scatter', symbolSize: 9, data: P.marks.filter((m) => m.date >= pds[0]).map((m) => [m.date, m.price]), itemStyle: { color: slot(1), borderColor: cv('--surface'), borderWidth: 2 }, tooltip: { show: false } }] }), true);
  }

  // ------------------------------------------------------------ PROJECTION & FISCALITÉ
  const SIM_KEY = 'pea-sim-v2';
  const MC_N = 5000;
  // Courbes de scénarios = centiles des 5 000 chemins (plus parlant qu'un taux fixe : la volatilité est incluse)
  const SCEN = [
    { k: 'p90', q: 0.9, label: 'Optimiste', hint: '1 chance sur 10 de faire mieux', color: () => cv('--up'), dash: 'dashed' },
    { k: 'p50', q: 0.5, label: 'Classique', hint: '1 chance sur 2 : la valeur probable', color: () => cv('--ink'), dash: 'solid' },
    { k: 'p25', q: 0.25, label: 'Réservé', hint: '1 chance sur 4 de faire moins bien', color: () => cv('--warn-text'), dash: 'dashed' },
    { k: 'p10', q: 0.1, label: 'Mauvais', hint: '1 chance sur 10 de faire moins bien', color: () => cv('--down'), dash: 'dashed' },
  ];
  const MONTHS_LONG = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
  function simDefaults() {
    const S = D.sim;
    return {
      scope: 'PEA', years: S.years, infl: S.inflation, ps: S.ps_rate, ir: S.ir_rate,
      exc: 0, excMonth: 12, idx: 0, reinvest: true, unit: 'nom',
      lines: S.lines.map((l) => ({ ticker: l.ticker, short: l.short, account: l.account, value: Math.round(l.value * 100) / 100,
        monthly: Math.round(l.monthly * 100) / 100, ret: l.ret, vol: l.vol, yld: Math.round((l.yld || 0) * 10000) / 10000, hist: l.hist_vol, on: true,
        price: l.account === 'PEA' && l.price ? Math.round(l.price * 1000) / 1000 : 0 })),
    };
  }
  let sim = null;
  function loadSim() {
    const def = simDefaults();
    let saved = null;
    try { saved = JSON.parse(store.get(SIM_KEY, 'null')); } catch (e) { saved = null; }
    if (!saved || !Array.isArray(saved.lines)) return def;
    const lines = def.lines.map((l) => { const o = saved.lines.find((x) => x.ticker === l.ticker); return o ? Object.assign({}, o, { value: l.value, hist: l.hist, short: l.short, price: l.price }) : l; });
    saved.lines.filter((x) => x.custom).forEach((x) => lines.push(x));
    return Object.assign({}, def, saved, { lines });
  }
  function saveSim() { store.set(SIM_KEY, JSON.stringify(sim)); }
  function rng(seed) { // mulberry32 : mêmes tirages d'un calcul à l'autre, la fourchette ne « tremble » pas
    let a = seed >>> 0;
    return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }
  function makeGauss(r) {
    let spare = null;
    return () => {
      if (spare !== null) { const s = spare; spare = null; return s; }
      let u = 0; while (u === 0) u = r();
      const v = r(), m = Math.sqrt(-2 * Math.log(u));
      spare = m * Math.sin(2 * Math.PI * v);
      return m * Math.cos(2 * Math.PI * v);
    };
  }
  const inScope = (P) => P.lines.filter((l) => l.on && (P.scope === 'ALL' || l.account === 'PEA'));
  const monthlyTotal = (P) => inScope(P).reduce((a, l) => a + (+l.monthly || 0), 0);
  function avgRet(P) {
    const ls = inScope(P);
    const w = ls.map((l) => (+l.value || 0) + (+l.monthly || 0) * 60);
    const tw = w.reduce((a, b) => a + b, 0);
    return tw ? ls.reduce((a, l, i) => a + (+l.ret || 0) * w[i], 0) / tw : 0.06;
  }

  function model(P) {
    const M = Math.max(1, Math.round(P.years * 12));
    const lines = inScope(P);
    const start = parseISO(D.sim.today);
    const dates = [], months = [];
    for (let m = 0; m <= M; m++) { const d = new Date(start); d.setMonth(d.getMonth() + m); dates.push(iso(d)); months.push(d.getMonth() + 1); }
    const tot = monthlyTotal(P);
    const share = lines.map((l) => (tot ? (+l.monthly || 0) / tot : 1 / Math.max(lines.length, 1)));
    const inv0 = { PEA: D.sim.invested.PEA || 0, CRYPTO: P.scope === 'ALL' ? (D.sim.invested.CRYPTO || 0) : 0 };
    const real = { PEA: 0, CRYPTO: 0 }, typed = { PEA: 0, CRYPTO: 0 };
    D.sim.lines.forEach((l) => { real[l.account] += l.value; });
    lines.forEach((l) => { typed[l.account] += +l.value || 0; });
    ['PEA', 'CRYPTO'].forEach((a) => { if (Math.abs(typed[a] - real[a]) > 0.5) inv0[a] = Math.max(0, inv0[a] + typed[a] - real[a]); });
    if (P.scope !== 'ALL') inv0.CRYPTO = 0;
    const coef = lines.map((l) => ({ mu: Math.log(1 + (+l.ret || 0)) / 12, s: (+l.vol || 0) / Math.sqrt(12), rho: l.account === 'CRYPTO' ? 0.35 : 0.85,
      y: (+l.yld || 0) / 12, pea: l.account === 'PEA', price: l.account === 'PEA' ? (+l.price || 0) : 0, monthly: +l.monthly || 0, v0: +l.value || 0 }));
    return { P, M, lines, dates, months, share, inv0, coef, matIdx: dates.findIndex((d) => d >= D.sim.maturity), start: typed.PEA + (P.scope === 'ALL' ? typed.CRYPTO : 0) };
  }

  // Un chemin. g = null : trajectoire « attendue » (rendements moyens) avec tout le détail.
  // Sinon : chemin aléatoire, seuls les totaux aux mois `rec` sont gardés dans out[offset…].
  function runPath(md, g, rec, outArr, offset) {
    const { P, M, coef, share, months } = md;
    const n = coef.length, det = !g;
    const v = new Float64Array(n), px = new Float64Array(n);
    for (let i = 0; i < n; i++) { v[i] = coef[i].v0; px[i] = coef[i].price; }
    let cashP = 0, cashC = 0, invP = md.inv0.PEA, invC = md.inv0.CRYPTO;
    const o = det ? { total: [], invested: [], tax: [], contrib: new Array(n).fill(0), left: new Array(n).fill(0) } : null;
    const exc = +P.exc || 0, excM = +P.excMonth, idx = +P.idx || 0;
    let ri = 0;
    const snap = (m) => {
      let vp = cashP, vc = cashC;
      for (let i = 0; i < n; i++) { if (coef[i].pea) vp += v[i]; else vc += v[i]; }
      if (!det) { while (ri < rec.length && rec[ri] === m) { outArr[offset + ri] = vp + vc; ri++; } return; }
      const rate = md.dates[m] >= D.sim.maturity ? P.ps : P.ps + P.ir;
      o.total.push(vp + vc); o.invested.push(invP + invC);
      o.tax.push(Math.max(vp - invP, 0) * rate + Math.max(vc - invC, 0) * (P.ps + P.ir));
    };
    snap(0);
    for (let m = 1; m <= M; m++) {
      const zc = det ? 0 : g();
      const grow = idx ? Math.pow(1 + idx, Math.floor((m - 1) / 12)) : 1;
      const excOn = exc && months[m] === excM;
      for (let i = 0; i < n; i++) {
        const c = coef[i];
        const gr = det ? Math.exp(c.mu) : Math.exp(c.mu - c.s * c.s / 2 + c.s * (c.rho * zc + Math.sqrt(1 - c.rho * c.rho) * g()));
        const div = v[i] * c.y;
        v[i] *= gr;
        if (px[i]) px[i] *= gr;
        if (P.reinvest) v[i] += div; else if (c.pea) cashP += div; else cashC += div;
        const w1 = c.monthly * grow, w2 = excOn ? exc * share[i] : 0;
        let got = w1 + w2;
        if (px[i]) got = Math.floor(w1 / px[i] + 1e-9) * px[i] + (w2 ? Math.floor(w2 / px[i] + 1e-9) * px[i] : 0);
        v[i] += got;
        if (c.pea) invP += got; else invC += got;
        if (det) { o.contrib[i] += got; o.left[i] += w1 + w2 - got; }
      }
      snap(m);
    }
    if (det) o.lineValues = Array.from(v);
    return o;
  }

  let mcJob = 0, lastMd = null, lastDet = null, lastQ = null, mcTimer = null;
  function runMC(md, det) {
    const job = ++mcJob;
    const rec = [], stepM = md.M <= 72 ? 3 : md.M <= 180 ? 6 : 12;
    for (let m = stepM; m <= md.M; m += stepM) rec.push(m);
    for (const m of [120, 240]) if (m <= md.M) rec.push(m);
    if (md.matIdx > 0) rec.push(md.matIdx);
    rec.push(md.M);
    const R = Array.from(new Set(rec)).sort((a, b) => a - b);
    const res = new Float64Array(MC_N * R.length);
    const g = makeGauss(rng(20261105));
    let k = 0;
    const step = () => {
      if (job !== mcJob) return;
      const end = Math.min(k + 400, MC_N);
      for (; k < end; k++) runPath(md, g, R, res, k * R.length);
      $('#sim-status').innerHTML = `<span class="spin"></span> Fourchette : ${nf(0).format(k)} / ${nf(0).format(MC_N)} scénarios calculés…`;
      if (k < MC_N) { setTimeout(step, 0); return; }
      const q = { rec: R };
      SCEN.forEach((s) => { q[s.k] = []; });
      const col = new Float64Array(MC_N);
      for (let j = 0; j < R.length; j++) {
        for (let i = 0; i < MC_N; i++) col[i] = res[i * R.length + j];
        col.sort();
        SCEN.forEach((s) => q[s.k].push(col[Math.floor(MC_N * s.q)]));
      }
      let loss = 0;
      const lj = R.length - 1;
      for (let i = 0; i < MC_N; i++) if (res[i * R.length + lj] < det.invested[md.M]) loss++;
      q.pLoss = loss / MC_N;
      lastQ = q;
      renderHero(md, det, q); renderSimChart(md, det, q); renderScen(md, det, q);
      $('#sim-status').textContent = `Calculé sur ${nf(0).format(MC_N)} scénarios aléatoires (volatilité de chaque ligne). La zone grise, entre Mauvais et Optimiste, contient 8 scénarios sur 10.`;
    };
    setTimeout(step, 20);
  }
  function recompute(withMC) {
    const md = model(sim), det = runPath(md, null);
    lastMd = md; lastDet = det; lastQ = null; mcJob++;
    $('#sim-status').innerHTML = `<span class="spin"></span> Fourchette : calcul des ${nf(0).format(MC_N)} scénarios…`;
    renderHero(md, det, null); renderSimChart(md, det, null); renderScen(md, det, null); renderBreakdown(md, det);
    clearTimeout(mcTimer);
    if (withMC !== false) mcTimer = setTimeout(() => runMC(md, det), 350);
  }

  function horizons(md) {
    const y0 = parseISO(D.sim.today).getFullYear();
    const out = [];
    if (md.matIdx > 0 && md.matIdx <= md.M) out.push([md.matIdx, `Le ${dShort(D.sim.maturity)}`, 'fin des 5 ans du PEA']);
    if (md.M >= 120 && Math.abs(120 - md.matIdx) > 6) out.push([120, `En ${y0 + 10}`, 'dans 10 ans']);
    if (md.M > 252) out.push([240, `En ${y0 + 20}`, 'dans 20 ans']);
    if (!out.length || out[out.length - 1][0] !== md.M) out.push([md.M, `En ${y0 + Math.round(md.M / 12)}`, `dans ${Math.round(md.M / 12)} an${md.M >= 24 ? 's' : ''}`]);
    return out.slice(-4);
  }
  function qAt(q, m, key) { if (!q) return null; const j = q.rec.indexOf(m); return j >= 0 ? q[key][j] : null; }
  // Taux annuel constant qui mènerait à `target` au mois m avec les mêmes versements
  function impliedRate(det, m, target) {
    const fv = (r) => { const g = Math.pow(1 + r, 1 / 12); let v = det.total[0]; for (let k = 1; k <= m; k++) v = v * g + (det.invested[k] - det.invested[k - 1]); return v; };
    let lo = -0.9, hi = 2;
    for (let i = 0; i < 70; i++) { const mid = (lo + hi) / 2; if (fv(mid) < target) lo = mid; else hi = mid; }
    return (lo + hi) / 2;
  }
  function renderScen(md, det, q) {
    const el = $('#pj-scen');
    if (!el) return;
    if (!q) { el.innerHTML = ''; return; }
    const P = sim, real = P.unit === 'real', defl = Math.pow(1 + P.infl, md.M / 12) ** (real ? 1 : 0);
    const y = parseISO(md.dates[md.M]).getFullYear();
    el.innerHTML = `<div class="scen-h">En ${y}${real ? ", en euros d'aujourd'hui" : ''}, selon le scénario :</div><div class="scen4">${SCEN.map((s) => {
      const v = qAt(q, md.M, s.k), r = impliedRate(det, md.M, v);
      return `<div style="border-top:3px ${s.dash === 'solid' ? 'solid' : 'dashed'} ${s.color()}"><div class="lbl">${s.label}</div>
        <div class="big">${eur(v / defl, 0)}</div><small>≈ ${pct(r, 1)} par an · ${s.hint}</small></div>`;
    }).join('')}</div>
      <div class="note" style="margin-top:8px">Pourquoi Classique fait moins que les ${pct(avgRet(P), 1)} saisis ? Ce taux est une moyenne : les baisses coûtent plus que les hausses ne rapportent (après −20 %, il faut +25 % pour revenir).</div>`;
  }

  function renderHero(md, det, q) {
    const P = sim, real = P.unit === 'real';
    const defl = (m) => (real ? Math.pow(1 + P.infl, m / 12) : 1);
    const cards = horizons(md).map(([m, lab, sub]) => {
      const med = qAt(q, m, 'p50'), lo = qAt(q, m, 'p10'), hi = qAt(q, m, 'p90');
      const val = med != null ? med : det.total[m];
      const inv = det.invested[m];
      const eff = det.total[m] - inv > 0 ? det.tax[m] / (det.total[m] - inv) : 0;
      const net = val - Math.max(val - inv, 0) * eff;
      return `<div class="hcard"><div class="hl">${lab} <span>· ${sub}</span></div>
        <div class="hv">${eur(val / defl(m), 0)}</div>
        <div class="hs">dont <b>${eur(inv / defl(m), 0)}</b> versés · plus-value <b class="${cls(val - inv)}">${eurS((val - inv) / defl(m), 0)}</b></div>
        <div class="hs">${lo != null ? `8 chances sur 10 entre <b>${eur(lo / defl(m), 0)}</b> et <b>${eur(hi / defl(m), 0)}</b>` : '<span class="spin"></span> fourchette en calcul…'}</div>
        <div class="hs muted">net d'impôts ≈ ${eur(net / defl(m), 0)}${real ? '' : ` · ≈ ${eur(val / Math.pow(1 + P.infl, m / 12), 0)} d'aujourd'hui`}</div></div>`;
    }).join('');
    const exc = +P.exc ? ` + <b>${eur(+P.exc, 0)}</b> chaque ${MONTHS_LONG[(+P.excMonth || 12) - 1]}` : '';
    const left = det.left.reduce((a, b) => a + b, 0), contrib = det.contrib.reduce((a, b) => a + b, 0);
    const lastNet = det.total[md.M] - det.tax[md.M];
    $('#sim-hero').innerHTML = `<div class="hsent">En versant <b>${eur(monthlyTotal(P), 0)} par mois</b>${exc}, avec un rendement moyen de <b>${pct(avgRet(P), 1)} par an</b>,
        ton ${P.scope === 'ALL' ? 'PEA + crypto' : 'PEA'} (aujourd'hui <b>${eur(md.start, 0)}</b>) vaudrait probablement${real ? ", en euros d'aujourd'hui" : ''} :</div>
      <div class="hcards">${cards}</div>
      <div class="hfoot">${q ? `Risque de finir sous ce que tu as versé : <b>${pct(q.pLoss, 1)}</b> des ${nf(0).format(MC_N)} scénarios. ` : ''}
        Revenu possible ensuite (règle des 4 %, en euros d'aujourd'hui) : <b>${eur(lastNet / Math.pow(1 + P.infl, md.M / 12) * 0.04 / 12, 0)} par mois</b>.
        ${left > contrib * 0.02 ? (() => { const i = det.left.indexOf(Math.max(...det.left)); const l = md.lines[i];
          return `<span class="down">Parts entières : ≈ ${eur(left, 0)} de tes versements ne seraient pas investis, surtout sur ${esc(l.short)} : son plan de ${eur(l.monthly, 0)} n'achète plus de part quand le prix d'une part le dépasse. Augmente ce plan (ou passe à 2 parts) pour éviter ça.</span>`; })() : ''}</div>`;
  }

  function renderSimChart(md, det, q) {
    const P = sim, real = P.unit === 'real';
    const f = (m) => (real ? Math.pow(1 + P.infl, m / 12) : 1);
    const ink = cv('--ink'), mut = cv('--muted');
    const ser = [], leg = [];
    if (q) {
      const xs = [md.dates[0]].concat(q.rec.map((m) => md.dates[m]));
      const ms = [0].concat(q.rec);
      const col = (k) => [det.total[0]].concat(q[k]);
      const lo = col('p10'), hi = col('p90');
      ser.push({ name: 'bas', type: 'line', stack: 'band', data: xs.map((x, i) => [x, lo[i] / f(ms[i])]), lineStyle: { opacity: 0 }, showSymbol: false, silent: true, emphasis: { disabled: true }, smooth: 0.3 });
      ser.push({ name: 'Fourchette', type: 'line', stack: 'band', data: xs.map((x, i) => [x, (hi[i] - lo[i]) / f(ms[i])]), lineStyle: { opacity: 0 }, areaStyle: { color: hexA(ink, 0.06) }, showSymbol: false, silent: true, emphasis: { disabled: true }, smooth: 0.3 });
      SCEN.forEach((s) => {
        const c = s.color(), d = col(s.k);
        ser.push(line(s.label, xs.map((x, i) => [x, d[i] / f(ms[i])]), c, { smooth: 0.3, z: s.k === 'p50' ? 4 : 3, lineStyle: { width: s.k === 'p50' ? 2.5 : 1.6, color: c, type: s.dash } }));
        leg.push({ label: s.k === 'p50' ? 'Classique (valeur probable)' : s.label, color: c });
      });
      leg.push({ label: '8 scénarios sur 10', color: hexA(ink, 0.2), sq: true });
    } else {
      ser.push(line('Trajectoire moyenne', md.dates.map((x, m) => [x, det.total[m] / f(m)]), ink));
      leg.push({ label: 'Trajectoire moyenne', color: ink });
    }
    ser.push(line('Capital versé', md.dates.map((x, m) => [x, det.invested[m] / f(m)]), mut, { lineStyle: { width: 1.5, color: mut } }));
    leg.push({ label: 'Capital versé', color: mut });
    legend('pj-legend', leg);
    const c = mk('pj-chart');
    if (!c) return;
    c.setOption(base({ xAxis: xTime(spanDays(md.dates[0], md.dates[md.M])), yAxis: yVal(axEur), series: ser,
      tooltip: Object.assign(base().tooltip, { formatter: (ps) => {
        const d = new Date(ps[0].axisValue);
        const m = Math.max(0, Math.min(md.M, Math.round((d - parseISO(md.dates[0])) / (864e5 * 30.44))));
        let h = `<div style="font-weight:650;margin-bottom:4px">${dLong(md.dates[m])}</div>`;
        const row = (k, v) => `<div style="display:flex;justify-content:space-between;gap:14px"><span>${k}</span><b>${eur(v, 0)}</b></div>`;
        let j = -1;
        if (q) { let best = 1e9; q.rec.forEach((r, i) => { if (Math.abs(r - m) < best) { best = Math.abs(r - m); j = i; } }); if (best > 6) j = -1; }
        if (j >= 0) {
          const mm = q.rec[j];
          h = `<div style="font-weight:650;margin-bottom:4px">${dLong(md.dates[mm])}</div>`;
          SCEN.forEach((s) => { h += row(`<span style="color:${s.color()}">●</span> ${s.label}`, q[s.k][j] / f(mm)); });
          h += row('Capital versé', det.invested[mm] / f(mm));
        } else {
          h += row('Trajectoire moyenne', det.total[m] / f(m)) + row('Capital versé', det.invested[m] / f(m));
        }
        return h;
      } }) }), true);
  }

  function slider(k, label, val, min, max, step, fmt, hint) {
    return `<div class="sl"><div class="sl-h"><label for="sl-${k}">${label}</label><b id="slv-${k}">${fmt(val)}</b></div>
      <input type="range" id="sl-${k}" data-k="${k}" min="${min}" max="${max}" step="${step}" value="${val}"><small>${hint}</small></div>`;
  }
  const SLFMT = { monthly: (v) => eur(+v, 0) + ' / mois', ret: (v) => nf(2).format(+v) + ' % / an', years: (v) => `${v} an${+v > 1 ? 's' : ''}`, exc: (v) => (+v ? eur(+v, 0) + ' / an' : 'aucun') };
  function renderSliders() {
    const P = sim, cur = monthlyTotal(P), plans = D.plans.filter((p) => p.active && (P.scope === 'ALL' || p.account === 'PEA')).reduce((a, p) => a + p.monthly, 0);
    $('#sim-sliders').innerHTML =
      slider('monthly', 'Versement mensuel', Math.round(cur), 0, Math.max(2000, Math.ceil(cur * 2 / 100) * 100), 5, SLFMT.monthly, `tes plans actuels : ${eur(plans, 0)} / mois`) +
      slider('ret', 'Rendement moyen attendu', +(avgRet(P) * 100).toFixed(2), 0, 15, 0.25, SLFMT.ret, 'repère : actions monde ≈ 7 % / an sur longue période (hors inflation)') +
      slider('years', 'Horizon', P.years, 1, 40, 1, SLFMT.years, `jusqu'en ${parseISO(D.sim.today).getFullYear() + (+P.years)}`) +
      `<div class="chips" style="margin:-4px 0 12px">${[['mat', '2030'], ['10', '10 ans'], ['20', '20 ans'], ['30', '30 ans'], ['40', '40 ans']]
        .map(([y, l]) => `<button class="chip" data-y="${y}" aria-pressed="${String(y === 'mat' ? +P.years === matYears() : +P.years === +y)}">${l}</button>`).join('')}</div>` +
      slider('exc', 'Versement exceptionnel chaque année', +P.exc || 0, 0, 5000, 50, SLFMT.exc, `ex. 600 € à Noël (mois réglable dans les réglages avancés)`) +
      `<label class="check-row" style="margin-top:6px"><input type="checkbox" id="sl-all" ${P.scope === 'ALL' ? 'checked' : ''}> Inclure la crypto</label>`;
  }
  const matYears = () => Math.max(1, Math.ceil((parseISO(D.sim.maturity) - parseISO(D.sim.today)) / (365.25 * 864e5)));
  function onSlider(e) {
    const k = e.target.dataset.k, v = parseFloat(e.target.value);
    if (!k) return;
    $(`#slv-${k}`).textContent = SLFMT[k](v);
    const ls = inScope(sim);
    if (k === 'monthly') {
      const cur = monthlyTotal(sim);
      if (cur > 0) ls.forEach((l) => { l.monthly = Math.round((+l.monthly || 0) * v / cur * 100) / 100; });
      else if (ls.length) ls[0].monthly = v;
    } else if (k === 'ret') {
      const d = v / 100 - avgRet(sim);
      ls.forEach((l) => { l.ret = Math.max(-0.5, Math.round(((+l.ret || 0) + d) * 10000) / 10000); });
    } else if (k === 'years') {
      sim.years = v;
      e.target.parentElement.querySelector('small').textContent = `jusqu'en ${parseISO(D.sim.today).getFullYear() + v}`;
    } else if (k === 'exc') sim.exc = v;
    saveSim();
    recompute();
    if ($('#sim-adv').open) renderSimForm();
  }

  function simField(label, html, hint) { return `<div class="field"><label>${label}</label>${html}${hint ? `<small>${hint}</small>` : ''}</div>`; }
  const pctIn = (k, v, step = 0.1) => `<input type="number" step="${step}" data-k="${k}" value="${(v * 100).toFixed(2).replace(/\.?0+$/, '')}">`;
  function renderSimForm() {
    const P = sim, prm = D.params || {};
    const live = (k) => (prm[k] && prm[k].live != null ? `live : ${pct(prm[k].live, 1)}` : '');
    $('#sim-form').innerHTML = `<div class="form wide">
      ${simField('Inflation (%/an)', pctIn('infl', P.infl), live('inflation'))}
      ${simField('Prélèvements sociaux (%)', pctIn('ps', P.ps), live('ps_rate'))}
      ${simField('Impôt sur le revenu PFU (%)', pctIn('ir', P.ir), 'appliqué avant les 5 ans du PEA et sur la crypto')}
      ${simField('Mois du versement exceptionnel', `<select data-k="excMonth">${MONTHS_LONG.map((m, i) => `<option value="${i + 1}" ${+P.excMonth === i + 1 ? 'selected' : ''}>${m}</option>`).join('')}</select>`)}
      ${simField('Hausse annuelle des versements (%)', pctIn('idx', P.idx), 'ex. 2 % pour suivre ton salaire')}
      <div class="field"><label>Dividendes</label><label class="check-row"><input type="checkbox" data-k="reinvest" ${P.reinvest ? 'checked' : ''}> réinvestis</label></div>
    </div>`;
    $('#sim-lines').innerHTML = `<table class="t"><thead><tr><th>Ligne</th><th>Compte</th><th class="n">Valeur de départ (€)</th><th class="n">Versement / mois (€)</th><th class="n">Prix d'une part (€)</th><th class="n">Rendement attendu (%/an)</th><th class="n">Dividende (%/an)</th><th class="n">Volatilité (%)</th><th></th></tr></thead><tbody>
      ${P.lines.map((l, i) => `<tr data-i="${i}" class="${l.on && (P.scope === 'ALL' || l.account === 'PEA') ? '' : 'closed'}">
        <td><label class="check-row"><input type="checkbox" data-l="on" ${l.on ? 'checked' : ''}>${l.custom ? `<input class="in" data-l="short" value="${esc(l.short)}" style="width:140px">` : `<span class="dot" style="background:${assetColor(l.ticker)}"></span>${esc(l.short)}`}</label></td>
        <td>${l.custom ? `<select class="in" data-l="account"><option ${l.account === 'PEA' ? 'selected' : ''}>PEA</option><option value="CRYPTO" ${l.account === 'CRYPTO' ? 'selected' : ''}>CRYPTO</option></select>` : esc(l.account)}</td>
        <td class="n"><input class="in" type="number" step="10" data-l="value" value="${l.value}"></td>
        <td class="n"><input class="in" type="number" step="5" data-l="monthly" value="${l.monthly}"></td>
        <td class="n">${l.account === 'PEA' ? `<input class="in" type="number" step="0.01" min="0" data-l="price" value="${l.price || ''}" placeholder="fractionné">` : '<small style="color:var(--muted)">fractionné</small>'}</td>
        <td class="n"><input class="in" type="number" step="0.5" data-l="ret" value="${+(l.ret * 100).toFixed(2)}"></td>
        <td class="n"><input class="in" type="number" step="0.1" data-l="yld" value="${+(l.yld * 100).toFixed(2)}"></td>
        <td class="n"><input class="in" type="number" step="1" data-l="vol" value="${+(l.vol * 100).toFixed(1)}">${l.hist ? `<br><small style="color:var(--muted)">historique ${nf(0).format(l.hist * 100)} %</small>` : ''}</td>
        <td>${l.custom ? '<button class="btn sm danger" data-del="1">×</button>' : ''}</td></tr>`).join('')}
      </tbody></table>
      <div class="actions" style="padding:0 12px 12px"><button class="btn" id="sim-add">+ Ajouter une ligne fictive</button>
      <span class="note" style="margin:0">PEA : parts entières (plancher du montant ÷ prix, le prix monte avec le rendement). Rendement = hausse moyenne du cours par an. Volatilité = ampleur des variations, utilisée pour la fourchette.</span></div>`;
  }
  function renderBreakdown(md, det) {
    const tot = det.lineValues.reduce((a, b) => a + b, 0) || 1;
    $('#sim-breakdown').innerHTML = `<table class="t"><thead><tr><th>Répartition à l'horizon (trajectoire moyenne)</th><th class="n">Valeur</th><th class="n">Part</th><th class="n">Investi sur la période</th><th class="n">Non investi (parts entières)</th></tr></thead><tbody>
      ${md.lines.map((l, i) => `<tr><td><div class="name"><span class="dot" style="background:${l.custom ? cv('--muted') : assetColor(l.ticker)}"></span>${esc(l.short)}</div></td><td class="n">${eur(det.lineValues[i], 0)}</td><td class="n">${pct(det.lineValues[i] / tot, 1)}</td><td class="n">${eur(det.contrib[i], 0)}</td><td class="n">${det.left[i] > 0.5 ? eur(det.left[i], 0) : '–'}</td></tr>`).join('')}
      </tbody></table>`;
  }
  function bindSim() {
    $('#sim-sliders').oninput = onSlider;
    $('#sim-sliders').onclick = (e) => {
      const b = e.target.closest('[data-y]'); if (!b) return;
      sim.years = b.dataset.y === 'mat' ? matYears() : +b.dataset.y;
      saveSim(); renderSliders(); recompute();
    };
    $('#sim-sliders').onchange = (e) => { if (e.target.id === 'sl-all') { sim.scope = e.target.checked ? 'ALL' : 'PEA'; saveSim(); renderSliders(); renderSimForm(); recompute(); } };
    let t;
    const later = () => { clearTimeout(t); t = setTimeout(() => { saveSim(); renderSliders(); recompute(); }, 300); };
    $('#sim-form').oninput = $('#sim-form').onchange = (e) => {
      const k = e.target.dataset.k; if (!k) return;
      if (e.target.type === 'checkbox') sim[k] = e.target.checked;
      else if (['infl', 'ps', 'ir', 'idx'].includes(k)) sim[k] = (parseFloat(e.target.value) || 0) / 100;
      else sim[k] = parseFloat(e.target.value) || 0;
      later();
    };
    $('#sim-lines').oninput = $('#sim-lines').onchange = (e) => {
      const tr = e.target.closest('tr[data-i]'); const k = e.target.dataset.l; if (!tr || !k) return;
      const l = sim.lines[+tr.dataset.i];
      if (k === 'on') l.on = e.target.checked;
      else if (k === 'short' || k === 'account') l[k] = e.target.value;
      else if (['ret', 'yld', 'vol'].includes(k)) l[k] = (parseFloat(e.target.value) || 0) / 100;
      else l[k] = parseFloat(e.target.value) || 0;
      later();
    };
    $('#sim-lines').onclick = (e) => {
      if (e.target.id === 'sim-add') {
        sim.lines.push({ ticker: 'X-' + Date.now(), short: 'Nouvelle ligne', account: 'PEA', value: 0, monthly: 50, price: 0, ret: 0.07, vol: 0.18, yld: 0, on: true, custom: true });
        saveSim(); renderSimForm(); renderSliders(); recompute();
      } else if (e.target.dataset.del) {
        sim.lines.splice(+e.target.closest('tr').dataset.i, 1); saveSim(); renderSimForm(); renderSliders(); recompute();
      }
    };
    $$('#sim-unit button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.u === sim.unit)));
  }

  function renderProjection() {
    const F = D.fiscal;
    const monthly = D.plans.filter((p) => p.active && p.account === 'PEA').reduce((a, p) => a + p.monthly, 0) || 1;
    $('#fx-counter').innerHTML = `<div style="font-size:30px;font-weight:650">${nf(0).format(F.days_left)} <span style="font-size:14px;color:var(--muted);font-weight:500">jours</span></div>
      <div class="meter"><div style="width:${(F.progress * 100).toFixed(1)}%"></div></div>
      <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--muted)"><span>Ouvert le ${dShort(F.opened)}</span><span>5 ans le ${dShort(F.maturity)}</span></div>
      <div class="note">Après le ${dShort(F.maturity)}, plus d'impôt sur le revenu sur les gains : seuls les prélèvements sociaux (${pct(F.ps_rate, 1)}) restent dus. Plafond de versements : ${eur(F.deposits, 0)} / ${eur(F.ceiling, 0)} (${pct(F.ceiling_used, 1)}), atteint dans ≈ ${nf(0).format((F.ceiling - F.deposits) / monthly / 12)} ans à ce rythme.</div>`;
    $('#fx-tax').innerHTML = `<div class="tax2">
        <div><div class="lbl">Si tu retires aujourd'hui</div><div class="big">${eur(F.net_now, 0)}</div><small>impôts ${eur(F.tax_now, 0)} (${pct(F.pfu_rate, 1)} des gains) · le PEA est clôturé</small></div>
        <div><div class="lbl">Après le ${dShort(F.maturity)}</div><div class="big up">${eur(F.net_after, 0)}</div><small>impôts ${eur(F.tax_after, 0)} (${pct(F.ps_rate, 1)} des gains) · le PEA reste ouvert</small></div></div>
      <div class="note">À valeur égale, attendre 2030 t'économise <b>${eur(F.saving, 0)}</b> d'impôts aujourd'hui, et l'écart grandit avec tes gains. Calcul sur ta plus-value actuelle (${eurS(F.gain, 0)}).</div>`;
    const D2 = D.dividends;
    $('#fx-divs').innerHTML = `<table class="t compact"><tbody>
      <tr><td style="color:var(--muted)">Reçus depuis l'ouverture</td><td class="n">${eur(D2.total)}</td></tr>
      <tr><td style="color:var(--muted)">12 derniers mois</td><td class="n">${eur(D2.ttm)}</td></tr>
      <tr><td style="color:var(--muted)">Attendus sur 12 mois</td><td class="n">${eur(D2.forward)}</td></tr>
      ${D2.next.map((x) => `<tr><td>${esc(x.short)} · ${dShort(x.ex_date)}</td><td class="n">${eur(x.amount)}</td></tr>`).join('')}</tbody></table>
      <div class="note" style="padding:0 12px 10px">Réinvestis par TR au plan suivant.</div>`;
    if (!sim) sim = loadSim();
    renderSliders(); renderSimForm(); bindSim(); recompute();
  }

  // ------------------------------------------------------------ ACTUALITÉS
  const newsState = { lang: '', sort: 'score', line: '' };
  function ago(isoStr) {
    const h = (Date.now() - new Date(isoStr).getTime()) / 36e5;
    if (h < 1) return "à l'instant";
    if (h < 24) return `il y a ${Math.floor(h)} h`;
    if (h < 48) return 'hier';
    return `il y a ${Math.floor(h / 24)} j`;
  }
  function newsName(t) { return t === 'MARCHE' ? 'Marchés' : ((D.assets[t] || {}).short || t); }
  function newsItems(items) {
    return items.map((n) => `<a class="news-item" href="${esc(n.url)}" target="_blank" rel="noopener">
      <div class="meta"><b>${esc(n.source)}</b><span>${ago(n.date)}</span><span class="lang">${esc(n.lang.toUpperCase())}</span>
      ${n.tickers.map((t) => `<span class="tagline"><span class="dot" style="background:${t === 'MARCHE' ? cv('--muted') : assetColor(t)}"></span>${esc(newsName(t))}</span>`).join('')}</div>
      <div class="tt">${esc(n.title)}</div></a>`).join('');
  }
  function renderNews() {
    const all = D.news.items || [];
    $('#news-sub').textContent = all.length ? `${all.length} articles des 7 derniers jours, en français et en anglais · mis à jour le ${esc((D.news.updated_at || '').replace(' UTC', ''))} (UTC)` : "Les actus arrivent au prochain passage du robot.";
    const counts = {};
    all.forEach((n) => n.tickers.forEach((t) => { counts[t] = (counts[t] || 0) + 1; }));
    const keys = ['MARCHE', ...Object.keys(counts).filter((t) => t !== 'MARCHE')].filter((t) => counts[t]);
    $('#news-lines').innerHTML = `<button class="chip" data-line="" aria-pressed="${!newsState.line}">Toutes <span class="n">${all.length}</span></button>` +
      keys.map((t) => `<button class="chip" data-line="${esc(t)}" aria-pressed="${newsState.line === t}"><span class="dot" style="background:${t === 'MARCHE' ? cv('--muted') : assetColor(t)}"></span>${esc(newsName(t))} <span class="n">${counts[t]}</span></button>`).join('');
    let items = all.filter((n) => (!newsState.lang || n.lang === newsState.lang) && (!newsState.line || n.tickers.includes(newsState.line)));
    items = items.slice().sort((a, b) => (newsState.sort === 'date' ? b.date.localeCompare(a.date) : b.score - a.score));
    $('#news-list').innerHTML = items.length ? `<div class="news-grid">${newsItems(items)}</div>` : '<div class="empty">Aucune actu pour ce filtre.</div>';
  }
  $('#news-lang').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; newsState.lang = b.dataset.l; $$('#news-lang button').forEach((x) => x.setAttribute('aria-pressed', String(x === b))); renderNews(); });
  $('#news-sort').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; newsState.sort = b.dataset.s; $$('#news-sort button').forEach((x) => x.setAttribute('aria-pressed', String(x === b))); renderNews(); });
  $('#news-lines').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; newsState.line = b.dataset.line; renderNews(); });
  $('#sim-reset').addEventListener('click', () => { sim = simDefaults(); saveSim(); renderProjection(); });
  $$('#sim-unit button').forEach((b) => b.addEventListener('click', () => {
    if (!sim) return;
    sim.unit = b.dataset.u; saveSim();
    $$('#sim-unit button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    if (lastMd) { renderHero(lastMd, lastDet, lastQ); renderSimChart(lastMd, lastDet, lastQ); renderScen(lastMd, lastDet, lastQ); }
  }));

  // ------------------------------------------------------------ TRANSACTIONS
  const TYPE_LABEL = { BUY: ['Achat', 'b-buy'], SELL: ['Vente', 'b-sell'], DIVIDEND: ['Dividende', 'b-div'], TRANSFER_IN: ['Transfert entrant', 'b-other'], TRANSFER_OUT: ['Transfert sortant', 'b-other'], STAKING: ['Staking', 'b-div'], BONUS: ['Attribution', 'b-other'], FEE: ['Frais', 'b-sell'] };
  function renderTransactions() {
    const fa = $('#tx-acc').value, ft = $('#tx-type').value, fs = $('#tx-src').value;
    const rows = D.transactions.filter((t) => (!fa || t.account === fa) && (!ft || t.type === ft) && (!fs || t.source === fs));
    const sum = (f) => rows.filter(f).reduce((a, t) => a + t.amount, 0);
    $('#tx-table').innerHTML = `<table class="t"><thead><tr><th>Date</th><th>Type</th><th>Ligne</th><th>Compte</th><th class="n">Quantité</th><th class="n">Prix unitaire</th><th class="n">Montant</th><th class="n">TTF</th><th>Source</th><th>Note</th></tr></thead><tbody>
      ${rows.map((t) => { const [lab, bc] = TYPE_LABEL[t.type] || [t.type, 'b-other']; return `<tr><td>${dShort(t.date)}</td><td><span class="badge ${bc}">${lab}</span></td>
        <td><div class="name"><span class="dot" style="background:${assetColor(t.ticker)}"></span>${esc(t.short)}</div></td><td>${esc(t.account)}</td>
        <td class="n">${t.quantity ? qty(t.quantity) : '–'}</td><td class="n">${t.price != null ? eur(t.price, t.price < 10 ? 4 : 2) : '–'}</td>
        <td class="n">${t.type === 'BUY' || t.type === 'TRANSFER_IN' || t.type === 'FEE' ? '−' : t.amount ? '+' : ''}${eur(t.amount)}</td><td class="n">${t.taxes ? eur(t.taxes) : '–'}</td>
        <td><span class="badge ${t.source === 'AUTO' ? 'b-auto' : t.source === 'ESTIME' ? 'b-est' : 'b-tr'}">${t.source === 'ESTIME' ? 'ESTIMÉ' : t.source}</span>${t.funding === 'reserve' ? ' <span class="badge b-div">RÉSERVE</span>' : ''}</td>
        <td style="white-space:normal;min-width:220px;color:var(--text-2)">${esc(t.note)}</td></tr>`; }).join('')}
      <tr class="total"><td colspan="6">${rows.length} opération(s) · achats ${eur(sum((t) => t.type === 'BUY'))} · ventes ${eur(sum((t) => t.type === 'SELL'))} · dividendes ${eur(sum((t) => t.type === 'DIVIDEND'))}</td><td colspan="4"></td></tr>
      </tbody></table>`;
  }

  // ------------------------------------------------------------ routage
  const RENDER = { overview: renderOverview, performance: renderPerformance, risque: renderRisk, positions: renderPositions, allocation: renderAllocation, crypto: renderCrypto, projection: renderProjection, transactions: renderTransactions, news: renderNews,
    donnees: () => { if (window.PEA_EDITOR) window.PEA_EDITOR.render(); else $('#ed-body').innerHTML = '<div class="empty"><span class="spin"></span> Chargement…</div>'; } };
  function show(view) {
    const parts = String(view || '').split('/');
    view = parts[0]; state.sub = parts[1] || null;
    if (!VIEWS.includes(view)) view = 'overview';
    state.view = view;
    $$('.view').forEach((v) => v.classList.toggle('active', v.id === 'view-' + view));
    $$('#nav a[data-view]').forEach((a) => a.classList.toggle('active', a.dataset.view === view));
    const scoped = ['overview', 'performance', 'risque', 'allocation'].includes(view);
    $('#scope-seg').parentElement.style.opacity = scoped ? '1' : '.45';
    $('#scope-seg').parentElement.title = scoped ? '' : 'Sans effet sur cette vue';
    renderChrome();
    try { RENDER[view](); } catch (e) { console.error(e); }
    requestAnimationFrame(() => Object.values(charts).forEach((c) => { if (c.getDom().offsetParent) c.resize(); }));
  }
  function rerender() { show(state.view); }

  $$('#scope-seg button').forEach((b) => b.addEventListener('click', () => { state.scope = b.dataset.scope; store.set('pea-scope', state.scope); rerender(); }));
  $$('#period-seg button').forEach((b) => b.addEventListener('click', () => { state.period = b.dataset.period; store.set('pea-period', state.period); rerender(); }));
  $$('#ov-mode button').forEach((b) => b.addEventListener('click', () => { state.ovMode = b.dataset.mode; $$('#ov-mode button').forEach((x) => x.setAttribute('aria-pressed', String(x === b))); renderEvolution(); }));
  $$('#pos-mode button').forEach((b) => b.addEventListener('click', () => { state.posMode = b.dataset.m; store.set('pea-posmode', state.posMode); if (state.pos) { const ch = charts['pos-chart']; if (ch) { ch.dispose(); delete charts['pos-chart']; } renderPositionChart(state.pos); } }));
  $$('#pos-int button').forEach((b) => b.addEventListener('click', () => { state.posInt = b.dataset.i; $('#pos-tv').dataset.k = ''; if (state.pos) renderPositionChart(state.pos); }));
  $$('#pj-h button').forEach((b) => b.addEventListener('click', () => { state.pjH = b.dataset.h; $$('#pj-h button').forEach((x) => x.setAttribute('aria-pressed', String(x === b))); renderProjection(); }));
  ['#tx-acc', '#tx-type', '#tx-src'].forEach((s) => $(s).addEventListener('change', renderTransactions));
  $('#theme-btn').addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    store.set('pea-theme', next);
    Object.keys(charts).forEach((k) => { charts[k].dispose(); delete charts[k]; });
    rerender();
  });
  window.addEventListener('hashchange', () => show(location.hash.slice(1)));
  let rt;
  window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => Object.values(charts).forEach((c) => c.getDom().offsetParent && c.resize()), 120); });
  window.PEA_APP = { rerender, show, state, store, fmt: { eur, eurS, pct, pctS, num, qty, dShort, dLong, esc, cls }, assetColor, help };
  show(location.hash.slice(1) || 'overview');
})();
