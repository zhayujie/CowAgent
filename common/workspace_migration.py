"""Moving the Agent workspace from the web console.

The console runs inside the process that holds the workspace open (the
conversation database, the memory index, the scheduler), so it can't move the
workspace in place. It records the move in a pending file next to config.json
instead, and ``apply_pending`` carries it out on the next start, before
anything opens the workspace. The outcome is kept in a result file the console
shows afterwards.

The move only switches over once every file is verified at the destination,
and the new place is recorded as ``agent_workspace`` in config.json. A failure
leaves the old workspace exactly as it was. Afterwards the old place is removed
and, if asked, a link to the new one left there.

Only the workspace moves. config.json, the credentials and the code stay where
they are, and the workspace may neither sit inside nor contain them: the
Agent's file tools reach everything in it.

The desktop client moves its workspace from its own shell
(desktop/src/main/workspace-migration.ts); nothing here runs there.
"""

import json
import os
import re
import shutil
import stat
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from common.atomic_write import write_json_atomic
from common.log import logger
from common.utils import expand_path

WORKSPACE_DIRNAME = "cow"
PENDING_FILE = "workspace-migration.json"
RESULT_FILE = "workspace-migration-result.json"

# Files the OS drops into any folder; they don't make a folder "used".
_NOISE_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}
# Present while a copy is under way. A target still holding it is what a killed
# copy left behind, which a new move may clear, unlike a real workspace.
_INCOMPLETE_MARKER = ".cow-migration-incomplete"
_PROGRESS_INTERVAL = 5.0
_IS_WIN = sys.platform == "win32"
_LINK_TAGS = {
    getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C),
    getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003),
}


class MigrationError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------- locations


def _data_root() -> str:
    from config import get_data_root

    return get_data_root()


def pending_path() -> str:
    return os.path.join(_data_root(), PENDING_FILE)


def result_path() -> str:
    return os.path.join(_data_root(), RESULT_FILE)


def _config_path() -> str:
    return os.path.join(_data_root(), "config.json")


def current_workspace() -> str:
    from agent import team
    from config import conf

    return os.path.abspath(str(team.instance_root(conf())))


def links_supported() -> bool:
    """Before Python 3.8, Windows junctions pass for plain folders (and realpath
    doesn't resolve them), so a cleanup could follow one out of the workspace."""
    return not _IS_WIN or sys.version_info >= (3, 8)


def managed_by_env() -> bool:
    """AGENT_WORKSPACE in the environment overrides config.json on every start."""
    return any(k.lower() == "agent_workspace" and v.strip() for k, v in os.environ.items())


def protected_dirs() -> List[str]:
    """Config, credentials and code: never inside the workspace, nor around it."""
    from config import get_root

    dirs = []
    for d in (_data_root(), get_root(), expand_path("~/.cow")):
        d = os.path.abspath(d)
        if not any(_same_path(d, seen) for seen in dirs):
            dirs.append(d)
    return dirs


def target_for(parent: str) -> str:
    """The workspace folder created inside a folder the user picked."""
    root = expand_path(parent.strip())
    # "D:" alone means the current directory of drive D, not its root.
    if re.fullmatch(r"[A-Za-z]:", root):
        root += os.sep
    return os.path.join(os.path.abspath(root), WORKSPACE_DIRNAME)


# --------------------------------------------------------------- filesystem


def _norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(p))


def _same_path(a: str, b: str) -> bool:
    return _norm(a) == _norm(b)


def _is_within(child: str, parent: str) -> bool:
    """True when ``child`` is ``parent`` itself or lies inside it."""
    c, p = _norm(child), _norm(parent)
    if c == p:
        return True
    try:
        rel = os.path.relpath(c, p)
    except ValueError:  # different drives
        return False
    return not rel.startswith("..") and not os.path.isabs(rel)


def _is_link(p: str) -> bool:
    """A symlink, or on Windows a junction (which os.path.islink misses before 3.12)."""
    try:
        st = os.lstat(p)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return _IS_WIN and getattr(st, "st_reparse_tag", 0) in _LINK_TAGS


def _realpath(p: str) -> str:
    try:
        return os.path.realpath(p)
    except OSError:
        return os.path.abspath(p)


