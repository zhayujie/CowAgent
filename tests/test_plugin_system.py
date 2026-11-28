# encoding:utf-8
"""Plugin system: manifests, lifecycle, guarded hooks and the kernel call sites."""

import textwrap
import time

import pytest

import agent.plugin as plugin_api
from agent.plugin import host as host_mod
from agent.plugin.admin import register_admin_command
from agent.plugin.host import PluginHost
from agent.plugin.manifest import ManifestError, load_manifest


def write_plugin(root, plugin_id, code, manifest=None):
    d = root / plugin_id
    d.mkdir(parents=True)
    (d / "plugin.yaml").write_text(manifest or f"id: {plugin_id}\nversion: 0.1.0\n", encoding="utf-8")
    (d / "__init__.py").write_text(textwrap.dedent(code), encoding="utf-8")
    return d


@pytest.fixture
def host(tmp_path, monkeypatch):
    h = PluginHost(
        builtin_dir=tmp_path / "builtin",
        user_dir=tmp_path / "user",
        state_file=tmp_path / "plugins.json",
    )
    register_admin_command(h)
    h.loaded = True
    monkeypatch.setattr(plugin_api, "_host", h)
    yield h
    h._pool.shutdown(wait=False)


@pytest.fixture
def user_dir(host):
    host.user_dir.mkdir(parents=True, exist_ok=True)
    return host.user_dir


ECHO_TOOL = """
from agent.tools.base_tool import BaseTool, ToolResult

class EchoTool(BaseTool):
    name = "plugin_echo"
    description = "echo"
    params = {"type": "object", "properties": {}}

    def execute(self, args):
        return ToolResult.success("echo")

def apply(ctx):
    ctx.tool(EchoTool)
    ctx.command("hello", lambda args, ev: f"hello {args}")
"""


# -- manifest -----------------------------------------------------------------

def test_manifest_defaults_and_config(tmp_path):
    d = tmp_path / "My-Plugin"
    d.mkdir()
    (d / "plugin.yaml").write_text(
        "name: Demo\npermissions: [network, fs.write]\nconfig:\n  token: ''\n  limit: {default: 3}\n",
        encoding="utf-8",
    )
    m = load_manifest(d)
    assert m.id == "my-plugin"
    assert m.title == "Demo"
    assert m.writes is True
    assert m.config_defaults() == {"token": "", "limit": 3}


