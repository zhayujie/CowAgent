/* Login screen, logout, and the 401 handling around fetch.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Authentication
// =====================================================================
// Auth gate for background pollers. When a web_password is set, the /poll and
// /api/scheduler/runs loops must NOT run before the user logs in — otherwise
// they fire every few seconds with no cookie and spam the server log with
// "401 Unauthorized (credentials offered: none)". Both loops call
// requestAuthGatedStart(); the actual start is deferred until the login/auth
// check opens the gate via openAuthGate(). When no password is set the gate is
// opened immediately at startup so behavior is unchanged.
// This file loads after the pollers define their loops but before boot.js, the
// only caller that runs at load time, so the declarations are always in scope.
let authGateOpen = false;
const _pendingAuthGatedStarts = [];
function requestAuthGatedStart(fn) {
    if (authGateOpen) { fn(); return; }
    _pendingAuthGatedStarts.push(fn);
}
function openAuthGate() {
    if (authGateOpen) return;
    authGateOpen = true;
    while (_pendingAuthGatedStarts.length) {
        const fn = _pendingAuthGatedStarts.shift();
        try { fn(); } catch (_) {}
    }
}

function toggleLoginPassword() {
    const input = document.getElementById('login-password');
    const icon = document.querySelector('#login-toggle-pwd i');
    if (input.type === 'password') {
        input.type = 'text';
        icon.classList.replace('fa-eye', 'fa-eye-slash');
    } else {
        input.type = 'password';
        icon.classList.replace('fa-eye-slash', 'fa-eye');
    }
}
window.toggleLoginPassword = toggleLoginPassword;

function showLoginScreen() {
    const overlay = document.getElementById('login-overlay');
    if (!overlay) return;
    overlay.classList.remove('hidden');
    document.getElementById('app').classList.add('hidden');

    const subtitle = document.getElementById('login-subtitle');
    const loginBtn = document.getElementById('login-btn');
    if (currentLang === 'en') {
        subtitle.textContent = 'Enter password to access the console';
        loginBtn.textContent = 'Login';
    } else if (currentLang === 'zh-Hant') {
        subtitle.textContent = '請輸入密碼以存取控制台';
        loginBtn.textContent = '登入';
    } else {
        subtitle.textContent = '请输入密码以访问控制台';
        loginBtn.textContent = '登录';
    }

    const form = document.getElementById('login-form');
    const pwdInput = document.getElementById('login-password');
    pwdInput.focus();

    form.onsubmit = function(e) {
        e.preventDefault();
        const pwd = pwdInput.value;
        if (!pwd) return;
        const btn = document.getElementById('login-btn');
        const errEl = document.getElementById('login-error');
        btn.disabled = true;
        errEl.classList.add('hidden');

        fetch('/auth/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({password: pwd})
        }).then(r => r.json()).then(data => {
            if (data.status === 'success') {
                overlay.classList.add('hidden');
                document.getElementById('app').classList.remove('hidden');
                const logoutBtn = document.getElementById('logout-btn-header');
                if (logoutBtn) logoutBtn.classList.remove('hidden');
                // Now that the auth cookie is set, release the parked pollers.
                openAuthGate();
                initApp();
            } else {
                if (currentLang === 'zh-Hant') {
                    errEl.textContent = '密碼錯誤';
                } else if (currentLang === 'zh') {
                    errEl.textContent = '密码错误';
                } else {
                    errEl.textContent = 'Wrong password';
                }
                errEl.classList.remove('hidden');
                pwdInput.value = '';
                pwdInput.focus();
            }
            btn.disabled = false;
        }).catch(() => {
            if (currentLang === 'zh-Hant') {
                errEl.textContent = '網路錯誤，請重試';
            } else if (currentLang === 'zh') {
                errEl.textContent = '网络错误，请重试';
            } else {
                errEl.textContent = 'Network error, please retry';
            }
            errEl.classList.remove('hidden');
            btn.disabled = false;
        });
        return false;
    };
}

function handleLogout() {
    fetch('/auth/logout', {
        method: 'POST'
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            window.location.reload();
        }
    }).catch(() => {
        window.location.reload();
    });
}
window.handleLogout = handleLogout;

// Intercept 401 responses globally to show login screen on session expiry
const _originalFetch = window.fetch;
window.fetch = function(...args) {
    return _originalFetch.apply(this, args).then(response => {
        if (response.status === 401) {
            const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
            if (!url.startsWith('/auth/')) {
                showLoginScreen();
            }
        }
        return response;
    });
};

function initApp() {
    applyI18n();
    _applyInputTooltips();
    _restoreSessionPanel();
    refreshWorkspaceSelector();
    refreshSessionSettings();

    fetch('/api/knowledge/list').then(r => r.json()).then(data => {
        if (data.status === 'success') {
            _knowledgeTreeData = data.tree || [];
            _knowledgeRootFiles = data.root_files || [];
        }
    }).catch(() => {});

    fetch('/api/version').then(r => r.json()).then(data => {
        APP_VERSION = `v${data.version}`;
        UPDATE_META = {
            version: data.version || '',
            install_kind: data.install_kind || 'unknown',
            update_supported: !!data.update_supported,
            unsupported_reason: data.unsupported_reason || ''
        };
        _setSidebarVersionLabel(`CowAgent ${APP_VERSION}`);
    }).catch(() => {
        _setSidebarVersionLabel('CowAgent');
    });
    chatInput.focus();
    // Last, and only from here: initApp() runs once auth has settled, on all
    // three paths into the app. Opening the routed view any earlier would
    // switch views behind the login overlay.
    routeApply();
}

