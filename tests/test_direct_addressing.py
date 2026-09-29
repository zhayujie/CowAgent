"""Addressing a teammate by name hands them the turn.

The alternative — the conversation's owner receiving the turn and forwarding it
— reads as a middleman: the user already said who they wanted, so a handover
adds a hop, a delay and a paraphrase. These cover the routing decision and the
one invariant it must not break: the conversation stays a single transcript
owned by one Agent, whoever happens to be speaking.
"""

import json
import threading
from types import SimpleNamespace

import pytest

from agent.registry import AgentRegistry, get_agent_registry, set_agent_registry
from bridge.agent_bridge import AgentBridge
from bridge.agent_initializer import AgentInitializer


@pytest.fixture(autouse=True)
def registry_restored():
    """Never let a pinned registry outlive the test that pinned it.

    Two of the classes below pin a registry so the roster they build is what
    resolves a workspace. ``set_agent_registry`` pins process-wide and keeps
    answering from that instance even after configuration moves on, so without
    this teardown the registry stays pinned for the rest of the run and every
    later test -- here, and in whichever module pytest reaches next -- resolves
    its workspace through this file's ``tmp_path``.
    """
    yield
    set_agent_registry(None)


class _FakeInitializer:
    def __init__(self, registry):
        self.registry = registry
        self.calls = []

    def initialize_agent(self, session_id=None, agent_id=None, host_agent_id=None):
        profile = self.registry.get(agent_id)
        self.calls.append((profile.id, session_id, host_agent_id))
        return SimpleNamespace(
            agent_id=profile.id,
            workspace_dir=profile.workspace,
            messages=[],
            messages_lock=threading.RLock(),
        )


def _bridge(tmp_path, disabled=()):
    registry = AgentRegistry.from_config(
        {
            "default_agent_id": "primary",
            "agents": [
                {
                    "id": "primary",
                    "name": "Primary",
                    "workspace": str(tmp_path / "primary"),
                },
                {
                    "id": "ops",
                    "name": "运营助手",
                    "workspace": str(tmp_path / "ops"),
                    "enabled": "ops" not in disabled,
                },
            ],
        }
    )
    bridge = object.__new__(AgentBridge)
    bridge.agent_registry = registry
    bridge._agent_instances = {}
    bridge._default_agents = {}
    bridge._agents_lock = threading.RLock()
    bridge.agents = {}
    bridge.default_agent = None
    bridge.initializer = _FakeInitializer(registry)
    return bridge


class _Ctx(dict):
    """Context exposes .get, which is all the resolver touches."""


def test_named_teammate_answers_instead_of_the_owner(tmp_path):
    bridge = _bridge(tmp_path)
    assert bridge._resolve_speaker("primary", _Ctx(speaker_agent_id="ops")) == "ops"


def test_unnamed_turn_stays_with_the_owner(tmp_path):
    bridge = _bridge(tmp_path)
    assert bridge._resolve_speaker("primary", _Ctx()) == "primary"
    assert bridge._resolve_speaker("primary", None) == "primary"


@pytest.mark.parametrize("named", ["ghost", "ops"])
def test_unreachable_addressee_falls_back_to_the_owner(tmp_path, named):
    """An archived or disabled teammate must not strand the turn: the user gets
    an answer from the owner rather than an error about routing."""
    bridge = _bridge(tmp_path, disabled=("ops",))
    assert bridge._resolve_speaker("primary", _Ctx(speaker_agent_id=named)) == "primary"


def test_guest_answers_as_itself_inside_the_owner_s_conversation(tmp_path):
    bridge = _bridge(tmp_path)
    bridge.get_agent(session_id="chat", agent_id="ops", host_agent_id="primary")

    agent_id, session_id, host = bridge.initializer.calls[-1]
    assert (agent_id, session_id) == ("ops", "chat")
    # The guest keeps its own workspace but is pointed at the host's transcript,
    # so it continues the conversation the user is looking at.
    assert host == "primary"


def test_owner_is_not_told_it_is_hosting_itself(tmp_path):
    bridge = _bridge(tmp_path)
    bridge.get_agent(session_id="chat", agent_id="primary", host_agent_id="primary")
    assert bridge.initializer.calls[-1] == ("primary", "chat", "primary")


def test_guest_and_owner_are_separate_runtimes_on_one_session(tmp_path):
    bridge = _bridge(tmp_path)
    owner = bridge.get_agent(session_id="chat")
    guest = bridge.get_agent(session_id="chat", agent_id="ops", host_agent_id="primary")

    assert owner is not guest
    assert bridge.get_agent(session_id="chat") is owner


def test_guest_roster_names_the_host_and_never_itself(tmp_path, monkeypatch):
    """A guest that could not see the host would talk past the person who owns
    the conversation."""
    from agent.workspace import session_prefs

    monkeypatch.setattr(
        session_prefs, "get_prefs", lambda sid, aid: {"members": ["ops"]}
    )
    registry = AgentRegistry.from_config(
        {
            "default_agent_id": "primary",
            "agents": [
                {"id": "primary", "name": "Primary", "workspace": str(tmp_path / "p")},
                {"id": "ops", "name": "运营助手", "workspace": str(tmp_path / "o")},
            ],
        }
    )
    monkeypatch.setattr("agent.registry.get_agent_registry", lambda: registry)

    guest_view = AgentInitializer._teammates_getter("chat", "ops", "primary")()
    assert [item["id"] for item in guest_view] == ["primary"]

    owner_view = AgentInitializer._teammates_getter("chat", "primary", "primary")()
    assert [item["id"] for item in owner_view] == ["ops"]


