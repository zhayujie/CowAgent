/* Light/dark theme toggle.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Theme
// =====================================================================
let currentTheme = localStorage.getItem('cow_theme') || 'dark';

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
    if (typeof rerenderMermaidForTheme === 'function') rerenderMermaidForTheme();
}

function toggleTheme() {
    currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('cow_theme', currentTheme);
    applyTheme();
}

