from models.bot_factory import create_bot
from bridge.context import Context
from bridge.reply import Reply
from common import const
from common.log import logger
from common.singleton import singleton
from config import conf
from translate.factory import create_translator
from voice.factory import create_voice


@singleton
class Bridge(object):
    def __init__(self):
        self.btype = {
            "chat": const.OPENAI,
            # Empty `voice_to_text` (the default in new configs) triggers
            # the auto-pick below — see _auto_pick_voice_to_text for order.
            "voice_to_text": conf().get("voice_to_text") or self._auto_pick_voice_to_text(),
            "text_to_voice": conf().get("text_to_voice", "google"),
            "translate": conf().get("translate", "baidu"),
        }
        # 这边取配置的模型
        bot_type = conf().get("bot_type")
        if bot_type:
            self.btype["chat"] = bot_type
        else:
            model_type = conf().get("model") or const.GPT_41_MINI
            
            # Ensure model_type is string to prevent AttributeError when using startswith()
            # This handles cases where numeric model names (e.g., "1") are parsed as integers from YAML
            if not isinstance(model_type, str):
                logger.warning(f"[Bridge] model_type is not a string: {model_type} (type: {type(model_type).__name__}), converting to string")
                model_type = str(model_type)
            
            if model_type in ["text-davinci-003"]:
                self.btype["chat"] = const.OPEN_AI
            if conf().get("use_azure_chatgpt", False):
                self.btype["chat"] = const.CHATGPTONAZURE
            if model_type in ["wenxin", "wenxin-4"]:
                self.btype["chat"] = const.BAIDU
            if model_type in ["xunfei"]:
                self.btype["chat"] = const.XUNFEI
            if model_type in [const.QWEN, const.QWEN_TURBO, const.QWEN_PLUS, const.QWEN_MAX]:
                self.btype["chat"] = const.QWEN_DASHSCOPE
            if model_type and (model_type.startswith("qwen") or model_type.startswith("qwq") or model_type.startswith("qvq")):
                self.btype["chat"] = const.QWEN_DASHSCOPE
            if model_type and model_type.startswith("gemini"):
                self.btype["chat"] = const.GEMINI
            if model_type and model_type.startswith("glm"):
                self.btype["chat"] = const.ZHIPU_AI
            if model_type and model_type.startswith("claude"):
                self.btype["chat"] = const.CLAUDEAPI

            if model_type in [const.MOONSHOT, "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"]:
                self.btype["chat"] = const.MOONSHOT
            if model_type and model_type.startswith("kimi"):
                self.btype["chat"] = const.MOONSHOT

            if model_type and model_type.startswith("doubao"):
                self.btype["chat"] = const.DOUBAO

            if model_type and model_type.startswith("deepseek"):
                self.btype["chat"] = const.DEEPSEEK

            # 小米 MiMo 系列模型，全部以 mimo- 开头
            if model_type and model_type.startswith("mimo-"):
                self.btype["chat"] = const.MIMO

            if model_type and isinstance(model_type, str):
                lowered_model_type = model_type.lower()
                if lowered_model_type == const.QIANFAN or lowered_model_type.startswith("ernie"):
                    self.btype["chat"] = const.QIANFAN

            if model_type in [const.MODELSCOPE]:
                self.btype["chat"] = const.MODELSCOPE
            
            # MiniMax models
            if model_type and (model_type in ["abab6.5-chat", "abab6.5"] or model_type.lower().startswith("minimax")):
                self.btype["chat"] = const.MiniMax

            if conf().get("use_linkai") and conf().get("linkai_api_key"):
                self.btype["chat"] = const.LINKAI
                if not conf().get("voice_to_text") or conf().get("voice_to_text") in ["openai"]:
                    self.btype["voice_to_text"] = const.LINKAI
                if not conf().get("text_to_voice") or conf().get("text_to_voice") in ["openai", const.TTS_1, const.TTS_1_HD]:
                    self.btype["text_to_voice"] = const.LINKAI

        self.bots = {}
        self.chat_bots = {}
        self._agent_bridge = None

    def refresh_voice(self):
        """Re-read voice_to_text / text_to_voice from config and drop the
        cached voice bots so the next call picks up the new provider.
        Used by the web console after the user edits voice settings.
        Does NOT touch the agent_bridge / agent state.
        """
        new_v2t = conf().get("voice_to_text") or self._auto_pick_voice_to_text()
        new_t2v = conf().get("text_to_voice", "google")
        if conf().get("use_linkai") and conf().get("linkai_api_key"):
            if not conf().get("voice_to_text") or conf().get("voice_to_text") in ["openai"]:
                new_v2t = const.LINKAI
            if not conf().get("text_to_voice") or conf().get("text_to_voice") in ["openai", const.TTS_1, const.TTS_1_HD]:
                new_t2v = const.LINKAI
        self.btype["voice_to_text"] = new_v2t
        self.btype["text_to_voice"] = new_t2v
        self.bots.pop("voice_to_text", None)
        self.bots.pop("text_to_voice", None)
        logger.info(f"[Bridge] voice refreshed: voice_to_text={new_v2t}, text_to_voice={new_t2v}")

    @staticmethod
    def _auto_pick_voice_to_text() -> str:
        """Pick an ASR provider by configured api keys when voice_to_text is
        unset. Order matches the web console: openai → dashscope → zhipu →
        linkai. Falls back to 'openai' when nothing is configured so the
        original "missing key" error is preserved.
        """
        def has(k: str) -> bool:
            v = (conf().get(k) or "").strip()
            return v != "" and v not in ("YOUR API KEY", "YOUR_API_KEY")

        for key, provider in (
            ("open_ai_api_key", "openai"),
            ("dashscope_api_key", "dashscope"),
            ("zhipu_ai_api_key", "zhipu"),
            ("linkai_api_key", "linkai"),
        ):
            if has(key):
                return provider
        return "openai"

    # 模型对应的接口
    def get_bot(self, typename):
        if self.bots.get(typename) is None:
            logger.info("create bot {} for {}".format(self.btype[typename], typename))
            if typename == "text_to_voice":
                self.bots[typename] = create_voice(self.btype[typename])
            elif typename == "voice_to_text":
                self.bots[typename] = create_voice(self.btype[typename])
            elif typename == "chat":
                self.bots[typename] = create_bot(self.btype[typename])
            elif typename == "translate":
                self.bots[typename] = create_translator(self.btype[typename])
        return self.bots[typename]

    def get_bot_type(self, typename):
        return self.btype[typename]

    def fetch_reply_content(self, query, context: Context) -> Reply:
        return self.get_bot("chat").reply(query, context)

    def fetch_voice_to_text(self, voiceFile) -> Reply:
        return self.get_bot("voice_to_text").voiceToText(voiceFile)

    def fetch_text_to_voice(self, text) -> Reply:
        return self.get_bot("text_to_voice").textToVoice(text)

    def fetch_translate(self, text, from_lang="", to_lang="en") -> Reply:
        return self.get_bot("translate").translate(text, from_lang, to_lang)

    def find_chat_bot(self, bot_type: str):
        if self.chat_bots.get(bot_type) is None:
            self.chat_bots[bot_type] = create_bot(bot_type)
        return self.chat_bots.get(bot_type)

    def reset_bot(self):
        """
        重置bot路由
        """
        self.__init__()

    def get_agent_bridge(self):
        """
        Get agent bridge for agent-based conversations
        """
        if self._agent_bridge is None:
            from bridge.agent_bridge import AgentBridge
            self._agent_bridge = AgentBridge(self)
        return self._agent_bridge

    def fetch_agent_reply(self, query: str, context: Context = None,
                          on_event=None, clear_history: bool = False) -> Reply:
        """
        Use super agent to handle the query

        Args:
            query: User query
            context: Context object
            on_event: Event callback for streaming
            clear_history: Whether to clear conversation history

        Returns:
            Reply object
        """
        agent_bridge = self.get_agent_bridge()
        return agent_bridge.agent_reply(query, context, on_event, clear_history)
