/* Color themes: palettes, wallpaper and new-chat logo on top of light/dark.
   Themes use the desktop client's format and live in the same folder
   (<workspace>/system/themes, served by /api/themes), so one theme works in both.
   A theme is pure data mapped onto the --cw-* palette variables in base.css;
   anything it can't express keeps the default look, and a theme that fails
   to apply or leaves text unreadable falls back to the default theme.
   Classic script sharing one global scope; see channel/web/README.md. */

const COLOR_THEME_KEY = 'cow_theme_id';
// Last applied variables per appearance, replayed in <head> before first paint.
const COLOR_THEME_CACHE_KEY = 'cow_theme_cache';
const DEFAULT_COLOR_THEME = 'default';
// Shown until /api/themes reports the real folder.
const COLOR_THEMES_DIR_HINT = '~/cow/system/themes';

const _CT_COLOR_KEYS = [
    'accent', 'accentHover', 'accentActive', 'accentSoft', 'accentContrast',
    'bubbleUserBg', 'bubbleUserText', 'bgBase', 'bgSurface', 'bgSurface2',
    'bgElevated', 'bgInset', 'bgInset2', 'textPrimary', 'textSecondary',
    'textTertiary', 'textDisabled', 'borderDefault', 'borderStrong', 'borderSubtle',
    'sidebarBg',
];

const _CT_DARK_BORDERS = {
    borderDefault: 'rgba(255, 255, 255, 0.08)',
    borderStrong: 'rgba(255, 255, 255, 0.14)',
    borderSubtle: 'rgba(255, 255, 255, 0.04)',
};

