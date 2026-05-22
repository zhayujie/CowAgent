from models.session_manager import Session
from common.log import logger


class DashscopeSession(Session):
    def __init__(self, session_id, system_prompt=None, model="qwen-turbo"):
        super().__init__(session_id)
        self.reset()

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
            elif len(self.messages) == 2 and self.messages[1]["role"] == "assistant":
                self.messages.pop(1)
                if precise:
                    cur_tokens = self.calc_tokens()
                else:
                    cur_tokens = cur_tokens - max_tokens
                break
            elif len(self.messages) == 2 and self.messages[1]["role"] == "user":
                logger.warn("user message exceed max_tokens. total_tokens={}".format(cur_tokens))
                break
            else:
                logger.debug("max_tokens={}, total_tokens={}, len(messages)={}".format(max_tokens, cur_tokens,
                                                                                       len(self.messages)))
                break
            if precise:
                cur_tokens = self.calc_tokens()
            else:
                cur_tokens = cur_tokens - max_tokens
        return cur_tokens

    def calc_tokens(self):
        return num_tokens_from_messages(self.messages)


def num_tokens_from_messages(messages):
    # 只是大概，具体计算规则：https://help.aliyun.com/zh/dashscope/developer-reference/token-api?spm=a2c4g.11186623.0.0.4d8b12b0BkP3K9
    tokens = 0
    for msg in messages:
        tokens += len(msg["content"])
    return tokens
