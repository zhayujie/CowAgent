"""Run Codex setup and device authorization outside HTTP request threads."""

from threading import Event, Lock, Thread
from urllib.parse import urlsplit

from models.codex.app_server import AppServer, CodexError, cached_models, clear_model_cache, codex_home, refresh_models
from models.codex.install import InstallError, find_codex, install_codex


class CodexSetup:
    def __init__(self):
        self._lock = Lock()
        self._cancel = Event()
        self._state = {"phase": "idle"}

    def dispatch(self, action):
        with self._lock:
            phase = self._state["phase"]
            if action == "cancel" and phase == "waiting":
                self._cancel.set()
                self._state = {"phase": "canceling"}
            elif action in ("login", "refresh", "logout") and phase in ("idle", "error"):
                self._cancel.clear()
                self._state = {"phase": "starting"}
                Thread(target=self._run, args=(action,), daemon=True).start()
            return self._snapshot()

    def _snapshot(self):
        home = codex_home()
        models = cached_models()
        return {
            **self._state, "installed": bool(find_codex(home)),
            "signed_in": (home / "auth.json").is_file(),
            "models_ready": bool(models), "models": models,
        }

    def _update(self, phase, **fields):
        with self._lock:
            self._state = {"phase": phase, **fields}

    def _run(self, action):
        try:
            if action == "login":
                if not find_codex(codex_home()):
                    self._update("installing")
                    install_codex(codex_home())
                self._update("starting")
                if self._login():
                    self._update("refreshing")
                    refresh_models()
            elif action == "refresh":
                self._update("refreshing")
                refresh_models()
            elif action == "logout":
                self._update("signing_out")
                with AppServer() as server:
                    server.request("account/logout", None)
                clear_model_cache()
        except (CodexError, InstallError, OSError) as exc:
            self._update("error", message=str(exc))
        except Exception:
            self._update("error", message="Codex returned an unexpected response. Check the CLI version and retry.")
        else:
            self._update("idle")

    def _login(self):
        with AppServer(timeout=15 * 60) as server:
            result = server.request(
                "account/login/start", {"type": "chatgptDeviceCode"}, preserve_events=True,
            )
            login_id = result["loginId"]
            url = result["verificationUrl"]
            destination = urlsplit(url)
            if destination.scheme != "https" or destination.netloc != "auth.openai.com":
                raise CodexError("Codex returned an unexpected authorization URL.")
            self._update("waiting", verification_url=url, user_code=result["userCode"])
            while not self._cancel.is_set():
                notification = server.receive(wait=0.5)
                if not notification:
                    continue
                if "id" in notification:
                    server.reject(notification)
                    continue
                if notification.get("method") != "account/login/completed":
                    continue
                params = notification.get("params") or {}
                if params.get("loginId") != login_id:
                    continue
                if not params.get("success"):
                    raise CodexError(params.get("error") or "ChatGPT authorization failed.")
                clear_model_cache()
                return True
            server.request("account/login/cancel", {"loginId": login_id})
            return False


codex_setup = CodexSetup()
