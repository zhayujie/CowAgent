# encoding:utf-8
"""An empty deepseek_api_base means DeepSeek's own endpoint, not the OpenAI one."""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.deepseek import deepseek_bot


def _base(**values):
    cfg = MagicMock()
    cfg.get = MagicMock(side_effect=lambda key, default=None: values.get(key, default))
    with patch.object(deepseek_bot, "conf", return_value=cfg), \
            patch.object(deepseek_bot, "SessionManager"):
        return deepseek_bot.DeepSeekBot().api_base


@pytest.mark.parametrize("values,expected", [
    # An empty base, even with an OpenAI base set.
    ({"deepseek_api_key": "k", "deepseek_api_base": "", "open_ai_api_base": "https://api.openai.com/v1"},
     deepseek_bot.DEFAULT_API_BASE),
    ({"deepseek_api_key": "k", "deepseek_api_base": "https://proxy.example.com/v1/"},
     "https://proxy.example.com/v1"),
    # Old setups that point the OpenAI fields at DeepSeek.
    ({"open_ai_api_key": "k", "open_ai_api_base": "https://api.deepseek.com/v1"},
     "https://api.deepseek.com/v1"),
])
def test_api_base(values, expected):
    assert _base(**values) == expected