def _links_to(p: str, target: str) -> bool:
    """A link at ``p`` that resolves to ``target``, i.e. one a move left behind."""
    return _is_link(p) and _same_path(_realpath(p), _realpath(target))


def _has_data(d: str) -> bool:
    if not os.path.lexists(d):
        return False
    if not os.path.isdir(d):
        return True
    try:
        return any(name not in _NOISE_FILES for name in os.listdir(d))
    except OSError:
        return False


def _is_stale_copy(d: str) -> bool:
    return os.path.isfile(os.path.join(d, _INCOMPLETE_MARKER))


def _same_device(a: str, b: str) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def _scan(root: str) -> Tuple[int, int]:
    """(files, bytes) under ``root``; a link counts as one file of no size."""
    files = size = 0
    stack = [root]
    while stack:
        p = stack.pop()
        if _is_link(p):
            files += 1
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        if stat.S_ISDIR(st.st_mode):
            try:
                stack.extend(os.path.join(p, name) for name in os.listdir(p))
            except OSError:
                pass
            continue
        files += 1
        size += st.st_size
    return files, size


def real_workspace() -> str:
    """Where the workspace's files actually are. A move made from the other
    client (desktop or console) leaves the path this one uses as a link to the
    new place."""
    current = current_workspace()
    return _realpath(current) if _is_link(current) and os.path.isdir(current) else current


def workspace_size() -> int:
    return _scan(real_workspace())[1]


def _make_link(target: str, link: str) -> None:
    if _IS_WIN:
        # Unlike a directory symlink, a junction needs no privilege.
        import _winapi

        _winapi.CreateJunction(target, link)
    else:
        os.symlink(target, link, target_is_directory=True)


def _remove_link(p: str) -> None:
    """Remove the link itself, never what it points to."""
    try:
        os.unlink(p)
    except FileNotFoundError:
        return
    except OSError:
        os.rmdir(p)  # a junction or a Windows directory symlink


# What the move is doing right now, for the progress page served while it runs.
_state: Dict = {}


def progress() -> Dict:
    return dict(_state)


def _set_phase(phase: str, **counts) -> None:
    _state.update(phase=phase, **counts)


class _Progress:
    def __init__(self, total_files: int, total_bytes: int):
        self.total_files, self.total_bytes = total_files, total_bytes
        self.files = self.bytes = 0
        self._last = time.monotonic()
        _set_phase("copying", done_files=0, total_files=total_files, done_bytes=0, total_bytes=total_bytes)

    def add(self, size: int) -> None:
        self.files += 1
        self.bytes += size
        _state.update(done_files=self.files, done_bytes=self.bytes)
        now = time.monotonic()
        if now - self._last >= _PROGRESS_INTERVAL:
            self._last = now
            pct = self.bytes * 100 // self.total_bytes if self.total_bytes else 100
            logger.info(f"[Workspace] copied {self.files}/{self.total_files} files ({pct}%), do not stop the service")


def _copy_tree(src: str, dst: str, progress: Optional[_Progress] = None) -> None:
    if _is_link(src):
        if progress:
            progress.add(0)
        is_dir = os.path.isdir(src)
        if _IS_WIN and is_dir:
            _make_link(_realpath(src), dst)
            return
        try:
            os.symlink(os.readlink(src), dst, target_is_directory=is_dir)
        except OSError:
            # File symlinks need a privilege on Windows; keep the content instead.
            if is_dir:
                raise
            shutil.copy2(src, dst)
        return
    if os.path.isdir(src):
        os.makedirs(dst, exist_ok=True)
        for name in os.listdir(src):
            _copy_tree(os.path.join(src, name), os.path.join(dst, name), progress)
        return
    if os.path.lexists(dst):
        raise FileExistsError(dst)
    shutil.copy2(src, dst)
    if progress:
        progress.add(os.path.getsize(dst))


def _remove_tree(root: str) -> None:
    """Delete ``root`` without following any link inside it: how shutil.rmtree
    treats a junction differs between Python versions."""
    if _is_link(root):
        _remove_link(root)
        return
    if os.path.isdir(root):
        for name in os.listdir(root):
            _remove_tree(os.path.join(root, name))
        os.rmdir(root)
        return
    try:
        os.unlink(root)
    except FileNotFoundError:
        pass
    except PermissionError:
        # Read-only files (git objects in a skill, for one) block deletion on Windows.
        os.chmod(root, stat.S_IWRITE)
        os.unlink(root)


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------- checks


