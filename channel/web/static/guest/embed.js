/* Floating chat window for a guest share page.
 *
 *   <script src="https://HOST/assets/guest/embed.js"
 *           data-share-url="https://HOST/share/TOKEN" data-title="Help" defer></script>
 *
 * Optional: data-color (color behind the fold icon while open), data-position
 * ("right" or "left"). The launcher shows the page's logo.
 *
 * The chat runs in an iframe on the CowAgent origin, so the host page never
 * sees the visitor token. The host's origin must be listed in the profile's
 * access.allowed_origins, or the browser refuses to frame the page.
 */
(function () {
  'use strict';
  var script = document.currentScript;
  if (!script) return;
  var url = script.getAttribute('data-share-url');
  if (!url) return;
  var title = script.getAttribute('data-title') || 'Chat';
  var color = script.getAttribute('data-color') || '#4ABE6E';
  var side = script.getAttribute('data-position') === 'left' ? 'left' : 'right';

  var css = [
    '.cow-guest-btn{position:fixed;' + side + ':20px;bottom:20px;width:48px;height:48px;border-radius:50%;border:none;',
    'padding:0;cursor:pointer;z-index:2147483000;color:#fff;display:flex;align-items:center;justify-content:center;',
    'overflow:hidden;box-shadow:0 8px 24px -8px rgba(0,0,0,.35),0 2px 6px rgba(0,0,0,.12);',
    'transition:transform .2s ease,box-shadow .2s ease}',
    '.cow-guest-btn:hover{transform:translateY(-2px);box-shadow:0 12px 28px -8px rgba(0,0,0,.4),0 2px 6px rgba(0,0,0,.12)}',
    '.cow-guest-btn img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}',
    // The default logo is a rounded square on white; crop to the color.
    '.cow-guest-btn img.cow-default{transform:scale(1.25)}',
    '.cow-guest-btn .cow-ico-fold{display:none}',
    '.cow-guest-btn.cow-open img{display:none}',
    '.cow-guest-btn.cow-open .cow-ico-fold{display:block}',
    '.cow-guest-panel{position:fixed;' + side + ':20px;bottom:80px;width:400px;height:640px;',
    'max-height:calc(100vh - 104px);border-radius:16px;overflow:hidden;z-index:2147483000;background:#fff;',
    'border:1px solid rgba(15,23,42,.08);box-shadow:0 24px 60px -16px rgba(0,0,0,.35);',
    'opacity:0;transform:translateY(12px) scale(.98);transform-origin:bottom ' + side + ';pointer-events:none;',
    'visibility:hidden;transition:opacity .2s ease,transform .2s ease,visibility 0s linear .2s}',
    '.cow-guest-panel.cow-open{opacity:1;transform:none;pointer-events:auto;visibility:visible;',
    'transition:opacity .2s ease,transform .2s ease}',
    '.cow-guest-panel iframe{width:100%;height:100%;border:0;display:block}',
    '@media (max-width:600px){.cow-guest-panel{' + side + ':0;bottom:0;width:100vw;height:100%;max-height:none;',
    'border-radius:0;border:none}.cow-guest-btn.cow-open{display:none}}'
  ].join('');
  var style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  var panel = document.createElement('div');
  panel.className = 'cow-guest-panel';
  var frame = null;

  var button = document.createElement('button');
  button.className = 'cow-guest-btn';
  button.type = 'button';
  button.style.background = color;
  button.setAttribute('aria-label', title);
  button.setAttribute('aria-expanded', 'false');
  button.title = title;
  button.innerHTML =
    '<svg class="cow-ico-fold" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path fill="none" ' +
    'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" d="M6 9l6 6 6-6"/></svg>';
  // The page's own logo, or the default one when it has none.
  var base = url.split('?')[0].replace(/\/+$/, '');
  var icon = document.createElement('img');
  icon.alt = '';
  icon.onerror = function () {
    icon.onerror = null;
    icon.className = 'cow-default';
    icon.src = base.replace(/\/share\/[^/]+$/, '') + '/assets/logo.jpg';
  };
  icon.src = base + '/api/logo';
  button.appendChild(icon);

  var isOpen = false;
  var frameReady = false;

  function showPanel() {
    panel.classList.toggle('cow-open', isOpen);
  }

  function setOpen(open) {
    isOpen = open;
    if (open && !frame) {
      frame = document.createElement('iframe');
      frame.src = url + (url.indexOf('?') === -1 ? '?' : '&') + 'embed=1';
      frame.title = title;
      frame.setAttribute('referrerpolicy', 'no-referrer');
      frame.setAttribute('allow', 'clipboard-write');
      // Shown once the page has painted, so the empty window never flashes
      // in a color the page's theme does not use.
      var ready = function () {
        if (frameReady) return;
        frameReady = true;
        showPanel();
      };
      frame.addEventListener('load', ready);
      setTimeout(ready, 3000);
      panel.appendChild(frame);
    }
    if (frameReady) showPanel();
    button.classList.toggle('cow-open', open);
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  button.addEventListener('click', function () {
    setOpen(!isOpen);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && isOpen) setOpen(false);
  });
  window.addEventListener('message', function (e) {
    if (frame && e.source === frame.contentWindow && e.data && e.data.type === 'cow-guest:close') setOpen(false);
  });

  document.body.appendChild(panel);
  document.body.appendChild(button);
})();