class TestSeedTeamMembersFromChannelInstance:
    """A team channel bot (e.g. a Feishu instance with members) carries its
    roster on every message. The bridge materializes it onto the session once,
    so the shared delegate/@mention machinery — which reads session_prefs — sees
    a team, exactly like a Web team conversation.
    """

    @staticmethod
    def _ctx(**kw):
        c = _Ctx(kw)
        c.kwargs = {}
        return c

    def test_seeds_when_session_has_no_roster(self, tmp_path, monkeypatch):
        from agent.workspace import session_prefs

        calls = {}
        monkeypatch.setattr(session_prefs, "get_prefs", lambda sid, aid: {})
        monkeypatch.setattr(
            session_prefs, "set_prefs",
            lambda sid, aid, **kw: calls.update({"sid": sid, "aid": aid, **kw}),
        )
        bridge = _bridge(tmp_path)
        bridge._seed_team_members("chat", "primary", self._ctx(members=["ops"]))
        assert calls == {"sid": "chat", "aid": "primary", "members": ["ops"]}

    def test_owner_is_never_seeded_as_a_member(self, tmp_path, monkeypatch):
        from agent.workspace import session_prefs

        calls = {}
        monkeypatch.setattr(session_prefs, "get_prefs", lambda sid, aid: {})
        monkeypatch.setattr(
            session_prefs, "set_prefs",
            lambda sid, aid, **kw: calls.update(kw),
        )
        bridge = _bridge(tmp_path)
        bridge._seed_team_members(
            "chat", "primary", self._ctx(members=["primary", "ops"])
        )
        assert calls.get("members") == ["ops"]

    def test_channel_roster_is_authoritative_and_reconciles(self, tmp_path, monkeypatch):
        # The channel instance's roster is the source of truth: when the session
        # roster differs, it is reconciled to match the instance (not left stale).
        from agent.workspace import session_prefs

        seeded = []
        monkeypatch.setattr(
            session_prefs, "get_prefs", lambda sid, aid: {"members": ["research"]}
        )
        monkeypatch.setattr(
            session_prefs, "set_prefs",
            lambda sid, aid, **kw: seeded.append(kw),
        )
        bridge = _bridge(tmp_path)
        bridge._seed_team_members("chat", "primary", self._ctx(members=["ops"]))
        assert seeded == [{"members": ["ops"]}]

    def test_already_in_sync_is_a_noop(self, tmp_path, monkeypatch):
        from agent.workspace import session_prefs

        seeded = []
        monkeypatch.setattr(
            session_prefs, "get_prefs", lambda sid, aid: {"members": ["ops"]}
        )
        monkeypatch.setattr(
            session_prefs, "set_prefs", lambda *a, **kw: seeded.append(kw)
        )
        bridge = _bridge(tmp_path)
        bridge._seed_team_members("chat", "primary", self._ctx(members=["ops"]))
        assert seeded == []  # no redundant write when nothing changed

    def test_single_agent_instance_clears_stale_session_roster(self, tmp_path, monkeypatch):
        # Switching an instance back to a single Agent (empty members) must drop
        # the session's stale team roster, or the team prompt keeps injecting.
        from agent.workspace import session_prefs

        calls = []
        monkeypatch.setattr(
            session_prefs, "get_prefs", lambda sid, aid: {"members": ["ops"]}
        )
        monkeypatch.setattr(
            session_prefs, "set_prefs",
            lambda sid, aid, **kw: calls.append(kw),
        )
        bridge = _bridge(tmp_path)
        # A channel message that now carries an empty roster (members=[]).
        bridge._seed_team_members("chat", "primary", self._ctx(members=[]))
        assert calls == [{"members": None}]  # roster cleared

    def test_empty_members_with_no_existing_roster_is_a_noop(self, tmp_path, monkeypatch):
        from agent.workspace import session_prefs

        calls = []
        monkeypatch.setattr(session_prefs, "get_prefs", lambda sid, aid: {})
        monkeypatch.setattr(
            session_prefs, "set_prefs", lambda *a, **kw: calls.append(kw)
        )
        bridge = _bridge(tmp_path)
        bridge._seed_team_members("chat", "primary", self._ctx(members=[]))
        assert calls == []  # nothing to clear, nothing to write

    def test_delegation_members_seed_once_and_never_clobber(self, tmp_path, monkeypatch):
        # A delegated turn (private session) seeds once from delegation_members
        # and must not overwrite an existing roster.
        from agent.workspace import session_prefs

        seeded = []
        monkeypatch.setattr(session_prefs, "get_prefs", lambda sid, aid: {})
        monkeypatch.setattr(
            session_prefs, "set_prefs",
            lambda sid, aid, **kw: seeded.append(kw),
        )
        bridge = _bridge(tmp_path)
        bridge._seed_team_members(
            "chat", "primary", self._ctx(delegation_members=["ops"])
        )
        assert seeded == [{"members": ["ops"]}]

        # Now with an existing roster, delegation must not clobber it.
        seeded.clear()
        monkeypatch.setattr(
            session_prefs, "get_prefs", lambda sid, aid: {"members": ["research"]}
        )
        bridge._seed_team_members(
            "chat", "primary", self._ctx(delegation_members=["ops"])
        )
        assert seeded == []

    def test_disabled_or_unknown_teammates_are_dropped(self, tmp_path, monkeypatch):
        from agent.workspace import session_prefs

        calls = {}
        monkeypatch.setattr(session_prefs, "get_prefs", lambda sid, aid: {})
        monkeypatch.setattr(
            session_prefs, "set_prefs",
            lambda sid, aid, **kw: calls.update(kw),
        )
        bridge = _bridge(tmp_path, disabled=("ops",))
        bridge._seed_team_members(
            "chat", "primary", self._ctx(members=["ops", "ghost"])
        )
        # ops is disabled, ghost is unknown: nothing addressable remains, so
        # no roster is written at all.
        assert calls == {}

    def test_no_members_on_context_is_a_noop(self, tmp_path, monkeypatch):
        from agent.workspace import session_prefs

        seeded = []
        monkeypatch.setattr(session_prefs, "get_prefs", lambda sid, aid: {})
        monkeypatch.setattr(
            session_prefs, "set_prefs", lambda *a, **kw: seeded.append(kw)
        )
        bridge = _bridge(tmp_path)
        bridge._seed_team_members("chat", "primary", self._ctx())
        assert seeded == []


