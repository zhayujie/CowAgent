"""The WeCom-app callback endpoint must reject a mismatched corp id.

``Query.GET`` (channel/wechatcom/wechatcomapp_channel.py:181) answers the
callback URL verification handshake. ``WeChatCrypto.check_signature`` does more
than compare the signature: it also decrypts the echoed string and raises
``InvalidCorpIdException`` when the corp id carried inside it differs from the
configured one (wechatpy/crypto/base.py:49). GET only caught
``InvalidSignatureException``, so a wrong ``wechatcom_corp_id`` -- a plain
configuration mistake -- escaped as a 500 instead of the expected 403. POST in
the same file already catches both kinds (line 204).
"""

import base64
import types
import unittest
from unittest.mock import patch

import web
from wechatpy.crypto import PrpCrypto
from wechatpy.enterprise.crypto import WeChatCrypto
from wechatpy.utils import WeChatSigner

from channel.wechatcom import wechatcomapp_channel as channel_module

TOKEN = "callback-token"
AES_KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode().rstrip("=")
CONFIGURED_CORP = "ww-configured"
GATEWAY_CORP = "ww-from-gateway"


class _Channel:
    """Query.GET only reaches for ``crypto``."""

    def __init__(self, crypto):
        self.crypto = crypto


def _echostr(corp_id):
    """An ``echostr`` the WeCom gateway would send for ``corp_id``."""
    return PrpCrypto(base64.b64decode(AES_KEY + "=")).encrypt("echo-42", corp_id).decode()


def _signature(echostr):
    signer = WeChatSigner()
    signer.add_data(TOKEN, "1700000000", "nonce", echostr)
    return signer.signature


class WeComAppCallbackVerifyTest(unittest.TestCase):
    def setUp(self):
        # web.Forbidden() writes a Content-Type header, which needs a request
        # context; give it the minimum one it touches.
        web.ctx.headers = []

    def _handshake(self, configured_corp, payload_corp, signature=None):
        echostr = _echostr(payload_corp)
        params = types.SimpleNamespace(
            msg_signature=signature or _signature(echostr),
            timestamp="1700000000",
            nonce="nonce",
            echostr=echostr,
        )
        crypto = WeChatCrypto(TOKEN, AES_KEY, configured_corp)
        with patch.object(channel_module, "WechatComAppChannel", lambda: _Channel(crypto)), \
                patch.object(channel_module.web, "input", lambda: params):
            return channel_module.Query().GET()

    def test_mismatched_corp_id_is_forbidden_and_not_a_crash(self):
        """A wrong corp id must answer 403, not leak InvalidCorpIdException."""
        with self.assertRaises(web.Forbidden):
            self._handshake(CONFIGURED_CORP, GATEWAY_CORP)

    def test_wrong_signature_is_still_forbidden(self):
        with self.assertRaises(web.Forbidden):
            self._handshake(CONFIGURED_CORP, CONFIGURED_CORP, signature="not-the-signature")

    def test_matching_corp_id_returns_the_decrypted_echo(self):
        self.assertEqual("echo-42", self._handshake(CONFIGURED_CORP, CONFIGURED_CORP))
