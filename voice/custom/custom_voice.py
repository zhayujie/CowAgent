# encoding:utf-8

"""
Custom (OpenAI-compatible) provider voice service.

Routes ASR/TTS through a user-created custom vendor (``custom_providers``,
see models/custom_provider.py). The vendor endpoint must be OpenAI-compatible:

- voiceToText: ``POST {api_base}/audio/transcriptions``
- textToVoice: ``POST {api_base}/audio/speech``

The vendor id is carried in ``voice_to_text`` / ``text_to_voice`` as
``custom:<id>`` (or legacy flat ``custom``). Unlike the built-in vendors
there is no default model — ``voice_to_text_model`` / ``text_to_voice_model``
must be set, otherwise an error Reply is returned.
"""
import datetime
import random

import requests

from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf
from models.custom_provider import _find_provider_by_id, get_custom_providers, parse_custom_bot_type
from voice.voice import Voice


class CustomVoice(Voice):
    def __init__(self, voice_type: str):
        self.voice_type = voice_type

    def _resolve_credentials(self):
        """Return (api_key, api_base) for the configured custom vendor.

        ``custom:<id>`` looks the id up in ``custom_providers``; the legacy
        flat ``custom`` type reads ``custom_api_key`` / ``custom_api_base``.
        """
        _, custom_id = parse_custom_bot_type(self.voice_type)
        if custom_id:
            entry = _find_provider_by_id(get_custom_providers(), custom_id)
            if entry is None:
                raise ValueError(
                    f"custom provider '{self.voice_type}' not found in custom_providers"
                )
            return entry.get("api_key", ""), entry.get("api_base") or ""
        return conf().get("custom_api_key", ""), conf().get("custom_api_base") or ""

    def voiceToText(self, voice_file):
        try:
            api_key, api_base = self._resolve_credentials()
            model = (conf().get("voice_to_text_model") or "").strip()
            if not api_base or not model:
                logger.error(
                    f"[Custom] voiceToText missing config: api_base={bool(api_base)}, "
                    f"voice_to_text_model={model!r}"
                )
                return Reply(ReplyType.ERROR, "我暂时还无法听清您的语音，请稍后再试吧~")
            url = f"{api_base.rstrip('/')}/audio/transcriptions"
            with open(voice_file, "rb") as f:
                response = requests.post(
                    url,
                    headers={"Authorization": "Bearer " + api_key},
                    files={"file": f},
                    data={"model": model},
                )
            try:
                data = response.json()
            except ValueError:
                data = {"raw": response.text[:200]}
            if response.status_code != 200 or "text" not in data:
                logger.error(
                    f"[Custom] voiceToText failed: status={response.status_code}, resp={data}"
                )
                return Reply(ReplyType.ERROR, "我暂时还无法听清您的语音，请稍后再试吧~")
            logger.info(f"[Custom] voiceToText text={data['text']} model={model}")
            return Reply(ReplyType.TEXT, data["text"])
        except Exception as e:
            logger.error(f"[Custom] voiceToText exception: {e}", exc_info=True)
            return Reply(ReplyType.ERROR, "我暂时还无法听清您的语音，请稍后再试吧~")

    def textToVoice(self, text):
        try:
            api_key, api_base = self._resolve_credentials()
            model = (conf().get("text_to_voice_model") or "").strip()
            if not api_base or not model:
                logger.error(
                    f"[Custom] textToVoice missing config: api_base={bool(api_base)}, "
                    f"text_to_voice_model={model!r}"
                )
                return Reply(ReplyType.ERROR, "遇到了一点小问题，请稍后再问我吧")
            url = f"{api_base.rstrip('/')}/audio/speech"
            response = requests.post(
                url,
                headers={
                    "Authorization": "Bearer " + api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "input": text,
                    "voice": conf().get("tts_voice_id") or "alloy",
                },
            )
            if response.status_code != 200:
                logger.error(
                    f"[Custom] textToVoice failed: status={response.status_code}, "
                    f"resp={response.text[:200]}"
                )
                return Reply(ReplyType.ERROR, "遇到了一点小问题，请稍后再问我吧")
            file_name = "tmp/" + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + str(random.randint(0, 1000)) + ".mp3"
            with open(file_name, "wb") as f:
                f.write(response.content)
            logger.info("[Custom] textToVoice success")
            return Reply(ReplyType.VOICE, file_name)
        except Exception as e:
            logger.error(f"[Custom] textToVoice exception: {e}", exc_info=True)
            return Reply(ReplyType.ERROR, "遇到了一点小问题，请稍后再问我吧")
