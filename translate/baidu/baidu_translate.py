# -*- coding: utf-8 -*-

import random
from hashlib import md5

import requests

from config import conf
from translate.translator import Translator

# 10s per attempt, the same bound the Youdao translator uses. requests would
# otherwise wait forever, and this call is retried up to three times, so a
# stalled connection could block the caller indefinitely.
REQUEST_TIMEOUT = 10


class BaiduTranslator(Translator):
    def __init__(self) -> None:
        super().__init__()
        endpoint = "http://api.fanyi.baidu.com"
        path = "/api/trans/vip/translate"
        self.url = endpoint + path
        self.appid = conf().get("baidu_translate_app_id")
        self.appkey = conf().get("baidu_translate_app_key")
        if not self.appid or not self.appkey:
            raise Exception("baidu translate appid or appkey not set")

    # For list of language codes, please refer to `https://api.fanyi.baidu.com/doc/21`, need to convert to ISO 639-1 codes
    def translate(self, query: str, from_lang: str = "", to_lang: str = "en") -> str:
        if not from_lang:
            from_lang = "auto"  # baidu suppport auto detect
        salt = random.randint(32768, 65536)
        sign = self.make_md5("{}{}{}{}".format(self.appid, query, salt, self.appkey))
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        payload = {"appid": self.appid, "q": query, "from": from_lang, "to": to_lang, "salt": salt, "sign": sign}

        retry_cnt = 3
        while retry_cnt:
            r = requests.post(self.url, params=payload, headers=headers, timeout=REQUEST_TIMEOUT)
            try:
                result = r.json()
            except ValueError:
                # An HTTP-level failure carries no error_code to inspect — a
                # proxy in front of the API answers with an HTML body, for
                # instance. Report the status and the body instead of letting a
                # decode error take over, which is what the Youdao translator's
                # raise_for_status() achieves for the sibling implementation.
                raise Exception(f"baidu translate HTTP {r.status_code}: {r.text[:200]}")
            errcode = result.get("error_code", "52000")
            if errcode != "52000":
                if errcode == "52001" or errcode == "52002":
                    retry_cnt -= 1
                    continue
                else:
                    raise Exception(result["error_msg"])
            else:
                break
        if retry_cnt == 0:
            # every attempt hit a transient error (52001/52002), so the last
            # response carries no trans_result: report the api error instead of
            # letting the join below fail with a bare KeyError
            raise Exception(result["error_msg"])
        text = "\n".join([item["dst"] for item in result["trans_result"]])
        return text

    def make_md5(self, s, encoding="utf-8"):
        return md5(s.encode(encoding)).hexdigest()
