"""A ``Context`` must not share its kwargs dict with any other Context.

``Context.__init__`` used to take ``kwargs=dict()``. Python evaluates that
literal once, when the function is defined, so every Context built without an
explicit dict pointed at the *same* object -- and several call sites build one
that way and then write keys through ``context["..."] = ...`` (the scheduler's
delivery paths, the evolution push, the cloud client's message push). A key one
turn wrote (``session_id``, ``receiver``, ``agent_id``, ``receive_id_type``,
``msg``, ``on_event`` ...) was therefore still readable on the next Context
built the same way, in an unrelated conversation.
"""
from bridge.context import Context, ContextType


def test_two_contexts_do_not_share_kwargs():
    first = Context(ContextType.TEXT, "hello")
    first["session_id"] = "conversation-A"
    first["agent_id"] = "agent-A"

    second = Context(ContextType.TEXT, "a different conversation")

    assert second.kwargs is not first.kwargs
    assert second.get("session_id") is None
    assert second.get("agent_id") is None


def test_a_fresh_context_does_not_inherit_a_delivered_tasks_keys():
    """The shape the scheduler and the evolution push build: no explicit kwargs."""
    scheduled = Context(ContextType.TEXT, "reminder")
    scheduled["receiver"] = "feishu:user-1"
    scheduled["session_id"] = "feishu:user-1"
    scheduled["receive_id_type"] = "open_id"

    push = Context(ContextType.TEXT, "an unrelated proactive push")
    push["receiver"] = "wecom:user-2"
    push["isgroup"] = False

    assert push.get("receive_id_type") is None
    assert push.get("session_id") is None
    assert push.get("receiver") == "wecom:user-2"


def test_deleting_a_key_on_one_context_leaves_the_next_one_alone():
    first = Context(ContextType.TEXT, "a")
    first["k"] = "v"
    del first["k"]

    second = Context(ContextType.TEXT, "b")

    assert second.get("k") is None


def test_an_explicit_kwargs_is_used_as_given():
    given = {"a": 1}
    context = Context(ContextType.TEXT, "x", kwargs=given)
    context["b"] = 2

    assert context.kwargs is given
    assert given == {"a": 1, "b": 2}


def test_context_without_kwargs_gets_its_own_empty_dict():
    context = Context()

    assert context.kwargs == {}
    context["k"] = "v"
    assert context["k"] == "v"