class TestARosterChangeReachesAConversationAlreadyRunning:
    """Gaining a teammate has to gain the tool that reaches them.

    A runtime fixes its tool list when it is built, and ``agent_delegate`` is
    only offered to a conversation that has teammates. A channel whose team is
    edited while a conversation is live would otherwise keep answering without
    the tool -- describing the teammate from the prompt, yet unable to hand
    anything over -- until the process restarted.
    """

    @staticmethod
    def _ctx(**kw):
        c = _Ctx(kw)
        c.kwargs = {}
        return c

    @staticmethod
    def _live(bridge, session_id):
        agent = SimpleNamespace(agent_id="primary")
        bridge._agent_instances[("primary", session_id)] = agent
        bridge.agents[session_id] = agent

    def test_the_runtime_built_before_the_teammate_is_retired(self, tmp_path, monkeypatch):
        from agent.workspace import session_prefs

        monkeypatch.setattr(session_prefs, "get_prefs", lambda sid, aid: {})
        monkeypatch.setattr(session_prefs, "set_prefs", lambda *a, **kw: None)
        bridge = _bridge(tmp_path)
        self._live(bridge, "chat")

        bridge._seed_team_members("chat", "primary", self._ctx(members=["ops"]))

        assert ("primary", "chat") not in bridge._agent_instances
        assert "chat" not in bridge.agents

    def test_losing_the_last_teammate_retires_it_too(self, tmp_path, monkeypatch):
        from agent.workspace import session_prefs

        monkeypatch.setattr(
            session_prefs, "get_prefs", lambda sid, aid: {"members": ["ops"]}
        )
        monkeypatch.setattr(session_prefs, "set_prefs", lambda *a, **kw: None)
        bridge = _bridge(tmp_path)
        self._live(bridge, "chat")

        bridge._seed_team_members("chat", "primary", self._ctx(members=[]))

        assert ("primary", "chat") not in bridge._agent_instances

    def test_an_unchanged_roster_leaves_the_conversation_alone(self, tmp_path, monkeypatch):
        # Retiring on every message would rebuild the runtime each turn.
        from agent.workspace import session_prefs

        monkeypatch.setattr(
            session_prefs, "get_prefs", lambda sid, aid: {"members": ["ops"]}
        )
        monkeypatch.setattr(session_prefs, "set_prefs", lambda *a, **kw: None)
        bridge = _bridge(tmp_path)
        self._live(bridge, "chat")

        bridge._seed_team_members("chat", "primary", self._ctx(members=["ops"]))

        assert ("primary", "chat") in bridge._agent_instances

    def test_only_the_edited_conversation_is_retired(self, tmp_path, monkeypatch):
        from agent.workspace import session_prefs

        monkeypatch.setattr(session_prefs, "get_prefs", lambda sid, aid: {})
        monkeypatch.setattr(session_prefs, "set_prefs", lambda *a, **kw: None)
        bridge = _bridge(tmp_path)
        self._live(bridge, "chat")
        self._live(bridge, "elsewhere")

        bridge._seed_team_members("chat", "primary", self._ctx(members=["ops"]))

        assert ("primary", "elsewhere") in bridge._agent_instances


