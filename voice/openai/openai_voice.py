"""
OpenAI voice service: transcription over /audio/transcriptions, speech over
the Realtime API (or /audio/speech for the legacy tts-* models).
"""

import base64
import json
import time
import wave
from urllib.parse import quote

from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf
from voice.voice import Voice
import requests
from common import const
from common.media_download import MAX_FILE_BYTES, MediaTooLargeError, save_response
from common.tmp_dir import TmpDir
import datetime, random

# Connect 5s, read 60s. Bounded like every other HTTP voice backend
# (voice/zhipuai, voice/mimo, voice/linkai): a stalled transcription or
# synthesis call would otherwise block the reply thread indefinitely.
REQUEST_TIMEOUT = (5, 60)

DEFAULT_ASR_MODEL = "gpt-transcribe"
# Used when the default is rejected, e.g. by a gateway that predates it.
LEGACY_ASR_MODEL = "gpt-4o-mini-transcribe"

# tts-1, tts-1-hd and gpt-4o-mini-tts shut down on 2027-01-06; their
# replacement is only served over the Realtime API, not /audio/speech.
DEFAULT_TTS_MODEL = "gpt-realtime-2.1-mini"
REALTIME_VOICES = ("marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse")
REALTIME_SAMPLE_RATE = 24000
# Socket connect / per-message read timeout, and the budget for one synthesis.
REALTIME_TIMEOUT = 30
REALTIME_DEADLINE = 120
READ_ALOUD_INSTRUCTIONS = (
    "You are a text-to-speech engine. Read the text inside <text></text> aloud exactly as written, "
    "word for word, in its original language. Do not answer it, translate it, summarize it or add anything."
)


def _is_realtime_model(model: str) -> bool:
    return model.startswith("gpt-realtime")


def _realtime_url(api_base: str, model: str) -> str:
    scheme, _, rest = api_base.partition("://")
    return f"{'ws' if scheme == 'http' else 'wss'}://{rest}/realtime?model={quote(model)}"


