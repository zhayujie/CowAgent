from types import SimpleNamespace
import pytest
from voice.openai import openai_voice as module

@pytest.mark.parametrize('suffix', ['', '/', '///'])
@pytest.mark.parametrize('method, endpoint', [('voiceToText', 'transcriptions'), ('textToVoice', 'speech')])
def test_audio_endpoint_has_one_separator(tmp_path, monkeypatch, suffix, method, endpoint):
    monkeypatch.setattr(module, 'conf', lambda: {'open_ai_api_base': 'https://gateway.example/v1' + suffix,
                                                 'open_ai_api_key': 'test', 'text_to_voice_model': 'tts-1'})
    urls = []
    def post(url, **kwargs):
        urls.append(url)
        return SimpleNamespace(status_code=503, json=lambda: {}, text='unavailable', close=lambda: None)
    monkeypatch.setattr(module.requests, 'post', post)
    source = tmp_path / 'voice.wav'
    source.write_bytes(b'voice')
    getattr(module.OpenaiVoice(), method)(str(source) if method == 'voiceToText' else 'hello')
    assert urls == ['https://gateway.example/v1/audio/' + endpoint]
