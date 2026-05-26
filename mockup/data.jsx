// Suitest — mock data
const SUITES = [
  {
    id: 'auth', name: 'Authentication',
    cases: [
      { id: 'TC-1042', name: 'Login with valid credentials', source: 'manual', priority: 'P0', status: 'pass', tags: ['smoke', 'auth'] },
      { id: 'TC-1043', name: 'Login with invalid password', source: 'manual', priority: 'P1', status: 'pass', tags: ['auth'] },
      { id: 'TC-1044', name: 'Reset password via email', source: 'ai', priority: 'P1', status: 'pass', tags: ['auth', 'email'] },
      { id: 'TC-1045', name: 'OAuth Google sign-in', source: 'ai', priority: 'P0', status: 'fail', tags: ['auth', 'oauth'] },
      { id: 'TC-1046', name: '2FA TOTP verification', source: 'mcp', priority: 'P0', status: 'pass', tags: ['auth', 'security'] },
    ]
  },
  {
    id: 'checkout', name: 'Checkout',
    cases: [
      { id: 'TC-2011', name: 'Add product to cart', source: 'manual', priority: 'P0', status: 'pass', tags: ['cart'] },
      { id: 'TC-2012', name: 'Apply discount code BLACK20', source: 'ai', priority: 'P1', status: 'pass', tags: ['cart', 'promo'] },
      { id: 'TC-2013', name: 'Stripe payment — success path', source: 'ai', priority: 'P0', status: 'pass', tags: ['payment'] },
      { id: 'TC-2014', name: 'Stripe payment — declined card', source: 'ai', priority: 'P0', status: 'warn', tags: ['payment', 'error'] },
      { id: 'TC-2015', name: 'Guest checkout flow', source: 'mcp', priority: 'P1', status: 'pass', tags: ['checkout'] },
      { id: 'TC-2016', name: 'Order confirmation email sent', source: 'ai', priority: 'P2', status: 'pass', tags: ['email'] },
    ]
  },
  {
    id: 'api', name: 'API — Orders',
    cases: [
      { id: 'TC-3001', name: 'POST /orders creates pending order', source: 'mcp', priority: 'P0', status: 'pass', tags: ['api'] },
      { id: 'TC-3002', name: 'GET /orders/:id returns 200', source: 'mcp', priority: 'P0', status: 'pass', tags: ['api'] },
      { id: 'TC-3003', name: 'POST /orders rejects negative qty', source: 'ai', priority: 'P1', status: 'fail', tags: ['api', 'validation'] },
      { id: 'TC-3004', name: 'Rate limit returns 429 after 100 req/min', source: 'ai', priority: 'P2', status: 'pass', tags: ['api'] },
    ]
  },
  {
    id: 'profile', name: 'User Profile',
    cases: [
      { id: 'TC-4001', name: 'Update display name', source: 'manual', priority: 'P2', status: 'pass', tags: ['profile'] },
      { id: 'TC-4002', name: 'Upload avatar image', source: 'manual', priority: 'P2', status: 'pass', tags: ['profile', 'upload'] },
      { id: 'TC-4003', name: 'Change email triggers verification', source: 'ai', priority: 'P1', status: 'pass', tags: ['profile', 'email'] },
    ]
  },
];

const CURRENT_CASE = {
  id: 'TC-1045',
  name: 'OAuth Google sign-in',
  source: 'ai',
  status: 'fail',
  priority: 'P0',
  suite: 'Authentication',
  owner: { name: 'Maya Putri', avatar: 'MP' },
  generatedBy: 'Suitest Agent · v2.4',
  generatedFrom: 'PRD-2026-Q1 § 4.2 "Social sign-in"',
  lastRun: '4m ago',
  duration: '8.2s',
  description: 'Verify that users can authenticate using their Google account through the OAuth 2.0 flow, including consent screen, scope grants, and session establishment.',
  preconditions: 'User has a valid Google account · OAuth client configured · Cookies enabled',
  steps: [
    { action: 'Navigate to app.suitest.io/login', expected: 'Login page loads within 2s with Google button visible', code: 'await page.goto("https://app.suitest.io/login")' },
    { action: 'Click "Continue with Google"', expected: 'Browser redirects to accounts.google.com/o/oauth2/v2/auth', code: 'await page.click("button[data-provider=\'google\']")' },
    { action: 'Enter test credentials qa@suitest.io', expected: 'Consent screen displayed listing requested scopes (email, profile)', code: 'await page.fill("#identifierId", env.GOOGLE_TEST_EMAIL)' },
    { action: 'Approve consent screen', expected: 'User redirected back to /dashboard with active session cookie', code: 'await page.click("button#submit_approve_access")' },
    { action: 'Verify session and user.id matches Google sub claim', expected: 'GET /api/me returns 200 with provider=google', code: 'expect(await api.me()).toMatchObject({ provider: "google" })' },
  ]
};

