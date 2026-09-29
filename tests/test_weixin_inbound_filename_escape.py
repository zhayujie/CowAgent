"""A sender-chosen ``file_name`` must not steer the download out of the tmp dir.

``WeixinMessage`` writes inbound attachments to ``tmp_dir()/<file_name>``, where
``file_name`` comes straight out of the message payload. A name carrying ``../``
or an absolute path therefore made the CDN download land wherever the sender
asked, outside the workspace the app manages and cleans. ``qq_message`` and
``dingtalk_message`` already strip the name before joining; these cover the
weixin path and the shared guard it now goes through.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
from channel import chat_message
from channel.weixin import weixin_message as wxm
from common import state_dir

# Relative only: the unfixed code would otherwise write a real file into /tmp
# while the red run is failing.
HOSTILE_NAMES = ["../../outside.txt", "..\\..\\win.txt", "sub/dir/evil.txt", "../"]


@pytest.fixture
def agent_workspace(tmp_path):
    set_agent_registry(AgentRegistry([AgentProfile(id="w1", name="W", workspace=str(tmp_path))], "w1"))
    yield tmp_path
    # None, not the previous instance: an instance argument re-pins the
    # registry and would leak this workspace into the later tests.
    set_agent_registry(None)


def _file_msg(file_name):
    return {
        "message_id": "m-1",
        "from_user_id": "u-1",
        "to_user_id": "u-2",
        "item_list": [
            {
                "type": wxm.ITEM_FILE,
                "file_item": {
                    "file_name": file_name,
                    "media": {"encrypt_query_param": "q", "aes_key": "k"},
                },
            }
        ],
    }


@pytest.mark.parametrize("hostile", HOSTILE_NAMES)
def test_a_hostile_file_name_cannot_escape_the_tmp_dir(agent_workspace, hostile):
    written = []

    def fake_download(cdn_base_url, encrypt_param, aes_key, save_path):
        written.append(Path(save_path))
        Path(save_path).write_bytes(b"payload")

    msg = wxm.WeixinMessage(_file_msg(hostile))
    with patch.object(wxm, "download_media_from_cdn", side_effect=fake_download):
        msg.prepare()

    tmp_root = state_dir.tmp_dir().resolve()
    assert written, "the download must still run"
    assert written[0].resolve().parent == tmp_root
    assert Path(msg.content).resolve().parent == tmp_root
    assert written[0].read_bytes() == b"payload"


def test_an_absolute_file_name_is_reduced_to_its_basename(agent_workspace):
    msg = wxm.WeixinMessage(_file_msg("/etc/passwd"))

    assert Path(msg.content).resolve().parent == state_dir.tmp_dir().resolve()


@pytest.mark.parametrize("raw,expected", [("", ""), ("..", ""), ("/", ""), ("a.txt", "a.txt")])
def test_the_shared_guard_is_total(raw, expected):
    assert chat_message.safe_filename(raw) == expected
