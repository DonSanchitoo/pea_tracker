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
  const VIEWS = ['overview', 'performance', 'risque', 'positions', 'allocation', 'crypto', 'projection', 'transactions'];
  const SCOPE_LABEL = { TOTAL: 'Consolidé', PEA: 'PEA', CRYPTO: 'Crypto' };
  const state = {
    scope: D.meta.scopes.includes(store.get('pea-scope', 'TOTAL')) ? store.get('pea-scope', 'TOTAL') : 'TOTAL',
    period: store.get('pea-period', 'MAX'),
    view: 'overview', ovMode: 'value', pos: null, pjH: 'mat',
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
    return (v) => { const d = new Date(v); return spanDays > 150 ? `${MONTHS[d.getMonth()]} ${String(d.getFullYear()).slice(2)}` : `${d.getDate()} ${MONTHS[d.getMonth()]}`; };
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
      <div class="side-card"><div class="lbl">Échéance fiscale PEA</div>
        <div class="row"><span class="big">${dShort(f.maturity)}</span><span class="lbl">${nf(0).format(f.days_left)} j</span></div>
        <div class="meter"><div style="width:${(f.progress * 100).toFixed(1)}%"></div></div>
        <div class="lbl">${pct(f.progress, 0)} du chemin vers l'exonération d'IR</div></div>
      <a class="btn" href="aide.html#maj">Mettre à jour mes données</a>`;
    const open = D.positions.filter((p) => p.open);
    const items = open.map((p) => `<span class="item"><b>${esc(p.short)}</b>${eur(p.price, p.price > 1000 ? 0 : 2)} <span class="${p.day_pct >= 0 ? 'tu' : 'td'}">${arrow(p.day_pct)}${pctS(p.day_pct)}</span></span>`).join('');
    const k = D.kpi.TOTAL;
    $('#ticker').innerHTML = `<span class="tag">● Marchés</span><div class="track">${items}<span class="item"><b>Total</b>${eur(k.value)}</span>${items}<span class="item"><b>Total</b>${eur(k.value)}</span></div>`;
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

  function renderPositionChart(t) {
    const p = D.positions.find((x) => x.ticker === t);
    const S = D.position_series[t];
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
    const c = mk('pos-chart');
    if (!c || !S) return;
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

  // ------------------------------------------------------------ ALLOCATION
  function hbars(items, color, total) {
    const mx = Math.max(...items.map((i) => i.weight), 0.0001);
    return items.map((i) => `<div class="hbar"><span>${esc(i.label)}</span><div class="track"><div class="fill" style="width:${(i.weight / mx * 100).toFixed(1)}%;background:${color}"></div></div><span class="v">${pct(i.weight, 1)}</span></div>`).join('') +
      (total ? `<div class="note">Total ${eur(total)}</div>` : '');
  }
  function renderAllocation() {
    const A = D.allocation;
    const pos = D.positions.filter((p) => p.open);
    const tot = A.total;
    $('#al-lines').innerHTML = `<div class="segbar">${pos.map((p) => { const w = p.value / tot; return `<div style="flex:${w};background:${assetColor(p.ticker)};color:${D.assets[p.ticker].slot === 4 ? '#0b0b0b' : '#fff'}" title="${esc(p.short)} ${pct(w, 1)}">${w > 0.09 ? pct(w, 0) : ''}</div>`; }).join('')}</div>
      <table class="t compact"><thead><tr><th>Ligne</th><th class="n">Valeur</th><th class="n">Poids total</th><th class="n">Poids dans son compte</th></tr></thead><tbody>
      ${pos.map((p) => `<tr><td><div class="name"><span class="dot" style="background:${assetColor(p.ticker)}"></span>${esc(p.short)}</div></td><td class="n">${eur(p.value)}</td><td class="n">${pct(p.weight_total, 1)}</td><td class="n">${pct(p.weight_account, 1)} <small style="color:var(--muted)">${esc(p.account)}</small></td></tr>`).join('')}
      </tbody></table>
      <div class="note">Concentration : nombre effectif de lignes <b>${num(A.concentration.total.n_eff, 1)}</b> (consolidé), <b>${num(A.concentration.pea.n_eff, 1)}</b> (PEA). <a href="aide.html#concentration">C'est quoi ?</a></div>`;
    $('#al-class').innerHTML = hbars(A.by_class, slot(1), tot);
    $('#al-zones').innerHTML = hbars(A.by_zone, slot(1)) + '<div class="note">Transparence : chaque ETF est éclaté selon les poids pays approximatifs de son indice (config.json). Air Liquide et TotalEnergies sont comptées en France (siège), même si leur activité est mondiale.</div>';
    $('#al-plan').innerHTML = `<div class="legend"><span><i class="sq" style="background:${slot(1)}"></i>Réel (valeur)</span><span><i class="sq" style="background:${cv('--muted')}"></i>Part des versements du plan</span></div>` +
      A.vs_plan.map((r) => `<div style="padding:6px 0;border-bottom:1px solid var(--border)"><div style="display:flex;justify-content:space-between;font-size:12px"><span>${esc(r.short)}</span><span class="num">${pct(r.actual, 1)} <span style="color:var(--muted)">/ ${pct(r.plan, 1)}</span></span></div>
        <div class="segbar thin" style="margin:4px 0 2px"><div style="flex:${r.actual};background:${slot(1)}"></div><div style="flex:${Math.max(1 - r.actual, 0)};background:var(--surface-3)"></div></div>
        <div class="segbar thin" style="margin:2px 0"><div style="flex:${r.plan};background:${cv('--muted')}"></div><div style="flex:${Math.max(1 - r.plan, 0)};background:var(--surface-3)"></div></div></div>`).join('') +
      `<div class="note">Les lignes sans plan (actions) ne reçoivent plus d'argent : leur poids baisse mécaniquement à chaque versement.</div>`;
    $('#al-plans').innerHTML = `<table class="t"><thead><tr><th>Plan</th><th class="n">Montant</th><th>Prochaine exécution</th><th class="n">Cours actuel</th><th class="n">Parts achetées (est.)</th><th class="n">Investi (est.)</th><th class="n">Non investi</th><th>Montant conseillé</th></tr></thead><tbody>
      ${D.plans.map((p) => `<tr><td><div class="name"><span class="dot" style="background:${assetColor(p.ticker)}"></span>${esc(p.short)}</div></td><td class="n">${eur(p.amount, 0)}</td><td>${dShort(p.next)} <small style="color:var(--muted)">J−${p.days_to}</small></td>
        <td class="n">${eur(p.price, p.price < 10 ? 3 : 2)}</td><td class="n">${p.shares != null ? p.shares : 'fractionné'}</td><td class="n">${eur(p.invested)}</td>
        <td class="n">${p.residual > 0.005 ? `<span class="${p.residual_pct >= 0.1 ? 'down' : 'flat'}">${eur(p.residual)} (${pct(p.residual_pct, 1)})</span>` : '–'}</td>
        <td>${p.suggest && p.residual_pct >= 0.05 ? p.suggest.map((s) => `${s.amount} € → ${s.shares} part${s.shares > 1 ? 's' : ''}`).join(' · ') : '<span style="color:var(--muted)">OK</span>'}</td></tr>`).join('')}
      <tr class="total"><td>Total mensuel</td><td class="n">${eur(D.plans.reduce((a, p) => a + p.amount, 0), 0)}</td><td></td><td></td><td></td><td class="n">${eur(D.plans.reduce((a, p) => a + p.invested, 0))}</td><td class="n">${eur(D.plans.reduce((a, p) => a + p.residual, 0))}</td><td></td></tr>
      </tbody></table>`;
  }

  // ------------------------------------------------------------ CRYPTO
  function renderCrypto() {
    if (!D.kpi.CRYPTO) { $('#cr-kpis').innerHTML = '<div class="empty">Pas de crypto.</div>'; return; }
    const k = D.kpi.CRYPTO, r = D.risk.CRYPTO;
    const eth = D.positions.find((p) => p.account === 'CRYPTO' && p.open) || D.positions.find((p) => p.account === 'CRYPTO');
    const stak = D.transactions.filter((t) => t.ticker === eth.ticker && t.type === 'STAKING').reduce((a, t) => a + t.quantity, 0);
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
      { label: 'Staking', value: eur(stak * eth.price), delta: 'récompenses cumulées' },
      { label: 'Plan mensuel', value: eur((D.plans.find((p) => p.ticker === eth.ticker) || {}).amount || 0, 0) },
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
  function renderProjection() {
    const F = D.fiscal, P = D.projection;
    $('#fx-counter').innerHTML = `<div style="font-size:30px;font-weight:650">${nf(0).format(F.days_left)} <span style="font-size:14px;color:var(--muted);font-weight:500">jours</span></div>
      <div class="meter"><div style="width:${(F.progress * 100).toFixed(1)}%"></div></div>
      <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--muted)"><span>Ouvert le ${dShort(F.opened)}</span><span>5 ans le ${dShort(F.maturity)}</span></div>
      <div style="margin-top:14px;font-size:12px">Plafond de versements : <b>${eur(F.deposits, 0)}</b> / ${eur(F.ceiling, 0)}</div>
      <div class="meter"><div style="width:${Math.max(F.ceiling_used * 100, 0.5).toFixed(2)}%"></div></div>
      <div class="note">${pct(F.ceiling_used, 2)} utilisé. À ${eur(P.monthly, 0)}/mois, plafond atteint dans ≈ ${nf(0).format((F.ceiling - F.deposits) / P.monthly / 12)} ans.</div>`;
    $('#fx-tax').innerHTML = `<table class="t"><thead><tr><th>Scénario de retrait</th><th class="n">Valeur PEA</th><th class="n">Gain imposable</th><th class="n">Taux</th><th class="n">Impôts</th><th class="n">Net en poche</th></tr></thead><tbody>
      <tr><td>Aujourd'hui (avant 5 ans : retrait = clôture du PEA)</td><td class="n">${eur(F.value)}</td><td class="n">${eurS(F.gain)}</td><td class="n">${pct(F.pfu_rate, 1)}</td><td class="n down">−${eur(F.tax_now)}</td><td class="n">${eur(F.net_now)}</td></tr>
      <tr><td>Après le ${dShort(F.maturity)} (à valeur égale)</td><td class="n">${eur(F.value)}</td><td class="n">${eurS(F.gain)}</td><td class="n">${pct(F.ps_rate, 1)}</td><td class="n down">−${eur(F.tax_after)}</td><td class="n">${eur(F.net_after)}</td></tr>
      </tbody></table><div class="note" style="padding:0 12px 10px">Écart aujourd'hui : <b>${eur(F.saving)}</b>. PFU = 12,8 % d'impôt + 18,6 % de prélèvements sociaux (taux 2026). Gain = valeur + dividendes − capital net investi.</div>`;

    const D2 = D.dividends;
    $('#fx-divs').innerHTML = `<table class="t compact"><tbody>
      <tr><td style="color:var(--muted)">Encaissés depuis l'ouverture</td><td class="n">${eur(D2.total)}</td></tr>
      <tr><td style="color:var(--muted)">12 derniers mois</td><td class="n">${eur(D2.ttm)}</td></tr>
      <tr><td style="color:var(--muted)">Rendement sur coût (actions)</td><td class="n">${pct(D2.yield_on_cost)}</td></tr>
      <tr><td style="color:var(--muted)">Estimation 12 mois à venir</td><td class="n">${eur(D2.forward)}</td></tr></tbody></table>
      <table class="t compact"><thead><tr><th>Prochains (estimés)</th><th class="n">Montant</th></tr></thead><tbody>
      ${D2.next.map((d) => `<tr><td>${esc(d.short)} · ${dShort(d.ex_date)}</td><td class="n">${eur(d.amount)}</td></tr>`).join('')}</tbody></table>
      <table class="t compact"><thead><tr><th>Reçus</th><th class="n">Montant</th></tr></thead><tbody>
      ${D2.received.slice().reverse().map((d) => `<tr><td>${dShort(d.date)} · ${esc(d.short)}</td><td class="n">${eur(d.amount)}</td></tr>`).join('')}</tbody></table>`;

    const mat = P.scenarios[0].horizons[0].date;
    const nEnd = state.pjH === 'mat' ? P.dates.findIndex((d) => d >= mat) : +state.pjH;
    const ds = P.dates.slice(0, nEnd + 1);
    const dark = document.documentElement.getAttribute('data-theme') === 'dark' || (!document.documentElement.getAttribute('data-theme') && matchMedia('(prefers-color-scheme: dark)').matches);
    const ramp = dark ? ['#1c5cab', '#3987e5', '#9ec5f4'] : ['#86b6ef', '#2a78d6', '#104281'];
    const mut = cv('--muted');
    const ser = P.scenarios.map((s, i) => line(`${s.label} (${pct(s.rate, 0)}/an)`, ds.map((d, j) => [d, s.values[j]]), ramp[i], { lineStyle: { width: 2, color: ramp[i], type: 'dashed' } }));
    ser.push(line('Capital investi', ds.map((d, j) => [d, P.invested[j]]), mut, { lineStyle: { width: 1.5, color: mut } }));
    legend('pj-legend', [...P.scenarios.map((s, i) => ({ label: `${s.label} ${pct(s.rate, 0)}/an`, color: ramp[i] })), { label: 'Capital investi', color: mut }]);
    const c = mk('pj-chart');
    if (c) c.setOption(base({ xAxis: xTime(spanDays(ds[0], ds[ds.length - 1])), yAxis: yVal(axEur), series: ser, tooltip: Object.assign(base().tooltip, { formatter: tip((v) => eur(v, 0)) }) }), true);

    const hz = P.scenarios[0].horizons.map((h) => h.label);
    $('#pj-table').innerHTML = `<table class="t"><thead><tr><th>Horizon</th><th>Date</th><th class="n">Capital investi</th>${P.scenarios.map((s) => `<th class="n">${esc(s.label)} ${pct(s.rate, 0)}</th>`).join('')}<th class="n">Net central (après PS)</th></tr></thead><tbody>
      ${hz.map((label, i) => `<tr><td>${esc(label)}</td><td>${dShort(P.scenarios[0].horizons[i].date)}</td><td class="n">${eur(P.scenarios[0].horizons[i].invested, 0)}</td>
        ${P.scenarios.map((s) => `<td class="n">${eur(s.horizons[i].value, 0)}<br><small class="${cls(s.horizons[i].gain)}">${eurS(s.horizons[i].gain, 0)}</small></td>`).join('')}
        <td class="n">${eur(P.scenarios[1].horizons[i].net, 0)}</td></tr>`).join('')}</tbody></table>
      <div class="note" style="padding:0 12px 10px">Point de départ : PEA à ${eur(P.start_value)}, ${eur(P.monthly, 0)} versés chaque mois. Les rendements ne sont pas garantis : c'est un ordre de grandeur, pas une prévision.</div>`;
  }

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
        <td><span class="badge ${t.source === 'AUTO' ? 'b-auto' : t.source === 'ESTIME' ? 'b-est' : 'b-tr'}">${t.source === 'ESTIME' ? 'ESTIMÉ' : t.source}</span></td>
        <td style="white-space:normal;min-width:220px;color:var(--text-2)">${esc(t.note)}</td></tr>`; }).join('')}
      <tr class="total"><td colspan="6">${rows.length} opération(s) · achats ${eur(sum((t) => t.type === 'BUY'))} · ventes ${eur(sum((t) => t.type === 'SELL'))} · dividendes ${eur(sum((t) => t.type === 'DIVIDEND'))}</td><td colspan="4"></td></tr>
      </tbody></table>`;
  }

  // ------------------------------------------------------------ routage
  const RENDER = { overview: renderOverview, performance: renderPerformance, risque: renderRisk, positions: renderPositions, allocation: renderAllocation, crypto: renderCrypto, projection: renderProjection, transactions: renderTransactions };
  function show(view) {
    if (!VIEWS.includes(view)) view = 'overview';
    state.view = view;
    $$('.view').forEach((v) => v.classList.toggle('active', v.id === 'view-' + view));
    $$('#nav a[data-view]').forEach((a) => a.classList.toggle('active', a.dataset.view === view));
    const scoped = ['overview', 'performance', 'risque'].includes(view);
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
  show(location.hash.slice(1) || 'overview');
})();