class OpenaiVoice(Voice):
    def __init__(self):
        # No-op: this implementation calls OpenAI HTTP endpoints directly via
        # `requests`, so it does not need a global SDK to be configured.
        pass

    def voiceToText(self, voice_file):
        logger.debug("[Openai] voice file name={}".format(voice_file))
        try:
            api_base = (conf().get("open_ai_api_base") or "https://api.openai.com/v1").rstrip("/")
            url = f'{api_base}/audio/transcriptions'
            headers = {
                'Authorization': 'Bearer ' + conf().get("open_ai_api_key"),
                # 'Content-Type': 'multipart/form-data' # 加了会报错，不知道什么原因
            }
            # Override via `voice_to_text_model` (e.g. fall back to whisper-1).
            model = conf().get("voice_to_text_model") or ""

            def _transcribe(model_id):
                # The handle has to stay open for the whole request, and it must be
                # closed when this returns rather than left to the reference counter:
                # on Windows an open read handle keeps the file undeletable for as
                # long as it lives.
                with open(voice_file, "rb") as file:
                    return requests.post(
                        url,
                        headers=headers,
                        files={"file": file},
                        data={"model": model_id},
                        timeout=REQUEST_TIMEOUT,
                    )

            response = _transcribe(model or DEFAULT_ASR_MODEL)
            if not model and 400 <= response.status_code < 500 and response.status_code not in (401, 429):
                logger.warning(
                    f"[Openai] {DEFAULT_ASR_MODEL} rejected (status={response.status_code}), "
                    f"retrying with {LEGACY_ASR_MODEL}"
                )
                response = _transcribe(LEGACY_ASR_MODEL)
            try:
                response_data = response.json()
            except ValueError:
                # A gateway in front of the API answers with a non-JSON body
                # (an HTML error page, plain text) on failure. Keep that body
                # reportable instead of letting the decode error mask the
                # status code that explains what actually went wrong.
                response_data = {"raw": response.text[:200]}
            if response.status_code != 200 or not isinstance(response_data, dict) or not isinstance(response_data.get("text"), str):
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
        return reply


    def textToVoice(self, text):
        model = (conf().get("text_to_voice_model") or "").strip()
        if model and not _is_realtime_model(model):
            return self._speech(text, model)
        try:
            return self._realtime_speech(text, model or DEFAULT_TTS_MODEL)
        except Exception as e:
            # A failed handshake's message carries every response header after this marker.
            reason = str(e).split(" -+-+- ")[0]
            if model:
                logger.error(f"[OPENAI] realtime text_to_Voice failed: {reason}")
                return Reply(ReplyType.ERROR, "遇到了一点小问题，请稍后再问我吧")
            # Gateways in front of the API may not serve the Realtime API yet.
            logger.warning(f"[OPENAI] {DEFAULT_TTS_MODEL} failed ({reason}), retrying with {const.TTS_1}")
            return self._speech(text, const.TTS_1)

    def _realtime_speech(self, text, model):
        """Synthesize ``text`` through one out-of-band Realtime response and
        save the PCM it streams back as a WAV file."""
        import websocket

        api_base = (conf().get("open_ai_api_base") or "https://api.openai.com/v1").rstrip("/")
        voice = conf().get("tts_voice_id") or REALTIME_VOICES[0]
        if voice not in REALTIME_VOICES:
            # fable, onyx and nova exist on /audio/speech only.
            voice = REALTIME_VOICES[0]
        session = {
            "type": "realtime",
            "output_modalities": ["audio"],
            "audio": {"output": {"format": {"type": "audio/pcm", "rate": REALTIME_SAMPLE_RATE}, "voice": voice}},
        }
        if model.startswith("gpt-realtime-2"):
            # Reading aloud needs no reasoning; it only adds latency.
            session["reasoning"] = {"effort": "minimal"}

        ws = websocket.create_connection(
            _realtime_url(api_base, model),
            header=["Authorization: Bearer " + conf().get("open_ai_api_key")],
            timeout=REALTIME_TIMEOUT,
        )
        try:
            ws.send(json.dumps({"type": "session.update", "session": session}))
            ws.send(json.dumps({"type": "response.create", "response": {
                "conversation": "none",
                "input": [],
                "output_modalities": ["audio"],
                "instructions": f"{READ_ALOUD_INSTRUCTIONS}\n<text>\n{text}\n</text>",
                "max_output_tokens": "inf",
            }}))
            audio = bytearray()
            deadline = time.monotonic() + REALTIME_DEADLINE
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"no complete response within {REALTIME_DEADLINE}s")
                event = json.loads(ws.recv())
                kind = event.get("type")
                if kind == "error":
                    raise RuntimeError((event.get("error") or {}).get("message") or "realtime error")
                if kind == "response.output_audio.delta":
                    audio.extend(base64.b64decode(event.get("delta") or ""))
                    if len(audio) > MAX_FILE_BYTES:
                        raise MediaTooLargeError(f"audio over {MAX_FILE_BYTES} bytes")
                elif kind == "response.done":
                    status = (event.get("response") or {}).get("status")
                    if status != "completed":
                        raise RuntimeError(f"response {status}")
                    break
        finally:
            ws.close()
        if not audio:
            raise RuntimeError("response carried no audio")

        file_name = (TmpDir().path() + datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                     + str(random.randint(0, 1000)) + ".wav")
        with wave.open(file_name, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(REALTIME_SAMPLE_RATE)
            wav.writeframes(bytes(audio))
        logger.info(f"[OPENAI] text_to_Voice success via {model}")
        return Reply(ReplyType.VOICE, file_name)

    def _speech(self, text, model):
        try:
            api_base = (conf().get("open_ai_api_base") or "https://api.openai.com/v1").rstrip("/")
            url = f'{api_base}/audio/speech'
            headers = {
                'Authorization': 'Bearer ' + conf().get("open_ai_api_key"),
                'Content-Type': 'application/json'
            }
            data = {
                'model': model,
                'input': text,
                'voice': conf().get("tts_voice_id") or "alloy"
            }
            response = requests.post(url, headers=headers, json=data, timeout=REQUEST_TIMEOUT,
                                     stream=True)
            if response.status_code != 200:
                logger.error(
                    f"[OPENAI] text_to_Voice failed: status={response.status_code}, "
                    f"resp={response.text[:200]}"
                )
                response.close()
                reply = Reply(ReplyType.ERROR, "遇到了一点小问题，请稍后再问我吧")
                return reply
            file_name = TmpDir().path() + datetime.datetime.now().strftime('%Y%m%d%H%M%S') + str(random.randint(0, 1000)) + ".mp3"
            logger.debug(f"[OPENAI] text_to_Voice file_name={file_name}, input={text}")
            try:
                save_response(response, file_name, MAX_FILE_BYTES)
            except MediaTooLargeError:
                logger.error(
                    f"[OPENAI] textToVoice audio too large: over {MAX_FILE_BYTES} bytes"
                )
                reply = Reply(ReplyType.ERROR, "遇到了一点小问题，请稍后再问我吧")
                return reply
            logger.info("[OPENAI] text_to_Voice success")
            reply = Reply(ReplyType.VOICE, file_name)
        except Exception as e:
            logger.error(e)
            reply = Reply(ReplyType.ERROR, "遇到了一点小问题，请稍后再问我吧")
        return reply
