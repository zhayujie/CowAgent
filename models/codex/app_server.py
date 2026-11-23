"""Stdio transport and managed ChatGPT authentication for the Codex provider."""

from collections import deque
import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
from threading import Thread
import time

from common.atomic_write import write_json_atomic
from common.log import logger
from models.codex.install import find_codex

# Pass network and OS settings needed by the CLI. CowAgent's API keys and
# Codex auth/backend overrides are deliberately left in the parent process.
_ENV_KEYS = {
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TMP", "TEMP", "TMPDIR",
    "LANG", "LC_ALL", "LC_CTYPE", "TERM", "HTTP_PROXY", "HTTPS_PROXY",
    "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR",
}
_AUTH_OPTIONS = ('-c', 'cli_auth_credentials_store="file"')
_MODELS_CACHE = "cowagent-models.json"
_ACCOUNT_CACHE = "cowagent-account.json"
TOOL_NAMESPACE = "cowagent"
LOGIN_REQUIRED = "Sign in with ChatGPT in the Models console or run 'cow codex login'."


class CodexError(RuntimeError):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


def codex_home():
    from config import get_device_dir

    return Path(get_device_dir(create=False)) / "codex"


def _launch_settings():
    home = codex_home()
    executable = find_codex(home)
    if not executable:
        raise CodexError("Codex CLI is not installed. Sign in from the Models console or run 'cow codex install'.", 503)
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if key.upper() in _ENV_KEYS}
    env["CODEX_HOME"] = str(home.resolve())
    return executable, home, env


def run_auth_command(*args):
    executable, home, env = _launch_settings()
    result = subprocess.run([executable, *_AUTH_OPTIONS, *args], cwd=home, env=env)
    if result.returncode == 0:
        clear_model_cache()
    return result.returncode


def clear_model_cache():
    for name in (_MODELS_CACHE, _ACCOUNT_CACHE, "cowagent-reasoning.json"):
        try:
            (codex_home() / name).unlink()
        except FileNotFoundError:
            pass


