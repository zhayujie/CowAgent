"""Time helpers for scheduler persistence and recurrence.

Scheduling timestamps are stored as timezone-aware UTC instants. Calendar
recurrences (cron expressions) are evaluated in an explicit IANA zone so their
local wall-clock meaning survives DST transitions.
"""
from croniter import croniter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc

# Fields whose persisted values are scheduling instants. Other metadata such as
# created_at/updated_at is not needed by the comparison path and is left alone
# for compatibility with external editors.
SCHEDULE_TIMESTAMP_FIELDS = (
    "next_run_at",
    "last_run_at",
    "last_error_at",
    "last_manual_run_at",
)


def utc_now() -> datetime:
    """Return the current instant in UTC."""
    return datetime.now(UTC)


def resolve_timezone(name=None):
    """Resolve an optional IANA name, defaulting to the server-local zone."""
    if name is None:
        return datetime.now().astimezone().tzinfo
    if not isinstance(name, str) or not name.strip():
        raise ValueError("timezone must be a non-empty IANA name")
    return ZoneInfo(name.strip())


def task_timezone(task: dict):
    """Return the timezone declared by a task, or the server-local zone."""
    return resolve_timezone(task.get("schedule", {}).get("timezone"))


def parse_utc(value: str, default_zone=None) -> datetime:
    """Parse an ISO timestamp and normalize it to an aware UTC datetime.

    Naive values remain conservative: they use the task timezone when one is
    declared, otherwise the server-local zone that previous CowAgent versions
    implicitly used.
    """
    if not isinstance(value, str):
        raise TypeError("timestamp must be an ISO string")

    # datetime.fromisoformat accepts "Z" from Python 3.11; normalize it here so
    # the scheduler keeps working on the versions supported by the project.
    if value.endswith(("Z", "z")):
        value = value[:-1] + "+00:00"

    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_zone or resolve_timezone())
    return dt.astimezone(UTC)


def format_utc(value: datetime) -> str:
    """Format a datetime as an aware UTC ISO string."""
    return value.astimezone(UTC).isoformat()


def normalize_task_timestamps(task: dict) -> dict:
    """Normalize scheduling fields in a task copy to aware UTC strings.

    This is deliberately done in memory as tasks are read. Existing naive
    values are interpreted in their declared/server timezone, but tasks that
    the scheduler never needs to act on are not rewritten on upgrade.
    """
    zone = task_timezone(task)
    normalized = dict(task)
    for field in SCHEDULE_TIMESTAMP_FIELDS:
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = format_utc(parse_utc(value, zone))
    return normalized


def _localize_wall_time(naive_dt: datetime, zone) -> datetime:
    """Attach a zone to a local wall clock with explicit DST policies.

    Fall-back times use the first occurrence (``fold=0``), so a daily task does
    not run twice. Spring-forward gaps advance minute by minute to the next
    real local time. Aware croniter input can otherwise manufacture an offset
    for a wall time that never exists.
    """
    candidate = naive_dt.replace(tzinfo=zone)
    instant = candidate.astimezone(UTC)
    if instant.astimezone(zone).replace(tzinfo=None) == naive_dt:
        return instant

    for _ in range(120):  # enough for the largest civil-time gap
        naive_dt += timedelta(minutes=1)
        candidate = naive_dt.replace(tzinfo=zone)
        instant = candidate.astimezone(UTC)
        if instant.astimezone(zone).replace(tzinfo=None) == naive_dt:
            return instant
    raise ValueError("could not resolve local time across a DST transition")


def next_cron_occurrence(expression: str, after_utc: datetime, zone=None) -> datetime:
    """Evaluate cron wall-clock recurrence in a zone and return a UTC instant."""
    local_zone = zone or resolve_timezone()
    local_after = after_utc.astimezone(local_zone).replace(tzinfo=None)
    local_next = croniter(expression, local_after).get_next(datetime)
    return _localize_wall_time(local_next, local_zone).astimezone(UTC)


def display_local(value: str, default_zone=None) -> datetime:
    """Convert a persisted scheduling timestamp to local time for display."""
    return parse_utc(value, default_zone).astimezone()
