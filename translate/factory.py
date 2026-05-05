SUPPORTED_TRANSLATORS = ("baidu", "youdao")


def create_translator(translator_type):
    if translator_type == "baidu":
        from translate.baidu.baidu_translate import BaiduTranslator

        return BaiduTranslator()
    if translator_type == "youdao":
        from translate.youdao.youdao_translate import YoudaoTranslator

        return YoudaoTranslator()
    raise RuntimeError(
        "unsupported translator type: {}, supported: {}".format(
            translator_type, ", ".join(SUPPORTED_TRANSLATORS)
        )
    )
