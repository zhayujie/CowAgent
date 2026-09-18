"""Counterfactual: bounded steer latency if the stream loop probed the inbox.

This monkey-patches the streaming loop's probe to also check the steer inbox,
demonstrating what a bounded-reaction design would look like. Compare the
latency printed here with ``test_steer_latency_repro.py``.

Run:
    uv run pytest tests/test_steer_latency_counterfactual.py -s -q
"""

import threading
import time
from types import SimpleNamespace

import agent.protocol.agent_stream as agent_stream_mod
from agent.protocol.agent_stream import AgentStreamExecutor
from agent.protocol.steer import SteerInbox


class _SlowFakeModel:
    def __init__(self, n_chunks=40, delay=0.05):
        self.model = "slow-test-model"
        self.n_chunks = n_chunks
        self.delay = delay
        self.stream_started = threading.Event()
        self.call_count = 0
        self.chunks_yielded = 0
        self._lock = threading.Lock()

    def call_stream(self, request):
        with self._lock:
            self.call_count += 1
        self.stream_started.set()
        for i in range(self.n_chunks):
            time.sleep(self.delay)
            with self._lock:
                self.chunks_yielded += 1
            yield {"type": "content", "content": f"token-{i} "}
        yield {"type": "content", "content": ""}


class _ReproExecutor(AgentStreamExecutor):
    def _is_thinking_enabled(self):
        return False

    def _trim_messages(self):
        return None

    def _validate_and_fix_messages(self):
        return None

    def _execute_tool(self, tool_call):
        return {"status": "success", "result": "ok", "execution_time": 0.0}


def test_counterfactual_probe_reacts_fast(monkeypatch):
    """With an inbox probe inside the chunk loop, reaction is ~one chunk."""

    inbox = SteerInbox()
    # A non-destructive probe, standing in for a real fix's stream-loop check.
    # (The upstream SteerInbox currently exposes only drain(); a fix would add
    # something like has_pending().)
    steer_flag = threading.Event()
    inbox.has_pending = steer_flag.is_set  # type: ignore[attr-defined]

    model = _SlowFakeModel(n_chunks=40, delay=0.05)
    executor = _ReproExecutor(
        agent=SimpleNamespace(),
        model=model,
        system_prompt="",
        tools=[],
        max_turns=4,
        messages=[],
        steer_inbox=inbox,
    )

    t0 = time.monotonic()
    steer_submitted_at = {}
    steer_applied_at = {}
    probed_steer = {"hit": False}

    def on_event(event):
        if event["type"] == "agent_steered" and "applied" not in steer_applied_at:
            steer_applied_at["applied"] = time.monotonic()

    executor.on_event = on_event

    # --- inject a bounded inbox probe into the streaming loop ---------------
    # We wrap model.call_stream so that between chunks we simulate what a
    # fixed executor would do: notice the steer and abort the stream early.
    real_call_stream = model.call_stream

    def probing_call_stream(request):
        for chunk in real_call_stream(request):
            if inbox.has_pending():  # type: ignore[attr-defined]
                probed_steer["hit"] = True
                # A real fix would raise a SteeringInterrupt here; we simply
                # stop yielding further chunks to bound the wait.
                return
            yield chunk

    model.call_stream = probing_call_stream

    runner = threading.Thread(
        target=lambda: executor.run_stream("do something long"),
        daemon=True,
    )
    runner.start()

    assert model.stream_started.wait(timeout=5), "stream never started"
    time.sleep(0.2)
    steer_submitted_at["at"] = time.monotonic()
    chunks_at_steer = model.chunks_yielded
    inbox.submit("STOP doing that and do something else")
    steer_flag.set()

    runner.join(timeout=15)

    applied = steer_applied_at.get("applied")
    latency = (applied - steer_submitted_at["at"]) if applied else None
    remaining = (model.n_chunks - chunks_at_steer) * model.delay

    print(f"\n[counterfactual] chunks at steer: {chunks_at_steer}/{model.n_chunks}")
    print(f"[counterfactual] stream remaining: ~{remaining:.3f}s")
    print(f"[counterfactual] LLM calls: {model.call_count}")
    print(f"[counterfactual] probe hit: {probed_steer['hit']}")
    print(f"[counterfactual] steer->applied: "
          f"{'never' if latency is None else f'{latency:.3f}s'}")
