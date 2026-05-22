"""
voice factory
"""


def create_voice(voice_type):
    """
    create a voice instance
    :param voice_type: voice type code
    :return: voice instance
    """
    if voice_type == "baidu":
        from voice.baidu.baidu_voice import BaiduVoice

        return BaiduVoice()
    elif voice_type == "google":
        from voice.google.google_voice import GoogleVoice

        return GoogleVoice()
    elif voice_type == "openai":
        from voice.openai.openai_voice import OpenaiVoice

        return OpenaiVoice()
    elif voice_type == "pytts":
        from voice.pytts.pytts_voice import PyttsVoice

        return PyttsVoice()
    elif voice_type == "azure":
        from voice.azure.azure_voice import AzureVoice

        return AzureVoice()
    elif voice_type == "elevenlabs":
        from voice.elevent.elevent_voice import ElevenLabsVoice

        return ElevenLabsVoice()

    elif voice_type == "linkai":
        from voice.linkai.linkai_voice import LinkAIVoice

        return LinkAIVoice()
    elif voice_type == "ali":
        from voice.ali.ali_voice import AliVoice

        return AliVoice()
    elif voice_type == "edge":
        from voice.edge.edge_voice import EdgeVoice

        return EdgeVoice()
    elif voice_type == "xunfei":
        from voice.xunfei.xunfei_voice import XunfeiVoice

        return XunfeiVoice()
    elif voice_type == "tencent":
        from voice.tencent.tencent_voice import TencentVoice

        return TencentVoice()
    elif voice_type == "minimax":
        from voice.minimax.minimax_voice import MinimaxVoice

        return MinimaxVoice()
    raise RuntimeError
