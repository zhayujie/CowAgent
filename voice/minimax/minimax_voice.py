# encoding:utf-8
"""
MiniMax TTS voice service
"""
import datetime
import random
import requests

from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf
from voice.voice import Voice


MINIMAX_TTS_VOICES = [
    "English_Graceful_Lady",
    "English_Insightful_Speaker",
    "English_radiant_girl",
    "English_Persuasive_Man",
    "English_Lucky_Robot",
    "English_expressive_narrator",
    "Chinese_Warm_Woman",
    "Chinese_Gentle_Man",
]


class MinimaxVoice(Voice):
    def __init__(self):
        self.api_key = conf().get("minimax_api_key")
        self.api_base = conf().get("minimax_api_base") or "https://api.minimax.io"
        # Strip trailing /v1 if present so we can always append /v1/t2a_v2
        self.api_base = self.api_base.rstrip("/")
        if self.api_base.endswith("/v1"):
            self.api_base = self.api_base[:-3]

    def voiceToText(self, voice_file):
        """MiniMax does not provide an ASR endpoint; raise NotImplementedError."""
        raise NotImplementedError("MiniMax voice-to-text is not supported")

    def textToVoice(self, text):
        try:
            model = conf().get("text_to_voice_model") or "speech-2.8-hd"
            voice_id = conf().get("tts_voice_id") or "English_Graceful_Lady"

            url = f"{self.api_base}/v1/t2a_v2"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }
            payload = {
                "model": model,
                "text": text,
                "stream": True,
                "voice_setting": {
                    "voice_id": voice_id,
                    "speed": 1,
                    "vol": 1,
                    "pitch": 0,
                },
                "audio_setting": {
                    "sample_rate": 32000,
                    "bitrate": 128000,
                    "format": "mp3",
                    "channel": 1,
                },
            }

            response = requests.post(url, headers=headers, json=payload, stream=True, timeout=60)
            response.raise_for_status()

            # Parse SSE stream and collect hex-encoded audio chunks
            audio_chunks = []
            buffer = ""
            for raw in response.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                if not line.startswith("data:"):
                    continue
                json_str = line[5:].strip()
                if not json_str or json_str == "[DONE]":
                    continue
                try:
                    import json
                    event_data = json.loads(json_str)
                    audio_hex = event_data.get("data", {}).get("audio")
                    if audio_hex:
                        audio_chunks.append(bytes.fromhex(audio_hex))
                except Exception:
                    continue

            if not audio_chunks:
                logger.error("[MINIMAX] TTS returned no audio data")
                return Reply(ReplyType.ERROR, "语音合成失败，未获取到音频数据")

            audio_data = b"".join(audio_chunks)
            file_name = "tmp/" + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + str(random.randint(0, 1000)) + ".mp3"
            with open(file_name, "wb") as f:
                f.write(audio_data)

            logger.info(f"[MINIMAX] textToVoice success, file={file_name}")
            return Reply(ReplyType.VOICE, file_name)

        except Exception as e:
            logger.error(f"[MINIMAX] textToVoice error: {e}")
            return Reply(ReplyType.ERROR, "遇到了一点小问题，请稍后再试")
