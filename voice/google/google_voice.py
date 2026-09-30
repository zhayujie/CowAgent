"""
google voice service
"""

import time

import speech_recognition
from gtts import gTTS

from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from voice.voice import Voice


class GoogleVoice(Voice):
    recognizer = speech_recognition.Recognizer()

    def __init__(self):
        pass

    def voiceToText(self, voice_file):
        with speech_recognition.AudioFile(voice_file) as source:
            audio = self.recognizer.record(source)
        try:
            text = self.recognizer.recognize_google(audio, language="zh-CN")
            logger.info("[Google] voiceToText text={} voice file name={}".format(text, voice_file))
            return Reply(ReplyType.TEXT, text)
        except speech_recognition.UnknownValueError:
            return Reply(ReplyType.ERROR, "抱歉，我听不懂")
        except speech_recognition.RequestError as e:
            return Reply(ReplyType.ERROR, "抱歉，无法连接到 Google 语音识别服务；{0}".format(e))
        except Exception as e:
            # Anything else used to hit `finally: return reply` with `reply`
            # unbound, so the caller saw UnboundLocalError instead of the cause.
            logger.error("[Google] voiceToText exception: {0}".format(e), exc_info=True)
            return Reply(ReplyType.ERROR, "抱歉，我暂时听不清您的语音，请稍后再试吧~")

    def textToVoice(self, text):
        try:
            # Avoid the same filename under multithreading
            mp3File = TmpDir().path() + "reply-" + str(int(time.time())) + "-" + str(hash(text) & 0x7FFFFFFF) + ".mp3"
            tts = gTTS(text=text, lang="zh")
            tts.save(mp3File)
            logger.info("[Google] textToVoice text={} voice file name={}".format(text, mp3File))
            return Reply(ReplyType.VOICE, mp3File)
        except Exception as e:
            return Reply(ReplyType.ERROR, str(e))