class TestTheAddressComesOffBeforeTheModelSeesIt:
    """Routing has already answered what the mention was asking, so the Agent
    should be handed the question, not the envelope. Left in, it reads its own
    name as a third party and replies about that person instead of answering.
    """

    @staticmethod
    def _strip(tmp_path, text, speaker="ops"):
        return _bridge(tmp_path)._strip_address(text, speaker)

    def test_the_name_is_removed(self, tmp_path):
        assert self._strip(tmp_path, "@运营助手 你是谁") == "你是谁"

    def test_the_id_is_removed_too(self, tmp_path):
        assert self._strip(tmp_path, "@ops 你是谁") == "你是谁"

    def test_punctuation_after_the_name_goes_with_it(self, tmp_path):
        assert self._strip(tmp_path, "@运营助手，帮我看下") == "帮我看下"

    def test_leading_whitespace_is_consumed(self, tmp_path):
        assert self._strip(tmp_path, "  @运营助手  你是谁") == "你是谁"

    def test_the_rest_of_the_message_is_untouched(self, tmp_path):
        assert self._strip(
            tmp_path, "@运营助手 看下这个 @运营助手 的历史"
        ) == "看下这个 @运营助手 的历史"

    def test_a_bare_address_still_reaches_the_agent(self, tmp_path):
        """"@Ops" alone means "you, speak" — stripping it would send an empty
        turn, so the mention stays rather than becoming nothing."""
        assert self._strip(tmp_path, "@运营助手") == "@运营助手"
        assert self._strip(tmp_path, "@运营助手   ") == "@运营助手   "

    def test_a_message_addressed_to_nobody_is_unchanged(self, tmp_path):
        assert self._strip(tmp_path, "你是谁") == "你是谁"

    def test_someone_else_s_name_is_left_in_place(self, tmp_path):
        assert self._strip(tmp_path, "@Primary 你是谁") == "@Primary 你是谁"

    def test_an_unknown_speaker_leaves_the_text_alone(self, tmp_path):
        assert self._strip(tmp_path, "@运营助手 你是谁", "ghost") == "@运营助手 你是谁"

    def test_empty_input_survives(self, tmp_path):
        assert self._strip(tmp_path, "") == ""

    def test_attachment_lines_after_the_question_are_kept(self, tmp_path):
        assert self._strip(
            tmp_path, "@运营助手 看下\n[工作空间文件: a.md]"
        ) == "看下\n[工作空间文件: a.md]"


class TestRecordingWhoSpoke:
    """Attribution is for the transcript only. ``extras`` is a column of ours,
    not part of the message format, so it must never reach a model — which it
    does the moment the Agent's own context dicts are annotated in place."""

    MESSAGES = [
        {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
        {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
    ]

    def test_the_author_is_recorded(self, tmp_path):
        tagged = _bridge(tmp_path)._attribute_to_speaker(self.MESSAGES, "ops")
        assert [m["extras"]["agent_id"] for m in tagged] == ["ops", "ops"]

    def test_the_agent_s_own_messages_are_left_clean(self, tmp_path):
        """The regression: these dicts are the live LLM context. Annotated in
        place, every later request carries an `extras` key and the API 400s."""
        live = [dict(m) for m in self.MESSAGES]
        _bridge(tmp_path)._attribute_to_speaker(live, "ops")
        assert all("extras" not in message for message in live)

    def test_existing_extras_are_preserved(self, tmp_path):
        tagged = _bridge(tmp_path)._attribute_to_speaker(
            [{"role": "assistant", "content": "hi", "extras": {"audio": {"url": "u"}}}],
            "ops",
        )
        assert tagged[0]["extras"] == {"audio": {"url": "u"}, "agent_id": "ops"}

    def test_the_message_body_is_carried_over(self, tmp_path):
        tagged = _bridge(tmp_path)._attribute_to_speaker(self.MESSAGES, "ops")
        assert tagged[0]["content"] == [{"type": "text", "text": "hi"}]
        assert tagged[1]["role"] == "user"

    def test_nothing_to_attribute_is_not_an_error(self, tmp_path):
        assert _bridge(tmp_path)._attribute_to_speaker([], "ops") == []
        assert _bridge(tmp_path)._attribute_to_speaker(None, "ops") == []


class TestKnowingWhoWroteWhat:
    """A shared transcript replays through one ``assistant`` role. Unless the
    author is restored, an Agent reads a colleague's work as its own."""

    HISTORY = [
        {"role": "user", "content": [{"type": "text", "text": "ship it"}]},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "shipped"}],
            "agent_id": "ops",
        },
        {"role": "user", "content": [{"type": "text", "text": "and now?"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "on it"}]},
    ]

    def _attributed(self, tmp_path, reader):
        from agent.registry import set_agent_registry
        from bridge.agent_initializer import AgentInitializer

        bridge = _bridge(tmp_path)
        set_agent_registry(bridge.agent_registry)
        return AgentInitializer._attribute_history(self.HISTORY, reader)

    def test_a_colleagues_reply_is_replayed_as_the_user(self, tmp_path):
        """assistant+[Name] is what the model copies into its own mouth."""
        message = self._attributed(tmp_path, "default")[1]
        assert message["role"] == "user"
        assert message["content"][0]["text"].startswith("运营助手(@ops)：")
        assert "shipped" in message["content"][0]["text"]

    def test_your_own_reply_stays_assistant(self, tmp_path):
        message = self._attributed(tmp_path, "default")[3]
        assert message["role"] == "assistant"
        assert message["content"][0]["text"] == "on it"

    def test_the_same_reply_is_bare_for_the_one_who_wrote_it(self, tmp_path):
        message = self._attributed(tmp_path, "ops")[1]
        assert message["role"] == "assistant"
        assert message["content"][0]["text"] == "shipped"

    def test_the_users_own_turns_are_never_labelled(self, tmp_path):
        attributed = self._attributed(tmp_path, "default")
        assert [m["content"][0]["text"] for m in attributed if m["role"] == "user"] == [
            "ship it",
            "运营助手(@ops)：shipped",
            "and now?",
        ]

    def test_nothing_of_ours_reaches_the_model(self, tmp_path):
        """The 400 from last time: `agent_id` is ours, and no model accepts it."""
        for message in self._attributed(tmp_path, "default"):
            assert set(message) == {"role", "content"}


