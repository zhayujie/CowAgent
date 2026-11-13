"""Official API domains shared by Feishu and international Lark clients."""

FEISHU_DOMAIN = "https://open.feishu.cn"
LARK_DOMAIN = "https://open.larksuite.com"

# Returned by the websocket endpoint API when an app is called on the other
# platform's domain, e.g. an international Lark app on open.feishu.cn.
WRONG_DOMAIN_CODE = 1000040351

# The SDK requests this endpoint to get the long-connection URL.
WS_ENDPOINT_PATH = "/callback/ws/endpoint"
