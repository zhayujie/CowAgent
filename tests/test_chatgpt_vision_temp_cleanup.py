import models.chatgpt.chat_gpt_bot as chatgpt_module


class _FailingClient:
    def chat_completions(self, **kwargs):
        raise RuntimeError("vision service unavailable")


class _ImageContext(dict):
    def __init__(self, image_path):
        super().__init__()
        self.content = str(image_path)


def test_reply_image_removes_temp_file_when_vision_request_fails(tmp_path, monkeypatch):
    image = tmp_path / "upload.png"
    image.write_bytes(b"not-a-real-image")

    monkeypatch.setattr(chatgpt_module, "conf", lambda: {})
    bot = chatgpt_module.ChatGPTBot.__new__(chatgpt_module.ChatGPTBot)
    bot._bot_type = ""
    bot._http_client = _FailingClient()
    bot._use_responses_for_plain_calls = lambda: False

    reply = bot.reply_image(_ImageContext(image))

    assert reply.type.name == "ERROR"
    assert not image.exists()


def test_reply_image_invalid_path_preserves_the_error_reply(monkeypatch):
    monkeypatch.setattr(chatgpt_module, "conf", lambda: {})
    bot = chatgpt_module.ChatGPTBot.__new__(chatgpt_module.ChatGPTBot)
    bot._bot_type = ""
    bot._http_client = _FailingClient()
    bot._use_responses_for_plain_calls = lambda: False
    context = _ImageContext("unused")
    context.content = None

    reply = bot.reply_image(context)

    assert reply.type.name == "ERROR"
