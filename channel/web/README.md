# Web Channel

A default chat console: text and image messages, markdown rendering, and the
management views (agents, settings, skills, memory, knowledge, channels,
scheduled tasks, logs).

# Usage

- Set `channel_type` to `web` in `config.json`.
- The process listens on port 9899; open http://localhost:9899/ in a browser.
- The port can be changed with `web_port` in the config file.
- Under Docker, map the port to the host in `docker-compose.yml` if it has to
  be reachable from outside.

# Backend layout

`web_channel.py` is the URL table and nothing else: 77 routes, `build_app()`,
and the imports that put every handler in scope. web.py resolves the handler
names in the table against a namespace dict, so every handler has to be
importable there -- that is why the file imports names it never calls.

The code sits in two packages, mirroring the frontend's `core/` and `views/`:

### `core/` -- shared by the channel and the handlers

| File | Responsibility |
|---|---|
| `channel.py` | `WebChannel`: the server, the message queues, SSE stream state. The only part that is a channel rather than an HTTP endpoint |
| `_common.py` | Auth checks, the workspace root, upload dirs, preview tokens, the path allow-list, `WebMessage` |
| `template.py` | Page assembly and asset stamping (see [Page assembly](#page-assembly)) |
| `providers.py` | The vendor catalogue, and the helpers that read a provider's configured values |

### `api/` -- one module per view

| File | Routes |
|---|---|
| `pages.py` | `/`, `/chat`, the in-app view paths, `/assets/*`, `/health` |
| `auth.py` | `/api/auth/*`, the MCP OAuth callback |
| `chat.py` | `/api/message`, `/api/poll`, `/api/cancel`, the SSE stream |
| `files.py` | Uploads, `/api/file`, `/uploads/*`, `/preview/*`, ASR and TTS |
| `sessions.py` | `/api/sessions/*`, `/api/history`, per-session settings and context |
| `agents.py` | `/api/agents/*`, core files, avatars |
| `config.py` | `/api/config` |
| `models.py` | `/api/models` |
| `channels.py` | `/api/channels`, the WeChat QR and Feishu registration flows |
| `scheduler.py` | `/api/scheduler/*` |
| `skills.py`, `memory.py`, `knowledge.py`, `logs.py` | The remaining management views |
| `update.py` | `/VERSION`, `/api/update/*` |
| `openai_compat.py` | `/v1/chat/completions` |

Two things to know before moving code between these modules:

- **A handler reads its collaborators out of its own module's globals.** A test
  that patches `conf` or `_require_auth` has to name the module the handler
  lives in; patching `channel.web.web_channel.conf` reaches nothing. Where a
  test helper takes the handler class, read the module off
  `handler_cls.__module__` rather than naming one.
- **Paths derived from `__file__` are relative to the module, not the web
  root.** `core/template.py`, `core/channel.py` and `api/pages.py` all sit one
  level below `channel/web/`, so each walks up a directory to find `static/`
  and `templates/`. A module moved between `api/` and the web root has to have
  this checked.

A test that asserts "this is still wired up" should read `web_backend_py()`
from `tests/conftest.py`, which concatenates every Python file under
`channel/web/`, rather than one file. A test that parses a specific structure
-- the URL table, a class body -- should keep reading the file it means, so it
fails loudly when that structure moves.

# Frontend layout

The console used to be three very large files (`console.js` at 16k lines,
`console.css` at 3.9k, `chat.html` at 2.1k). It is now split by concern. There
is no bundler: every script is a classic script, executed in document order via
`defer`, sharing one global scope.

## Page assembly

`chat.html` is the page shell. It pulls fragments in with
`<!--#include templates/xxx.html-->` markers, which `core/template.py` expands on
the server before the page is sent. Assembly happens server-side rather than by
fetching at runtime because the page relies on the Tailwind CDN JIT compiler,
whose behaviour is only predictable when the whole DOM is present at parse
time.

`core/template.py` also stamps every `assets/js/**` and `assets/css/**` reference
with a `?v=` version so an upgraded console never runs against cached old
scripts. **Adding a script or stylesheet needs no Python change**; the pattern
match picks it up.

The version is each file's own modification time, not the request time. A
request-time stamp changed the URL on every request, so all 46 assets (about
1 MB) were re-downloaded on every reload. Per-file stamps only move when the
file actually changes, which lets `AssetsHandler` promise `immutable` for
stamped first-party assets: an unchanged file is never requested again, and a
changed file gets a new URL and takes effect immediately, so nothing can get
stuck on an old version.

`assets/vendor/**` is pinned and not stamped. Like the logos and fonts it is
served with an `ETag`: the browser still asks, but a hit is a `304` with no
body.

Two rules for includes:

- A marker must sit alone on its line, **flush left**. `core/template.py` replaces
  the marker text in place, so any indentation before the marker would be
  prepended to the fragment's first line. Fragments carry their own
  indentation.
- One trailing newline is stripped from the fragment; the marker line's own
  newline takes its place. Fragment files can therefore end with a newline like
  any other file without producing a blank line.

## Fragments `templates/`

| File | Contents |
|---|---|
| `layout/login.html` | Login overlay |
| `layout/sidebar.html` | Left navigation (`data-view` names the target), the update menu on the version row, mobile overlay |
| `layout/session-panel.html` | Session history side panel |
| `layout/header.html` | Top bar: panel toggle, breadcrumb, language/theme switches, logout |
| `views/chat.html` | Chat view: message list, composer card, workspace panel |
| `views/agents.html` | Agent team: list, detail drawer, create form |
| `views/config.html` | Settings view with the "basic" and "models" tabs |
| `views/skills.html` | Skill list and skill definition viewer |
| `views/memory.html` | Memory list and file viewer |
| `views/knowledge.html` | Knowledge base: documents panel and relation graph panel |
| `views/channels.html` | Channels view (content injected by JS) |
| `views/tasks.html` | Scheduled tasks and run records |
| `views/logs.html` | Log terminal |
| `modals/team-chat.html` | New multi-agent conversation |
| `modals/knowledge-dialog.html` | Knowledge create/rename/delete dialog |
| `modals/confirm-dialog.html` | Static confirm dialog |
| `modals/rename-dialog.html` | Channel instance rename |
| `modals/folder-picker.html` | Project folder picker |
| `modals/vendor.html` | Vendor credentials and model catalog editor |
| `modals/custom-provider.html` | Custom OpenAI-compatible provider |
| `modals/task-edit.html` | Scheduled task create/edit |
| `modals/run-detail.html` | Run record detail |

Names that are easy to misread:

- **Model management is not its own view.** It is the `#config-panel-models`
  tab inside `views/config.html`; JS injects the content into `#models-content`.
- **The scheduled-tasks container is `#view-tasks`**, not "scheduler".
- Session history is the `#session-panel` side panel, not a `.view`.
- The workspace panel is nested inside `views/chat.html`, not a top-level view.

`templates/` lives outside `static/`, so `AssetsHandler` never exposes it.

## Scripts `static/js/`

**These are classic scripts, not ES modules.** They share one global scope and
execute in the order `chat.html` lists them, via `defer`. Everything else in
the frontend rests on this:

- The 700-odd top-level declarations are all implicit globals, and **generated
  HTML leans on that with `onclick="foo()"` everywhere**. Switching to
  `type="module"` or wrapping a file in an IIFE would silently break every one
  of those inline calls.
- Top-level `const`/`let` land in the shared global lexical environment and are
  visible across files, but with a TDZ: **no file can read a `const`/`let`
  declared by a later file while its own top level is running.** All startup
  code that must run immediately is collected in `boot.js`, which has to load
  last.
- **The TDZ restriction propagates along the call chain, and that is the
  easiest trap to fall into.** A top-level `let x = someFunc();` looks like it
  only depends on `someFunc`, but any later file's `let`/`const` that
  `someFunc` reads throws `ReferenceError`. Once that happens **none of the
  remaining top-level declarations in that file run**; those `const`s stay in
  the TDZ for good, and everything that reads them keeps throwing. It shows up
  as a whole view failing, not one small feature. It only surfaces in a
  browser; a static search will not find it. Two known instances are listed
  under the load-order constraints below.
- The same top-level name declared in two files is a `SyntaxError` and a blank
  page. Check for a clash before adding a declaration.
- **Do not reassign an existing global at top level.** Which version a reader
  sees would then depend on load order, and nothing static will catch that.
  There are currently none; `tests/test_web_console_assets.py` guards the
  script list and load order.

Two checks hold these rules in place.

`tests/test_web_console_assets.py` runs with the suite and pins the script list
and the known order dependencies: every script is loaded exactly once, there
are no orphan files, no duplicate globals, every script is actually reachable
through `AssetsHandler`, and each of the "three load-order constraints" below
holds.

`channel/web/tools/check-load-order.mjs` uses AST analysis to find **new** order
problems -- the only way to catch the transitive TDZ described above. Run it
after reordering scripts or adding top-level code:

```
node --stack-size=40000 channel/web/tools/check-load-order.mjs
```

It needs the TypeScript parser in `desktop/node_modules` (present after
`npm install` under `desktop/`), which is why it is not part of the Python
suite. `--stack-size` is required: the default stack cannot walk an AST of this
size.

## Address-bar routing

The console is the app at `/`, and its views and tabs are paths under it:
`/agents`, `/settings`, `/settings/models`. A reload lands where the user left
off, links can be shared, and Back/Forward move between views. `/chat` is the
old address and stays as a redirect to `/` (the URL table must hold exactly one
`/chat` entry; web.py takes the first match, so a second one is dead code).

**A route name is not always the view's internal id.** The settings view's id
is `config`, but its URL is `/settings`, because `/config` is already the
backend's config API, which both this console and the desktop client call. The
URL table in `web_channel.py` points these paths at the same shell and the
frontend router opens the view; the two tables have to agree, and
`tests/test_web_console_routing.py` compares them.

The same holds for tabs, see `ROUTE_TAB_PATHS`: the memory view's
self-evolution tab has the element id `dreams`, but its URL segment is
`evolution` -- a path should name the concept the user sees, not the internal
code name. The alias only affects the URL; the element id,
`switchMemoryTab('dreams')` and `ROUTE_TABS` all stay as they are. A
hand-written `/memory/dreams` still opens the tab and is normalised to
`/memory/evolution`.

The scheduled-tasks view has the internal id `tasks` but the URL `/scheduler`,
because the backend already calls this area scheduler (`/api/scheduler/...`)
and the word "tasks" is needed elsewhere; `/tasks` is left free for it.

**A view's default tab does not appear in the path**, see
`ROUTE_DEFAULT_TABS`: `/scheduler` is the task list, not `/scheduler/tasks`;
only a non-default tab adds a segment, as in `/scheduler/records`,
`/settings/models`, `/knowledge/graph`. The converse matters just as much: no
tab segment **means** the default tab rather than "leave the tab alone". Going
Back from `/scheduler/records` to `/scheduler` has to switch the task tab back
on, otherwise the page stays on the run records while the trailing write at the
end of `routeApply` pushes the address bar to `/scheduler/records` again, which
looks exactly like Back not working.

The view paths come **last** in the URL table: web.py takes the first match, so
no view name can shadow an API route above it -- and a new API route cannot
collide with a view name either.

**Asset references in the page must be absolute** (`/assets/js/...`). Path
routing depends on it: a relative reference under `/settings/models` would
resolve to `/settings/assets/...` and 404 the whole page. This gives up nothing
for reverse-proxy subpath mounts (say `https://host/cow/`): the console could
never be mounted that way, since every API call it makes is already an absolute
`/api/...` path. Supporting a subpath would mean prefixing all of them, not
making asset references relative again.

Routing stops at view and tab. Deeper state -- the open session, the file in
the editor -- deliberately stays out of the URL: it is already restored from
localStorage, and putting it in the URL would rewrite the address bar on every
click in the session list.

Three rules shape the history stack:

- **Switching views** pushes an entry, so Back returns to the previous view.
- **Switching tabs** replaces the current entry instead of adding one, so Back
  leaves the view rather than walking back through every tab visited inside it.
- **Re-entering the current view** (clicking the already selected sidebar item)
  is also a replace; otherwise Back would appear to do nothing after a few
  clicks.

The address bar is only ever written with `pushState`/`replaceState`, which do
not fire `popstate`, so a write cannot loop back in as a navigation. Back and
Forward, which do fire `popstate`, are the single entry point; the
`_routeApplying` flag suppresses writes while a route is being applied, so no
duplicate entries are created.

Unsaved edits still block navigation. On Back the address bar has already
moved; `navigateTo` returns `false` when the guard refuses, and the router puts
the address bar back with `replaceState` until the user confirms discarding.

`channel/web/tools/check-router.mjs` verifies this behaviour: it stubs
`location`/`history`/the DOM and drives the router through the scenarios above,
checking the count and content of history entries. No dependencies, no browser;
run it after touching the router:

```
node channel/web/tools/check-router.mjs
```

The Python tests can only pin the wiring (the tab vocabulary matches the DOM,
every tab switcher reports to the router, the first route is applied only after
auth), see `tests/test_web_console_routing.py`.

### core/ -- infrastructure shared across views

| File | Responsibility |
|---|---|
| `core/version.js` | Version label (filled from the backend's `/VERSION`) and the one-click update menu on the version row |
| `core/i18n.js` | Translation table and `t()` / `applyI18n()` / `setLanguage()` |
| `core/theme.js` | Light/dark theme switch |
| `core/utils.js` | `escapeHtml`, time formatting, scroll helpers, tool argument summaries |
| `core/mermaid-fence.js` | Which mermaid fences are complete enough to draw (same rules as desktop) |
| `core/markdown.js` | markdown-it setup; image, video, code block and mermaid rendering |
| `core/confirm.js` | Scripted confirm dialog shared by the views |
| `core/notify.js` | Task completion notifications and notification permission |
| `core/nav.js` | `navigateTo` view switching and each view's lazy-load hook |
| `core/router.js` | Address-bar routing: parsing and writing `/view/tab`, Back/Forward; see above |
| `core/auth.js` | Login screen, logout, the 401 interceptor on `fetch`, the auth gate for background pollers. **Loads last, see below** |

### chat/ -- the chat view

| File | Responsibility |
|---|---|
| `chat/state.js` | Session and streaming state, history loading, attachments, `agent_id` injection into `fetch` |
| `chat/context-usage.js` | Usage popover on the clear-context button and compaction |
| `chat/workspace-selector.js` | Project selector above the input and the file picker dialog |
| `chat/session-settings.js` | Per-session permission mode and model: the two chips under the input |
| `chat/composer-input.js` | Drag-and-drop upload, paste, slash command menu, input key handling |
| `chat/message-actions.js` | Voice messages, copy, editing a sent message |
| `chat/send.js` | Send, regenerate, SSE streaming with polling fallback |
| `chat/scheduler-notify.js` | Cross-session notifications from scheduled tasks |
| `chat/render.js` | Message DOM: user/bot bubbles, steps, voice pills, history rendering |
| `chat/timeline.js` | Message navigator: header button listing the conversation's questions, click one to jump to it |
| `chat/new-chat.js` | New conversation and multi-agent conversation |

### views/ -- the management pages

| File | Responsibility |
|---|---|
| `views/sessions.js` | Session history panel: list, pin, rename, project grouping |
| `views/agents.js` | Agent list, detail drawer, avatars, core files |
| `views/config.js` | Basic settings tab |
| `views/models.js` | Models tab: vendors, capability cards, fallback chain, model catalog |
| `views/models-custom-provider.js` | Add/edit dialog for custom OpenAI-compatible providers |
| `views/channels.js` | Channel list, binding and configuration |
| `views/channels-weixin.js` | WeChat QR login |
| `views/channels-wecom.js` | WeCom bot QR authorisation |
| `views/channels-feishu.js` | Feishu one-click app registration |
| `views/tasks.js` | Scheduled tasks and run records |
| `views/tasks-modal.js` | Scheduled task create/edit dialog |
| `views/skills.js` | Built-in tools and installed skills |
| `views/memory.js` | Memory file list |
| `views/doc-viewers.js` | Viewer/editor for memory files and skill definitions |
| `views/knowledge.js` | Knowledge tree, import, relation graph |
| `views/logs.js` | Live log stream |
| `boot.js` | Startup: apply theme and language, auth gate, first fetch of config and history |

### Three load-order constraints that must not move

Beyond the general "core before views", three orderings are hard constraints;
changing them produces runtime errors:

1. **`views/agents.js` must precede `chat/state.js`**, even though it lives
   under `views/`. `chat/state.js` runs `let sessionId = loadOrCreateSessionId()`
   at top level, and `activeSessionStorageKey()` compares `activeAgentId` with
   `defaultAgentId`, a `let` in `views/agents.js`. Moving it later is the
   transitive TDZ described above and takes the whole chat view down. Note the
   short-circuit in `activeAgentId &&`: **only users who have ever picked an
   agent trigger it**; a fresh install shows nothing wrong.
2. **`core/auth.js` must follow `chat/state.js`**, which is why it sits at the
   end of the core layer. Both wrap `window.fetch`: `chat/state.js` appends
   `agent_id` to the URL, `core/auth.js` checks the URL prefix to decide
   whether a 401 should go to the login screen. The later wrapper is the outer
   one, so the 401 check sees the caller's original URL. The auth gate
   (`requestAuthGatedStart` / `openAuthGate`) is in this file too; the only
   top-level caller is `boot.js`, which loads later, so no TDZ is hit.
3. **`boot.js` must precede `workspace.js`**, which is where `console.js` used
   to be. `applyI18n()` probes `relocalizeWorkspacePanel` with a `typeof`
   guard, and it has always run before `workspace.js` defines that function;
   moving it later changes the behaviour. (`typeof` is safe for a **function
   declaration** in a not-yet-loaded script and returns `'undefined'`; for
   `let`/`const` it throws the same TDZ error, so do not rely on it to probe
   variables.)

### Two files left unsplit

`workspace.js` and `doc-editor.js` are unchanged; they were separate files to
begin with. Their positions are constrained:

- `doc-editor.js` **must load first**, because `views/doc-viewers.js` calls
  `createDocEditor()` at top level to build `memoryEditor` and `skillEditor`.
- `workspace.js` **must load last**; it consumes `t`, `escapeHtml`,
  `renderMarkdown`, `showConfirmDialog`, `_wsToast`, `sessionId`,
  `activeAgentId` and a number of other globals.

### Known coupling that the split did not remove

The split moved code; it did not decouple it. These remain and need care:

- `_wsToast` is defined in `chat/workspace-selector.js` but used by the context
  popover, session settings, the skills page, `doc-editor.js` and
  `workspace.js`. It belongs in `core/`.
- The `chat/` files share mutable globals such as `sessionId`, `chatInput`,
  `messagesDiv` and `_sessCfg`; the split divided the files by responsibility
  without gathering the state.
- `startSSE()` in `chat/send.js` is a single 600-line function, the largest
  piece in the frontend.
- The input `keydown` handler in `chat/composer-input.js` is 92 lines and
  handles both slash-command navigation and sending.
- The tail of `views/agents.js` holds three helpers used by the memory page.
- `views/models.js` (2.3k lines) and `core/i18n.js` (1.8k) are still large.
  The latter is mostly the translation table itself, so splitting it would gain
  little.

## Stylesheets `static/css/`

**Load order is cascade order: a later file overrides an earlier one. Read this
section before reordering or inserting a file.**

| File | Responsibility |
|---|---|
| `base.css` | Keyframes, scrollbars, shared tooltip, `.view` switching, chat column layout, mobile adjustments |
| `sessions.css` | Sidebar, session history panel and list, project grouping, drag ordering, rename |
| `components.css` | Controls shared across views: `cfg-dropdown`, form controls, confirm dialog, update menu, API key masking, floating tooltip |
| `markdown.css` | Message body rendering: markdown, thinking/tool/subagent steps, log colouring, code block frame |
| `chat.css` | Input and composer card, attachment bar, slash command menu, context usage popover, drop overlay, voice pill |
| `workspace.css` | Workspace panel and project selector, document editor, artifact cards, `@` mention menu |
| `knowledge.css` | Knowledge document tree and relation graph |
| `agents.css` | Agent cards, detail drawer, composer identity badge |

Two things to watch when moving rules:

- **Dark mode does not use CSS variables.** Rules are written in light/dark
  pairs with a `.dark` ancestor selector. Move both halves of a pair together or
  dark mode silently breaks.
- `sessions.css` must precede `components.css`: both size `.agent-avatar` at
  the same specificity, and flipping the order gives the session list the wrong
  avatar size.
