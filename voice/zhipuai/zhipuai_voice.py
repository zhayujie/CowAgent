# encoding:utf-8
"""ZhipuAI voice: glm-asr-2512 (ASR) + glm-tts (TTS) via BigModel REST API."""
import datetime
import os
import random

import requests

from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from config import conf
from voice import audio_convert
from voice.voice import Voice


DEFAULT_ASR_MODEL = "glm-asr-2512"
DEFAULT_TTS_MODEL = "glm-tts"
DEFAULT_TTS_VOICE = "tongtong"
DEFAULT_API_BASE = "https://open.bigmodel.cn/api/paas/v4"
MAX_FILE_BYTES = 25 * 1024 * 1024
REQUEST_TIMEOUT = (5, 60)


class ZhipuAIVoice(Voice):
    def __init__(self):
        pass

    def voiceToText(self, voice_file: str):
        try:
            voice_file = self._ensure_compatible_format(voice_file)

            try:
                size = os.path.getsize(voice_file)
                if size > MAX_FILE_BYTES:
                    logger.warning(
                        f"[ZhipuAIVoice] audio file {size}B exceeds {MAX_FILE_BYTES}B; "
                        f"glm-asr-2512 may reject it"
                    )
            except OSError:
                pass

            api_key = conf().get("zhipu_ai_api_key", "")
            if not api_key:
                logger.error("[ZhipuAIVoice] zhipu_ai_api_key is not configured")
                return Reply(ReplyType.ERROR, "未配置 ZhipuAI API key")

            api_base = (conf().get("zhipu_ai_api_base") or DEFAULT_API_BASE).rstrip("/")
            url = f"{api_base}/audio/transcriptions"
            model = conf().get("voice_to_text_model") or DEFAULT_ASR_MODEL

            with open(voice_file, "rb") as f:
                files = {"file": (os.path.basename(voice_file), f)}
                data = {"model": model, "stream": "false"}
                headers = {"Authorization": f"Bearer {api_key}"}
                response = requests.post(
                    url, headers=headers, files=files, data=data, timeout=REQUEST_TIMEOUT
                )

            if response.status_code != 200:
                logger.error(
                    f"[ZhipuAIVoice] voiceToText failed: status={response.status_code} "
                    f"body={response.text[:500]}"
                )
                return Reply(ReplyType.ERROR, "我暂时还无法听清您的语音，请稍后再试吧~")

            payload = response.json()
            text = (payload.get("text") or "").strip()
            if not text:
                logger.error(f"[ZhipuAIVoice] voiceToText empty text: {payload}")
                return Reply(ReplyType.ERROR, "我暂时还无法听清您的语音，请稍后再试吧~")

            logger.info(f"[ZhipuAIVoice] voiceToText model={model} text={text}")
            return Reply(ReplyType.TEXT, text)
        except Exception as e:
            logger.exception(f"[ZhipuAIVoice] voiceToText exception: {e}")
            return Reply(ReplyType.ERROR, "我暂时还无法听清您的语音，请稍后再试吧~")

    def textToVoice(self, text: str):
        try:
            api_key = conf().get("zhipu_ai_api_key", "")
            if not api_key:
                logger.error("[ZhipuAIVoice] zhipu_ai_api_key is not configured")
                return Reply(ReplyType.ERROR, "未配置 ZhipuAI API key")

            api_base = (conf().get("zhipu_ai_api_base") or DEFAULT_API_BASE).rstrip("/")
            url = f"{api_base}/audio/speech"
            model = conf().get("text_to_voice_model") or DEFAULT_TTS_MODEL
            voice_id = conf().get("tts_voice_id") or DEFAULT_TTS_VOICE

            payload = {
                "model": model,
                "input": text,
                "voice": voice_id,
                "response_format": "wav",
                "speed": 1.0,
                "volume": 1.0,
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            response = requests.post(
                url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
            )

            if response.status_code != 200:
                logger.error(
                    f"[ZhipuAIVoice] textToVoice failed: status={response.status_code} "
                    f"body={response.text[:500]} model={model} voice={voice_id}"
                )
                return Reply(ReplyType.ERROR, "语音合成失败，请稍后再试")

            # Some errors come back as JSON / SSE with HTTP 200.
            ct = response.headers.get("Content-Type", "")
            if "application/json" in ct or "text/event-stream" in ct:
                try:
                    err = response.json()
                except Exception:
                    err = {"raw": response.text[:500]}
                logger.error(
                    f"[ZhipuAIVoice] textToVoice unexpected text response "
                    f"(content_type={ct}): {err}"
                )
                return Reply(ReplyType.ERROR, "语音合成失败，请稍后再试")

            audio_bytes = response.content
            ext = self._sniff_audio_ext(audio_bytes) or "wav"

            file_name = (
                TmpDir().path() + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                + str(random.randint(0, 1000)) + "." + ext
            )
            with open(file_name, "wb") as f:
                f.write(audio_bytes)
            logger.info(
                f"[ZhipuAIVoice] textToVoice model={model} voice={voice_id} "
                f"file={file_name} bytes={len(audio_bytes)} ext={ext}"
            )
            return Reply(ReplyType.VOICE, file_name)
        except Exception as e:
            logger.exception(f"[ZhipuAIVoice] textToVoice exception: {e}")
            return Reply(ReplyType.ERROR, "语音合成失败，请稍后再试")

    @staticmethod
    def _sniff_audio_ext(data: bytes) -> str:
        """Detect audio container by magic bytes; returns '' on unknown."""
        if len(data) < 12:
            return ""
        head = data[:12]
        if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
            return "wav"
        if head[:3] == b"ID3" or head[:2] == b"\xff\xfb" or head[:2] == b"\xff\xf3" or head[:2] == b"\xff\xf2":
            return "mp3"
        if head[:4] == b"OggS":
            return "ogg"
        if head[:4] == b"fLaC":
            return "flac"
        return ""

    @staticmethod
    def _ensure_compatible_format(voice_file: str) -> str:
        # glm-asr-2512 only accepts .wav / .mp3
        lower = voice_file.lower()
        if lower.endswith(".mp3") or lower.endswith(".wav"):
            return voice_file
        try:
            mp3_file = os.path.splitext(voice_file)[0] + ".mp3"
            audio_convert.any_to_mp3(voice_file, mp3_file)
            return mp3_file
        except Exception as e:
            logger.warning(f"[ZhipuAIVoice] mp3 convert failed: {e}")
            return voice_file
