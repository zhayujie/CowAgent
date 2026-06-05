# encoding:utf-8

import copy
import json
import logging
import os
import pickle

from common.log import logger
from common import i18n

# All available config keys are listed in this dict (use lowercase keys).
# The values here are placeholders only; the program does NOT read them.
# They merely document the expected format — put real values in config.json.
available_setting = {
    # global UI language for CLI, startup logs, error messages, agent prompts
    # and channel replies. Options: "auto" (detect from system locale, default),
    # "zh" (Chinese) or "en" (English). An explicit value locks the language.
    # value: auto/en/zh
    "cow_lang": "auto",
    # openai api config
    "open_ai_api_key": "",  # openai api key
    # openai api base; when use_azure_chatgpt is true, set the matching api base
    "open_ai_api_base": "https://api.openai.com/v1",
    "claude_api_base": "https://api.anthropic.com/v1",  # claude api base
    "gemini_api_base": "https://generativelanguage.googleapis.com",  # gemini api base
    "custom_api_key": "",  # custom OpenAI-compatible provider api key (used when bot_type is "custom")
    "custom_api_base": "",  # custom OpenAI-compatible provider api base (used when bot_type is "custom")
    "proxy": "",  # proxy used by openai
    # chatgpt model; when use_azure_chatgpt is true, this is the Azure model deployment name
    "model": "gpt-3.5-turbo",  # options: gpt-4o, gpt-4o-mini, gpt-4-turbo, claude-3-sonnet, wenxin, moonshot, qwen-turbo, xunfei, glm-4, minimax, gemini, etc. See common/const.py for the full list
    "bot_type": "",  # optional; for OpenAI-compatible third-party services set "openai" or "custom" (in custom mode switching model won't auto-switch bot_type). See common/const.py for bot names; inferred from model name if left empty
    "use_azure_chatgpt": False,  # whether to use Azure chatgpt
    "azure_deployment_id": "",  # azure model deployment name
    "azure_api_version": "",  # azure api version
    # Bot trigger config
    "single_chat_prefix": ["bot", "@bot"],  # text must contain this prefix to trigger a reply in single chat
    "single_chat_reply_prefix": "[bot] ",  # auto-reply prefix in single chat, used to distinguish from a real person
    "single_chat_reply_suffix": "",  # auto-reply suffix in single chat; \n inserts a line break
    "group_chat_prefix": ["@bot"],  # messages containing this prefix trigger a reply in group chat
    "no_need_at": False,  # whether replying in group chat does not require an @mention
    "group_chat_reply_prefix": "",  # auto-reply prefix in group chat
    "group_chat_reply_suffix": "",  # auto-reply suffix in group chat; \n inserts a line break
    "group_chat_keyword": [],  # messages containing this keyword trigger a reply in group chat
    "group_at_off": False,  # whether to disable @bot triggering in group chat
    "group_name_white_list": ["group1", "group2"],  # group names where auto-reply is enabled
    "group_name_keyword_white_list": [],  # group-name keywords where auto-reply is enabled
    "group_chat_in_one_session": ["group1"],  # group names that share conversation context
    "group_shared_session": False,  # whether group chat shares conversation context (all members share). When False each user has an independent session in the group
    "nick_name_black_list": [],  # user nickname blacklist
    "group_welcome_msg": "",  # fixed welcome message for new group members; uses a random style when empty
    "trigger_by_self": False,  # whether the bot can be triggered by itself
    "text_to_image": "dall-e-2",  # image generation model, options: dall-e-2, dall-e-3
    # Azure OpenAI dall-e-3 config
    "dalle3_image_style": "vivid", # dalle3 image style, options: vivid, natural
    "dalle3_image_quality": "hd", # dalle3 image quality, options: standard, hd
    # Azure OpenAI DALL-E API config; when use_azure_chatgpt is true, separates the text-reply resource from the DALL-E resource
    "azure_openai_dalle_api_base": "", # [optional] azure openai endpoint for image replies; defaults to open_ai_api_base
    "azure_openai_dalle_api_key": "", # [optional] azure openai key for image replies; defaults to open_ai_api_key
    "azure_openai_dalle_deployment_id":"", # [optional] azure openai deployment id for image replies; defaults to text_to_image
    "image_proxy": True,  # whether an image proxy is needed; required when accessing LinkAI from mainland China
    "image_create_prefix": ["画", "看", "找"],  # prefixes that enable image replies
    "concurrency_in_session": 1,  # max number of in-flight messages per session; values >1 may cause out-of-order replies
    "image_create_size": "256x256",  # image size, options: 256x256, 512x512, 1024x1024 (dall-e-3 defaults to 1024x1024)
    "group_chat_exit_group": False,
    # chatgpt session params
    "expires_in_seconds": 3600,  # idle session expiry time
    # persona description (only used in chat mode)
    "character_desc": "You are a helpful AI assistant. You aim to answer and solve any questions people have, and can communicate in multiple languages.",
    "conversation_max_tokens": 1000,  # max characters of context memory
    # chatgpt rate limit config
    "rate_limit_chatgpt": 20,  # chatgpt call rate limit
    "rate_limit_dalle": 50,  # openai dalle call rate limit
    # chatgpt api params, see https://platform.openai.com/docs/api-reference/chat/create
    "temperature": 0.9,
    "top_p": 1,
    "frequency_penalty": 0,
    "presence_penalty": 0,
    "request_timeout": 180,  # chatgpt request timeout; the openai api defaults to 600, hard questions usually need longer
    "timeout": 120,  # chatgpt retry timeout; will auto-retry within this window
    # Baidu Wenxin (ERNIE) params
    "baidu_wenxin_model": "eb-instant",  # defaults to the ERNIE-Bot-turbo model
    "baidu_wenxin_api_key": "",  # Baidu api key
    "baidu_wenxin_secret_key": "",  # Baidu secret key
    "baidu_wenxin_prompt_enabled": False,  # Enable prompt if you are using ernie character model
    # Baidu Qianfan / ERNIE OpenAI-compatible API
    "qianfan_api_key": "",  # Baidu Qianfan API key in bce-v3 format
    "qianfan_api_base": "https://qianfan.baidubce.com/v2",  # Qianfan OpenAI-compatible API base
    # Xunfei Spark API
    "xunfei_app_id": "",  # Xunfei app id
    "xunfei_api_key": "",  # Xunfei API key
    "xunfei_api_secret": "",  # Xunfei API secret
    "xunfei_domain": "",  # Xunfei model domain param; for Spark4.0 Ultra it is 4.0Ultra, see https://www.xfyun.cn/doc/spark/Web.html for others
    "xunfei_spark_url": "",  # Xunfei model request url; for Spark4.0 Ultra it is wss://spark-api.xf-yun.com/v4.0/chat, see https://www.xfyun.cn/doc/spark/Web.html for others
    # claude config
    "claude_api_cookie": "",
    "claude_uuid": "",
    # claude api key
    "claude_api_key": "",
    # Tongyi Qianwen API, see https://help.aliyun.com/document_detail/2587494.html for how to obtain
    "qwen_access_key_id": "",
    "qwen_access_key_secret": "",
    "qwen_agent_key": "",
    "qwen_app_id": "",
    "qwen_node_id": "",  # id used by workflow-orchestration models; keep it an empty string if qwen_node_id is unused
    # Alibaba Lingji (Tongyi new sdk) model api key
    "dashscope_api_key": "",
    # Google Gemini Api Key
    "gemini_api_key": "",
    # Embedding model config
    "embedding_provider": "",  # explicitly set the provider: openai / linkai / dashscope / doubao / zhipu (aligned with bot_type naming)
    "embedding_model": "",     # leave empty to use the provider's default model
    "embedding_dimensions": 0, # leave empty/0 to use the provider's default dimension (1024 recommended for consistency)
    # voice config
    "speech_recognition": True,  # whether to enable speech recognition
    "group_speech_recognition": False,  # whether to enable group speech recognition
    "voice_reply_voice": False,  # whether to reply to voice with voice; requires the matching TTS engine api key
    "always_reply_voice": False,  # whether to always reply with voice
    "voice_to_text": "openai",  # speech recognition engine: openai,baidu,google,azure,xunfei,ali
    "text_to_voice": "openai",  # TTS engine: openai,baidu,google,azure,xunfei,ali,pytts(offline),elevenlabs,edge(online)
    "text_to_voice_model": "tts-1",
    "tts_voice_id": "alloy",
    # baidu voice api config; required when using Baidu speech recognition and TTS
    "baidu_app_id": "",
    "baidu_api_key": "",
    "baidu_secret_key": "",
    # 1536 Mandarin (with basic English) 1737 English 1637 Cantonese 1837 Sichuanese 1936 Mandarin far-field
    "baidu_dev_pid": 1536,
    # azure voice api config; required when using Azure speech recognition and TTS
    "azure_voice_api_key": "",
    "azure_voice_region": "japaneast",
    # elevenlabs voice api config
    "xi_api_key": "",  # see https://docs.elevenlabs.io/api-reference/quick-start/authentication for how to obtain the api key
    "xi_voice_id": "",  # ElevenLabs offers 9 English voice ids: Adam/Antoni/Arnold/Bella/Domi/Elli/Josh/Rachel/Sam
    # service time limit
    "chat_time_module": False,  # whether to enable service-time limiting
    "chat_start_time": "00:00",  # service start time
    "chat_stop_time": "24:00",  # service stop time
    # translation api
    "translate": "baidu",  # translation api: baidu, youdao
    # baidu translation api config
    "baidu_translate_app_id": "",  # baidu translation api appid
    "baidu_translate_app_key": "",  # baidu translation api secret key
    # youdao translation api config
    "youdao_translate_app_key": "",  # youdao translation api app id
    "youdao_translate_app_secret": "",  # youdao translation api app secret
    # wechatmp config
    "wechatmp_token": "",  # WeChat Official Account token
    "wechatmp_port": 8080,  # WeChat Official Account port; needs port forwarding to 80 or 443
    "wechatmp_app_id": "",  # WeChat Official Account appID
    "wechatmp_app_secret": "",  # WeChat Official Account appsecret
    "wechatmp_aes_key": "",  # WeChat Official Account EncodingAESKey; required in encrypted mode
    # wechatcom shared config
    "wechatcom_corp_id": "",  # WeCom corp id
    # wechatcomapp config
    "wechatcomapp_token": "",  # WeCom app token
    "wechatcomapp_port": 9898,  # WeCom app service port; no port forwarding needed
    "wechatcomapp_secret": "",  # WeCom app secret
    "wechatcomapp_agent_id": "",  # WeCom app agent_id
    "wechatcomapp_aes_key": "",  # WeCom app aes_key
    # WeChat Customer Service (wechat_kf) config
    "wechat_kf_corp_id": "",  # corp_id of the company the WeChat Customer Service belongs to
    "wechat_kf_token": "",  # WeChat Customer Service callback token
    "wechat_kf_port": 9888,  # WeChat Customer Service callback service port
    "wechat_kf_secret": "",  # WeChat Customer Service app secret
    "wechat_kf_aes_key": "",  # WeChat Customer Service callback aes_key
    "wechat_kf_cursor_path": "~/.wechat_kf_cursors.json",  # path for persisting the WeChat Customer Service sync_msg cursor
    # Feishu config
    "feishu_port": 80,  # Feishu bot listening port; only needed in webhook mode
    "feishu_app_id": "",  # Feishu bot app id
    "feishu_app_secret": "",  # Feishu bot app secret
    "feishu_token": "",  # Feishu verification token; only needed in webhook mode
    "feishu_event_mode": "websocket",  # Feishu event mode: webhook(HTTP server) or websocket(long connection)
    # Feishu streaming reply (based on the official cardkit streaming-card API; requires the cardkit:card:write permission and Feishu client 7.20+)
    "feishu_stream_reply": True,  # whether to enable streaming reply (typewriter effect); auto-downgrades to non-streaming or shows an upgrade prompt on failure/old clients
    # DingTalk config
    "dingtalk_client_id": "",  # DingTalk bot Client ID
    "dingtalk_client_secret": "",  # DingTalk bot Client Secret
    "dingtalk_card_enabled": False,
    # WeCom smart bot config (long connection mode)
    "wecom_bot_id": "",  # WeCom smart bot BotID
    "wecom_bot_secret": "",  # WeCom smart bot long-connection secret
    # Telegram config
    "telegram_token": "",  # Bot token from @BotFather
    "telegram_proxy": "",  # Optional HTTP/SOCKS5 proxy, e.g. http://127.0.0.1:7890 or socks5://127.0.0.1:1080 (empty falls back to env vars)
    "telegram_group_trigger": "mention_or_reply",  # Group trigger: mention_or_reply(@ or reply, recommended) | mention_only(@ only) | all(every message)
    "telegram_register_commands": True,  # Auto-register the BotFather command menu on startup (aligned with web slash commands)
    # Slack config (Socket Mode, no public IP required)
    "slack_bot_token": "",  # Bot User OAuth Token, like xoxb-...
    "slack_app_token": "",  # App-Level Token (generated after enabling Socket Mode), like xapp-...
    "slack_group_trigger": "mention_or_reply",  # Channel trigger: mention_or_reply(@ or reply in thread, recommended) | mention_only(@ only) | all(every message)
    # Discord config (Gateway connection, no public IP required)
    "discord_token": "",  # Discord Bot Token (generated on the Bot page of the Developer Portal)
    "discord_group_trigger": "mention_or_reply",  # Channel trigger: mention_or_reply(@ or reply to bot, recommended) | mention_only(@ only) | all(every message)
    # WeChat config
    "weixin_token": "",  # bot_token obtained after WeChat login; leave empty to auto scan-login on startup
    "weixin_base_url": "https://ilinkai.weixin.qq.com",  # Weixin ilink API base URL
    "weixin_cdn_base_url": "https://novac2c.cdn.weixin.qq.com/c2c",  # CDN base URL
    "weixin_credentials_path": "~/.weixin_cow_credentials.json",  # credentials file path
    # custom trigger words for chatgpt commands
    "clear_memory_commands": ["#清除记忆"],  # session-reset command; must start with #
    # channel config
    "channel_type": "",  # channel type; supports running multiple channels at once. Single: "feishu", multiple: "feishu, dingtalk" or ["feishu", "dingtalk"]. Options: web,feishu,dingtalk,wecom_bot,weixin,wechatmp,wechatmp_service,wechatcom_app,wechat_kf,telegram,slack,discord
    "web_console": True,  # whether to auto-start the Web console (on by default). Set False to disable
    "subscribe_msg": "",  # subscribe message; supported by: wechatmp, wechatmp_service, wechatcom_app
    "debug": False,  # whether to enable debug mode; prints more logs when on
    "appdata_dir": "",  # data directory
    # plugin config
    "plugin_trigger_prefix": "$",  # prefix for plugin chat commands; avoid clashing with the admin command prefix "#"
    # whether to use the global plugin config
    "use_global_plugin_config": False,
    "max_media_send_count": 3,  # max number of media resources sent at once
    "media_send_interval": 1,  # interval between sending images, in seconds
    # Zhipu AI platform config
    "zhipu_ai_api_key": "",
    "zhipu_ai_api_base": "https://open.bigmodel.cn/api/paas/v4",
    "moonshot_api_key": "",
    "moonshot_base_url": "https://api.moonshot.cn/v1",
    # Doubao (Volcano Ark) platform config
    "ark_api_key": "",
    "ark_base_url": "https://ark.cn-beijing.volces.com/api/v3",
    # ModelScope community platform config
    "modelscope_api_key": "",
    "modelscope_base_url": "https://api-inference.modelscope.cn/v1/chat/completions",
    # LinkAI platform config
    "use_linkai": False,
    "linkai_api_key": "",
    "linkai_app_code": "",
    "linkai_api_base": "https://api.link-ai.tech",
    "cloud_host": "client.link-ai.tech",
    "cloud_port": None,
    "cloud_deployment_id": "",
    "minimax_api_key": "",
    "Minimax_group_id": "",
    "Minimax_base_url": "",
    "deepseek_api_key": "",
    "deepseek_api_base": "https://api.deepseek.com/v1",
    # Xiaomi MiMo LLM
    "mimo_api_key": "",
    "mimo_api_base": "https://api.xiaomimimo.com/v1",
    "web_host": "",  # Web console bind address; empty means auto
    "web_port": 9899,
    "web_password": "",  # Web console password; empty means no authentication required
    "web_session_expire_days": 30,  # Auth session expiry in days
    "web_file_serve_root": "~",  # Root dir the /api/file endpoint may serve; "/" allows the whole filesystem
    "agent": True,  # whether to enable Agent mode
    "agent_workspace": "~/cow",  # agent workspace path, used to store skills, memory, etc.
    "agent_max_context_tokens": 50000,  # max context tokens in Agent mode
    "agent_max_context_turns": 20,  # max context memory turns in Agent mode
    "agent_max_steps": 20,  # max decision steps per run in Agent mode
    "enable_thinking": False,  # Enable deep-thinking mode for thinking-capable models
    "reasoning_effort": "high",  # Reasoning depth under thinking mode: "high" or "max"
    "knowledge": True,  # whether to enable the knowledge base feature
    "skill": {},  # Per-skill runtime config; nested keys flatten to SKILL_<NAME>_<KEY> env vars at startup
    "mcp_servers": [],  # MCP server list; each entry supports type "stdio" (local process) or "sse" (remote URL)
}


