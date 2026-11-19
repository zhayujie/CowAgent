from types import SimpleNamespace
import pytest
from bridge.reply import ReplyType
from voice.openai import openai_voice
from voice.custom import custom_voice
from voice.linkai import linkai_voice

@pytest.mark.parametrize('provider', ['openai', 'custom', 'linkai'])
@pytest.mark.parametrize('text', [None, 17, {}, [], 'valid transcript', ''])
def test_transcription_returns_text_only_for_string(tmp_path, monkeypatch, provider, text):
    module = {'openai': openai_voice, 'custom': custom_voice,
              'linkai': linkai_voice}[provider]
    configuration = {'open_ai_api_key': 'test', 'custom_api_key': 'test',
                     'custom_api_base': 'https://gateway.example/v1', 'voice_to_text_model': 'asr',
                     'linkai_api_base': 'https://gateway.example/v1', 'linkai_api_key': 'test'}
    monkeypatch.setattr(module, 'conf', lambda: configuration)
    response = SimpleNamespace(status_code=200, json=lambda: {'text': text})
    monkeypatch.setattr(module.requests, 'post', lambda *args, **kwargs: response)
    source = tmp_path / 'clip.wav'
    source.write_bytes(b'audio')
    voice = (module.OpenaiVoice() if provider == 'openai'
             else module.CustomVoice('custom') if provider == 'custom'
             else module.LinkAIVoice())
    reply = voice.voiceToText(str(source))
    assert reply.type == (ReplyType.TEXT if isinstance(text, str) else ReplyType.ERROR)
    if isinstance(text, str):
        assert reply.content == text
