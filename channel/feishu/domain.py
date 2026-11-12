"""Official API domains shared by Feishu and international Lark clients."""

FEISHU_DOMAIN = "https://open.feishu.cn"
LARK_DOMAIN = "https://open.larksuite.com"


def resolve_feishu_domain(value=None):
    """Resolve a platform name or official HTTPS API origin.

    Restrict credential-bearing requests to the two supported platform origins;
    a typo must not send an app secret or tenant token to an arbitrary host.
    """
    domain = (value or FEISHU_DOMAIN).strip().rstrip("/").lower()
    aliases = {"feishu": FEISHU_DOMAIN, "lark": LARK_DOMAIN,
               FEISHU_DOMAIN: FEISHU_DOMAIN, LARK_DOMAIN: LARK_DOMAIN}
    if domain not in aliases:
        raise ValueError(
            "Unsupported Feishu/Lark API domain; expected https://open.feishu.cn "
            "or https://open.larksuite.com"
        )
    return aliases[domain]
