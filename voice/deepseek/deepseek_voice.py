# encoding:utf-8
"""
DeepSeek speech: speech recognition (ASR) and speech synthesis (TTS).

Both are plain HTTP tools endpoints authenticated with the chat API key:
- ASR: ``POST {api_base}/tools/asr`` with a multipart ``file`` (16-bit PCM
  WAV or Ogg Opus, up to 8 MiB / 120 s). Language is detected automatically.
- TTS: ``POST {api_base}/tools/tts`` with ``{"text", "voice_id", "format"}``;
  the audio is streamed back in the response body. Language is detected
  automatically and Markdown is stripped server-side by default.

Neither endpoint takes a model id, so voice_to_text_model /
text_to_voice_model are ignored.

Docs:
- https://api-docs.deepseek.com/zh-cn/guides/asr
- https://api-docs.deepseek.com/zh-cn/guides/tts
"""
import datetime
import os
import random
import struct
import tempfile
import wave

import requests

from bridge.reply import Reply, ReplyType
from common.deployment import is_mobile
from common.i18n import t as _t
from common.log import logger
from common.media_download import MAX_FILE_BYTES, MediaTooLargeError, save_response
from common.tmp_dir import TmpDir
from config import conf
from voice import audio_convert, webm_opus
from voice.voice import Voice

DEFAULT_API_BASE = "https://api.deepseek.com/v1"
DEFAULT_TTS_VOICE = "stella"
REQUEST_TIMEOUT = (5, 120)
MAX_ASR_BYTES = 8 * 1024 * 1024
ASR_WAV_RATES = {8000, 16000, 22050, 24000, 32000, 44100, 48000}
ASR_FAILED_MSG = "语音识别失败，请稍后再试"
ASR_FAILED_MSG_EN = "Speech recognition failed, please try again later"
TTS_FAILED_MSG = "语音合成失败，请稍后再试"
TTS_FAILED_MSG_EN = "Speech synthesis failed, please try again later"


class _ConvertError(Exception):
    pass


def _failure(status: int, zh: str, en: str) -> str:
    # Name what the user can fix: a wrong key or an empty balance reads as
    # "try again later" otherwise.
    if status in (401, 403):
        return _t("DeepSeek API Key 无效，请在模型配置中检查", "Invalid DeepSeek API key, please check the model settings")
    if status == 402:
        return _t("DeepSeek 账户余额不足", "Insufficient DeepSeek account balance")
    if status == 429:
        return _t("请求过于频繁，请稍后再试", "Too many requests, please try again later")
    return f"{_t(zh, en)} (HTTP {status})"


def _missing_key() -> str:
    return _t("未配置 DeepSeek API Key", "DeepSeek API key is not configured")


def _unreachable() -> str:
    return _t("无法连接 DeepSeek 语音服务，请检查网络", "Can't reach the DeepSeek speech service, please check the network")


def _api_base() -> str:
    # The tools endpoints only live under /v1, while the chat endpoint also
    # answers on the bare host, so a base configured without it is common.
    base = (conf().get("deepseek_api_base") or DEFAULT_API_BASE).strip().rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return base


def _is_accepted_wav(path: str) -> bool:
    try:
        if os.path.getsize(path) > MAX_ASR_BYTES:
            return False
        with wave.open(path, "rb") as w:
            return (
                w.getsampwidth() == 2
                and w.getcomptype() == "NONE"
                and w.getframerate() in ASR_WAV_RATES
            )
    except Exception:
        return False


def _fix_streamed_wav_header(path: str) -> None:
    # The TTS body is a streamed WAV whose RIFF and data sizes are 0xFFFFFFFF
    # placeholders; the wave module and some players take them literally.
    size = os.path.getsize(path)
    with open(path, "r+b") as f:
        head = f.read(12)
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            return
        pos = 12
        while pos + 8 <= size:
            f.seek(pos)
            chunk_id = f.read(4)
            chunk_size = struct.unpack("<I", f.read(4))[0]
            if chunk_id == b"data":
                f.seek(pos + 4)
                f.write(struct.pack("<I", size - pos - 8))
                f.seek(4)
                f.write(struct.pack("<I", size - 8))
                return
            pos += 8 + chunk_size + (chunk_size & 1)


def _convert_to_wav(src: str, dst: str) -> None:
    if src.lower().endswith((".sil", ".silk", ".slk")):
        audio_convert.sil_to_wav(src, dst)
        return
    if audio_convert.AudioSegment is None:
        raise ImportError("pydub is required for audio conversion. Please install it with: pip install pydub")
    audio = audio_convert.AudioSegment.from_file(src, parameters=["-nostdin"])
    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    audio.export(dst, format="wav", codec="pcm_s16le")