def check_target(parent: str, current: Optional[str] = None) -> Dict:
    """Whether the workspace can move into ``parent``/cow."""
    result = {"ok": False, "target": "", "required_bytes": 0, "free_bytes": None}

    def fail(code: str, detail: str = "") -> Dict:
        result.update(code=code, detail=detail)
        return result

    if managed_by_env():
        return fail("managed_by_env")
    raw = expand_path((parent or "").strip())
    if not raw or not os.path.isabs(raw):
        return fail("not_absolute")
    target = target_for(raw)
    result["target"] = target
    current = current or current_workspace()
    if _same_path(target, current) or _same_path(target, _realpath(current)):
        return fail("same_location")

    for d in protected_dirs():
        for candidate in {d, _realpath(d)}:
            if _is_within(target, candidate) or _is_within(candidate, target):
                return fail("protected_dir", d)

    source = _realpath(current) if os.path.lexists(current) else None
    # A link a previous move left at the target that points back here is
    # replaced, not nested.
    link_back = bool(source) and _links_to(target, source)
    if source and not link_back:
        for s in {current, source}:
            if _is_within(target, s) or _is_within(s, target):
                return fail("nested", s)

    if _has_data(target) and not link_back and not _is_stale_copy(target):
        return fail("target_has_data")

    root = os.path.dirname(target)
    try:
        os.makedirs(root, exist_ok=True)
        probe = os.path.join(root, f".cow-write-test-{uuid.uuid4().hex}")
        with open(probe, "w"):
            pass
        os.remove(probe)
    except OSError as e:
        return fail("not_writable", str(e))

    if source:
        # A rename on the same drive needs no room; anything else is a full copy.
        if not (_same_path(source, current) and _same_device(source, root)):
            result["required_bytes"] = _scan(source)[1]
        try:
            result["free_bytes"] = shutil.disk_usage(root).free
        except OSError:
            pass
        if result["free_bytes"] is not None and result["required_bytes"] > result["free_bytes"]:
            return fail("insufficient_space")

    result["ok"] = True
    return result


# ----------------------------------------------------------------- schedule


def read_pending() -> Optional[dict]:
    return _read_json(pending_path())


def read_result() -> Optional[dict]:
    return _read_json(result_path())


def dismiss_result() -> None:
    try:
        os.remove(result_path())
    except FileNotFoundError:
        pass


def cancel() -> None:
    try:
        os.remove(pending_path())
    except FileNotFoundError:
        pass


def schedule(parent: str, keep_link: bool) -> Dict:
    """Record a move for the next start, once the target passes the checks."""
    current = current_workspace()
    check = check_target(parent, current)
    if not check["ok"]:
        return check
    pending = {
        "from": current,
        "to": check["target"],
        "keep_link": bool(keep_link),
        "requested_at": _now(),
    }
    write_json_atomic(pending_path(), pending, indent=2)
    dismiss_result()
    logger.info(f"[Workspace] move scheduled for the next start: {current} -> {check['target']}")
    return {**check, "pending": pending}


# -------------------------------------------------------------------- apply


Rewrites = List[Tuple[str, Optional[str]]]


def _rewrite_json(path: str, data: dict, original: Optional[str], rewrites: Rewrites) -> None:
    write_json_atomic(path, data, indent=4)
    rewrites.append((path, original))


def _undo(rewrites: Rewrites) -> None:
    for path, original in reversed(rewrites):
        try:
            if original is None:
                os.remove(path)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(original)
        except OSError:
            logger.error(f"[Workspace] could not restore {path}")


