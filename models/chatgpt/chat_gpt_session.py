from models.session_manager import Session
from common.log import logger
from common import const

"""
    e.g.  [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Who won the world series in 2020?"},
        {"role": "assistant", "content": "The Los Angeles Dodgers won the World Series in 2020."},
        {"role": "user", "content": "Where was it played?"}
    ]
"""


class ChatGPTSession(Session):
    def __init__(self, session_id, system_prompt=None, model="gpt-3.5-turbo"):
        super().__init__(session_id, system_prompt)
        self.model = model
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
                logger.debug("max_tokens={}, total_tokens={}, len(messages)={}".format(max_tokens, cur_tokens, len(self.messages)))
                break
            if precise:
                cur_tokens = self.calc_tokens()
            else:
                cur_tokens = cur_tokens - max_tokens
        return cur_tokens

    def calc_tokens(self):
        return num_tokens_from_messages(self.messages, self.model)


# refer to https://github.com/openai/openai-cookbook/blob/main/examples/How_to_count_tokens_with_tiktoken.ipynb
def num_tokens_from_messages(messages, model):
    """Returns the number of tokens used by a list of messages."""

    if model in ["wenxin", "xunfei"] or model.startswith(const.GEMINI):
        return num_tokens_by_character(messages)

    import tiktoken

    if model in ["gpt-3.5-turbo-0301", "gpt-35-turbo", "gpt-3.5-turbo-1106", "moonshot", const.LINKAI_35]:
        return num_tokens_from_messages(messages, model="gpt-3.5-turbo")
    elif model in ["gpt-4-0314", "gpt-4-0613", "gpt-4-32k", "gpt-4-32k-0613", "gpt-3.5-turbo-0613",
                   "gpt-3.5-turbo-16k", "gpt-3.5-turbo-16k-0613", "gpt-35-turbo-16k", "gpt-4-turbo-preview",
                   "gpt-4-1106-preview", const.GPT4_TURBO_PREVIEW, const.GPT4_VISION_PREVIEW, const.GPT4_TURBO_01_25,
                   const.GPT_4o, const.GPT_4O_0806, const.GPT_4o_MINI, const.LINKAI_4o, const.LINKAI_4_TURBO, const.GPT_5, const.GPT_5_MINI, const.GPT_5_NANO]:
        return num_tokens_from_messages(messages, model="gpt-4")
    elif model.startswith("claude-3"):
        return num_tokens_from_messages(messages, model="gpt-3.5-turbo")
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        logger.debug("Warning: model not found. Using cl100k_base encoding.")
        encoding = tiktoken.get_encoding("cl100k_base")
    if model == "gpt-3.5-turbo":
        tokens_per_message = 4  # every message follows <|start|>{role/name}\n{content}<|end|>\n
        tokens_per_name = -1  # if there's a name, the role is omitted
    elif model == "gpt-4":
        tokens_per_message = 3
        tokens_per_name = 1
    else:
        logger.debug(f"num_tokens_from_messages() is not implemented for model {model}. Returning num tokens assuming gpt-3.5-turbo.")
        return num_tokens_from_messages(messages, model="gpt-3.5-turbo")
    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            num_tokens += len(encoding.encode(value))
            if key == "name":
                num_tokens += tokens_per_name
    num_tokens += 3  # every reply is primed with <|start|>assistant<|message|>
    return num_tokens


def num_tokens_by_character(messages):
    """Returns the number of tokens used by a list of messages."""
    tokens = 0
    for msg in messages:
        tokens += len(msg["content"])
    return tokens
