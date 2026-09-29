/* Startup: theme, i18n, auth gate, initial fetches. Loads last.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// Everything below reads protected endpoints, so it waits for the auth gate:
// fired before login it only collects 401s, and the login path never retries
// it, which left the chat empty after signing in until the next reload.
requestAuthGatedStart(loadAgentCatalog);
requestAuthGatedStart(() => {
    fetch('/config').then(r => r.json()).then(data => {
        if (data.status === 'success') {
            appConfig = data;
            const title = data.title || 'CowAgent';
            document.getElementById('welcome-title').textContent = title;
            initConfigView(data);
        }
        loadHistory(1);
    }).catch(() => { loadHistory(1); });
});

// Start polling so scheduler/push messages are received.
requestAuthGatedStart(startPolling);
// =====================================================================
// Initialization
// =====================================================================
applyTheme();
applyI18n();

fetch('/auth/check').then(r => r.json()).then(data => {
    if (data.auth_required && !data.authenticated) {
        // Keep background pollers parked until login succeeds (openAuthGate is
        // called from the login handler), so they don't spam 401s meanwhile.
        showLoginScreen();
    } else {
        if (data.auth_required) {
            const logoutBtn = document.getElementById('logout-btn-header');
            if (logoutBtn) logoutBtn.classList.remove('hidden');
        }
        openAuthGate();
        initApp();
    }
}).catch(() => {
    // No auth info available (e.g. request failed): fall back to running so a
    // password-less deployment still works.
    openAuthGate();
    initApp();
});

requestAnimationFrame(() => {
    document.body.classList.add('transition-colors', 'duration-200');
});