def cached_account():
    """The signed-in ChatGPT account as of the last sync: email and plan."""
    home = codex_home()
    if not (home / "auth.json").is_file():
        return {}
    try:
        account = json.loads((home / _ACCOUNT_CACHE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(account, dict):
        return {}
    return {key: account[key] for key in ("email", "plan") if isinstance(account.get(key), str)}


def cached_models():
    home = codex_home()
    if not (home / "auth.json").is_file():
        return []
    try:
        models = json.loads((home / _MODELS_CACHE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [model for model in models if isinstance(model, str) and model] if isinstance(models, list) else []


def cached_reasoning_capability(model):
    """Read optional model capabilities captured during the last CLI sync."""
    try:
        data = json.loads((codex_home() / "cowagent-reasoning.json").read_text(encoding="utf-8"))
        entry = data.get(model, {})
        values = entry.get("values", [])
        allowed = {"low", "medium", "high", "xhigh", "max", "ultra"}
        values = [v for v in values if v in allowed]
        if not values:
            return None
        default = entry.get("default")
        return {"supported": True, "param": "reasoning_effort", "default": default if default in values else values[0],
                "options": [{"value": v, "label": v} for v in values], "thinking_only": True}
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def refresh_models():
    """Refresh the public model slugs used by CowAgent's pickers."""
    with AppServer() as server:
        account = server.require_chatgpt()
        models = []
        reasoning = {}
        cursor = None
        while True:
            page = server.request("model/list", {"cursor": cursor, "limit": 50, "modelProvider": "openai"})
            models.extend(entry["model"] for entry in page["data"] if not entry.get("hidden"))
            for entry in page["data"]:
                if not entry.get("hidden") and entry.get("model"):
                    reasoning[entry["model"].lower()] = {
                        "values": [v.get("reasoningEffort") for v in entry.get("supportedReasoningEfforts", []) if isinstance(v, dict)],
                        "default": entry.get("defaultReasoningEffort"),
                    }
            cursor = page.get("nextCursor")
            if not cursor:
                break
    models = list(dict.fromkeys(models))
    write_json_atomic(codex_home() / _MODELS_CACHE, models)
    write_json_atomic(codex_home() / "cowagent-reasoning.json", reasoning)
    write_json_atomic(codex_home() / _ACCOUNT_CACHE, {
        "email": account.get("email") or "", "plan": account.get("planType") or "",
    })
    return models


class AppServer:
    """One isolated child for a model call or a short account operation.

    ``timeout`` bounds the whole session, or with ``idle=True`` the silence
    between two messages, so a long streamed answer is not cut off.
    """

    def __init__(self, timeout=120, idle=False):
        self.timeout = timeout
        self.idle = idle
        self._next_id = 0
        self._messages = Queue()
        self._turn_events = deque()
        self._stderr = deque(maxlen=20)

    def __enter__(self):
        executable, home, env = _launch_settings()
        self._process = subprocess.Popen(
            [executable, *_AUTH_OPTIONS, "app-server", "--listen", "stdio://",
             "--disable", "shell_tool", "--disable", "apps", "--disable", "plugins",
             "--disable", "hooks", "--disable", "image_generation",
             "--disable", "browser_use", "--disable", "computer_use",
             "--disable", "multi_agent", "--disable", "multi_agent_v2",
             "-c", 'web_search="disabled"',
             # Keep CowAgent functions visible even for Code Mode models.
             "-c", f'features.code_mode.direct_only_tool_namespaces=["{TOOL_NAMESPACE}"]'],
            cwd=home, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
        )
        self._deadline = time.monotonic() + self.timeout
        self._reader = Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        self._stderr_reader = Thread(target=self._read_stderr, daemon=True)
        self._stderr_reader.start()
        try:
            self.request("initialize", {
                "clientInfo": {"name": "cowagent", "title": "CowAgent", "version": "1.0.0"},
                "capabilities": {"experimentalApi": True},
            })
            self._send({"method": "initialized"})
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_exc):
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        self._reader.join(timeout=2)
        self._process.stdin.close()

    def _read_stdout(self):
        try:
            for line in self._process.stdout:
                self._messages.put(json.loads(line))
        except (OSError, ValueError):
            pass
        finally:
            self._process.stdout.close()
            self._messages.put(None)

    def _read_stderr(self):
        try:
            for line in self._process.stderr:
                if line.strip():
                    self._stderr.append(line.rstrip())
        except (OSError, ValueError):
            pass

    def _exit_error(self):
        # stdout closing first does not mean the last stderr lines are in.
        self._stderr_reader.join(timeout=1)
        detail = self._stderr[-1] if self._stderr else ""
        if self._stderr:
            logger.warning("[Codex] App Server stderr:\n" + "\n".join(self._stderr))
        message = "Codex App Server exited or returned an invalid message."
        return CodexError(f"{message} {detail}".strip())

    def _send(self, message):
        try:
            self._process.stdin.write(json.dumps(message) + "\n")
            self._process.stdin.flush()
        except OSError as exc:
            raise CodexError("Codex App Server closed its input.") from exc

    def receive(self, *, wait=None):
        if self._turn_events:
            return self._turn_events.popleft()
        return self._receive(wait=wait)

    def _receive(self, *, wait=None):
        try:
            remaining = max(0, self._deadline - time.monotonic())
            message = self._messages.get(timeout=remaining if wait is None else min(wait, remaining))
        except Empty as exc:
            if wait is not None and time.monotonic() < self._deadline:
                return None
            raise CodexError("Codex App Server timed out.", 504) from exc
        if not isinstance(message, dict):
            raise self._exit_error()
        if self.idle:
            self._deadline = time.monotonic() + self.timeout
        return message

    def reject(self, message):
        self._send({
            "id": message["id"],
            "error": {"code": -32601, "message": "This request is not supported by the CowAgent provider."},
        })

    def request(self, method, params, *, preserve_events=False):
        request_id = self._next_id
        self._next_id += 1
        self._send({"id": request_id, "method": method, "params": params})
        while True:
            message = self._receive()
            if "method" in message:
                if preserve_events:
                    self._turn_events.append(message)
                elif "id" in message:
                    self.reject(message)
                continue
            if message.get("id") == request_id:
                if "error" in message:
                    raise CodexError(f"Codex {method}: {message['error'].get('message', 'request failed')}")
                return message["result"]

    def require_chatgpt(self):
        account = self.request("account/read", {"refreshToken": False}).get("account")
        if not account or account.get("type") != "chatgpt":
            raise CodexError(LOGIN_REQUIRED, 401)
        return account
