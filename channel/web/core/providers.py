"""Vendor catalogue for the model and settings views.

Mostly data: the provider ids, their config keys, the base-URL placeholders
shown in the form, and the recommended model list. It sat as a class attribute
on ``ConfigHandler``, but three places read it -- that handler serves it,
``ModelsHandler`` builds its capability cards from it, and ``WebChannel``
resolves provider labels through it -- so two of them had to reach across into
a handler to get at it.

The few functions at the bottom read a provider's configured values. They are
here for the same reason, and because they were the last thing tying the two
handlers to each other.
"""

from collections import OrderedDict

from common import const


_RECOMMENDED_MODELS = [
    const.DEEPSEEK_FLASH, const.DEEPSEEK_V4_FLASH, const.DEEPSEEK_V4_PRO,
    const.MINIMAX_M3, const.MINIMAX_M2_7_HIGHSPEED, const.MINIMAX_M2_7,
    # claude-opus-5-5 is the Claude default; claude-opus-5 / claude-sonnet-5 / claude-fable-5 follow right after it.
    const.CLAUDE_OPUS_5_5, const.CLAUDE_OPUS_5, const.CLAUDE_SONNET_5, const.CLAUDE_FABLE_5_1, const.CLAUDE_FABLE_5, const.CLAUDE_4_8_OPUS, const.CLAUDE_4_7_OPUS, const.CLAUDE_4_6_SONNET, const.CLAUDE_4_6_OPUS,
    const.GPT_61_SOL, const.GPT_6_LUNA, const.GPT_6_SOL, const.GPT_6_ASTRA, const.GPT_56_LUNA, const.GPT_56_TERRA, const.GPT_56_SOL, const.GPT_55, const.GPT_54, const.GPT_54_MINI, const.GPT_54_NANO, const.GPT_5, const.GPT_41, const.GPT_4o,
    const.GEMINI_38_FLASH, const.GEMINI_37_FLASH, const.GEMINI_36_FLASH, const.GEMINI_35_FLASH, const.GEMINI_31_FLASH_LITE_PRE, const.GEMINI_31_PRO_PRE, const.GEMINI_3_FLASH_PRE,
    const.GLM_5_3_FLASH, const.GLM_5_3, const.GLM_5_2, const.GLM_5_1, const.GLM_5_TURBO, const.GLM_5, const.GLM_4_7,
    const.QWEN38_FLASH, const.QWEN38_MAX, const.QWEN37_PLUS, const.QWEN37_MAX, const.QWEN36_PLUS,
    const.DOUBAO_SEED_2_1_PRO, const.DOUBAO_SEED_2_1_TURBO, const.DOUBAO_SEED_2_CODE,
    const.KIMI_K3, const.KIMI_K2_7_CODE, const.KIMI_K2_7_CODE_HIGHSPEED, const.KIMI_K2_6, const.KIMI_K2_5, const.KIMI_K2,
    const.ERNIE_5_1, const.ERNIE_5, const.ERNIE_X1_1, const.ERNIE_45_TURBO_128K, const.ERNIE_45_TURBO_32K,
    const.MIMO_V2_5_PRO, const.MIMO_V2_5,
]

# Generic placeholder hints surfaced in the web console. We deliberately
# show the version-path tail (e.g. "/v1") so users are reminded to type
# the full base URL. The form is intentionally vague (`...../v1`) so it
# never looks like a real default a user might paste verbatim — and we
# never auto-rewrite anything on the server side.
_PLACEHOLDER_V1 = "https://...../v1"
_PLACEHOLDER_QIANFAN = "https://...../v2"
_PLACEHOLDER_ZHIPU = "https://...../api/paas/v4"
_PLACEHOLDER_DOUBAO = "https://...../api/v3"
_PLACEHOLDER_GEMINI = "https://....."

