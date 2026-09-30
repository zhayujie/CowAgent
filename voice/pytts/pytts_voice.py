"""
pytts voice service (offline)
"""

import os
import sys
import time

import pyttsx3

from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from voice.voice import Voice


class PyttsVoice(Voice):
    engine = pyttsx3.init()

    def __init__(self):
        # 语速
        self.engine.setProperty("rate", 125)
        # 音量
        self.engine.setProperty("volume", 1.0)
        if sys.platform == "win32":
            for voice in self.engine.getProperty("voices"):
                if "Chinese" in voice.name:
                    self.engine.setProperty("voice", voice.id)
        else:
            self.engine.setProperty("voice", "zh")
            # If the problem of espeak is fixed, using runAndWait() and remove this startLoop()
            # TODO: check if this is work on win32
            self.engine.startLoop(useDriverLoop=False)

    def textToVoice(self, text):
        try:
            # Avoid the same filename under multithreading
            wavFileName = "reply-" + str(int(time.time())) + "-" + str(hash(text) & 0x7FFFFFFF) + ".wav"
            wavFile = TmpDir().path() + wavFileName
            logger.info("[Pytts] textToVoice text={} voice file name={}".format(text, wavFile))

            self.engine.save_to_file(text, wavFile)

            if sys.platform == "win32":
                self.engine.runAndWait()
            else:
                # In ubuntu, runAndWait do not really wait until the file created.
                # It will return once the task queue is empty, but the task is still running in coroutine.
                # And if you call runAndWait() and time.sleep() twice, it will stuck, so do not use this.
                # If you want to fix this, add self._proxy.setBusy(True) in line 127 in espeak.py, at the beginning of the function save_to_file.
                # self.engine.runAndWait()

                # Before espeak fix this problem, we iterate the generator and control the waiting by ourself.
                # But this is not the canonical way to use it, for example if the file already exists it also cannot wait.
                self.engine.iterate()
                while self.engine.isBusy() or wavFileName not in os.listdir(TmpDir().path()):
                    time.sleep(0.1)

            reply = Reply(ReplyType.VOICE, wavFile)

        except Exception as e:
            reply = Reply(ReplyType.ERROR, str(e))
        return reply
