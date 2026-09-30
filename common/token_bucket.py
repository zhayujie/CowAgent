import threading
import time


class TokenBucket:
    def __init__(self, tpm, timeout=None):
        self.capacity = int(tpm)  # 令牌桶容量
        self.tokens = 0  # 初始令牌数为0
        self.rate = int(tpm) / 60  # 令牌每秒生成速率
        self.timeout = timeout  # 等待令牌超时时间
        self.cond = threading.Condition()  # 条件变量
        self.is_running = True
        # Start the token generator thread. It must be a daemon: a rate limiter
        # has no reason to keep the process from exiting, and both production
        # call sites build a bucket without ever calling close().
        self._thread = threading.Thread(target=self._generate_tokens, daemon=True)
        self._thread.start()

    def _generate_tokens(self):
        """生成令牌"""
        if self.rate <= 0:
            # A sub-1 tokens-per-minute config rounds to a rate of zero, so
            # there is nothing to generate. Stop here instead of dividing by 0
            # in the sleep below, which would kill this thread silently.
            self.is_running = False
            return
        while self.is_running:
            with self.cond:
                if self.tokens < self.capacity:
                    self.tokens += 1
                self.cond.notify()  # 通知获取令牌的线程
            time.sleep(1 / self.rate)

    def get_token(self):
        """获取令牌"""
        with self.cond:
            while self.tokens <= 0:
                flag = self.cond.wait(self.timeout)
                if not flag:  # 超时
                    return False
            self.tokens -= 1
        return True

    def close(self):
        self.is_running = False
        # The generator may be mid-sleep, so bound the wait. It is a daemon
        # thread, so a missed join can never keep the process alive.
        self._thread.join(timeout=1)


if __name__ == "__main__":
    token_bucket = TokenBucket(20, None)  # 创建一个每分钟生产20个tokens的令牌桶
    # token_bucket = TokenBucket(20, 0.1)
    for i in range(3):
        if token_bucket.get_token():
            print(f"第{i+1}次请求成功")
    token_bucket.close()
