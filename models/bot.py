"""
Auto-replay chat robot abstract class
"""

from bridge.context import Context
from bridge.reply import Reply


class Bot(object):
    """
    Base class for all chat-bot implementations.

    Subclasses may also implement:

        call_with_tools(messages, tools=None, stream=False, **kwargs)
            -> dict | generator  (OpenAI-compatible format)

        call_vision(image_url, question, model=None, max_tokens=1000)
            -> dict with keys: model, content, usage  (or error/message)

    These are NOT defined here to avoid shadowing concrete implementations
    provided by mixin classes (e.g. OpenAICompatibleBot) in the MRO.
    Use ``hasattr(bot, 'call_vision')`` to detect support at runtime.
    """

    def reply(self, query, context: Context = None) -> Reply:
        """
        bot auto-reply content
        :param req: received message
        :return: reply content
        """
        raise NotImplementedError