const ACTIVE_RUNS = [
  { id: 'R-8842', name: 'Checkout E2E · Chrome 124', status: 'running', progress: 62, passed: 18, failed: 0, total: 29, branch: 'main', commit: 'a7f3e21', duration: '4m 22s', triggered: 'Push by maya@', env: 'staging' },
  { id: 'R-8841', name: 'Auth Suite · MCP Browser', status: 'running', progress: 41, passed: 9, failed: 1, total: 22, branch: 'feat/oauth', commit: '2b9d4c0', duration: '2m 11s', triggered: 'CI · GitHub Actions', env: 'preview' },
  { id: 'R-8840', name: 'API Smoke · /orders', status: 'pass', progress: 100, passed: 12, failed: 0, total: 12, branch: 'main', commit: 'a7f3e21', duration: '47s', triggered: 'Scheduled · 14:00 WIB', env: 'production' },
  { id: 'R-8839', name: 'Regression Pack · Full', status: 'fail', progress: 100, passed: 211, failed: 3, total: 214, branch: 'main', commit: 'c4a1b89', duration: '12m 04s', triggered: 'Nightly', env: 'staging' },
  { id: 'R-8838', name: 'Profile Settings · Mobile', status: 'pass', progress: 100, passed: 14, failed: 0, total: 14, branch: 'main', commit: 'c4a1b89', duration: '1m 38s', triggered: 'PR #3421', env: 'preview' },
];

const LOG_LINES = [
  { t: '14:32:01.024', l: 'info', m: 'Booting Suitest agent · runner=mcp-browser-v3.2.1 · region=ap-southeast-1' },
  { t: '14:32:01.118', l: 'info', m: 'Connecting to MCP server <span class="hl">browser-use://staging</span>...' },
  { t: '14:32:01.402', l: 'ok',   m: 'MCP handshake complete. Capabilities: [navigate, click, type, screenshot, wait_for_selector]' },
  { t: '14:32:01.530', l: 'info', m: 'Loading test plan from <span class="hl">TC-1045 OAuth Google sign-in</span> <span class="dim">(generated by agent v2.4)</span>' },
  { t: '14:32:02.018', l: 'info', m: '→ Step 1/5: Navigate to app.suitest.io/login' },
  { t: '14:32:02.612', l: 'ok',   m: '   Page loaded in 594ms. Found 14 interactive elements.' },
  { t: '14:32:02.701', l: 'info', m: '→ Step 2/5: Click "Continue with Google"' },
  { t: '14:32:02.890', l: 'ok',   m: '   Click dispatched on <span class="hl">button[data-provider=&quot;google&quot;]</span>' },
  { t: '14:32:03.255', l: 'ok',   m: '   Redirected to accounts.google.com/o/oauth2/v2/auth?...' },
  { t: '14:32:03.401', l: 'info', m: '→ Step 3/5: Enter test credentials' },
  { t: '14:32:04.812', l: 'ok',   m: '   Credentials accepted, consent screen rendered.' },
  { t: '14:32:04.998', l: 'info', m: '→ Step 4/5: Approve consent screen' },
  { t: '14:32:05.811', l: 'warn', m: '   Consent screen took 813ms to register approval (threshold: 500ms)' },
  { t: '14:32:06.022', l: 'info', m: '→ Step 5/5: Verify session and user.id matches Google sub claim' },
  { t: '14:32:06.318', l: 'fail', m: '   Expected response 200, received <span class="hl">403 Forbidden</span> from GET /api/me' },
  { t: '14:32:06.319', l: 'fail', m: '   <span class="hl">AssertionError</span>: provider mismatch. Expected "google", received "<span class="hl">null</span>"' },
  { t: '14:32:06.420', l: 'info', m: 'Capturing failure artifacts: screenshot, HAR, console logs, DOM snapshot...' },
  { t: '14:32:06.701', l: 'ok',   m: 'Artifacts uploaded to s3://suitest-runs/R-8841/step-5/' },
  { t: '14:32:06.804', l: 'info', m: 'Syncing failure to Jira project SUIT...' },
  { t: '14:32:07.122', l: 'ok',   m: 'Created Jira ticket <span class="hl">SUIT-1284</span> · linked to TC-1045 · assigned to maya@' },
];

