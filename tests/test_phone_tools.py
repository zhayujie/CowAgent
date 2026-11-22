import threading
import time
from types import SimpleNamespace

import pytest

from agent.tools.phone import bridge as bridge_module
from agent.tools.phone.bridge import PhoneBridge
from agent.tools.phone.phone_calendar import PhoneCalendar
from agent.tools.phone.phone_contacts import PhoneContacts
from agent.tools.phone.phone_location import PhoneLocation
from agent.tools.phone.phone_open import PhoneOpen
from agent.tools.phone.phone_photos import PhonePhotos
from agent.tools.phone.phone_share import PhoneShare


@pytest.fixture
def phone(monkeypatch):
    fresh = PhoneBridge()
    monkeypatch.setattr(bridge_module, "bridge", fresh)
    monkeypatch.setattr("agent.tools.phone.base.bridge", fresh)
    return fresh


def _app(phone, handle, rounds=1):
    """An app that polls and answers each request with ``handle(request)``."""
    def run():
        for _ in range(rounds):
            requests, _ = phone.poll(
                ["phone_open", "phone_location", "phone_calendar", "phone_photos", "phone_share"], 2,
            )
            for r in requests:
                phone.answer(r["id"], handle(r))
    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(0.05)
    return t


def _tool(cls, channel="web", workspace=None):
    tool = cls()
    tool.model = SimpleNamespace(channel_type=channel)
    tool.context = SimpleNamespace(workspace_dir=workspace)
    tool.cwd = workspace
    return tool


def test_offered_only_after_app_polls_and_in_app_chats(phone):
    assert not _tool(PhoneLocation).is_available()
    phone.poll(["phone_location"], 0)
    assert _tool(PhoneLocation).is_available()
    assert not _tool(PhoneOpen).is_available()
    assert not _tool(PhoneLocation, channel="feishu").is_available()


def test_round_trip(phone):
    seen = []

    def handle(r):
        seen.append(r)
        return {"ok": True, "result": {"latitude": 1.0}}

    _app(phone, handle)
    result = _tool(PhoneOpen).execute({"action": "call", "target": "10086"})
    assert result.status == "success"
    assert seen[0]["tool"] == "phone_open"
    assert seen[0]["args"] == {"action": "call", "target": "10086"}


def test_app_not_polling_gives_up_after_delivery_wait(phone, monkeypatch):
    monkeypatch.setattr(bridge_module, "DELIVERY_WAIT", 0.3)
    phone.poll(["phone_location"], 0)
    result = _tool(PhoneLocation).execute({})
    assert result.status == "error"
    assert "not open" in result.result
    assert phone.poll(["phone_location"], 0) == ([], [])


def test_request_waits_for_a_late_poll(phone, monkeypatch):
    monkeypatch.setattr(bridge_module, "DELIVERY_WAIT", 2)
    phone.poll(["phone_location"], 0)

    def late_app():
        time.sleep(0.5)
        requests, _ = phone.poll(["phone_location"], 1)
        phone.answer(requests[0]["id"], {"ok": True, "result": {"latitude": 1}})

    threading.Thread(target=late_app, daemon=True).start()
    assert _tool(PhoneLocation).execute({}).status == "success"


def test_app_error_codes_reach_the_model(phone):
    _app(phone, lambda r: {"ok": False, "error": "permission_denied"})
    result = _tool(PhoneLocation).execute({})
    assert result.status == "error"
    assert "did not grant" in result.result


def test_cancel_tells_the_app(phone):
    phone.poll(["phone_location"], 0)
    cancel = threading.Event()
    tool = _tool(PhoneLocation)
    tool.cancel_event = cancel
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", tool.execute({})))
    t.start()
    requests, _ = phone.poll(["phone_location"], 2)
    assert len(requests) == 1
    cancel.set()
    t.join(2)
    assert out["r"].status == "error"
    _, cancelled = phone.poll(["phone_location"], 2)
    assert cancelled == [requests[0]["id"]]
    assert phone.answer(requests[0]["id"], {"ok": True}) is False


def test_phone_tools_load_on_mobile_only(monkeypatch):
    from agent.tools.tool_manager import _available_here

    monkeypatch.delenv("COW_DEPLOYMENT", raising=False)
    assert not _available_here("phone_open")
    assert _available_here("bash")
    monkeypatch.setenv("COW_DEPLOYMENT", "mobile")
    assert _available_here("phone_location")
    assert not _available_here("bash")


def test_calendar_passes_times_on(phone):
    seen = []
    _app(phone, lambda r: seen.append(r) or {"ok": True, "result": []}, rounds=2)
    assert _tool(PhoneCalendar).execute({"action": "list", "start": "2026-11-25"}).status == "success"
    created = _tool(PhoneCalendar).execute(
        {"action": "create", "title": "Dentist", "start": "2026-11-25 15:00", "reminder_minutes": "30"}
    )
    assert created.status == "success"
    assert seen[1]["args"] == {
        "action": "create", "start": "2026-11-25T15:00", "title": "Dentist", "reminder_minutes": 30,
    }


