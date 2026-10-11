// Turns the sample state into one full of attacker-style strings, to prove the page shows them as
// text and never as markup, handlers or links. Used by the dev server (--state hostile) and tests.

export const PAYLOADS = Object.freeze({
  img: '<img src=x onerror="window.__pwned=1">',
  script: '</script><script>window.__pwned=2</script>',
  js: 'javascript:window.__pwned=3',
  svg: '<svg onload="window.__pwned=4"></svg>',
  quote: '"><img src=x onerror=window.__pwned=5>',
  long: 'A'.repeat(5000),
  longWords: 'hostile '.repeat(700),
});

const BAD_URLS = [
  'javascript:window.__pwned=6',
  'https://evil.example/x',
  'data:text/html,<script>window.__pwned=7</script>',
  'https://github.com/stevengonsalvez/foundry-autonomous-sdlc.evil.example/x',
  'https://github.com/evil/other-repo/issues/1',
  'https://github.com/stevengonsalvez/foundry-autonomous-sdlc/../../evil/x',
  'https://user:pass@github.com/stevengonsalvez/foundry-autonomous-sdlc/x',
];

export function makeHostile(sample) {
  const doc = structuredClone(sample);
  const p = PAYLOADS;
  doc.repo = p.img;
  const by = (n) => doc.tickets.find((t) => t.issue === n);

  const a = by(24);
  a.title = p.img;
  a.summary = p.script;
  a.author = p.quote;
  a.scenario = p.svg;
  a.url = BAD_URLS[0];
  a.pr.url = BAD_URLS[1];
  a.pr.branch = p.img;
  a.release = { tag: 'v1"onmouseover="window.__pwned=8', url: BAD_URLS[2] };
  a.qa = a.qa.map((q, i) => ({ ...q, question: [p.img, p.script, p.js, p.long][i % 4], answer: [p.svg, p.quote, p.longWords, p.img][i % 4] }));
  a.reviews[0].findings = [{ severity: p.img, area: p.script, detail: p.quote }];
  a.hops[0].run_url = BAD_URLS[3];
  a.hops[0].detail = p.img;
  a.hops[1].run_url = BAD_URLS[5];
  a.commits = [
    { sha: 'not a sha"><img src=x>', message: p.img, kind: p.script, files: [p.img] },
    { sha: 'abc1234', message: p.long, kind: 'test', files: 2 },
  ];
  a.agent_runs[0].agent = p.img;

  const b = by(25);
  b.title = p.script;
  b.escalation.label = p.img;
  b.escalation.reasons = [p.img, p.long, p.js];
  b.escalation.tried = [p.svg, p.quote];
  b.escalation.evidence_url = BAD_URLS[4];

  const c = by(5);
  c.title = p.long;
  c.escalation.evidence_url = BAD_URLS[6];
  c.escalation.reasons = [p.longWords];

  const d = by(27);
  d.title = p.js;
  d.ci_triage.explanation = p.img;
  d.ci_triage.cause = p.script;
  d.ci_triage.test_files = [p.svg, p.long];

  by(7).title = p.longWords;
  by(2).title = p.quote;
  by(2).type = p.img;
  by(9).stage_history[0].stage = p.img;

  doc.agents[0].name = p.img;
  doc.agents[0].role = p.script;
  doc.agents[0].last_error = { at: doc.generated_at, detail: p.quote, object: 24, result: p.img };
  doc.agents[2].lock_holder = p.long;
  doc.ledger.errors = [{ at: doc.generated_at, message: p.img }];
  doc.environments.history[0].reason = p.script;
  doc.environments.history[0].run_url = BAD_URLS[0];
  doc.environments.prod.tag = p.quote;
  doc.environments.prod.version = p.img;
  doc.environments.prod.run_url = BAD_URLS[1];
  doc.cost.billing.by_meter[0].name = p.img;
  doc.cost.billing.scope = p.script;
  doc.flow.defects[0].owner = p.img;
  doc.flow.change_failure.per_release[1].version = p.script;
  return doc;
}
