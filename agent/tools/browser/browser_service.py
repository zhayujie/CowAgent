"""
Browser service - Playwright wrapper managing browser lifecycle and page operations.

All Playwright calls run on a dedicated background thread so that callers from
any worker thread can safely use the service.  An idle-timeout mechanism
automatically shuts down the browser (and its thread) after a configurable
period of inactivity to free resources.
"""

import os
import sys
import uuid
import queue
import threading
from typing import Optional, Dict, Any, List, Callable

from common.log import logger
from common.utils import expand_path, is_cloud_deployment


_DEFAULT_USER_DATA_DIR = "~/.cow/browser_profile"

try:
    from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False


# ---------------------------------------------------------------------------
# Snapshot DOM helpers
# ---------------------------------------------------------------------------

# Tags that typically carry useful content for an agent
_INTERACTIVE_TAGS = {
    "a", "button", "input", "textarea", "select", "option",
    "label", "details", "summary",
}
_SEMANTIC_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "li", "td", "th", "caption", "figcaption", "blockquote", "pre", "code",
    "nav", "main", "article", "section", "header", "footer", "form", "table",
    "img", "video", "audio",
}
_KEEP_TAGS = _INTERACTIVE_TAGS | _SEMANTIC_TAGS

_SNAPSHOT_JS = """
() => {
    const KEEP = new Set(%s);
    const INTERACTIVE = new Set(%s);
    const SKIP = new Set(["script","style","noscript","svg","path","meta","link","br","hr"]);
    const CLICKABLE_ROLES = new Set([
        "button","link","tab","menuitem","menuitemcheckbox","menuitemradio",
        "option","switch","checkbox","radio","combobox","searchbox","slider",
        "spinbutton","textbox","treeitem"
    ]);
    let refCounter = 0;
    const refMap = {};

    function visible(el) {
        if (!(el instanceof HTMLElement)) return true;
        const st = window.getComputedStyle(el);
        if (st.display === "none" || st.visibility === "hidden") return false;
        if (parseFloat(st.opacity) === 0) return false;
        return true;
    }

    // Strong signals: these attributes alone are enough to mark as interactive
    function hasStrongInteractiveSignal(el) {
        const role = el.getAttribute("role");
        if (role && CLICKABLE_ROLES.has(role)) return true;
        if (el.hasAttribute("onclick") || el.hasAttribute("tabindex")) return true;
        if (el.hasAttribute("data-click") || el.hasAttribute("data-action")) return true;
        if (el.getAttribute("contenteditable") === "true") return true;
        return false;
    }

    // Check if cursor:pointer is set directly (not just inherited from parent)
    function hasOwnPointerCursor(el) {
        try {
            const st = window.getComputedStyle(el);
            if (st.cursor !== "pointer") return false;
            const parent = el.parentElement;
            if (parent) {
                const pst = window.getComputedStyle(parent);
                if (pst.cursor === "pointer") return false;
            }
            return true;
        } catch(e) {}
        return false;
    }

    function hasTextOrContent(el) {
        const t = el.textContent || "";
        if (t.trim().length > 0) return true;
        if (el.querySelector("img,video,audio,canvas")) return true;
        const ariaLabel = el.getAttribute("aria-label");
        if (ariaLabel && ariaLabel.trim()) return true;
        const title = el.getAttribute("title");
        if (title && title.trim()) return true;
        return false;
    }

    function isImplicitInteractive(el) {
        if (hasStrongInteractiveSignal(el)) return true;
        if (hasOwnPointerCursor(el) && hasTextOrContent(el)) return true;
        return false;
    }

    function getTextContent(el) {
        let text = "";
        for (const ch of el.childNodes) {
            if (ch.nodeType === Node.TEXT_NODE) {
                text += ch.textContent;
            }
        }
        return text.trim();
    }

    function walk(node) {
        if (node.nodeType === Node.TEXT_NODE) {
            const t = node.textContent.trim();
            return t ? t : null;
        }
        if (node.nodeType !== Node.ELEMENT_NODE) return null;
        const tag = node.tagName.toLowerCase();
        if (SKIP.has(tag)) return null;
        if (!visible(node)) return null;

        const children = [];
        for (const ch of node.childNodes) {
            const r = walk(ch);
            if (r !== null) {
                if (typeof r === "string") children.push(r);
                else children.push(r);
            }
        }

        const nativeInteractive = INTERACTIVE.has(tag);
        const implicitInteractive = !nativeInteractive && (node instanceof HTMLElement) && isImplicitInteractive(node);
        const keep = KEEP.has(tag) || implicitInteractive;

        if (!keep) {
            if (children.length === 0) return null;
            if (children.length === 1) return children[0];
            return children;
        }

        const obj = { tag };
        if (nativeInteractive || implicitInteractive) {
            refCounter++;
            obj.ref = refCounter;
            refMap[refCounter] = node;
        }

        if (implicitInteractive) {
            const role = node.getAttribute("role");
            if (role) obj.role = role;
            const directText = getTextContent(node);
            if (!directText && children.length === 0) {
                const ariaLabel = node.getAttribute("aria-label");
                const title = node.getAttribute("title");
                if (ariaLabel) obj.ariaLabel = ariaLabel;
                else if (title) obj.ariaLabel = title;
            }
        }

        // Attributes
        if (tag === "a" && node.href) obj.href = node.getAttribute("href");
        if (tag === "img") {
            obj.alt = node.alt || "";
            obj.src = node.getAttribute("src") || "";
        }
        if (tag === "input" || tag === "textarea" || tag === "select") {
            obj.type = node.type || "text";
            obj.name = node.name || undefined;
            obj.value = node.value || undefined;
            obj.placeholder = node.placeholder || undefined;
            if (node.disabled) obj.disabled = true;
            if (tag === "input" && node.type === "checkbox") obj.checked = node.checked;
        }
        if (tag === "button") {
            if (node.disabled) obj.disabled = true;
        }
        if (tag === "option") {
            obj.value = node.value;
            if (node.selected) obj.selected = true;
        }
        if (tag === "label" && node.htmlFor) obj.for = node.htmlFor;

        // Role / aria-label for native interactive & semantic elements
        if (!implicitInteractive) {
            const role = node.getAttribute("role");
            if (role) obj.role = role;
            const ariaLabel = node.getAttribute("aria-label");
            if (ariaLabel) obj.ariaLabel = ariaLabel;
        }

        // Children
        if (children.length === 1 && typeof children[0] === "string") {
            obj.text = children[0];
        } else if (children.length > 0) {
            obj.children = children;
        }

        return obj;
    }

    const result = walk(document.body);
    window.__cowRefMap = refMap;
    return { tree: result, refCount: refCounter };
}
""" % (
    str(list(_KEEP_TAGS)),
    str(list(_INTERACTIVE_TAGS)),
)