def _rebase_team(old: str, new: str, rewrites: Rewrites) -> None:
    """Member workspaces that lived under the old workspace move with it."""
    path = os.path.join(new, "agents", "team.json")
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8-sig") as f:
        original = f.read()
    data = json.loads(original)
    agents = data.get("agents") if isinstance(data, dict) else None
    if not isinstance(agents, list):
        return
    changed = False
    for agent in agents:
        value = agent.get("workspace") if isinstance(agent, dict) else None
        if not isinstance(value, str) or not value.strip():
            continue
        absolute = os.path.abspath(expand_path(value.strip()))
        if _is_within(absolute, old):
            agent["workspace"] = os.path.join(new, os.path.relpath(absolute, old))
            changed = True
    if changed:
        _rewrite_json(path, data, original, rewrites)


def _pin_workspace(workspace: str, rewrites: Rewrites) -> None:
    """Record ``workspace`` as agent_workspace in config.json."""
    from config import read_config_template

    path = _config_path()
    original = None
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            original = f.read()
        data = json.loads(original)
    else:
        # Seeded like a console save would be, so no template default goes missing.
        data = read_config_template()
    data["agent_workspace"] = workspace
    _rewrite_json(path, data, original, rewrites)


def _use_workspace(workspace: str) -> None:
    """Point the already loaded config at ``workspace``."""
    from agent.registry import set_agent_registry
    from config import conf

    conf()["agent_workspace"] = workspace
    set_agent_registry(None)


def _migrate(pending: dict) -> List[str]:
    old = os.path.abspath(str(pending.get("from") or ""))
    new = os.path.abspath(str(pending.get("to") or ""))
    keep_link = bool(pending.get("keep_link", True))

    if not links_supported():
        raise MigrationError("python_too_old", sys.version.split()[0])
    current = current_workspace()
    if not _same_path(current, old):
        raise MigrationError("workspace_changed", current)
    check = check_target(os.path.dirname(new), current)
    if not check["ok"]:
        raise MigrationError(check["code"], check.get("detail", ""))

    rewrites: Rewrites = []
    exists = os.path.lexists(old)
    real_old = _realpath(old) if exists else old
    # A link an earlier move left at ~/cow dangles once the workspace moves on,
    # so it is re-pointed (or dropped) afterwards.
    home = os.path.abspath(expand_path("~/cow"))
    home_link = home if exists and not _same_path(home, old) and _links_to(home, real_old) else None

    os.makedirs(os.path.dirname(new), exist_ok=True)
    # Only a link back here, OS noise files or a killed copy can be in the way:
    # check_target refuses a target that holds anything else.
    if _is_link(new):
        _remove_link(new)
    elif os.path.lexists(new):
        _remove_tree(new)

    method = None
    partial = False
    try:
        if exists:
            _set_phase("scanning")
            expected = _scan(real_old)
            logger.info(f"[Workspace] moving {expected[0]} files ({expected[1]} bytes): {old} -> {new}, "
                        f"do not stop the service until it finishes")
            if _same_path(real_old, old) and _same_device(old, os.path.dirname(new)):
                try:
                    os.rename(old, new)
                    method = "rename"
                except OSError as e:
                    logger.info(f"[Workspace] rename failed ({e}), copying instead")
            if method is None:
                partial = True
                marker = os.path.join(new, _INCOMPLETE_MARKER)
                try:
                    os.makedirs(new, exist_ok=True)
                    with open(marker, "w"):
                        pass
                    _copy_tree(real_old, new, _Progress(*expected))
                    os.remove(marker)
                except OSError as e:
                    raise MigrationError("copy_failed", str(e))
                _set_phase("verifying")
                copied = _scan(new)
                if copied != expected:
                    raise MigrationError(
                        "verify_failed",
                        f"{expected[0]} files / {expected[1]} bytes, copied {copied[0]} / {copied[1]}",
                    )
                method = "copy"
                partial = False
        try:
            if method:
                _rebase_team(old, new, rewrites)
            _pin_workspace(new, rewrites)
        except Exception as e:
            raise MigrationError("finalize_failed", str(e))
    # BaseException too: Ctrl+C in the middle of a long copy must not leave a
    # half-filled target behind.
    except BaseException:
        _undo(rewrites)
        try:
            if method == "rename":
                os.rename(new, old)
            elif method == "copy" or partial:
                _remove_tree(new)
        except OSError as e:
            logger.error(f"[Workspace] rollback left {new} behind: {e}")
        raise

    # The new workspace is live from here on; what follows only tidies up.
    _use_workspace(new)
    warnings: List[str] = []
    _set_phase("cleaning")
    if method == "copy":
        try:
            _remove_tree(real_old)
            if not _same_path(real_old, old):
                _remove_link(old)
        except OSError as e:
            logger.warning(f"[Workspace] could not remove the old workspace {real_old}: {e}")
            warnings.append(f"cleanup:{real_old}")
            return warnings
    if method:
        links = ([old] if keep_link else []) + ([home_link] if home_link else [])
        for path in links:
            try:
                if _is_link(path):
                    _remove_link(path)
                if keep_link and not os.path.lexists(path):
                    _make_link(new, path)
            except OSError as e:
                logger.warning(f"[Workspace] could not link {path} -> {new}: {e}")
                warnings.append(f"link:{path}")
    return warnings


