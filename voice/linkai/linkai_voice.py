"""LinkAI voice: Whisper ASR + multi-vendor TTS (OpenAI / Doubao / Baidu)
proxied via https://docs.link-ai.tech/platform/api/voice-speech."""
import datetime
import os
import random

import requests

from bridge.reply import Reply, ReplyType
from common import const
from common.log import logger
from common.utils import apply_client_source, apply_cloud_user
from config import conf
from voice import audio_convert
from voice.voice import Voice


class LinkAIVoice(Voice):
    def __init__(self):
        pass

    def voiceToText(self, voice_file):
        logger.debug("[LinkVoice] voice file name={}".format(voice_file))
        try:
            url = conf().get("linkai_api_base", "https://api.link-ai.tech") + "/v1/audio/transcriptions"
            headers = {"Authorization": "Bearer " + conf().get("linkai_api_key")}
            apply_client_source(headers)
            apply_cloud_user(headers)
            # Pin whisper-1: gateway ignores any other ASR model id.
            model = const.WHISPER_1
            if voice_file.endswith(".amr"):
                try:
                    mp3_file = os.path.splitext(voice_file)[0] + ".mp3"
                    audio_convert.any_to_mp3(voice_file, mp3_file)
                    voice_file = mp3_file
                except Exception as e:
                    logger.warning(f"[LinkVoice] amr file transfer failed, directly send amr voice file: {e}")
            with open(voice_file, "rb") as file:
                res = requests.post(
                    url,
                    files={"file": file},
                    headers=headers,
                    data={"model": model},
                    timeout=(5, 60),
                )
            if res.status_code != 200:
                msg = ""
                try:
                    msg = res.json().get("message", "")
                except Exception:
                    pass
                logger.error(f"[LinkVoice] voiceToText error, status_code={res.status_code}, msg={msg}")
                return None
            text = res.json().get("text")
            logger.info(f"[LinkVoice] voiceToText success, text={text}, file name={voice_file}")
            return Reply(ReplyType.TEXT, text)
        except Exception as e:
            logger.error(e)
            return None

    def textToVoice(self, text):
        try:
            url = conf().get("linkai_api_base", "https://api.link-ai.tech") + "/v1/audio/speech"
            headers = {"Authorization": "Bearer " + conf().get("linkai_api_key")}
            apply_client_source(headers)
            apply_cloud_user(headers)
            # Gateway routes by `model` (tts-1 / doubao / baidu) + `voice` from
            # that engine's catalog. `app_code` is optional workspace override.
            data = {
                "input": text,
                "voice": conf().get("tts_voice_id"),
                "app_code": conf().get("linkai_app_code"),
            }
            model = conf().get("text_to_voice_model")
            if model:
                data["model"] = model
            res = requests.post(url, headers=headers, json=data, timeout=(5, 120))
            if res.status_code != 200:
                msg = ""
                try:
                    msg = res.json().get("message", "")
                except Exception:
                    pass
                logger.error(f"[LinkVoice] textToVoice error, status_code={res.status_code}, msg={msg}")
                return None
            tmp_file_name = "tmp/" + datetime.datetime.now().strftime('%Y%m%d%H%M%S') + str(random.randint(0, 1000)) + ".mp3"
            os.makedirs(os.path.dirname(tmp_file_name), exist_ok=True)
            with open(tmp_file_name, 'wb') as f:
                f.write(res.content)
            logger.info(f"[LinkVoice] textToVoice success, input={text}, voice_id={data.get('voice')}")
            return Reply(ReplyType.VOICE, tmp_file_name)
        except Exception as e:
            logger.error(e)
            return None