// Same palettes as the desktop client (desktop/src/renderer/src/theme/themes.ts).
const BUILTIN_COLOR_THEMES = [
    { id: 'default', name: 'Meadow', preview: { accent: '#4abe6e', bg: '#f9fafb', surface: '#ffffff' } },
    {
        id: 'ocean', name: 'Ocean', preview: { accent: '#3370ff', bg: '#f7f9fc', surface: '#ffffff' },
        light: { colors: {
            accent: '#3370ff', accentHover: '#2f68ee', accentActive: '#2559d6', accentSoft: 'rgba(51, 112, 255, 0.10)',
            accentContrast: '#ffffff', bubbleUserBg: '#e6efff', bubbleUserText: '#1a3a7a',
            bgBase: '#f7f9fc', bgSurface: '#ffffff', bgSurface2: '#eef2f9', bgElevated: '#ffffff',
            bgInset: '#eef2f9', bgInset2: '#eef2f9', textPrimary: '#1a2233', textSecondary: '#48536b',
            textTertiary: '#6b7488', textDisabled: '#9aa3b5', borderDefault: '#e3e8f0', borderStrong: '#cbd4e2',
            borderSubtle: '#eef2f9',
        } },
        dark: { colors: {
            accent: '#4a83ff', accentHover: '#5e91ff', accentActive: '#3a72f0', accentSoft: 'rgba(74, 131, 255, 0.16)',
            accentContrast: '#0e0e10', bubbleUserBg: 'rgba(74, 131, 255, 0.20)', bubbleUserText: '#dce8ff',
            bgBase: '#0e0e10', bgSurface: '#161618', bgSurface2: '#1c1c1f', bgElevated: '#1f1f23',
            bgInset: '#161618', bgInset2: '#161618', textPrimary: '#f4f4f5', textSecondary: '#c4c4cc',
            textTertiary: '#8e8e96', textDisabled: '#5a5a62', ..._CT_DARK_BORDERS,
        } },
    },
    {
        id: 'clay', name: 'Clay', preview: { accent: '#c96442', bg: '#faf9f5', surface: '#ffffff' },
        light: { colors: {
            accent: '#c96442', accentHover: '#b8583a', accentActive: '#a24d33', accentSoft: 'rgba(201, 100, 66, 0.10)',
            accentContrast: '#ffffff', bubbleUserBg: '#f1ebe2', bubbleUserText: '#3d3424',
            bgBase: '#faf9f5', bgSurface: '#ffffff', bgSurface2: '#f2f0e9', bgElevated: '#ffffff',
            bgInset: '#faf9f5', bgInset2: '#f2f0e9', textPrimary: '#2b2925', textSecondary: '#55524b',
            textTertiary: '#7a766c', textDisabled: '#aba79c', borderDefault: '#e8e5dc', borderStrong: '#d7d3c7',
            borderSubtle: '#f2f0e9',
        } },
        dark: { colors: {
            accent: '#d97757', accentHover: '#e08a6d', accentActive: '#c96442', accentSoft: 'rgba(217, 119, 87, 0.16)',
            accentContrast: '#ffffff', bubbleUserBg: 'rgba(217, 119, 87, 0.18)', bubbleUserText: '#f7e1d7',
            bgBase: '#1f1e1c', bgSurface: '#262624', bgSurface2: '#302f2c', bgElevated: '#2c2b29',
            bgInset: '#262624', bgInset2: '#2a2927', textPrimary: '#f5f4ef', textSecondary: '#cdcac0',
            textTertiary: '#9b978d', textDisabled: '#67645d', ..._CT_DARK_BORDERS,
        } },
    },
    {
        id: 'sakura', name: 'Sakura', preview: { accent: '#e16b8c', bg: '#fcf8f9', surface: '#ffffff' },
        light: { colors: {
            accent: '#e16b8c', accentHover: '#d65c7e', accentActive: '#c24f70', accentSoft: 'rgba(225, 107, 140, 0.10)',
            accentContrast: '#ffffff', bubbleUserBg: '#fce8ee', bubbleUserText: '#7a2e47',
            bgBase: '#fcf8f9', bgSurface: '#ffffff', bgSurface2: '#f8eef1', bgElevated: '#ffffff',
            bgInset: '#fcf8f9', bgInset2: '#f6ecef', textPrimary: '#2f2529', textSecondary: '#5f5157',
            textTertiary: '#887a80', textDisabled: '#bcb0b5', borderDefault: '#f0e3e8', borderStrong: '#e3d1d8',
            borderSubtle: '#f8eef1',
        } },
        dark: { colors: {
            accent: '#e8799a', accentHover: '#ee8eab', accentActive: '#da6a8b', accentSoft: 'rgba(232, 121, 154, 0.16)',
            accentContrast: '#ffffff', bubbleUserBg: 'rgba(232, 121, 154, 0.18)', bubbleUserText: '#ffe4ec',
            bgBase: '#131113', bgSurface: '#1a181a', bgSurface2: '#221f22', bgElevated: '#242124',
            bgInset: '#1a181a', bgInset2: '#1a181a', textPrimary: '#f6eff2', textSecondary: '#d4c8cd',
            textTertiary: '#9e9197', textDisabled: '#675b60', ..._CT_DARK_BORDERS,
        } },
    },
    {
        id: 'lavender', name: 'Lavender', preview: { accent: '#8467d8', bg: '#f9f8fc', surface: '#ffffff' },
        light: { colors: {
            accent: '#8467d8', accentHover: '#7659cb', accentActive: '#684cb8', accentSoft: 'rgba(132, 103, 216, 0.10)',
            accentContrast: '#ffffff', bubbleUserBg: '#efebfb', bubbleUserText: '#3f3075',
            bgBase: '#f9f8fc', bgSurface: '#ffffff', bgSurface2: '#f1eff8', bgElevated: '#ffffff',
            bgInset: '#f9f8fc', bgInset2: '#efedf6', textPrimary: '#25222f', textSecondary: '#524d62',
            textTertiary: '#787388', textDisabled: '#aca8ba', borderDefault: '#e8e5f0', borderStrong: '#d8d4e5',
            borderSubtle: '#f1eff8',
        } },
        dark: { colors: {
            accent: '#9c86ee', accentHover: '#ac99f2', accentActive: '#8d76e3', accentSoft: 'rgba(156, 134, 238, 0.16)',
            accentContrast: '#ffffff', bubbleUserBg: 'rgba(156, 134, 238, 0.18)', bubbleUserText: '#ece7ff',
            bgBase: '#111014', bgSurface: '#18171c', bgSurface2: '#1f1e24', bgElevated: '#222127',
            bgInset: '#18171c', bgInset2: '#18171c', textPrimary: '#f3f2f7', textSecondary: '#cbc8d6',
            textTertiary: '#928ea1', textDisabled: '#5f5c6b', ..._CT_DARK_BORDERS,
        } },
    },
];