class TestKnowingItsOwnName:
    """An Agent that cannot read its own name does not recognise being called
    by it: it sees the mention as a third party and declines to answer on that
    stranger's behalf. Both halves of the fix are covered here — the prompt
    states the name, and a console-created Agent has it in its persona file."""

    @staticmethod
    def _team_prompt(language="zh"):
        from agent.prompt.builder import _build_team_section

        return "\n".join(
            _build_team_section(
                {
                    "agent_id": "ops",
                    "agent_name": "我的运营助手",
                    "teammates": [{"id": "default", "name": "Gray"}],
                },
                language,
            )
        )

    def test_the_prompt_states_the_agent_s_own_name(self):
        assert "我的运营助手" in self._team_prompt()
        assert "@ops" in self._team_prompt()

    def test_the_english_prompt_states_it_too(self):
        assert "我的运营助手(@ops)" in self._team_prompt("en")

    def test_teammates_are_still_named(self):
        assert "Gray(@default)" in self._team_prompt()

    def test_a_solo_conversation_gets_no_team_section(self):
        from agent.prompt.builder import _build_team_section

        assert _build_team_section({"agent_id": "ops", "teammates": []}, "zh") == []

    def test_creating_an_agent_writes_its_name_into_the_persona(self, tmp_path):
        from agent.admin import AgentAdminService

        persona = tmp_path / "AGENT.md"
        persona.write_text(
            "# AGENT.md\n\n- **名字**: *(在首次对话时填写)*\n- **角色**: *(填写)*\n",
            encoding="utf-8",
        )
        AgentAdminService._seed_name(str(tmp_path), "我的运营助手")
        assert "- **名字**: 我的运营助手" in persona.read_text(encoding="utf-8")

    def test_an_english_persona_template_is_seeded_too(self, tmp_path):
        from agent.admin import AgentAdminService

        persona = tmp_path / "AGENT.md"
        persona.write_text("- **Name**: *(fill in later)*\n", encoding="utf-8")
        AgentAdminService._seed_name(str(tmp_path), "Ops")
        assert persona.read_text(encoding="utf-8").strip() == "- **Name**: Ops"

    def test_a_persona_that_already_names_itself_is_left_alone(self, tmp_path):
        """A cloned or hand-written persona is the author's, not ours."""
        from agent.admin import AgentAdminService

        persona = tmp_path / "AGENT.md"
        original = "# 我是 Gray\n\n我是一个合伙人型助手。\n"
        persona.write_text(original, encoding="utf-8")
        AgentAdminService._seed_name(str(tmp_path), "Ops")
        assert persona.read_text(encoding="utf-8") == original

    def test_only_the_first_name_field_is_replaced(self, tmp_path):
        from agent.admin import AgentAdminService

        persona = tmp_path / "AGENT.md"
        persona.write_text(
            "- **名字**: *(填写)*\n\n## 用户\n- **名字**: 老板\n", encoding="utf-8"
        )
        AgentAdminService._seed_name(str(tmp_path), "Ops")
        assert persona.read_text(encoding="utf-8") == (
            "- **名字**: Ops\n\n## 用户\n- **名字**: 老板\n"
        )

    def test_a_missing_persona_file_is_not_an_error(self, tmp_path):
        from agent.admin import AgentAdminService

        AgentAdminService._seed_name(str(tmp_path / "nope"), "Ops")


def test_agent_delegate_survives_tool_loading(tmp_path):
    """The tool was skipped at load time by a NameError in its own gate, so a
    roster that should have had delegation silently had none."""
    import inspect

    from bridge.agent_initializer import AgentInitializer

    source = inspect.getsource(AgentInitializer._load_tools)
    assert "from config import conf" in source, (
        "_load_tools reads conf() to decide whether agent_delegate loads; "
        "without the import every load raises NameError and the tool vanishes"
    )


