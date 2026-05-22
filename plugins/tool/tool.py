from chatgpt_tool_hub.apps import AppFactory
from chatgpt_tool_hub.apps.app import App
from chatgpt_tool_hub.tools.tool_register import main_tool_register

import plugins
from bridge.bridge import Bridge
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common import const
from config import conf, get_appdata_dir
from plugins import *


@plugins.register(
    name="tool",
    desc="Arming your ChatGPT bot with various tools",
    version="0.5",
    author="goldfishh",
    desire_priority=0,
)
class Tool(Plugin):
    def __init__(self):
        super().__init__()
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        self.app = self._reset_app()
        if not self.tool_config.get("tools"):
            logger.warn("[tool] init failed, ignore ")
            raise Exception("config.json not found")
        logger.info("[tool] inited")


    def get_help_text(self, verbose=False, **kwargs):
        help_text = "这是一个能让chatgpt联网，搜索，数字运算的插件，将赋予强大且丰富的扩展能力。"
        trigger_prefix = conf().get("plugin_trigger_prefix", "$")
        if not verbose:
            return help_text
        help_text += "\n使用说明：\n"
        help_text += f"{trigger_prefix}tool " + "命令: 根据给出的{命令}模型来选择使用哪些工具尽力为你得到结果。\n"
        help_text += f"{trigger_prefix}tool 工具名 " + "命令: 根据给出的{命令}使用指定工具尽力为你得到结果。\n"
        help_text += f"{trigger_prefix}tool reset: 重置工具。\n\n"

        help_text += f"已加载工具列表: \n"
        for idx, tool in enumerate(main_tool_register.get_registered_tool_names()):
            if idx != 0:
                help_text += ", "
            help_text += f"{tool}"
        return help_text

    def on_handle_context(self, e_context: EventContext):
        if e_context["context"].type != ContextType.TEXT:
            return

        # 暂时不支持未来扩展的bot
        if Bridge().get_bot_type("chat") not in (
            const.OPENAI,
            const.CHATGPT,
            const.OPEN_AI,
            const.CHATGPTONAZURE,
            const.LINKAI,
        ):
            return

        content = e_context["context"].content
        content_list = e_context["context"].content.split(maxsplit=1)

        if not content or len(content_list) < 1:
            e_context.action = EventAction.CONTINUE
            return

        logger.debug("[tool] on_handle_context. content: %s" % content)
        reply = Reply()
        reply.type = ReplyType.TEXT
        trigger_prefix = conf().get("plugin_trigger_prefix", "$")
        # todo: 有些工具必须要api-key，需要修改config文件，所以这里没有实现query增删tool的功能
        if content.startswith(f"{trigger_prefix}tool"):
            if len(content_list) == 1:
                logger.debug("[tool]: get help")
                reply.content = self.get_help_text()
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            elif len(content_list) > 1:
                if content_list[1].strip() == "reset":
                    logger.debug("[tool]: reset config")
                    self.app = self._reset_app()
                    reply.content = "重置工具成功"
                    e_context["reply"] = reply
                    e_context.action = EventAction.BREAK_PASS
                    return
                elif content_list[1].startswith("reset"):
                    logger.debug("[tool]: remind")
                    e_context["context"].content = "请你随机用一种聊天风格，提醒用户：如果想重置tool插件，reset之后不要加任何字符"

                    e_context.action = EventAction.BREAK
                    return
                query = content_list[1].strip()
                
                use_one_tool = False
                for tool_name in main_tool_register.get_registered_tool_names():
                    if query.startswith(tool_name):
                        use_one_tool = True
                        query = query[len(tool_name):]
                        break

                # Don't modify bot name
                all_sessions = Bridge().get_bot("chat").sessions
                user_session = all_sessions.session_query(query, e_context["context"]["session_id"]).messages

                logger.debug("[tool]: just-go")
                try:
                    if use_one_tool:
                        _func, _ = main_tool_register.get_registered_tool()[tool_name]
                        tool = _func(**self.app_kwargs)
                        _reply = tool.run(query)
                    else:
                        # chatgpt-tool-hub will reply you with many tools
                        _reply = self.app.ask(query, user_session)
                    e_context.action = EventAction.BREAK_PASS
                    all_sessions.session_reply(_reply, e_context["context"]["session_id"])
                except Exception as e:
                    logger.exception(e)
                    logger.error(str(e))

                    e_context["context"].content = "请你随机用一种聊天风格，提醒用户：这个问题tool插件暂时无法处理"
                    reply.type = ReplyType.ERROR
                    e_context.action = EventAction.BREAK
                    return

                reply.content = _reply
                e_context["reply"] = reply
        return

    def _read_json(self) -> dict:
        default_config = {"tools": [], "kwargs": {}}
        return super().load_config() or default_config

    def _build_tool_kwargs(self, kwargs: dict):
        tool_model_name = kwargs.get("model_name")
        request_timeout = kwargs.get("request_timeout")

        return {
            # 全局配置相关
            "log": False,  # tool 日志开关
            "debug": kwargs.get("debug", False),  # 输出更多日志
            "no_default": kwargs.get("no_default", False),  # 不要默认的工具，只加载自己导入的工具
            "think_depth": kwargs.get("think_depth", 2),  # 一个问题最多使用多少次工具
            "proxy": conf().get("proxy", ""),  # 科学上网
            "request_timeout": request_timeout if request_timeout else conf().get("request_timeout", 120),
            "temperature": kwargs.get("temperature", 0),  # llm 温度，建议设置0
            # LLM配置相关
            "llm_api_key": conf().get("open_ai_api_key", ""),  # 如果llm api用key鉴权，传入这里
            "llm_api_base_url": conf().get("open_ai_api_base", "https://api.openai.com/v1"),  # 支持openai接口的llm服务地址前缀
            "deployment_id": conf().get("azure_deployment_id", ""),  # azure openai会用到
            # note: 目前tool暂未对其他模型测试，但这里仍对配置来源做了优先级区分，一般插件配置可覆盖全局配置
            "model_name": tool_model_name if tool_model_name else conf().get("model", const.GPT35),
            # 工具配置相关
            # for arxiv tool
            "arxiv_simple": kwargs.get("arxiv_simple", True),  # 返回内容更精简
            "arxiv_top_k_results": kwargs.get("arxiv_top_k_results", 2),  # 只返回前k个搜索结果
            "arxiv_sort_by": kwargs.get("arxiv_sort_by", "relevance"),  # 搜索排序方式 ["relevance","lastUpdatedDate","submittedDate"]
            "arxiv_sort_order": kwargs.get("arxiv_sort_order", "descending"),  # 搜索排序方式 ["ascending", "descending"]
            "arxiv_output_type": kwargs.get("arxiv_output_type", "text"),  # 搜索结果类型 ["text", "pdf", "all"]
            # for bing-search tool
            "bing_subscription_key": kwargs.get("bing_subscription_key", ""),
            "bing_search_url": kwargs.get("bing_search_url", "https://api.bing.microsoft.com/v7.0/search"),  # 必应搜索的endpoint地址，无需修改
            "bing_search_top_k_results": kwargs.get("bing_search_top_k_results", 2),  # 只返回前k个搜索结果
            "bing_search_simple": kwargs.get("bing_search_simple", True),  # 返回内容更精简
            "bing_search_output_type": kwargs.get("bing_search_output_type", "text"),  # 搜索结果类型 ["text", "json"]
            # for email tool
            "email_nickname_mapping": kwargs.get("email_nickname_mapping", "{}"),  # 关于人的代号对应的邮箱地址，可以不输入邮箱地址发送邮件。键为代号值为邮箱地址
            "email_smtp_host": kwargs.get("email_smtp_host", ""),  # 例如 'smtp.qq.com'
            "email_smtp_port": kwargs.get("email_smtp_port", ""),  # 例如 587
            "email_sender": kwargs.get("email_sender", ""),  # 发送者的邮件地址
            "email_authorization_code": kwargs.get("email_authorization_code", ""),  # 发送者验证秘钥（可能不是登录密码）
            # for google-search tool
            "google_api_key": kwargs.get("google_api_key", ""),
            "google_cse_id": kwargs.get("google_cse_id", ""),
            "google_simple": kwargs.get("google_simple", True),   # 返回内容更精简
            "google_output_type": kwargs.get("google_output_type", "text"),  # 搜索结果类型 ["text", "json"]
            # for finance-news tool
            "finance_news_filter": kwargs.get("finance_news_filter", False),  # 是否开启过滤
            "finance_news_filter_list": kwargs.get("finance_news_filter_list", []),  # 过滤词列表
            "finance_news_simple": kwargs.get("finance_news_simple", True),   # 返回内容更精简
            "finance_news_repeat_news": kwargs.get("finance_news_repeat_news", False),  # 是否过滤不返回。该tool每次返回约50条新闻，可能有重复新闻
            # for morning-news tool
            "morning_news_api_key": kwargs.get("morning_news_api_key", ""),   # api-key
            "morning_news_simple": kwargs.get("morning_news_simple", True),   # 返回内容更精简
            "morning_news_output_type": kwargs.get("morning_news_output_type", "text"),  # 搜索结果类型 ["text", "image"]
            # for news-api tool
            "news_api_key": kwargs.get("news_api_key", ""),
            # for searxng-search tool
            "searxng_search_host": kwargs.get("searxng_search_host", ""),
            "searxng_search_top_k_results": kwargs.get("searxng_search_top_k_results", 2),  # 只返回前k个搜索结果
            "searxng_search_output_type": kwargs.get("searxng_search_output_type", "text"),  # 搜索结果类型 ["text", "json"]
            # for sms tool
            "sms_nickname_mapping": kwargs.get("sms_nickname_mapping", "{}"),  # 关于人的代号对应的手机号，可以不输入手机号发送sms。键为代号值为手机号
            "sms_username": kwargs.get("sms_username", ""),  # smsbao用户名
            "sms_apikey": kwargs.get("sms_apikey", ""),  # smsbao
            # for stt tool
            "stt_api_key": kwargs.get("stt_api_key", ""),  # azure
            "stt_api_region": kwargs.get("stt_api_region", ""),  # azure
            "stt_recognition_language": kwargs.get("stt_recognition_language", "zh-CN"),  # 识别的语言类型 部分：en-US ja-JP ko-KR yue-CN zh-CN
            # for tts tool
            "tts_api_key": kwargs.get("tts_api_key", ""),  # azure
            "tts_api_region": kwargs.get("tts_api_region", ""),  # azure
            "tts_auto_detect": kwargs.get("tts_auto_detect", True),  # 是否自动检测语音的语言
            "tts_speech_id": kwargs.get("tts_speech_id", "zh-CN-XiaozhenNeural"),  # 输出语音ID
            # for summary tool
            "summary_max_segment_length": kwargs.get("summary_max_segment_length", 2500),  # 每2500tokens分段，多段触发总结tool
            # for terminal tool
            "terminal_nsfc_filter": kwargs.get("terminal_nsfc_filter", True),  # 是否过滤llm输出的危险命令
            "terminal_return_err_output": kwargs.get("terminal_return_err_output", True),  # 是否输出错误信息
            "terminal_timeout": kwargs.get("terminal_timeout", 20),  # 允许命令最长执行时间
            # for visual tool
            "caption_api_key": kwargs.get("caption_api_key", ""),  # ali dashscope apikey
            # for browser tool
            "browser_use_summary": kwargs.get("browser_use_summary", True),  # 是否对返回结果使用tool功能
            # for url-get tool
            "url_get_use_summary": kwargs.get("url_get_use_summary", True),  # 是否对返回结果使用tool功能
            # for wikipedia tool
            "wikipedia_top_k_results": kwargs.get("wikipedia_top_k_results", 2),  # 只返回前k个搜索结果
            # for wolfram-alpha tool
            "wolfram_alpha_appid": kwargs.get("wolfram_alpha_appid", ""),
        }

    def _filter_tool_list(self, tool_list: list):
        valid_list = []
        for tool in tool_list:
            if tool in main_tool_register.get_registered_tool_names():
                valid_list.append(tool)
            else:
                logger.warning("[tool] filter invalid tool: " + repr(tool))
        return valid_list

    def _reset_app(self) -> App:
        self.tool_config = self._read_json()
        self.app_kwargs = self._build_tool_kwargs(self.tool_config.get("kwargs", {}))

        app = AppFactory()
        app.init_env(**self.app_kwargs)
        # filter not support tool
        tool_list = self._filter_tool_list(self.tool_config.get("tools", []))

        return app.create_app(tools_list=tool_list, **self.app_kwargs)