def test_calendar_refuses_bad_times_before_reaching_the_phone(phone):
    phone.poll(["phone_calendar"], 0)
    result = _tool(PhoneCalendar).execute({"action": "create", "title": "x", "start": "tomorrow 3pm"})
    assert result.status == "error"
    assert phone.poll(["phone_calendar"], 0) == ([], [])


def test_read_only_session_cannot_add_events():
    from agent.permission.policy import check_tool_call

    assert not check_tool_call("read-only", "phone_calendar", {"action": "create"}).allowed
    assert check_tool_call("read-only", "phone_calendar", {"action": "list"}).allowed
    assert check_tool_call("read-only", "phone_contacts", {"query": "Ann"}).allowed


def test_picked_photos_land_in_the_workspace(phone, tmp_path):
    picked = tmp_path / "cache" / "rn_image_picker_lib_temp_1.jpg"
    picked.parent.mkdir()
    picked.write_bytes(b"jpeg")
    _app(phone, lambda r: {"ok": True, "result": {"photos": [
        {"path": f"file://{picked}"}, {"path": "/etc/passwd"},
    ]}})
    result = _tool(PhonePhotos, workspace=str(tmp_path / "ws")).execute({"max_count": 3})
    assert result.status == "success"
    [saved] = result.result["photos"]
    assert saved.startswith(str(tmp_path / "ws" / "tmp"))
    assert open(saved, "rb").read() == b"jpeg"


def test_phone_offers_no_full_access(monkeypatch):
    from agent.permission.policy import available_modes, normalize_mode

    monkeypatch.delenv("COW_DEPLOYMENT", raising=False)
    assert "full-access" in available_modes()
    assert normalize_mode("full-access") == "full-access"
    monkeypatch.setenv("COW_DEPLOYMENT", "mobile")
    assert available_modes() == ("read-only", "workspace-write")
    assert normalize_mode("full-access") == "workspace-write"
    assert normalize_mode(None) == "workspace-write"
    assert normalize_mode("read-only") == "read-only"


def test_contacts_search_needs_a_name(phone):
    phone.poll(["phone_contacts"], 0)
    for query in (".", "*", "  "):
        assert _tool(PhoneContacts).execute({"query": query}).status == "error"
    assert phone.poll(["phone_contacts"], 0) == ([], [])


def test_share_hands_the_app_a_workspace_file(phone, tmp_path):
    (tmp_path / "report.pdf").write_bytes(b"%PDF")
    seen = []
    _app(phone, lambda r: seen.append(r) or {"ok": True, "result": {"shared": True}})
    assert _tool(PhoneShare, workspace=str(tmp_path)).execute({"path": "report.pdf"}).status == "success"
    assert seen[0]["args"] == {
        "path": str((tmp_path / "report.pdf").resolve()), "name": "report.pdf", "mime": "application/pdf",
    }


def test_share_refuses_what_is_not_a_file_here(phone, tmp_path):
    phone.poll(["phone_share"], 0)
    tool = _tool(PhoneShare, workspace=str(tmp_path))
    for path in ("missing.txt", "https://example.com/a.png", ""):
        assert tool.execute({"path": path}).status == "error"
    assert phone.poll(["phone_share"], 0) == ([], [])


def test_upcoming_occurrences():
    from datetime import datetime

    from agent.tools.scheduler.time_utils import upcoming_occurrences

    until = datetime(2026, 11, 25, 12, 0)
    daily = {"enabled": True, "next_run_at": "2026-11-23T08:00:00",
             "schedule": {"type": "cron", "expression": "0 8 * * *"}}
    assert upcoming_occurrences(daily, until, 10) == [
        datetime(2026, 11, d, 8, 0).timestamp() for d in (23, 24, 25)
    ]
    assert len(upcoming_occurrences(daily, until, 2)) == 2
    hourly = {"enabled": True, "next_run_at": "2026-11-25T10:30:00", "schedule": {"type": "interval", "seconds": 3600}}
    assert upcoming_occurrences(hourly, until, 10) == [
        datetime(2026, 11, 25, 10, 30).timestamp(), datetime(2026, 11, 25, 11, 30).timestamp(),
    ]
    once = {"enabled": True, "next_run_at": "2026-11-24T20:00:00", "schedule": {"type": "once"}}
    assert upcoming_occurrences(once, until, 10) == [datetime(2026, 11, 24, 20, 0).timestamp()]
    assert upcoming_occurrences({**once, "enabled": False}, until, 10) == []
    zoned = {"enabled": True, "next_run_at": "2026-11-24T12:00:00+00:00",
             "schedule": {"type": "once", "timezone": "Asia/Shanghai"}}
    assert upcoming_occurrences(zoned, until, 10) == [1795521600.0]