_BROWSER_DEAD_HINTS = (
    "has been closed",
    "browser has disconnected",
    "target closed",
    "browser closed",
    "context or browser has been closed",
)


def _is_browser_dead_error(err: Exception) -> bool:
    """Return True if *err* indicates the browser / page died out from under us."""
    msg = str(err).lower()
    return any(h in msg for h in _BROWSER_DEAD_HINTS)


def _should_use_headless() -> bool:
    """Decide headless mode: headless on Linux servers without display, headed elsewhere."""
    if sys.platform in ("win32", "darwin"):
        return False
    # Linux: check for display
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return False
    return True


def _flatten_tree(node, indent=0) -> List[str]:
    """Convert snapshot tree to compact text lines for LLM consumption."""
    if node is None:
        return []
    if isinstance(node, str):
        return [" " * indent + node]
    if isinstance(node, list):
        lines = []
        for child in node:
            lines.extend(_flatten_tree(child, indent))
        return lines
    if not isinstance(node, dict):
        return []

    tag = node.get("tag", "?")
    ref = node.get("ref")
    parts = [tag]
    if ref:
        parts[0] = f"[{ref}] {tag}"

    # Inline attributes
    for attr in ("type", "name", "href", "alt", "role", "ariaLabel", "placeholder", "value"):
        val = node.get(attr)
        if val:
            # Truncate long values
            s = str(val)
            if len(s) > 80:
                s = s[:77] + "..."
            parts.append(f'{attr}="{s}"')

    for flag in ("disabled", "checked", "selected"):
        if node.get(flag):
            parts.append(flag)

    prefix = " " * indent
    header = prefix + " ".join(parts)

    text = node.get("text")
    if text:
        # Truncate long text
        if len(text) > 120:
            text = text[:117] + "..."
        header += f": {text}"

    lines = [header]
    children = node.get("children", [])
    for child in children:
        lines.extend(_flatten_tree(child, indent + 2))
    return lines


