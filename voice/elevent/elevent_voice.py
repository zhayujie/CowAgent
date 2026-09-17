# Requires: elevenlabs==1.0.3  (pip install elevenlabs==1.0.3)
import time

from elevenlabs.client import ElevenLabs
from elevenlabs import save
from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from voice.voice import Voice
from config import conf

XI_API_KEY = conf().get("xi_api_key")
client = ElevenLabs(api_key=XI_API_KEY)
name = conf().get("xi_voice_id")

class ElevenLabsVoice(Voice):

    def __init__(self):
        pass

    def voiceToText(self, voice_file):
        pass

    def textToVoice(self, text):
        audio = client.generate(
            text=text,
            voice=name,
            model='eleven_multilingual_v2'
        )
        fileName = TmpDir().path() + "reply-" + str(int(time.time())) + "-" + str(hash(text) & 0x7FFFFFFF) + ".mp3"
        save(audio, fileName)
        logger.info("[ElevenLabs] textToVoice text={} voice file name={}".format(text, fileName))
        return Reply(ReplyType.VOICE, fileName)