const DEFECTS = [
  {
    id: 'SUIT-1284', title: 'OAuth Google: session not persisted after consent approval',
    severity: 'critical', component: 'auth/oauth', testId: 'TC-1045', run: 'R-8841', age: '4m', assignee: 'Maya P.',
    trace: 'AssertionError: expected "google", received null\n  at expect (verify.spec.ts:42:8)\n  at runStep (mcp-runner.ts:188:14)\n  at async TestCase.run (test-case.ts:301:5)',
    aiNote: 'Likely regression from commit 2b9d4c0 — cookie domain was changed from .suitest.io to app.suitest.io, breaking cross-subdomain session reads.'
  },
  {
    id: 'SUIT-1283', title: 'POST /orders accepts negative quantity bypassing validator',
    severity: 'high', component: 'api/orders', testId: 'TC-3003', run: 'R-8839', age: '2h', assignee: 'Rangga A.',
    trace: 'AssertionError: expected status 400, received 201\n  at validateOrder.spec.ts:67:8',
    aiNote: 'Schema validator missing min(1) constraint on quantity field in OrderCreateSchema (orders.schema.ts:34).'
  },
  {
    id: 'SUIT-1282', title: 'Discount BLACK20 not applied when cart total below Rp 100.000',
    severity: 'medium', component: 'checkout/promo', testId: 'TC-2012', run: 'R-8839', age: '2h', assignee: 'Sari W.',
    trace: 'AssertionError: expected total 80000, received 100000\n  at promo.spec.ts:24:12',
    aiNote: 'Discount eligibility threshold mismatched between docs (Rp 50k) and code (Rp 100k).'
  },
];

const PASS_RATE_HISTORY = [
  { d: 'May 12', p: 88.2 }, { d: 'May 13', p: 91.4 }, { d: 'May 14', p: 89.7 },
  { d: 'May 15', p: 92.1 }, { d: 'May 16', p: 93.8 }, { d: 'May 17', p: 92.3 },
  { d: 'May 18', p: 94.6 }, { d: 'May 19', p: 93.2 }, { d: 'May 20', p: 95.1 },
  { d: 'May 21', p: 94.8 }, { d: 'May 22', p: 96.4 },
];

const FLAKY_TESTS = [
  { name: 'checkout.stripe.declined_card', rate: 14.3, runs: 56 },
  { name: 'auth.oauth.google_signin', rate: 9.8, runs: 71 },
  { name: 'orders.api.rate_limit', rate: 6.2, runs: 92 },
  { name: 'profile.upload_avatar', rate: 4.1, runs: 48 },
  { name: 'cart.apply_promo_code', rate: 3.5, runs: 113 },
];

const INTEGRATIONS = [
  { name: 'GitHub Actions', cat: 'CI/CD', logo: 'GH', desc: 'Trigger test runs on push, PR, and tag events.', connected: true, since: 'Connected 4 months ago' },
  { name: 'GitLab CI', cat: 'CI/CD', logo: 'GL', desc: 'Pipeline-triggered runs with merge-request gating.', connected: false },
  { name: 'Jenkins', cat: 'CI/CD', logo: 'JK', desc: 'Webhook-driven jobs and post-build reporting.', connected: true, since: 'Connected 2 months ago' },
  { name: 'Jira Cloud', cat: 'Issue Tracker', logo: 'JR', desc: 'Bi-directional sync · auto-create issues on failure.', connected: true, since: 'Connected · org=suitest-id' },
  { name: 'Linear', cat: 'Issue Tracker', logo: 'LN', desc: 'Push defects into Linear with traceability.', connected: false },
  { name: 'Slack', cat: 'Notifications', logo: 'SL', desc: 'Alerts to #qa-alerts on failed runs and flaky tests.', connected: true, since: 'Connected · 3 channels' },
  { name: 'Browser-Use MCP', cat: 'MCP Server', logo: 'MCP', desc: 'Autonomous browser agent for end-to-end web testing.', connected: true, since: 'v3.2.1 · 4 concurrent sessions', highlight: true },
  { name: 'Playwright MCP', cat: 'MCP Server', logo: 'PW', desc: 'Programmatic browser control via Model Context Protocol.', connected: true, since: 'v1.8.0', highlight: true },
  { name: 'OpenAPI Scanner', cat: 'API Discovery', logo: 'API', desc: 'Generate test cases from your OpenAPI/Swagger spec.', connected: true, since: '14 specs indexed', highlight: true },
];

const REQUIREMENTS = [
  { id: 'REQ-401', name: 'Users can sign in with Google', tests: ['TC-1045', 'TC-1046'], defects: ['SUIT-1284'] },
  { id: 'REQ-402', name: 'Reset password by email link', tests: ['TC-1044'], defects: [] },
  { id: 'REQ-510', name: 'Apply promo codes at checkout', tests: ['TC-2012'], defects: ['SUIT-1282'] },
  { id: 'REQ-511', name: 'Process payments via Stripe', tests: ['TC-2013', 'TC-2014'], defects: [] },
  { id: 'REQ-620', name: 'Orders API exposes CRUD endpoints', tests: ['TC-3001', 'TC-3002', 'TC-3003'], defects: ['SUIT-1283'] },
  { id: 'REQ-621', name: 'API rate limits at 100 req/min', tests: ['TC-3004'], defects: [] },
];

window.SuitestData = { SUITES, CURRENT_CASE, ACTIVE_RUNS, LOG_LINES, DEFECTS, PASS_RATE_HISTORY, FLAKY_TESTS, INTEGRATIONS, REQUIREMENTS };