def test_manifest_rejects_bad_id(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    (d / "plugin.json").write_text('{"id": "Bad Id!"}', encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(d)


# -- lifecycle ----------------------------------------------------------------

def test_enable_registers_and_disable_revokes(host, user_dir):
    write_plugin(user_dir, "echo", ECHO_TOOL)
    host.discover()
    ok, err = host.enable("echo")
    assert ok, err
    assert "plugin_echo" in host.tools
    assert [t.name for t in plugin_api.plugin_tools()] == ["plugin_echo"]
    assert plugin_api.dispatch_command("/hello world") == "hello world"

    host.disable("echo")
    assert host.tools == {}
    assert plugin_api.plugin_tools() == []
    assert plugin_api.dispatch_command("/hello world") is None


def test_enabled_state_survives_restart(host, user_dir, tmp_path):
    write_plugin(user_dir, "echo", ECHO_TOOL)
    host.discover()
    host.enable("echo")

    fresh = PluginHost(builtin_dir=host.builtin_dir, user_dir=user_dir, state_file=host.state_path)
    fresh.load_all()
    assert fresh.records["echo"].enabled
    assert "plugin_echo" in fresh.tools
    fresh._pool.shutdown(wait=False)


def test_failed_apply_leaves_nothing_behind(host, user_dir):
    write_plugin(user_dir, "broken", """
        def apply(ctx):
            ctx.command("half", lambda a, e: "x")
            raise RuntimeError("boom")
    """)
    host.discover()
    ok, err = host.enable("broken")
    assert not ok and "boom" in err
    assert "half" not in host.commands
    assert host.records["broken"].error


def test_conflicts_are_refused(host, user_dir):
    write_plugin(user_dir, "a", ECHO_TOOL)
    write_plugin(user_dir, "b", ECHO_TOOL)
    write_plugin(user_dir, "shadow", """
        def apply(ctx):
            ctx.command("help", lambda a, e: "mine")
    """)
    write_plugin(user_dir, "readtool", """
        from agent.tools.base_tool import BaseTool
        class T(BaseTool):
            name = "read"
        def apply(ctx):
            ctx.tool(T)
    """)
    host.discover()
    assert host.enable("a")[0]
    ok, err = host.enable("b")
    assert not ok and "already provided" in err
    assert not host.enable("shadow")[0]
    assert not host.enable("readtool")[0]
    assert host.tool_owner["plugin_echo"] == "a"


def test_modify_hook_needs_permission(host, user_dir):
    write_plugin(user_dir, "sneaky", """
        def apply(ctx):
            ctx.on("message.in", lambda ev: None, modify=True)
    """)
    host.discover()
    ok, err = host.enable("sneaky")
    assert not ok and "hook.modify" in err


def test_builtin_default_and_user_shadowing(host, user_dir):
    write_plugin(host.builtin_dir, "core", "def apply(ctx):\n    pass\n",
                 manifest="id: core\ndefault_enabled: true\n")
    host.load_all()
    assert host.records["core"].enabled and host.records["core"].builtin

    write_plugin(user_dir, "core", "def apply(ctx):\n    pass\n")
    host.discover()
    assert not host.records["core"].builtin


# -- guarded execution --------------------------------------------------------

def test_message_hook_rewrites_and_answers(host, user_dir):
    write_plugin(user_dir, "filter", """
        def apply(ctx):
            @ctx.on("message.in", modify=True)
            def rewrite(ev):
                if ev.text == "ping":
                    ev.reply = "pong"
                else:
                    ev.text = ev.text.upper()
    """, manifest="id: filter\npermissions: [hook.modify]\n")
    host.discover()
    assert host.enable("filter")[0]
    assert plugin_api.on_message("hi") == {"text": "HI", "reply": None}
    assert plugin_api.on_message("ping")["reply"] == "pong"


def test_hook_failures_trip_the_breaker(host, user_dir):
    write_plugin(user_dir, "flaky", """
        def apply(ctx):
            @ctx.on("message.in", modify=True)
            def bad(ev):
                raise ValueError("nope")
    """, manifest="id: flaky\npermissions: [hook.modify]\n")
    host.discover()
    host.enable("flaky")
    for _ in range(host_mod.FAILURE_LIMIT):
        assert plugin_api.on_message("hi")["text"] == "hi"
    assert not host.records["flaky"].enabled
    assert "consecutive failures" in host.records["flaky"].error
    assert host.hooks == {}


def test_slow_hook_is_abandoned(host, user_dir, monkeypatch):
    monkeypatch.setattr(host_mod, "HOOK_TIMEOUT", 0.2)
    write_plugin(user_dir, "slow", """
        import time
        def apply(ctx):
            @ctx.on("message.in", modify=True)
            def slow(ev):
                time.sleep(2)
                ev.text = "late"
    """, manifest="id: slow\npermissions: [hook.modify]\n")
    host.discover()
    host.enable("slow")
    # call() reads the timeout from its default; patch it on the bound method.
    original = host.call
    monkeypatch.setattr(host, "call", lambda pid, fn, *a, timeout=0.2: original(pid, fn, *a, timeout=timeout))
    start = time.monotonic()
    assert plugin_api.on_message("hi")["text"] == "hi"
    assert time.monotonic() - start < 1.5


def test_tool_after_marks_modified_result(host, user_dir):
    write_plugin(user_dir, "redact", """
        def apply(ctx):
            @ctx.on("tool.after", modify=True)
            def redact(ev):
                ev.result = ev.result.replace("secret", "***")
    """, manifest="id: redact\npermissions: [hook.modify]\n")
    host.discover()
    host.enable("redact")
    out = plugin_api.after_tool("read", {}, "a secret b")
    assert out.startswith("a *** b")
    assert "plugin redact modified" in out
    assert plugin_api.after_tool("read", {}, "plain") == "plain"


def test_prompt_sections_are_labeled_and_capped(host, user_dir):
    write_plugin(user_dir, "notes", """
        def apply(ctx):
            ctx.on("prompt.build", lambda ev: ("Team notes", "x" * 2000))
    """)
    host.discover()
    host.enable("notes")
    lines = plugin_api.prompt_sections(language="en")
    assert lines[0] == "## Team notes (plugin: notes)"
    assert len(lines[2]) == plugin_api.SECTION_LIMIT


def test_turn_end_runs_in_background(host, user_dir):
    write_plugin(user_dir, "audit", """
        seen = []
        def apply(ctx):
            ctx.on("turn.end", lambda ev: seen.append(ev.final_response))
    """)
    host.discover()
    host.enable("audit")
    plugin_api.turn_end(final_response="done", cancelled=False)
    import sys
    seen = sys.modules["cow_plugins.audit"].seen
    for _ in range(50):
        if seen:
            break
        time.sleep(0.02)
    assert seen == ["done"]


# -- slots consumed by other modules ------------------------------------------

def test_tool_writes_follows_permissions(host, user_dir):
    write_plugin(user_dir, "echo", ECHO_TOOL, manifest="id: echo\npermissions: [network]\n")
    host.discover()
    host.enable("echo")
    assert plugin_api.tool_writes("plugin_echo") is False
    assert plugin_api.tool_writes("unknown_tool") is None

    from agent.permission.policy import _check_read_only
    assert _check_read_only("plugin_echo", {}, None).allowed

    host.disable("echo")
    (user_dir / "echo" / "plugin.yaml").write_text("id: echo\npermissions: [shell]\n", encoding="utf-8")
    host.discover()
    host.enable("echo")
    assert plugin_api.tool_writes("plugin_echo") is True
    assert not _check_read_only("plugin_echo", {}, None).allowed


def test_mcp_servers_and_revision(host, user_dir):
    write_plugin(user_dir, "srv", """
        def apply(ctx):
            ctx.mcp("demo", {"command": "demo-mcp"})
    """)
    host.discover()
    assert plugin_api.mcp_revision() == 0
    host.enable("srv")
    assert plugin_api.mcp_servers() == [{"name": "demo", "command": "demo-mcp", "type": "stdio"}]
    first = plugin_api.mcp_revision()
    assert first > 0

    from agent.tools.tool_manager import ToolManager
    merged = ToolManager._with_plugin_mcp([{"name": "demo", "command": "mine"}])
    assert merged == [{"name": "demo", "command": "mine"}]

    host.disable("srv")
    assert plugin_api.mcp_servers() == [] and plugin_api.mcp_revision() == 0


def test_plugin_skills_do_not_override(host, user_dir, tmp_path):
    d = write_plugin(user_dir, "skilled", """
        def apply(ctx):
            ctx.skills()
    """)
    for name in ("plugin-only", "shared"):
        sd = d / "skills" / name
        sd.mkdir(parents=True)
        (sd / "SKILL.md").write_text(f"---\nname: {name}\ndescription: from plugin\n---\nbody\n", encoding="utf-8")
    custom = tmp_path / "custom"
    (custom / "shared").mkdir(parents=True)
    (custom / "shared" / "SKILL.md").write_text("---\nname: shared\ndescription: mine\n---\nbody\n", encoding="utf-8")
    host.discover()
    host.enable("skilled")

    from agent.skills.manager import SkillManager
    mgr = SkillManager(builtin_dir=str(tmp_path / "none"), custom_dir=str(custom))
    assert mgr.skills["plugin-only"].skill.source == "plugin"
    assert mgr.skills["shared"].skill.description == "mine"


def test_channel_and_provider_fallbacks(host, user_dir):
    write_plugin(user_dir, "ext", """
        class FakeChannel:
            pass
        class FakeBot:
            pass
        def apply(ctx):
            ctx.channel("fakechan", FakeChannel)
            ctx.provider("fakebot", FakeBot)
    """)
    host.discover()
    host.enable("ext")
    from channel.channel_factory import _build_channel
    from models.bot_factory import create_bot
    ch = _build_channel("fakechan", False)
    assert type(ch).__name__ == "FakeChannel" and ch.channel_type == "fakechan"
    assert type(create_bot("fakebot")).__name__ == "FakeBot"
    host.disable("ext")
    with pytest.raises(RuntimeError):
        _build_channel("fakechan", False)


# -- /plugin and install -------------------------------------------------------

def test_install_enable_remove_via_command(host, tmp_path):
    src = write_plugin(tmp_path / "src", "echo", ECHO_TOOL)
    out = plugin_api.dispatch_command(f"/plugin install {src}", channel_type="web")
    assert "Installed 'echo' (off)" in out
    assert not host.records["echo"].enabled

    assert "Enabled" in plugin_api.dispatch_command("/plugin enable echo", channel_type="web")
    assert "[on] echo" in plugin_api.dispatch_command("/plugin list", channel_type="web")
    assert "already installed" in plugin_api.dispatch_command(f"/plugin install {src}", channel_type="web")

    assert "Removed" in plugin_api.dispatch_command("/plugin remove echo", channel_type="web")
    assert not (host.user_dir / "echo").exists()
    assert "echo" not in host.records


def test_management_refused_outside_owner_consoles(host, tmp_path):
    src = write_plugin(tmp_path / "src", "echo", ECHO_TOOL)
    out = plugin_api.dispatch_command(f"/plugin install {src}", channel_type="wechatcom_app")
    assert "can only be managed" in out
    out = plugin_api.dispatch_command(f"/plugin install {src}", channel_type="web", is_group=True)
    assert "can only be managed" in out
    assert "No plugins installed" in plugin_api.dispatch_command("/plugin list", channel_type="feishu")


# -- channel entry ------------------------------------------------------------

def test_chat_channel_answers_plugin_command_and_rewrites_text(host, user_dir, monkeypatch):
    from bridge.context import Context, ContextType
    from bridge.reply import ReplyType
    from channel import chat_channel as mod

    class PassThrough:
        def emit_event(self, e_context):
            return e_context

    write_plugin(user_dir, "mix", """
        def apply(ctx):
            ctx.command("hello", lambda args, ev: f"hello from {ev.channel_type}")
            @ctx.on("message.in", modify=True)
            def tag(ev):
                ev.text = ev.text + " [tagged]"
    """, manifest="id: mix\npermissions: [hook.modify]\n")
    host.discover()
    host.enable("mix")

    monkeypatch.setattr(mod, "PluginManager", PassThrough)
    seen = []
    monkeypatch.setattr(mod.Channel, "build_reply_content",
                        lambda self, query, context=None: seen.append(query))
    ch = mod.ChatChannel.__new__(mod.ChatChannel)
    ch.channel_type = "web"

    reply = ch._generate_reply(Context(ContextType.TEXT, "/hello", kwargs={}))
    assert reply.type == ReplyType.TEXT and reply.content == "hello from web"

    ctx = Context(ContextType.TEXT, "hi", kwargs={})
    ch._generate_reply(ctx)
    assert ctx.content == "hi [tagged]"
    assert seen == ["hi [tagged]"]


# -- nothing changes without plugins --------------------------------------------

def test_call_sites_are_noops_before_loading(monkeypatch):
    monkeypatch.setattr(plugin_api, "_host", None)
    assert plugin_api.on_message("/plugin list") == {"text": "/plugin list", "reply": None}
    assert plugin_api.dispatch_command("/help") is None
    reply = object()
    assert plugin_api.render_reply(reply) is reply
    assert plugin_api.after_tool("read", {}, "x") == "x"
    assert plugin_api.prompt_sections() == []
    assert plugin_api.plugin_tools() == []
    assert plugin_api.tool_writes("anything") is None
    assert plugin_api.mcp_servers() == [] and plugin_api.mcp_revision() == 0
    assert plugin_api.channel_factory("x") is None
    plugin_api.turn_end(final_response="x")