class Config(dict):
    def __init__(self, d=None):
        super().__init__()
        if d is None:
            d = {}
        for k, v in d.items():
            self[k] = v
        # user_datas: per-user data; key is the username, value is the user's data (also a dict)
        self.user_datas = {}

    def __getitem__(self, key):
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        return super().__setitem__(key, value)

    def get(self, key, default=None):
        # skip comment fields starting with an underscore
        if key.startswith("_"):
            return super().get(key, default)
        
        # if the key is not in available_setting, fall back to dict.get and return the value actually loaded from config.json (or default if absent)
        if key not in available_setting:
            return super().get(key, default)
        
        try:
            return self[key]
        except KeyError as e:
            return default
        except Exception as e:
            raise e

    # Make sure to return a dictionary to ensure atomic
    def get_user_data(self, user) -> dict:
        if self.user_datas.get(user) is None:
            self.user_datas[user] = {}
        return self.user_datas[user]

    def load_user_datas(self):
        try:
            with open(os.path.join(get_appdata_dir(), "user_datas.pkl"), "rb") as f:
                self.user_datas = pickle.load(f)
                logger.debug("[Config] User datas loaded.")
        except FileNotFoundError as e:
            logger.debug("[Config] User datas file not found, ignore.")
        except Exception as e:
            logger.warning("[Config] User datas error: {}".format(e))
            self.user_datas = {}

    def save_user_datas(self):
        try:
            with open(os.path.join(get_appdata_dir(), "user_datas.pkl"), "wb") as f:
                pickle.dump(self.user_datas, f)
                logger.info("[Config] User datas saved.")
        except Exception as e:
            logger.info("[Config] User datas error: {}".format(e))