class BrowserService:
    """Manages a Playwright browser on a dedicated background thread.

    All Playwright operations are dispatched to a single long-lived thread via
    a task queue.  Callers from *any* worker thread can use the public API
    safely.  An idle timer automatically shuts the browser down after
    ``idle_timeout`` seconds of inactivity (default 300 = 5 min).
    """

    _IDLE_TIMEOUT_DEFAULT = 300  # seconds

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._headless: Optional[bool] = None
        self._screenshot_dir: Optional[str] = None

        # Background thread state
        self._thread: Optional[threading.Thread] = None
        self._task_queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._alive = False
        self._ready = threading.Event()

        # Playwright objects (only accessed on the background thread)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

        # Launch mode: one of "fresh" | "persistent" | "cdp".
        # - cdp: connect to an externally launched Chrome via CDP endpoint.
        # - persistent: launch with launch_persistent_context using a user_data_dir
        #   so cookies / login state survive across runs (default).
        # - fresh: classic launch + new_context, clean state every run.
        cdp_endpoint = self._config.get("cdp_endpoint") or ""
        persistent_flag = self._config.get("persistent", True)
        user_data_dir_cfg = self._config.get("user_data_dir")
        if user_data_dir_cfg is None:
            user_data_dir_cfg = _DEFAULT_USER_DATA_DIR

        self._cdp_endpoint: str = cdp_endpoint.strip() if isinstance(cdp_endpoint, str) else ""
        if self._cdp_endpoint:
            self._launch_mode = "cdp"
            self._user_data_dir: str = ""
        elif persistent_flag and user_data_dir_cfg:
            self._launch_mode = "persistent"
            self._user_data_dir = expand_path(str(user_data_dir_cfg))
        else:
            self._launch_mode = "fresh"
            self._user_data_dir = ""

        # Idle auto-release
        idle_cfg = self._config.get("idle_timeout")
        self._idle_timeout: float = float(idle_cfg) if idle_cfg is not None else self._IDLE_TIMEOUT_DEFAULT
        self._idle_timer: Optional[threading.Timer] = None

        # Set when the browser / page is detected to have died externally
        # (e.g. user manually closed the window). The next _submit() will then
        # tear down the stale thread and relaunch.
        self._needs_restart = False

    # ------------------------------------------------------------------
    # Background-thread lifecycle
    # ------------------------------------------------------------------

    def _start_thread(self):
        """Start the dedicated Playwright thread if not already running."""
        with self._lock:
            if self._alive and self._thread and self._thread.is_alive():
                return
            # Wait for old thread to fully exit before creating a new one
            old = self._thread
            if old and old.is_alive():
                old.join(timeout=5)
            # Fresh queue to avoid stale sentinels from a previous close()
            self._task_queue = queue.Queue()
            self._alive = True
            self._ready = threading.Event()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="BrowserThread")
            self._thread.start()
            # Block until browser is ready (or failed)
            self._ready.wait(timeout=30)

    def _run_loop(self):
        """Event loop running on the dedicated thread. Processes tasks until stopped."""
        logger.info("[Browser] Background thread started")
        try:
            self._launch_browser()
        except Exception as e:
            logger.error(f"[Browser] Failed to launch browser: {e}")
            self._alive = False
            self._ready.set()
            self._drain_queue(RuntimeError(f"Browser launch failed: {e}"))
            return
        self._ready.set()

        while self._alive:
            try:
                task = self._task_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if task is None:
                break
            fn, args, kwargs, result_slot = task
            try:
                result_slot["value"] = fn(*args, **kwargs)
            except Exception as e:
                result_slot["error"] = e
                if _is_browser_dead_error(e):
                    self._needs_restart = True
                    logger.warning(
                        f"[Browser] Detected closed page/context ({e}); "
                        "will relaunch on next request."
                    )
            finally:
                result_slot["event"].set()

        self._shutdown_browser()
        self._drain_queue(RuntimeError("Browser thread stopped"))
        logger.info("[Browser] Background thread exited")

    def _drain_queue(self, error: Exception):
        """Unblock all callers waiting on the queue with an error."""
        while True:
            try:
                task = self._task_queue.get_nowait()
            except queue.Empty:
                break
            if task is None:
                continue
            _, _, _, result_slot = task
            result_slot["error"] = error
            result_slot["event"].set()

    def _launch_browser(self):
        """Launch / connect Chromium on the background thread."""
        if self._headless is None:
            headless_cfg = self._config.get("headless")
            self._headless = headless_cfg if headless_cfg is not None else _should_use_headless()

        launch_args = ["--disable-dev-shm-usage"]
        if self._headless:
            launch_args.append("--no-sandbox")

        if is_cloud_deployment():
            launch_args.extend([
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-features=site-per-process,TranslateUI,IsolateOrigins",
                "--no-zygote",
                "--js-flags=--max-old-space-size=384",
                "--memory-pressure-off",
            ])

        extra_args = self._config.get("launch_args", [])
        if extra_args:
            launch_args.extend(extra_args)

        viewport_w = self._config.get("viewport_width", 1280)
        viewport_h = self._config.get("viewport_height", 720)
        viewport = {"width": viewport_w, "height": viewport_h}
        user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )

        self._playwright = sync_playwright().start()

        if self._launch_mode == "cdp":
            self._connect_cdp(viewport)
        elif self._launch_mode == "persistent":
            self._launch_persistent(launch_args, viewport, user_agent)
        else:
            self._launch_fresh(launch_args, viewport, user_agent)

        logger.info("[Browser] Browser ready")

    def _launch_fresh(self, launch_args: List[str], viewport: Dict[str, int], user_agent: str):
        """Classic launch: brand new Chromium with an empty context."""
        logger.info(f"[Browser] Launching Chromium (fresh, headless={self._headless})")
        self._browser = self._playwright.chromium.launch(
            headless=self._headless,
            args=launch_args,
        )
        self._context = self._browser.new_context(
            viewport=viewport,
            user_agent=user_agent,
        )
        self._page = self._context.new_page()
        self._wire_close_listeners()

    def _launch_persistent(self, launch_args: List[str], viewport: Dict[str, int], user_agent: str):
        """Launch Chromium with a persistent user_data_dir so login state survives."""
        os.makedirs(self._user_data_dir, exist_ok=True)
        logger.info(
            f"[Browser] Launching Chromium (persistent, headless={self._headless}, "
            f"profile={self._user_data_dir})"
        )
        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=self._user_data_dir,
                headless=self._headless,
                args=launch_args,
                viewport=viewport,
                user_agent=user_agent,
            )
        except Exception as e:
            # Profile is locked when another Chromium instance already holds it.
            msg = str(e).lower()
            if "singletonlock" in msg or "profile" in msg or "lock" in msg:
                raise RuntimeError(
                    f"Browser profile '{self._user_data_dir}' is in use by another process. "
                    "Close the other Chromium / cow instance, or set a different "
                    "tools.browser.user_data_dir."
                ) from e
            raise

        # Persistent context has no parent Browser handle; reuse the auto-created page.
        self._browser = None
        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        self._wire_close_listeners()

    def _connect_cdp(self, viewport: Dict[str, int]):
        """Attach to an existing Chrome started with --remote-debugging-port."""
        endpoint = self._cdp_endpoint
        logger.info(f"[Browser] Connecting to existing Chrome via CDP: {endpoint}")
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(endpoint)
        except Exception as e:
            msg = str(e).lower()
            if "econnrefused" in msg or "connect" in msg or "refused" in msg:
                raise RuntimeError(
                    f"Cannot reach Chrome at {endpoint}. The CDP browser is not "
                    "running. Ask the user to launch Chrome with "
                    "--remote-debugging-port and --user-data-dir, then retry. "
                    "Do not retry this tool until the user confirms."
                ) from e
            raise

        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
        else:
            self._context = self._browser.new_context(viewport=viewport)

        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        self._wire_close_listeners()

    def _wire_close_listeners(self):
        """Mark needs_restart whenever the browser / context / page dies externally."""
        def _on_dead(_obj=None):
            self._needs_restart = True

        try:
            if self._browser:
                self._browser.on("disconnected", _on_dead)
            if self._context:
                self._context.on("close", _on_dead)
            if self._page:
                self._page.on("close", _on_dead)
        except Exception as e:
            logger.debug(f"[Browser] Failed to wire close listeners: {e}")

    def _shutdown_browser(self):
        """Shut down Playwright resources on the background thread.

        Mode-specific behavior:
        - cdp: only disconnect the Playwright client; leave the user's Chrome
          and its tabs untouched (do NOT close the context).
        - persistent: close the persistent context (no separate browser handle).
        - fresh: close context, then browser.
        """
        self._cancel_idle_timer()

        if self._launch_mode == "cdp":
            # For CDP, browser.close() only detaches the Playwright client;
            # the user's Chrome process and its tabs stay alive.
            try:
                if self._browser:
                    self._browser.close()
            except Exception as e:
                logger.debug(f"[Browser] cdp disconnect error: {e}")
        else:
            for obj, label in [
                (self._context, "context"),
                (self._browser, "browser"),
            ]:
                try:
                    if obj:
                        obj.close()
                except Exception as e:
                    logger.debug(f"[Browser] {label} close error: {e}")

        try:
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.debug(f"[Browser] playwright stop error: {e}")
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        logger.info("[Browser] Browser closed")

    def _submit(self, fn: Callable, *args, **kwargs):
        """Submit *fn* to the background thread and block until it completes."""
        # If the browser died externally (e.g. user closed the window), tear
        # down the stale thread first so _start_thread() will relaunch fresh.
        if self._needs_restart:
            logger.info("[Browser] Restarting after detecting closed browser")
            self.close()
            self._needs_restart = False

        self._start_thread()

        if not self._alive:
            raise RuntimeError("Browser is not available")

        self._reset_idle_timer()

        result_slot: Dict[str, Any] = {"event": threading.Event()}
        self._task_queue.put((fn, args, kwargs, result_slot))

        # Timeout prevents permanent hang if the background thread crashes
        completed = result_slot["event"].wait(timeout=120)
        if not completed:
            raise TimeoutError("Browser operation timed out (120s)")

        if "error" in result_slot:
            raise result_slot["error"]
        return result_slot.get("value")

    # ------------------------------------------------------------------
    # Idle auto-release
    # ------------------------------------------------------------------

    def _reset_idle_timer(self):
        self._cancel_idle_timer()
        if self._idle_timeout > 0:
            self._idle_timer = threading.Timer(self._idle_timeout, self._on_idle_timeout)
            self._idle_timer.daemon = True
            self._idle_timer.start()

    def _cancel_idle_timer(self):
        if self._idle_timer:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _on_idle_timeout(self):
        logger.info(f"[Browser] Idle for {self._idle_timeout}s, auto-releasing browser")
        self.close()

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def close(self):
        """Shut down browser and background thread (safe from any thread)."""
        self._cancel_idle_timer()
        with self._lock:
            if not self._alive:
                self._needs_restart = False
                return
            self._alive = False
            t = self._thread
        if self._task_queue is not None:
            self._task_queue.put(None)
        if t is not None and t.is_alive():
            t.join(timeout=10)
        with self._lock:
            self._thread = None
            self._needs_restart = False

    # ------------------------------------------------------------------
    # Actions  (each method is dispatched to the background thread)
    # ------------------------------------------------------------------

    def navigate(self, url: str, timeout: int = 30000) -> Dict[str, Any]:
        return self._submit(self._do_navigate, url, timeout)

    def _do_navigate(self, url: str, timeout: int) -> Dict[str, Any]:
        page = self._page
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            status = resp.status if resp else None
        except Exception as e:
            return {"error": f"Navigation failed: {e}"}

        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(500)

        try:
            title = page.title()
        except Exception:
            title = ""
        try:
            current_url = page.url
        except Exception:
            current_url = url

        return {"url": current_url, "title": title, "status": status}

    def snapshot(self, selector: Optional[str] = None) -> str:
        return self._submit(self._do_snapshot, selector)

    def _do_snapshot(self, selector: Optional[str] = None) -> str:
        page = self._page
        try:
            result = page.evaluate(_SNAPSHOT_JS)
        except Exception as e:
            return f"[Snapshot error: {e}]"

        tree = result.get("tree")
        ref_count = result.get("refCount", 0)
        lines = _flatten_tree(tree)

        try:
            title = page.title()
        except Exception:
            title = ""
        try:
            url = page.url
        except Exception:
            url = ""

        header = f"Page: {title}  ({url})\nInteractive elements: {ref_count}\n---"
        body = "\n".join(lines)

        max_chars = self._config.get("snapshot_max_chars", 30000)
        if len(body) > max_chars:
            body = body[:max_chars] + "\n... [snapshot truncated]"

        return f"{header}\n{body}"

    def screenshot(self, full_page: bool = False, cwd: str = "") -> str:
        return self._submit(self._do_screenshot, full_page, cwd)

    def _do_screenshot(self, full_page: bool = False, cwd: str = "") -> str:
        page = self._page
        save_dir = self._get_screenshot_dir(cwd)
        filename = f"screenshot_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.join(save_dir, filename)
        page.screenshot(path=filepath, full_page=full_page)
        logger.info(f"[Browser] Screenshot saved: {filepath}")
        return filepath

    def click(self, ref: Optional[int] = None, selector: Optional[str] = None,
              timeout: int = 5000) -> Dict[str, Any]:
        return self._submit(self._do_click, ref, selector, timeout)

    def _do_click(self, ref, selector, timeout) -> Dict[str, Any]:
        page = self._page
        try:
            if ref is not None:
                result = page.evaluate(f"""
                    () => {{
                        const el = window.__cowRefMap && window.__cowRefMap[{ref}];
                        if (!el) return {{ error: "ref {ref} not found. Run snapshot first." }};
                        el.click();
                        return {{ clicked: true, tag: el.tagName.toLowerCase() }};
                    }}
                """)
                if result.get("error"):
                    return result
                page.wait_for_timeout(500)
                return result
            elif selector:
                page.click(selector, timeout=timeout)
                return {"clicked": True, "selector": selector}
            else:
                return {"error": "Provide either ref (from snapshot) or selector"}
        except Exception as e:
            return {"error": f"Click failed: {e}"}

    def fill(self, text: str, ref: Optional[int] = None,
             selector: Optional[str] = None, timeout: int = 5000) -> Dict[str, Any]:
        return self._submit(self._do_fill, text, ref, selector, timeout)

    def _do_fill(self, text, ref, selector, timeout) -> Dict[str, Any]:
        page = self._page
        try:
            if ref is not None:
                result = page.evaluate(f"""
                    () => {{
                        const el = window.__cowRefMap && window.__cowRefMap[{ref}];
                        if (!el) return {{ error: "ref {ref} not found. Run snapshot first." }};
                        el.focus();
                        el.value = "";
                        return {{ tag: el.tagName.toLowerCase(), name: el.name || "" }};
                    }}
                """)
                if result.get("error"):
                    return result
                page.keyboard.type(text)
                return {"filled": True, "ref": ref, "text": text}
            elif selector:
                page.fill(selector, text, timeout=timeout)
                return {"filled": True, "selector": selector, "text": text}
            else:
                return {"error": "Provide either ref (from snapshot) or selector"}
        except Exception as e:
            return {"error": f"Fill failed: {e}"}

    def select(self, value: str, ref: Optional[int] = None,
               selector: Optional[str] = None, timeout: int = 5000) -> Dict[str, Any]:
        return self._submit(self._do_select, value, ref, selector, timeout)

    def _do_select(self, value, ref, selector, timeout) -> Dict[str, Any]:
        page = self._page
        try:
            if ref is not None:
                result = page.evaluate(f"""
                    () => {{
                        const el = window.__cowRefMap && window.__cowRefMap[{ref}];
                        if (!el || el.tagName.toLowerCase() !== "select")
                            return {{ error: "ref {ref} is not a <select> element" }};
                        el.value = {repr(value)};
                        el.dispatchEvent(new Event("change", {{ bubbles: true }}));
                        return {{ selected: true, value: el.value }};
                    }}
                """)
                return result
            elif selector:
                page.select_option(selector, value, timeout=timeout)
                return {"selected": True, "selector": selector, "value": value}
            else:
                return {"error": "Provide either ref (from snapshot) or selector"}
        except Exception as e:
            return {"error": f"Select failed: {e}"}

    def scroll(self, direction: str = "down", amount: int = 500) -> Dict[str, Any]:
        return self._submit(self._do_scroll, direction, amount)

    def _do_scroll(self, direction, amount) -> Dict[str, Any]:
        page = self._page
        delta_map = {
            "down": (0, amount),
            "up": (0, -amount),
            "right": (amount, 0),
            "left": (-amount, 0),
        }
        dx, dy = delta_map.get(direction, (0, amount))
        try:
            page.mouse.wheel(dx, dy)
            page.wait_for_timeout(300)
            scroll_info = page.evaluate("""
                () => ({
                    scrollX: window.scrollX,
                    scrollY: window.scrollY,
                    scrollHeight: document.documentElement.scrollHeight,
                    clientHeight: document.documentElement.clientHeight
                })
            """)
            return {"scrolled": direction, "amount": amount, **scroll_info}
        except Exception as e:
            return {"error": f"Scroll failed: {e}"}

    def wait(self, selector: Optional[str] = None, timeout: int = 5000,
             state: str = "visible") -> Dict[str, Any]:
        return self._submit(self._do_wait, selector, timeout, state)

    def _do_wait(self, selector, timeout, state) -> Dict[str, Any]:
        page = self._page
        try:
            if selector:
                page.wait_for_selector(selector, timeout=timeout, state=state)
                return {"waited": True, "selector": selector, "state": state}
            else:
                page.wait_for_timeout(timeout)
                return {"waited": True, "timeout_ms": timeout}
        except Exception as e:
            return {"error": f"Wait failed: {e}"}

    def go_back(self) -> Dict[str, Any]:
        return self._submit(self._do_go_back)

    def _do_go_back(self) -> Dict[str, Any]:
        page = self._page
        try:
            page.go_back(wait_until="domcontentloaded", timeout=10000)
            try:
                title = page.title()
            except Exception:
                title = ""
            try:
                url = page.url
            except Exception:
                url = ""
            return {"url": url, "title": title}
        except Exception as e:
            return {"error": f"Go back failed: {e}"}

    def go_forward(self) -> Dict[str, Any]:
        return self._submit(self._do_go_forward)

    def _do_go_forward(self) -> Dict[str, Any]:
        page = self._page
        try:
            page.go_forward(wait_until="domcontentloaded", timeout=10000)
            try:
                title = page.title()
            except Exception:
                title = ""
            try:
                url = page.url
            except Exception:
                url = ""
            return {"url": url, "title": title}
        except Exception as e:
            return {"error": f"Go forward failed: {e}"}

    def get_text(self, selector: str) -> Dict[str, Any]:
        return self._submit(self._do_get_text, selector)

    def _do_get_text(self, selector) -> Dict[str, Any]:
        page = self._page
        try:
            text = page.text_content(selector, timeout=5000)
            return {"text": text or ""}
        except Exception as e:
            return {"error": f"Get text failed: {e}"}

    def evaluate(self, script: str) -> Dict[str, Any]:
        return self._submit(self._do_evaluate, script)

    def _do_evaluate(self, script) -> Dict[str, Any]:
        page = self._page
        try:
            result = page.evaluate(script)
            return {"result": result}
        except Exception as e:
            return {"error": f"Evaluate failed: {e}"}

    def press(self, key: str) -> Dict[str, Any]:
        return self._submit(self._do_press, key)

    def _do_press(self, key) -> Dict[str, Any]:
        page = self._page
        try:
            page.keyboard.press(key)
            page.wait_for_timeout(300)
            return {"pressed": key}
        except Exception as e:
            return {"error": f"Press failed: {e}"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_screenshot_dir(self, cwd: str = "") -> str:
        if self._screenshot_dir and os.path.isdir(self._screenshot_dir):
            return self._screenshot_dir
        base = cwd or os.getcwd()
        d = os.path.join(base, "tmp")
        os.makedirs(d, exist_ok=True)
        self._screenshot_dir = d
        return d
