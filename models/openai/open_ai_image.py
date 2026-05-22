import time

from common.log import logger
from common.token_bucket import TokenBucket
from config import conf
from models.openai.openai_compat import RateLimitError, wrap_http_error
from models.openai.openai_http_client import OpenAIHTTPClient, OpenAIHTTPError


# OpenAI image generation API wrapper
class OpenAIImage(object):
    def __init__(self):
        # Lazy default client; subclasses (ChatGPTBot/OpenAIBot) typically
        # construct their own _http_client and override _get_image_client().
        self._image_api_key = conf().get("open_ai_api_key")
        self._image_api_base = conf().get("open_ai_api_base") or None
        self._image_proxy = conf().get("proxy") or None
        self._image_client = OpenAIHTTPClient(
            api_key=self._image_api_key,
            api_base=self._image_api_base,
            proxy=self._image_proxy,
        )
        if conf().get("rate_limit_dalle"):
            self.tb4dalle = TokenBucket(conf().get("rate_limit_dalle", 50))

    def create_img(self, query, retry_count=0, api_key=None, api_base=None):
        try:
            if conf().get("rate_limit_dalle") and not self.tb4dalle.get_token():
                return False, "请求太快了，请休息一下再问我吧"
            logger.info("[OPEN_AI] image_query={}".format(query))
            response = self._image_client.images_generate(
                api_key=api_key or None,
                api_base=api_base or None,
                prompt=query,  # image description
                n=1,
                model=conf().get("text_to_image") or "dall-e-2",
                # size=conf().get("image_create_size", "256x256"),
            )
            image_url = response["data"][0]["url"]
            logger.info("[OPEN_AI] image_url={}".format(image_url))
            return True, image_url
        except OpenAIHTTPError as http_err:
            mapped = wrap_http_error(http_err)
            if isinstance(mapped, RateLimitError):
                logger.warn(mapped)
                if retry_count < 1:
                    time.sleep(5)
                    logger.warn("[OPEN_AI] ImgCreate RateLimit exceed, 第{}次重试".format(retry_count + 1))
                    return self.create_img(query, retry_count + 1)
                return False, "画图出现问题，请休息一下再问我吧"
            logger.exception(mapped)
            return False, "画图出现问题，请休息一下再问我吧"
        except RateLimitError as e:
            logger.warn(e)
            if retry_count < 1:
                time.sleep(5)
                logger.warn("[OPEN_AI] ImgCreate RateLimit exceed, 第{}次重试".format(retry_count + 1))
                return self.create_img(query, retry_count + 1)
            return False, "画图出现问题，请休息一下再问我吧"
        except Exception as e:
            logger.exception(e)
            return False, "画图出现问题，请休息一下再问我吧"
