// The docs assistant: the chat window from a guest page, embedded the same
// way any site embeds one. Chinese pages get the Chinese assistant, every
// other page the English one. `?chat=open` opens the window on arrival.
(function () {
  var HOST = 'https://ask.cowagent.ai';
  var SHARES = {
    zh: { token: 'uyc00EYyjB3eym5_uhGdixkF', title: 'CowAgent 开源助手' },
    en: { token: 'c2CAAU0eKg5U-W-mOY6JAF8u', title: 'CowAgent Assistant' }
  };
  var current = '';

  function langOf(path) {
    return /^\/zh(\/|$)/.test(path || '') ? 'zh' : 'en';
  }

  function mount(lang, open) {
    if (lang === current) return;
    // Pages change without a reload, so a language switch swaps the window.
    document.querySelectorAll('.cow-guest-btn, .cow-guest-panel').forEach(function (el) { el.remove(); });
    current = lang;
    var share = SHARES[lang];
    var script = document.createElement('script');
    script.src = HOST + '/assets/guest/embed.js';
    script.setAttribute('data-share-url', HOST + '/share/' + share.token);
    script.setAttribute('data-title', share.title);
    if (open) script.setAttribute('data-open', 'true');
    document.body.appendChild(script);
  }

  mount(langOf(location.pathname), new URLSearchParams(location.search).get('chat') === 'open');
  window.addEventListener('mintlify:navigate', function () {
    mount(langOf(location.pathname), false);
  });
})();