config = Config()


def drag_sensitive(config):
    try:
        if isinstance(config, str):
            conf_dict: dict = json.loads(config)
            conf_dict_copy = copy.deepcopy(conf_dict)
            for key in conf_dict_copy:
                if "key" in key or "secret" in key:
                    if isinstance(conf_dict_copy[key], str):
                        conf_dict_copy[key] = conf_dict_copy[key][0:3] + "*" * 5 + conf_dict_copy[key][-3:]
            return json.dumps(conf_dict_copy, indent=4)

        elif isinstance(config, dict):
            config_copy = copy.deepcopy(config)
            for key in config:
                if "key" in key or "secret" in key:
                    if isinstance(config_copy[key], str):
                        config_copy[key] = config_copy[key][0:3] + "*" * 5 + config_copy[key][-3:]
            return config_copy
    except Exception as e:
        logger.exception(e)
        return config
    return config


def load_config():
    global config

    # print ASCII logo
    logger.info("  ____                _                    _   ")
    logger.info(" / ___|_____      __ / \\   __ _  ___ _ __ | |_ ")
    logger.info("| |   / _ \\ \\ /\\ / // _ \\ / _` |/ _ \\ '_ \\| __|")
    logger.info("| |__| (_) \\ V  V // ___ \\ (_| |  __/ | | | |_ ")
    logger.info(" \\____\\___/ \\_/\\_//_/   \\_\\__, |\\___|_| |_|\\__|")
    logger.info("                          |___/                 ")
    logger.info("")
    config_path = "./config.json"
    if not os.path.exists(config_path):
        logger.info("config file not found, falling back to config-template.json")
        config_path = "./config-template.json"

    config_str = read_file(config_path)
    logger.debug("[INIT] config str: {}".format(drag_sensitive(config_str)))

    # Deserialize the json string into a dict.
    # `object_pairs_hook` lets us catch users who accidentally typed the
    # same key twice (e.g. two `"tools"` blocks) — json.loads would
    # otherwise silently drop all but the last occurrence.
    config = Config(json.loads(config_str, object_pairs_hook=_merge_duplicate_keys))

    # Migrate legacy singular keys (`tool`, `skill`) into the canonical
    # plural buckets so the rest of the codebase only reads one schema.
    # Deep-merge so existing `tools`/`skills` entries are preserved and
    # only missing namespaces are filled in from the legacy section.
    _merge_legacy_namespace(config, legacy="tool",  canonical="tools")
    _merge_legacy_namespace(config, legacy="skill", canonical="skills")

    # override config with environment variables.
    # Some online deployment platforms (e.g. Railway) deploy project from github directly. So you shouldn't put your secrets like api key in a config file, instead use environment variables to override the default config.
    for name, value in os.environ.items():
        name = name.lower()
        # skip comment fields starting with an underscore
        if name.startswith("_"):
            continue
        if name in available_setting:
            logger.info("[INIT] override config by environ args: {}={}".format(name, value))
            try:
                config[name] = eval(value)
            except Exception:
                if value == "false":
                    config[name] = False
                elif value == "true":
                    config[name] = True
                else:
                    config[name] = value

    if config.get("debug", False):
        logger.setLevel(logging.DEBUG)
        logger.debug("[INIT] set log level to DEBUG")

    # Resolve the global UI language as early as possible so that every
    # downstream layer (logs, CLI, agent prompts, channel replies) shares it.
    resolved_lang = i18n.resolve_language(config.get("cow_lang", "auto"))

    logger.info("[INIT] load config: {}".format(drag_sensitive(config)))

    # print system initialization info
    logger.info("[INIT] ========================================")
    logger.info("[INIT] System Initialization")
    logger.info("[INIT] ========================================")
    logger.info("[INIT] Language: {}".format(resolved_lang))
    logger.info("[INIT] Channel: {}".format(config.get("channel_type", "unknown")))
    logger.info("[INIT] Model: {}".format(config.get("model", "unknown")))

    # Agent mode info
    if config.get("agent", True):
        workspace = config.get("agent_workspace", "~/cow")
        logger.info("[INIT] Mode: Agent (workspace: {})".format(workspace))
    else:
        logger.info("[INIT] Mode: Chat (set \"agent\":true in config.json to enable Agent mode)")

    logger.info("[INIT] Debug: {}".format(config.get("debug", False)))
    logger.info("[INIT] ========================================")

    # Sync selected config values to environment variables so that
    # subprocesses (e.g. shell skill scripts) can access them directly.
    # Existing env vars are NOT overwritten (env takes precedence).
    _CONFIG_TO_ENV = {
        "open_ai_api_key": "OPENAI_API_KEY",
        "open_ai_api_base": "OPENAI_API_BASE",
        "linkai_api_key": "LINKAI_API_KEY",
        "linkai_api_base": "LINKAI_API_BASE",
        "claude_api_key": "CLAUDE_API_KEY",
        "claude_api_base": "CLAUDE_API_BASE",
        "gemini_api_key": "GEMINI_API_KEY",
        "gemini_api_base": "GEMINI_API_BASE",
        "minimax_api_key": "MINIMAX_API_KEY",
        "minimax_api_base": "MINIMAX_API_BASE",
        "deepseek_api_key": "DEEPSEEK_API_KEY",
        "deepseek_api_base": "DEEPSEEK_API_BASE",
        "mimo_api_key": "MIMO_API_KEY",
        "mimo_api_base": "MIMO_API_BASE",
        "qianfan_api_key": "QIANFAN_API_KEY",
        "qianfan_api_base": "QIANFAN_API_BASE",
        "zhipu_ai_api_key": "ZHIPU_AI_API_KEY",
        "zhipu_ai_api_base": "ZHIPU_AI_API_BASE",
        "moonshot_api_key": "MOONSHOT_API_KEY",
        "moonshot_api_base": "MOONSHOT_API_BASE",
        "ark_api_key": "ARK_API_KEY",
        "ark_api_base": "ARK_API_BASE",
        "dashscope_api_key": "DASHSCOPE_API_KEY",
        "dashscope_api_base": "DASHSCOPE_API_BASE",
        # Channel credentials (used by skills that check env vars)
        "feishu_app_id": "FEISHU_APP_ID",
        "feishu_app_secret": "FEISHU_APP_SECRET",
        "dingtalk_client_id": "DINGTALK_CLIENT_ID",
        "dingtalk_client_secret": "DINGTALK_CLIENT_SECRET",
        "wechatmp_app_id": "WECHATMP_APP_ID",
        "wechatmp_app_secret": "WECHATMP_APP_SECRET",
        "wechatcomapp_agent_id": "WECHATCOMAPP_AGENT_ID",
        "wechatcomapp_secret": "WECHATCOMAPP_SECRET",
        "wechatcom_corp_id": "WECHATCOM_CORP_ID",
        "wechat_kf_corp_id": "WECHAT_KF_CORP_ID",
        "wechat_kf_secret": "WECHAT_KF_SECRET",
        "wechat_kf_token": "WECHAT_KF_TOKEN",
        "wechat_kf_aes_key": "WECHAT_KF_AES_KEY",
        "qq_app_id": "QQ_APP_ID",
        "qq_app_secret": "QQ_APP_SECRET",
        "weixin_token": "WEIXIN_TOKEN",
    }
    injected = 0
    for conf_key, env_key in _CONFIG_TO_ENV.items():
        if env_key not in os.environ:
            val = config.get(conf_key, "")
            if val:
                os.environ[env_key] = str(val)
                injected += 1

    injected += _sync_skill_config_to_env(config.get("skills", {}))

    if injected:
        logger.info("[INIT] Synced {} config values to environment variables".format(injected))

    config.load_user_datas()


