# encoding:utf-8
"""MiniMax TTS via /v1/t2a_v2 (SSE stream, hex-encoded mp3 chunks)."""
import datetime
import json
import random
import requests

from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from config import conf
from voice.voice import Voice


class MinimaxVoice(Voice):
    def __init__(self):
        self.api_key = conf().get("minimax_api_key")
        # Mainland endpoint matches `sk-api-0-...` keys; override via
        # `minimax_api_base` for international (api.minimax.io) workspaces.
        self.api_base = (conf().get("minimax_api_base") or "https://api.minimaxi.com").rstrip("/")
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

            # MiniMax returns HTTP 200 even on errors; capture base_resp for diagnostics.
            audio_chunks = []
            last_base_resp = None
            event_count = 0
            for raw in response.iter_lines():
                if not raw:
                    continue
                event_count += 1
                line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                if not line.startswith("data:"):
                    continue
                json_str = line[5:].strip()
                if not json_str or json_str == "[DONE]":
                    continue
                try:
                    event_data = json.loads(json_str)
                except Exception:
                    continue
                base_resp = event_data.get("base_resp") or {}
                if base_resp:
                    last_base_resp = base_resp
                audio_hex = (event_data.get("data") or {}).get("audio")
                if audio_hex:
                    try:
                        audio_chunks.append(bytes.fromhex(audio_hex))
                    except Exception as e:
                        logger.warning(f"[MINIMAX] skip bad audio hex chunk: {e}")

            if not audio_chunks:
                ct = response.headers.get("Content-Type", "")
                if last_base_resp and last_base_resp.get("status_code") not in (None, 0):
                    logger.error(
                        f"[MINIMAX] TTS failed: status_code={last_base_resp.get('status_code')}, "
                        f"status_msg={last_base_resp.get('status_msg')}, model={model}, voice_id={voice_id}"
                    )
                else:
                    logger.error(
                        f"[MINIMAX] TTS returned no audio data, model={model}, voice_id={voice_id}, "
                        f"url={url}, http={response.status_code}, content_type={ct!r}, events={event_count}"
                    )
                return Reply(ReplyType.ERROR, "语音合成失败，未获取到音频数据")

            audio_data = b"".join(audio_chunks)
            file_name = TmpDir().path() + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + str(random.randint(0, 1000)) + ".mp3"
            with open(file_name, "wb") as f:
                f.write(audio_data)

            logger.info(f"[MINIMAX] textToVoice success, file={file_name}")
            return Reply(ReplyType.VOICE, file_name)

        except Exception as e:
            logger.error(f"[MINIMAX] textToVoice error: {e}")
            return Reply(ReplyType.ERROR, "遇到了一点小问题，请稍后再试")
