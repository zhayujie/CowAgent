"""
baidu voice service with thread-safe token caching
"""
import json
import os
import time
import threading
import requests

from aip import AipSpeech

from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from config import conf
from voice.voice import Voice

try:
    from voice.audio_convert import get_pcm_from_wav
except ImportError as e:
    logger.debug("import voice.audio_convert failed: {}".format(e))

class BaiduVoice(Voice):
    def __init__(self):
        try:
            # 读取本地 TTS 参数配置
            curdir = os.path.dirname(__file__)
            config_path = os.path.join(curdir, "config.json")
            if not os.path.exists(config_path):
                bconf = {"lang": "zh", "ctp": 1, "spd": 5, "pit": 5, "vol": 5, "per": 0}
                with open(config_path, "w") as fw:
                    json.dump(bconf, fw, indent=4)
            else:
                with open(config_path, "r") as fr:
                    bconf = json.load(fr)

            self.app_id = str(conf().get("baidu_app_id"))
            self.api_key = str(conf().get("baidu_api_key"))
            self.secret_key = str(conf().get("baidu_secret_key"))
            self.dev_id = conf().get("baidu_dev_pid")

            self.lang = bconf["lang"]
            self.ctp  = bconf["ctp"]
            self.spd  = bconf["spd"]
            self.pit  = bconf["pit"]
            self.vol  = bconf["vol"]
            self.per  = bconf["per"]

            # 百度 SDK 客户端（短文本合成 & 语音识别）
            self.client = AipSpeech(self.app_id, self.api_key, self.secret_key)

            # access_token 缓存与锁
            self._access_token    = None
            self._token_expire_ts = 0
            self._token_lock      = threading.Lock()
        except Exception as e:
            logger.warn("BaiduVoice init failed: %s, ignore" % e)

    def _get_access_token(self):
        # 多线程安全获取 token
        with self._token_lock:
            now = time.time()
            if self._access_token and now < self._token_expire_ts:
                return self._access_token
            url = "https://aip.baidubce.com/oauth/2.0/token"
            params = {
                "grant_type":    "client_credentials",
                "client_id":     self.api_key,
                "client_secret": self.secret_key,
            }
            resp = requests.post(url, params=params).json()
            token = resp.get("access_token")
            expires_in = resp.get("expires_in", 2592000)
            if token:
                self._access_token    = token
                self._token_expire_ts = now + expires_in - 60  # 提前 1 分钟过期
                return token
            else:
                logger.error("BaiduVoice _get_access_token failed: %s", resp)
                return None

    def voiceToText(self, voice_file):
        logger.debug("[Baidu] recognize voice file=%s", voice_file)
        pcm = get_pcm_from_wav(voice_file)
        res = self.client.asr(pcm, "pcm", 16000, {"dev_pid": self.dev_id})
        if res.get("err_no") == 0:
            text = "".join(res["result"])
            logger.info("[Baidu] ASR result: %s", text)
            return Reply(ReplyType.TEXT, text)
        else:
            err = res.get("err_msg", "")
            logger.error("[Baidu] ASR error: %s", err)
            return Reply(ReplyType.ERROR, f"语音识别失败：{err}")

    def _long_text_synthesis(self, text):
        token = self._get_access_token()
        if not token:
            return Reply(ReplyType.ERROR, "获取百度 access_token 失败")

        # 创建合成任务
        create_url = f"https://aip.baidubce.com/rpc/2.0/tts/v1/create?access_token={token}"
        payload = {
            "text":            text,
            "format":          "mp3-16k",
            "voice":           0,
            "lang":            self.lang,
            "speed":           self.spd,
            "pitch":           self.pit,
            "volume":          self.vol,
            "enable_subtitle": 0,
        }
        headers = {"Content-Type": "application/json"}
        create_resp = requests.post(create_url, headers=headers, json=payload).json()
        task_id = create_resp.get("task_id")
        if not task_id:
            logger.error("[Baidu] 长文本合成创建任务失败: %s", create_resp)
            return Reply(ReplyType.ERROR, "长文本合成任务提交失败")
        logger.info("[Baidu] 长文本合成任务已提交 task_id=%s", task_id)

        # 轮询查询任务状态
        query_url = f"https://aip.baidubce.com/rpc/2.0/tts/v1/query?access_token={token}"
        for _ in range(100):
            time.sleep(3)
            resp = requests.post(query_url, headers=headers, json={"task_ids":[task_id]})
            result = resp.json()
            infos = result.get("tasks_info") or result.get("tasks") or []
            if not infos:
                continue
            info = infos[0]
            status = info.get("task_status")
            if status == "Success":
                task_res = info.get("task_result", {})
                audio_url = task_res.get("audio_address") or task_res.get("speech_url")
                break
            elif status == "Running":
                continue
            else:
                logger.error("[Baidu] 长文本合成失败: %s", info)
                return Reply(ReplyType.ERROR, "长文本合成执行失败")
        else:
            return Reply(ReplyType.ERROR, "长文本合成超时，请稍后重试")

        # 下载并保存音频
        audio_data = requests.get(audio_url).content
        fn = TmpDir().path() + f"reply-long-{int(time.time())}-{hash(text)&0x7FFFFFFF}.mp3"
        with open(fn, "wb") as f:
            f.write(audio_data)
        logger.info("[Baidu] 长文本合成 success: %s", fn)
        return Reply(ReplyType.VOICE, fn)

    def textToVoice(self, text):
        try:
            # GBK 编码字节长度
            gbk_len = len(text.encode("gbk", errors="ignore"))
            if gbk_len <= 1024:
                # 短文本走 SDK 合成
                result = self.client.synthesis(
                    text, self.lang, self.ctp,
                    {"spd":self.spd, "pit":self.pit, "vol":self.vol, "per":self.per}
                )
                if not isinstance(result, dict):
                    fn = TmpDir().path() + f"reply-{int(time.time())}-{hash(text)&0x7FFFFFFF}.mp3"
                    with open(fn, "wb") as f:
                        f.write(result)
                    logger.info("[Baidu] 短文本合成 success: %s", fn)
                    return Reply(ReplyType.VOICE, fn)
                else:
                    logger.error("[Baidu] 短文本合成 error: %s", result)
                    return Reply(ReplyType.ERROR, "短文本语音合成失败")
            else:
                # 长文本
                return self._long_text_synthesis(text)
        except Exception as e:
            logger.error("BaiduVoice textToVoice exception: %s", e)
            return Reply(ReplyType.ERROR, f"合成异常：{e}")

