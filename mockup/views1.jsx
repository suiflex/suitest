// Suitest — Dashboard, Test Cases, Runs views
const { useState: useStateA, useEffect: useEffectA, useMemo: useMemoA } = React;
const { Icon: IconA } = window;
const { SUITES, CURRENT_CASE, ACTIVE_RUNS, LOG_LINES, PASS_RATE_HISTORY } = window.SuitestData;

// ============== DASHBOARD ==============
function DashboardView() {
  return (
    <div className="content">
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">
            Dashboard
            <span className="badge pass"><span className="dot"></span>All systems healthy</span>
          </h1>
          <div className="page-sub">Selamat siang, Maya — here's your test quality snapshot.</div>
        </div>
        <button className="btn"><IconA name="filter" size={12}/> Last 7 days</button>
        <button className="btn btn-primary"><IconA name="play" size={12}/> Run gating suite</button>
      </div>

      <div className="dash">
        <div className="dash-kpis">
          <KpiCard label="Tests run today" value="1,247" delta="+18.2%" up icon="play"/>
          <KpiCard label="Pass rate" value="96.4%" delta="+2.1%" up icon="check"/>
          <KpiCard label="Avg. duration" value="11.8s" delta="-1.4s" up icon="clock" deltaSuffix=" faster"/>
          <KpiCard label="Active MCP agents" value="4" delta="2 idle" icon="bot"/>
        </div>

        <div className="grid-2">
          <div className="card">
            <div className="card-head">
              <span className="card-title">Pass rate · last 11 days</span>
              <span className="badge ai"><span className="dot"></span>AI-augmented</span>
              <button className="btn btn-sm btn-ghost" style={{marginLeft: 'auto'}}>Open <IconA name="arrowRight" size={11}/></button>
            </div>
            <div className="card-body">
              <PassRateChart data={PASS_RATE_HISTORY}/>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <span className="card-title">Coverage by suite</span>
              <span className="muted" style={{marginLeft: 'auto', fontSize: 11.5}}>4 suites · 247 cases</span>
            </div>
            <div className="card-body" style={{paddingTop: 4}}>
              {[
                { name: 'Authentication', cov: 94, total: 32, ai: 18 },
                { name: 'Checkout', cov: 87, total: 64, ai: 41 },
                { name: 'API — Orders', cov: 78, total: 47, ai: 38 },
                { name: 'User Profile', cov: 91, total: 28, ai: 7 },
              ].map(s => (
                <div key={s.name} style={{padding: '10px 0', borderBottom: '1px solid var(--border-subtle)'}}>
                  <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6}}>
                    <span style={{fontSize: 12.5, fontWeight: 500}}>{s.name}</span>
                    <span className="muted" style={{fontSize: 11.5}}>{s.total} cases · {s.ai} AI-generated</span>
                    <span className="mono tabular" style={{marginLeft: 'auto', fontSize: 12, color: 'var(--fg-1)'}}>{s.cov}%</span>
                  </div>
                  <div className="progress-track">
                    <div className={`progress-fill${s.cov < 80 ? ' warn' : ''}`} style={{width: `${s.cov}%`}}/>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="grid-2">
          <div className="card">
            <div className="card-head">
              <span className="card-title">Recent runs</span>
              <button className="btn btn-sm btn-ghost" style={{marginLeft: 'auto'}}>All runs <IconA name="arrowRight" size={11}/></button>
            </div>
            <div className="runs-mini">
              {ACTIVE_RUNS.slice(0, 5).map(r => (
                <div className="run-row" key={r.id}>
                  <span className="run-id mono">{r.id}</span>
                  <div>
                    <div className="run-name">{r.name}</div>
                    <div className="run-meta mono">{r.branch} · {r.commit} · {r.duration}</div>
                  </div>
                  <span className="muted mono" style={{fontSize: 11.5}}>{r.passed}/{r.total}</span>
                  <RunStatusBadge status={r.status}/>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <span className="card-title">Agent activity</span>
              <span className="badge ai"><span className="dot"></span>Last 30 min</span>
            </div>
            <div className="activity-feed">
              <ActivityRow icon="sparkles" tone="ai" text='Generated <b>5 test cases</b> for OAuth flow from PRD-2026-Q1 § 4.2' time="2m ago"/>
              <ActivityRow icon="bug" tone="fail" text='Auto-filed <b>SUIT-1284</b> · OAuth session not persisted · linked to TC-1045' time="4m ago"/>
              <ActivityRow icon="play" tone="default" text='Ran <b>R-8841</b> in MCP browser session · 22 steps in 2m 11s' time="6m ago"/>
              <ActivityRow icon="check" tone="pass" text='Verified fix for <b>SUIT-1281</b> · re-ran TC-2014 · all assertions passed' time="14m ago"/>
              <ActivityRow icon="sparkles" tone="ai" text='Discovered <b>3 new API endpoints</b> in openapi.json · queued for test generation' time="22m ago"/>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <span className="card-title">Release readiness · Sprint 24 → production</span>
            <span className="badge warn" style={{marginLeft: 'auto'}}><span className="dot"></span>2 blockers</span>
          </div>
          <div className="card-body" style={{display: 'grid', gridTemplateColumns: '180px 1fr', gap: 24, alignItems: 'center'}}>
            <ReadinessGauge value={86}/>
            <div style={{display: 'flex', flexDirection: 'column', gap: 10}}>
              <ReadinessRow ok label="Smoke suite green on main" detail="34/34 passing · last run 12m ago"/>
              <ReadinessRow ok label="Regression pack ≥ 95% pass rate" detail="96.4% (211/214)"/>
              <ReadinessRow warn label="Critical defects open" detail="SUIT-1284 (OAuth) · SUIT-1283 (Orders API)"/>
              <ReadinessRow ok label="Coverage ≥ 80% on changed files" detail="92% across 47 files in this sprint"/>
              <ReadinessRow ok label="No flaky tests blocking gating" detail="2 flaky tests quarantined by agent"/>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function KpiCard({ label, value, delta, up, deltaSuffix = '', icon }) {
  return (
    <div className="kpi">
      <div className="kpi-label"><IconA name={icon} size={12}/>{label}</div>
      <div className="kpi-value">{value}</div>
      <div className="kpi-meta">
        {delta && <span className={`kpi-delta ${up ? 'up' : 'down'}`}>
          {up && delta.startsWith('+') && <IconA name="arrowUp" size={10}/>}
          {up && delta.startsWith('-') && <IconA name="arrowDown" size={10}/>}
          {delta}{deltaSuffix}
        </span>}
        {!delta?.includes('idle') && <span>vs last 7d</span>}
      </div>
    </div>
  );
}

function RunStatusBadge({ status }) {
  const map = {
    pass: { cls: 'pass', label: 'pass' },
    fail: { cls: 'fail', label: 'fail' },
    running: { cls: 'running', label: 'running' },
    warn: { cls: 'warn', label: 'flaky' },
  };
  const s = map[status] || map.pass;
  return <span className={`badge ${s.cls}`}><span className="dot"></span>{s.label}</span>;
}

function ActivityRow({ icon, tone, text, time }) {
  return (
    <div className="activity-item">
      <div className={`activity-icon ${tone}`}><IconA name={icon} size={13}/></div>
      <div style={{flex: 1}}>
        <div className="activity-text" dangerouslySetInnerHTML={{__html: text}}/>
        <div className="activity-meta"><span>{time}</span></div>
      </div>
    </div>
  );
}

function ReadinessRow({ ok, warn, label, detail }) {
  return (
    <div style={{display: 'flex', gap: 10, alignItems: 'flex-start'}}>
      <div style={{width: 18, height: 18, borderRadius: 5, display: 'grid', placeItems: 'center', flexShrink: 0,
        background: ok ? 'var(--accent-dim)' : 'var(--amber-bg)',
        color: ok ? 'var(--accent)' : 'var(--amber)'}}>
        <IconA name={ok ? 'check' : 'x'} size={11}/>
      </div>
      <div>
        <div style={{fontSize: 12.5, fontWeight: 500}}>{label}</div>
        <div className="muted" style={{fontSize: 11.5, marginTop: 1}}>{detail}</div>
      </div>
    </div>
  );
}

function ReadinessGauge({ value }) {
  const r = 52, c = 2 * Math.PI * r;
  const offset = c - (value / 100) * c;
  return (
    <div className="gauge">
      <svg viewBox="0 0 120 120">
        <circle cx="60" cy="60" r={r} fill="none" stroke="var(--bg-elev-3)" strokeWidth="9"/>
        <circle cx="60" cy="60" r={r} fill="none" stroke="var(--accent)" strokeWidth="9"
          strokeLinecap="round" strokeDasharray={c} strokeDashoffset={offset}
          transform="rotate(-90 60 60)"/>
        <text x="60" y="58" textAnchor="middle" fill="var(--fg-1)" fontSize="22" fontWeight="600" style={{fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.02em'}}>{value}</text>
        <text x="60" y="76" textAnchor="middle" fill="var(--fg-4)" fontSize="10">READY</text>
      </svg>
    </div>
  );
}

function PassRateChart({ data }) {
  const w = 520, h = 160, pad = 24;
  const max = 100, min = 80;
  const xs = data.map((_, i) => pad + (i * (w - pad * 2)) / (data.length - 1));
  const ys = data.map(d => h - pad - ((d.p - min) / (max - min)) * (h - pad * 2));
  const path = xs.map((x, i) => `${i === 0 ? 'M' : 'L'} ${x} ${ys[i]}`).join(' ');
  const area = `${path} L ${xs[xs.length-1]} ${h-pad} L ${xs[0]} ${h-pad} Z`;
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
        <defs>
          <linearGradient id="prgrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.25"/>
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0"/>
          </linearGradient>
        </defs>
        {[80, 85, 90, 95, 100].map(t => {
          const y = h - pad - ((t - min) / (max - min)) * (h - pad * 2);
          return <g key={t}>
            <line x1={pad} y1={y} x2={w - pad} y2={y} stroke="var(--border-subtle)" strokeDasharray="2 4"/>
            <text x={6} y={y + 3} fill="var(--fg-5)" fontSize="9.5">{t}%</text>
          </g>;
        })}
        <path d={area} fill="url(#prgrad)"/>
        <path d={path} fill="none" stroke="var(--accent)" strokeWidth="1.8"/>
        {xs.map((x, i) => (
          <g key={i}>
            <circle cx={x} cy={ys[i]} r="3" fill="var(--bg-base)" stroke="var(--accent)" strokeWidth="1.5"/>
            <text x={x} y={h - 6} textAnchor="middle" fill="var(--fg-5)" fontSize="9.5">{data[i].d.replace('May ', '')}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

// ============== TEST CASES ==============
function TestCasesView() {
  const [activeId, setActiveId] = useStateA('TC-1045');
  const [showGen, setShowGen] = useStateA(false);

  const activeCase = useMemoA(() => {
    for (const s of SUITES) for (const c of s.cases) if (c.id === activeId) return c;
    return null;
  }, [activeId]);

  const detail = activeId === 'TC-1045' ? CURRENT_CASE : {
    ...activeCase,
    suite: SUITES.find(s => s.cases.some(c => c.id === activeId))?.name,
    description: 'Auto-generated description for ' + activeCase?.name,
    owner: { name: 'Maya Putri', avatar: 'MP' },
    generatedBy: activeCase?.source === 'ai' ? 'Suitest Agent · v2.4' : null,
    generatedFrom: activeCase?.source === 'ai' ? 'PRD-2026-Q1' : null,
    lastRun: '12m ago',
    duration: '6.4s',
    preconditions: 'Standard test environment',
    steps: [
      { action: 'Setup test fixtures and authenticate', expected: 'Test session established' },
      { action: `Execute primary action for ${activeCase?.name}`, expected: 'Operation completes within SLA' },
      { action: 'Verify expected state', expected: 'All assertions pass' },
    ]
  };

  return (
    <>
      <div className="tabs-row">
        <div className="tab active">All <span className="count">247</span></div>
        <div className="tab">Manual <span className="count">89</span></div>
        <div className="tab">AI-generated <span className="count">142</span></div>
        <div className="tab">MCP <span className="count">16</span></div>
        <div className="tab">Failing <span className="count" style={{color: 'var(--red)'}}>4</span></div>
        <div style={{marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8, paddingRight: 14}}>
          <button className="btn btn-sm"><IconA name="filter" size={11}/> Filter</button>
          <button className="btn btn-sm btn-primary" onClick={() => setShowGen(true)}>
            <IconA name="sparkles" size={12}/> Generate with AI
          </button>
        </div>
      </div>

      <div className="tc-page">
        <div className="tc-tree">
          <div className="tc-tree-head">
            <IconA name="search" size={12} style={{color: 'var(--fg-4)'}}/>
            <input placeholder="Filter cases..." style={{flex: 1, fontSize: 12}}/>
          </div>
          <div className="tc-tree-body">
            {SUITES.map(s => (
              <div key={s.id}>
                <div className="tree-suite">{s.name} · {s.cases.length}</div>
                {s.cases.map(c => (
                  <div
                    key={c.id}
                    className={`tree-item${c.id === activeId ? ' active' : ''}`}
                    onClick={() => setActiveId(c.id)}
                  >
                    <SourceDot src={c.source} status={c.status}/>
                    <span className="tree-id">{c.id}</span>
                    <span className="tree-name" style={{fontFamily: 'var(--font-sans)'}}>{c.name}</span>
                    <span className={`src-pill ${c.source === 'ai' ? 'ai' : c.source === 'mcp' ? 'mcp' : ''}`}>
                      {c.source.toUpperCase()}
                    </span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>

        <div className="tc-detail">
          <TestCaseDetail detail={detail}/>
        </div>
      </div>

      {showGen && <GenerateModal onClose={() => setShowGen(false)}/>}
    </>
  );
}

function SourceDot({ src, status }) {
  const color = status === 'fail' ? 'var(--red)' : status === 'warn' ? 'var(--amber)' : 'var(--accent)';
  return <span style={{width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0}}/>;
}

function TestCaseDetail({ detail }) {
  return (
    <>
      <div className="tc-toolbar">
        <span className="badge neutral mono"><span className="dot"></span>{detail.id}</span>
        <span className={`badge ${detail.status === 'fail' ? 'fail' : detail.status === 'warn' ? 'warn' : 'pass'}`}>
          <span className="dot"></span>{detail.status}
        </span>
        <span className="badge ai"><span className="dot"></span>P0 critical</span>
        <span className="muted" style={{fontSize: 11.5}}>· Last run {detail.lastRun} · {detail.duration}</span>
        <div style={{flex: 1}}/>
        <button className="btn btn-sm"><IconA name="diff" size={11}/> Compare</button>
        <button className="btn btn-sm"><IconA name="bot" size={11}/> Edit with AI</button>
        <button className="btn btn-sm btn-primary"><IconA name="play" size={11}/> Run now</button>
      </div>
      <div className="tc-body">
        <div className="eyebrow" style={{marginBottom: 6}}>{detail.suite}</div>
        <h1 className="h1" style={{margin: '0 0 8px', fontSize: 22, letterSpacing: '-0.015em'}}>{detail.name}</h1>
        <p style={{color: 'var(--fg-3)', fontSize: 13, maxWidth: 720, lineHeight: 1.55, margin: 0}}>{detail.description}</p>

        <div className="tc-meta">
          <div className="tc-meta-item">
            <div className="tc-meta-label">Owner</div>
            <div className="tc-meta-value">{detail.owner?.name}</div>
          </div>
          <div className="tc-meta-item">
            <div className="tc-meta-label">Suite</div>
            <div className="tc-meta-value">{detail.suite}</div>
          </div>
          {detail.generatedBy && (
            <div className="tc-meta-item">
              <div className="tc-meta-label">Generated by</div>
              <div className="tc-meta-value" style={{color: 'var(--violet)'}}>{detail.generatedBy}</div>
            </div>
          )}
          {detail.generatedFrom && (
            <div className="tc-meta-item" style={{flex: 1}}>
              <div className="tc-meta-label">Source</div>
              <div className="tc-meta-value mono" style={{fontSize: 12}}>{detail.generatedFrom}</div>
            </div>
          )}
          <div className="tc-meta-item">
            <div className="tc-meta-label">Avg duration</div>
            <div className="tc-meta-value mono">{detail.duration}</div>
          </div>
        </div>

        <div style={{display: 'flex', alignItems: 'center', gap: 10, margin: '24px 0 10px'}}>
          <h2 className="h2" style={{margin: 0}}>Test steps</h2>
          <span className="muted" style={{fontSize: 11.5}}>· {detail.steps.length} steps</span>
          <button className="btn btn-sm btn-ghost" style={{marginLeft: 'auto'}}><IconA name="plus" size={11}/> Add step</button>
          <button className="btn btn-sm btn-ghost"><IconA name="sparkles" size={11}/> AI: suggest edge cases</button>
        </div>

        <div className="step-list">
          {detail.steps.map((s, i) => (
            <div className="step" key={i}>
              <div className="step-num">{i + 1}</div>
              <div>
                <div className="step-action">{s.action}</div>
                <div className="step-expected"><span className="label">Expected</span>{s.expected}</div>
                {s.code && (
                  <div style={{marginTop: 8, fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--fg-3)',
                    background: 'var(--bg-base)', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border-subtle)'}}>
                    <span style={{color: 'var(--fg-5)', marginRight: 8}}>$</span>{s.code}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        <div style={{margin: '24px 0 0', padding: '14px 16px', background: 'var(--violet-bg)', border: '1px solid rgba(167, 139, 250, 0.2)', borderRadius: 8, display: 'flex', gap: 12}}>
          <div style={{width: 24, height: 24, borderRadius: 6, background: 'rgba(167, 139, 250, 0.2)', color: 'var(--violet)', display: 'grid', placeItems: 'center', flexShrink: 0}}>
            <IconA name="spark" size={13}/>
          </div>
          <div style={{flex: 1, fontSize: 12.5, color: 'var(--fg-2)'}}>
            <b style={{color: 'var(--fg-1)'}}>Agent insight</b> · Step 5 has a <b style={{color: 'var(--red)'}}>93% failure probability</b> on current main. The session cookie domain changed in commit <code style={{fontFamily: 'var(--font-mono)', fontSize: 11, padding: '1px 5px', background: 'var(--bg-base)', borderRadius: 3}}>2b9d4c0</code> from <code style={{fontFamily: 'var(--font-mono)', fontSize: 11, padding: '1px 5px', background: 'var(--bg-base)', borderRadius: 3}}>.suitest.io</code> to <code style={{fontFamily: 'var(--font-mono)', fontSize: 11, padding: '1px 5px', background: 'var(--bg-base)', borderRadius: 3}}>app.suitest.io</code>, breaking cross-subdomain reads. <a style={{color: 'var(--accent)', cursor: 'pointer'}}>Open suggested patch →</a>
          </div>
        </div>
      </div>
    </>
  );
}

function GenerateModal({ onClose }) {
  const [source, setSource] = useStateA('prd');
  const [input, setInput] = useStateA(
    source === 'prd' ? 'PRD-2026-Q1 § 4.2 "Social sign-in"\n\nUsers should be able to authenticate via Google OAuth 2.0.\nAcceptance criteria:\n  • Show consent screen with email + profile scopes\n  • Persist session for 30 days\n  • Map Google "sub" claim to internal user.id\n  • Reject expired authorization codes' : ''
  );
  const [generated, setGenerated] = useStateA([]);
  const [generating, setGenerating] = useStateA(false);

  const sources = [
    { id: 'prd', icon: 'docs', title: 'From requirements', desc: 'Paste a PRD, user story, or acceptance criteria. The agent extracts scenarios and generates Gherkin-style test cases.' },
    { id: 'api', icon: 'code', title: 'From OpenAPI spec', desc: 'Point at your OpenAPI/Swagger URL. Suitest generates contract + edge case tests for every endpoint.' },
    { id: 'url', icon: 'globe', title: 'From frontend URL', desc: 'Crawl your app at a URL. The agent explores user flows in an MCP browser and generates E2E tests.' },
    { id: 'mcp', icon: 'plug', title: 'Via MCP server', desc: 'Connect a custom MCP server. The agent uses your tools to author tests against any system.' },
  ];

  const startGen = () => {
    setGenerating(true);
    setGenerated([]);
    const seed = [
      { id: 'TC-1050', name: 'Google OAuth — happy path with consent grant', priority: 'P0', steps: 5 },
      { id: 'TC-1051', name: 'Google OAuth — user denies consent → redirect to /login?err=denied', priority: 'P1', steps: 4 },
      { id: 'TC-1052', name: 'Google OAuth — expired authorization code returns 401', priority: 'P1', steps: 3 },
      { id: 'TC-1053', name: 'Google OAuth — scope downgrade re-prompts consent', priority: 'P2', steps: 5 },
      { id: 'TC-1054', name: 'Google OAuth — CSRF state mismatch rejects callback', priority: 'P0', steps: 4 },
    ];
    seed.forEach((t, i) => setTimeout(() => setGenerated(prev => [...prev, t]), 400 + i * 280));
    setTimeout(() => setGenerating(false), 400 + seed.length * 280 + 200);
  };

  return (
    <div style={{position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(2px)', zIndex: 50, display: 'grid', placeItems: 'center'}}>
      <div style={{width: 'min(880px, 92vw)', maxHeight: '88vh', background: 'var(--bg-elev-1)', border: '1px solid var(--border)', borderRadius: 12, display: 'flex', flexDirection: 'column', overflow: 'hidden', boxShadow: '0 24px 64px rgba(0,0,0,0.5)'}}>
        <div style={{display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', borderBottom: '1px solid var(--border-subtle)'}}>
          <div style={{width: 26, height: 26, borderRadius: 7, background: 'var(--accent-dim)', color: 'var(--accent)', display: 'grid', placeItems: 'center'}}>
            <IconA name="sparkles" size={14}/>
          </div>
          <div>
            <div style={{fontSize: 14, fontWeight: 600}}>Generate test cases with AI</div>
            <div className="muted" style={{fontSize: 11.5}}>The agent will draft test cases you can review, edit, or run.</div>
          </div>
          <button className="icon-btn" style={{marginLeft: 'auto'}} onClick={onClose}><IconA name="x" size={14}/></button>
        </div>

        <div style={{padding: 18, overflowY: 'auto'}}>
          <div className="eyebrow">1 · Choose a source</div>
          <div className="gen-source-grid">
            {sources.map(s => (
              <div key={s.id} className={`gen-source${source === s.id ? ' active' : ''}`} onClick={() => setSource(s.id)}>
                <div className="gen-source-icon"><IconA name={s.icon} size={15}/></div>
                <div className="gen-source-title">{s.title}</div>
                <div className="gen-source-desc">{s.desc}</div>
              </div>
            ))}
          </div>

          <div className="eyebrow" style={{marginTop: 18}}>2 · Provide input</div>
          <div style={{marginTop: 8, background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px'}}>
            {source === 'prd' && (
              <textarea value={input} onChange={e => setInput(e.target.value)} style={{width: '100%', minHeight: 120, resize: 'vertical', fontSize: 12.5, lineHeight: 1.55, color: 'var(--fg-1)'}}/>
            )}
            {source === 'api' && (
              <div style={{display: 'flex', flexDirection: 'column', gap: 8}}>
                <div style={{display: 'flex', gap: 8, alignItems: 'center', fontFamily: 'var(--font-mono)', fontSize: 12.5}}>
                  <span style={{color: 'var(--fg-5)'}}>$</span>
                  <span style={{color: 'var(--fg-1)'}}>https://api.suitest.io/openapi.json</span>
                  <button className="btn btn-sm" style={{marginLeft: 'auto'}}><IconA name="refresh" size={10}/> Refetch</button>
                </div>
                <div className="muted" style={{fontSize: 12}}>47 endpoints discovered · 12 covered · <b style={{color: 'var(--fg-2)'}}>35 will be generated</b></div>
                <div style={{display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4}}>
                  {['GET /orders', 'POST /orders', 'PATCH /orders/:id', 'GET /products', 'POST /payments', 'GET /users/me', 'POST /webhooks'].map(e => (
                    <span key={e} className="badge neutral mono" style={{fontSize: 10.5}}>{e}</span>
                  ))}
                  <span className="muted mono" style={{fontSize: 11}}>+28 more</span>
                </div>
              </div>
            )}
            {source === 'url' && (
              <div style={{display: 'flex', flexDirection: 'column', gap: 8}}>
                <div style={{display: 'flex', gap: 8, alignItems: 'center', fontFamily: 'var(--font-mono)', fontSize: 12.5}}>
                  <IconA name="globe" size={12} style={{color: 'var(--fg-4)'}}/>
                  <span style={{color: 'var(--fg-1)'}}>https://app.suitest.io</span>
                  <span className="badge neutral mono" style={{marginLeft: 8, fontSize: 10.5}}>depth: 3</span>
                  <span className="badge neutral mono" style={{fontSize: 10.5}}>auth: oauth</span>
                </div>
                <div className="muted" style={{fontSize: 12}}>The MCP browser will crawl interactive flows and propose E2E tests for each.</div>
              </div>
            )}
            {source === 'mcp' && (
              <div style={{display: 'flex', flexDirection: 'column', gap: 8}}>
                <div style={{display: 'flex', gap: 8, alignItems: 'center', fontFamily: 'var(--font-mono)', fontSize: 12.5}}>
                  <IconA name="plug" size={12} style={{color: 'var(--accent)'}}/>
                  <span style={{color: 'var(--fg-1)'}}>browser-use://staging</span>
                  <span className="badge pass" style={{marginLeft: 8}}><span className="dot"></span>connected</span>
                </div>
                <div className="muted" style={{fontSize: 12}}>Tools available: <b style={{color: 'var(--fg-2)'}}>navigate, click, type, screenshot, wait_for_selector, evaluate</b></div>
              </div>
            )}
          </div>

          <div className="eyebrow" style={{marginTop: 18, display: 'flex', alignItems: 'center'}}>
            3 · Review generated cases
            <span style={{marginLeft: 'auto', fontFamily: 'var(--font-mono)', textTransform: 'none', letterSpacing: 0, color: 'var(--fg-4)', fontSize: 11}}>
              {generated.length} of 5 generated
            </span>
          </div>

          <div style={{marginTop: 8, minHeight: 220, background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 8, padding: generated.length ? 4 : 0, display: 'flex', flexDirection: 'column'}}>
            {!generated.length && !generating && (
              <div style={{display: 'grid', placeItems: 'center', flex: 1, padding: 32, textAlign: 'center', color: 'var(--fg-4)', fontSize: 12.5}}>
                <div>
                  <IconA name="sparkles" size={22} style={{color: 'var(--fg-5)', marginBottom: 8}}/>
                  <div>Click <b style={{color: 'var(--fg-2)'}}>Generate</b> below to produce test cases from your source.</div>
                </div>
              </div>
            )}
            {generating && !generated.length && (
              <div style={{display: 'grid', placeItems: 'center', flex: 1, padding: 32, color: 'var(--accent)', fontSize: 12.5}}>
                <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
                  <span className="dot" style={{width: 8, height: 8, borderRadius: '50%', background: 'var(--accent)', animation: 'pulse 1s infinite'}}></span>
                  Agent is reading your input...
                </div>
              </div>
            )}
            {generated.map((g, i) => (
              <div key={g.id} style={{display: 'grid', gridTemplateColumns: 'auto 80px 1fr auto auto', gap: 12, alignItems: 'center', padding: '9px 12px', borderBottom: i < generated.length - 1 ? '1px solid var(--border-subtle)' : 'none', animation: 'slideIn 0.3s ease-out'}}>
                <input type="checkbox" defaultChecked style={{accentColor: 'var(--accent)'}}/>
                <span className="mono" style={{fontSize: 11.5, color: 'var(--fg-4)'}}>{g.id}</span>
                <span style={{fontSize: 12.5, color: 'var(--fg-1)'}}>{g.name}</span>
                <span className="badge neutral mono" style={{fontSize: 10.5}}>{g.priority}</span>
                <span className="muted mono" style={{fontSize: 11}}>{g.steps} steps</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{display: 'flex', alignItems: 'center', gap: 10, padding: '12px 18px', borderTop: '1px solid var(--border-subtle)'}}>
          <span className="muted" style={{fontSize: 11.5}}>
            {generated.length > 0
              ? <><b style={{color: 'var(--accent)'}}>{generated.length} cases</b> ready · 23 steps total · est. 4m runtime</>
              : 'Suitest Agent v2.4 · uses your workspace context'
            }
          </span>
          <div style={{flex: 1}}/>
          <button className="btn btn-sm" onClick={onClose}>Cancel</button>
          {generated.length === 0
            ? <button className="btn btn-sm btn-primary" onClick={startGen} disabled={generating}>
                <IconA name="sparkles" size={11}/> {generating ? 'Generating...' : 'Generate'}
              </button>
            : <button className="btn btn-sm btn-primary" onClick={onClose}>
                <IconA name="check" size={11}/> Add {generated.length} to suite
              </button>
          }
        </div>
      </div>
      <style>{`@keyframes slideIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }`}</style>
    </div>
  );
}

window.DashboardView = DashboardView;
window.TestCasesView = TestCasesView;
