# encoding:utf-8

"""
CowAgent model API voice service.

The API is OpenAI-compatible, so this is the custom-vendor client with the
built-in credentials (``cowagent_api_key`` / ``cowagent_api_base``) and the
models and voice this endpoint serves as defaults.
"""
from models.cowagent_provider import resolve_cowagent_credentials
from voice.custom.custom_voice import CustomVoice


class CowAgentVoice(CustomVoice):
    DEFAULT_ASR_MODEL = "seed-asr"
    DEFAULT_TTS_MODEL = "seed-tts-2.0"
    DEFAULT_VOICE = "zh_female_vv_uranus_bigtts"

    def __init__(self):
        super().__init__("cowagent")

    def _resolve_credentials(self):
        return resolve_cowagent_credentials()

    def _extra_headers(self) -> dict:
        return {}