def _temp_path(suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return path


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _prepare_upload(voice_file: str):
    """Return (path, mime, temp_path) of a file the ASR endpoint accepts.

    temp_path is the file created here (None when the input is sent as is).
    """
    if _is_accepted_wav(voice_file):
        return voice_file, "audio/wav", None
    if webm_opus.is_ogg_opus(voice_file) and os.path.getsize(voice_file) <= MAX_ASR_BYTES:
        return voice_file, "audio/ogg", None
    if webm_opus.is_webm(voice_file):
        # Browser recordings: repack the Opus stream, which needs no ffmpeg.
        ogg = _temp_path(".ogg")
        try:
            webm_opus.webm_to_ogg(voice_file, ogg)
            return ogg, "audio/ogg", ogg
        except Exception as e:
            _remove_quietly(ogg)
            logger.warning(f"[DeepSeekVoice] webm remux failed, converting instead: {e}")
    # amr / silk / mp3 / m4a etc.: normalize to 16 kHz mono 16-bit PCM WAV.
    wav = _temp_path(".wav")
    try:
        _convert_to_wav(voice_file, wav)
    except Exception as e:
        _remove_quietly(wav)
        raise _ConvertError(str(e)) from e
    return wav, "audio/wav", wav


class DeepSeekVoice(Voice):
    def __init__(self):
        pass

    def voiceToText(self, voice_file: str):
        converted = None
        try:
            api_key = conf().get("deepseek_api_key", "")
            if not api_key:
                logger.error("[DeepSeekVoice] deepseek_api_key is not configured")
                return Reply(ReplyType.ERROR, _missing_key())

            upload, mime, converted = _prepare_upload(voice_file)

            url = f"{_api_base()}/tools/asr"
            with open(upload, "rb") as f:
                response = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (os.path.basename(upload), f, mime)},
                    timeout=REQUEST_TIMEOUT,
                )
            if response.status_code != 200:
                logger.error(
                    f"[DeepSeekVoice] voiceToText failed: status={response.status_code} "
                    f"body={response.text[:500]}"
                )
                return Reply(ReplyType.ERROR, _failure(response.status_code, ASR_FAILED_MSG, ASR_FAILED_MSG_EN))

            data = response.json()
            text = data.get("text") if isinstance(data, dict) else None
            if not isinstance(text, str) or not text.strip():
                logger.warning(f"[DeepSeekVoice] voiceToText empty text: {data}")
                return Reply(ReplyType.ERROR, _t("没有识别到说话内容，请再说一次", "No speech detected, please try again"))

            text = text.strip()
            logger.info(
                f"[DeepSeekVoice] voiceToText text={text} duration_ms={data.get('duration_ms')}"
            )
            return Reply(ReplyType.TEXT, text)
        except _ConvertError as e:
            logger.error(f"[DeepSeekVoice] voiceToText can't convert {voice_file}: {e}")
            # Inside the phone app there is no ffmpeg to install.
            if is_mobile():
                return Reply(ReplyType.ERROR, _t("暂不支持识别该录音格式", "This recording format isn't supported"))
            return Reply(ReplyType.ERROR, _t(
                "无法转换该录音格式，请安装 ffmpeg 后重试",
                "Can't convert this recording, please install ffmpeg and try again",
            ))
        except requests.RequestException as e:
            logger.error(f"[DeepSeekVoice] voiceToText request failed: {e}")
            return Reply(ReplyType.ERROR, _unreachable())
        except Exception as e:
            logger.exception(f"[DeepSeekVoice] voiceToText exception: {e}")
            return Reply(ReplyType.ERROR, _t(ASR_FAILED_MSG, ASR_FAILED_MSG_EN))
        finally:
            if converted:
                _remove_quietly(converted)

    def textToVoice(self, text: str):
        try:
            api_key = conf().get("deepseek_api_key", "")
            if not api_key:
                logger.error("[DeepSeekVoice] deepseek_api_key is not configured")
                return Reply(ReplyType.ERROR, _missing_key())

            # tts_voice_id belongs to whichever vendor was picked explicitly;
            # when DeepSeek is only the auto-picked fallback it may name another
            # vendor's timbre, which this endpoint would reject.
            voice_id = DEFAULT_TTS_VOICE
            if (conf().get("text_to_voice") or "").strip().lower() == "deepseek":
                voice_id = (conf().get("tts_voice_id") or "").strip() or DEFAULT_TTS_VOICE

            response = requests.post(
                f"{_api_base()}/tools/tts",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"text": text, "voice_id": voice_id, "format": "wav"},
                timeout=REQUEST_TIMEOUT,
                stream=True,
            )
            if response.status_code != 200:
                logger.error(
                    f"[DeepSeekVoice] textToVoice failed: status={response.status_code} "
                    f"body={response.text[:500]} voice={voice_id}"
                )
                response.close()
                return Reply(ReplyType.ERROR, _failure(response.status_code, TTS_FAILED_MSG, TTS_FAILED_MSG_EN))

            file_name = (
                TmpDir().path() + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                + str(random.randint(0, 1000)) + ".wav"
            )
            # A synthesis failure after streaming started cuts the connection;
            # save_response raises then and never leaves a truncated file behind.
            try:
                result = save_response(response, file_name, MAX_FILE_BYTES)
            except MediaTooLargeError:
                logger.error(f"[DeepSeekVoice] textToVoice audio too large: over {MAX_FILE_BYTES} bytes")
                return Reply(ReplyType.ERROR, _t(TTS_FAILED_MSG, TTS_FAILED_MSG_EN))
            if result.size == 0:
                logger.error("[DeepSeekVoice] textToVoice returned empty audio")
                os.remove(file_name)
                return Reply(ReplyType.ERROR, _t(TTS_FAILED_MSG, TTS_FAILED_MSG_EN))
            _fix_streamed_wav_header(file_name)

            logger.info(
                f"[DeepSeekVoice] textToVoice voice={voice_id} file={file_name} bytes={result.size}"
            )
            return Reply(ReplyType.VOICE, file_name)
        except requests.RequestException as e:
            logger.error(f"[DeepSeekVoice] textToVoice request failed: {e}")
            return Reply(ReplyType.ERROR, _unreachable())
        except Exception as e:
            logger.exception(f"[DeepSeekVoice] textToVoice exception: {e}")
            return Reply(ReplyType.ERROR, _t(TTS_FAILED_MSG, TTS_FAILED_MSG_EN))