PROVIDER_MODELS = OrderedDict([
    ("deepseek", {
        "label": "DeepSeek",
        "api_key_field": "deepseek_api_key",
        "api_base_key": "deepseek_api_base",
        "api_base_default": "https://api.deepseek.com/v1",
        "api_base_placeholder": _PLACEHOLDER_V1,
        "models": [const.DEEPSEEK_FLASH, const.DEEPSEEK_V4_FLASH, const.DEEPSEEK_V4_PRO],
    }),
    ("claudeAPI", {
        "label": "Claude",
        "api_key_field": "claude_api_key",
        "api_base_key": "claude_api_base",
        "api_base_default": "https://api.anthropic.com/v1",
        "api_base_placeholder": _PLACEHOLDER_V1,
        "models": [const.CLAUDE_OPUS_5_5, const.CLAUDE_OPUS_5, const.CLAUDE_SONNET_5, const.CLAUDE_FABLE_5_1, const.CLAUDE_FABLE_5, const.CLAUDE_4_8_OPUS, const.CLAUDE_4_7_OPUS, const.CLAUDE_4_6_SONNET, const.CLAUDE_4_6_OPUS],
    }),
    ("openai", {
        "label": "OpenAI",
        "api_key_field": "open_ai_api_key",
        "api_base_key": "open_ai_api_base",
        "api_base_default": "https://api.openai.com/v1",
        "api_base_placeholder": _PLACEHOLDER_V1,
        "models": [const.GPT_61_SOL, const.GPT_6_LUNA, const.GPT_6_SOL, const.GPT_6_ASTRA, const.GPT_56_LUNA, const.GPT_56_TERRA, const.GPT_56_SOL, const.GPT_55, const.GPT_54, const.GPT_54_MINI, const.GPT_54_NANO, const.GPT_5, const.GPT_41, const.GPT_4o],
    }),
    ("gemini", {
        "label": "Gemini",
        "api_key_field": "gemini_api_key",
        "api_base_key": "gemini_api_base",
        "api_base_default": "https://generativelanguage.googleapis.com",
        "api_base_placeholder": _PLACEHOLDER_GEMINI,
        "models": [const.GEMINI_38_FLASH, const.GEMINI_37_FLASH, const.GEMINI_36_FLASH, const.GEMINI_35_FLASH, const.GEMINI_31_FLASH_LITE_PRE, const.GEMINI_31_PRO_PRE, const.GEMINI_3_FLASH_PRE],
    }),
    ("minimax", {
        "label": "MiniMax",
        "api_key_field": "minimax_api_key",
        "api_base_key": None,
        "api_base_default": None,
        "api_base_placeholder": "",
        "models": [const.MINIMAX_M3, const.MINIMAX_M2_7, const.MINIMAX_M2_7_HIGHSPEED],
    }),
    ("zhipu", {
        "label": {"zh": "智谱AI", "en": "GLM"},
        "api_key_field": "zhipu_ai_api_key",
        "api_base_key": "zhipu_ai_api_base",
        "api_base_default": "https://open.bigmodel.cn/api/paas/v4",
        "api_base_placeholder": _PLACEHOLDER_ZHIPU,
        "models": [const.GLM_5_3_FLASH, const.GLM_5_3, const.GLM_5_2, const.GLM_5_1, const.GLM_5_TURBO, const.GLM_5, const.GLM_4_7],
    }),
    ("dashscope", {
        "label": {"zh": "通义千问", "en": "Qwen"},
        "api_key_field": "dashscope_api_key",
        "api_base_key": None,
        "api_base_default": None,
        "api_base_placeholder": "",
        "models": [const.QWEN38_FLASH, const.QWEN38_MAX, const.QWEN37_PLUS, const.QWEN37_MAX, const.QWEN36_PLUS],
    }),
    ("moonshot", {
        "label": "Kimi",
        "api_key_field": "moonshot_api_key",
        "api_base_key": "moonshot_base_url",
        "api_base_default": "https://api.moonshot.cn/v1",
        "api_base_placeholder": _PLACEHOLDER_V1,
        "models": [const.KIMI_K3, const.KIMI_K2_7_CODE, const.KIMI_K2_7_CODE_HIGHSPEED, const.KIMI_K2_6, const.KIMI_K2_5, const.KIMI_K2],
    }),
    ("doubao", {
        "label": {"zh": "豆包", "en": "Doubao"},
        "api_key_field": "ark_api_key",
        "api_base_key": "ark_base_url",
        "api_base_default": "https://ark.cn-beijing.volces.com/api/v3",
        "api_base_placeholder": _PLACEHOLDER_DOUBAO,
        "models": [const.DOUBAO_SEED_2_1_PRO, const.DOUBAO_SEED_2_1_TURBO, const.DOUBAO_SEED_2_PRO, const.DOUBAO_SEED_2_CODE],
    }),
    ("qianfan", {
        "label": {"zh": "百度", "en": "ERNIE"},
        "api_key_field": "qianfan_api_key",
        "api_base_key": "qianfan_api_base",
        "api_base_default": "https://qianfan.baidubce.com/v2",
        "api_base_placeholder": _PLACEHOLDER_QIANFAN,
        "models": [const.ERNIE_5_1, const.ERNIE_5, const.ERNIE_X1_1, const.ERNIE_45_TURBO_128K, const.ERNIE_45_TURBO_32K],
    }),
    ("mimo", {
        "label": {"zh": "小米 MiMo", "en": "MiMo"},
        "api_key_field": "mimo_api_key",
        "api_base_key": "mimo_api_base",
        "api_base_default": "https://api.xiaomimimo.com/v1",
        "api_base_placeholder": _PLACEHOLDER_V1,
        "models": [const.MIMO_V2_5_PRO, const.MIMO_V2_5],
    }),
    ("linkai", {
        "label": "LinkAI",
        "api_key_field": "linkai_api_key",
        "api_base_key": None,
        "api_base_default": None,
        "api_base_placeholder": "",
        "models": _RECOMMENDED_MODELS,
    }),
    ("custom", {
        "label": {"zh": "自定义", "en": "Custom"},
        "api_key_field": "custom_api_key",
        "api_base_key": "custom_api_base",
        "api_base_default": "",
        "api_base_placeholder": _PLACEHOLDER_V1,
        "models": [],
    }),
])


# Three helpers that read a provider's config values. They were static methods
# split across ConfigHandler and ModelsHandler, and each handler needed one
# from the other, which is a cycle the moment the two live in separate
# modules. They are about the catalogue above, so they belong here.

def is_real_key(value: str) -> bool:
    """False for an unset key and for the placeholders the form ships with."""
    return bool(value) and value not in ("", "YOUR API KEY", "YOUR_API_KEY")


def mask_key(value: str) -> str:
    """Mask the middle part of an API key for display."""
    if not value or len(value) <= 8:
        return value
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


def legacy_custom_in_use(local_config: dict) -> bool:
    """True when the flat single-provider custom config is still relevant:
    either it is the active bot_type, or its key/base fields are filled.
    In that case the legacy "custom" card must stay visible even when
    multi ``custom_providers`` entries exist."""
    if (local_config.get("bot_type") or "") == "custom":
        return True
    return (is_real_key(local_config.get("custom_api_key") or "")
            or bool(local_config.get("custom_api_base")))