def apply_pending() -> Optional[Dict]:
    """Carry out a move the console scheduled. Call after load_config, before
    anything opens the workspace. Returns the outcome, or None if none was due."""
    path = pending_path()
    if not os.path.exists(path):
        return None
    pending = _read_json(path) or {}
    # Dropped first: a move that fails (or crashes) must not run again on every start.
    cancel()
    _state.clear()
    _set_phase("starting")

    result = {
        "from": pending.get("from"),
        "to": pending.get("to"),
        "requested_at": pending.get("requested_at"),
    }
    try:
        if not pending.get("from") or not pending.get("to"):
            raise MigrationError("copy_failed", "unreadable migration request")
        warnings = _migrate(pending)
        result.update(ok=True, warnings=warnings)
        logger.info(f"[Workspace] now using {result['to']}")
    except MigrationError as e:
        result.update(ok=False, code=e.code, detail=e.detail, warnings=[])
        logger.error(f"[Workspace] migration failed ({e.code}), still using {result['from']}: {e.detail}")
    except Exception as e:
        result.update(ok=False, code="copy_failed", detail=str(e), warnings=[])
        logger.exception(f"[Workspace] migration failed, still using {result['from']}")
    except BaseException:
        # Ctrl+C: _migrate has rolled back; record why before the process stops.
        result.update(ok=False, code="interrupted", detail="", warnings=[])
        _record_result(result)
        raise
    _record_result(result)
    return result


def _record_result(result: Dict) -> None:
    result["finished_at"] = _now()
    try:
        write_json_atomic(result_path(), result, indent=2)
    except OSError as e:
        logger.warning(f"[Workspace] could not record the migration result: {e}")


# ---------------------------------------------------------- progress server

_PROGRESS_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="3"><title>CowAgent</title></head>
<body style="font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;color:#475569">
<div style="text-align:center"><p style="font-size:16px">正在迁移工作空间，完成后将自动打开控制台，请勿关闭服务。</p>
<p style="font-size:13px;color:#94a3b8">Moving the workspace. The console opens when it is done; please keep the service running.</p></div>
</body></html>"""


def serve_progress(host: str, port: int):
    """Answer on the console's port while the move runs, before the console
    itself can start: an open console tab polls /api/workspace-location and
    draws the progress, anything else gets a page that reloads until the
    console is back. Returns a function that stops the server, or None when
    the port could not be bound."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?", 1)[0] == "/api/workspace-location":
                # Counts only: nothing here needs a login to be safe to show.
                body = json.dumps({"status": "success", "migrating": True, "progress": progress()})
                self._send(200, body.encode("utf-8"), "application/json; charset=utf-8")
            elif self.path.startswith("/api/"):
                self._send(503, b'{"status": "error", "code": "migrating"}', "application/json; charset=utf-8")
            else:
                self._send(503, _PROGRESS_PAGE.encode("utf-8"), "text/html; charset=utf-8")

        do_POST = do_GET

        def log_message(self, *args) -> None:
            pass

    class Server(ThreadingHTTPServer):
        # On Windows SO_REUSEADDR lets a second socket share a port already in use.
        allow_reuse_address = not _IS_WIN

    try:
        server = Server((host, port), Handler)
    except OSError as e:
        logger.warning(f"[Workspace] progress page unavailable on {host}:{port}: {e}")
        return None
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="workspace-migration-progress", daemon=True).start()

    def stop() -> None:
        server.shutdown()
        server.server_close()

    return stop
