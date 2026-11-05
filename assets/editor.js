/* PEA Tracker : « Mes données ». Lit et écrit config.json, data/transactions.csv et data/reconciliation.csv
   dans le dépôt GitHub via l'API GitHub (jeton personnel stocké uniquement dans ce navigateur), puis relance le calcul. */
(function () {
  'use strict';
  const D = window.PEA_DATA, APP = window.PEA_APP;
  if (!D || !APP) return;
  const { eur, pct, qty, dShort, esc } = APP.fmt;
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const [OWNER, REPO] = (D.meta.repo || 'DonSanchitoo/pea_tracker').split('/');
  const API = 'https://api.github.com';
  const TOKEN_KEY = 'pea-gh-token';
  const COLS = ['date', 'account', 'type', 'ticker', 'quantity', 'amount', 'taxes', 'source', 'note'];
  const TYPES = [['BUY', 'Achat'], ['SELL', 'Vente'], ['DIVIDEND', 'Dividende'], ['TRANSFER_IN', 'Transfert entrant'], ['TRANSFER_OUT', 'Transfert sortant'],
    ['STAKING', 'Récompense de staking'], ['BONUS', 'Action gratuite'], ['FEE', 'Frais']];
  const TYPE_LABEL = Object.fromEntries(TYPES);
  const FREQS = [['1', 'Chaque mois'], ['twice', '2 fois par mois'], ['2', 'Tous les 2 mois'], ['3', 'Chaque trimestre']];
  const WORLD = { 'Amérique du Nord': 74, 'Europe': 16, 'Japon': 5.5, 'Pacifique développé': 2.5, 'Autres': 2 };
  const EM = { 'Chine': 27, 'Taïwan': 22, 'Inde': 20, 'Corée du Sud': 11, 'Autres émergents': 20 };
  const S = { tab: 'ops', files: null, loading: false, catalog: null, newAssets: {}, edit: null, open: false, user: null };

  const token = () => APP.store.get(TOKEN_KEY, '');
  const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b64enc = (s) => { const b = new TextEncoder().encode(s); let bin = ''; for (let i = 0; i < b.length; i += 0x8000) bin += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000)); return btoa(bin); };
  const b64dec = (s) => new TextDecoder().decode(Uint8Array.from(atob(s.replace(/\s/g, '')), (c) => c.charCodeAt(0)));
  const clean = (v) => String(v == null ? '' : v).replace(/[,\r\n]/g, ' ').replace(/\s+/g, ' ').trim();
  const numIn = (v) => { const n = parseFloat(String(v).replace(',', '.')); return isFinite(n) ? n : null; };
  const fmtNum = (n, d) => (n == null || n === '' ? '' : String(+(+n).toFixed(d)));

  // ------------------------------------------------------------ GitHub
  async function gh(path, opt) {
    opt = opt || {};
    const h = { Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' };
    if (token()) h.Authorization = 'Bearer ' + token();
    if (opt.body) h['Content-Type'] = 'application/json';
    const r = await fetch(API + path, { method: opt.method || 'GET', headers: h, body: opt.body ? JSON.stringify(opt.body) : undefined, cache: 'no-store' });
    if (r.status === 204) return null;
    let j = null;
    try { j = await r.json(); } catch (e) { j = null; }
    if (!r.ok) {
      const m = (j && j.message) || r.statusText;
      const err = new Error(r.status === 401 ? 'jeton refusé (expiré ou mal copié)' : r.status === 403 && /rate limit/i.test(m) ? 'limite de lecture GitHub atteinte, connecte ton jeton' :
        r.status === 403 || r.status === 404 ? `accès refusé (${m}) : vérifie les permissions du jeton` : r.status === 409 ? 'conflit' : `${r.status} ${m}`);
      err.status = r.status;
      throw err;
    }
    return j;
  }
  async function getFile(path) {
    const j = await gh(`/repos/${OWNER}/${REPO}/contents/${path}?ref=main`);
    return { text: b64dec(j.content), sha: j.sha };
  }
  async function putFile(path, text, sha, message) {
    return gh(`/repos/${OWNER}/${REPO}/contents/${path}`, { method: 'PUT', body: { message, content: b64enc(text), sha, branch: 'main' } });
  }
  async function loadFiles(force) {
    if (S.files && !force) return;
    S.loading = true;
    try {
      const [c, t, r] = await Promise.all([getFile('config.json'), getFile('data/transactions.csv'), getFile('data/reconciliation.csv')]);
      S.files = { config: Object.assign(c, { json: JSON.parse(c.text) }), tx: Object.assign(t, parseCSV(t.text)), recon: r };
    } finally { S.loading = false; }
  }
  async function loadCatalog() {
    if (S.catalog) return S.catalog;
    try { const r = await fetch('data/catalog.json?v=' + Date.now()); S.catalog = (await r.json()).items || []; } catch (e) { S.catalog = []; }
    return S.catalog;
  }

  function parseCSV(text) {
    const lines = text.replace(/\r/g, '').split('\n');
    const rows = [];
    for (let i = 1; i < lines.length; i++) {
      if (!lines[i].trim()) continue;
      const f = lines[i].split(',');
      const o = {};
      COLS.forEach((c, j) => { o[c] = f[j] !== undefined ? f[j] : ''; });
      if (f.length > COLS.length) o.note = f.slice(COLS.length - 1).join(' ');
      rows.push(o);
    }
    return { head: lines[0], rows };
  }
  const toCSV = (head, rows) => head + '\n' + rows.map((r) => COLS.map((c) => clean(r[c])).join(',')).join('\n') + '\n';

  // ------------------------------------------------------------ messages & recalcul
  function msg(kind, html) { $('#ed-msg').innerHTML = html ? `<div class="msg ${kind}">${html}</div>` : ''; }
  function status(html) { $('#ed-status').innerHTML = html || ''; }

  async function commit(changes, message) {
    if (!token()) { S.tab = 'connexion'; render(); msg('err', 'Connecte d\'abord ton jeton GitHub pour pouvoir enregistrer.'); return false; }
    msg('info', '<span class="spin"></span> Enregistrement dans GitHub…');
    try {
      for (const ch of changes) {
        const f = S.files[ch.key];
        const res = await putFile(ch.path, ch.text, f.sha, message);
        f.sha = res.content.sha;
        f.text = ch.text;
        if (ch.key === 'config') { f.json = JSON.parse(ch.text); Object.keys(S.newAssets).forEach((t) => { if (f.json.assets[t]) delete S.newAssets[t]; }); }
        if (ch.key === 'tx') Object.assign(f, parseCSV(ch.text));
      }
    } catch (e) {
      if (e.status === 409) {
        await loadFiles(true);
        msg('err', 'Le fichier venait d\'être modifié (par le robot). J\'ai rechargé la dernière version : refais ta modification.');
      } else msg('err', `Échec de l'enregistrement : ${esc(e.message)}`);
      render();
      return false;
    }
    msg('ok', `Enregistré dans GitHub : « ${esc(message)} ». Recalcul du dashboard lancé.`);
    recalc();
    return true;
  }

  async function recalc() {
    if (!token()) { S.tab = 'connexion'; render(); msg('err', 'Connecte ton jeton GitHub pour lancer un recalcul.'); return; }
    const t0 = Date.now();
    try {
      await gh(`/repos/${OWNER}/${REPO}/actions/workflows/main.yml/dispatches`, { method: 'POST', body: { ref: 'main', inputs: { mail: 'none' } } });
    } catch (e) { status(`Recalcul impossible : ${esc(e.message)}`); return; }
    status('<span class="spin"></span> Recalcul en cours sur GitHub (1 à 2 min)…');
    let run = null;
    for (let i = 0; i < 72; i++) {
      await sleep(5000);
      try {
        const j = await gh(`/repos/${OWNER}/${REPO}/actions/workflows/main.yml/runs?per_page=5&event=workflow_dispatch`);
        run = (j.workflow_runs || []).find((r) => new Date(r.created_at).getTime() > t0 - 90000) || null;
      } catch (e) { run = null; }
      if (run && run.status === 'completed') break;
    }
    if (!run || run.conclusion !== 'success') {
      status(`Recalcul ${run ? 'en échec' : 'sans réponse'}${run ? ` : <a href="${run.html_url}" target="_blank" rel="noopener">voir le détail</a>` : ''}`);
      return;
    }
    status('<span class="spin"></span> Publication du site…');
    const gen0 = D.meta.generated_at;
    for (let i = 0; i < 48; i++) {
      await sleep(5000);
      try {
        const txt = await (await fetch('data/dashboard.js?v=' + Date.now(), { cache: 'no-store' })).text();
        const m = txt.match(/"generated_at":"([^"]+)"/);
        if (m && m[1] !== gen0) { status('À jour, rechargement…'); location.reload(); return; }
      } catch (e) { /* on réessaie */ }
    }
    status('Recalcul terminé ; la mise en ligne tarde. Recharge la page dans une minute.');
  }

  // ------------------------------------------------------------ instruments
  const norm = (s) => String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const title = (s) => String(s || '').toLowerCase().replace(/\b([a-zà-ÿ])/g, (m) => m.toUpperCase()).replace(/\b(Etf|Pea|Msci|Us|Usa|Esg|Em|Sp|Nsdq|Cac|Ucits)\b/g, (m) => m.toUpperCase());
  function cfgAssets() { return (S.files ? S.files.config.json.assets : D.config.assets) || {}; }
  function nextSlot() {
    const used = new Set(Object.values(cfgAssets()).map((a) => a.slot).concat(Object.values(S.newAssets).map((a) => a.slot)));
    for (let i = 1; i <= 8; i++) if (!used.has(i)) return i;
    return 8;
  }
  function guessAsset(it) {
    const preset = (D.presets || []).find((p) => p.ticker === it.s);
    if (preset) { const a = Object.assign({}, preset); delete a.ticker; a.tr_name = a.name; a.slot = nextSlot(); a.ttf = false; return a; }
    const n = (it.n || '').toUpperCase(), isin = it.i || '';
    const kind = it.t === 'Crypto' ? 'Crypto' : it.t === 'Action' ? 'Action' : 'ETF';
    let cls = 'Actions Monde (ETF)', zones = Object.assign({}, WORLD), fr = `"${title(it.n)}"`, en = fr;
    if (kind === 'Crypto') { cls = 'Crypto-actifs'; zones = { 'Crypto (hors zone)': 100 }; fr = it.n; en = `${it.n} price`; }
    else if (kind === 'Action') {
      cls = isin.startsWith('FR') ? 'Actions françaises' : 'Actions européennes';
      zones = isin.startsWith('FR') ? { France: 100 } : { Europe: 100 };
    } else if (/NASDAQ|NSDQ/.test(n)) { zones = { 'Amérique du Nord': 98, 'Autres': 2 }; fr = 'Nasdaq'; en = 'Nasdaq 100'; }
    else if (/S&P|SP 500|S\.P|500|USA|\bUS\b|AMERI/.test(n)) { zones = { 'Amérique du Nord': 100 }; fr = '"S&P 500" OR "Wall Street"'; en = '"S&P 500"'; }
    else if (/EMERG|\bEM\b|ASIA|ASIE|CHINA|CHINE|INDIA|INDE/.test(n)) { cls = 'Actions Asie émergente (ETF)'; zones = Object.assign({}, EM); fr = '"marchés émergents"'; en = '"emerging markets"'; }
    else if (/EUROPE|EURO|EMU|STOXX|DAX/.test(n)) { cls = 'Actions Europe (ETF)'; zones = { Europe: 100 }; fr = '"bourses européennes" OR "Stoxx 600"'; en = '"European stocks" OR "Stoxx 600"'; }
    else if (/CAC|FRANCE/.test(n)) { cls = 'Actions françaises'; zones = { France: 100 }; fr = '"CAC 40"'; en = '"CAC 40"'; }
    else if (/JAPAN|JAPON|TOPIX|NIKKEI/.test(n)) { zones = { Japon: 100 }; fr = 'Nikkei OR "Bourse de Tokyo"'; en = 'Nikkei OR "Japanese stocks"'; }
    else if (/WORLD|MONDE|ACWI/.test(n)) { fr = '"MSCI World"'; en = '"MSCI World"'; }
    const nm = title(it.n);
    return { name: nm, short: nm.length > 22 ? nm.slice(0, 22).trim() : nm, tr_name: nm, isin, account: kind === 'Crypto' ? 'CRYPTO' : 'PEA', kind, asset_class: cls,
      ter: kind === 'ETF' ? 0.2 : 0, slot: nextSlot(), zones, ttf: kind === 'Action' && isin.startsWith('FR'), news: { fr, en } };
  }
  async function searchInstruments(q) {
    const nq = norm(q).trim();
    const cat0 = nq ? await loadCatalog() : (S.catalog || []);
    const byTicker = {}; cat0.forEach((it) => { byTicker[it.s] = it; });
    const pre = {}; (D.presets || []).forEach((p) => { pre[p.ticker] = p; });
    const ownList = Object.entries(cfgAssets()).concat(Object.entries(S.newAssets).filter(([t]) => !cfgAssets()[t]));
    const own = ownList.map(([t, a]) => ({ s: t, n: a.short, full: a.name, i: a.isin || '', t: a.kind, own: true,
      k: ((byTicker[t] || {}).n || '') + ' ' + ((byTicker[t] || {}).k || '') }));
    const score = (it) => {
      const s = norm(it.s), n = norm(it.n) + ' ' + norm(it.full) + ' ' + norm(it.k), i = norm(it.i);
      if (!nq) return it.own ? 1 : 0;
      if (s === nq || s.split('.')[0] === nq || s.split('-')[0] === nq || i === nq) return 100;
      if (s.startsWith(nq)) return 80;
      if (n.split(/\s+/).some((w) => w.startsWith(nq))) return 60;
      if (nq.split(/\s+/).every((w) => n.includes(w))) return 45;
      if (i.startsWith(nq)) return 40;
      return 0;
    };
    const mine = own.map((it) => [score(it) + 5, it]).filter((x) => x[0] > 5 || !nq).sort((a, b) => b[0] - a[0]).map((x) => x[1]);
    if (!nq) return { mine, others: (D.presets || []).filter((p) => !cfgAssets()[p.ticker] && !S.newAssets[p.ticker]).map((p) => ({ s: p.ticker, n: p.short, full: p.name, i: p.isin, t: p.kind, preset: true })) };
    const cat = cat0.map((it) => (pre[it.s] ? Object.assign({}, it, { n: pre[it.s].short, full: pre[it.s].name }) : it));
    const ownSet = new Set(own.map((x) => x.s));
    const others = cat.filter((it) => !ownSet.has(it.s)).map((it) => [score(it), it]).filter((x) => x[0] > 0).sort((a, b) => b[0] - a[0]).slice(0, 12).map((x) => x[1]);
    if (others.filter((x) => x.t === 'Crypto').length < 2 && nq.length >= 2) {
      try {
        const r = await fetch('https://api.coingecko.com/api/v3/search?query=' + encodeURIComponent(q));
        const j = await r.json();
        (j.coins || []).slice(0, 5).forEach((c) => { const s = c.symbol.toUpperCase() + '-EUR'; if (!ownSet.has(s) && !others.find((o) => o.s === s)) others.push({ s, n: c.name, i: '', t: 'Crypto' }); });
      } catch (e) { /* hors ligne */ }
    }
    return { mine, others };
  }
  function pickerHTML(name, ticker, opts) {
    opts = opts || {};
    const a = ticker ? (cfgAssets()[ticker] || S.newAssets[ticker]) : null;
    return `<div class="picker" data-picker="${name}"><input class="in pk-q" autocomplete="off" placeholder="Nom, ticker ou ISIN (ex. Nasdaq, AI, FR0000120073)…" value="${a ? esc(a.short + ' · ' + ticker) : ''}">
      <input type="hidden" class="pk-v" name="${name}" value="${esc(ticker || '')}"><div class="pk-list" hidden></div>
      <div class="pk-sel">${a ? (S.newAssets[ticker] ? `Nouvelle ligne : ${esc(a.name)} · ${esc(a.account)} · ${esc(a.asset_class)}` : `${esc(a.name)} · ${esc(a.account)}`) : (opts.hint || '')}</div></div>`;
  }
  function wirePickers(root, onPick) {
    $$('.picker', root).forEach((pk) => {
      const q = $('.pk-q', pk), list = $('.pk-list', pk), v = $('.pk-v', pk), sel = $('.pk-sel', pk);
      let seq = 0;
      const show = async () => {
        const my = ++seq;
        const { mine, others } = await searchInstruments(q.value);
        if (my !== seq) return;
        const item = (it) => `<div class="pk-item" data-s="${esc(it.s)}"><span><b>${esc(it.n)}</b>${it.full && it.full !== it.n ? ` <span style="color:var(--muted)">${esc(it.full)}</span>` : ''}</span><span class="k">${esc(it.t || '')}</span><small>${esc(it.s)}${it.i ? ' · ' + esc(it.i) : ''}</small></div>`;
        list.innerHTML = (mine.length ? `<div class="pk-head">Mes lignes</div>${mine.map(item).join('')}` : '') +
          (others.length ? `<div class="pk-head">${q.value.trim() ? 'Ajouter une nouvelle ligne' : 'Suggestions'}</div>${others.map(item).join('')}` : '') +
          (!mine.length && !others.length ? '<div class="pk-item"><span>Aucun résultat. Essaie le nom, le mnémonique ou l\'ISIN.</span></div>' : '');
        list.hidden = false;
        list._items = mine.concat(others);
      };
      q.addEventListener('focus', show);
      q.addEventListener('input', () => { v.value = ''; show(); });
      q.addEventListener('blur', () => setTimeout(() => { list.hidden = true; }, 180));
      list.addEventListener('mousedown', (e) => {
        const el = e.target.closest('.pk-item[data-s]'); if (!el) return;
        e.preventDefault();
        const it = (list._items || []).find((x) => x.s === el.dataset.s); if (!it) return;
        if (!cfgAssets()[it.s] && !S.newAssets[it.s]) S.newAssets[it.s] = guessAsset(it);
        const a = cfgAssets()[it.s] || S.newAssets[it.s];
        v.value = it.s;
        q.value = `${a.short} · ${it.s}`;
        sel.innerHTML = S.newAssets[it.s] ? `Nouvelle ligne : ${esc(a.name)} · ${esc(a.account)} · ${esc(a.asset_class)} <a href="#" data-goto="lignes">(ajuster dans « Lignes »)</a>` : `${esc(a.name)} · ${esc(a.account)}`;
        list.hidden = true;
        if (onPick) onPick(it.s, a, pk);
      });
    });
  }
  // nouvelles lignes choisies dans un formulaire : ajoutées à config.json avant les opérations
  function withNewAssets(cfgObj, tickers) {
    let added = 0;
    tickers.forEach((t) => { if (t && !cfgObj.assets[t] && S.newAssets[t]) { cfgObj.assets[t] = S.newAssets[t]; added++; } });
    return added;
  }

  // ------------------------------------------------------------ vues
  function field(label, html, hint) { return `<div class="field"><label>${label}</label>${html}${hint ? `<small>${hint}</small>` : ''}</div>`; }
  const sel = (name, opts, cur) => `<select name="${name}">${opts.map(([v, l]) => `<option value="${esc(v)}" ${String(v) === String(cur) ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
  const assetName = (t) => { const a = cfgAssets()[t] || S.newAssets[t]; return a ? a.short : t; };

  function connectBanner() {
    return token() ? '' : `<div class="msg info">Lecture seule : pour enregistrer des modifications, connecte une fois ton jeton GitHub sur cet appareil. <a href="#" data-goto="connexion">Comment faire</a></div>`;
  }

  // ---- Opérations
  function renderOps() {
    const tx = S.files.tx, e = S.edit && S.edit.kind === 'ops' ? S.edit : null;
    const r = e ? tx.rows[e.index] : { date: today(), type: 'BUY', ticker: '', quantity: '', amount: '', taxes: '', source: 'TR', note: '' };
    const form = S.open || e ? `<div class="panel"><div class="panel-h"><h2>${e ? 'Modifier l\'opération' : 'Nouvelle opération'}</h2></div><div class="panel-b"><form id="f-op" class="form wide">
      ${field('Type', sel('type', TYPES, r.type))}
      ${field('Date d\'exécution', `<input type="date" name="date" value="${esc(r.date)}" required>`)}
      ${field('Ligne', pickerHTML('ticker', r.ticker))}
      ${field('Quantité', `<input type="number" step="any" min="0" name="quantity" value="${esc(r.quantity)}">`, 'Achat : laisse vide pour la calculer au cours du jour')}
      ${field('Montant (€)', `<input type="number" step="0.01" min="0" name="amount" value="${esc(r.amount)}">`, 'montant débité ou crédité par TR')}
      ${field('TTF incluse (€)', `<input type="number" step="0.01" min="0" name="taxes" value="${esc(r.taxes)}">`, 'calculée seule pour les actions françaises')}
      ${field('Source', sel('source', [['TR', 'TR (montant exact)'], ['AUTO', 'Estimé'], ['ESTIME', 'Hypothèse']], r.source))}
      ${field('Note', `<input name="note" value="${esc(r.note)}">`)}
      </form><div class="actions"><button class="btn primary" data-act="save-op">Enregistrer</button><button class="btn" data-act="cancel">Annuler</button>${e ? `<button class="btn danger" data-act="del-op" data-i="${e.index}">Supprimer cette opération</button>` : ''}</div></div></div>` : '';
    const rows = tx.rows.map((x, i) => [x, i]).reverse();
    return `${connectBanner()}${form}
      <div class="panel"><div class="panel-h"><h2>Registre <span class="sub">${tx.rows.length} opérations · touche une ligne pour la modifier</span></h2><button class="btn primary" data-act="new-op">+ Ajouter une opération</button></div>
      <div class="panel-b flush tbl-wrap"><table class="t"><thead><tr><th>Date</th><th>Type</th><th>Ligne</th><th class="n">Quantité</th><th class="n">Montant</th><th class="n">TTF</th><th>Source</th><th>Note</th><th></th></tr></thead><tbody>
      ${rows.map(([x, i]) => `<tr data-row="edit-op" data-i="${i}" style="cursor:pointer"><td>${dShort(x.date)}</td><td>${esc(TYPE_LABEL[x.type] || x.type)}</td><td><div class="name"><span class="dot" style="background:${APP.assetColor(x.ticker)}"></span>${esc(assetName(x.ticker))}</div></td>
        <td class="n">${+x.quantity ? qty(+x.quantity) : (x.type === 'BUY' ? '<small>au cours du jour</small>' : '–')}</td><td class="n">${x.amount ? eur(+x.amount) : '–'}</td><td class="n">${+x.taxes ? eur(+x.taxes) : '–'}</td>
        <td><span class="badge ${x.source === 'AUTO' ? 'b-auto' : x.source === 'ESTIME' ? 'b-est' : 'b-tr'}">${esc(x.source === 'ESTIME' ? 'ESTIMÉ' : x.source)}</span></td>
        <td style="white-space:normal;min-width:180px;color:var(--text-2)">${esc(x.note)}</td>
        <td style="white-space:nowrap"><button class="btn sm" data-act="edit-op" data-i="${i}">Modifier</button> <button class="btn sm danger" data-act="del-op" data-i="${i}">Supprimer</button></td></tr>`).join('')}
      </tbody></table></div></div>`;
  }
  function ttfAuto(form) {
    const t = form.ticker.value, a = cfgAssets()[t] || S.newAssets[t];
    if (!a || !a.ttf || form.type.value !== 'BUY' || form.taxes.dataset.touched) return;
    const amt = numIn(form.amount.value);
    form.taxes.value = amt ? (Math.round(amt * 0.004 / 1.004 * 100) / 100).toFixed(2) : '';
  }
  async function saveOp() {
    const f = $('#f-op');
    const t = f.ticker.value;
    if (!t) { msg('err', 'Choisis une ligne.'); return; }
    if (!f.date.value) { msg('err', 'Indique la date.'); return; }
    const cfg = JSON.parse(JSON.stringify(S.files.config.json));
    const a = cfg.assets[t] || S.newAssets[t];
    const row = { date: f.date.value, account: a.account, type: f.type.value, ticker: t, quantity: fmtNum(numIn(f.quantity.value), 8), amount: fmtNum(numIn(f.amount.value), 2),
      taxes: fmtNum(numIn(f.taxes.value) || 0, 2), source: f.source.value, note: f.note.value };
    if (['BUY', 'SELL', 'DIVIDEND', 'TRANSFER_IN', 'FEE'].includes(row.type) && !(+row.amount > 0)) { msg('err', 'Indique un montant.'); return; }
    if (row.type !== 'BUY' && ['SELL', 'TRANSFER_IN', 'TRANSFER_OUT', 'STAKING', 'BONUS'].includes(row.type) && !(+row.quantity > 0)) { msg('err', 'Indique une quantité.'); return; }
    const rows = S.files.tx.rows.slice();
    const e = S.edit && S.edit.kind === 'ops' ? S.edit : null;
    if (e) rows[e.index] = row; else rows.push(row);
    const changes = [];
    if (withNewAssets(cfg, [t])) changes.push({ key: 'config', path: 'config.json', text: JSON.stringify(cfg, null, 2) + '\n' });
    changes.push({ key: 'tx', path: 'data/transactions.csv', text: toCSV(S.files.tx.head, rows) });
    const label = `${TYPE_LABEL[row.type]} ${a.short} du ${dShort(row.date)}`;
    if (await commit(changes, `Dashboard : ${e ? 'modification' : 'ajout'} ${label}`)) { S.edit = null; S.open = false; render(); }
  }

  // ---- Versement ponctuel
  function renderVersement() {
    const plans = (S.files.config.json.plans || []).filter((p) => p.active !== false && (!p.end || p.end >= today()));
    return `${connectBanner()}<div class="panel"><div class="panel-h"><h2>Versement ponctuel</h2><span class="sub">ex. 600 € reçus à Noël, à répartir entre le PEA et la crypto</span></div><div class="panel-b">
      <form id="f-vers"><div class="form">
        ${field('Date d\'achat', `<input type="date" name="date" value="${today()}" required>`, 'une date future crée un versement « prévu »')}
        ${field('Montant total (€)', `<input type="number" step="1" min="0" name="total" value="">`)}
        ${field('Note', `<input name="note" value="Versement ponctuel">`)}
      </div>
      <div style="margin-top:14px" id="alloc-rows"></div>
      <div class="actions"><button type="button" class="btn" data-act="alloc-add">+ Ligne</button><button type="button" class="btn" data-act="alloc-plans" ${plans.length ? '' : 'disabled'}>Répartir comme mes plans</button><span id="alloc-left" class="note" style="margin:0;align-self:center"></span></div>
      </form>
      <div class="note">Le robot calcule la quantité au cours du jour d'exécution : parts entières pour le PEA (le reliquat n'est pas investi), quantité exacte pour la crypto. Tu pourras ensuite corriger avec les montants TR dans « Opérations ».</div>
      <div class="actions"><button class="btn primary" data-act="save-vers">Enregistrer le versement</button></div></div></div>`;
  }
  function allocRow(t, amt) {
    return `<div class="alloc-row">${field('Ligne', pickerHTML('t', t))}${field('Montant (€)', `<input type="number" step="1" min="0" class="alloc-amt" value="${amt != null ? amt : ''}">`)}<button type="button" class="btn sm danger" data-act="alloc-del" style="margin-bottom:4px">×</button></div>`;
  }
  function addAlloc(t, amt) {
    const box = $('#alloc-rows');
    const div = document.createElement('div');
    div.innerHTML = allocRow(t, amt);
    const el = div.firstElementChild;
    box.appendChild(el);
    wirePickers(el);
    updateLeft();
  }
  function updateLeft() {
    const tot = numIn(($('#f-vers [name=total]') || {}).value) || 0;
    const used = $$('.alloc-amt').reduce((a, i) => a + (numIn(i.value) || 0), 0);
    const el = $('#alloc-left');
    if (el) el.innerHTML = tot ? (Math.abs(tot - used) < 0.01 ? '✓ tout est réparti' : `${tot > used ? 'reste' : 'dépassement de'} <b>${eur(Math.abs(tot - used))}</b>`) : '';
  }
  async function saveVersement() {
    const f = $('#f-vers');
    const date = f.date.value, note = f.note.value || 'Versement ponctuel';
    const parts = $$('#alloc-rows .alloc-row').map((r) => ({ t: $('.pk-v', r).value, amt: numIn($('.alloc-amt', r).value) })).filter((p) => p.t && p.amt > 0);
    if (!date || !parts.length) { msg('err', 'Indique une date et au moins une ligne avec un montant.'); return; }
    const cfg = JSON.parse(JSON.stringify(S.files.config.json));
    const rows = S.files.tx.rows.slice();
    parts.forEach((p) => {
      const a = cfg.assets[p.t] || S.newAssets[p.t];
      rows.push({ date, account: a.account, type: 'BUY', ticker: p.t, quantity: '', amount: p.amt.toFixed(2), taxes: '0', source: 'AUTO', note });
    });
    const changes = [];
    if (withNewAssets(cfg, parts.map((p) => p.t))) changes.push({ key: 'config', path: 'config.json', text: JSON.stringify(cfg, null, 2) + '\n' });
    changes.push({ key: 'tx', path: 'data/transactions.csv', text: toCSV(S.files.tx.head, rows) });
    const tot = parts.reduce((a, p) => a + p.amt, 0);
    if (await commit(changes, `Dashboard : versement ponctuel de ${tot.toFixed(2)} € le ${dShort(date)}`)) render();
  }

  // ---- Plans
  const freqOf = (p) => ((p.days || []).length > 1 ? 'twice' : String(p.every || 1));
  const freqText = (p) => { const f = freqOf(p); const d = (p.days || [p.day || 16]).join(' et '); return (FREQS.find((x) => x[0] === f) || [0, ''])[1] + ` (le ${d})`; };
  function renderPlans() {
    const plans = S.files.config.json.plans || [];
    const e = S.edit && S.edit.kind === 'plan' ? S.edit : null;
    const p = e ? plans[e.index] : { ticker: '', amount: '', every: 1, days: [16], start: today(), end: null, active: true };
    const f = freqOf(p), days = p.days || [16];
    const form = S.open || e ? `<div class="panel"><div class="panel-h"><h2>${e ? 'Modifier le plan' : 'Nouveau plan d\'épargne'}</h2></div><div class="panel-b"><form id="f-plan" class="form wide">
      ${field('Ligne', pickerHTML('ticker', p.ticker))}
      ${field('Montant par exécution (€)', `<input type="number" step="1" min="1" name="amount" value="${esc(p.amount)}">`)}
      ${field('Fréquence', sel('freq', FREQS, f))}
      ${field('Jour d\'exécution', `<input type="number" min="1" max="28" name="day1" value="${days[0]}">`, 'TR : le 2 ou le 16 en général ; jour ouvré suivant si week-end')}
      ${field('2e jour (si 2 fois par mois)', `<input type="number" min="1" max="28" name="day2" value="${days[1] || ''}">`)}
      ${field('Première exécution', `<input type="date" name="start" value="${esc(p.start || today())}">`)}
      ${field('Fin (optionnel)', `<input type="date" name="end" value="${esc(p.end || '')}">`, 'vide = sans fin')}
      <div class="field"><label>État</label><label class="check-row"><input type="checkbox" name="active" ${p.active !== false ? 'checked' : ''}> Actif</label></div>
      </form><div class="actions"><button class="btn primary" data-act="save-plan">Enregistrer</button><button class="btn" data-act="cancel">Annuler</button></div></div></div>` : '';
    return `${connectBanner()}${form}<div class="panel"><div class="panel-h"><h2>Plans d'épargne <span class="sub">config.json</span></h2><button class="btn primary" data-act="new-plan">+ Nouveau plan</button></div>
      <div class="panel-b flush tbl-wrap"><table class="t"><thead><tr><th>Ligne</th><th class="n">Montant</th><th>Fréquence</th><th>Début</th><th>Fin</th><th>État</th><th></th></tr></thead><tbody>
      ${plans.map((x, i) => { const live = x.active !== false && (!x.end || x.end >= today()); return `<tr class="${live ? '' : 'closed'}" data-row="edit-plan" data-i="${i}" style="cursor:pointer"><td><div class="name"><span class="dot" style="background:${APP.assetColor(x.ticker)}"></span>${esc(assetName(x.ticker))}</div></td>
        <td class="n">${eur(+x.amount, 0)}</td><td>${esc(freqText(x))}</td><td>${dShort(x.start)}</td><td>${x.end ? dShort(x.end) : '–'}</td><td><span class="pill ${live ? 'on' : 'off'}">${live ? 'actif' : 'arrêté'}</span></td>
        <td style="white-space:nowrap"><button class="btn sm" data-act="edit-plan" data-i="${i}">Modifier</button> ${live ? `<button class="btn sm" data-act="stop-plan" data-i="${i}">Arrêter</button>` : ''} <button class="btn sm danger" data-act="del-plan" data-i="${i}">Supprimer</button></td></tr>`; }).join('')}
      </tbody></table></div></div>
      <div class="note">« Arrêter » garde l'historique (date de fin = aujourd'hui) ; « Supprimer » retire le plan de la configuration, les achats passés restent dans le registre.</div>`;
  }
  async function savePlan() {
    const f = $('#f-plan');
    const t = f.ticker.value, amount = numIn(f.amount.value);
    if (!t || !(amount > 0)) { msg('err', 'Choisis une ligne et un montant.'); return; }
    const fr = f.freq.value;
    const d1 = Math.min(Math.max(parseInt(f.day1.value, 10) || 16, 1), 28), d2 = parseInt(f.day2.value, 10);
    const plan = { id: (S.edit && S.files.config.json.plans[S.edit.index].id) || `${t.split(/[.-]/)[0].toLowerCase()}-${Date.now().toString(36)}`,
      ticker: t, amount, every: fr === 'twice' ? 1 : parseInt(fr, 10), days: fr === 'twice' && d2 ? [d1, Math.min(Math.max(d2, 1), 28)].sort((a, b) => a - b) : [d1],
      start: f.start.value || today(), end: f.end.value || null };
    if (!f.active.checked) plan.active = false;
    const cfg = JSON.parse(JSON.stringify(S.files.config.json));
    withNewAssets(cfg, [t]);
    if (S.edit && S.edit.kind === 'plan') cfg.plans[S.edit.index] = plan; else cfg.plans.push(plan);
    if (await commit([{ key: 'config', path: 'config.json', text: JSON.stringify(cfg, null, 2) + '\n' }], `Dashboard : plan ${assetName(t)} ${amount} € (${freqText(plan)})`)) { S.edit = null; S.open = false; render(); }
  }

  // ---- Lignes
  function renderLignes() {
    const assets = cfgAssets();
    const e = S.edit && S.edit.kind === 'ligne' ? S.edit : null;
    const t0 = e ? e.ticker : '';
    const a = e ? (assets[t0] || S.newAssets[t0]) : null;
    const classes = Object.keys((S.files.config.json.projection || {}).class_defaults || {}).filter((c) => c !== 'default');
    const form = S.open || e ? `<div class="panel"><div class="panel-h"><h2>${e ? `Modifier ${esc(a.short)}` : 'Nouvelle ligne'}</h2></div><div class="panel-b">
      ${e ? '' : `<div class="field" style="max-width:520px">${field('Chercher l\'instrument', pickerHTML('pick', ''))}</div>`}
      <form id="f-ligne" class="form wide" style="margin-top:10px">
      ${field('Ticker Yahoo', `<input name="ticker" value="${esc(t0)}" ${e ? 'readonly' : ''} placeholder="ex. PUST.PA, BTC-EUR">`, 'Euronext Paris : mnémonique + .PA')}
      ${field('Nom court', `<input name="short" value="${esc(a ? a.short : '')}">`)}
      ${field('Nom complet', `<input name="name" value="${esc(a ? a.name : '')}">`)}
      ${field('Nom chez TR', `<input name="tr_name" value="${esc(a ? a.tr_name || '' : '')}">`)}
      ${field('ISIN', `<input name="isin" value="${esc(a ? a.isin || '' : '')}">`)}
      ${field('Compte', sel('account', [['PEA', 'PEA'], ['CRYPTO', 'Wallet crypto']], a ? a.account : 'PEA'))}
      ${field('Type', sel('kind', [['ETF', 'ETF'], ['Action', 'Action'], ['Crypto', 'Crypto']], a ? a.kind : 'ETF'))}
      ${field('Classe d\'actif', `<input name="asset_class" list="cls-list" value="${esc(a ? a.asset_class : 'Actions Monde (ETF)')}"><datalist id="cls-list">${classes.map((c) => `<option value="${esc(c)}">`).join('')}</datalist>`)}
      ${field('Frais courants (TER, %/an)', `<input type="number" step="0.01" min="0" name="ter" value="${a ? a.ter || 0 : 0.2}">`)}
      ${field('Staking (%/an, crypto)', `<input type="number" step="0.01" min="0" name="staking" value="${a && a.staking ? +(a.staking.rate * 100).toFixed(2) : ''}">`, 'récompenses ajoutées chaque mois')}
      ${field('Actus : mots-clés FR', `<input name="news_fr" value="${esc(a && a.news ? a.news.fr : '')}">`)}
      ${field('Actus : mots-clés EN', `<input name="news_en" value="${esc(a && a.news ? a.news.en : '')}">`)}
      ${field('Répartition géographique', `<input name="zones" value="${esc(a ? Object.entries(a.zones || {}).map(([k, v]) => `${k}:${v}`).join('; ') : '')}">`, 'format « Zone:poids; Zone:poids »')}
      <div class="field"><label>Taxe TTF</label><label class="check-row"><input type="checkbox" name="ttf" ${a && a.ttf ? 'checked' : ''}> Action française soumise à la TTF</label></div>
      ${e ? '' : `${field('Créer un plan (€/mois, optionnel)', `<input type="number" step="1" min="0" name="plan_amount" value="">`)}${field('Jour du plan', `<input type="number" min="1" max="28" name="plan_day" value="16">`)}${field('Première exécution', `<input type="date" name="plan_start" value="${today()}">`)}`}
      </form><div class="actions"><button class="btn primary" data-act="save-ligne">Enregistrer</button><button class="btn" data-act="cancel">Annuler</button></div></div></div>` : '';
    const used = new Set(S.files.tx.rows.map((r) => r.ticker).concat((S.files.config.json.plans || []).map((p) => p.ticker)));
    return `${connectBanner()}${form}<div class="panel"><div class="panel-h"><h2>Lignes suivies <span class="sub">config.json</span></h2><button class="btn primary" data-act="new-ligne">+ Ajouter une ligne</button></div>
      <div class="panel-b flush tbl-wrap"><table class="t"><thead><tr><th>Ligne</th><th>Ticker</th><th>ISIN</th><th>Compte</th><th>Classe</th><th class="n">TER</th><th class="n">Staking</th><th>Actus (FR / EN)</th><th></th></tr></thead><tbody>
      ${Object.entries(assets).map(([t, x]) => `<tr data-row="edit-ligne" data-t="${esc(t)}" style="cursor:pointer"><td><div class="name"><span class="dot" style="background:${APP.assetColor(t)}"></span><div>${esc(x.short)}<small>${esc(x.name)}</small></div></div></td><td>${esc(t)}</td><td>${esc(x.isin || '–')}</td>
        <td>${esc(x.account)}</td><td>${esc(x.asset_class)}</td><td class="n">${x.ter ? pct(x.ter / 100) : '–'}</td><td class="n">${x.staking ? pct(x.staking.rate) : '–'}</td>
        <td style="white-space:normal;min-width:200px;color:var(--text-2)">${esc((x.news || {}).fr || '')} / ${esc((x.news || {}).en || '')}</td>
        <td style="white-space:nowrap"><button class="btn sm" data-act="edit-ligne" data-t="${esc(t)}">Modifier</button> ${used.has(t) ? '' : `<button class="btn sm danger" data-act="del-ligne" data-t="${esc(t)}">Supprimer</button>`}</td></tr>`).join('')}
      </tbody></table></div></div>`;
  }
  function fillLigne(t, a) {
    const f = $('#f-ligne'); if (!f) return;
    f.ticker.value = t; f.short.value = a.short; f.name.value = a.name; f.tr_name.value = a.tr_name || a.name; f.isin.value = a.isin || '';
    f.account.value = a.account; f.kind.value = a.kind; f.asset_class.value = a.asset_class; f.ter.value = a.ter || 0; f.ttf.checked = !!a.ttf;
    f.news_fr.value = (a.news || {}).fr || ''; f.news_en.value = (a.news || {}).en || '';
    f.zones.value = Object.entries(a.zones || {}).map(([k, v]) => `${k}:${v}`).join('; ');
  }
  async function saveLigne() {
    const f = $('#f-ligne');
    const t = f.ticker.value.trim().toUpperCase().replace(/\s+/g, '');
    if (!t || !f.short.value.trim()) { msg('err', 'Ticker et nom court obligatoires.'); return; }
    const cfg = JSON.parse(JSON.stringify(S.files.config.json));
    const prev = cfg.assets[t] || S.newAssets[t] || {};
    const zones = {};
    f.zones.value.split(';').forEach((z) => { const [k, v] = z.split(':'); if (k && k.trim() && numIn(v) != null) zones[k.trim()] = numIn(v); });
    const a = Object.assign({}, prev, {
      name: f.name.value.trim() || f.short.value.trim(), short: f.short.value.trim(), tr_name: f.tr_name.value.trim() || f.name.value.trim(), isin: f.isin.value.trim(),
      account: f.account.value, kind: f.kind.value, asset_class: f.asset_class.value.trim() || 'Actions Monde (ETF)', ter: numIn(f.ter.value) || 0,
      slot: prev.slot || nextSlot(), zones: Object.keys(zones).length ? zones : (f.account.value === 'CRYPTO' ? { 'Crypto (hors zone)': 100 } : { Autres: 100 }),
      ttf: f.ttf.checked, news: { fr: f.news_fr.value.trim() || `"${f.short.value.trim()}"`, en: f.news_en.value.trim() || `"${f.short.value.trim()}"` },
    });
    const st = numIn(f.staking.value);
    if (st) a.staking = Object.assign({}, prev.staking || {}, { rate: st / 100, since: (prev.staking && prev.staking.since) || today() }); else delete a.staking;
    cfg.assets[t] = a;
    const pa = f.plan_amount ? numIn(f.plan_amount.value) : null;
    if (pa) cfg.plans.push({ id: `${t.split(/[.-]/)[0].toLowerCase()}-${Date.now().toString(36)}`, ticker: t, amount: pa, every: 1,
      days: [Math.min(Math.max(parseInt(f.plan_day.value, 10) || 16, 1), 28)], start: f.plan_start.value || today(), end: null });
    delete S.newAssets[t];
    const editing = S.edit && S.edit.kind === 'ligne';
    if (await commit([{ key: 'config', path: 'config.json', text: JSON.stringify(cfg, null, 2) + '\n' }], `Dashboard : ${editing ? 'modification' : 'ajout'} de la ligne ${a.short}${pa ? ` + plan ${pa} €/mois` : ''}`)) { S.edit = null; S.open = false; render(); }
  }

  // ---- Paramètres
  function renderParams() {
    const c = S.files.config.json, P = D.params || {};
    const rows = Object.entries(c.params || {}).map(([k, p]) => {
      const live = P[k] || {};
      return `<tr data-k="${esc(k)}"><td>${esc(p.label || k)}</td>
        <td class="n">${live.live != null ? `${pct(live.live, 2)}<br><small style="color:var(--muted)">${live.live_url ? `<a href="${esc(live.live_url)}" target="_blank" rel="noopener">${esc(live.live_source || '')}</a>` : esc(live.live_source || '')}</small>` : '<small style="color:var(--muted)">pas de source live</small>'}</td>
        <td><select class="in" data-f="mode"><option value="auto" ${p.mode === 'auto' ? 'selected' : ''}>Auto (live)</option><option value="manual" ${p.mode !== 'auto' ? 'selected' : ''}>Manuel</option></select></td>
        <td class="n"><input class="in" type="number" step="0.01" data-f="value" value="${+(p.value * 100).toFixed(3)}"> %</td>
        <td class="n"><b>${live.value != null ? pct(live.value, 2) : pct(p.value, 2)}</b><br><small style="color:var(--muted)">${live.origin || ''}</small></td></tr>`;
    }).join('');
    const stak = Object.entries(c.assets).filter(([, a]) => a.account === 'CRYPTO').map(([t, a]) => `<tr data-t="${esc(t)}"><td>${esc(a.short)}</td>
      <td class="n"><input class="in" type="number" step="0.01" min="0" data-f="rate" value="${a.staking ? +(a.staking.rate * 100).toFixed(3) : ''}"> %</td>
      <td><input class="in" type="date" data-f="since" value="${esc(a.staking ? a.staking.since || '' : '')}"></td></tr>`).join('');
    const cd = (c.projection || {}).class_defaults || {};
    const al = c.alerts || {};
    return `${connectBanner()}<div class="panel"><div class="panel-h"><h2>Taux économiques et fiscaux</h2><span class="sub">« Auto » suit la source officielle à chaque mise à jour ; « Manuel » impose ta valeur</span></div>
      <div class="panel-b flush tbl-wrap"><table class="t" id="t-params"><thead><tr><th>Paramètre</th><th class="n">Valeur live</th><th>Mode</th><th class="n">Valeur manuelle / de secours</th><th class="n">Utilisée</th></tr></thead><tbody>${rows}</tbody></table></div></div>
      <div class="grid">
      <div class="panel c6"><div class="panel-h"><h2>Staking</h2><span class="sub">taux net versé par TR</span></div><div class="panel-b flush"><table class="t" id="t-stak"><thead><tr><th>Crypto</th><th class="n">Taux annuel</th><th>Depuis</th></tr></thead><tbody>${stak}</tbody></table></div></div>
      <div class="panel c6"><div class="panel-h"><h2>Alertes et référence</h2></div><div class="panel-b"><form id="f-misc" class="form">
        ${field('Indice de référence (ticker)', `<input name="bench_t" value="${esc(c.benchmark.ticker)}">`)}
        ${field('Nom de l\'indice', `<input name="bench_l" value="${esc(c.benchmark.label)}">`)}
        ${field('Alerte drawdown (%)', `<input type="number" step="1" name="dd" value="${al.drawdown_pct}">`)}
        ${field('Alerte reliquat de plan (%)', `<input type="number" step="1" name="resid" value="${al.plan_residual_pct}">`)}
        ${field('Alerte poids d\'une ligne (%)', `<input type="number" step="1" name="wmax" value="${al.max_line_weight_pct}">`)}
        ${field('Horizon par défaut du simulateur (ans)', `<input type="number" step="1" min="1" name="years" value="${(c.projection || {}).years || 20}">`)}
      </form></div></div>
      <div class="panel c12"><div class="panel-h"><h2>Hypothèses par défaut du simulateur</h2><span class="sub">par classe d'actif, en %/an</span></div><div class="panel-b flush tbl-wrap"><table class="t" id="t-cd"><thead><tr><th>Classe</th><th class="n">Rendement</th><th class="n">Volatilité</th><th class="n">Dividende</th></tr></thead><tbody>
        ${Object.entries(cd).map(([k, v]) => `<tr data-c="${esc(k)}"><td>${k === 'default' ? 'Autres (par défaut)' : esc(k)}</td><td class="n"><input class="in" type="number" step="0.1" data-f="return" value="${+(v.return * 100).toFixed(2)}"></td>
          <td class="n"><input class="in" type="number" step="0.5" data-f="vol" value="${+(v.vol * 100).toFixed(2)}"></td><td class="n"><input class="in" type="number" step="0.1" data-f="yield" value="${+((v.yield || 0) * 100).toFixed(2)}"></td></tr>`).join('')}
      </tbody></table></div></div></div>
      <div class="actions"><button class="btn primary" data-act="save-params">Enregistrer les paramètres</button></div>`;
  }
  async function saveParams() {
    const cfg = JSON.parse(JSON.stringify(S.files.config.json));
    $$('#t-params tr[data-k]').forEach((tr) => {
      const p = cfg.params[tr.dataset.k];
      p.mode = $('[data-f=mode]', tr).value;
      const v = numIn($('[data-f=value]', tr).value); if (v != null) p.value = Math.round(v * 1000) / 100000;
    });
    $$('#t-stak tr[data-t]').forEach((tr) => {
      const a = cfg.assets[tr.dataset.t]; const r = numIn($('[data-f=rate]', tr).value); const since = $('[data-f=since]', tr).value;
      if (r) a.staking = { rate: Math.round(r * 1000) / 100000, since: since || today() }; else delete a.staking;
    });
    const f = $('#f-misc');
    cfg.benchmark = { ticker: f.bench_t.value.trim() || cfg.benchmark.ticker, label: f.bench_l.value.trim() || cfg.benchmark.label };
    cfg.alerts = { drawdown_pct: numIn(f.dd.value) ?? -10, plan_residual_pct: numIn(f.resid.value) ?? 10, max_line_weight_pct: numIn(f.wmax.value) ?? 90 };
    cfg.projection = cfg.projection || {}; cfg.projection.years = parseInt(f.years.value, 10) || 20;
    $$('#t-cd tr[data-c]').forEach((tr) => {
      const o = cfg.projection.class_defaults[tr.dataset.c];
      ['return', 'vol', 'yield'].forEach((k) => { const v = numIn($(`[data-f=${k}]`, tr).value); if (v != null) o[k] = Math.round(v * 100) / 10000; });
    });
    await commit([{ key: 'config', path: 'config.json', text: JSON.stringify(cfg, null, 2) + '\n' }], 'Dashboard : mise à jour des paramètres');
  }

  // ---- Relevé TR
  function renderReleve() {
    const pos = D.positions.filter((p) => p.open);
    const acc = ['PEA', 'CRYPTO'].map((a) => [a, pos.filter((p) => p.account === a).reduce((s, p) => s + p.value, 0)]);
    return `${connectBanner()}<div class="panel"><div class="panel-h"><h2>Nouveau relevé Trade Republic</h2><span class="sub">recopie les chiffres de l'appli ; le contrôle compare ensuite le registre à ce relevé</span></div>
      <div class="panel-b flush tbl-wrap"><table class="t" id="t-rel"><thead><tr><th>Ligne</th><th class="n">Quantité (TR)</th><th class="n">Prix d'acquisition moyen (TR)</th><th class="n">Valeur (TR)</th><th class="n">Performance % (TR, optionnel)</th></tr></thead><tbody>
      ${pos.map((p) => `<tr data-t="${esc(p.ticker)}"><td><div class="name"><span class="dot" style="background:${APP.assetColor(p.ticker)}"></span>${esc(p.short)}</div></td>
        <td class="n"><input class="in" type="number" step="any" data-f="quantity" value="${p.account === 'PEA' ? Math.round(p.qty) : ''}"></td>
        <td class="n"><input class="in" type="number" step="0.01" data-f="pru" value="${p.pru ? p.pru.toFixed(2) : ''}"></td>
        <td class="n"><input class="in" type="number" step="0.01" data-f="value" value="${p.value.toFixed(2)}"></td>
        <td class="n"><input class="in" type="number" step="0.01" data-f="perf" value=""></td></tr>`).join('')}
      ${acc.map(([a, v]) => `<tr data-acc="${a}" class="total"><td>Total ${a === 'PEA' ? 'PEA' : 'wallet crypto'} (écran Épargne)</td><td></td><td></td><td class="n"><input class="in" type="number" step="0.01" data-f="value" value="${v.toFixed(2)}"></td><td></td></tr>`).join('')}
      </tbody></table></div></div>
      <div class="note">Les valeurs sont pré-remplies avec celles du dashboard : remplace-les par celles affichées dans TR au même moment. Laisse vide ce que TR n'affiche pas.</div>
      <div class="actions"><button class="btn primary" data-act="save-releve">Enregistrer le relevé</button></div>`;
  }
  async function saveReleve() {
    const d = new Date();
    const stamp = `${today()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    const lines = [];
    let tot = 0;
    $$('#t-rel tr[data-t]').forEach((tr) => {
      const g = (k) => clean($(`[data-f=${k}]`, tr).value);
      if (!g('quantity') && !g('pru') && !g('value')) return;
      lines.push([stamp, 'POSITION', tr.dataset.t, g('quantity'), g('pru'), g('value'), '', g('perf'), 'Saisi depuis le dashboard'].join(','));
    });
    $$('#t-rel tr[data-acc]').forEach((tr) => {
      const v = clean($('[data-f=value]', tr).value); if (!v) return; tot += +v;
      lines.push([stamp, 'ACCOUNT', tr.dataset.acc, '', '', v, '', '', 'Saisi depuis le dashboard'].join(','));
    });
    if (tot) lines.push([stamp, 'ACCOUNT', 'TOTAL', '', '', tot.toFixed(2), '', '', 'Saisi depuis le dashboard'].join(','));
    if (!lines.length) { msg('err', 'Rien à enregistrer.'); return; }
    const text = S.files.recon.text.replace(/\n*$/, '\n') + lines.join('\n') + '\n';
    await commit([{ key: 'recon', path: 'data/reconciliation.csv', text }], `Dashboard : relevé Trade Republic du ${stamp}`);
  }

  // ---- Connexion
  function renderConnexion() {
    const t = token();
    return `<div class="panel"><div class="panel-h"><h2>Connexion à GitHub</h2>${t ? `<span class="pill on">jeton enregistré sur cet appareil</span>` : '<span class="pill off">non connecté</span>'}</div><div class="panel-b">
      <p style="margin:0 0 8px">Le dashboard enregistre tes modifications directement dans ton dépôt <b>${esc(OWNER)}/${esc(REPO)}</b>. Il lui faut un <b>jeton d'accès personnel</b>, à créer une seule fois. Il reste dans ce navigateur, jamais dans le dépôt.</p>
      <div class="box"><b>Créer le jeton (2 minutes, depuis le téléphone aussi) :</b><ol class="steps">
        <li>Ouvre <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener">github.com/settings/personal-access-tokens/new</a> (connecté à ton compte).</li>
        <li><b>Token name</b> : <code>pea-tracker dashboard</code> · <b>Expiration</b> : 1 an (ou « No expiration »).</li>
        <li><b>Repository access</b> : <i>Only select repositories</i> → <code>${esc(REPO)}</code>.</li>
        <li><b>Permissions › Repository</b> : <i>Contents</i> = <b>Read and write</b>, <i>Actions</i> = <b>Read and write</b>.</li>
        <li><b>Generate token</b>, copie-le (il commence par <code>github_pat_</code>) et colle-le ci-dessous.</li></ol></div>
      <form id="f-tok" class="form" style="margin-top:12px">${field('Jeton GitHub', `<input type="password" name="tok" autocomplete="off" placeholder="github_pat_…" value="">`)}</form>
      <div class="actions"><button class="btn primary" data-act="save-tok">Enregistrer et tester</button>${t ? '<button class="btn" data-act="test-tok">Tester le jeton actuel</button><button class="btn danger" data-act="forget-tok">Oublier ce jeton sur cet appareil</button>' : ''}</div>
      <div id="tok-res" style="margin-top:10px"></div>
      <div class="note">Sécurité : le jeton ne donne accès qu'à ce dépôt. Si ton téléphone est perdu, supprime-le sur GitHub (Settings › Developer settings › Personal access tokens). Fais la même opération une fois sur chaque appareil.</div></div></div>`;
  }
  async function testToken() {
    const out = $('#tok-res');
    out.innerHTML = '<span class="spin"></span> Test…';
    try {
      const repo = await gh(`/repos/${OWNER}/${REPO}`);
      const ok = repo.permissions && repo.permissions.push;
      let actions = true;
      try { await gh(`/repos/${OWNER}/${REPO}/actions/permissions`); } catch (e) { actions = e.status !== 403 && e.status !== 404; }
      out.innerHTML = ok ? `<div class="msg ok">Connecté : écriture autorisée sur ${esc(repo.full_name)}${actions ? '' : ' ; <b>permission Actions manquante</b>, le recalcul immédiat ne marchera pas (il se fera au prochain passage du robot)'}.</div>`
        : '<div class="msg err">Le jeton lit le dépôt mais ne peut pas écrire : donne la permission « Contents : Read and write ».</div>';
    } catch (e) { out.innerHTML = `<div class="msg err">Échec : ${esc(e.message)}</div>`; }
  }

  // ------------------------------------------------------------ rendu & événements
  const TABS = { ops: renderOps, versement: renderVersement, plans: renderPlans, lignes: renderLignes, params: renderParams, releve: renderReleve, connexion: renderConnexion };
  async function render() {
    $$('#ed-tabs button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.t === S.tab)));
    const body = $('#ed-body');
    if (S.tab !== 'connexion' && !S.files) {
      body.innerHTML = '<div class="empty"><span class="spin"></span> Lecture de tes fichiers sur GitHub…</div>';
      try { await loadFiles(); } catch (e) {
        body.innerHTML = `<div class="msg err">Lecture impossible : ${esc(e.message)}. ${token() ? '' : 'Connecte ton jeton GitHub (onglet Connexion) pour lever la limite de lecture.'}</div>`;
        return;
      }
    }
    body.innerHTML = TABS[S.tab]();
    wirePickers(body, (t, a, pk) => {
      if (pk.dataset.picker === 'pick') fillLigne(t, a);
      if (pk.dataset.picker === 'ticker' && $('#f-op')) ttfAuto($('#f-op'));
    });
    if (S.tab === 'versement') { addAlloc('', null); }
    const fo = $('#f-op');
    if (fo) { fo.amount.addEventListener('input', () => ttfAuto(fo)); fo.type.addEventListener('change', () => ttfAuto(fo)); fo.taxes.addEventListener('input', () => { fo.taxes.dataset.touched = '1'; }); }
    const fv = $('#f-vers');
    if (fv) fv.addEventListener('input', updateLeft);
  }

  $('#ed-tabs').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    S.tab = b.dataset.t; S.edit = null; S.open = false; msg('', ''); render();
  });
  $('#ed-recalc').addEventListener('click', () => recalc());
  $('#ed-body').addEventListener('click', async (e) => {
    const g = e.target.closest('[data-goto]');
    if (g) { e.preventDefault(); S.tab = g.dataset.goto; S.edit = null; S.open = false; render(); return; }
    let b = e.target.closest('[data-act]');
    if (!b) {
      const tr = e.target.closest('tr[data-row]');
      if (!tr || e.target.closest('input,select,a')) return;
      b = { dataset: { act: tr.dataset.row, i: tr.dataset.i, t: tr.dataset.t }, closest: () => null };
    }
    const act = b.dataset.act, i = +b.dataset.i;
    const files = S.files;
    switch (act) {
      case 'new-op': case 'new-plan': case 'new-ligne': S.edit = null; S.open = true; render(); window.scrollTo({ top: 0, behavior: 'smooth' }); break;
      case 'cancel': S.edit = null; S.open = false; render(); break;
      case 'edit-op': S.edit = { kind: 'ops', index: i }; render(); window.scrollTo({ top: 0, behavior: 'smooth' }); break;
      case 'del-op': {
        const r = files.tx.rows[i];
        if (!confirm(`Supprimer ${TYPE_LABEL[r.type] || r.type} ${assetName(r.ticker)} du ${dShort(r.date)} (${r.amount} €) ?`)) return;
        const rows = files.tx.rows.filter((_, j) => j !== i);
        await commit([{ key: 'tx', path: 'data/transactions.csv', text: toCSV(files.tx.head, rows) }], `Dashboard : suppression ${TYPE_LABEL[r.type] || r.type} ${assetName(r.ticker)} du ${dShort(r.date)}`);
        S.edit = null; S.open = false; render(); break;
      }
      case 'save-op': saveOp(); break;
      case 'alloc-add': addAlloc('', null); break;
      case 'alloc-del': b.closest('.alloc-row').remove(); updateLeft(); break;
      case 'alloc-plans': {
        const tot = numIn($('#f-vers [name=total]').value);
        if (!tot) { msg('err', 'Indique d\'abord le montant total.'); return; }
        const plans = (files.config.json.plans || []).filter((p) => p.active !== false && (!p.end || p.end >= today()));
        const by = {}; plans.forEach((p) => { by[p.ticker] = (by[p.ticker] || 0) + (+p.amount); });
        const sum = Object.values(by).reduce((a, b2) => a + b2, 0);
        $('#alloc-rows').innerHTML = '';
        Object.entries(by).forEach(([t, v]) => addAlloc(t, Math.round(tot * v / sum)));
        msg('', ''); break;
      }
      case 'save-vers': saveVersement(); break;
      case 'edit-plan': S.edit = { kind: 'plan', index: i }; render(); window.scrollTo({ top: 0, behavior: 'smooth' }); break;
      case 'stop-plan': {
        const cfg = JSON.parse(JSON.stringify(files.config.json));
        cfg.plans[i].end = today();
        await commit([{ key: 'config', path: 'config.json', text: JSON.stringify(cfg, null, 2) + '\n' }], `Dashboard : arrêt du plan ${assetName(cfg.plans[i].ticker)}`);
        render(); break;
      }
      case 'del-plan': {
        const p = files.config.json.plans[i];
        if (!confirm(`Supprimer le plan ${assetName(p.ticker)} de ${p.amount} € ? (les achats passés restent)`)) return;
        const cfg = JSON.parse(JSON.stringify(files.config.json));
        cfg.plans.splice(i, 1);
        await commit([{ key: 'config', path: 'config.json', text: JSON.stringify(cfg, null, 2) + '\n' }], `Dashboard : suppression du plan ${assetName(p.ticker)}`);
        render(); break;
      }
      case 'save-plan': savePlan(); break;
      case 'edit-ligne': S.edit = { kind: 'ligne', ticker: b.dataset.t }; render(); window.scrollTo({ top: 0, behavior: 'smooth' }); break;
      case 'del-ligne': {
        const t = b.dataset.t;
        if (!confirm(`Retirer la ligne ${assetName(t)} ?`)) return;
        const cfg = JSON.parse(JSON.stringify(files.config.json));
        delete cfg.assets[t];
        await commit([{ key: 'config', path: 'config.json', text: JSON.stringify(cfg, null, 2) + '\n' }], `Dashboard : retrait de la ligne ${t}`);
        render(); break;
      }
      case 'save-ligne': saveLigne(); break;
      case 'save-params': saveParams(); break;
      case 'save-releve': saveReleve(); break;
      case 'save-tok': {
        const v = $('#f-tok').tok.value.trim();
        if (!v) return;
        APP.store.set(TOKEN_KEY, v);
        S.files = null;
        render(); setTimeout(testToken, 50); break;
      }
      case 'test-tok': testToken(); break;
      case 'forget-tok': APP.store.set(TOKEN_KEY, ''); try { localStorage.removeItem(TOKEN_KEY); } catch (er) { /* rien */ } render(); break;
      default: break;
    }
  });

  window.PEA_EDITOR = { render };
  if (APP.state.view === 'donnees') render();
})();
