// Suitest — print-mode app: render all routes stacked
function PrintApp() {
  const routes = [
    { id: 'dashboard',    crumbs: ['Nusantara Retail', 'Dashboard'],                    view: window.DashboardView },
    { id: 'cases',        crumbs: ['Nusantara Retail', 'Test Cases'],                   view: window.TestCasesView },
    { id: 'runs',         crumbs: ['Nusantara Retail', 'Test Runs', 'R-8841'],          view: window.RunsView },
    { id: 'defects',      crumbs: ['Nusantara Retail', 'Defects'],                      view: window.DefectsView },
    { id: 'analytics',    crumbs: ['Nusantara Retail', 'Analytics'],                    view: window.AnalyticsView },
    { id: 'trace',        crumbs: ['Nusantara Retail', 'Traceability'],                 view: window.TraceabilityView },
    { id: 'integrations', crumbs: ['Nusantara Retail', 'Integrations'],                 view: window.IntegrationsView },
    { id: 'docs',         crumbs: ['Nusantara Retail', 'Docs & specs'],                 view: window.DocsView },
    { id: 'inbox',        crumbs: ['Nusantara Retail', 'Inbox'],                        view: window.InboxView },
  ];

  return (
    <>
      {routes.map(r => {
        const View = r.view;
        return (
          <div className="print-page" key={r.id}>
            <window.Sidebar route={r.id} setRoute={() => {}}/>
            <main className="main">
              <window.Topbar crumbs={r.crumbs}/>
              <View/>
            </main>
            <window.AiPanel context={r.id}/>
          </div>
        );
      })}
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<PrintApp/>);

// Auto-print once everything is laid out
(function autoPrint() {
  if (window.__SUITEST_SKIP_PRINT) return;
  const waitForFonts = document.fonts ? document.fonts.ready : Promise.resolve();
  waitForFonts.then(() => {
    // Give React + Babel a moment to mount all 9 pages
    setTimeout(() => {
      try { window.print(); } catch (e) { console.error('Print failed:', e); }
    }, 1200);
  });
})();
