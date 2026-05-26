// Suitest — Runs, Defects, Analytics, Integrations, Traceability views
const { useState: useStateB, useEffect: useEffectB } = React;
const { Icon: IconB } = window;
const { ACTIVE_RUNS: RUNS_B, LOG_LINES: LOGS_B, DEFECTS, FLAKY_TESTS, INTEGRATIONS, REQUIREMENTS, SUITES: SUITES_B } = window.SuitestData;

// ============== RUNS ==============
function RunsView() {
  const [activeRun, setActiveRun] = useStateB('R-8841');
  const [logIdx, setLogIdx] = useStateB(LOGS_B.length);
  const run = RUNS_B.find(r => r.id === activeRun);

  // Streaming log effect (loops)
  useEffectB(() => {
    if (run?.status !== 'running') return;
    const id = setInterval(() => {
      setLogIdx(i => i >= LOGS_B.length ? 14 : i + 1);
    }, 1100);
    return () => clearInterval(id);
  }, [run?.status]);

  const visibleLogs = LOGS_B.slice(0, logIdx);

  return (
    <div className="runs-page">
      <div className="runs-summary">
        <div className="runs-now">
          <div className="eyebrow" style={{marginBottom: 6}}>Active right now</div>
          <div style={{display: 'flex', alignItems: 'baseline', gap: 6}}>
            <span style={{fontSize: 28, fontWeight: 600, letterSpacing: '-0.02em', fontVariantNumeric: 'tabular-nums'}}>2</span>
            <span className="muted" style={{fontSize: 12.5}}>running</span>
          </div>
          <div style={{display: 'flex', gap: 4, marginTop: 8}}>
            {[1,1,1,1,1,1,1,0,0].map((on, i) => (
              <div key={i} style={{width: 20, height: 4, borderRadius: 2, background: on ? 'var(--accent)' : 'var(--bg-elev-3)'}}/>
            ))}
          </div>
          <div className="muted" style={{fontSize: 11.5, marginTop: 6}}>7 of 9 MCP slots in use</div>
        </div>
        <div className="runs-counters">
          <div><div className="counter-label">Today</div><div className="counter-val tabular">62</div></div>
          <div><div className="counter-label">Passed</div><div className="counter-val tabular pass">59</div></div>
          <div><div className="counter-label">Failed</div><div className="counter-val tabular fail">3</div></div>
          <div><div className="counter-label">Avg duration</div><div className="counter-val tabular">11.8<span style={{fontSize: 14, color: 'var(--fg-4)'}}>s</span></div></div>
          <div><div className="counter-label">Queue</div><div className="counter-val tabular">0</div></div>
        </div>
      </div>

      <div className="runs-split">
        <div className="runs-list">
          {RUNS_B.map(r => (
            <div key={r.id} className={`run-item${r.id === activeRun ? ' active' : ''}`} onClick={() => setActiveRun(r.id)}>
              <div className="run-item-name">
                <RunDot status={r.status}/>
                <span style={{flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{r.name}</span>
              </div>
              <div className="run-item-meta mono">
                <span>{r.id}</span>
                <span>{r.branch}</span>
                <span>{r.duration}</span>
              </div>
              <div className="run-item-progress">
                <div className="progress-track">
                  <div className={`progress-fill${r.failed > 0 && r.status !== 'running' ? ' fail' : r.status === 'running' ? ' warn' : ''}`} style={{width: `${r.progress}%`}}/>
                </div>
                <div style={{display: 'flex', justifyContent: 'space-between', marginTop: 5, fontSize: 11, color: 'var(--fg-4)'}}>
                  <span className="mono">{r.passed}/{r.total} passed{r.failed > 0 && <span style={{color: 'var(--red)'}}> · {r.failed} failed</span>}</span>
                  <span className="mono">{r.progress}%</span>
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="run-detail">
          <div className="run-detail-head">
            <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8}}>
              <span className="badge running"><span className="dot"></span>{run.status}</span>
              <span className="mono muted" style={{fontSize: 11.5}}>{run.id}</span>
              <span className="muted" style={{fontSize: 11.5}}>· {run.triggered}</span>
              <div style={{flex: 1}}/>
              <button className="btn btn-sm"><IconB name="stop" size={11}/> Cancel</button>
              <button className="btn btn-sm"><IconB name="refresh" size={11}/> Re-run</button>
              <button className="btn btn-sm"><IconB name="expand" size={11}/> Fullscreen</button>
            </div>
            <h1 className="h1" style={{margin: '4px 0 6px', fontSize: 20}}>{run.name}</h1>
            <div style={{display: 'flex', flexWrap: 'wrap', gap: '6px 18px', fontSize: 12, color: 'var(--fg-3)'}}>
              <span><IconB name="branch" size={11}/> <span className="mono" style={{color: 'var(--fg-2)', marginLeft: 4}}>{run.branch}</span> @ <span className="mono" style={{color: 'var(--fg-2)'}}>{run.commit}</span></span>
              <span><IconB name="globe" size={11}/> <span style={{marginLeft: 4}}>{run.env}</span></span>
              <span><IconB name="clock" size={11}/> <span style={{marginLeft: 4}}>{run.duration} elapsed</span></span>
              <span><IconB name="bot" size={11}/> <span style={{marginLeft: 4}}>browser-use MCP · session #7421</span></span>
            </div>
          </div>

          <div className="run-tabs">
            <div className="run-tab active">Logs <span className="count">{LOGS_B.length}</span></div>
            <div className="run-tab">Steps <span className="count">{run.total}</span></div>
            <div className="run-tab">Artifacts <span className="count">14</span></div>
            <div className="run-tab">Browser <span className="count">live</span></div>
            <div className="run-tab">Network <span className="count">28</span></div>
          </div>

          <div className="run-detail-body">
            <div className="logs">
              {visibleLogs.map((l, i) => (
                <div className="log-line" key={i}>
                  <span className="log-time">{l.t}</span>
                  <span className={`log-level ${l.l}`}>{l.l === 'ok' ? 'PASS' : l.l.toUpperCase()}</span>
                  <span className="log-msg" dangerouslySetInnerHTML={{__html: l.m}}/>
                </div>
              ))}
              {run.status === 'running' && (
                <div className="log-line">
                  <span className="log-time">{logTimeNow()}</span>
                  <span className="log-level info">INFO</span>
                  <span className="log-msg" style={{color: 'var(--accent)'}}>▌</span>
                </div>
              )}
            </div>

            <div className="browser-preview">
              <div className="bp-head">
                <span className="badge running"><span className="dot"></span>MCP session</span>
                <span style={{flex: 1}}/>
                <span className="mono muted" style={{fontSize: 10.5}}>1280×800 · Chrome 124</span>
              </div>
              <div style={{padding: '8px 14px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 6}}>
                <span style={{width: 8, height: 8, borderRadius: '50%', background: 'var(--red)'}}/>
                <span style={{width: 8, height: 8, borderRadius: '50%', background: 'var(--amber)'}}/>
                <span style={{width: 8, height: 8, borderRadius: '50%', background: 'var(--accent)'}}/>
                <div className="bp-url" style={{marginLeft: 8}}>accounts.google.com/o/oauth2/v2/auth?client_id=...</div>
              </div>
              <div className="bp-stage">
                <div className="bp-shot">
                  <BrowserMockOAuth/>
                </div>
                <div className="bp-steps">
                  <div className="bp-step done"><span className="bp-step-num">1.</span>navigate → /login</div>
                  <div className="bp-step done"><span className="bp-step-num">2.</span>click → button[data-provider="google"]</div>
                  <div className="bp-step done"><span className="bp-step-num">3.</span>type → #identifierId "qa@suitest.io"</div>
                  <div className="bp-step active"><span className="bp-step-num">4.</span>click → #submit_approve_access</div>
                  <div className="bp-step"><span className="bp-step-num">5.</span>assert → GET /api/me → 200</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function logTimeNow() {
  const d = new Date(); const pad = n => String(n).padStart(2, '0');
  return `14:32:${pad(7 + (d.getSeconds() % 8))}.${pad(Math.floor(d.getMilliseconds()/10))}`;
}

function RunDot({ status }) {
  const c = status === 'pass' ? 'var(--accent)' : status === 'fail' ? 'var(--red)' : status === 'warn' ? 'var(--amber)' : 'var(--blue)';
  const anim = status === 'running' ? 'pulse 1.2s infinite' : 'none';
  return <span style={{width: 7, height: 7, borderRadius: '50%', background: c, animation: anim, boxShadow: status === 'running' ? `0 0 0 3px ${c}33` : 'none'}}/>;
}

function BrowserMockOAuth() {
  return (
    <div style={{position: 'absolute', inset: 0, padding: '22px 18px', display: 'flex', flexDirection: 'column', gap: 12, fontSize: 11}}>
      <div style={{textAlign: 'center', color: '#fff', fontSize: 13, fontWeight: 500}}>Google</div>
      <div style={{textAlign: 'center', color: 'rgba(255,255,255,0.8)', fontSize: 11, marginTop: -6}}>Choose an account</div>
      <div style={{height: 1, background: 'rgba(255,255,255,0.1)', margin: '6px 0'}}/>
      <div style={{display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', background: 'rgba(255,255,255,0.05)', borderRadius: 6}}>
        <div style={{width: 22, height: 22, borderRadius: '50%', background: 'linear-gradient(135deg, #ea4335, #4285f4)'}}/>
        <div style={{flex: 1}}>
          <div style={{color: '#fff', fontSize: 10.5, fontWeight: 500}}>QA Suitest</div>
          <div style={{color: 'rgba(255,255,255,0.5)', fontSize: 9.5}}>qa@suitest.io</div>
        </div>
      </div>
      <div style={{color: 'rgba(255,255,255,0.7)', fontSize: 10, marginTop: 4}}>This will allow Suitest to:</div>
      <div style={{color: 'rgba(255,255,255,0.85)', fontSize: 10}}>✓ See your name & email<br/>✓ Access your profile picture</div>
      <div style={{flex: 1}}/>
      <div style={{display: 'flex', gap: 6, justifyContent: 'flex-end'}}>
        <div style={{padding: '5px 10px', borderRadius: 4, color: 'rgba(255,255,255,0.6)', fontSize: 10}}>Cancel</div>
        <div style={{padding: '5px 10px', borderRadius: 4, background: 'var(--accent)', color: 'var(--accent-fg)', fontSize: 10, fontWeight: 600, boxShadow: '0 0 0 2px var(--accent-ring)', animation: 'pulse 1.5s infinite'}}>Allow</div>
      </div>
    </div>
  );
}

// ============== DEFECTS ==============
function DefectsView() {
  return (
    <>
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">
            Defects
            <span className="badge fail"><span className="dot"></span>12 open</span>
            <span className="badge ai"><span className="dot"></span>9 auto-filed by agent</span>
          </h1>
          <div className="page-sub">Failures sync to Jira in real time with full traceability back to test cases and requirements.</div>
        </div>
        <button className="btn"><IconB name="filter" size={12}/> All severities</button>
        <button className="btn"><IconB name="link" size={12}/> Jira: SUIT</button>
      </div>

      <div className="defects-page">
        {DEFECTS.map(d => <DefectCard key={d.id} d={d}/>)}
      </div>
    </>
  );
}

function DefectCard({ d }) {
  const sevBadge = d.severity === 'critical' ? 'fail' : d.severity === 'high' ? 'warn' : 'info';
  return (
    <div className="defect-card">
      <div className="defect-head">
        <span className={`badge ${sevBadge}`}><span className="dot"></span>{d.severity}</span>
        <a className="jira-link"><IconB name="link" size={10}/>{d.id}</a>
        <span className="muted mono" style={{fontSize: 11}}>· filed {d.age} ago</span>
        <div className="defect-title" style={{flex: 1, marginLeft: 6}}>{d.title}</div>
        <button className="btn btn-sm"><IconB name="eye" size={11}/> View in Jira</button>
        <button className="btn btn-sm btn-primary"><IconB name="play" size={11}/> Re-run</button>
      </div>

      <div className="grid-2" style={{gap: 12}}>
        <div className="trace-line">{d.trace.split('\n').map((line, i) => (
          <div key={i}>
            {line.includes('AssertionError') || line.includes('expected') ? <span className="err">{line}</span> : line}
          </div>
        ))}</div>
        <div style={{padding: '10px 12px', background: 'var(--violet-bg)', border: '1px solid rgba(167, 139, 250, 0.2)', borderRadius: 6, display: 'flex', gap: 10}}>
          <div style={{width: 18, height: 18, borderRadius: 4, background: 'rgba(167, 139, 250, 0.2)', color: 'var(--violet)', display: 'grid', placeItems: 'center', flexShrink: 0, marginTop: 2}}>
            <IconB name="spark" size={11}/>
          </div>
          <div style={{flex: 1, fontSize: 12, color: 'var(--fg-2)', lineHeight: 1.55}}>
            <div style={{color: 'var(--violet)', fontSize: 10.5, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3}}>Agent diagnosis</div>
            {d.aiNote}
          </div>
        </div>
      </div>

      <div className="defect-meta-row">
        <span><IconB name="flask" size={10}/> Test case <b className="mono">{d.testId}</b></span>
        <span><IconB name="play" size={10}/> Run <b className="mono">{d.run}</b></span>
        <span><IconB name="folder" size={10}/> Component <b>{d.component}</b></span>
        <span><IconB name="user" size={10}/> Assignee <b>{d.assignee}</b></span>
      </div>
    </div>
  );
}

// ============== ANALYTICS ==============
function AnalyticsView() {
  const heat = Array.from({length: 280}, () => {
    const r = Math.random();
    if (r < 0.55) return 0;
    if (r < 0.78) return 1;
    if (r < 0.92) return 2;
    if (r < 0.98) return 3;
    return 4;
  });

  return (
    <>
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">Analytics</h1>
          <div className="page-sub">Quality signals across coverage, stability, and release readiness.</div>
        </div>
        <button className="btn"><IconB name="filter" size={12}/> Last 30 days</button>
        <button className="btn"><IconB name="docs" size={12}/> Export</button>
      </div>

      <div className="analytics-page">
        <div className="grid-3">
          <div className="card" style={{padding: '18px 20px'}}>
            <ReadinessGaugeB value={86} label="Release readiness" sub="Next deploy: Thursday"/>
          </div>
          <div className="card" style={{padding: '18px 20px'}}>
            <ReadinessGaugeB value={92} label="Test coverage" sub="247 of 268 cases automated"/>
          </div>
          <div className="card" style={{padding: '18px 20px'}}>
            <ReadinessGaugeB value={96.4} label="Pass rate (7d)" sub="+2.1% vs prior week"/>
          </div>
        </div>

        <div className="grid-2">
          <div className="card">
            <div className="card-head">
              <span className="card-title">Pass rate trend</span>
              <span className="muted" style={{marginLeft: 'auto', fontSize: 11.5}}>96.4% · 11 days</span>
            </div>
            <div className="card-body">
              <PassRateChartB/>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <span className="card-title">Flaky tests</span>
              <span className="badge warn" style={{marginLeft: 'auto'}}><span className="dot"></span>5 detected</span>
            </div>
            <div className="flaky-list">
              {FLAKY_TESTS.map(f => (
                <div className="flaky-item" key={f.name}>
                  <span className="flaky-name">{f.name}</span>
                  <span className="muted mono" style={{fontSize: 11}}>{f.runs} runs</span>
                  <span className="flaky-rate">{f.rate.toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <span className="card-title">Test execution heatmap · last 14 days × hours</span>
            <span className="muted" style={{marginLeft: 'auto', fontSize: 11.5}}>2,847 runs · darker = more activity</span>
          </div>
          <div className="card-body">
            <div className="heatmap">
              {heat.map((v, i) => {
                const colors = ['var(--bg-elev-3)', 'rgba(74,222,128,0.25)', 'rgba(74,222,128,0.5)', 'rgba(74,222,128,0.75)', 'var(--accent)'];
                return <div className="heat-cell" key={i} style={{background: colors[v]}}/>;
              })}
            </div>
            <div style={{display: 'flex', alignItems: 'center', gap: 12, marginTop: 12, fontSize: 11, color: 'var(--fg-4)'}}>
              <span>Less</span>
              <div style={{display: 'flex', gap: 3}}>
                <div style={{width: 11, height: 11, borderRadius: 2, background: 'var(--bg-elev-3)'}}/>
                <div style={{width: 11, height: 11, borderRadius: 2, background: 'rgba(74,222,128,0.25)'}}/>
                <div style={{width: 11, height: 11, borderRadius: 2, background: 'rgba(74,222,128,0.5)'}}/>
                <div style={{width: 11, height: 11, borderRadius: 2, background: 'rgba(74,222,128,0.75)'}}/>
                <div style={{width: 11, height: 11, borderRadius: 2, background: 'var(--accent)'}}/>
              </div>
              <span>More</span>
              <span style={{marginLeft: 'auto'}}>Peak hour: <b style={{color: 'var(--fg-2)'}}>14:00 WIB</b> · 47 runs/hr</span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function ReadinessGaugeB({ value, label, sub }) {
  const r = 38, c = 2 * Math.PI * r;
  const offset = c - (value / 100) * c;
  return (
    <div style={{display: 'flex', alignItems: 'center', gap: 16}}>
      <svg width="90" height="90" viewBox="0 0 90 90">
        <circle cx="45" cy="45" r={r} fill="none" stroke="var(--bg-elev-3)" strokeWidth="7"/>
        <circle cx="45" cy="45" r={r} fill="none" stroke="var(--accent)" strokeWidth="7"
          strokeLinecap="round" strokeDasharray={c} strokeDashoffset={offset}
          transform="rotate(-90 45 45)"/>
        <text x="45" y="49" textAnchor="middle" fill="var(--fg-1)" fontSize="18" fontWeight="600" style={{fontVariantNumeric: 'tabular-nums'}}>{Math.round(value)}<tspan fontSize="10" fill="var(--fg-4)">%</tspan></text>
      </svg>
      <div>
        <div style={{fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--fg-4)', fontWeight: 500}}>{label}</div>
        <div className="muted" style={{fontSize: 12, marginTop: 3}}>{sub}</div>
      </div>
    </div>
  );
}

function PassRateChartB() {
  const data = window.SuitestData.PASS_RATE_HISTORY;
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
          <linearGradient id="prgrad2" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.25"/>
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0"/>
          </linearGradient>
        </defs>
        {[80, 90, 100].map(t => {
          const y = h - pad - ((t - min) / (max - min)) * (h - pad * 2);
          return <g key={t}>
            <line x1={pad} y1={y} x2={w - pad} y2={y} stroke="var(--border-subtle)" strokeDasharray="2 4"/>
            <text x={6} y={y + 3} fill="var(--fg-5)" fontSize="9.5">{t}%</text>
          </g>;
        })}
        <path d={area} fill="url(#prgrad2)"/>
        <path d={path} fill="none" stroke="var(--accent)" strokeWidth="1.8"/>
        {xs.map((x, i) => (
          <g key={i}>
            <circle cx={x} cy={ys[i]} r="2.5" fill="var(--bg-base)" stroke="var(--accent)" strokeWidth="1.5"/>
          </g>
        ))}
      </svg>
    </div>
  );
}

// ============== INTEGRATIONS ==============
function IntegrationsView() {
  const groups = {};
  INTEGRATIONS.forEach(i => { groups[i.cat] = groups[i.cat] || []; groups[i.cat].push(i); });

  return (
    <>
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">Integrations</h1>
          <div className="page-sub">CI/CD pipelines, issue trackers, and MCP servers wired into your test workflow.</div>
        </div>
        <button className="btn"><IconB name="plus" size={12}/> Add custom MCP</button>
      </div>

      <div className="integrations-page">
        {Object.entries(groups).map(([cat, items]) => (
          <div key={cat}>
            <div className="eyebrow" style={{marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8}}>
              {cat}
              {cat === 'MCP Server' && <span className="badge ai" style={{textTransform: 'none', letterSpacing: 0}}><span className="dot"></span>Agent runtime</span>}
            </div>
            <div className="integ-grid">
              {items.map(i => <IntegrationCard key={i.name} i={i}/>)}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

function IntegrationCard({ i }) {
  return (
    <div className={`integ-card${i.connected ? ' connected' : ''}`}>
      <div className="integ-head">
        <div className="integ-logo" style={i.highlight ? {background: 'var(--accent-dim)', color: 'var(--accent)'} : {}}>{i.logo}</div>
        <div style={{flex: 1}}>
          <div className="integ-name">{i.name}</div>
          <div className="integ-cat">{i.cat}</div>
        </div>
        {i.connected
          ? <span className="badge pass"><span className="dot"></span>connected</span>
          : <span className="badge neutral"><span className="dot"></span>off</span>
        }
      </div>
      <div className="integ-desc">{i.desc}</div>
      <div className="integ-foot">
        {i.connected
          ? <>
              <span className="muted">{i.since}</span>
              <button className="btn btn-sm btn-ghost" style={{marginLeft: 'auto'}}>Configure</button>
            </>
          : <button className="btn btn-sm btn-primary" style={{marginLeft: 'auto'}}>Connect</button>
        }
      </div>
    </div>
  );
}

// ============== TRACEABILITY ==============
function TraceabilityView() {
  const [activeReq, setActiveReq] = useStateB('REQ-401');
  const req = REQUIREMENTS.find(r => r.id === activeReq);
  const linkedTests = new Set(req?.tests || []);
  const linkedDefects = new Set(req?.defects || []);

  const allTests = SUITES_B.flatMap(s => s.cases.map(c => ({...c, suite: s.name})));
  const allDefects = DEFECTS;

  return (
    <>
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">Traceability</h1>
          <div className="page-sub">Bi-directional links between business requirements, test cases, and defects.</div>
        </div>
        <button className="btn"><IconB name="filter" size={12}/> Sprint 24</button>
        <button className="btn"><IconB name="docs" size={12}/> Export matrix</button>
      </div>

      <div className="trace-page">
        <div style={{display: 'flex', gap: 12, alignItems: 'center', padding: '10px 14px', background: 'var(--bg-elev-1)', border: '1px solid var(--border-subtle)', borderRadius: 8, fontSize: 12.5}}>
          <IconB name="spark" size={14} style={{color: 'var(--violet)'}}/>
          <span>Coverage map · <b style={{color: 'var(--fg-1)'}}>6 of 6 requirements</b> have linked test cases · <b style={{color: 'var(--red)'}}>2 with open defects</b></span>
          <span style={{flex: 1}}/>
          <button className="btn btn-sm btn-ghost"><IconB name="sparkles" size={11}/> Find gaps</button>
        </div>

        <div className="trace-grid">
          <div className="trace-col">
            <div className="trace-col-head">Requirements · {REQUIREMENTS.length}</div>
            {REQUIREMENTS.map(r => (
              <div key={r.id} className={`trace-item${r.id === activeReq ? ' active' : ''}`} onClick={() => setActiveReq(r.id)}>
                <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
                  <span className="trace-item-id">{r.id}</span>
                  {r.defects.length > 0 && <span className="badge fail" style={{padding: '1px 5px', fontSize: 10}}>!</span>}
                </div>
                <div className="trace-item-name">{r.name}</div>
                <div className="muted mono" style={{fontSize: 10.5, marginTop: 3}}>{r.tests.length} tests · {r.defects.length} defects</div>
              </div>
            ))}
          </div>

          <div className="trace-col">
            <div className="trace-col-head">Test cases · {linkedTests.size} linked</div>
            {allTests.map(t => (
              <div key={t.id} className={`trace-item${linkedTests.has(t.id) ? ' linked' : ''}`}>
                <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
                  <SourceDotB src={t.source} status={t.status}/>
                  <span className="trace-item-id">{t.id}</span>
                  <span className="muted mono" style={{fontSize: 10, marginLeft: 'auto'}}>{t.source.toUpperCase()}</span>
                </div>
                <div className="trace-item-name" style={{fontSize: 12}}>{t.name}</div>
              </div>
            ))}
          </div>

          <div className="trace-col">
            <div className="trace-col-head">Defects · {linkedDefects.size} linked</div>
            {allDefects.map(d => (
              <div key={d.id} className={`trace-item${linkedDefects.has(d.id) ? ' linked' : ''}`}>
                <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
                  <span className="trace-item-id">{d.id}</span>
                  <span className={`badge ${d.severity === 'critical' ? 'fail' : d.severity === 'high' ? 'warn' : 'info'}`} style={{padding: '1px 5px', fontSize: 9.5, marginLeft: 'auto'}}>{d.severity}</span>
                </div>
                <div className="trace-item-name" style={{fontSize: 12}}>{d.title}</div>
              </div>
            ))}
            {Array.from({length: 4}).map((_, i) => (
              <div key={`empty-${i}`} className="trace-item" style={{opacity: 0.4}}>
                <div className="trace-item-id">—</div>
                <div className="trace-item-name muted" style={{fontSize: 12}}>No defect</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

function SourceDotB({ src, status }) {
  const color = status === 'fail' ? 'var(--red)' : status === 'warn' ? 'var(--amber)' : 'var(--accent)';
  return <span style={{width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0}}/>;
}

// ============== INBOX & DOCS (lightweight) ==============
function InboxView() {
  return (
    <>
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">Inbox <span className="badge neutral">3 unread</span></h1>
          <div className="page-sub">Approvals, alerts, and items the agent flagged for your review.</div>
        </div>
      </div>
      <div className="dash">
        {[
          { icon: 'bug', tone: 'fail', t: 'Deploy gate failed for staging', b: 'SUIT-1284 (critical) blocks promotion. Agent suggests reverting commit 2b9d4c0 or applying patch in PR #3422.', time: '4m ago' },
          { icon: 'sparkles', tone: 'ai', t: 'Promote 12 AI-generated tests to gating', b: 'These tests have run 50+ times with 100% pass rate. Promoting will move them into the smoke suite.', time: '32m ago' },
          { icon: 'docs', tone: 'default', t: 'New PRD section detected', b: 'PRD-2026-Q1 was updated with a new payment refund flow. The agent drafted 4 test cases — review and accept?', time: '1h ago' },
        ].map((it, i) => (
          <div key={i} className="card" style={{padding: '14px 16px', display: 'flex', gap: 12}}>
            <div className={`activity-icon ${it.tone}`} style={{width: 30, height: 30}}><IconB name={it.icon} size={14}/></div>
            <div style={{flex: 1}}>
              <div style={{fontSize: 13.5, fontWeight: 600, marginBottom: 3}}>{it.t}</div>
              <div className="muted" style={{fontSize: 12.5, lineHeight: 1.5}}>{it.b}</div>
              <div style={{display: 'flex', gap: 8, marginTop: 10}}>
                <button className="btn btn-sm btn-primary">Review</button>
                <button className="btn btn-sm">Dismiss</button>
                <span className="muted mono" style={{fontSize: 11, marginLeft: 'auto', alignSelf: 'center'}}>{it.time}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

function DocsView() {
  return (
    <>
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">Docs & specs</h1>
          <div className="page-sub">Indexed sources the agent reads to generate and maintain your tests.</div>
        </div>
        <button className="btn btn-primary"><IconB name="plus" size={12}/> Add source</button>
      </div>
      <div className="dash">
        <div className="grid-2">
          {[
            { name: 'PRD-2026-Q1', t: 'Product Requirements Document', meta: 'Notion · 142 pages · indexed 2h ago', tests: 47, icon: 'docs' },
            { name: 'openapi.json', t: 'OpenAPI v3.1 spec', meta: 'api.suitest.io · 47 endpoints · indexed 18m ago', tests: 12, icon: 'code' },
            { name: 'app.suitest.io', t: 'Frontend crawl', meta: 'MCP browser · 28 routes · indexed 6h ago', tests: 64, icon: 'globe' },
            { name: 'User Stories — Sprint 24', t: 'Linear', meta: '34 issues · indexed 22m ago', tests: 28, icon: 'file' },
          ].map(s => (
            <div key={s.name} className="card" style={{padding: '16px 18px'}}>
              <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10}}>
                <div style={{width: 32, height: 32, borderRadius: 7, background: 'var(--bg-elev-3)', display: 'grid', placeItems: 'center'}}>
                  <IconB name={s.icon} size={15}/>
                </div>
                <div style={{flex: 1}}>
                  <div style={{fontSize: 13.5, fontWeight: 600}}>{s.name}</div>
                  <div className="muted" style={{fontSize: 11.5}}>{s.t}</div>
                </div>
                <span className="badge pass"><span className="dot"></span>synced</span>
              </div>
              <div className="muted" style={{fontSize: 12}}>{s.meta}</div>
              <div style={{display: 'flex', gap: 8, marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border-subtle)', alignItems: 'center'}}>
                <span className="mono" style={{fontSize: 12, color: 'var(--accent)'}}>{s.tests} test cases</span>
                <span className="muted" style={{fontSize: 11.5}}>generated from this source</span>
                <button className="btn btn-sm" style={{marginLeft: 'auto'}}>Re-sync</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

window.RunsView = RunsView;
window.DefectsView = DefectsView;
window.AnalyticsView = AnalyticsView;
window.IntegrationsView = IntegrationsView;
window.TraceabilityView = TraceabilityView;
window.InboxView = InboxView;
window.DocsView = DocsView;
