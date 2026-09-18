"""Minimal reproduction: steering latency during a live LLM stream.

The existing suite mocks ``_call_llm_stream`` out entirely, so a steer that
arrives *while the model is actually streaming* is never exercised. This file
drives the REAL streaming loop with a slow fake provider and measures how long
the run takes to react to a steer submitted mid-stream.

Run:
    uv run pytest tests/test_steer_latency_repro.py -s -q
"""

import threading
import time
from types import SimpleNamespace

from agent.protocol.agent_stream import AgentStreamExecutor
from agent.protocol.steer import SteerInbox


class _SlowFakeModel:
    """Model whose ``call_stream`` yields ``n_chunks`` chunks with a delay.

    Total stream duration stands in for "the model is producing a long answer /
    many tool calls". A real provider looks the same from the executor's view:
    one generator that must be consumed to the end.
    """

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

    def _execute_tool(self, tool_call):  # pragma: no cover - not used here
        return {"status": "success", "result": "ok", "execution_time": 0.0}


def test_steer_during_live_stream_latency():
    """Delay between submitting a steer and the run reacting to it.

    Expected (buggy) behaviour: the run cannot react until the whole stream is
    consumed, so latency is ~ the remaining stream duration plus a full extra
    turn. A fixed design would react within a bounded number of chunks.
    """

    inbox = SteerInbox()
    model = _SlowFakeModel(n_chunks=40, delay=0.05)  # 2.0s total stream
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
    timeline = []
    steer_submitted_at = {}
    steer_applied_at = {}

    def on_event(event):
        name = event["type"]
        timeline.append((round(time.monotonic() - t0, 3), name))
        if name == "agent_steered" and "applied" not in steer_applied_at:
            steer_applied_at["applied"] = time.monotonic()

    executor.on_event = on_event

    runner = threading.Thread(
        target=lambda: executor.run_stream("do something long"),
        daemon=True,
    )
    runner.start()

    assert model.stream_started.wait(timeout=5), "stream never started"
    time.sleep(0.2)  # let a few chunks flow
    steer_submitted_at["at"] = time.monotonic()
    chunks_at_steer = model.chunks_yielded
    inbox.submit("STOP doing that and do something else")

    runner.join(timeout=15)

    applied = steer_applied_at.get("applied")
    latency = (applied - steer_submitted_at["at"]) if applied else None
    remaining = (model.n_chunks - chunks_at_steer) * model.delay

    print(f"\n[live-stream steer] chunks yielded when steered: {chunks_at_steer}/{model.n_chunks}")
    print(f"[live-stream steer] stream would run ~{remaining:.3f}s more")
    print(f"[live-stream steer] LLM calls made: {model.call_count}")
    print(f"[live-stream steer] steer->applied latency: "
          f"{'never applied' if latency is None else f'{latency:.3f}s'}")
    print(f"[live-stream steer] event timeline:")
    for ts, name in timeline:
        print(f"    +{ts:>6.3f}s  {name}")

    # --- regression witness: assert the observed (bad) property -------------
    assert applied is not None, "steer was never applied at all"
    assert latency is not None and latency >= remaining * 0.5, (
        f"steer reacted in {latency:.3f}s, faster than the remaining stream "
        f"({remaining:.3f}s) - the defect may have been fixed; update this repro"
    )
