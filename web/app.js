/* Static web app: same journey as the Streamlit app (blueprint section 8), scoring in the browser via engine.js. */
(function () {
  'use strict';
  const $ = (sel, el) => (el || document).querySelector(sel);
  const esc = (s) => String(s === undefined || s === null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const isNum = (x) => typeof x === 'number' && isFinite(x);
  const main = $('#main');
  let B, E, S;

  const PRIORITY = { demand: 'Market demand', infrastructure: 'Reliable infrastructure', labour: 'Labour', cost: 'Operating cost', growth: 'Growth', policy: 'Policy & ease of doing business' };
  const NEEDS = { power_intensive: 'Power-intensive', digital_first: 'Digital-first', logistics_heavy: 'Logistics-heavy', skilled_labour: 'Skilled labour' };
  const PLOT = { displayModeBar: false, responsive: true };
  const FONT = { family: 'Inter, system-ui, sans-serif', color: '#12161C', size: 13 };
  const SHORT = { demand: 'Demand', infrastructure: 'Infrastructure', outlook: 'Outlook', labour: 'Labour', ecosystem: 'Ecosystem', cost: 'Cost', policy: 'Policy' };
  const SEQ = ['#DCE5FB', '#9DB4F2', '#5B82EA', '#2F5FE0', '#163A9E'];

  // ---------- session (per-viewer convenience only; works without storage)
  const store = {
    get(k) { try { return JSON.parse(sessionStorage.getItem(k)); } catch (e) { return mem[k] || null; } },
    set(k, v) { mem[k] = v; try { sessionStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
    del(k) { delete mem[k]; try { sessionStorage.removeItem(k); } catch (e) { /* ignore */ } },
  };
  const mem = {};
  const getProfile = () => store.get('profile');
  const setProfile = (p) => { store.set('profile', p); store.del('whatif'); };

  // ---------- formatting (mirror of ui/narrative.py)
  function indian(n, dec) {
    dec = dec || 0;
    const neg = n < 0; const s = Math.abs(n).toFixed(dec); let [w, f] = s.split('.');
    if (w.length > 3) { const head = w.slice(0, -3), tail = w.slice(-3); w = head.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + tail; }
    return (neg ? '-' : '') + w + (f ? '.' + f : '');
  }
  function fmt(v, unit) {
    if (!isNum(v)) return 'n/a';
    const u = (unit || '').toLowerCase();
    if (u.startsWith('category:')) {  // ordinal government category, e.g. 'category: 1=Aspirer, 2=Fast Mover, ...'
      const labels = Object.fromEntries(unit.split(':').slice(1).join(':').split(',').map((x) => x.trim().split('=')));
      const lo = Math.floor(v), hi = Math.ceil(v);
      if (lo !== hi) return 'between ' + (labels[String(lo)] || lo) + ' and ' + (labels[String(hi)] || hi);  // a median between two categories
      return labels[String(lo)] || v.toFixed(0);
    }
    if (u.startsWith('of 25')) return (v === Math.trunc(v) ? v.toFixed(0) : v.toFixed(1)) + ' of 25';
    if (u.startsWith('score 0-100')) return v.toFixed(1) + ' / 100';
    if (u.startsWith('rs crore')) return '₹' + indian(v) + ' cr';
    if (u.startsWith('rs') && u.includes('day')) return '₹' + indian(v) + '/day';
    if (u.startsWith('rs')) return '₹' + indian(v);
    if (u.includes('%')) return (Math.abs(v) >= 1 || v === 0 ? v.toFixed(1) : v.toFixed(2)) + '%';
    if (u === 'persons' || u === 'number') return indian(v);
    if (u.includes('usd million')) return 'US$' + indian(v) + ' mn';
    if (Math.abs(v) >= 1000) return indian(v);
    return Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2);
  }
  const SOURCE_TAGS = { dpiit_brap_2024: 'DPIIT BRAP 2024', leads_2025: 'LEADS 2025', niti_epi_2024: 'NITI EPI 2024', startup_ranking_5: 'DPIIT Startup Ranking 5.0', aishe_2023_24: 'AISHE 2023-24', plfs_annual_2023_24: 'PLFS 2023-24 T8' };
  function sourceTag(r) {
    const f = String(r.source_file || '').split(';')[0];
    let t = '';
    if (f.includes('rbi_hsis')) t = 'RBI ' + f.split('/').pop().split('_')[0];
    else if (f.includes('hces')) t = 'HCES 2023-24';
    else if (f.includes('trai')) t = 'TRAI PIR';
    else if (f.includes('registry')) t = 'Forecast model';
    else t = (Object.entries(SOURCE_TAGS).find(([k]) => f.includes(k)) || ['', ''])[1];
    if (r.quality === 'derived') t = t ? t + ', derived' : 'derived';
    return [t, r.period].filter(Boolean).join(' · ');
  }
  const badge = (t, k) => `<span class="badge b-${k || 'grey'}">${esc(t)}</span>`;
  const label = (sid) => B.states[sid] || sid;
  function describe(p) {
    const parts = [S.industries[p.industry].label];
    parts.push(p.current_state && B.states[p.current_state] ? 'from ' + label(p.current_state) : 'from another state');
    if (isNum(p.capital_rs_crore)) parts.push('₹' + p.capital_rs_crore + ' crore');
    if ((p.needs || []).length) parts.push(p.needs.map((n) => NEEDS[n].toLowerCase()).join(', '));
    return parts.join(' · ');
  }
  function modelExplanation(industry) {
    const prof = S.industries[industry]; const t = prof.model_target;
    const reg = B.registry[t || industry] || {};
    if (!t || reg.status !== 'validated')
      return { ok: false, text: 'Ranking only. ' + (reg.reason || prof.target_note || '') + ' The outlook dimension therefore uses historical growth momentum, labelled as such, and no forecast is shown.' };
    const vm = reg.validation_mae, hm = reg.holdout_mae;
    return { ok: true, text: `Next-year forecast of ${reg.target}: ${reg.selected_spec.split('|')[0]} on lagged growth, trained with expanding-window CV (${reg.trained_on}). Validation MAE ${vm.model.toFixed(1)} pp vs ${vm[reg.best_baseline].toFixed(1)} pp for the ${reg.best_baseline === 'mean3' ? '3-year mean' : reg.best_baseline} baseline; untouched FY 2024-25 hold-out MAE ${hm.model.toFixed(1)} pp vs ${Math.min(hm.persistence, hm.mean3).toFixed(1)} pp for the best baseline. The bootstrap interval for the gain crosses zero and the 80% band is about ±12 pp, so read the forecast as a direction, not a promise. Drivers (last year's growth, 3-year mean, national growth) are model attributions, not causes.` };
  }
  // Plain-language reading of the ranking, built from the same relative reasons as the state cards.
  function managerial(res) {
    const parts = [];
    res.ranking.slice(0, 3).forEach((r, i) => {
      const { pos, neg } = E.reasons(res, r.state_id, 1);
      let txt = `${r.state} ${['leads', 'follows', 'is third'][i]} (${r.score.toFixed(1)})`;
      if (pos.length) txt += `. Biggest edge over the other compared states: ${pos[0].meaning} (${pos[0].dimension_label.toLowerCase()})`;
      if (neg.length) txt += `${pos.length ? ';' : '.'} main watch-out: ${neg[0].meaning} (${neg[0].dimension_label.toLowerCase()})`;
      parts.push(txt + '.');
    });
    if (res.ranking.length > 1) {
      const gap = res.ranking[0].score - res.ranking[1].score;
      if (gap < 2) parts.push(`The top two are ${gap.toFixed(1)} points apart, which is within what a modest change of weights can reverse: treat them as a tie and compare on site visits.`);
    }
    parts.push('State averages hide corridor- and district-level differences; use this list to decide where to look next, not where to sign.');
    return parts.join(' ');
  }
  const lowerFirst = (l) => (/^[A-Z]{2}/.test(l) ? l : l.charAt(0).toLowerCase() + l.slice(1));
  const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
  // one strength / watch-out: what the number means, the evidence vs the other compared states, why it matters here
  function reasonHtml(x, kind) {
    const tags = [];
    if (x.priority) tags.push('Your priority: ' + x.dimension_label.toLowerCase());
    x.needs.forEach((n) => tags.push('Your need: ' + NEEDS[n].toLowerCase()));
    return `<div class="why"><span class="${kind}" aria-hidden="true">${kind === 'p' ? '+' : '–'}</span><span><strong>${esc(cap(x.meaning || x.label))}</strong>: ${esc(lowerFirst(x.label))} ${esc(fmt(x.value, x.unit))} vs ${esc(fmt(x.peer_median, x.unit))} median of the other ${x.n_peers} compared state${x.n_peers === 1 ? '' : 's'} <span class="src" style="display:inline">(${esc(sourceTag(x))})</span>. ${esc(x.why)}${tags.length ? `<span class="tags">${tags.map((t) => `<span class="badge b-blue">${esc(t)}</span>`).join('')}</span>` : ''}</span></div>`;
  }
  const NO_POS = 'No indicator in this profile is materially stronger than the other compared states.';
  const NO_NEG = 'No indicator in this profile is materially weaker than the other compared states.';

  // ---------- views
  function home() {
    const m = B.registry.manufacturing || {};
    const fc = m.status === 'validated'
      ? `${badge('Manufacturing: forecast validated', 'blue')}<p class="s14">Next-year real manufacturing GSVA growth. Validation MAE ${m.validation_mae.model.toFixed(1)} pp vs ${m.validation_mae[m.best_baseline].toFixed(1)} pp for the best baseline; hold-out error ${m.holdout_mae.model.toFixed(1)} pp.</p>`
      : `${badge('Manufacturing: ranking only')}<p class="s14">${esc(m.reason || '')}</p>`;
    return `<div class="stack">
      <div class="row">
        <div class="grow"><p class="eyebrow">State screening for established businesses</p>
          <h1 style="font-size:clamp(40px,6vw,64px);line-height:1.02">Where should your business expand next?</h1>
          <p class="lead">Compare evidence-backed state expansion opportunities using public economic data. Every number shows its source table and period.</p>
          <div class="btns" style="margin-top:22px"><a class="btn primary" href="#/profile" style="min-height:52px;padding:0 24px">Start an analysis</a><a class="btn" href="#/methods" style="min-height:52px">How the index works</a></div></div>
        <div class="side card"><p class="eyebrow">What you get</p>
          <p class="s14"><strong>Top three states</strong> with a relative 0–100 index, the dimensions behind it and evidence-linked reasons for and against.</p>
          <p class="s14"><strong>Source beside every number</strong>: table, period, and a raw government file with a recorded checksum.</p>
          <p class="s14" style="margin-bottom:0"><strong>How sure the ranking is</strong>: stability under ±20% weight changes, what would make the runner-up win, and which data are missing or old.</p></div>
      </div>
      <div class="grid" style="--min:220px">
        <div class="card stat"><div class="v">7</div><div class="l">pilot states: Maharashtra, Gujarat, Karnataka, Tamil Nadu, Telangana, Uttar Pradesh, Rajasthan</div></div>
        <div class="card stat"><div class="v">6</div><div class="l">industries: retail, manufacturing, IT &amp; professional services, logistics, healthcare, hospitality</div></div>
        <div class="card stat"><div class="v">FY 2024-25</div><div class="l">latest state accounts (RBI Handbook, 11 Dec 2025, 2011-12 prices)</div></div>
        <div class="card stat"><div class="v">30</div><div class="l">states in the frozen national reference each indicator is ranked against</div></div>
      </div>
      <div class="grid" style="--min:420px">
        <div class="card"><h2 style="margin-bottom:12px">Forecast status by industry</h2>${fc}
          ${badge('Retail · IT · Logistics · Healthcare · Hospitality: ranking only')}<p class="s14" style="margin-bottom:0">No consistent state-level sector output series exists, so no forecast is shown for these.</p></div>
        <div class="caveat"><h2 style="margin-bottom:10px">What this is not</h2>
          <ul style="margin:0;padding-left:20px"><li>Not a probability of commercial success, profit or survival.</li><li>Not site or parcel selection: everything is measured at state level.</li><li>Not financial advice. Use it to decide which states to investigate next.</li><li>Weights are documented design defaults, not learned optima. You can change them.</li></ul></div>
      </div></div>`;
  }

  function profileView() {
    const cur = getProfile() || { industry: 'manufacturing', current_state: 'UP', capital_rs_crore: 8, priorities: [], needs: [], exclude_current: false, states: B.pilots.slice() };
    const p = Object.assign({}, cur);
    const demos = Object.entries(B.demos).map(([k, d]) => `<div class="card"><h3>${esc(d.title)}</h3><p class="s14 muted">${esc(d.blurb)}</p><button class="btn" data-demo="${k}">Run this example</button></div>`).join('');
    main.innerHTML = `<div class="stack"><div><p class="eyebrow">Step 1 of 3</p><h1>Describe the expansion</h1>
      <p class="lead">Five questions. We do not ask for revenue, company documents or anything that identifies you. Nothing you enter leaves your browser.</p></div>
      <section aria-label="Worked examples"><p style="font-weight:600;margin:0 0 10px">Try a worked example</p><div class="grid" style="--min:320px">${demos}</div></section>
      <div class="row"><form class="grow stack" id="pf" style="gap:16px" onsubmit="return false">
        <fieldset><legend>1 · Industry <span style="color:var(--neg)">*</span></legend><div class="grid" id="ind" style="--min:170px;gap:10px"></div><p class="small muted" id="indnote" style="margin:10px 0 0"></p></fieldset>
        <fieldset><legend>2 · Where you are now</legend><div class="grid" style="--min:220px">
          <label class="f">Current state<select id="cur"></select></label>
          <label class="f">Investment capital (₹ crore)<input id="cap" type="number" min="0" step="0.5"><span class="small muted" style="font-weight:400">Context only: no state-level capex or rent data exists, so it does not change scores.</span></label></div>
          <label class="check"><input type="checkbox" id="excl">Leave my current state out of the ranking</label></fieldset>
        <fieldset><legend>3 · Priorities <span class="muted" style="font-weight:400">· choose up to 3 (<span id="npri">0</span> of 3)</span></legend><div class="chips" id="pri"></div><div id="polnote"></div></fieldset>
        <fieldset><legend>4 · Operational needs <span class="muted" style="font-weight:400">· optional</span></legend><div class="chips" id="needs"></div></fieldset>
        <fieldset><legend>5 · States to compare</legend><div class="chips" id="sts"></div><p class="small muted" style="margin:10px 0 0">Scores are ranked against a frozen national reference, so removing a state does not change the others' scores.</p></fieldset>
        <div class="btns"><button class="btn primary" id="go" style="min-height:52px;padding:0 24px">Check data coverage</button><span id="gomsg" class="small" style="color:var(--neg)"></span></div>
      </form>
      <aside class="side card" aria-label="Weights preview" style="align-self:flex-start"><h2>Weights you will use</h2><p class="small muted" id="wnote"></p><div id="wts"></div><div id="wnotes" class="small muted"></div></aside></div></div>`;
    main.querySelectorAll('[data-demo]').forEach((b) => b.addEventListener('click', () => { setProfile(B.demos[b.dataset.demo].profile); location.hash = '#/eligibility'; }));
    const cs = $('#cur');
    cs.innerHTML = B.pilots.map((s) => `<option value="${s}">${esc(label(s))}</option>`).join('') + '<option value="">Other state</option>';
    cs.value = p.current_state || ''; $('#cap').value = isNum(p.capital_rs_crore) ? p.capital_rs_crore : ''; $('#excl').checked = !!p.exclude_current;
    cs.addEventListener('change', () => { p.current_state = cs.value || null; render(); });
    $('#cap').addEventListener('input', (e) => { const v = parseFloat(e.target.value); p.capital_rs_crore = isNum(v) && v >= 0 ? v : null; });
    $('#excl').addEventListener('change', (e) => { p.exclude_current = e.target.checked; });
    function render() {
      $('#ind').innerHTML = Object.entries(S.industries).map(([k, v]) => {
        const tag = v.model_target && (B.registry[v.model_target] || {}).status === 'validated' ? 'Forecast validated' : 'Ranking only';
        return `<button type="button" class="tile" aria-pressed="${p.industry === k}" data-ind="${k}"><strong>${esc(v.label)}</strong><small>${tag}</small></button>`;
      }).join('');
      const prof = S.industries[p.industry];
      $('#indnote').textContent = prof.model_target ? 'A next-year growth forecast is shown where the model is validated and the state has current data.' : 'Ranking only: ' + (prof.target_note || '');
      $('#npri').textContent = p.priorities.length;
      $('#pri').innerHTML = Object.entries(PRIORITY).map(([k, v]) => { const on = p.priorities.includes(k); const dis = !on && p.priorities.length >= 3; return `<button type="button" class="chip" aria-pressed="${on}" ${dis ? 'disabled' : ''} data-pri="${k}">${v}</button>`; }).join('');
      $('#polnote').innerHTML = p.priorities.includes('policy') && S.priorities.policy_note ? `<p class="caveat" style="margin:10px 0 0">${esc(S.priorities.policy_note)}</p>` : '';
      $('#needs').innerHTML = Object.entries(NEEDS).map(([k, v]) => `<button type="button" class="chip" aria-pressed="${p.needs.includes(k)}" data-need="${k}">${v}</button>`).join('');
      $('#sts').innerHTML = B.pilots.map((s) => `<button type="button" class="chip" aria-pressed="${p.states.includes(s)}" data-st="${s}">${esc(label(s))}</button>`).join('');
      $('#excl').disabled = !p.current_state;
      const ew = E.effectiveWeights(p); const base = prof.weights; const tot = Object.values(base).reduce((a, b) => a + b, 0);
      $('#wnote').textContent = prof.label + ' defaults (v3), adjusted by your choices. Design defaults, not learned optima.';
      $('#wts').innerHTML = Object.entries(ew.w).map(([d, v]) => `<div class="s14" style="display:flex;justify-content:space-between"><span>${esc(S.dimensions[d].label)}</span><span class="mono">${(100 * v).toFixed(1)}%</span></div><div class="wbar"><div class="${Math.abs(v - base[d] / tot) > 1e-6 ? 'up' : ''}" style="width:${(100 * v).toFixed(1)}%"></div></div>`).join('');
      $('#wnotes').innerHTML = ew.notes.map((n) => `<p style="margin:6px 0">· ${esc(n)}</p>`).join('');
      $('#go').disabled = p.states.length < 2;
      $('#gomsg').textContent = p.states.length < 2 ? 'Choose at least two states to compare.' : '';
    }
    $('#pf').addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.dataset.ind) p.industry = b.dataset.ind;
      else if (b.dataset.pri) { const k = b.dataset.pri; p.priorities = p.priorities.includes(k) ? p.priorities.filter((x) => x !== k) : (p.priorities.length < 3 ? p.priorities.concat(k) : p.priorities); }
      else if (b.dataset.need) { const k = b.dataset.need; p.needs = p.needs.includes(k) ? p.needs.filter((x) => x !== k) : p.needs.concat(k); }
      else if (b.dataset.st) { const k = b.dataset.st; p.states = p.states.includes(k) ? p.states.filter((x) => x !== k) : B.pilots.filter((x) => x === k || p.states.includes(x)); }
      else if (b.id === 'go') { if (p.states.length >= 2) { setProfile(Object.assign({}, p, { exclude_current: p.exclude_current && !!p.current_state })); location.hash = '#/eligibility'; } return; }
      else return;
      render();
    });
    render();
  }

  function needProfile() {
    const p = getProfile();
    if (!p) main.innerHTML = `<div class="stack"><p class="lead">Start with your business profile.</p><div><a class="btn primary" href="#/profile">Go to the profile</a></div></div>`;
    return p;
  }

  function eligibilityView() {
    const p = needProfile(); if (!p) return;
    const prof = S.industries[p.industry];
    const res = E.score(p, { stability: false });
    const reg = B.registry[prof.model_target || ''] || {}; const validated = reg.status === 'validated';
    const compared = p.states.filter((s) => !(p.exclude_current && s === p.current_state));
    if (res.message) {
      main.innerHTML = `<div class="stack"><div><p class="eyebrow">Step 2 of 3 · ${esc(describe(p))}</p><h1>No ranking can be produced</h1></div><div class="caveat">${esc(res.message)}</div>
        <ul>${res.excluded.map((r) => `<li><strong>${esc(r.state)}</strong>: ${esc(r.reason)}</li>`).join('')}</ul><div><a class="btn" href="#/profile">Edit profile</a></div></div>`;
      return;
    }
    const exSet = new Set(res.excluded.map((r) => r.state_id));
    const status = compared.map((sid) => {
      if (exSet.has(sid)) return { sid, st: 'Excluded', why: res.excluded.find((r) => r.state_id === sid).reason };
      const hasFc = validated && res.indicators.some((r) => r.state_id === sid && r.indicator.startsWith('forecast') && isNum(r.score));
      if (hasFc) return { sid, st: 'Forecast + ranking', why: 'validated ' + prof.model_target + ' model' };
      if (validated) {
        const last = res.indicators.find((r) => r.state_id === sid && r.indicator === 'momentum_manufacturing');
        return { sid, st: 'Ranking only', why: `state accounts end in ${last ? last.period : 'an earlier year'}, so no ${reg.forecast_fy} forecast can be issued` };
      }
      return { sid, st: 'Ranking only', why: reg.reason || prof.target_note || 'no defensible sector target' };
    });
    // industries without a forecast model: every state is ranking-only by design, so don't show an empty forecast tile
    const tileSet = prof.model_target ? [['Forecast + ranking'], ['Ranking only'], ['Excluded']] : [['Ranking only'], ['Excluded']];
    const tiles = tileSet.map(([lab]) => {
      const sub = status.filter((x) => x.st === lab);
      return `<div class="card stat"><div class="v">${sub.length}</div><div class="l">${lab}${sub.length ? ': ' + sub.map((x) => esc(label(x.sid))).join(', ') : ''}</div></div>`;
    }).join('');
    const gaps = res.ranking.filter((r) => r.disclosure).map((r) => `${r.state}: ${r.disclosure}`);
    const dims = Object.keys(prof.indicators);
    const rows = compared.map((sid) => {
      const g = res.indicators.filter((r) => r.state_id === sid);
      const cells = dims.map((d) => { const gd = g.filter((r) => r.dimension === d); const o = gd.filter((r) => isNum(r.score)).length; return `<td class="num ${o !== gd.length ? 'gap' : ''}">${o}/${gd.length}</td>`; }).join('');
      const per = g.filter((r) => /^momentum_/.test(r.indicator)).map((r) => r.period).sort().pop() || '';
      const st = status.find((x) => x.sid === sid).st;
      return `<tr><th scope="row">${esc(label(sid))}</th><td>${badge(st, st === 'Forecast + ranking' ? 'blue' : st === 'Excluded' ? 'amber' : 'grey')}</td>${cells}<td class="num ${per && per < '2024' ? 'gap' : ''}">${esc(per)}</td></tr>`;
    }).join('');
    const vint = {};
    res.indicators.filter((r) => r.observed).forEach((r) => { (vint[r.label] = vint[r.label] || { src: new Set(), per: new Set() }); vint[r.label].src.add(sourceTag(r).split(' · ')[0]); vint[r.label].per.add(String(r.period)); });
    const vrows = Object.entries(vint).sort().map(([k, v]) => { const ps = [...v.per].sort(); return `<tr><td>${esc(k)}</td><td>${esc([...v.src].join(', '))}</td><td class="num">${esc(ps.length > 1 ? ps[0] + ' to ' + ps[ps.length - 1] : ps[0])}</td></tr>`; }).join('');
    main.innerHTML = `<div class="stack"><div><p class="eyebrow">Step 2 of 3 · ${esc(describe(p))}</p><h1>${res.ranking.length} of ${compared.length} states can be compared</h1>
      <p class="lead">For ${esc(prof.label.toLowerCase())}, each state needs at least one observed official indicator in: <strong>${prof.mandatory_dimensions.map((d) => esc(S.dimensions[d].label.toLowerCase())).join(', ')}</strong>. Nothing is filled in where data are missing.</p></div>
      <div class="grid" style="--min:240px">${tiles}</div>
      ${gaps.length ? `<div class="caveat" role="note"><strong>${gaps.length} gap(s) disclosed, not filled</strong><br>${gaps.map(esc).join(' · ')}</div>` : ''}
      ${!prof.model_target ? `<div class="note"><strong>No forecast is offered for ${esc(prof.label.toLowerCase())}.</strong> ${esc(prof.target_note || '')} States are compared on the ranking index only; the outlook dimension uses historical growth momentum.</div>` : ''}
      ${!validated && prof.model_target ? `<div class="note">Forecast unavailable: ${esc(reg.reason || 'model not validated')}.</div>` : ''}
      <section><h2 style="margin-bottom:12px">Indicator coverage</h2><div class="tbl-wrap"><table><thead><tr><th>State</th><th>Status</th>${dims.map((d) => `<th class="num">${esc(S.dimensions[d].label)}</th>`).join('')}<th class="num">Latest state accounts</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="small muted">observed / indicators in the profile. Amber = an indicator is not published for that state; weights within the dimension are renormalised over what is observed.</p>
      <details><summary>Why each state has this status</summary><ul>${status.map((x) => `<li><strong>${esc(label(x.sid))}</strong> · ${esc(x.st)}: ${esc(x.why)}</li>`).join('')}</ul></details></section>
      <section><h2 style="margin-bottom:12px">Source vintages used</h2><div class="tbl-wrap"><table><thead><tr><th>Indicator</th><th>Source</th><th class="num">Period(s)</th></tr></thead><tbody>${vrows}</tbody></table></div></section>
      <div class="btns"><a class="btn primary" href="#/results" style="min-height:52px;padding:0 24px">See the ranking</a><a class="btn" href="#/profile">Edit profile</a></div></div>`;
  }

  function cellShade(v) {
    if (!isNum(v)) return ['#F5F6F8', '#4A5361'];
    return v >= 80 ? ['#163A9E', '#FFFFFF'] : v >= 60 ? ['#C9D6F8', '#12161C'] : v >= 40 ? ['#EEF0F3', '#12161C'] : ['#FFE7C2', '#5C3B00'];
  }

  function resultsView() {
    const p = needProfile(); if (!p) return;
    const base = E.score(p);
    if (base.message) { main.innerHTML = `<div class="stack"><h1>No ranking</h1><div class="caveat">${esc(base.message)}</div><div><a class="btn" href="#/profile">Edit profile</a></div></div>`; return; }
    const eff = E.effectiveWeights(Object.assign({}, p, { states: p.states }));
    let whatif = store.get('whatif');
    const run = () => (whatif ? E.score(Object.assign({}, p, { dimension_weights: whatif }), { stability: false }) : base);
    const stab = {}; (base.stability || []).forEach((x) => { stab[x.state_id] = x; });
    const ex = modelExplanation(p.industry);

    main.innerHTML = `<div class="stack"><div><p class="eyebrow">Step 3 of 3 · ${esc(describe(p))}</p><h1 id="headline"></h1>
        <p class="lead">Index = weighted mean of national percentile scores (0–100) against 30 states. <strong>It is a relative screening score, not a probability of success.</strong> <span id="wi"></span></p>
        <div class="btns" style="margin-top:14px"><button class="btn" id="csv">Download CSV</button><button class="btn dark" id="print">Print / save PDF brief</button></div></div>
      <section aria-label="Top three states" class="grid" style="--min:320px" id="top3"></section>
      <div class="row"><section class="grow card"><h2>Pilot states on the map</h2><div id="map" class="chart" style="height:520px" role="img" aria-label="Map of India with the compared states shaded by index"></div>
          <p class="small muted" style="margin:6px 0 0">Hover or tap a state for comparable macro indicators. Grey = not compared. Boundaries: geoBoundaries ADM1 (CC BY 4.0), not an official Survey of India map.</p></section>
        <section class="side card"><label class="f">Look at a state<select id="sel"></select></label><div id="selhead" style="margin-top:12px"></div><div id="dimbars" class="chart" style="height:260px"></div></section></div>
      <section><h2 style="margin-bottom:12px">Comparison matrix</h2><div class="tbl-wrap" id="matrix"></div>
        <details style="margin-top:12px"><summary>All indicators: raw value, period, source and percentile score</summary><div class="tbl-wrap" id="allind" style="max-height:520px;overflow:auto"></div></details></section>
      <div class="row"><section class="grow card"><h2>What if you weight it differently?</h2><p class="small muted">Sliders set relative weights; they are renormalised to 100%. Starting values include your priorities. The ranking updates live.</p><div id="sliders"></div>
          <div class="btns"><button class="btn" id="reset">Reset</button></div><div id="moved" style="margin-top:12px"></div></section>
        <section class="side card"><h2>How stable is this ranking?</h2><p class="small muted">500 random re-weightings of your profile weights, each dimension moved ±20%. Bar = share keeping the same rank; brackets = best–worst rank seen.</p><div id="stab" class="chart" style="height:300px"></div><div class="note" id="counter"></div></section></div>
      <section class="card"><div class="btns" style="justify-content:space-between"><h2>Compare two states</h2><div class="btns"><label class="sr" for="ca">First state</label><select id="ca" style="width:auto"></select><label class="sr" for="cb">Second state</label><select id="cb" style="width:auto"></select></div></div>
        <div id="cmp" class="chart" style="height:340px"></div><div class="tbl-wrap" id="cmptbl"></div></section>
      <div class="grid" style="--min:420px"><section class="card"><h2 style="margin-bottom:8px">Model explanation</h2><p class="s14">${esc(ex.text)}</p></section>
        <section class="card"><h2 style="margin-bottom:8px">Managerial interpretation</h2><p class="s14" id="mgr"></p></section></div>
      <details><summary>How your choices and the data gaps were handled</summary><ul id="notes" class="s14"></ul></details></div>`;

    const dims = Object.keys(base.dim_weights);
    const start = whatif || Object.fromEntries(Object.entries(eff.w).map(([d, v]) => [d, +(100 * v).toFixed(1)]));
    $('#sliders').innerHTML = dims.map((d) => `<div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(120px,200px) 54px;gap:12px;align-items:center"><label for="w-${d}" class="s14">${esc(S.dimensions[d].label)}</label><input type="range" id="w-${d}" min="0" max="60" step="0.5" value="${start[d]}"><span class="mono s14" id="wv-${d}" style="text-align:right"></span></div>`).join('');

    function draw() {
      const res = run(); const rk = res.ranking; const top = rk.slice(0, 3);
      $('#headline').textContent = top[0].state + ' leads' + (top.length >= 3 ? `, ${top[1].state} and ${top[2].state} follow` : top.length === 2 ? `, ${top[1].state} follows` : '');
      $('#wi').textContent = whatif ? 'Weights changed in “What if” below.' : '';
      const fcRows = {}; res.indicators.filter((r) => r.indicator.startsWith('forecast')).forEach((r) => { fcRows[r.state_id] = r; });
      $('#top3').innerHTML = top.map((r, i) => {
        const { pos, neg } = E.reasons(res, r.state_id, 2);
        let b = badge('Data confidence: ' + r.confidence, r.confidence === 'High' ? 'blue' : 'amber');
        if (!whatif && stab[r.state_id]) b += badge(`Same rank in ${Math.floor(100 * stab[r.state_id].share_same_rank)}% of ±20% re-weightings`);
        let fc;
        if (ex.ok) {
          const f = fcRows[r.state_id];
          fc = f && isNum(f.value)
            ? `<div class="fc"><span class="src">Forecast · manufacturing real GSVA growth, ${esc(f.period)}</span><span class="mono" style="font-size:18px">${(f.value >= 0 ? '+' : '') + f.value.toFixed(1)}%</span><span class="src">${esc(f.note)}</span></div>`
            : `<div class="fc"><span class="src">Forecast</span><strong>Not available</strong><span class="src">State accounts end before the latest year, so no forecast can be issued. Ranking only.</span></div>`;
        } else fc = `<div class="fc"><span class="src">Forecast</span><strong>Ranking only</strong><span class="src">No validated sector target for this industry.</span></div>`;
        return `<article class="card ${i === 0 ? 'lead-card' : ''}"><div style="display:flex;justify-content:space-between;gap:12px"><div><span class="mono small muted">#${r.rank}</span><h2 style="font-size:26px">${esc(r.state)}</h2></div><div style="text-align:right"><span class="score">${r.score.toFixed(1)}</span><span class="src">index / 100</span></div></div>
          <div style="margin-top:12px">${b}</div>${fc}
          <p class="s14" style="margin:8px 0 2px;font-weight:600;color:var(--blue-dark)">Why it ranks here</p>${pos.length ? pos.map((x) => reasonHtml(x, 'p')).join('') : `<p class="small muted">${NO_POS}</p>`}
          <p class="s14" style="margin:10px 0 2px;font-weight:600;color:var(--neg)">Watch-outs</p>${neg.length ? neg.map((x) => reasonHtml(x, 'n')).join('') : `<p class="small muted">${NO_NEG}</p>`}
          ${r.disclosure ? `<div class="caveat small" style="margin-top:10px">${esc(r.disclosure)}</div>` : ''}</article>`;
      }).join('');
      // map
      const facts = {};
      ['per_capita_nsdp_real', 'per_capita_power_availability', 'nh_km_per_lakh_pop', 'internet_subs_per_100'].forEach((c) => B.indicators.filter((x) => x.c === c).forEach((x) => { (facts[x.s] = facts[x.s] || []).push(`${S.indicators[c].label}: ${fmt(x.v, x.u)} (${x.p})`); }));
      const ids = rk.map((r) => r.state_id); const others = GEO.features.map((f) => f.id).filter((x) => !ids.includes(x));
      if (window.Plotly) {
        Plotly.react('map', [
          { type: 'choropleth', geojson: GEO, featureidkey: 'id', locations: others, z: others.map(() => 0), colorscale: [[0, '#E6E9EF'], [1, '#E6E9EF']], showscale: false, hoverinfo: 'skip', marker: { line: { color: '#fff', width: 0.6 } } },
          { type: 'choropleth', geojson: GEO, featureidkey: 'id', locations: ids, z: rk.map((r) => r.score), zmin: 40, zmax: 70, colorscale: SEQ.map((c, i) => [i / (SEQ.length - 1), c]), marker: { line: { color: '#fff', width: 1.2 } },
            text: rk.map((r) => [`<b>${r.state}</b>`, `Index ${r.score.toFixed(1)} / 100 · rank ${r.rank}`].concat(facts[r.state_id] || []).join('<br>')), hovertemplate: '%{text}<extra></extra>',
            colorbar: { title: { text: 'Index', font: FONT }, thickness: 10, len: 0.55, outlinewidth: 0, tickfont: { family: 'IBM Plex Mono, monospace', size: 11, color: '#4A5361' } } },
        ], { geo: { visible: false, bgcolor: '#fff', projection: { type: 'mercator' }, lonaxis: { range: [67.5, 89.5] }, lataxis: { range: [7.5, 31.5] } }, margin: { l: 0, r: 0, t: 0, b: 0 }, paper_bgcolor: '#fff', font: FONT, hoverlabel: { bgcolor: '#fff', bordercolor: '#DCE0E6', font: FONT } }, PLOT);
      }
      // selected state
      const sel = $('#sel'); const prev = sel.value; sel.innerHTML = rk.map((r) => `<option value="${r.state_id}">${esc(r.state)}</option>`).join(''); if (ids.includes(prev)) sel.value = prev;
      drawSel(res);
      // matrix
      $('#matrix').innerHTML = `<table><thead><tr><th>Rank · state</th><th class="num">Index</th>${dims.map((d) => `<th class="num">${esc(S.dimensions[d].label)}<br><span class="mono" style="color:var(--blue)">${(100 * res.dim_weights[d]).toFixed(0)}%</span></th>`).join('')}</tr></thead><tbody>${rk.map((r) => `<tr><th scope="row">${r.rank} · ${esc(r.state)}</th><td class="num"><strong>${r.score.toFixed(1)}</strong></td>${dims.map((d) => { const v = r['dim_' + d]; const c = cellShade(v); return `<td class="num"><span class="cell" style="background:${c[0]};color:${c[1]}">${isNum(v) ? v.toFixed(1) : 'n/a'}</span></td>`; }).join('')}</tr>`).join('')}</tbody></table>`;
      const order = rk.map((r) => r.state);
      const byInd = {}; res.indicators.forEach((r) => { const k = r.dimension + '|' + r.label; (byInd[k] = byInd[k] || {})[r.state] = r; });
      $('#allind').innerHTML = `<table><thead><tr><th>Dimension</th><th>Indicator</th>${order.map((s) => `<th class="num">${esc(s)}</th>`).join('')}</tr></thead><tbody>${Object.entries(byInd).map(([k, v]) => { const [d, l] = k.split('|'); return `<tr><td class="small">${esc(S.dimensions[d].label)}</td><td>${esc(l)}</td>${order.map((s) => { const r = v[s]; return r && r.observed ? `<td class="num" title="${esc(sourceTag(r))}">${esc(fmt(r.value, r.unit))}<span class="src">${esc(sourceTag(r))} · pct ${Math.round(r.score)}</span></td>` : '<td class="num muted">not available</td>'; }).join('')}</tr>`; }).join('')}</tbody></table>`;
      // compare
      const ca = $('#ca'), cb = $('#cb'); const pa = ca.value, pb = cb.value;
      ca.innerHTML = rk.map((r) => `<option value="${r.state_id}">${esc(r.state)}</option>`).join(''); ca.value = ids.includes(pa) ? pa : ids[0];
      cb.innerHTML = rk.filter((r) => r.state_id !== ca.value).map((r) => `<option value="${r.state_id}">${esc(r.state)}</option>`).join(''); cb.value = ids.includes(pb) && pb !== ca.value ? pb : rk.find((r) => r.state_id !== ca.value).state_id;
      drawCmp(res);
      // what-if
      dims.forEach((d) => { const tot = dims.reduce((a, x) => a + parseFloat($('#w-' + x).value), 0) || 1; $('#wv-' + d).textContent = (100 * parseFloat($('#w-' + d).value) / tot).toFixed(1) + '%'; });
      if (whatif) {
        const was = {}; base.ranking.forEach((r) => { was[r.state_id] = r.rank; });
        const ch = rk.filter((r) => was[r.state_id] !== r.rank).map((r) => `${r.state} ${was[r.state_id] > r.rank ? 'up' : 'down'} ${Math.abs(was[r.state_id] - r.rank)}`);
        $('#moved').innerHTML = `<div class="note">Rank changes vs your profile weights: ${ch.length ? esc(ch.join(', ')) : 'none'}</div>`;
      } else $('#moved').innerHTML = '';
      // stability (base weights) + counter
      if (window.Plotly && base.stability) {
        const st = base.stability;
        Plotly.react('stab', [{ type: 'bar', orientation: 'h', x: st.map((x) => 100 * x.share_same_rank), y: st.map((x) => x.best_rank === x.worst_rank ? `${x.state} (rank ${x.best_rank})` : `${x.state} (rank ${x.best_rank}–${x.worst_rank})`),
          marker: { color: '#1F4FD1', line: { color: '#fff', width: 2 } }, width: 0.55, text: st.map((x) => Math.floor(100 * x.share_same_rank) + '%'), textposition: 'outside', cliponaxis: false,
          textfont: { family: 'IBM Plex Mono, monospace', color: '#12161C' }, hovertemplate: '%{y}: same rank in %{x:.0f}% of draws<extra></extra>' }],
        { xaxis: { range: [0, 125], ticksuffix: '%', tickvals: [0, 50, 100], gridcolor: '#EEF0F3', tickfont: { color: '#4A5361' } }, yaxis: { autorange: 'reversed', automargin: true }, margin: { l: 8, r: 36, t: 8, b: 28 }, paper_bgcolor: '#fff', plot_bgcolor: '#fff', font: FONT, showlegend: false }, PLOT);
      }
      $('#counter').innerHTML = res.counter ? `<strong>Could the runner-up win?</strong><br>${esc(res.counter)}` : '';
      $('#mgr').textContent = managerial(res);
      const lines = res.notes.concat(res.ranking.filter((r) => r.disclosure).map((r) => `${r.state}: ${r.disclosure}`), res.excluded.map((r) => `${r.state} excluded: ${r.reason}`));
      $('#notes').innerHTML = lines.length ? lines.map((n) => `<li>${esc(n)}</li>`).join('') : '<li>No adjustments or gaps.</li>';
      CURRENT = res;
    }
    function drawSel(res) {
      const sid = $('#sel').value; const r = res.ranking.find((x) => x.state_id === sid);
      $('#selhead').innerHTML = `<div style="display:flex;justify-content:space-between;align-items:baseline"><h3 style="font-size:22px">${esc(r.state)}</h3><span class="score" style="font-size:28px">${r.score.toFixed(1)}</span></div><span class="src">rank ${r.rank} · ${esc(r.data_confidence)}</span>`;
      if (!window.Plotly) return;
      const vals = dims.map((d) => r['dim_' + d]);
      Plotly.react('dimbars', [{ type: 'bar', orientation: 'h', x: vals, y: dims.map((d) => `${SHORT[d]} · ${(100 * res.dim_weights[d]).toFixed(0)}%`), marker: { color: '#1F4FD1', line: { color: '#fff', width: 2 } }, width: 0.55,
        text: vals.map((v) => (isNum(v) ? v.toFixed(0) : 'n/a')), textposition: 'outside', cliponaxis: false, textfont: { family: 'IBM Plex Mono, monospace', color: '#12161C' }, hovertemplate: '%{y}: %{x:.1f} / 100<extra></extra>' }],
      { xaxis: { range: [0, 110], gridcolor: '#EEF0F3', tickfont: { color: '#4A5361' } }, yaxis: { autorange: 'reversed', automargin: true }, margin: { l: 8, r: 8, t: 8, b: 28 }, paper_bgcolor: '#fff', plot_bgcolor: '#fff', font: FONT, showlegend: false }, PLOT);
    }
    function drawCmp(res) {
      const a = $('#ca').value, b = $('#cb').value; const rk = res.ranking; const ra = rk.find((r) => r.state_id === a), rb = rk.find((r) => r.state_id === b);
      if (window.Plotly) {
        const tr = (r, color) => ({ type: 'bar', orientation: 'h', name: r.state, x: dims.map((d) => r['dim_' + d]), y: dims.map((d) => S.dimensions[d].label), marker: { color, line: { color: '#fff', width: 2 } },
          text: dims.map((d) => (isNum(r['dim_' + d]) ? r['dim_' + d].toFixed(0) : 'n/a')), textposition: 'outside', cliponaxis: false, textfont: { family: 'IBM Plex Mono, monospace', color: '#12161C' }, hovertemplate: '%{fullData.name} · %{y}: %{x:.1f}<extra></extra>' });
        Plotly.react('cmp', [tr(ra, '#1F4FD1'), tr(rb, '#B5700B')], { barmode: 'group', bargap: 0.3, bargroupgap: 0.08, xaxis: { range: [0, 112], gridcolor: '#EEF0F3', tickfont: { color: '#4A5361' } }, yaxis: { autorange: 'reversed', automargin: true },
          legend: { orientation: 'h', y: 1.1, x: 0 }, margin: { l: 8, r: 8, t: 30, b: 28 }, paper_bgcolor: '#fff', plot_bgcolor: '#fff', font: FONT }, PLOT);
      }
      const labs = [...new Set(res.indicators.map((r) => r.label))];
      const cell = (sid, l) => { const r = res.indicators.find((x) => x.state_id === sid && x.label === l); return r && r.observed ? `${esc(fmt(r.value, r.unit))} <span class="src">${esc(sourceTag(r))}</span>` : '<span class="muted">not available</span>'; };
      $('#cmptbl').innerHTML = `<table><thead><tr><th>Indicator</th><th class="num">${esc(ra.state)}</th><th class="num">${esc(rb.state)}</th></tr></thead><tbody>${labs.map((l) => `<tr><td>${esc(l)}</td><td class="num">${cell(a, l)}</td><td class="num">${cell(b, l)}</td></tr>`).join('')}</tbody></table>`;
    }
    let CURRENT = base;
    $('#sel').addEventListener('change', () => drawSel(CURRENT));
    $('#ca').addEventListener('change', () => { draw(); });
    $('#cb').addEventListener('change', () => drawCmp(CURRENT));
    let tmr;
    dims.forEach((d) => $('#w-' + d).addEventListener('input', () => {
      clearTimeout(tmr);
      tmr = setTimeout(() => { const w = {}; dims.forEach((x) => { w[x] = parseFloat($('#w-' + x).value); }); whatif = Object.values(w).some((v) => v > 0) ? w : null; store.set('whatif', whatif); draw(); }, 120);
    }));
    $('#reset').addEventListener('click', () => { whatif = null; store.del('whatif'); dims.forEach((d) => { $('#w-' + d).value = (100 * eff.w[d]).toFixed(1); }); draw(); });
    $('#csv').addEventListener('click', () => downloadCsv(CURRENT, p));
    $('#print').addEventListener('click', () => { document.querySelectorAll('details').forEach((d) => { d.open = true; }); window.print(); });
    draw();
  }

  function downloadCsv(res, p) {
    const q = (v) => { const s = v === undefined || v === null || (typeof v === 'number' && !isFinite(v)) ? '' : String(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    const rk = {}; res.ranking.forEach((r) => { rk[r.state_id] = r; });
    const head = ['state', 'rank', 'suitability_index', 'dimension', 'indicator', 'value', 'unit', 'period', 'quality', 'source_file', 'source_url', 'national_percentile_score', 'indicator_weight_in_dimension', 'dimension_weight', 'contribution_to_index', 'caveat', 'note'];
    const rows = res.indicators.slice().sort((a, b) => rk[a.state_id].rank - rk[b.state_id].rank || a.dimension.localeCompare(b.dimension)).map((r) =>
      [r.state, rk[r.state_id].rank, rk[r.state_id].score, r.dimension, r.label, r.value, r.unit, r.period, r.quality, r.source_file, r.url, r.score, r.w_ind_eff, r.dim_weight, r.contribution, r.proxy, r.note].map(q).join(','));
    const meta = [`# India Expansion Intelligence export, ${new Date().toISOString().slice(0, 10)}`, `# Profile: ${describe(p)}`, '# Scoring version: weights_v3.yaml',
      '# Relative suitability index (0-100) for state screening. It is NOT a probability of commercial success, profit or survival, and not financial advice. Weights are design defaults (v3), not learned optima.'];
    const blob = new Blob([meta.join('\n') + '\n' + head.join(',') + '\n' + rows.join('\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'expansion_screening.csv'; document.body.appendChild(a); a.click(); a.remove();
  }

  function methodsView() {
    const steps = [['01', 'Raw files', 'Official XLSX/HTML/PDF saved unchanged with sha256 in the source register'], ['02', 'Parse & map', 'Fixed state alias map, units converted once, footnotes stripped'],
      ['03', 'Validate', 'Duplicates, ±40% jumps flagged, single price base, edition revisions logged'], ['04', 'Warehouse', 'DuckDB: dim_state, fact_economic, fact_indicator'],
      ['05', 'Model', 'Lag features as of release date; ridge vs persistence and 3-year-mean baselines'], ['06', 'Score', 'Percentiles vs 30 states, weights v3, your priorities (computed in your browser)']];
    const regRows = Object.entries(S.industries).map(([k, v]) => { const r = B.registry[v.model_target || k] || {}; return `<tr><th scope="row">${esc(v.label)}</th><td>${badge((r.status || 'not trained').replace('_', ' '), r.status === 'validated' ? 'blue' : 'grey')}</td><td class="s14">${esc(r.reason || v.target_note || '')}</td></tr>`; }).join('');
    const dkeys = Object.keys(S.dimensions);
    const wRows = Object.values(S.industries).map((v) => `<tr><th scope="row">${esc(v.label)}</th>${dkeys.map((d) => `<td class="num">${v.weights[d] === undefined ? '<span class="muted" title="no auditable indicator for this industry">—</span>' : v.weights[d]}</td>`).join('')}</tr>`).join('');
    const whyRows = Object.values(S.industries).map((v) => `<details><summary>${esc(v.label)}</summary><div class="tbl-wrap"><table><thead><tr><th>Dimension</th><th>Indicator</th><th class="num">Weight</th><th>Why it is in this profile</th></tr></thead><tbody>${Object.entries(v.indicators).map(([d, m]) => Object.entries(m).map(([c, w]) => `<tr><td class="small">${esc(S.dimensions[d].label)}</td><td>${esc(S.indicators[c].label)}</td><td class="num">${w}</td><td class="small">${esc((v.why || {})[c] || '')}</td></tr>`).join('')).join('')}</tbody></table></div></details>`).join('');
    const indRows = Object.entries(S.indicators).map(([k, v]) => `<tr><td>${esc(v.label)}</td><td class="small">${esc(v.unit)}</td><td class="small">${v.direction > 0 ? 'higher is better' : 'lower is better'}</td><td class="small">${esc(v.proxy || '')}</td></tr>`).join('');
    const em = {}; B.eligibility.forEach((r) => { (em[r.state] = em[r.state] || {})[r.industry] = r.status; });
    const inds = Object.keys(S.industries);
    const emRows = Object.entries(em).map(([s, v]) => `<tr><th scope="row">${esc(s)}</th>${inds.map((i) => `<td>${badge(v[i], v[i] === 'approve' ? 'blue' : v[i] === 'exclude' ? 'amber' : 'grey')}</td>`).join('')}</tr>`).join('');
    const urls = {}; B.indicators.forEach((r) => { String(r.url || '').split(' ; ').filter(Boolean).forEach((u) => { urls[u] = (urls[u] || 0) + 1; }); });
    const srcList = Object.keys(urls).sort().map((u) => `<li><a href="${esc(u)}" rel="noopener" target="_blank">${esc(u.replace(/^https?:\/\//, '').slice(0, 110))}</a></li>`).join('');
    const md = window.marked ? window.marked.parse(B.model_card) : `<pre>${esc(B.model_card)}</pre>`;
    main.innerHTML = `<div class="stack"><div><h1>Methods and data lineage</h1><p class="lead">How each number gets from a government file to your screen, what the model can and cannot say, and the exact weights used. Data refreshed ${esc(B.generated)} · scoring weights v3.</p></div>
      <section><h2 style="margin-bottom:12px">Lineage</h2><ol class="lineage grid" style="--min:170px;gap:10px">${steps.map(([n, t, d]) => `<li class="card"><span class="mono small muted">${n}</span><br><strong>${t}</strong><p class="small muted" style="margin:4px 0 0">${esc(d)}</p></li>`).join('')}</ol></section>
      <section><h2 style="margin-bottom:12px">Forecast models and targets</h2><div class="tbl-wrap"><table><thead><tr><th>Industry</th><th>Status</th><th>Reason</th></tr></thead><tbody>${regRows}</tbody></table></div>
        <details style="margin-top:12px"><summary>Model card: manufacturing (full)</summary><div class="md">${md}</div></details></section>
      <section><h2 style="margin-bottom:6px">Default weights (v3)</h2><p class="small muted">Design defaults from the blueprint, tilted by industry. NOT learned optima. Indicators are scored as their percentile among 30 states (cost and risk reversed); missing indicators are dropped and weights renormalised, never filled; a state missing a mandatory dimension is excluded.</p>
        <div class="tbl-wrap"><table><thead><tr><th>Industry</th>${dkeys.map((d) => `<th class="num">${esc(S.dimensions[d].label)}</th>`).join('')}</tr></thead><tbody>${wRows}</tbody></table></div>
        <p class="small muted" style="margin:12px 0 4px">— = the industry has no such dimension: no auditable indicator exists for it, so its weight is spread over the others.</p>
        <h3 style="margin:16px 0 6px">Indicators used by each industry, and why</h3><p class="small muted">Only indicators with a stated business link are scored. Operational needs can add indicators (e.g. digital-first adds internet subscriptions). Strengths and watch-outs on the results page compare each state with the other states you chose.</p>${whyRows}
        <details style="margin-top:12px"><summary>Indicator definitions</summary><div class="tbl-wrap"><table><thead><tr><th>Indicator</th><th>Unit</th><th>Direction</th><th>Caveat</th></tr></thead><tbody>${indRows}</tbody></table></div></details></section>
      <section><h2 style="margin-bottom:12px">Eligibility matrix (7 states × 6 industries, default settings)</h2><div class="tbl-wrap"><table><thead><tr><th>State</th>${inds.map((i) => `<th>${esc(S.industries[i].label)}</th>`).join('')}</tr></thead><tbody>${emRows}</tbody></table></div></section>
      <section><h2 style="margin-bottom:12px">Coverage of the state accounts panel</h2><img src="coverage_heatmap.png" alt="Heatmap of state by fiscal year by activity coverage in the RBI Handbook 2024-25; Gujarat lacks 2023-24 and 2024-25, several small states lack 2024-25" style="width:100%;border:1px solid var(--line);border-radius:12px;background:#fff"></section>
      <section><h2 style="margin-bottom:12px">Sources</h2><details><summary>${Object.keys(urls).length} official source pages behind the numbers shown</summary><ul class="small">${srcList}</ul></details>
        <p style="font-weight:600;margin:16px 0 6px">Not available (never estimated)</p><ul class="s14">${B.unavailable.map((r) => `<li><strong>${esc(r.source.replace(/_/g, ' '))}</strong>: ${esc(r.reason)}</li>`).join('')}</ul>
        <div class="note">Secondary pages (GST collections, minimum wages, private salary surveys) are shown only where the number was found in a saved copy of the cited page; they never enter a score.</div></section>
      <section class="card"><h2>Was this comparison useful?</h2><p class="small muted">Feedback stays in this browser tab and is never used as ground truth for any model.</p><div class="btns" id="fb"><button class="btn" data-v="yes">Yes</button><button class="btn" data-v="no">Not really</button></div></section></div>`;
    $('#fb').addEventListener('click', (e) => { if (e.target.dataset.v) $('#fb').innerHTML = '<span role="status" style="color:var(--blue-dark);font-weight:600">Thanks, noted.</span>'; });
  }

  // ---------- router
  let GEO = null;
  const routes = { '': home, profile: profileView, eligibility: eligibilityView, results: resultsView, methods: methodsView };
  function route() {
    const key = (location.hash.replace(/^#\/?/, '').split('?')[0]) || '';
    const view = routes[key] || home;
    document.querySelectorAll('.nav a').forEach((a) => { if (a.getAttribute('href') === '#/' + key) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
    const html = view();
    if (typeof html === 'string') main.innerHTML = html;
    window.scrollTo(0, 0); main.focus({ preventScroll: true });
  }
  Promise.all([fetch('data/bundle.json').then((r) => r.json()), fetch('data/india_adm1.json').then((r) => r.json())]).then(([b, g]) => {
    B = b; S = b.spec; E = window.EIEngine.Engine(b); GEO = g;
    window.addEventListener('hashchange', route); route();
  }).catch((e) => { main.innerHTML = `<div class="caveat">Could not load the data bundle (${esc(e.message)}).</div>`; });
})();
