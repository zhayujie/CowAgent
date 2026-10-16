"""Web todo event contract and executable vanilla frontend regression tests."""
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_todo_sse_forwards_only_snapshot_fields():
    from channel.web.core.channel import WebChannel

    cls = dict(zip(WebChannel.__code__.co_freevars,
                   (cell.cell_contents for cell in WebChannel.__closure__)))['cls']
    published = []
    channel = SimpleNamespace(sse_streams={'req': object()},
                              _publish_sse_event=lambda rid, event: published.append((rid, event)))
    callback = cls._make_sse_callback(channel, 'req')
    payload = dict(agent_id='a', session_id='s', run_id='r', tool_call_id='call',
                   version=4, todos=[], counts={'pending': 0}, explanation='clear',
                   private_internal='must not escape', type='wrong')
    callback({'type': 'todo_update', 'data': payload})
    assert published == [('req', {'type': 'todo_update', **{k: v for k, v in payload.items()
                           if k not in ('private_internal', 'type')}})]
    # The forwarding contract is JSON-compatible and preserves empty-array clears.
    assert json.loads(json.dumps(published[0][1]))['todos'] == []
    channel.sse_streams.clear()
    callback({'type': 'todo_update', 'data': payload})
    assert len(published) == 1


def test_vanilla_todo_runtime():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for vanilla frontend execution')
    result = subprocess.run([node, str(ROOT / 'tests/web_todo.test.cjs')],
                            capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_scroll_to_bottom_control_tracks_composer_and_has_accessible_label():
    from channel.web.core import template

    html = template.render('chat.html')
    css = (ROOT / 'channel/web/static/css/chat.css').read_text(encoding='utf-8')
    assert 'id="scroll-to-bottom-btn"' in html
    assert 'data-i18n-aria-label="chat_scroll_to_bottom"' in html
    assert html.index('id="scroll-to-bottom-btn"') < html.index('id="chat-composer"')
    assert 'bottom: calc(var(--chat-composer-height, 96px) + 12px)' in css
    assert '.chat-scroll-to-bottom.hidden' in css


def test_todo_loads_after_state_before_consumers():
    from channel.web.core import template
    html = template.render('chat.html')
    todo = html.index('/assets/js/chat/todo.js')
    assert html.index('/assets/js/chat/state.js') < todo
    for consumer in ('send.js', 'render.js', 'new-chat.js'):
        assert todo < html.index('/assets/js/chat/' + consumer)
    assert html.index('id="todo-panel"') < html.index('id="composer-card"')
