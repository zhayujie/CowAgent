"""
azure voice service
"""
import json
import os
import time

import azure.cognitiveservices.speech as speechsdk
from langid import classify

from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from config import conf
from voice.voice import Voice

"""
Azure voice
主目录设置文件中需填写azure_voice_api_key和azure_voice_region

查看可用的 voice： https://speech.microsoft.com/portal/voicegallery

"""


class AzureVoice(Voice):
    def __init__(self):
        try:
            curdir = os.path.dirname(__file__)
            config_path = os.path.join(curdir, "config.json")
            config = None
            if not os.path.exists(config_path):  # 如果没有配置文件，创建本地配置文件
                config = {
                    "speech_synthesis_voice_name": "zh-CN-XiaoxiaoNeural",  # 识别不出时的默认语音
                    "auto_detect": True,  # 是否自动检测语言
                    "speech_synthesis_zh": "zh-CN-XiaozhenNeural",
                    "speech_synthesis_en": "en-US-JacobNeural",
                    "speech_synthesis_ja": "ja-JP-AoiNeural",
                    "speech_synthesis_ko": "ko-KR-SoonBokNeural",
                    "speech_synthesis_de": "de-DE-LouisaNeural",
                    "speech_synthesis_fr": "fr-FR-BrigitteNeural",
                    "speech_synthesis_es": "es-ES-LaiaNeural",
                    "speech_recognition_language": "zh-CN",
                }
                with open(config_path, "w") as fw:
                    json.dump(config, fw, indent=4)
            else:
                with open(config_path, "r") as fr:
                    config = json.load(fr)
            self.config = config
            self.api_key = conf().get("azure_voice_api_key")
            self.api_region = conf().get("azure_voice_region")
            self.speech_config = speechsdk.SpeechConfig(subscription=self.api_key, region=self.api_region)
            self.speech_config.speech_synthesis_voice_name = self.config["speech_synthesis_voice_name"]
            self.speech_config.speech_recognition_language = self.config["speech_recognition_language"]
        except Exception as e:
            logger.warn("AzureVoice init failed: %s, ignore " % e)

    def voiceToText(self, voice_file):
        audio_config = speechsdk.AudioConfig(filename=voice_file)
        speech_recognizer = speechsdk.SpeechRecognizer(speech_config=self.speech_config, audio_config=audio_config)
        result = speech_recognizer.recognize_once()
        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            logger.info("[Azure] voiceToText voice file name={} text={}".format(voice_file, result.text))
            reply = Reply(ReplyType.TEXT, result.text)
        else:
            cancel_details = result.cancellation_details
            logger.error("[Azure] voiceToText error, result={}, errordetails={}".format(result, cancel_details))
            reply = Reply(ReplyType.ERROR, "抱歉，语音识别失败")
        return reply

    def textToVoice(self, text):
        if self.config.get("auto_detect"):
            lang = classify(text)[0]
            key = "speech_synthesis_" + lang
            if key in self.config:
                logger.info("[Azure] textToVoice auto detect language={}, voice={}".format(lang, self.config[key]))
                self.speech_config.speech_synthesis_voice_name = self.config[key]
            else:
                self.speech_config.speech_synthesis_voice_name = self.config["speech_synthesis_voice_name"]
        else:
            self.speech_config.speech_synthesis_voice_name = self.config["speech_synthesis_voice_name"]
        # Avoid the same filename under multithreading
        fileName = TmpDir().path() + "reply-" + str(int(time.time())) + "-" + str(hash(text) & 0x7FFFFFFF) + ".wav"
        audio_config = speechsdk.AudioConfig(filename=fileName)
        speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=self.speech_config, audio_config=audio_config)
        result = speech_synthesizer.speak_text(text)
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            logger.info("[Azure] textToVoice text={} voice file name={}".format(text, fileName))
            reply = Reply(ReplyType.VOICE, fileName)
        else:
            cancel_details = result.cancellation_details
            logger.error("[Azure] textToVoice error, result={}, errordetails={}".format(result, cancel_details.error_details))
            reply = Reply(ReplyType.ERROR, "抱歉，语音合成失败")
        return reply
