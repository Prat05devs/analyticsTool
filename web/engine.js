/* Scoring engine: a line-by-line port of scoring/score.py for the static web app.
 * Same rules: percentile vs a frozen national reference, cost/risk reversed, no favourable fill (missing
 * indicators dropped and weights renormalised), mandatory-dimension exclusion, priority / need multipliers,
 * what-if override, +-20% stability and the runner-up counter-explanation.
 * tests/test_web_parity.py checks this file against the Python engine.
 * The index is a relative screening score, NOT a probability of success. */
(function (root) {
  'use strict';

  const isNum = (x) => typeof x === 'number' && isFinite(x);

  function transform(x, how) {
    if (!isNum(x)) return NaN;
    if (how === 'log') return x > 0 ? Math.log(x) : NaN;
    return x;
  }

  function percentile(x, ref) {
    const r = ref.filter(isNum);
    if (!r.length || !isNum(x)) return NaN;
    let lt = 0, eq = 0;
    for (const v of r) { if (v < x) lt++; else if (v === x) eq++; }
    return 100 * (lt + 0.5 * eq) / r.length;
  }

  function median(xs) {
    const v = xs.filter(isNum).sort((a, b) => a - b);
    if (!v.length) return NaN;
    const m = Math.floor(v.length / 2);
    return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
  }

  // small seeded PRNG (mulberry32) for the stability draws
  function rng(seed) {
    let a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function Engine(bundle) {
    const S = bundle.spec;
    const latest = {};
    for (const r of bundle.indicators) latest[r.s + '|' + r.c] = r;
    const modelOk = (ind) => {
      const t = S.industries[ind].model_target;
      return !!t && (bundle.registry[t] || {}).status === 'validated';
    };

    function effectiveWeights(p) {
      const prof = S.industries[p.industry];
      const notes = [];
      const override = !!p.dimension_weights && Object.keys(p.dimension_weights).length > 0;
      const dims = Object.assign({}, override ? p.dimension_weights : prof.weights);
      const inds = {};
      for (const d of Object.keys(prof.indicators)) inds[d] = Object.assign({}, prof.indicators[d]);
      const pri = p.priorities || [];
      if (pri.length > S.priorities.max_selected) throw new Error('choose at most ' + S.priorities.max_selected + ' priorities');
      if (override) notes.push('What-if: dimension weights set by hand (priorities already reflected in the starting values).');
      for (const pr of override ? [] : pri) {
        const d = S.priorities.map[pr];
        if (d === null || d === undefined) { notes.push(S.priorities.policy_note); continue; }
        if (!(d in dims)) { notes.push("Priority '" + pr + "': " + prof.label + ' has no ' + S.dimensions[d].label.toLowerCase() + ' dimension, so it does not change the scores.'); continue; }
        dims[d] = dims[d] * S.priorities.multiplier;
        notes.push("Priority '" + pr + "': " + S.dimensions[d].label + ' weight x' + S.priorities.multiplier + '.');
      }
      for (const need of p.needs || []) {
        const rule = S.operational_needs[need];
        if (!(rule.dimension in dims)) {
          notes.push("Operational need '" + need + "' maps to a dimension the " + prof.label + ' profile does not have, so it does not change the scores.');
          continue;
        }
        const have = inds[rule.dimension] = inds[rule.dimension] || {};
        const added = (rule.add || []).filter((i) => !(i in have));
        for (const i of added) have[i] = 1.0;  // the need brings its own indicators into a profile that lacks them
        if (added.length) notes.push("Operational need '" + need + "' adds " + added.join(', ') + ' to ' + S.dimensions[rule.dimension].label + '.');
        const supported = rule.boost.filter((i) => i in have);
        if (!supported.length) {
          notes.push("Operational need '" + need + "' has no supported indicator in the " + prof.label + ' profile, so it does not change the scores.');
          continue;
        }
        if (!override) dims[rule.dimension] *= rule.dim_multiplier;
        for (const i of supported) inds[rule.dimension][i] *= rule.indicator_multiplier;
        notes.push("Operational need '" + need + "': " + S.dimensions[rule.dimension].label + ' weight x' + rule.dim_multiplier + ', ' + supported.join(', ') + ' x' + rule.indicator_multiplier + '.');
      }
      if (p.capital_rs_crore !== null && p.capital_rs_crore !== undefined && p.capital_rs_crore !== '')
        notes.push('Investment capital is recorded as context only: no auditable state-level capex or rent data exists, so the budget does not change scores.');
      const tot = Object.values(dims).reduce((a, b) => a + b, 0);
      const w = {};
      for (const d of Object.keys(dims)) w[d] = dims[d] / tot;
      return { w, inds, notes };
    }

    function indicatorTable(p) {
      const ok = modelOk(p.industry);
      const effInds = effectiveWeights(p).inds;  // industry profile plus indicators added by operational needs
      const rows = [];
      for (const dim of Object.keys(effInds)) {
        for (const code of Object.keys(effInds[dim])) {
          const meta = S.indicators[code];
          if (meta.requires_model && !ok) continue;
          const refv = (bundle.reference[code] || []).map((v) => transform(v, meta.transform)).filter(isNum);
          for (const sid of p.states) {
            const row = { state_id: sid, state: bundle.states[sid], dimension: dim, indicator: code, label: meta.label,
              unit: meta.unit, direction: meta.direction, proxy: meta.proxy || '', value: NaN, period: '', source_file: '',
              url: '', quality: '', note: '' };
            if (meta.requires_model) {
              const f = bundle.forecasts[sid];
              if (f) Object.assign(row, { value: f.v, period: f.p, source_file: 'models/registry.json; data/curated/forecast_manufacturing.parquet',
                quality: 'model', note: '80% band ' + sign(f.lo, 1) + ' to ' + sign(f.hi, 1) + ' pp; hold-out MAE ' + f.mae.toFixed(2) + ' pp' });
            } else {
              const r = latest[sid + '|' + code];
              if (r && isNum(r.v)) Object.assign(row, { value: r.v, period: r.p, source_file: r.f, url: r.url, quality: r.q, note: r.n || '' });
            }
            const pct = percentile(transform(row.value, meta.transform), refv);
            row.score = (meta.direction > 0 || !isNum(pct)) ? pct : 100 - pct;
            rows.push(row);
          }
        }
      }
      return rows;
    }

    function score(pIn, opts) {
      opts = opts || {};
      const prof = S.industries[pIn.industry];
      const states = pIn.states.filter((x) => !(pIn.exclude_current && x === pIn.current_state));
      const p = Object.assign({}, pIn, { states });
      const { w: dimw, inds: indw, notes } = effectiveWeights(p);
      const tab = indicatorTable(p);
      for (const r of tab) r.w_ind = indw[r.dimension][r.indicator];
      const excluded = [];
      for (const sid of states) {
        const have = new Set(tab.filter((r) => r.state_id === sid && isNum(r.score)).map((r) => r.dimension));
        const miss = prof.mandatory_dimensions.filter((d) => !have.has(d));
        if (miss.length) excluded.push({ state_id: sid, state: bundle.states[sid], reason: 'no observed data for mandatory dimension(s): ' + miss.join(', ') });
      }
      const exSet = new Set(excluded.map((e) => e.state_id));
      const elig = states.filter((x) => !exSet.has(x));
      const res = { industry: p.industry, profile: p, dim_weights: dimw, notes, excluded, ranking: [], indicators: [], stability: null, counter: null, message: null };
      if (elig.length < 2) {
        res.indicators = tab;
        res.message = 'Fewer than two comparable states pass the mandatory data gates, so no ranking is shown.';
        return res;
      }
      const t = tab.filter((r) => elig.includes(r.state_id)).map((r) => Object.assign({}, r));
      const sums = {};
      for (const r of t) { r.observed = isNum(r.score); const k = r.state_id + '|' + r.dimension; sums[k] = (sums[k] || 0) + (r.observed ? r.w_ind : 0); }
      for (const r of t) { const s = sums[r.state_id + '|' + r.dimension]; r.w_ind_eff = s ? (r.observed ? r.w_ind : 0) / s : NaN; }
      const dims = Object.keys(dimw);
      const ds = {};
      for (const sid of elig) {
        ds[sid] = {};
        for (const d of dims) {
          const g = t.filter((r) => r.state_id === sid && r.dimension === d);
          const nObs = g.filter((r) => r.observed).length;
          ds[sid][d] = nObs ? g.reduce((a, r) => a + (isNum(r.score) ? r.score : 0) * (isNum(r.w_ind_eff) ? r.w_ind_eff : 0), 0) : NaN;
        }
      }
      const total = (row, weights) => {
        let tw = 0, s = 0;
        for (const d of Object.keys(weights)) if (isNum(row[d])) { tw += weights[d]; s += row[d] * weights[d]; }
        return tw ? s / tw : NaN;
      };
      const totW = {};
      for (const r of t) { const k = r.state_id + '|' + r.dimension; totW[k] = (totW[k] || 0) + r.w_ind; }
      let rk = elig.slice().sort().map((sid) => {
        const g = t.filter((r) => r.state_id === sid);
        const dropped = dims.filter((d) => !isNum(ds[sid][d]));
        const miss = g.filter((r) => !r.observed).map((r) => r.label);
        let cov = 0;
        for (const r of g) if (r.observed) cov += r.w_ind / totW[sid + '|' + r.dimension] * dimw[r.dimension];
        const msg = [];
        if (miss.length) msg.push('not available: ' + miss.join('; '));
        if (dropped.length) msg.push('dimension dropped and weights renormalised: ' + dropped.join(', '));
        const stale = g.filter((r) => r.observed && /^\d{4}/.test(String(r.period)) && parseInt(String(r.period).slice(0, 4), 10) <= 2022).length;
        const proxy = g.filter((r) => r.observed && r.proxy !== '').length;
        const level = cov >= 0.95 && stale <= 2 ? 'High' : cov >= 0.8 ? 'Medium' : 'Low';
        const row = { state_id: sid, state: bundle.states[sid], score: total(ds[sid], dimw), weight_coverage: cov,
          disclosure: msg.join(' | '), confidence: level,
          data_confidence: level + ': ' + Math.round(cov * 100) + '% of weighted indicators observed; ' + stale + ' older than 2023; ' + proxy + ' proxies' };
        for (const d of dims) row['dim_' + d] = ds[sid][d];
        return row;
      });
      rk.sort((a, b) => b.score - a.score);
      rk.forEach((r, i) => { r.rank = i + 1; });
      const med = {};
      for (const code of new Set(t.map((r) => r.indicator))) med[code] = median(t.filter((r) => r.indicator === code).map((r) => r.value));
      for (const r of t) { r.dim_weight = dimw[r.dimension]; r.contribution = r.score * r.w_ind_eff * r.dim_weight; r.pilot_median = med[r.indicator]; }
      Object.assign(res, { ranking: rk, indicators: t });
      if (opts.stability !== false) res.stability = stability(rk, ds, dimw, S.stability);
      res.counter = counter(rk, ds, dimw, t);
      return res;
    }

    function stability(rk, ds, dimw, cfg) {
      const dims = Object.keys(dimw);
      const base = dims.map((d) => dimw[d]);
      const M = rk.map((r) => dims.map((d) => ds[r.state_id][d]));
      const rand = rng(cfg.seed);
      const [lo, hi] = cfg.perturbation;
      const n = rk.length;
      const same = new Array(n).fill(0), top3 = new Array(n).fill(0), top1 = new Array(n).fill(0);
      const best = new Array(n).fill(Infinity), worst = new Array(n).fill(0);
      const totals = (w) => M.map((row) => {
        let s = 0, tw = 0;
        row.forEach((v, j) => { if (isNum(v)) { s += v * w[j]; tw += w[j]; } });
        return s / tw;
      });
      const ranksOf = (tot) => {
        const order = tot.map((v, i) => i).sort((a, b) => tot[b] - tot[a]);
        const r = new Array(n);
        order.forEach((i, k) => { r[i] = k + 1; });
        return r;
      };
      const baseRank = ranksOf(totals(base));
      for (let k = 0; k < cfg.draws; k++) {
        const w = base.map((b) => b * (lo + (hi - lo) * rand()));
        const r = ranksOf(totals(w));
        for (let i = 0; i < n; i++) {
          if (r[i] === baseRank[i]) same[i]++;
          if (r[i] <= 3) top3[i]++;
          if (r[i] === 1) top1[i]++;
          best[i] = Math.min(best[i], r[i]); worst[i] = Math.max(worst[i], r[i]);
        }
      }
      return rk.map((r, i) => ({ state_id: r.state_id, state: r.state, rank: baseRank[i], share_same_rank: same[i] / cfg.draws,
        share_top3: top3[i] / cfg.draws, share_top1: top1[i] / cfg.draws, best_rank: best[i], worst_rank: worst[i] }))
        .sort((a, b) => a.rank - b.rank);
    }

    function counter(rk, ds, dimw, t) {
      if (rk.length < 2) return null;
      const a = rk[0].state_id, b = rk[1].state_id, A = bundle.states[a], B = bundle.states[b];
      const gaps = {};
      for (const d of Object.keys(dimw)) if (isNum(ds[a][d]) && isNum(ds[b][d])) gaps[d] = ds[b][d] - ds[a][d];
      let d = null, gap = -Infinity;
      for (const k of Object.keys(gaps)) if (gaps[k] > gap) { gap = gaps[k]; d = k; }
      if (gap <= 0) return B + ' does not score higher than ' + A + ' on any dimension, so no re-weighting of these dimensions would put it first.';
      let sa = 0, sb = 0;
      for (const x of Object.keys(gaps)) { sa += dimw[x] * ds[a][x]; sb += dimw[x] * ds[b][x]; }
      const k = 1 + (sa - sb) / (dimw[d] * gap);
      const diffs = [];
      for (const code of new Set(t.filter((r) => r.dimension === d).map((r) => r.indicator))) {
        const sA = t.find((r) => r.state_id === a && r.indicator === code), sB = t.find((r) => r.state_id === b && r.indicator === code);
        if (sA && sB && isNum(sA.score) && isNum(sB.score)) diffs.push([code, sB.score - sA.score]);
      }
      diffs.sort((x, y) => y[1] - x[1]);
      const l0 = diffs.length ? S.indicators[diffs[0][0]].label : d;
      const lab = /^[A-Z]{2}/.test(l0) ? l0 : l0.charAt(0).toLowerCase() + l0.slice(1);
      const lead = B + ' scores ' + Math.round(ds[b][d]) + ' vs ' + Math.round(ds[a][d]) + ' for ' + A + ' on ' +
        S.dimensions[d].label.toLowerCase() + ' (mainly ' + lab + ').';
      if (k < 1.15) return lead + " The top two are close: raising that dimension's weight by about " + Math.round(100 * (k - 1)) + '% would put ' + B + ' first, so treat them as a near-tie.';
      return lead + ' If that dimension carried about ' + k.toFixed(1) + 'x its current weight, ' + B + ' would rank first.';
    }

    // Strengths / watch-outs RELATIVE TO THE OTHER COMPARED STATES (port of scoring/score.py reasons):
    // gap = score - median score of the other eligible states; lever = gap x within-dimension weight x dimension weight;
    // reported only if |gap| >= min_gap and the raw difference from the peers' median is material.
    function reasons(res, sid, k) {
      k = k || 3;
      if (!res.ranking.length) return { pos: [], neg: [] };
      const prof = S.industries[res.industry];
      const p = res.profile || { priorities: [], needs: [] };
      const cfg = S.reasons || {};
      const minGap = cfg.min_gap === undefined ? 5 : cfg.min_gap, minRel = cfg.min_rel_diff === undefined ? 0.05 : cfg.min_rel_diff;
      const override = !!p.dimension_weights && Object.keys(p.dimension_weights).length > 0;
      const priDims = new Set(override ? [] : (p.priorities || []).map((x) => S.priorities.map[x]).filter((d) => d !== null && d !== undefined));
      const obs = res.indicators.filter((r) => r.observed);
      const items = [];
      for (const r of obs.filter((x) => x.state_id === sid)) {
        const o = obs.filter((x) => x.state_id !== sid && x.indicator === r.indicator);
        if (!o.length) continue;
        const meta = S.indicators[r.indicator];
        const peerMed = median(o.map((x) => x.value));
        const floor = meta.min_diff !== undefined ? meta.min_diff : minRel * Math.abs(peerMed);
        if (Math.abs(r.value - peerMed) < floor) continue;
        const gap = r.score - median(o.map((x) => x.score));
        const needs = (p.needs || []).filter((n) => S.operational_needs[n].boost.includes(r.indicator) && S.operational_needs[n].dimension === r.dimension);
        const why = (prof.why || {})[r.indicator] || (needs.length ? S.operational_needs[needs[0]].why : '');
        const higher = gap * meta.direction > 0;
        items.push(Object.assign({}, r, { dimension_label: S.dimensions[r.dimension].label, peer_median: peerMed,
          n_peers: new Set(o.map((x) => x.state_id)).size, gap, lever: gap * r.w_ind_eff * r.dim_weight,
          meaning: meta[higher ? 'hi' : 'lo'] || '', why, priority: priDims.has(r.dimension), needs }));
      }
      const pos = items.filter((x) => x.gap >= minGap && x.lever > 0).sort((x, y) => y.lever - x.lever).slice(0, k);
      const neg = items.filter((x) => x.gap <= -minGap && x.lever < 0).sort((x, y) => x.lever - y.lever).slice(0, k);
      return { pos, neg };
    }

    return { effectiveWeights, indicatorTable, score, reasons, modelOk, spec: S };
  }

  function sign(x, d) { return (x >= 0 ? '+' : '') + x.toFixed(d); }

  const api = { Engine, percentile, transform, median };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.EIEngine = api;
})(typeof window !== 'undefined' ? window : globalThis);
