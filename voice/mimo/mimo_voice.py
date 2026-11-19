# encoding:utf-8
"""
小米 MiMo 语音：mimo-v2.5-asr 语音识别 + mimo-v2.5-tts 语音合成。

两者都走 /chat/completions 接口：
- ASR：user 消息携带一段 base64 编码的 input_audio（仅支持 mp3 / wav），
  返回识别出的文本。
- TTS：assistant 消息内容为待合成文本，audio 字段指定预置音色
  （如 冰糖/茉莉/苏打/Mia/Chloe 等），返回 base64 编码的音频字节。

文档：
- https://platform.xiaomimimo.com/docs/zh-CN/usage-guide/speech-recognition
- https://platform.xiaomimimo.com/docs/zh-CN/usage-guide/speech-synthesis-v2.5
"""
import base64
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

DEFAULT_API_BASE = "https://api.xiaomimimo.com/v1"
DEFAULT_ASR_MODEL = "mimo-v2.5-asr"
DEFAULT_TTS_MODEL = "mimo-v2.5-tts"
DEFAULT_TTS_VOICE = "冰糖"  # 默认音色：中国集群事实默认值
REQUEST_TIMEOUT = (5, 120)
# The ASR endpoint rejects a base64 audio payload above 10 MB.
MAX_ASR_BASE64_BYTES = 10 * 1024 * 1024
ASR_MIME_TYPES = {".mp3": "audio/mpeg", ".wav": "audio/wav"}
ASR_FAILED_MSG = "我暂时还无法听清您的语音，请稍后再试吧~"


class MimoVoice(Voice):
    def __init__(self):
        pass

    def voiceToText(self, voice_file: str):
        try:
            api_key = conf().get("mimo_api_key", "")
            if not api_key:
                logger.error("[MimoVoice] mimo_api_key is not configured")
                return Reply(ReplyType.ERROR, "未配置 MiMo API key")

            voice_file = self._ensure_asr_format(voice_file)
            mime = ASR_MIME_TYPES.get(os.path.splitext(voice_file)[1].lower())
            if not mime:
                logger.error(f"[MimoVoice] voiceToText unsupported audio format: {voice_file}")
                return Reply(ReplyType.ERROR, ASR_FAILED_MSG)

            with open(voice_file, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode("ascii")
            if len(audio_b64) > MAX_ASR_BASE64_BYTES:
                logger.warning(
                    f"[MimoVoice] audio payload {len(audio_b64)}B exceeds "
                    f"{MAX_ASR_BASE64_BYTES}B; mimo-v2.5-asr may reject it"
                )

            api_base = (conf().get("mimo_api_base") or DEFAULT_API_BASE).rstrip("/")
            model = conf().get("voice_to_text_model") or DEFAULT_ASR_MODEL
            payload = {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [{
                        "type": "input_audio",
                        "input_audio": {"data": f"data:{mime};base64,{audio_b64}"},
                    }],
                }],
                "asr_options": {"language": "auto"},
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            response = requests.post(
                f"{api_base}/chat/completions", headers=headers, json=payload, timeout=REQUEST_TIMEOUT
            )
            if response.status_code != 200:
                logger.error(
                    f"[MimoVoice] voiceToText failed: status={response.status_code} "
                    f"body={response.text[:500]} model={model}"
                )
                return Reply(ReplyType.ERROR, ASR_FAILED_MSG)

            data = response.json()
            if "error" in data:
                logger.error(f"[MimoVoice] voiceToText api error: {data['error']}")
                return Reply(ReplyType.ERROR, ASR_FAILED_MSG)

            message = (data.get("choices") or [{}])[0].get("message", {}) or {}
            text = (message.get("content") or "").strip()
            if not text:
                logger.error(f"[MimoVoice] voiceToText empty text: {data}")
                return Reply(ReplyType.ERROR, ASR_FAILED_MSG)

            logger.info(f"[MimoVoice] voiceToText model={model} text={text}")
            return Reply(ReplyType.TEXT, text)
        except Exception as e:
            logger.exception(f"[MimoVoice] voiceToText exception: {e}")
            return Reply(ReplyType.ERROR, ASR_FAILED_MSG)

    @staticmethod
    def _ensure_asr_format(voice_file: str) -> str:
        # mimo-v2.5-asr only accepts mp3 / wav; channels hand over amr / silk /
        # opus / ogg etc., so convert those to mp3 first.
        if os.path.splitext(voice_file)[1].lower() in ASR_MIME_TYPES:
            return voice_file
        mp3_file = os.path.splitext(voice_file)[0] + ".mp3"
        try:
            audio_convert.any_to_mp3(voice_file, mp3_file)
            return mp3_file
        except Exception as e:
            logger.warning(f"[MimoVoice] mp3 convert failed: {e}")
            return voice_file

    def textToVoice(self, text: str):
        try:
            api_key = conf().get("mimo_api_key", "")
            if not api_key:
                logger.error("[MimoVoice] mimo_api_key is not configured")
                return Reply(ReplyType.ERROR, "未配置 MiMo API key")

            api_base = (conf().get("mimo_api_base") or DEFAULT_API_BASE).rstrip("/")
            model = conf().get("text_to_voice_model") or DEFAULT_TTS_MODEL
            voice_id = conf().get("tts_voice_id") or DEFAULT_TTS_VOICE

            # 目标合成文本必须放在 assistant 消息；user 消息可选用作风格指令
            payload = {
                "model": model,
                "messages": [
                    {"role": "assistant", "content": text},
                ],
                "audio": {
                    "format": "wav",
                    "voice": voice_id,
                },
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            url = f"{api_base}/chat/completions"
            response = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)

            if response.status_code != 200:
                logger.error(
                    f"[MimoVoice] textToVoice failed: status={response.status_code} "
                    f"body={response.text[:500]} model={model} voice={voice_id}"
                )
                return Reply(ReplyType.ERROR, "语音合成失败，请稍后再试")

            data = response.json()
            if "error" in data:
                err = data["error"]
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                logger.error(f"[MimoVoice] textToVoice api error: {msg}")
                return Reply(ReplyType.ERROR, "语音合成失败，请稍后再试")

            message = (data.get("choices") or [{}])[0].get("message", {}) or {}
            audio_obj = message.get("audio") or {}
            audio_b64 = audio_obj.get("data")
            if not audio_b64:
                logger.error(f"[MimoVoice] textToVoice empty audio in response: {data}")
                return Reply(ReplyType.ERROR, "语音合成失败，请稍后再试")

            try:
                audio_bytes = base64.b64decode(audio_b64)
            except Exception as e:
                logger.error(f"[MimoVoice] base64 decode failed: {e}")
                return Reply(ReplyType.ERROR, "语音合成失败，请稍后再试")

            file_name = (
                TmpDir().path() + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                + str(random.randint(0, 1000)) + ".wav"
            )
            with open(file_name, "wb") as f:
                f.write(audio_bytes)
            logger.info(
                f"[MimoVoice] textToVoice model={model} voice={voice_id} "
                f"file={file_name} bytes={len(audio_bytes)}"
            )
            return Reply(ReplyType.VOICE, file_name)
        except Exception as e:
            logger.exception(f"[MimoVoice] textToVoice exception: {e}")
            return Reply(ReplyType.ERROR, "语音合成失败，请稍后再试")
