# wechatcomapp_client.py
import threading
import time
from wechatpy.enterprise import WeChatClient

from common.log import logger

# wechatpy keeps a fetched token's expiry on the client (``expires_at``, set by
# ``_fetch_access_token``) and only the token itself in the session, so there is
# no expiry key to read back. Renew this long before it lapses, and check this
# often -- a 2h token needs one renewal per two hours, not one per check.
TOKEN_REFRESH_MARGIN_SECONDS = 600
TOKEN_REFRESH_CHECK_SECONDS = 60


class WechatComAppClient(WeChatClient):
    def __init__(self, corp_id, secret, access_token=None, session=None, timeout=None, auto_retry=True):
        super(WechatComAppClient, self).__init__(corp_id, secret, access_token, session, timeout, auto_retry)
        self.fetch_access_token_lock = threading.Lock()
        self._refresh_stop = threading.Event()
        self._active_refresh()

    def _expires_at(self) -> float:
        """When the current token lapses, as the SDK tracks it.

        Reading ``<corp_id>_expires_at`` from the session always returned 0 --
        nothing writes that key -- so every caller below concluded the token was
        about to expire and asked the token endpoint again.
        """
        try:
            return float(getattr(self, "expires_at", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    def _refresh_due(self) -> bool:
        return self._expires_at() - time.time() < TOKEN_REFRESH_MARGIN_SECONDS

    def _refresh_once_if_needed(self) -> None:
        """Renew the access token when it is close to expiring.

        Runs on the only refresh thread, so errors are logged rather than
        raised: an escaping exception would end renewal for the process.
        """
        if not self._refresh_due():
            return
        try:
            with self.fetch_access_token_lock:
                # 双重检查避免重复刷新
                if self._refresh_due():
                    super(WechatComAppClient, self).fetch_access_token()
        except Exception as e:
            logger.error(f"[WechatComApp] access token refresh failed, retrying later: {e}")

    def _active_refresh(self):
        """启动主动刷新的后台线程"""
        def refresh_loop():
            # An Event rather than a bare sleep: close() has to be able to end
            # this thread, or every restarted channel leaves a poller behind.
            while not self._refresh_stop.is_set():
                self._refresh_once_if_needed()
                self._refresh_stop.wait(TOKEN_REFRESH_CHECK_SECONDS)

        # 启动守护线程
        threading.Thread(
            target=refresh_loop,
            daemon=True,
            name="wechatcom_token_refresh_thread"
        ).start()

    def close(self) -> None:
        """Stop the background refresher; the channel calls this on stop()."""
        self._refresh_stop.set()

    def fetch_access_token(self):
        with self.fetch_access_token_lock:
            access_token = self.session.get(self.access_token_key)

            if access_token and not self._refresh_due():
                return access_token
            return super().fetch_access_token()
