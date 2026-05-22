import json
import base64
import os
import time
from voice.voice import Voice
from common.log import logger
from tencentcloud.common import credential
from tencentcloud.asr.v20190614 import asr_client, models as asr_models
from tencentcloud.tts.v20190823 import tts_client, models as tts_models
from bridge.reply import Reply, ReplyType
from common.tmp_dir import TmpDir

class TencentVoice(Voice):
    def __init__(self):
        super().__init__()
        self.secret_id = None
        self.secret_key = None
        self.voice_type = 1003
        self._load_config()
        
    def _load_config(self):
        """
        从本地配置文件加载配置
        """
        try:
            config_path = os.path.join(os.path.dirname(__file__), 'config.json')
            with open(config_path, 'r') as f:
                config = json.load(f)
            self.secret_id = config.get('secret_id')
            self.secret_key = config.get('secret_key')
            self.voice_type = config.get('voice_type', self.voice_type)
            if not self.secret_id or not self.secret_key:
                logger.error("[Tencent] Missing credentials in config.json")
        except Exception as e:
            logger.error(f"[Tencent] Failed to load config: {e}")
    
    def setup(self, config):
        """
        设置配置信息（保留此方法用于向后兼容）
        """
        pass
        
    def voiceToText(self, voice_file):
        """
        将语音文件转换为文本
        """
        try:
            # 实例化认证对象
            cred = credential.Credential(self.secret_id, self.secret_key)
            
            # 实例化客户端
            client = asr_client.AsrClient(cred, "ap-guangzhou")
            
            # 读取音频文件
            with open(voice_file, 'rb') as f:
                audio_data = f.read()
            
            # 进行base64编码
            base64_audio = base64.b64encode(audio_data).decode('utf-8')
            
            # 构造请求对象
            req = asr_models.SentenceRecognitionRequest()
            req.ProjectId = 0
            req.SubServiceType = 2
            req.EngSerViceType = "16k_zh"
            req.SourceType = 1
            req.VoiceFormat = "wav"
            req.UsrAudioKey = "voice_recognition"
            req.Data = base64_audio
            
            # 发起请求
            resp = client.SentenceRecognition(req)
            
            # 解析结果
            if resp.Result:
                logger.info("[Tencent] Voice to text success: {}".format(resp.Result))
                return Reply(ReplyType.TEXT, resp.Result)
            else:
                logger.warning("[Tencent] Voice to text failed")
                return Reply(ReplyType.ERROR, "腾讯语音识别失败")
            
        except Exception as e:
            logger.error("[Tencent] Voice to text error: {}".format(e))
            return Reply(ReplyType.ERROR, "腾讯语音识别出错：{}".format(str(e)))

    def textToVoice(self, text):
        """
        将文本转换为语音
        """
        try:
            cred = credential.Credential(self.secret_id, self.secret_key)
            client = tts_client.TtsClient(cred, "ap-guangzhou")

            req = tts_models.TextToVoiceRequest()
            req.Text = text
            req.SessionId = str(int(time.time()))
            req.Volume = 5
            req.Speed = 0
            req.ProjectId = 0
            req.ModelType = 1
            req.PrimaryLanguage = 1
            req.SampleRate = 16000
            req.VoiceType = self.voice_type  # 客服女声

            response = client.TextToVoice(req)
            
            if response.Audio:
                fileName = TmpDir().path() + "reply-" + str(int(time.time())) + "-" + str(hash(text) & 0x7FFFFFFF) + ".mp3"
                with open(fileName, "wb") as f:
                    f.write(base64.b64decode(response.Audio))
                logger.info("[Tencent] textToVoice text={} voice file name={}".format(text, fileName))
                return Reply(ReplyType.VOICE, fileName)
            else:
                logger.error("[Tencent] textToVoice failed")
                return Reply(ReplyType.ERROR, "腾讯语音合成失败")

        except Exception as e:
            logger.error("[Tencent] Text to voice error: {}".format(e))
            return Reply(ReplyType.ERROR, "腾讯语音合成出错：{}".format(str(e)))