def _deep_merge_dicts(base: dict, incoming: dict) -> dict:
    """Recursively merge ``incoming`` into ``base`` (incoming wins on leaves)."""
    for key, val in incoming.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(val, dict)
        ):
            _deep_merge_dicts(base[key], val)
        else:
            base[key] = val
    return base


def _merge_duplicate_keys(pairs):
    """object_pairs_hook for json.loads: deep-merge duplicate top-level keys
    (lists concat, dicts merge, scalars take the latter) instead of dropping."""
    out = {}
    duplicates = []
    for key, val in pairs:
        if key not in out:
            out[key] = val
            continue
        duplicates.append(key)
        prev = out[key]
        if isinstance(prev, dict) and isinstance(val, dict):
            _deep_merge_dicts(prev, val)
        elif isinstance(prev, list) and isinstance(val, list):
            prev.extend(val)
        else:
            out[key] = val
    if duplicates:
        # logger may not be wired yet — fall back to print so we never lose the warning.
        unique = sorted(set(duplicates))
        try:
            logger.warning("[INIT] config.json has duplicate keys (merged): %s", unique)
        except Exception:
            print("[INIT] config.json has duplicate keys (merged):", unique)
    return out


def _merge_legacy_namespace(cfg, legacy: str, canonical: str) -> None:
    """Fold deprecated singular keys (``tool`` / ``skill``) into their plural
    canonical counterparts at load time. Canonical entries always win."""
    legacy_section = cfg.get(legacy)
    if not isinstance(legacy_section, dict) or not legacy_section:
        cfg.pop(legacy, None)
        return
    canonical_section = cfg.get(canonical)
    if not isinstance(canonical_section, dict):
        canonical_section = {}
    merged_keys = []
    for name, val in legacy_section.items():
        if name in canonical_section:
            if isinstance(canonical_section[name], dict) and isinstance(val, dict):
                for sub_key, sub_val in val.items():
                    if (
                        sub_key in canonical_section[name]
                        and isinstance(canonical_section[name][sub_key], dict)
                        and isinstance(sub_val, dict)
                    ):
                        _deep_merge_dicts(sub_val, canonical_section[name][sub_key])
                        canonical_section[name][sub_key] = sub_val
                    else:
                        canonical_section[name].setdefault(sub_key, sub_val)
            continue
        canonical_section[name] = val
        merged_keys.append(name)
    cfg[canonical] = canonical_section
    cfg.pop(legacy, None)
    if merged_keys:
        logger.warning(
            "[INIT] Legacy config key '{}' is deprecated; merged into '{}': {}. "
            "Please rename '{}' to '{}' in your config.json.".format(
                legacy, canonical, merged_keys, legacy, canonical,
            )
        )


