"""
google voice service
"""

from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf
from voice.voice import Voice
import requests
from common import const
from common.tmp_dir import TmpDir
import datetime, random

# Connect 5s, read 60s. Bounded like every other HTTP voice backend
# (voice/zhipuai, voice/mimo, voice/linkai): a stalled transcription or
# synthesis call would otherwise block the reply thread indefinitely.
REQUEST_TIMEOUT = (5, 60)


class OpenaiVoice(Voice):
    def __init__(self):
        # No-op: this implementation calls OpenAI HTTP endpoints directly via
        # `requests`, so it does not need a global SDK to be configured.
        pass

    def voiceToText(self, voice_file):
        logger.debug("[Openai] voice file name={}".format(voice_file))
        try:
            api_base = conf().get("open_ai_api_base") or "https://api.openai.com/v1"
            url = f'{api_base}/audio/transcriptions'
            headers = {
                'Authorization': 'Bearer ' + conf().get("open_ai_api_key"),
                # 'Content-Type': 'multipart/form-data' # 加了会报错，不知道什么原因
            }
            data = {
                # Override via `voice_to_text_model` (e.g. fall back to whisper-1).
                "model": conf().get("voice_to_text_model") or "gpt-4o-mini-transcribe",
            }
            # The handle has to stay open for the whole request, and it must be
            # closed when this returns rather than left to the reference counter:
            # on Windows an open read handle keeps the file undeletable for as
            # long as it lives.
            with open(voice_file, "rb") as file:
                response = requests.post(
                    url,
                    headers=headers,
                    files={"file": file},
                    data=data,
                    timeout=REQUEST_TIMEOUT,
                )
            try:
                response_data = response.json()
            except ValueError:
                # A gateway in front of the API answers with a non-JSON body
                # (an HTML error page, plain text) on failure. Keep that body
                # reportable instead of letting the decode error mask the
                # status code that explains what actually went wrong.
                response_data = {"raw": response.text[:200]}
            if response.status_code != 200 or "text" not in response_data:
                logger.error(
                    f"[Openai] voiceToText failed: status={response.status_code}, "
                    f"resp={response_data}"
                )
                reply = Reply(ReplyType.ERROR, "我暂时还无法听清您的语音，请稍后再试吧~")
            else:
                text = response_data["text"]
                reply = Reply(ReplyType.TEXT, text)
                logger.info("[Openai] voiceToText text={} voice file name={}".format(text, voice_file))
        except Exception as e:
            logger.error(f"[Openai] voiceToText exception: {e}", exc_info=True)
            reply = Reply(ReplyType.ERROR, "我暂时还无法听清您的语音，请稍后再试吧~")
        finally:
            return reply


    def textToVoice(self, text):
        try:
            api_base = conf().get("open_ai_api_base") or "https://api.openai.com/v1"
            url = f'{api_base}/audio/speech'
            headers = {
                'Authorization': 'Bearer ' + conf().get("open_ai_api_key"),
                'Content-Type': 'application/json'
            }
            data = {
                'model': conf().get("text_to_voice_model") or const.TTS_1,
                'input': text,
                'voice': conf().get("tts_voice_id") or "alloy"
            }
            response = requests.post(url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
            file_name = TmpDir().path() + datetime.datetime.now().strftime('%Y%m%d%H%M%S') + str(random.randint(0, 1000)) + ".mp3"
            logger.debug(f"[OPENAI] text_to_Voice file_name={file_name}, input={text}")
            with open(file_name, 'wb') as f:
                f.write(response.content)
            logger.info("[OPENAI] text_to_Voice success")
            reply = Reply(ReplyType.VOICE, file_name)
        except Exception as e:
            logger.error(e)
            reply = Reply(ReplyType.ERROR, "遇到了一点小问题，请稍后再问我吧")
        return reply
