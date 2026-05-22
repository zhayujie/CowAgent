# encoding:utf-8

import requests

from models.bot import Bot
from bridge.reply import Reply, ReplyType


# Baidu Unit对话接口 (可用, 但能力较弱)
class BaiduUnitBot(Bot):
    def reply(self, query, context=None):
        token = self.get_token()
        url = "https://aip.baidubce.com/rpc/2.0/unit/service/v3/chat?access_token=" + token
        post_data = (
            '{"version":"3.0","service_id":"S73177","session_id":"","log_id":"7758521","skill_ids":["1221886"],"request":{"terminal_id":"88888","query":"'
            + query
            + '", "hyper_params": {"chat_custom_bot_profile": 1}}}'
        )
        print(post_data)
        headers = {"content-type": "application/x-www-form-urlencoded"}
        response = requests.post(url, data=post_data.encode(), headers=headers)
        if response:
            reply = Reply(
                ReplyType.TEXT,
                response.json()["result"]["context"]["SYS_PRESUMED_HIST"][1],
            )
            return reply

    def get_token(self):
        access_key = "YOUR_ACCESS_KEY"
        secret_key = "YOUR_SECRET_KEY"
        host = "https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id=" + access_key + "&client_secret=" + secret_key
        response = requests.get(host)
        if response:
            print(response.json())
            return response.json()["access_token"]
