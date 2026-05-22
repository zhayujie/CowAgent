#####################################################################
#    xunfei voice service
#     Auth: njnuko
#     Email: njnuko@163.com
#
#    要使用本模块, 首先到 xfyun.cn 注册一个开发者账号,
#    之后创建一个新应用, 然后在应用管理的语音识别或者语音合同右边可以查看APPID API Key 和 Secret Key
#    然后在 config.json 中填入这三个值
#
#    配置说明：
# {
#  "APPID":"xxx71xxx",
#  "APIKey":"xxxx69058exxxxxx",  #讯飞xfyun.cn控制台语音合成或者听写界面的APIKey
#  "APISecret":"xxxx697f0xxxxxx",  #讯飞xfyun.cn控制台语音合成或者听写界面的APIKey
#  "BusinessArgsTTS":{"aue": "lame", "sfl": 1, "auf": "audio/L16;rate=16000", "vcn": "xiaoyan", "tte": "utf8"}, #语音合成的参数，具体可以参考xfyun.cn的文档
#  "BusinessArgsASR":{"domain": "iat", "language": "zh_cn", "accent": "mandarin", "vad_eos":10000, "dwa": "wpgs"}  #语音听写的参数，具体可以参考xfyun.cn的文档
# }
#####################################################################

import json
import os
import time

from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from config import conf
from voice.voice import Voice
from .xunfei_asr import xunfei_asr
from .xunfei_tts import xunfei_tts
import shutil

try:
    from voice.audio_convert import any_to_mp3
    from pydub import AudioSegment
    _audio_available = True
except ImportError as e:
    logger.debug("import audio libraries failed: {}".format(e))
    _audio_available = False


class XunfeiVoice(Voice):
    def __init__(self):
        try:
            curdir = os.path.dirname(__file__)
            config_path = os.path.join(curdir, "config.json")
            conf = None
            with open(config_path, "r") as fr:
                conf = json.load(fr)
            print(conf)
            self.APPID = str(conf.get("APPID"))
            self.APIKey = str(conf.get("APIKey"))
            self.APISecret = str(conf.get("APISecret"))
            self.BusinessArgsTTS = conf.get("BusinessArgsTTS")
            self.BusinessArgsASR= conf.get("BusinessArgsASR")

        except Exception as e:
            logger.warn("XunfeiVoice init failed: %s, ignore " % e)

    def voiceToText(self, voice_file):
        # 识别本地文件
        try:
            logger.debug("[Xunfei] voice file name={}".format(voice_file))
            #print("voice_file===========",voice_file)
            #print("voice_file_type===========",type(voice_file))
            #mp3_name, file_extension = os.path.splitext(voice_file)
            #mp3_file = mp3_name + ".mp3"
            #pcm_data=get_pcm_from_wav(voice_file)
            #mp3_name, file_extension = os.path.splitext(voice_file)
            #AudioSegment.from_wav(voice_file).export(mp3_file, format="mp3")
            #shutil.copy2(voice_file, 'tmp/test1.wav')
            #shutil.copy2(mp3_file, 'tmp/test1.mp3')
            #print("voice and mp3 file",voice_file,mp3_file)
            text = xunfei_asr(self.APPID,self.APISecret,self.APIKey,self.BusinessArgsASR,voice_file)
            logger.info("讯飞语音识别到了: {}".format(text))
            reply = Reply(ReplyType.TEXT, text)
        except Exception as e:
            logger.warn("XunfeiVoice init failed: %s, ignore " % e)
            reply = Reply(ReplyType.ERROR, "讯飞语音识别出错了；{0}")
        return reply

    def textToVoice(self, text):
        try:
            # Avoid the same filename under multithreading
            fileName = TmpDir().path() + "reply-" + str(int(time.time())) + "-" + str(hash(text) & 0x7FFFFFFF) + ".mp3"
            return_file = xunfei_tts(self.APPID,self.APIKey,self.APISecret,self.BusinessArgsTTS,text,fileName)
            logger.info("[Xunfei] textToVoice text={} voice file name={}".format(text, fileName))
            reply = Reply(ReplyType.VOICE, fileName)
        except Exception as e:
            logger.error("[Xunfei] textToVoice error={}".format(fileName))
            reply = Reply(ReplyType.ERROR, "抱歉，讯飞语音合成失败")
        return reply
