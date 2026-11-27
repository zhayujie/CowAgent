# Requires: elevenlabs==1.0.3  (pip install elevenlabs==1.0.3)
import uuid

from elevenlabs.client import ElevenLabs
from elevenlabs import save
from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from voice.voice import Voice
from config import conf

class ElevenLabsVoice(Voice):

    def __init__(self):
        pass

    def voiceToText(self, voice_file):
        pass

    def textToVoice(self, text):
        fileName = TmpDir().path() + "reply-" + uuid.uuid4().hex + ".mp3"

        try:
            client = ElevenLabs(api_key=conf().get("xi_api_key"))
            name = conf().get("xi_voice_id")
            audio = client.generate(
                text=text,
                voice=name,
                model='eleven_multilingual_v2'
            )
            save(audio, fileName)
        except Exception as e:
            # Raising here would drop the text answer too, since this runs while
            # the text reply is being converted to voice.
            logger.error("[ElevenLabs] textToVoice failed: {}".format(e))
            return Reply(ReplyType.ERROR, "抱歉，语音合成失败")

        logger.info("[ElevenLabs] textToVoice text={} voice file name={}".format(text, fileName))
        return Reply(ReplyType.VOICE, fileName)