def test_upcoming_occurrences_skip_a_stale_next_run():
    from datetime import datetime

    from agent.tools.scheduler.time_utils import upcoming_occurrences

    now = datetime(2026, 11, 25, 10, 2)
    until = datetime(2026, 11, 25, 10, 30)
    every_5m = {"enabled": True, "next_run_at": "2026-11-24T10:00:00", "schedule": {"type": "interval", "seconds": 300}}
    assert upcoming_occurrences(every_5m, until, 2, now=now) == [
        datetime(2026, 11, 25, 10, 5).timestamp(), datetime(2026, 11, 25, 10, 10).timestamp(),
    ]
    daily = {"enabled": True, "next_run_at": "2026-11-20T08:00:00",
             "schedule": {"type": "cron", "expression": "0 8 * * *"}}
    assert upcoming_occurrences(daily, datetime(2026, 11, 26, 9, 0), 5, now=now) == [
        datetime(2026, 11, 26, 8, 0).timestamp()
    ]


def test_runs_wait_until_the_list_changes(monkeypatch):
    import json

    import agent.memory
    from channel.web.api import scheduler as api

    ledger = [[{"run_id": "r1", "status": "running", "extras": {}}]] * 3 + [
        [{"run_id": "r1", "status": "done", "extras": {"output_preview": "ok"}}]
    ]
    reads = []

    class Store:
        def list_runs(self, **_):
            reads.append(1)
            return [dict(r) for r in ledger[min(len(reads), len(ledger)) - 1]]

    monkeypatch.setattr(agent.memory, "get_conversation_store", lambda: Store())
    monkeypatch.setattr(api, "_require_auth", lambda: None)
    monkeypatch.setattr(api.web, "header", lambda *a, **k: None)
    monkeypatch.setattr(api, "time", SimpleNamespace(sleep=lambda s: None, monotonic=time.monotonic))

    def get(**query):
        defaults = dict(agent_id="", task_id="", limit="100", since="", offset="0", wait="0", etag="")
        monkeypatch.setattr(api.web, "input", lambda **_: SimpleNamespace(**{**defaults, **query}))
        return json.loads(api.SchedulerRunsHandler().GET())

    first = get()
    assert first["runs"][0]["status"] == "running" and len(reads) == 1
    changed = get(wait="25", etag=first["etag"])
    assert changed["runs"][0]["status"] == "done" and changed["etag"] != first["etag"]
    assert len(reads) == 4


def test_await_run_wakes_the_scheduler_and_tells_how_the_run_ended(monkeypatch):
    import agent.memory
    from agent.tools.scheduler import integration

    ledger = [[]] + [[{"run_id": "r1", "status": "running", "extras": {}}]] * 2 + [
        [{"run_id": "r1", "status": "done", "error": None, "extras": {"output_preview": "rain"}}]
    ]
    queries = []

    class Store:
        def list_runs(self, **query):
            queries.append(query)
            return ledger[min(len(queries), len(ledger)) - 1]

    woken = []
    monkeypatch.setattr(agent.memory, "get_conversation_store", lambda: Store())
    monkeypatch.setattr(integration, "_scheduler_service", SimpleNamespace(wake=lambda: woken.append(1)))
    monkeypatch.setattr(integration, "time", SimpleNamespace(sleep=lambda s: None, monotonic=time.monotonic))

    run = integration.await_run("t1", 100, 30)
    assert woken == [1]
    assert run == {"run_id": "r1", "status": "done", "error": "", "output_preview": "rain"}
    assert queries[0] == {"task_source": "scheduler", "task_id": "t1", "since": 100, "limit": 1}

    queries.clear()
    ledger[:] = [[{"run_id": "r2", "status": "running", "extras": {}}]]
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(integration, "time", SimpleNamespace(sleep=lambda s: None, monotonic=lambda: next(clock)))
    assert integration.await_run("t1", 100, 30) == {}
    assert len(queries) == 3


def test_a_woken_scheduler_checks_at_once():
    from agent.tools.scheduler.scheduler_service import SchedulerService

    checked = threading.Event()
    service = SchedulerService(SimpleNamespace(list_tasks=lambda **_: []), lambda task: True)
    ticks = []

    def check():
        ticks.append(1)
        if len(ticks) == 2:
            checked.set()

    service._check_and_execute_tasks = check
    service.start()
    try:
        time.sleep(0.2)
        service.wake()
        assert checked.wait(2)
    finally:
        service.stop()


@pytest.mark.parametrize("mobile, loopback, authed, expected", [
    (False, True, True, "notfound"),
    (True, False, True, "notfound"),
    (True, True, False, "unauthorized"),
    (True, True, True, None),
])
def test_phone_routes_answer_the_app_alone(monkeypatch, mobile, loopback, authed, expected):
    from channel.web.api import phone as api

    class Refused(Exception):
        pass

    def require_auth():
        if not authed:
            raise Refused("unauthorized")

    monkeypatch.setattr(api, "is_mobile", lambda: mobile)
    monkeypatch.setattr(api, "_is_loopback_request", lambda: loopback)
    monkeypatch.setattr(api, "_require_auth", require_auth)
    monkeypatch.setattr(api.web, "notfound", lambda: Refused("notfound"))
    monkeypatch.setattr(api.web, "data", lambda: b"{}")
    if expected is None:
        assert api._guard() == {}
    else:
        with pytest.raises(Refused, match=expected):
            api._guard()