class TestMentionParsing:
    """The composer writes the display name, but a mention typed or edited by
    hand has to resolve too, so the text is the fallback source of truth."""

    ROSTER = [
        {"id": "primary", "name": "Primary", "avatar": ""},
        {"id": "agent-17n3e8", "name": "运营助手", "avatar": ""},
    ]

    @staticmethod
    def _resolve(text, roster=None):
        from channel.web.core._common import _addressed_agent_id

        if roster is None:
            roster = TestMentionParsing.ROSTER
        return _addressed_agent_id(text, roster)

    def test_leading_name_addresses_that_agent(self):
        assert self._resolve("@运营助手 你是谁") == "agent-17n3e8"

    def test_leading_id_still_works(self):
        assert self._resolve("@agent-17n3e8 你是谁") == "agent-17n3e8"

    def test_name_alone_addresses_that_agent(self):
        assert self._resolve("@运营助手") == "agent-17n3e8"

    def test_punctuation_after_the_name_counts_as_a_boundary(self):
        assert self._resolve("@运营助手，帮我看下") == "agent-17n3e8"

    def test_talking_about_someone_is_not_addressing_them(self):
        assert self._resolve("帮我问问 @运营助手 的看法") == ""

    def test_an_unknown_name_addresses_nobody(self):
        assert self._resolve("@nobody hello") == ""

    def test_plain_text_addresses_nobody(self):
        assert self._resolve("你是谁") == ""

    def test_an_empty_roster_addresses_nobody(self):
        assert self._resolve("@运营助手 你是谁", []) == ""

    def test_the_longer_label_wins_when_one_name_prefixes_another(self):
        roster = [
            {"id": "a", "name": "运营", "avatar": ""},
            {"id": "b", "name": "运营助手", "avatar": ""},
        ]
        assert self._resolve("@运营助手 你好", roster) == "b"
        assert self._resolve("@运营 你好", roster) == "a"


class TestSharedTranscriptStaysCurrent:
    """History is restored once on init. Without a reload, a teammate that
    already joined misses later turns spoken by someone else."""

    def test_a_later_host_turn_is_visible_to_the_guest(self, tmp_path, monkeypatch):
        from agent.memory import clear_conversation_store_cache, get_conversation_store
        from agent.registry import set_agent_registry
        from agent.workspace import session_prefs
        from config import conf

        bridge = _bridge(tmp_path)
        set_agent_registry(bridge.agent_registry)
        monkeypatch.setitem(conf(), "conversation_persistence", True)
        monkeypatch.setattr(
            session_prefs,
            "get_prefs",
            lambda sid, aid: {"members": ["ops"]} if sid == "chat" else {},
        )
        clear_conversation_store_cache()

        store = get_conversation_store(str(tmp_path / "primary"))
        store.append_messages(
            "chat",
            [
                {"role": "user", "content": [{"type": "text", "text": "team roster"}]},
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "ops is here"}],
                    "extras": {"agent_id": "primary"},
                },
            ],
        )

        guest = SimpleNamespace(
            agent_id="ops",
            workspace_dir=str(tmp_path / "ops"),
            messages=[{"role": "assistant", "content": [{"type": "text", "text": "stale"}]}],
            messages_lock=threading.RLock(),
        )
        initializer = AgentInitializer(bridge=None, agent_bridge=bridge)
        bridge.initializer = initializer
        initializer._restore_conversation_history(
            guest, "chat", str(tmp_path / "primary"), "primary"
        )
        assert any("ops is here" in str(m.get("content")) for m in guest.messages)

        store.append_messages(
            "chat",
            [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "CowAgent repo is here"}],
                },
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "located the repo"}],
                    "extras": {"agent_id": "primary"},
                },
            ],
        )
        # The cached guest still has only what it restored the first time.
        assert not any("located the repo" in str(m.get("content")) for m in guest.messages)

        bridge._sync_shared_transcript(guest, "chat", "primary")
        texts = [m["content"][0]["text"] for m in guest.messages]
        assert any(
            t.startswith("Primary(@primary)：") and "located the repo" in t for t in texts
        )

    def test_only_a_runtime_built_earlier_counts_as_cached(self, tmp_path):
        """A runtime built for this turn restored the transcript while
        initialising; reloading it again straight away is wasted work."""
        bridge = _bridge(tmp_path)
        assert not bridge._has_runtime("ops", "chat")
        bridge.get_agent(session_id="chat", agent_id="ops", host_agent_id="primary")
        assert bridge._has_runtime("ops", "chat")
        assert not bridge._has_runtime("primary", "chat")
        assert not bridge._has_runtime("ops", None)

    def test_solo_conversation_does_not_reload(self, tmp_path, monkeypatch):
        from agent.workspace import session_prefs

        monkeypatch.setattr(session_prefs, "get_prefs", lambda sid, aid: {})
        bridge = _bridge(tmp_path)
        guest = SimpleNamespace(
            agent_id="ops",
            messages=[{"keep": True}],
            messages_lock=threading.RLock(),
        )
        bridge._sync_shared_transcript(guest, "chat", "primary")
        assert guest.messages == [{"keep": True}]


