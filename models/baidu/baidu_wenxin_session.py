from models.session_manager import Session
from common.log import logger

"""
    e.g.  [
        {"role": "user", "content": "Who won the world series in 2020?"},
        {"role": "assistant", "content": "The Los Angeles Dodgers won the World Series in 2020."},
        {"role": "user", "content": "Where was it played?"}
    ]
"""


class BaiduWenxinSession(Session):
    def __init__(self, session_id, system_prompt=None, model="gpt-3.5-turbo"):
        super().__init__(session_id, system_prompt)
        self.model = model
        # 百度文心不支持system prompt
        # self.reset()

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
            if len(self.messages) >= 2:
                self.messages.pop(0)
                self.messages.pop(0)
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
    tokens = 0
    for msg in messages:
        # 官方token计算规则暂不明确： "大约为 token数为 "中文字 + 其他语种单词数 x 1.3"
        # 这里先直接根据字数粗略估算吧，暂不影响正常使用，仅在判断是否丢弃历史会话的时候会有偏差
        tokens += len(msg["content"])
    return tokens