def _sync_skill_config_to_env(skill_section) -> int:
    """Flatten skill-namespaced config into environment variables.

    Mapping rule: ``config["skills"][<name>][<key>]`` -> ``SKILL_<NAME>_<KEY>``
    (e.g. ``skills["image-generation"].model`` -> ``SKILL_IMAGE_GENERATION_MODEL``).

    This lets subprocess-based skill scripts read their own settings without
    importing project code. Existing env vars are NOT overwritten so the
    real environment always wins.

    Returns the number of variables actually injected.
    """
    if not isinstance(skill_section, dict):
        return 0
    injected = 0
    for skill_name, skill_conf in skill_section.items():
        if not isinstance(skill_conf, dict):
            continue
        name_part = str(skill_name).replace("-", "_").upper()
        for key, val in skill_conf.items():
            if val is None or val == "":
                continue
            env_key = "SKILL_{}_{}".format(name_part, str(key).upper())
            if env_key in os.environ:
                continue
            os.environ[env_key] = str(val)
            injected += 1
    return injected


def get_root():
    return os.path.dirname(os.path.abspath(__file__))


def read_file(path):
    with open(path, mode="r", encoding="utf-8-sig") as f:
        return f.read()


def conf():
    return config


def get_appdata_dir():
    data_path = os.path.join(get_root(), conf().get("appdata_dir", ""))
    if not os.path.exists(data_path):
        logger.info("[INIT] data path not exists, create it: {}".format(data_path))
        os.makedirs(data_path)
    return data_path


def subscribe_msg():
    trigger_prefix = conf().get("single_chat_prefix", [""])[0]
    msg = conf().get("subscribe_msg", "")
    return msg.format(trigger_prefix=trigger_prefix)


# global plugin config
plugin_config = {}


def write_plugin_config(pconf: dict):
    """
    Write the global plugin config.
    :param pconf: the full plugin config
    """
    global plugin_config
    for k in pconf:
        plugin_config[k.lower()] = pconf[k]

def remove_plugin_config(name: str):
    """
    Remove the global config of a plugin pending reload.
    :param name: name of the plugin to reload
    """
    global plugin_config
    plugin_config.pop(name.lower(), None)


def pconf(plugin_name: str) -> dict:
    """
    Get the config for a plugin by name.
    :param plugin_name: plugin name
    :return: the plugin's config
    """
    return plugin_config.get(plugin_name.lower())


# global config holding globally-effective state
global_config = {"admin_users": []}