class TestOwnToolChainsSurviveTheReload:
    """A team conversation is reread before every turn. Flattening the
    speaker's own turns to text leaves it a history of claimed work with no
    trace of the tool calls behind it, and it goes on claiming work it skips."""

    @staticmethod
    def _tool_turn(author, question, call_id, answer):
        stamp = {"agent_id": author} if author else {}
        return [
            {"role": "user", "content": [{"type": "text", "text": question}], **stamp},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "checking"},
                    {"type": "tool_use", "id": call_id, "name": "read", "input": {"path": "a.py"}},
                ],
                **stamp,
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": call_id, "content": "print(1)"}],
                **stamp,
            },
            {"role": "assistant", "content": [{"type": "text", "text": answer}], **stamp},
        ]

    def _history(self, tmp_path, reader):
        from agent.registry import set_agent_registry

        set_agent_registry(_bridge(tmp_path).agent_registry)
        return AgentInitializer._shared_history(
            [
                *self._tool_turn("primary", "fix a.py", "call_p", "fixed a.py"),
                *self._tool_turn("ops", "check a.py", "call_o", "a.py looks fine"),
            ],
            reader,
        )

    @staticmethod
    def _blocks(history, kind):
        return [
            block
            for message in history
            if isinstance(message["content"], list)
            for block in message["content"]
            if block.get("type") == kind
        ]

    def test_the_speaker_keeps_its_own_tool_calls(self, tmp_path):
        history = self._history(tmp_path, "primary")
        assert [b["id"] for b in self._blocks(history, "tool_use")] == ["call_p"]
        assert [b["tool_use_id"] for b in self._blocks(history, "tool_result")] == ["call_p"]
        assert history[3] == {"role": "assistant", "content": [{"type": "text", "text": "fixed a.py"}]}

    def test_a_colleagues_turn_is_still_flattened_and_named(self, tmp_path):
        history = self._history(tmp_path, "primary")
        assert history[4:] == [
            {"role": "user", "content": [{"type": "text", "text": "check a.py"}]},
            {"role": "user", "content": [{"type": "text", "text": "运营助手(@ops)：a.py looks fine"}]},
        ]

    def test_each_speaker_keeps_only_its_own(self, tmp_path):
        history = self._history(tmp_path, "ops")
        assert [b["id"] for b in self._blocks(history, "tool_use")] == ["call_o"]
        assert history[1]["content"][0]["text"] == "Primary(@primary)：fixed a.py"

    def test_an_unstamped_turn_stays_text_only(self, tmp_path):
        history = AgentInitializer._shared_history(
            self._tool_turn("", "fix a.py", "call_x", "fixed a.py"), "primary"
        )
        assert self._blocks(history, "tool_use") == []
        assert [m["content"][0]["text"] for m in history] == ["fix a.py", "fixed a.py"]

    def test_nothing_of_ours_reaches_the_model(self, tmp_path):
        for message in self._history(tmp_path, "primary"):
            assert set(message) == {"role", "content"}

    def test_the_reload_keeps_them_end_to_end(self, tmp_path, monkeypatch):
        from agent.memory import clear_conversation_store_cache, get_conversation_store
        from agent.registry import set_agent_registry
        from agent.workspace import session_prefs
        from config import conf

        bridge = _bridge(tmp_path)
        set_agent_registry(bridge.agent_registry)
        bridge.initializer = AgentInitializer(bridge=None, agent_bridge=bridge)
        monkeypatch.setitem(conf(), "conversation_persistence", True)
        monkeypatch.setattr(
            session_prefs,
            "get_prefs",
            lambda sid, aid: {"members": ["ops"]} if sid == "chat" else {},
        )
        clear_conversation_store_cache()

        stored = [
            {**{k: v for k, v in m.items() if k != "agent_id"}, "extras": {"agent_id": m["agent_id"]}}
            for m in [
                *self._tool_turn("primary", "fix a.py", "call_p", "fixed a.py"),
                *self._tool_turn("ops", "check a.py", "call_o", "a.py looks fine"),
            ]
        ]
        get_conversation_store(str(tmp_path / "primary")).append_messages("chat", stored)

        host = SimpleNamespace(
            agent_id="primary",
            workspace_dir=str(tmp_path / "primary"),
            messages=[],
            messages_lock=threading.RLock(),
        )
        bridge._sync_shared_transcript(host, "chat", "primary")
        assert [b["id"] for b in self._blocks(host.messages, "tool_use")] == ["call_p"]
        assert host.messages[-1]["content"][0]["text"] == "运营助手(@ops)：a.py looks fine"


class TestStripCopiedSpeakerPrefix:
    def test_bracket_and_colon_prefixes_are_removed(self, tmp_path):
        bridge = _bridge(tmp_path)
        labels = ["团队负责人", "开发", "default", "developer"]
        assert (
            bridge._strip_speaker_prefix("[团队负责人] 浓缩一版", labels)
            == "浓缩一版"
        )
        assert bridge._strip_speaker_prefix("开发：仓库在这", labels) == "仓库在这"
        assert (
            bridge._strip_speaker_prefix("团队负责人(@default)：浓缩一版", labels)
            == "浓缩一版"
        )
        assert bridge._strip_speaker_prefix("正常回复", labels) == "正常回复"


