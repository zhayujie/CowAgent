/* Light/dark theme toggle.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Theme
// =====================================================================
// Each page sets its own default before first paint; light if none did.
let currentTheme = localStorage.getItem('cow_theme') || window.__COW_DEFAULT_THEME__ || 'light';

function applyTheme() {
    const root = document.documentElement;
    if (currentTheme === 'dark') {
        root.classList.add('dark');
        document.getElementById('theme-icon').className = 'fas fa-sun';
        document.getElementById('hljs-light').disabled = true;
        document.getElementById('hljs-dark').disabled = false;
    } else {
        root.classList.remove('dark');
        document.getElementById('theme-icon').className = 'fas fa-moon';
        document.getElementById('hljs-light').disabled = false;
        document.getElementById('hljs-dark').disabled = true;
    }
    // Color themes (themes.js) are console-only; the guest page has none.
    if (typeof applyColorTheme === 'function') applyColorTheme();
    rerenderMermaidDiagrams();
}

// Mermaid bakes the theme colors into the rendered SVG, so a theme switch
// re-renders diagrams the user already previewed. Never-previewed blocks are
// left alone, so this never triggers the mermaid download by itself.
function rerenderMermaidDiagrams() {
    document.querySelectorAll('.mermaid-block[data-mermaid="done"]').forEach(block => {
        block.dataset.mermaid = 'pending';
        const figure = block.querySelector('.mermaid-figure');
        if (figure) figure.remove();
    });
    if (document.querySelector('.mermaid-block[data-mermaid="pending"]')) {
        renderMermaidBlocks(document);
    }
}

function toggleTheme() {
    currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('cow_theme', currentTheme);
    applyTheme();
}