let colorThemes = BUILTIN_COLOR_THEMES.slice();
let colorThemeId = localStorage.getItem(COLOR_THEME_KEY) || DEFAULT_COLOR_THEME;
let colorThemesDir = '';

// ---- Loading ----------------------------------------------------------------
// theme.json files come from users and the agent; rebuild each one from the
// fields this format defines so a malformed value can only drop that field.

function _ctIsRecord(v) {
    return !!v && typeof v === 'object' && !Array.isArray(v);
}

// Resource references are refused so a theme can't make the console fetch
// remote content through a color value.
function _ctIsCssValue(v) {
    return typeof v === 'string' && v.trim() !== '' && v.length <= 300
        && !/url\s*\(|@import|expression\s*\(/i.test(v);
}

// Images end up inside a CSS url("..."): only our own asset URLs (or inlined
// data) are allowed, and nothing that could close the url().
function _ctIsImageUrl(v) {
    return typeof v === 'string' && /^(\/api\/themes\/asset\?|data:image\/)/.test(v)
        && !/["'\\()\s]/.test(v);
}

function _ctFinite(v) {
    return typeof v === 'number' && Number.isFinite(v) ? v : undefined;
}

function _ctWallpaper(wp) {
    if (!_ctIsRecord(wp) || !_ctIsImageUrl(wp.image)) return undefined;
    return {
        image: wp.image,
        focusX: _ctFinite(wp.focusX),
        focusY: _ctFinite(wp.focusY),
        overlayOpacity: _ctFinite(wp.overlayOpacity),
        glass: wp.glass === true,
    };
}

function _ctAppearance(src) {
    if (!_ctIsRecord(src)) return undefined;
    const out = {};
    if (_ctIsRecord(src.colors)) {
        const colors = {};
        _CT_COLOR_KEYS.forEach(k => { if (_ctIsCssValue(src.colors[k])) colors[k] = src.colors[k]; });
        if (Object.keys(colors).length) out.colors = colors;
    }
    const wp = _ctWallpaper(src.wallpaper);
    if (wp) out.wallpaper = wp;
    return out.colors || out.wallpaper ? out : undefined;
}

function _ctNormalize(raw) {
    if (!_ctIsRecord(raw) || typeof raw.id !== 'string' || !raw.id.trim()) return null;
    const theme = {
        id: raw.id,
        name: typeof raw.name === 'string' && raw.name.trim() ? raw.name.slice(0, 64) : raw.id,
    };
    const light = _ctAppearance(raw.light);
    const dark = _ctAppearance(raw.dark);
    // One wallpaper serves both appearances: an appearance's own wins, then the
    // top-level shared one, then the other appearance's.
    const shared = _ctWallpaper(raw.wallpaper);
    const lightWp = (light && light.wallpaper) || shared || (dark && dark.wallpaper);
    const darkWp = (dark && dark.wallpaper) || shared || (light && light.wallpaper);
    if (light || lightWp) theme.light = { ...light, wallpaper: lightWp };
    if (dark || darkWp) theme.dark = { ...dark, wallpaper: darkWp };
    const logo = _ctIsRecord(raw.identity) ? raw.identity.logo : undefined;
    if (_ctIsImageUrl(logo)) theme.identity = { logo };
    const p = raw.preview;
    if (_ctIsRecord(p) && _ctIsCssValue(p.accent) && _ctIsCssValue(p.bg) && _ctIsCssValue(p.surface)) {
        theme.preview = { accent: p.accent, bg: p.bg, surface: p.surface };
    } else {
        const c = (theme.dark && theme.dark.colors) || (theme.light && theme.light.colors) || {};
        theme.preview = { accent: c.accent || '#4abe6e', bg: c.bgBase || '#111111', surface: c.bgSurface || '#1c1c1f' };
    }
    return theme;
}

function registerColorThemes(list) {
    const loaded = [];
    const taken = new Set(BUILTIN_COLOR_THEMES.map(th => th.id));
    (Array.isArray(list) ? list : []).forEach(raw => {
        const theme = _ctNormalize(raw);
        if (!theme) return;
        // A theme written straight into the folder may reuse a built-in (or
        // another theme's) id; suffix it so it still shows up.
        let id = theme.id;
        for (let n = 2; taken.has(id); n++) id = `${theme.id}-${n}`;
        taken.add(id);
        loaded.push(id === theme.id ? theme : { ...theme, id });
    });
    colorThemes = BUILTIN_COLOR_THEMES.concat(loaded);
}

let _ctLastLoad = 0;
let _ctLoaded = false;
// Re-scan the themes folder so themes added since the page loaded (imported,
// copied in by hand, or written by the agent) show up.
function loadColorThemes(force) {
    if (!force && Date.now() - _ctLastLoad < 1500) return Promise.resolve();
    _ctLastLoad = Date.now();
    return fetch('/api/themes').then(r => r.json()).then(data => {
        if (!data || data.status !== 'success') return;
        colorThemesDir = data.dir || '';
        registerColorThemes(data.themes);
        _ctLoaded = true;
        applyColorTheme();
        renderColorThemeMenu();
    }).catch(() => {});
}

function getColorTheme(id) {
    return colorThemes.find(th => th.id === id) || colorThemes[0];
}

// ---- Colors -----------------------------------------------------------------

function _ctParse(value) {
    if (typeof value !== 'string') return null;
    const v = value.trim();
    let m = /^#([0-9a-f]{3})$/i.exec(v);
    if (m) return m[1].split('').map(c => parseInt(c + c, 16)).concat(1);
    m = /^#([0-9a-f]{6})$/i.exec(v);
    if (m) return [0, 2, 4].map(i => parseInt(m[1].slice(i, i + 2), 16)).concat(1);
    m = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/i.exec(v);
    if (!m) return null;
    let a = m[4] === undefined ? 1 : parseFloat(m[4]);
    if (m[4] && m[4].endsWith('%')) a /= 100;
    return [+m[1], +m[2], +m[3], Math.min(1, Math.max(0, a))];
}

function _ctMix(a, b, t) {
    return [0, 1, 2].map(i => a[i] + (b[i] - a[i]) * t);
}

const _CT_WHITE = [255, 255, 255];
const _CT_BLACK = [0, 0, 0];
// The sidebar's nav text (text-neutral-400).
const _CT_SIDEBAR_TEXT = [163, 163, 163];

function _ctLuminance(c) {
    const ch = (v) => {
        const s = Math.min(255, Math.max(0, v)) / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2]);
}

function _ctContrast(a, b) {
    const [hi, lo] = [_ctLuminance(a), _ctLuminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
}

function _ctTriple(c) {
    return c.slice(0, 3).map(v => Math.round(Math.min(255, Math.max(0, v)))).join(' ');
}

// The --cw-* variables for one appearance of a theme, or null when its text
// would be unreadable. Keys the theme doesn't set keep the default.
function _ctVars(colors, darkColors, dark) {
    const surfaceDefault = dark ? [26, 26, 26] : _CT_WHITE;
    const baseDefault = dark ? [17, 17, 17] : [249, 250, 251];
    const raw = (k) => _ctParse(colors[k]);
    const surface = raw('bgSurface') || surfaceDefault;
    // Translucent colors are flattened onto the surface they sit on.
    const c = (k) => {
        const v = raw(k);
        return v ? _ctMix(surface, v, v[3]) : null;
    };
    const base = c('bgBase') || baseDefault;
    const text = c('textPrimary');
    if (text && (_ctContrast(text, base) < 3 || _ctContrast(text, surface) < 3)) return null;

    const vars = {};
    const set = (name, color) => { if (color) vars['--cw-' + name] = _ctTriple(color); };
    const mix = (a, b, t) => (a && b ? _ctMix(a, b, t) : null);
    set('canvas', c('bgBase'));
    set('panel', c('bgSurface'));

    const accent = c('accent');
    if (accent) {
        [[50, 0.9], [100, 0.8], [200, 0.6], [300, 0.4]].forEach(([s, t]) => set('primary-' + s, _ctMix(accent, _CT_WHITE, t)));
        set('primary-400', accent);
        [[500, 0.1], [600, 0.22], [700, 0.38], [800, 0.52], [900, 0.62]].forEach(([s, t]) => set('primary-' + s, _ctMix(accent, _CT_BLACK, t)));
        set('accent-ink', dark ? _ctMix(accent, _CT_WHITE, 0.35) : _ctMix(accent, _CT_BLACK, 0.3));
    }
    // Text on a fill: the theme's own pick when it reads, else white or black.
    const ink = (bg, want) => {
        if (want && _ctContrast(want, bg) >= 3) return want;
        return _ctContrast(_CT_WHITE, bg) >= 2.5 ? _CT_WHITE : _CT_BLACK;
    };
    if (accent) set('on-accent', ink(accent, c('accentContrast')));
    // The user's bubble sits on the page, so flatten its fill onto the base.
    const bubbleRaw = raw('bubbleUserBg');
    const bubble = bubbleRaw ? _ctMix(base, bubbleRaw, bubbleRaw[3]) : accent;
    if (bubble) {
        set('bubble-user', bubble);
        set('bubble-user-text', ink(bubble, bubbleRaw ? c('bubbleUserText') : c('accentContrast')));
    }

    const t1 = text, t2 = c('textSecondary'), t3 = c('textTertiary'), t4 = c('textDisabled');
    if (dark) {
        set('slate-50', t1); set('slate-100', t1);
        set('slate-200', mix(t1, t2, 0.5));
        set('slate-300', t2);
        set('slate-400', mix(t2, t3, 0.5));
        set('slate-500', t3);
        set('slate-600', t4);
        set('slate-700', c('borderStrong'));
        set('slate-800', c('bgElevated'));
        set('slate-900', c('bgBase'));
    } else {
        set('slate-50', c('bgInset'));
        set('slate-100', c('bgSurface2'));
        set('slate-200', c('borderDefault'));
        set('slate-300', c('borderStrong'));
        set('slate-400', mix(t3, t4, 0.5));
        set('slate-500', t3);
        set('slate-600', t2);
        set('slate-700', mix(t2, t1, 0.5));
        set('slate-800', t1); set('slate-900', t1);
    }
    // The sidebar stays dark in both appearances: the theme's sidebarBg when
    // its light text still reads on it, else the dark palette's base. A
    // translucent sidebarBg lets a wallpaper show through (themes.css).
    const sidebarBg = raw('sidebarBg') || (darkColors && _ctParse(darkColors.sidebarBg));
    const darkBase = darkColors && _ctParse(darkColors.bgBase);
    if (sidebarBg && _ctContrast(_CT_SIDEBAR_TEXT, sidebarBg) >= 3) {
        set('sidebar', sidebarBg);
        // Translucent, it must still read over the brightest wallpaper.
        let alpha = sidebarBg[3];
        while (alpha < 1 && _ctContrast(_CT_SIDEBAR_TEXT, _ctMix(_CT_WHITE, sidebarBg, alpha)) < 3) {
            alpha = Math.min(1, alpha + 0.05);
        }
        if (alpha < 1) {
            vars['--cw-sidebar-alpha'] = alpha.toFixed(2);
            vars['--cw-sidebar-blur'] = 'blur(20px) saturate(1.4)';
        }
    } else if (darkBase) {
        set('sidebar', _ctMix(darkBase, _CT_BLACK, 0.35));
    }
    return vars;
}

// Everything needed to paint one appearance of a theme; cached for <head>.
function _ctResolve(theme, dark) {
    const app = dark ? theme.dark : theme.light;
    const darkColors = theme.dark && theme.dark.colors;
    const vars = _ctVars((app && app.colors) || {}, darkColors, dark);
    if (!vars) return null;
    const wp = app && app.wallpaper;
    if (wp) {
        const clamp = (n, d) => Math.min(1, Math.max(0, n === undefined ? d : n));
        const opacity = clamp(wp.overlayOpacity, dark ? 0.3 : 0.4);
        vars['--cw-wallpaper-image'] = `url("${wp.image}")`;
        vars['--cw-wallpaper-position'] = `${clamp(wp.focusX, 0.5) * 100}% ${clamp(wp.focusY, 0.5) * 100}%`;
        vars['--cw-wallpaper-overlay'] = `rgba(${dark ? '0, 0, 0' : '255, 255, 255'}, ${opacity})`;
        if (wp.glass) vars['--cw-glass-alpha'] = dark ? '0.72' : '0.78';
    }
    const logo = theme.identity && theme.identity.logo;
    if (logo) vars['--cw-theme-logo'] = `url("${logo}")`;
    return { vars, wallpaper: wp ? (wp.glass ? 'glass' : 'on') : '', logo: !!logo };
}

function _ctPaint(state) {
    const root = document.documentElement;
    // Includes the variables <head> replayed from the cache.
    for (let i = root.style.length - 1; i >= 0; i--) {
        if (root.style[i].startsWith('--cw-')) root.style.removeProperty(root.style[i]);
    }
    root.removeAttribute('data-wallpaper');
    root.removeAttribute('data-theme-logo');
    if (!state) return;
    Object.entries(state.vars).forEach(([name, value]) => root.style.setProperty(name, value));
    if (state.wallpaper) root.setAttribute('data-wallpaper', state.wallpaper);
    if (state.logo) root.setAttribute('data-theme-logo', '');
}

function _ctCachedState(dark) {
    const cached = JSON.parse(localStorage.getItem(COLOR_THEME_CACHE_KEY) || 'null');
    return cached && cached.id === colorThemeId ? cached[dark ? 'dark' : 'light'] : null;
}

// Apply the selected theme for the current light/dark appearance. Called
// from applyTheme() in theme.js on every appearance change.
function applyColorTheme() {
    const dark = document.documentElement.classList.contains('dark');
    // Theme folders aren't listed until /api/themes answers (after login):
    // keep painting the cached theme instead of dropping to the default.
    if (!_ctLoaded && !colorThemes.some(th => th.id === colorThemeId)) {
        try { _ctPaint(_ctCachedState(dark)); } catch (_) { /* first paint already has it */ }
        return;
    }
    const theme = getColorTheme(colorThemeId);
    let state = null;
    try {
        if (theme.id !== DEFAULT_COLOR_THEME) {
            state = _ctResolve(theme, dark);
            if (!state) console.warn(`[theme] "${theme.id}" has unreadable text colors, using the default theme`);
        }
        _ctPaint(state);
    } catch (e) {
        console.warn(`[theme] failed to apply "${theme.id}", using the default theme:`, e);
        state = null;
        try { _ctPaint(null); } catch (_) { /* the base stylesheet still applies */ }
    }
    try {
        if (!state) localStorage.removeItem(COLOR_THEME_CACHE_KEY);
        else localStorage.setItem(COLOR_THEME_CACHE_KEY, JSON.stringify({
            id: theme.id, light: _ctResolve(theme, false), dark: _ctResolve(theme, true),
        }));
    } catch (_) { /* storage full or unavailable: only the first paint is affected */ }
}

function selectColorTheme(id) {
    colorThemeId = id;
    localStorage.setItem(COLOR_THEME_KEY, id);
    applyColorTheme();
    renderColorThemeMenu();
}

// ---- Theme menu -------------------------------------------------------------

function renderColorThemeMenu() {
    const list = document.getElementById('color-theme-list');
    if (!list) return;
    const active = getColorTheme(colorThemeId).id;
    list.innerHTML = colorThemes.map(th => {
        const p = th.preview || { accent: '#4abe6e', bg: '#111', surface: '#1c1c1f' };
        const swatch = [p.bg, p.surface, p.accent]
            .map(c => `<span style="background:${escapeHtml(c)}"></span>`).join('');
        return `<button type="button" class="color-theme-item" data-theme-id="${escapeHtml(th.id)}">
                    <span class="color-theme-swatch">${swatch}</span>
                    <span class="color-theme-name">${escapeHtml(th.name)}</span>
                    ${th.id === active ? '<i class="fas fa-check color-theme-check"></i>' : ''}
                </button>`;
    }).join('');
}

// The theme list flies out of the sidebar's footer menu on hover (or a tap),
// bottom-aligned with it, and stays open while picking so themes can be
// compared in place.
let _ctMenuCloseTimer = 0;

function openColorThemeMenu() {
    clearTimeout(_ctMenuCloseTimer);
    const menu = document.getElementById('color-theme-menu');
    const anchor = document.getElementById('update-menu');
    if (!menu || !anchor || anchor.classList.contains('hidden') || !menu.classList.contains('hidden')) return;
    // Layout offsets, not the anchor's own rect: that one moves while the
    // menu's slide-in animation runs.
    const parent = anchor.offsetParent || document.body;
    const base = parent.getBoundingClientRect();
    const left = base.left + parent.clientLeft + anchor.offsetLeft + anchor.offsetWidth;
    const bottom = base.top + parent.clientTop + anchor.offsetTop + anchor.offsetHeight;
    menu.style.left = `${left}px`;
    menu.style.bottom = `${window.innerHeight - bottom}px`;
    renderColorThemeMenu();
    menu.classList.remove('hidden');
    loadColorThemes();
}

function closeColorThemeMenu() {
    clearTimeout(_ctMenuCloseTimer);
    const menu = document.getElementById('color-theme-menu');
    if (menu) menu.classList.add('hidden');
}

// The row and the list are separate boxes: leaving one closes the list only
// if the pointer doesn't reach the other in time.
function scheduleCloseColorThemeMenu() {
    clearTimeout(_ctMenuCloseTimer);
    _ctMenuCloseTimer = setTimeout(closeColorThemeMenu, 120);
}

document.addEventListener('click', (e) => {
    const menu = document.getElementById('color-theme-menu');
    const item = e.target.closest && e.target.closest('.color-theme-item[data-theme-id]');
    if (menu && item && menu.contains(item)) selectColorTheme(item.dataset.themeId);
});

// ---- Custom theme dialog ----------------------------------------------------

function _themeDocsUrl() {
    return `${currentLang === 'zh' ? 'https://docs.cowagent.ai/zh' : 'https://docs.cowagent.ai'}/extensions/custom-theme`;
}

function openThemeAddModal() {
    closeColorThemeMenu();
    if (typeof closeUpdateMenu === 'function') closeUpdateMenu();
    const overlay = document.getElementById('theme-add-overlay');
    if (!overlay) return;
    _setThemeImportBusy(false);
    _setThemeImportError('');
    document.getElementById('theme-add-docs').href = _themeDocsUrl();
    const dir = document.getElementById('theme-add-dir');
    dir.textContent = colorThemesDir || COLOR_THEMES_DIR_HINT;
    loadColorThemes(true).then(() => { dir.textContent = colorThemesDir || COLOR_THEMES_DIR_HINT; });
    overlay.classList.remove('hidden');
}

function closeThemeAddModal() {
    const overlay = document.getElementById('theme-add-overlay');
    if (overlay) overlay.classList.add('hidden');
}

let _themeImportBusy = false;

function _setThemeImportBusy(busy) {
    _themeImportBusy = busy;
    const zone = document.getElementById('theme-drop-zone');
    if (!zone) return;
    zone.classList.toggle('is-busy', busy);
    document.getElementById('theme-drop-icon').className = busy ? 'fas fa-spinner fa-spin' : 'fas fa-file-arrow-up';
    document.getElementById('theme-drop-idle').classList.toggle('hidden', busy);
    document.getElementById('theme-drop-busy').classList.toggle('hidden', !busy);
}

function _setThemeImportError(msg) {
    const el = document.getElementById('theme-add-error');
    if (!el) return;
    el.textContent = msg;
    el.classList.toggle('hidden', !msg);
}

// Upload [{file, path}] and install the theme; asks before replacing one
// with the same id, and switches to it once imported.
async function importThemeFiles(entries, overwrite) {
    if (_themeImportBusy || !entries.length) return;
    _setThemeImportBusy(true);
    _setThemeImportError('');
    try {
        const form = new FormData();
        entries.forEach(({ file, path }) => {
            form.append('files', file, file.name);
            form.append('paths', path || file.name);
        });
        form.append('reserved', JSON.stringify(BUILTIN_COLOR_THEMES.map(th => th.id)));
        if (overwrite) form.append('overwrite', '1');
        const res = await fetch('/api/themes/import', { method: 'POST', body: form }).then(r => r.json());
        _setThemeImportBusy(false);
        if (res.status === 'exists') {
            showConfirmDialog({
                title: t('theme_import_replace_title'),
                message: t('theme_import_replace_msg').replace('{name}', res.name),
                okText: t('theme_import_replace_ok'),
                tone: 'primary',
                onConfirm: () => importThemeFiles(entries, true),
            });
        } else if (res.status === 'ok') {
            await loadColorThemes(true);
            selectColorTheme(res.id);
            closeThemeAddModal();
        } else {
            _setThemeImportError(t(`theme_import_err_${res.code || 'failed'}`));
        }
    } catch (_) {
        _setThemeImportBusy(false);
        _setThemeImportError(t('theme_import_err_failed'));
    }
}

// Walk a dropped folder into [{file, path}] (paths keep the folder name).
function _readDroppedEntry(entry, out) {
    if (entry.isFile) {
        return new Promise(resolve => entry.file(file => {
            out.push({ file, path: entry.fullPath.replace(/^\//, '') });
            resolve();
        }, () => resolve()));
    }
    if (!entry.isDirectory) return Promise.resolve();
    const reader = entry.createReader();
    const readAll = () => new Promise(resolve => reader.readEntries(async items => {
        if (!items.length) return resolve();
        await Promise.all(items.map(item => _readDroppedEntry(item, out)));
        resolve(readAll());
    }, () => resolve()));
    return readAll();
}

function _bindThemeAddModal() {
    const overlay = document.getElementById('theme-add-overlay');
    const zone = document.getElementById('theme-drop-zone');
    const input = document.getElementById('theme-file-input');
    if (!overlay || !zone || !input) return;

    overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) closeThemeAddModal(); });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !overlay.classList.contains('hidden')) closeThemeAddModal();
    });
    const pick = () => { if (!_themeImportBusy) input.click(); };
    zone.addEventListener('click', pick);
    zone.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); }
    });
    input.addEventListener('change', () => {
        const files = Array.from(input.files || []);
        input.value = '';
        importThemeFiles(files.map(file => ({ file, path: file.name })));
    });
    // While the dialog is open, file drags anywhere but the drop zone are
    // inert so they can't reach the chat input's attachment drop.
    ['dragenter', 'dragover', 'drop'].forEach(type => window.addEventListener(type, (e) => {
        if (overlay.classList.contains('hidden') || zone.contains(e.target)) return;
        e.preventDefault();
        e.stopPropagation();
        if (e.dataTransfer) e.dataTransfer.dropEffect = 'none';
    }, true));
    zone.addEventListener('dragenter', (e) => { e.preventDefault(); if (!_themeImportBusy) zone.classList.add('is-over'); });
    zone.addEventListener('dragover', (e) => { e.preventDefault(); e.stopPropagation(); });
    zone.addEventListener('dragleave', (e) => {
        if (!zone.contains(e.relatedTarget)) zone.classList.remove('is-over');
    });
    zone.addEventListener('drop', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        zone.classList.remove('is-over');
        if (_themeImportBusy) return;
        const items = Array.from(e.dataTransfer.items || []);
        const entries = [];
        const roots = items.map(item => item.webkitGetAsEntry && item.webkitGetAsEntry()).filter(Boolean);
        if (roots.length) {
            await Promise.all(roots.map(entry => _readDroppedEntry(entry, entries)));
        } else {
            Array.from(e.dataTransfer.files || []).forEach(file => entries.push({ file, path: file.name }));
        }
        if (entries.length) importThemeFiles(entries);
        else _setThemeImportError(t('theme_import_err_no_theme'));
    });
}

// Start a new chat with the theme prompt typed in, ready for the user to
// describe the style and send.
function startThemeWithAgent() {
    closeThemeAddModal();
    const prompt = t('theme_agent_prompt').replace('{dir}', colorThemesDir || COLOR_THEMES_DIR_HINT);
    if (currentView !== 'chat') navigateTo('chat');
    newChat();
    chatInput.value = prompt;
    chatInput.dispatchEvent(new Event('input', { bubbles: true }));
    chatInput.focus();
    chatInput.selectionStart = chatInput.selectionEnd = chatInput.value.length;
}

// auth.js loads after this file; wait until every script has run.
document.addEventListener('DOMContentLoaded', () => {
    _bindThemeAddModal();
    requestAuthGatedStart(() => loadColorThemes(true));
});
