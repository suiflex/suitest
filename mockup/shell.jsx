// Suitest — app shell, sidebar, topbar, AI panel
const { useState, useEffect, useRef, useMemo } = React;
const { Icon } = window;

// ===== Sidebar =====
function Sidebar({ route, setRoute }) {
  const navItems = [
    { section: 'WORKSPACE', items: [
      { id: 'dashboard', label: 'Dashboard', icon: 'dashboard' },
      { id: 'inbox', label: 'Inbox', icon: 'inbox', count: 3 },
    ]},
    { section: 'TESTING', items: [
      { id: 'cases', label: 'Test Cases', icon: 'flask', count: 247 },
      { id: 'runs', label: 'Test Runs', icon: 'play', live: true },
      { id: 'defects', label: 'Defects', icon: 'bug', count: 12 },
    ]},
    { section: 'INSIGHTS', items: [
      { id: 'analytics', label: 'Analytics', icon: 'chart' },
      { id: 'trace', label: 'Traceability', icon: 'network' },
    ]},
    { section: 'CONFIG', items: [
      { id: 'integrations', label: 'Integrations', icon: 'plug' },
      { id: 'docs', label: 'Docs & specs', icon: 'docs' },
    ]},
  ];
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="brand-mark">s</div>
        <div className="brand-name">sui<b>test</b></div>
        <div style={{marginLeft: 'auto', display: 'flex', gap: 4}}>
          <button className="icon-btn" title="Notifications"><Icon name="bell" size={13}/></button>
        </div>
      </div>

      <div className="workspace-picker">
        <div className="workspace-avatar">N</div>
        <div className="workspace-name">Nusantara Retail</div>
        <Icon name="chevDown" size={12} className="workspace-chev"/>
      </div>

      <div className="nav">
        {navItems.map(sec => (
          <div className="nav-section" key={sec.section}>
            <div className="nav-section-label">{sec.section}</div>
            {sec.items.map(it => (
              <div
                key={it.id}
                className={`nav-item${route === it.id ? ' active' : ''}`}
                onClick={() => setRoute(it.id)}
              >
                <Icon name={it.icon} size={14} className="nav-icon"/>
                <span>{it.label}</span>
                {it.live && <span className="nav-dot"/>}
                {it.count != null && <span className="nav-count">{it.count}</span>}
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="sidebar-footer">
        <div className="user-avatar">MP</div>
        <div className="user-info">
          <div className="user-name">Maya Putri</div>
          <div className="user-role">QA Lead</div>
        </div>
        <button className="icon-btn"><Icon name="settings" size={13}/></button>
      </div>
    </aside>
  );
}

// ===== Topbar =====
function Topbar({ crumbs = [], actions = null }) {
  return (
    <div className="topbar">
      <div className="crumbs">
        {crumbs.map((c, i) => (
          <React.Fragment key={i}>
            {i > 0 && <span className="sep"><Icon name="chev" size={11}/></span>}
            <span className={i === crumbs.length - 1 ? 'current' : 'item'}>{c}</span>
          </React.Fragment>
        ))}
      </div>
      <div className="topbar-spacer"></div>
      <div className="topbar-search">
        <Icon name="search" size={12}/>
        <span>Search or run command...</span>
        <span className="kbd">⌘K</span>
      </div>
      {actions}
      <button className="icon-btn" title="Help"><Icon name="book" size={14}/></button>
      <button className="btn btn-sm"><Icon name="plus" size={12}/> New</button>
    </div>
  );
}

// ===== AI Panel =====
function AiPanel({ context }) {
  const [mode, setMode] = useState('agent'); // agent | ask | generate
  const [input, setInput] = useState('');
  const threadRef = useRef(null);

  const thread = AI_THREADS[context] || AI_THREADS.dashboard;

  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight;
  }, [context]);

  return (
    <aside className="ai-panel">
      <div className="ai-header">
        <div className="ai-avatar">
          <Icon name="spark" size={13}/>
        </div>
        <div style={{flex: 1, minWidth: 0}}>
          <div className="ai-title">Suitest Agent</div>
          <div className="ai-sub">v2.4 · ready · 4 sessions</div>
        </div>
        <button className="icon-btn" title="History"><Icon name="clock" size={13}/></button>
        <button className="icon-btn" title="More"><Icon name="more" size={13}/></button>
      </div>

      <div className="ai-thread" ref={threadRef}>
        {thread.map((m, i) => <AiMessage key={i} m={m}/>)}
      </div>

      <div className="ai-composer">
        <div className="ai-mode">
          <button className={`ai-mode-btn${mode === 'agent' ? ' active' : ''}`} onClick={() => setMode('agent')}>Agent</button>
          <button className={`ai-mode-btn${mode === 'generate' ? ' active' : ''}`} onClick={() => setMode('generate')}>Generate</button>
          <button className={`ai-mode-btn${mode === 'ask' ? ' active' : ''}`} onClick={() => setMode('ask')}>Ask</button>
        </div>
        <div className="ai-input-wrap">
          <textarea
            className="ai-input"
            placeholder={
              mode === 'agent' ? 'Tell the agent what to do — e.g. "Run the failing OAuth test in MCP browser"'
              : mode === 'generate' ? 'Paste a requirement, URL, or API endpoint to generate test cases...'
              : 'Ask about your test suite, runs, or defects...'
            }
            value={input}
            onChange={e => setInput(e.target.value)}
            rows={2}
          />
          <div className="ai-input-row">
            <button className="ai-attach-btn"><Icon name="paperclip" size={11}/> PRD</button>
            <button className="ai-attach-btn"><Icon name="globe" size={11}/> URL</button>
            <button className="ai-attach-btn"><Icon name="code" size={11}/> API</button>
            <button className="ai-send"><Icon name="send" size={11}/> Send</button>
          </div>
        </div>
      </div>
    </aside>
  );
}

function AiMessage({ m }) {
  return (
    <div className="ai-msg">
      <div className={`ai-msg-role ${m.role}`}>
        <span className="role-dot"></span>
        <span>{m.role === 'agent' ? 'Suitest Agent' : 'You'}</span>
        <span style={{marginLeft: 'auto', color: 'var(--fg-5)'}}>{m.time}</span>
      </div>
      <div className="ai-msg-body" dangerouslySetInnerHTML={{__html: m.body}} />
      {m.tool && (
        <div className="ai-tool">
          <div className="ai-tool-head">
            <Icon name="terminal" size={11}/>
            <span>{m.tool.name}</span>
            {m.tool.status === 'ok' && <span className="ok" style={{marginLeft: 'auto'}}>✓ {m.tool.duration}</span>}
            {m.tool.status === 'running' && <span style={{marginLeft: 'auto', color: 'var(--blue)'}}>running...</span>}
          </div>
          <div className="ai-tool-body" dangerouslySetInnerHTML={{__html: m.tool.output}}/>
        </div>
      )}
      {m.suggestions && (
        <div className="ai-suggestions">
          {m.suggestions.map((s, i) => (
            <button className="ai-chip" key={i}>
              <span className="chip-icon"><Icon name={s.icon || 'spark'} size={11}/></span>
              <span>{s.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ===== AI Thread content per route =====
const AI_THREADS = {
  dashboard: [
    { role: 'agent', time: '14:28', body: 'Good afternoon, Maya. I monitored 47 runs since your last sign-in. <b style="color:var(--fg-1)">3 new defects</b> auto-filed in Jira overnight, all linked to the OAuth refactor on <code>feat/oauth</code>.',
      suggestions: [
        { icon: 'play', label: 'Re-run failing tests on main' },
        { icon: 'sparkles', label: 'Summarize this week\'s flaky tests' },
        { icon: 'bug', label: 'Show me SUIT-1284 root cause' },
      ]
    },
    { role: 'agent', time: '14:30', body: 'I noticed <code>checkout.stripe.declined_card</code> failed twice with the same timing anomaly. Want me to mark it flaky and isolate it from the gating run?',
      tool: { name: 'analyze.flaky_pattern', status: 'ok', duration: '1.2s',
        output: '<div><span class="k">test:</span> <span class="v">checkout.stripe.declined_card</span></div><div><span class="k">fails_in:</span> <span class="v">14.3% of last 56 runs</span></div><div><span class="k">pattern:</span> <span class="v">timing — Stripe API latency &gt; 800ms</span></div>'
      }
    },
  ],
  cases: [
    { role: 'user', time: '14:18', body: 'Generate test cases for the new OAuth Google sign-in flow. Spec is in PRD-2026-Q1.' },
    { role: 'agent', time: '14:18', body: 'Reading <code>PRD-2026-Q1 § 4.2</code>... extracted 3 user stories and 7 acceptance criteria. Generating <b style="color:var(--fg-1)">5 test cases</b> covering happy path, consent denial, expired token, scope mismatch, and CSRF protection.',
      tool: { name: 'docs.read + generate.test_cases', status: 'ok', duration: '4.8s',
        output: '<div><span class="k">source:</span> <span class="v">PRD-2026-Q1 § 4.2</span></div><div><span class="k">generated:</span> <span class="v">TC-1045 → TC-1049 (5 cases, 23 steps)</span></div><div><span class="k">coverage:</span> <span class="v">7/7 acceptance criteria</span></div>'
      }
    },
    { role: 'agent', time: '14:19', body: 'TC-1045 is currently selected. I drafted Playwright assertions for each step. The agent flagged step 5 as <span style="color:var(--red)">likely to fail</span> — your session cookie domain changed in commit <code>2b9d4c0</code>.',
      suggestions: [
        { icon: 'play', label: 'Run TC-1045 in MCP browser now' },
        { icon: 'diff', label: 'Show suggested fix for cookie domain' },
        { icon: 'plus', label: 'Add edge case: revoked Google account' },
      ]
    },
  ],
  runs: [
    { role: 'agent', time: '14:32', body: 'R-8841 is executing TC-1045 step 4/5. The MCP browser took 813ms to approve the consent screen — above your 500ms threshold. I\'ll flag this as a perf regression if it repeats.' },
    { role: 'agent', time: '14:32', body: 'Step 5 failed. <code>GET /api/me</code> returned <span style="color:var(--red)">403</span>. I\'m capturing artifacts and filing the defect now.',
      tool: { name: 'defects.create + jira.sync', status: 'ok', duration: '2.1s',
        output: '<div><span class="k">ticket:</span> <span class="v">SUIT-1284 created</span></div><div><span class="k">linked:</span> <span class="v">TC-1045 ↔ REQ-401 ↔ commit 2b9d4c0</span></div><div><span class="k">assignee:</span> <span class="v">maya@suitest.io</span></div>'
      },
      suggestions: [
        { icon: 'eye', label: 'Open SUIT-1284 in Jira' },
        { icon: 'spark', label: 'Suggest a fix' },
      ]
    },
  ],
  defects: [
    { role: 'agent', time: '14:35', body: 'I reviewed 3 active defects. SUIT-1284 (critical) blocks the staging release. Root cause is a cookie domain mismatch — the fix is a one-line change in <code>auth/cookie.ts</code>.',
      tool: { name: 'analyze.root_cause', status: 'ok', duration: '3.4s',
        output: '<div><span class="k">defect:</span> <span class="v">SUIT-1284</span></div><div><span class="k">offender:</span> <span class="v">commit 2b9d4c0 by rangga@</span></div><div><span class="k">file:</span> <span class="v">apps/web/src/auth/cookie.ts:24</span></div><div><span class="k">suggested:</span> <span class="v">domain: ".suitest.io"</span></div>'
      },
      suggestions: [
        { icon: 'diff', label: 'Open suggested patch in PR' },
        { icon: 'play', label: 'Verify fix in MCP browser' },
      ]
    },
  ],
  analytics: [
    { role: 'agent', time: '14:40', body: 'Your <b style="color:var(--accent)">release readiness</b> for next Thursday is at <b style="color:var(--fg-1)">86%</b>. Two blockers: SUIT-1284 (OAuth) and SUIT-1283 (Orders API validation). Once both close, you\'ll hit 97%.' },
    { role: 'agent', time: '14:41', body: 'I see pass rate climbed from 88% to 96% over the past 10 days — credit goes to the 47 AI-generated regression tests added last sprint.',
      suggestions: [
        { icon: 'chart', label: 'Drill into coverage gaps' },
        { icon: 'sparkles', label: 'Generate 10 more tests for /api/orders' },
      ]
    },
  ],
  integrations: [
    { role: 'agent', time: '14:44', body: 'You have 3 MCP servers connected. <code>browser-use://staging</code> is the busiest — handled 412 runs this week. Want me to pre-warm 2 more sessions for tonight\'s regression?',
      suggestions: [
        { icon: 'play', label: 'Pre-warm 2 MCP sessions' },
        { icon: 'plus', label: 'Connect new MCP server' },
      ]
    },
  ],
  trace: [
    { role: 'agent', time: '14:46', body: 'Coverage map looks healthy. <b style="color:var(--fg-1)">6 of 6 requirements</b> have linked test cases. <code>REQ-401</code> currently has an open defect — propagated to Jira and tracked.',
      suggestions: [
        { icon: 'sparkles', label: 'Find requirements without tests' },
      ]
    },
  ],
  inbox: [
    { role: 'agent', time: '14:18', body: 'I queued 3 items for your review: a failed deploy gate, a flaky test promotion, and an AI-generated test suite from yesterday\'s PRD update.' },
  ],
  docs: [
    { role: 'agent', time: '14:48', body: 'I indexed your OpenAPI spec at <code>api.suitest.io/openapi.json</code>. 47 endpoints discovered, 12 already covered by tests. Want me to generate coverage for the remaining 35?',
      suggestions: [
        { icon: 'sparkles', label: 'Generate tests for uncovered endpoints' },
      ]
    },
  ],
};

window.Sidebar = Sidebar;
window.Topbar = Topbar;
window.AiPanel = AiPanel;
