from models.bot_factory import create_bot
from bridge.context import Context
from bridge.reply import Reply, ReplyType
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
            # Empty `voice_to_text` / `text_to_voice` (the default in new
            # configs) triggers the auto-pick below — see _auto_pick_* for order.
            "voice_to_text": conf().get("voice_to_text") or self._auto_pick_voice_to_text(),
            "text_to_voice": conf().get("text_to_voice") or self._auto_pick_text_to_voice(),
            "translate": conf().get("translate", "baidu"),
        }
        # 这边取配置的模型
        bot_type = conf().get("bot_type")
        if bot_type:
            self.btype["chat"] = bot_type
        else:
            model_type = conf().get("model") or const.DEFAULT_MODEL
            
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
        self.asr_bots = {}
        self._agent_bridge = None

    def refresh_voice(self):
        """Re-read voice_to_text / text_to_voice from config and drop the
        cached voice bots so the next call picks up the new provider.
        Used by the web console after the user edits voice settings.
        Does NOT touch the agent_bridge / agent state.
        """
        new_v2t = conf().get("voice_to_text") or self._auto_pick_voice_to_text()
        new_t2v = conf().get("text_to_voice") or self._auto_pick_text_to_voice()
        if conf().get("use_linkai") and conf().get("linkai_api_key"):
            if not conf().get("voice_to_text") or conf().get("voice_to_text") in ["openai"]:
                new_v2t = const.LINKAI
            if not conf().get("text_to_voice") or conf().get("text_to_voice") in ["openai", const.TTS_1, const.TTS_1_HD]:
                new_t2v = const.LINKAI
        self.btype["voice_to_text"] = new_v2t
        self.btype["text_to_voice"] = new_t2v
        self.bots.pop("voice_to_text", None)
        self.bots.pop("text_to_voice", None)
        self.asr_bots = {}
        logger.info(f"[Bridge] voice refreshed: voice_to_text={new_v2t}, text_to_voice={new_t2v}")

    # ASR vendors in the web console's order, each with its api key field.
    _ASR_KEYS = (
        ("deepseek_api_key", "deepseek"),
        ("open_ai_api_key", "openai"),
        ("dashscope_api_key", "dashscope"),
        ("zhipu_ai_api_key", "zhipu"),
        ("mimo_api_key", "mimo"),
        ("cowagent_api_key", "cowagent"),
        ("linkai_api_key", "linkai"),
    )

    # Chat bot types whose vendor also offers speech recognition.
    _ASR_BY_CHAT = {
        const.OPENAI: "openai",
        const.CHATGPT: "openai",
        const.DEEPSEEK: "deepseek",
        const.QWEN_DASHSCOPE: "dashscope",
        const.ZHIPU_AI: "zhipu",
        const.MIMO: "mimo",
        const.COWAGENT: "cowagent",
        const.LINKAI: "linkai",
    }

    @staticmethod
    def _has_key(key: str) -> bool:
        v = (conf().get(key) or "").strip()
        return v != "" and v not in ("YOUR API KEY", "YOUR_API_KEY")

    @classmethod
    def _pick_by_api_key(cls, candidates) -> str:
        for key, provider in candidates:
            if cls._has_key(key):
                return provider
        return ""

    @classmethod
    def _auto_pick_voice_to_text(cls) -> str:
        """Pick an ASR provider by configured api keys when voice_to_text is
        unset. Order matches the web console: deepseek → openai → dashscope →
        zhipu → mimo → cowagent → linkai. Falls back to 'openai' when nothing
        is configured so the original "missing key" error is preserved.
        """
        return cls._pick_by_api_key(cls._ASR_KEYS) or "openai"

    def _voice_to_text_chain(self) -> list:
        """ASR providers to try in order. An explicitly chosen provider is
        used alone, so audio never reaches a vendor the user did not pick.
        Auto mode starts with the main model's vendor, then every other
        vendor that has an api key.
        """
        explicit = (conf().get("voice_to_text") or "").strip()
        legacy_linkai = (explicit == "openai" and conf().get("use_linkai")
                         and self._has_key("linkai_api_key"))
        if explicit and not legacy_linkai:
            return [explicit]

        chain = []
        chat_type = str(self.btype.get("chat") or "")
        main = self._ASR_BY_CHAT.get(chat_type)
        main_key = next((k for k, p in self._ASR_KEYS if p == main), "")
        if chat_type.startswith("custom:"):
            chain.append(chat_type)
        elif main_key and self._has_key(main_key):
            chain.append(main)
        for key, provider in self._ASR_KEYS:
            if provider not in chain and self._has_key(key):
                chain.append(provider)
        return chain or [self.btype["voice_to_text"]]

    @classmethod
    def _auto_pick_text_to_voice(cls) -> str:
        """Pick a TTS provider by configured api keys when text_to_voice is
        unset. Order matches the web console: deepseek → openai → minimax →
        dashscope → mimo → cowagent → linkai. Falls back to 'google' (the
        historical default) when nothing is configured.
        """
        return cls._pick_by_api_key((
            ("deepseek_api_key", "deepseek"),
            ("open_ai_api_key", "openai"),
            ("minimax_api_key", "minimax"),
            ("dashscope_api_key", "dashscope"),
            ("mimo_api_key", "mimo"),
            ("cowagent_api_key", "cowagent"),
            ("linkai_api_key", "linkai"),
        )) or "google"

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
        chain = self._voice_to_text_chain()
        for provider in chain[:-1]:
            try:
                reply = self._asr_bot(provider).voiceToText(voiceFile)
                if reply is not None and reply.type == ReplyType.TEXT:
                    return reply
                reason = reply.content if reply is not None else "no reply"
            except Exception as e:
                reason = e
            logger.warning(f"[Bridge] voice_to_text via {provider} failed ({reason}), trying the next provider")
        return self._asr_bot(chain[-1]).voiceToText(voiceFile)

    def _asr_bot(self, provider: str):
        if provider not in self.asr_bots:
            logger.info(f"create bot {provider} for voice_to_text")
            self.asr_bots[provider] = create_voice(provider)
        return self.asr_bots[provider]

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
