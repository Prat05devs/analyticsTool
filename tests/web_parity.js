// Runs web/engine.js on the Python parity fixtures and prints the results as JSON (used by test_web_parity.py).
const fs = require('fs'), path = require('path');
const root = path.join(__dirname, '..');
const { Engine } = require(path.join(root, 'web', 'engine.js'));
const bundle = JSON.parse(fs.readFileSync(path.join(root, 'web', 'data', 'bundle.json')));
const cases = JSON.parse(fs.readFileSync(path.join(root, 'tests', 'fixtures', 'web_parity.json')));
const E = Engine(bundle);
const out = cases.map((c) => {
  const r = E.score(c.profile);
  return { ranking: r.ranking.map((x) => ({ s: x.state_id, score: x.score, rank: x.rank })), weights: r.dim_weights,
           counter: r.counter, stability: (r.stability || []).map((x) => ({ s: x.state_id, same: x.share_same_rank })),
           message: r.message,
           reasons: Object.fromEntries(r.ranking.map((x) => { const q = E.reasons(r, x.state_id, 3); return [x.state_id, [q.pos.map((y) => y.indicator), q.neg.map((y) => y.indicator)]]; })) };
});
process.stdout.write(JSON.stringify(out));
