from models.session_manager import Session
from common.log import logger


class OpenAISession(Session):
    def __init__(self, session_id, system_prompt=None, model="text-davinci-003"):
        super().__init__(session_id, system_prompt)
        self.model = model
        self.reset()

    def __str__(self):
        # 构造对话模型的输入
        """
        e.g.  Q: xxx
              A: xxx
              Q: xxx
        """
        prompt = ""
        for item in self.messages:
            if item["role"] == "system":
                prompt += item["content"] + "<|endoftext|>\n\n\n"
            elif item["role"] == "user":
                prompt += "Q: " + item["content"] + "\n"
            elif item["role"] == "assistant":
                prompt += "\n\nA: " + item["content"] + "<|endoftext|>\n"

        if len(self.messages) > 0 and self.messages[-1]["role"] == "user":
            prompt += "A: "
        return prompt

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
            if len(self.messages) > 1:
                self.messages.pop(0)
            elif len(self.messages) == 1 and self.messages[0]["role"] == "assistant":
                self.messages.pop(0)
                if precise:
                    cur_tokens = self.calc_tokens()
                else:
                    cur_tokens = len(str(self))
                break
            elif len(self.messages) == 1 and self.messages[0]["role"] == "user":
                logger.warn("user question exceed max_tokens. total_tokens={}".format(cur_tokens))
                break
            else:
                logger.debug("max_tokens={}, total_tokens={}, len(conversation)={}".format(max_tokens, cur_tokens, len(self.messages)))
                break
            if precise:
                cur_tokens = self.calc_tokens()
            else:
                cur_tokens = len(str(self))
        return cur_tokens

    def calc_tokens(self):
        return num_tokens_from_string(str(self), self.model)


# refer to https://github.com/openai/openai-cookbook/blob/main/examples/How_to_count_tokens_with_tiktoken.ipynb
def num_tokens_from_string(string: str, model: str) -> int:
    """Returns the number of tokens in a text string."""
    import tiktoken

    encoding = tiktoken.encoding_for_model(model)
    num_tokens = len(encoding.encode(string, disallowed_special=()))
    return num_tokens
