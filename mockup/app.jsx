// Suitest — main app
const { useState: useStateM } = React;

function App() {
  const [route, setRoute] = useStateM('dashboard');

  const ROUTES = {
    dashboard: { crumbs: ['Nusantara Retail', 'Dashboard'], view: window.DashboardView },
    inbox: { crumbs: ['Nusantara Retail', 'Inbox'], view: window.InboxView },
    cases: { crumbs: ['Nusantara Retail', 'Test Cases'], view: window.TestCasesView },
    runs: { crumbs: ['Nusantara Retail', 'Test Runs', 'R-8841'], view: window.RunsView },
    defects: { crumbs: ['Nusantara Retail', 'Defects'], view: window.DefectsView },
    analytics: { crumbs: ['Nusantara Retail', 'Analytics'], view: window.AnalyticsView },
    trace: { crumbs: ['Nusantara Retail', 'Traceability'], view: window.TraceabilityView },
    integrations: { crumbs: ['Nusantara Retail', 'Integrations'], view: window.IntegrationsView },
    docs: { crumbs: ['Nusantara Retail', 'Docs & specs'], view: window.DocsView },
  };

  const r = ROUTES[route] || ROUTES.dashboard;
  const View = r.view;

  return (
    <div className="app" data-screen-label={`Suitest · ${route}`}>
      <window.Sidebar route={route} setRoute={setRoute}/>
      <main className="main">
        <window.Topbar crumbs={r.crumbs}/>
        <View/>
      </main>
      <window.AiPanel context={route}/>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
