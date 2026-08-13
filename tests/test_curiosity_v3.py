import asyncio
from concurrent.futures import ThreadPoolExecutor

from agent.curiosity import (
    CuriosityState,
    FatigueGuard,
    FeedbackEngine,
    InterestGraph,
    PushOrchestrator,
)


def test_fatigue_guard_keeps_all_concurrent_feedback():
    state = CuriosityState()
    guard = FatigueGuard(state, window_size=100)

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(guard.record_feedback, (index % 2 == 0 for index in range(100))))

    window = state.snapshot()["feedback_window"]
    assert len(window) == 100
    assert window.count(1) == 50
    assert window.count(0) == 50


def test_feedback_keywords_do_not_match_substrings_and_balance_mixed_feedback():
    engine = FeedbackEngine()

    false_positive = asyncio.run(engine.analyze("这个电影真好看"))
    mixed = asyncio.run(engine.analyze("真好但无聊"))

    assert false_positive.type == "neutral"
    assert false_positive.weight == 0
    assert mixed.type == "neutral"
    assert mixed.weight == 0


def test_feedback_engine_falls_back_to_neutral_on_llm_failure_or_invalid_json():
    async def timeout(_message):
        raise TimeoutError

    timeout_result = asyncio.run(FeedbackEngine(llm_analyzer=timeout).analyze("unclear"))
    invalid_result = asyncio.run(
        FeedbackEngine(llm_analyzer=lambda _message: "not json").analyze("unclear")
    )

    assert (timeout_result.type, timeout_result.weight) == ("neutral", 0)
    assert (invalid_result.type, invalid_result.weight) == ("neutral", 0)


def test_interest_graph_concurrent_get_or_create_preserves_one_node():
    graph = InterestGraph(CuriosityState())

    with ThreadPoolExecutor(max_workers=16) as pool:
        nodes = list(pool.map(lambda _: graph.get_or_create("python"), range(100)))

    assert len(graph.snapshot()) == 1
    assert len({node["created_at"] for node in nodes}) == 1


class _Guard:
    def __init__(self, error=False):
        self.error = error

    def is_fatigued(self):
        if self.error:
            raise RuntimeError("guard failed")
        return False


def test_orchestrator_isolates_message_and_guard_failures():
    def fail_messages():
        raise TimeoutError

    messages_failure = PushOrchestrator(fail_messages, _Guard(), lambda messages: messages)
    guard_failure = PushOrchestrator(lambda: ["hello"], _Guard(error=True), lambda messages: messages)

    assert messages_failure.orchestrate() is None
    assert guard_failure.orchestrate() is None
