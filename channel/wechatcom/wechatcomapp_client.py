# wechatcomapp_client.py
import threading
import time
from wechatpy.enterprise import WeChatClient

class WechatComAppClient(WeChatClient):
    def __init__(self, corp_id, secret, access_token=None, session=None, timeout=None, auto_retry=True):
        super(WechatComAppClient, self).__init__(corp_id, secret, access_token, session, timeout, auto_retry)
        self.fetch_access_token_lock = threading.Lock()
        self._active_refresh()
        
    def _active_refresh(self):
        """启动主动刷新的后台线程"""
        def refresh_loop():
            while True:
                now = time.time()
                expires_at = self.session.get(f"{self.corp_id}_expires_at", 0)
                
                # 提前10分钟刷新(600秒)
                if expires_at - now < 600:
                    with self.fetch_access_token_lock:
                        # 双重检查避免重复刷新
                        if self.session.get(f"{self.corp_id}_expires_at", 0) - time.time() < 600:
                            super(WechatComAppClient, self).fetch_access_token()
                # 每次检查间隔60秒
                time.sleep(60)
                
        # 启动守护线程
        refresh_thread = threading.Thread(
            target=refresh_loop,
            daemon=True,
            name="wechatcom_token_refresh_thread"
        )
        refresh_thread.start()

    def fetch_access_token(self):
        with self.fetch_access_token_lock:
            access_token = self.session.get(self.access_token_key)
            expires_at = self.session.get(f"{self.corp_id}_expires_at", 0)
            
            if access_token and expires_at > time.time() + 60:
                return access_token
            return super().fetch_access_token()