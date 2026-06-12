# encoding:utf-8
"""
小米 MiMo TTS - 基于 mimo-v2.5-tts 模型的语音合成。

通过 /chat/completions 接口实现：assistant 消息内容为待合成文本，
audio 字段指定预置音色（如 冰糖/茉莉/苏打/Mia/Chloe 等），返回 base64
编码的音频字节。

文档：https://platform.xiaomimimo.com/docs/zh-CN/usage-guide/speech-synthesis-v2.5
注意：MiMo 不提供 ASR 端点，因此 voiceToText 不实现。
"""
import base64
import datetime
import os
import random

import requests

from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf
from voice.voice import Voice

DEFAULT_API_BASE = "https://api.xiaomimimo.com/v1"
DEFAULT_TTS_MODEL = "mimo-v2.5-tts"
DEFAULT_TTS_VOICE = "冰糖"  # 默认音色：中国集群事实默认值
REQUEST_TIMEOUT = (5, 120)


class MimoVoice(Voice):
    def __init__(self):
        pass

    def voiceToText(self, voice_file: str):
        # MiMo 没有独立 ASR 端点；建议使用其他 provider（如 openai/zhipu/dashscope）
        logger.warning("[MimoVoice] voiceToText is not supported by MiMo API")
        return Reply(ReplyType.ERROR, "MiMo 暂不支持语音识别，请配置其他 voice_to_text provider")

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
                "tmp/" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                + str(random.randint(0, 1000)) + ".wav"
            )
            os.makedirs(os.path.dirname(file_name), exist_ok=True)
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
