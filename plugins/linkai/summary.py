import requests
from config import conf
from common.log import logger
import os
import html


class LinkSummary:
    def __init__(self):
        pass

    def summary_file(self, file_path: str, app_code: str):
        body = {
            "app_code": app_code
        }
        url = self.base_url() + "/v1/summary/file"
        logger.info(f"[LinkSum] file summary, app_code={app_code}")
        # os.path.basename, not split("/"): the name is what travels in the
        # multipart header, and on Windows a path is separated by backslashes,
        # so the whole local path used to be sent.
        name = os.path.basename(file_path)
        # The handle has to stay open for the duration of the request and be
        # closed afterwards: requests does not own it, so every summary leaked a
        # descriptor (and kept the file locked on Windows).
        with open(file_path, "rb") as file:
            file_body = {
                "file": (name, file),
                "name": name,
            }
            res = requests.post(url, headers=self.headers(), files=file_body, data=body, timeout=(5, 300))
        return self._parse_summary_res(res)

    def summary_url(self, url: str, app_code: str):
        url = html.unescape(url)
        body = {
            "url": url,
            "app_code": app_code
        }
        logger.info(f"[LinkSum] url summary, app_code={app_code}")
        res = requests.post(url=self.base_url() + "/v1/summary/url", headers=self.headers(), json=body, timeout=(5, 180))
        return self._parse_summary_res(res)

    def summary_chat(self, summary_id: str):
        body = {
            "summary_id": summary_id
        }
        res = requests.post(url=self.base_url() + "/v1/summary/chat", headers=self.headers(), json=body, timeout=(5, 180))
        if res.status_code == 200:
            res = res.json()
            logger.debug(f"[LinkSum] chat open, res={res}")
            if res.get("code") == 200:
                data = res.get("data")
                return {
                    "questions": data.get("questions"),
                    "file_id": data.get("file_id")
                }
        else:
            res_json = res.json()
            logger.error(f"[LinkSum] summary error, status_code={res.status_code}, msg={res_json.get('message')}")
            return None

    def _parse_summary_res(self, res):
        if res.status_code == 200:
            res = res.json()
            logger.debug(f"[LinkSum] summary result, res={res}")
            if res.get("code") == 200:
                data = res.get("data")
                return {
                    "summary": data.get("summary"),
                    "summary_id": data.get("summary_id")
                }
        else:
            res_json = res.json()
            logger.error(f"[LinkSum] summary error, status_code={res.status_code}, msg={res_json.get('message')}")
            return None

    def base_url(self):
        return conf().get("linkai_api_base", "https://api.link-ai.tech")

    def headers(self):
        return {"Authorization": "Bearer " + conf().get("linkai_api_key")}

    def check_file(self, file_path: str, sum_config: dict) -> bool:
        file_size = os.path.getsize(file_path) // 1000

        if (sum_config.get("max_file_size") and file_size > sum_config.get("max_file_size")) or file_size > 15000:
            logger.warn(f"[LinkSum] file size exceeds limit, No processing, file_size={file_size}KB")
            return False

        # Matched case-insensitively, like the media classifier in
        # models/linkai/link_ai_bot.py (`urlparse(url).path.lower()`): a
        # "REPORT.PDF" used to come back from `split(".")[-1]` as "PDF", get
        # reported as unsupported, and the file was silently skipped.
        suffix = os.path.splitext(file_path)[1].lstrip(".").lower()
        support_list = ["txt", "csv", "docx", "pdf", "md", "jpg", "jpeg", "png"]
        if suffix not in support_list:
            logger.warn(f"[LinkSum] unsupported file, suffix={suffix}, support_list={support_list}")
            return False

        return True

    def check_url(self, url: str):
        if not url:
            return False
        support_list = ["http://mp.weixin.qq.com", "https://mp.weixin.qq.com"]
        black_support_list = ["https://mp.weixin.qq.com/mp/waerrpage"]
        for black_url_prefix in black_support_list:
            if url.strip().startswith(black_url_prefix):
                logger.warn(f"[LinkSum] unsupported url, no need to process, url={url}")
                return False
        for support_url in support_list:
            if url.strip().startswith(support_url):
                return True
        return False
