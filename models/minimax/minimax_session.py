from models.session_manager import Session
from common.log import logger

"""
    e.g.
    [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Who won the world series in 2020?"},
        {"role": "assistant", "content": "The Los Angeles Dodgers won the World Series in 2020."},
        {"role": "user", "content": "Where was it played?"}
    ]
"""


class MinimaxSession(Session):
    def __init__(self, session_id, system_prompt=None, model="minimax"):
        super().__init__(session_id, system_prompt)
        self.model = model
        # self.reset()

    def add_query(self, query):
        user_item = {"sender_type": "USER", "sender_name": self.session_id, "text": query}
        self.messages.append(user_item)

    def add_reply(self, reply):
        assistant_item = {"sender_type": "BOT", "sender_name": "MM智能助理", "text": reply}
        self.messages.append(assistant_item)

    def discard_exceeding(self, max_tokens, cur_tokens=None):
        precise = True
        try:
            cur_tokens = self.calc_tokens()
        except Exception as e:
            precise = False
            if cur_tokens is None:
                raise e
            logger.debug("Exception when counting tokens precisely for query: {}".format(e))
        while cur_tokens > max_tokens:
            if len(self.messages) > 2:
                self.messages.pop(1)
            elif len(self.messages) == 2 and self.messages[1]["sender_type"] == "BOT":
                self.messages.pop(1)
                if precise:
                    cur_tokens = self.calc_tokens()
                else:
                    cur_tokens = cur_tokens - max_tokens
                break
            elif len(self.messages) == 2 and self.messages[1]["sender_type"] == "USER":
                logger.warn("user message exceed max_tokens. total_tokens={}".format(cur_tokens))
                break
            else:
                logger.debug("max_tokens={}, total_tokens={}, len(messages)={}".format(max_tokens, cur_tokens, len(self.messages)))
                break
            if precise:
                cur_tokens = self.calc_tokens()
            else:
                cur_tokens = cur_tokens - max_tokens
        return cur_tokens

    def calc_tokens(self):
        return num_tokens_from_messages(self.messages, self.model)


def num_tokens_from_messages(messages, model):
    """Returns the number of tokens used by a list of messages."""
    # 官方token计算规则："对于中文文本来说，1个token通常对应一个汉字；对于英文文本来说，1个token通常对应3至4个字母或1个单词"
    # 详情请产看文档：https://help.aliyun.com/document_detail/2586397.html
    # 目前根据字符串长度粗略估计token数，不影响正常使用
    tokens = 0
    for msg in messages:
        tokens += len(msg["text"])
    return tokens