class TestReplayingWorkHandedToATeammate:
    """A hand-off is the one tool result worth replaying.

    Everything else a tool returned is already summarised in the reply, but a
    teammate's answer is somebody else's words. Dropped with the rest of the
    tool chain it reads, one turn later, as something the speaker knew by
    itself -- and an Agent that reads its own history that way starts
    answering in a teammate's place instead of handing the work over.
    """

    @staticmethod
    def _handoff(agent_id, said, call_id="call_1"):
        return [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "let me ask"},
                    {
                        "type": "tool_use",
                        "id": call_id,
                        "name": "agent_delegate",
                        "input": {"agent_id": agent_id},
                    },
                ],
                "agent_id": "default",
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "content": json.dumps(
                            {
                                "agent_id": agent_id,
                                "agent_name": "运营助手",
                                "status": "done",
                                "content": said,
                            }
                        ),
                    }
                ],
            },
        ]

    def _restored(self, messages):
        from bridge.agent_initializer import AgentInitializer

        return AgentInitializer._filter_text_only_messages(messages)

    def test_the_teammates_answer_comes_back_as_its_own_turn(self):
        restored = self._restored(
            [
                {"role": "user", "content": [{"type": "text", "text": "ask ops"}]},
                *self._handoff("ops", "shipped at noon"),
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "ops says noon"}],
                    "agent_id": "default",
                },
            ]
        )
        assert [(m["role"], m.get("agent_id")) for m in restored] == [
            ("user", None),
            ("assistant", "ops"),
            ("assistant", "default"),
        ]
        assert restored[1]["content"][0]["text"] == "shipped at noon"

    def test_the_speaker_still_owns_the_answer_it_wrote(self):
        """The relay is kept too: dropping it would lose the speaker's voice."""
        restored = self._restored(
            [
                {"role": "user", "content": [{"type": "text", "text": "ask ops"}]},
                *self._handoff("ops", "shipped at noon"),
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "ops says noon"}],
                    "agent_id": "default",
                },
            ]
        )
        assert restored[-1]["content"][0]["text"] == "ops says noon"

    def test_the_teammate_is_named_when_the_transcript_is_attributed(self, tmp_path):
        from agent.registry import set_agent_registry
        from bridge.agent_initializer import AgentInitializer

        set_agent_registry(_bridge(tmp_path).agent_registry)
        restored = self._restored(
            [
                {"role": "user", "content": [{"type": "text", "text": "ask ops"}]},
                *self._handoff("ops", "shipped at noon"),
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "ops says noon"}],
                    "agent_id": "default",
                },
            ]
        )
        spoke = AgentInitializer._attribute_history(restored, "default")[1]
        assert spoke["role"] == "user"
        assert spoke["content"][0]["text"] == "运营助手(@ops)：shipped at noon"

    def test_every_other_tool_result_is_still_discarded(self):
        restored = self._restored(
            [
                {"role": "user", "content": [{"type": "text", "text": "the weather?"}]},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_2",
                            "name": "web_search",
                            "input": {},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_2",
                            "content": json.dumps({"agent_id": "ops", "content": "raining"}),
                        }
                    ],
                },
                {"role": "assistant", "content": [{"type": "text", "text": "rain"}]},
            ]
        )
        assert [m["content"][0]["text"] for m in restored] == ["the weather?", "rain"]

    def test_a_hand_off_that_came_back_empty_says_nothing(self):
        restored = self._restored(
            [
                {"role": "user", "content": [{"type": "text", "text": "ask ops"}]},
                *self._handoff("ops", "   "),
                {"role": "assistant", "content": [{"type": "text", "text": "no word"}]},
            ]
        )
        assert [m["content"][0]["text"] for m in restored] == ["ask ops", "no word"]

    def test_a_long_report_is_trimmed_to_its_context_budget(self):
        from bridge.agent_initializer import _DELEGATED_REPLY_MAX_CHARS

        restored = self._restored(
            [
                {"role": "user", "content": [{"type": "text", "text": "ask ops"}]},
                *self._handoff("ops", "x" * (_DELEGATED_REPLY_MAX_CHARS + 500)),
                {"role": "assistant", "content": [{"type": "text", "text": "summary"}]},
            ]
        )
        said = restored[1]["content"][0]["text"]
        assert said == "x" * _DELEGATED_REPLY_MAX_CHARS + "…"

    def test_each_teammate_in_a_turn_keeps_its_own_voice(self):
        """Two hand-offs in one turn are two turns, in the order they happened."""
        restored = self._restored(
            [
                {"role": "user", "content": [{"type": "text", "text": "ask them both"}]},
                *self._handoff("ops", "ops here", call_id="call_a"),
                *self._handoff("dev", "dev here", call_id="call_b"),
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "both replied"}],
                    "agent_id": "default",
                },
            ]
        )
        assert [(m.get("agent_id"), m["content"][0]["text"]) for m in restored[1:]] == [
            ("ops", "ops here"),
            ("dev", "dev here"),
            ("default", "both replied"),
        ]


def test_transcript_keeps_the_address_the_model_was_spared():
    from agent.chat.service import ChatService

    sent = {"role": "user", "content": [{"type": "text", "text": "last week's GMV"}]}
    reply = {"role": "assistant", "content": [{"type": "text", "text": "GMV rose"}]}

    stored = ChatService._restore_verbatim_query(
        [sent, reply], "last week's GMV", "@analyst last week's GMV"
    )

    assert stored[0]["content"][0]["text"] == "@analyst last week's GMV"
    assert stored[1] is reply
    assert sent["content"][0]["text"] == "last week's GMV"


def test_a_pinned_registry_does_not_outlive_its_test(tmp_path, monkeypatch):
    """The classes above pin one, so the registry must follow configuration again.

    ``_bridge`` builds a two-Agent roster under the test's ``tmp_path``. A
    registry still pinned to a previous test's roster ignores every later
    ``agent_workspace`` -- so this check moves the configured workspace and
    insists the registry moves with it.
    """
    from config import conf

    before = get_agent_registry().get(require_enabled=False).workspace
    monkeypatch.setitem(conf(), "agent_workspace", str(tmp_path / "solo"))
    assert get_agent_registry().get(require_enabled=False).workspace != before
