"""The models tab's endpoint: /api/models.

Builds what the tab renders -- the vendor cards, the per-capability model
lists, the fallback chain -- out of the catalogue in core/providers.py and
the user's config.json, and saves the edits back.

This is the largest handler in the console by a wide margin, and it is one
class because the frontend asks for the whole page state in one request.
"""

from collections import OrderedDict
from typing import List
import json
import os

import web

from channel.web.core._common import (
    _read_config_file_for_write,
    _require_auth,
    _write_config_file_for_write,
)
from channel.web.core.providers import (
    PROVIDER_MODELS,
    is_real_key,
    legacy_custom_in_use,
    mask_key,
)
from common import const
from common.log import logger
from config import (
    conf,
    get_data_root,
    sync_image_generation_custom_provider_env,
)
from models import model_catalog


class ModelsHandler:
    """API for the unified Models console.

    Layered model:
      Layer 1 (providers): vendor credentials shared across capabilities.
                            Stored as flat *_api_key / *_api_base fields in
                            config.json — the same fields ConfigHandler
                            already manages.
      Layer 2 (capabilities): which provider/model is used by chat / vision /
                            asr / tts / embedding / image / search.

    GET  /api/models           -> overview (providers + capabilities)
    POST /api/models/provider  -> upsert a vendor credential
    DELETE /api/models/provider -> clear a vendor credential
    POST /api/models/capability -> set provider/model for a capability
    """

    # Capability -> provider ids drawn from PROVIDER_MODELS.
    _ASR_PROVIDERS = ["openai", "dashscope", "zhipu", "linkai"]
    # Web-console white-list. Other vendors stay usable via direct config.
    _TTS_PROVIDERS = ["openai", "minimax", "dashscope", "mimo", "linkai"]

    # TTS engine catalog (speech models, not voice timbres). Entries are
    # either a bare code or {value, hint?} when a friendly label helps.
    _TTS_PROVIDER_MODELS = {
        "openai":    ["tts-1", "tts-1-hd", "gpt-4o-mini-tts"],
        "minimax": [
            {"value": "speech-2.8-hd",    "hint": "情绪渲染融合语气词,自然听感"},
            {"value": "speech-2.8-turbo", "hint": "极致生成速度,更自然逼真"},
            {"value": "speech-2.6-hd",    "hint": "超低延时,归一化升级"},
            {"value": "speech-2.6-turbo", "hint": "更快更便宜,适合语音聊天/数字人"},
        ],
        "dashscope": [
            {"value": "qwen3-tts-flash", "hint": "覆盖普通话、方言与主流外语"},
        ],
        # 小米 MiMo TTS 系列，通过 chat completions 接口合成
        "mimo": [
            {"value": "mimo-v2.5-tts", "hint": "预置音色 · 支持唱歌模式"},
        ],
        # Aggregating gateway: a single endpoint multiplexes several
        # underlying TTS engines, selected via the `model` field.
        # Each engine exposes its own voice catalog (see _TTS_PROVIDER_VOICES).
        "linkai": [
            {"value": "tts-1",  "hint": "OpenAI · 多语种通用"},
            {"value": "doubao", "hint": "字节豆包 · 中文音色丰富"},
            {"value": "baidu",  "hint": "百度 · 中文主播音色"},
        ],
    }

    # ASR engine catalog per provider. The first entry of each list is the
    # runtime default (mirrors DEFAULT_ASR_MODEL in voice/*). Users can still
    # pick "custom" in the UI to send any other model id.
    _ASR_PROVIDER_MODELS = {
        "openai": [
            {"value": "gpt-4o-mini-transcribe", "hint": "默认 · 速度快"},
            {"value": "gpt-4o-transcribe",      "hint": "更高准确率"},
            {"value": "whisper-1",              "hint": "经典 Whisper"},
        ],
        "dashscope": [
            {"value": "qwen3-asr-flash", "hint": "覆盖普通话、方言与主流外语"},
        ],
        "zhipu": [
            {"value": "glm-asr-2512", "hint": "智谱语音识别"},
        ],
        # LinkAI gateway routes ASR by `model` (see
        # https://docs.link-ai.tech/platform/api/voice-recognition). An empty
        # value means "let the gateway pick its default engine".
        "linkai": [
            {"value": "", "hint": "默认"},
            {"value": "doubao", "hint": "火山豆包"},
            {"value": "whisper-1", "hint": "OpenAI Whisper"},
            {"value": "baidu", "hint": "百度"},
        ],
    }

    # Per-provider voice timbres. Entries can be a bare code string
    # (label = code) or {value, hint?} when a friendly secondary label
    # helps recognition. We keep `value` as the raw API code so power
    # users can cross-reference config.json.
    _TTS_PROVIDER_VOICES = {
        "openai":    [
            "alloy", "echo", "fable", "onyx", "nova", "shimmer",
            "ash", "ballad", "coral", "sage", "verse",
        ],
        "minimax": [
            # Mandarin Chinese (full catalog)
            {"value": "male-qn-qingse",                           "hint": "中文 · 青涩青年（男）"},
            {"value": "male-qn-jingying",                         "hint": "中文 · 精英青年（男）"},
            {"value": "male-qn-badao",                            "hint": "中文 · 霸道青年（男）"},
            {"value": "male-qn-daxuesheng",                       "hint": "中文 · 青年大学生（男）"},
            {"value": "female-shaonv",                            "hint": "中文 · 少女（女）"},
            {"value": "female-yujie",                             "hint": "中文 · 御姐（女）"},
            {"value": "female-chengshu",                          "hint": "中文 · 成熟女性（女）"},
            {"value": "female-tianmei",                           "hint": "中文 · 甜美女性（女）"},
            {"value": "male-qn-qingse-jingpin",                   "hint": "中文 · 青涩青年-beta（男）"},
            {"value": "male-qn-jingying-jingpin",                 "hint": "中文 · 精英青年-beta（男）"},
            {"value": "male-qn-badao-jingpin",                    "hint": "中文 · 霸道青年-beta（男）"},
            {"value": "male-qn-daxuesheng-jingpin",               "hint": "中文 · 青年大学生-beta（男）"},
            {"value": "female-shaonv-jingpin",                    "hint": "中文 · 少女-beta（女）"},
            {"value": "female-yujie-jingpin",                     "hint": "中文 · 御姐-beta（女）"},
            {"value": "female-chengshu-jingpin",                  "hint": "中文 · 成熟女性-beta（女）"},
            {"value": "female-tianmei-jingpin",                   "hint": "中文 · 甜美女性-beta（女）"},
            {"value": "clever_boy",                               "hint": "中文 · 聪明男童"},
            {"value": "cute_boy",                                 "hint": "中文 · 可爱男童"},
            {"value": "lovely_girl",                              "hint": "中文 · 萌萌女童"},
            {"value": "cartoon_pig",                              "hint": "中文 · 卡通猪小琪"},
            {"value": "bingjiao_didi",                            "hint": "中文 · 病娇弟弟"},
            {"value": "junlang_nanyou",                           "hint": "中文 · 俊朗男友"},
            {"value": "chunzhen_xuedi",                           "hint": "中文 · 纯真学弟"},
            {"value": "lengdan_xiongzhang",                       "hint": "中文 · 冷淡学长"},
            {"value": "badao_shaoye",                             "hint": "中文 · 霸道少爷"},
            {"value": "tianxin_xiaoling",                         "hint": "中文 · 甜心小玲"},
            {"value": "qiaopi_mengmei",                           "hint": "中文 · 俏皮萌妹"},
            {"value": "wumei_yujie",                              "hint": "中文 · 妩媚御姐"},
            {"value": "diadia_xuemei",                            "hint": "中文 · 嗲嗲学妹"},
            {"value": "danya_xuejie",                             "hint": "中文 · 淡雅学姐"},
            {"value": "Chinese (Mandarin)_Reliable_Executive",    "hint": "中文 · 沉稳高管"},
            {"value": "Chinese (Mandarin)_News_Anchor",           "hint": "中文 · 新闻女声"},
            {"value": "Chinese (Mandarin)_Mature_Woman",          "hint": "中文 · 傲娇御姐"},
            {"value": "Chinese (Mandarin)_Unrestrained_Young_Man","hint": "中文 · 不羁青年"},
            {"value": "Arrogant_Miss",                            "hint": "中文 · 嚣张小姐"},
            {"value": "Robot_Armor",                              "hint": "中文 · 机械战甲"},
            {"value": "Chinese (Mandarin)_Kind-hearted_Antie",    "hint": "中文 · 热心大婶"},
            {"value": "Chinese (Mandarin)_HK_Flight_Attendant",   "hint": "中文 · 港普空姐"},
            {"value": "Chinese (Mandarin)_Humorous_Elder",        "hint": "中文 · 搞笑大爷"},
            {"value": "Chinese (Mandarin)_Gentleman",             "hint": "中文 · 温润男声"},
            {"value": "Chinese (Mandarin)_Warm_Bestie",           "hint": "中文 · 温暖闺蜜"},
            {"value": "Chinese (Mandarin)_Male_Announcer",        "hint": "中文 · 播报男声"},
            {"value": "Chinese (Mandarin)_Sweet_Lady",            "hint": "中文 · 甜美女声"},
            {"value": "Chinese (Mandarin)_Southern_Young_Man",    "hint": "中文 · 南方小哥"},
            {"value": "Chinese (Mandarin)_Wise_Women",            "hint": "中文 · 阅历姐姐"},
            {"value": "Chinese (Mandarin)_Gentle_Youth",          "hint": "中文 · 温润青年"},
            {"value": "Chinese (Mandarin)_Warm_Girl",             "hint": "中文 · 温暖少女"},
            {"value": "Chinese (Mandarin)_Kind-hearted_Elder",    "hint": "中文 · 花甲奶奶"},
            {"value": "Chinese (Mandarin)_Cute_Spirit",           "hint": "中文 · 憨憨萌兽"},
            {"value": "Chinese (Mandarin)_Radio_Host",            "hint": "中文 · 电台男主播"},
            {"value": "Chinese (Mandarin)_Lyrical_Voice",         "hint": "中文 · 抒情男声"},
            {"value": "Chinese (Mandarin)_Straightforward_Boy",   "hint": "中文 · 率真弟弟"},
            {"value": "Chinese (Mandarin)_Sincere_Adult",         "hint": "中文 · 真诚青年"},
            {"value": "Chinese (Mandarin)_Gentle_Senior",         "hint": "中文 · 温柔学姐"},
            {"value": "Chinese (Mandarin)_Stubborn_Friend",       "hint": "中文 · 嘴硬竹马"},
            {"value": "Chinese (Mandarin)_Crisp_Girl",            "hint": "中文 · 清脆少女"},
            {"value": "Chinese (Mandarin)_Pure-hearted_Boy",      "hint": "中文 · 清澈邻家弟弟"},
            {"value": "Chinese (Mandarin)_Soft_Girl",             "hint": "中文 · 柔和少女"},
            # Cantonese (full catalog)
            {"value": "Cantonese_ProfessionalHost（F)",            "hint": "粤语 · 专业女主持"},
            {"value": "Cantonese_GentleLady",                     "hint": "粤语 · 温柔女声"},
            {"value": "Cantonese_ProfessionalHost（M)",            "hint": "粤语 · 专业男主持"},
            {"value": "Cantonese_PlayfulMan",                     "hint": "粤语 · 活泼男声"},
            {"value": "Cantonese_CuteGirl",                       "hint": "粤语 · 可爱女孩"},
            {"value": "Cantonese_KindWoman",                      "hint": "粤语 · 善良女声"},
            # English (curated: 1F + 1M)
            {"value": "English_Graceful_Lady",                    "hint": "英文 · Graceful Lady（女）"},
            {"value": "English_Trustworthy_Man",                  "hint": "英文 · Trustworthy Man（男）"},
            # Japanese (curated: 1F + 1M)
            {"value": "Japanese_KindLady",                        "hint": "日文 · Kind Lady（女）"},
            {"value": "Japanese_LoyalKnight",                     "hint": "日文 · Loyal Knight（男）"},
            # Korean (curated: 1F + 1M)
            {"value": "Korean_SweetGirl",                         "hint": "韩文 · Sweet Girl（女）"},
            {"value": "Korean_CheerfulBoyfriend",                 "hint": "韩文 · Cheerful Boyfriend（男）"},
        ],
        "dashscope": [
            {"value": "Cherry",   "hint": "芊悦 · 阳光女声"},
            {"value": "Serena",   "hint": "苏瑶 · 温柔女声"},
            {"value": "Chelsie",  "hint": "千雪 · 二次元少女"},
            {"value": "Ethan",    "hint": "晨煦 · 阳光男声"},
            {"value": "Moon",     "hint": "月白 · 率性男声"},
            {"value": "Kai",      "hint": "凯 · 治愈男声"},
            {"value": "Nofish",   "hint": "不吃鱼 · 设计师男声"},
            {"value": "Bella",    "hint": "萌宝 · 小萝莉"},
            {"value": "Bunny",    "hint": "萌小姬 · 萌系少女"},
            {"value": "Stella",   "hint": "少女阿月 · 元气少女"},
            {"value": "Neil",     "hint": "阿闻 · 新闻主播"},
            {"value": "Seren",    "hint": "小婉 · 助眠女声"},
            {"value": "Jada",     "hint": "上海话 · 阿珍"},
            {"value": "Dylan",    "hint": "北京话 · 晓东"},
            {"value": "Sunny",    "hint": "四川话 · 晴儿"},
            {"value": "Eric",     "hint": "四川话 · 程川"},
            {"value": "Rocky",    "hint": "粤语 · 阿强"},
            {"value": "Kiki",     "hint": "粤语 · 阿清"},
            {"value": "Peter",    "hint": "天津话 · 李彼得"},
            {"value": "Marcus",   "hint": "陕西话 · 秦川"},
            {"value": "Roy",      "hint": "闽南语 · 阿杰"},
        ],
        # 小米 MiMo 预置音色列表（mimo-v2.5-tts），文档：
        # https://platform.xiaomimimo.com/docs/zh-CN/usage-guide/speech-synthesis-v2.5
        "mimo": [
            {"value": "冰糖",   "hint": "中文 · 女声 · 冰糖"},
            {"value": "茉莉",   "hint": "中文 · 女声 · 茉莉"},
            {"value": "苏打",   "hint": "中文 · 男声 · 苏打"},
            {"value": "白桦",   "hint": "中文 · 男声 · 白桦"},
            {"value": "Mia",   "hint": "英文 · 女声 · Mia"},
            {"value": "Chloe", "hint": "英文 · 女声 · Chloe"},
            {"value": "Milo",  "hint": "英文 · 男声 · Milo"},
            {"value": "Dean",  "hint": "英文 · 男声 · Dean"},
        ],
        # Aggregating gateway: voices are scoped per engine model. The
        # frontend picks the correct list based on the selected model so
        # users don't see incompatible timbres for the active engine.
        "linkai": {
            "tts-1": [
                "alloy", "echo", "fable", "onyx", "nova", "shimmer",
            ],
            "doubao": [
                {"value": "zh_female_wanwanxiaohe_moon_bigtts",       "hint": "湾湾小何"},
                {"value": "BV007_streaming",                          "hint": "亲切女声"},
                {"value": "BV001_streaming",                          "hint": "通用女声"},
                {"value": "BV002_streaming",                          "hint": "通用男声"},
                {"value": "BV051_streaming",                          "hint": "奶气萌娃"},
                {"value": "zh_female_linjianvhai_moon_bigtts",        "hint": "邻家女孩"},
                {"value": "BV700_streaming",                          "hint": "灿灿"},
                {"value": "BV019_streaming",                          "hint": "重庆小伙"},
                {"value": "BV524_streaming",                          "hint": "日语男声"},
                {"value": "BV021_streaming",                          "hint": "东北老铁"},
                {"value": "BV701_streaming",                          "hint": "擎苍"},
                {"value": "BV113_streaming",                          "hint": "甜宠少御"},
                {"value": "BV056_streaming",                          "hint": "阳光男声"},
                {"value": "BV213_streaming",                          "hint": "广西表哥"},
                {"value": "BV119_streaming",                          "hint": "通用赘婿"},
                {"value": "BV705_streaming",                          "hint": "炀炀"},
                {"value": "BV033_streaming",                          "hint": "温柔小哥"},
                {"value": "BV102_streaming",                          "hint": "儒雅青年"},
                {"value": "BV522_streaming",                          "hint": "气质女生"},
                {"value": "BV034_streaming",                          "hint": "知性姐姐 · 双语"},
                {"value": "BV005_streaming",                          "hint": "活泼女声"},
                {"value": "zh_female_wanqudashu_moon_bigtts",         "hint": "湾区大叔"},
                {"value": "zh_female_daimengchuanmei_moon_bigtts",    "hint": "呆萌川妹"},
                {"value": "zh_male_guozhoudege_moon_bigtts",          "hint": "广州德哥"},
                {"value": "zh_male_beijingxiaoye_moon_bigtts",        "hint": "北京小爷"},
                {"value": "zh_male_shaonianzixin_moon_bigtts",        "hint": "少年梓辛 / Brayan"},
                {"value": "zh_female_meilinvyou_moon_bigtts",         "hint": "魅力女友"},
                {"value": "zh_male_shenyeboke_moon_bigtts",           "hint": "深夜播客"},
                {"value": "zh_female_sajiaonvyou_moon_bigtts",        "hint": "柔美女友"},
                {"value": "zh_female_yuanqinvyou_moon_bigtts",        "hint": "撒娇学妹"},
                {"value": "zh_male_haoyuxiaoge_moon_bigtts",          "hint": "浩宇小哥"},
                {"value": "zh_male_guangxiyuanzhou_moon_bigtts",      "hint": "广西远舟"},
                {"value": "zh_female_meituojieer_moon_bigtts",        "hint": "妹坨洁儿"},
                {"value": "zh_male_yuzhouzixuan_moon_bigtts",         "hint": "豫州子轩"},
                {"value": "BV115_streaming",                          "hint": "古风少御"},
                {"value": "zh_female_gaolengyujie_moon_bigtts",       "hint": "高冷御姐"},
                {"value": "zh_male_yuanboxiaoshu_moon_bigtts",        "hint": "渊博小叔"},
                {"value": "zh_male_yangguangqingnian_moon_bigtts",    "hint": "阳光青年"},
                {"value": "zh_male_aojiaobazong_moon_bigtts",         "hint": "傲娇霸总"},
                {"value": "zh_male_jingqiangkanye_moon_bigtts",       "hint": "京腔侃爷 / Harmony"},
                {"value": "zh_female_shuangkuaisisi_moon_bigtts",     "hint": "爽快思思 / Skye"},
                {"value": "zh_male_wennuanahu_moon_bigtts",           "hint": "温暖阿虎 / Alvin"},
                {"value": "multi_female_shuangkuaisisi_moon_bigtts",  "hint": "はるこ / Esmeralda"},
                {"value": "multi_male_jingqiangkanye_moon_bigtts",    "hint": "かずね / Javier or Álvaro"},
                {"value": "multi_female_gaolengyujie_moon_bigtts",    "hint": "あけみ"},
                {"value": "multi_male_wanqudashu_moon_bigtts",        "hint": "ひろし / Roberto"},
                {"value": "ICL_zh_female_bingruoshaonv_tob",          "hint": "病弱少女"},
                {"value": "ICL_zh_female_huoponvhai_tob",             "hint": "活泼女孩"},
                {"value": "ICL_zh_female_heainainai_tob",             "hint": "和蔼奶奶"},
                {"value": "ICL_zh_female_linjuayi_tob",               "hint": "邻居阿姨"},
                {"value": "zh_female_wenrouxiaoya_moon_bigtts",       "hint": "温柔小雅"},
                {"value": "zh_female_tianmeixiaoyuan_moon_bigtts",    "hint": "甜美小源"},
                {"value": "zh_female_qingchezizi_moon_bigtts",        "hint": "清澈梓梓"},
                {"value": "zh_male_dongfanghaoran_moon_bigtts",       "hint": "东方浩然"},
                {"value": "zh_male_jieshuoxiaoming_moon_bigtts",      "hint": "解说小明"},
                {"value": "zh_female_kailangjiejie_moon_bigtts",      "hint": "开朗姐姐"},
                {"value": "zh_male_linjiananhai_moon_bigtts",         "hint": "邻家男孩"},
                {"value": "zh_female_tianmeiyueyue_moon_bigtts",      "hint": "甜美悦悦"},
                {"value": "zh_female_xinlingjitang_moon_bigtts",      "hint": "心灵鸡汤"},
            ],
            "baidu": [
                {"value": "baidu_0",    "hint": "度小美 · 标准女主播"},
                {"value": "baidu_1",    "hint": "度小宇 · 亲切男声"},
                {"value": "baidu_3",    "hint": "度逍遥 · 情感男声"},
                {"value": "baidu_4",    "hint": "度丫丫 · 童声"},
                {"value": "baidu_5",    "hint": "度小娇 · 成熟女主播"},
                {"value": "baidu_5003", "hint": "度逍遥 · 情感男声"},
                {"value": "baidu_5118", "hint": "度小鹿 · 甜美女声"},
                {"value": "baidu_103",  "hint": "度米朵 · 可爱童声"},
                {"value": "baidu_106",  "hint": "度博文 · 专业男主播"},
                {"value": "baidu_110",  "hint": "度小童 · 童声主播"},
                {"value": "baidu_111",  "hint": "度小萌 · 软萌妹子"},
                {"value": "baidu_4003", "hint": "度逍遥 · 情感男声"},
                {"value": "baidu_4100", "hint": "度小雯 · 活力女主播"},
                {"value": "baidu_4103", "hint": "度米朵 · 可爱女声"},
                {"value": "baidu_4105", "hint": "度灵儿 · 清澈女声"},
                {"value": "baidu_4106", "hint": "度博文 · 专业男主播"},
                {"value": "baidu_4115", "hint": "度小贤 · 电台男主播"},
                {"value": "baidu_4117", "hint": "度小乔 · 活泼女声"},
                {"value": "baidu_4119", "hint": "度小鹿 · 甜美女声"},
                {"value": "baidu_4129", "hint": "度小彦 · 知识男主播"},
                {"value": "baidu_4140", "hint": "度小新 · 专业女主播"},
                {"value": "baidu_4143", "hint": "度清风 · 配音男声"},
                {"value": "baidu_4144", "hint": "度姗姗 · 娱乐女声"},
                {"value": "baidu_4149", "hint": "度星河 · 广告男声"},
                {"value": "baidu_4206", "hint": "度博文 · 综艺男声"},
                {"value": "baidu_4226", "hint": "南方 · 电台女主播"},
                {"value": "baidu_4254", "hint": "度小清 · 广告女声"},
                {"value": "baidu_4278", "hint": "度小贝 · 知识女主播"},
            ],
        },
    }
    _EMBEDDING_PROVIDERS = ["openai", "dashscope", "doubao", "zhipu", "linkai", "custom"]

    # Embedding model catalog per provider. Mirrors the default_model in
    # agent/memory/embedding/provider.py::EMBEDDING_VENDORS.
    # Custom providers have no preset list — model names vary per vendor,
    # so the user always types the model id manually.
    _EMBEDDING_PROVIDER_MODELS = {
        "openai":    ["text-embedding-3-small", "text-embedding-3-large"],
        "dashscope": ["text-embedding-v4"],
        "doubao":    ["doubao-embedding-vision-251215"],
        "zhipu":     ["embedding-3"],
        "linkai":    ["text-embedding-3-small"],
        "custom":    [],
    }

    # Capability-scoped model catalogs. The chat dropdown can reuse the
    # provider's generic model list, but vision and image generation are
    # served by a narrower subset that the runtime actually dispatches to —
    # see agent/tools/vision/vision.py and skills/image-generation/SKILL.md.
    # Anything not listed here intentionally hides the model dropdown so
    # users cannot pin a chat-only model and silently get a 4xx at runtime.
    _VISION_PROVIDER_MODELS = {
        # DeepSeek 视觉模型：deepseek-flash（V4.1，原生多模态），其次是
        # deepseek-v4-flash-vision-exp。deepseek-flash 是项目默认主模型，一把
        # DeepSeek key 即可同时覆盖对话与视觉。
        "deepseek":  [const.DEEPSEEK_FLASH, const.DEEPSEEK_V4_FLASH_VISION_EXP],
        # OpenAI ordering puts the GPT-5.6 family first, then GPT-5.5/5.4,
        # GPT-5 and the GPT-4.1/4o backstops.
        "openai":    [
            const.GPT_56_LUNA,
            const.GPT_56_TERRA,
            const.GPT_56_SOL,
            const.GPT_55,
            const.GPT_54,
            const.GPT_54_MINI,
            const.GPT_54_NANO,
            const.GPT_5,
            const.GPT_41,
            const.GPT_41_MINI,
            const.GPT_4o,
        ],
        "doubao":    [const.DOUBAO_SEED_2_1_PRO, const.DOUBAO_SEED_2_1_TURBO, const.DOUBAO_SEED_2_PRO],
        "moonshot":  [const.KIMI_K2_6],
        "dashscope": [const.QWEN38_FLASH, const.QWEN37_PLUS, const.QWEN36_PLUS],
        # claude-sonnet-5 stays first here (unlike the chat lists): the first
        # entry is the auto-picked vision model, and image understanding does
        # not justify the Opus price.
        "claudeAPI": [const.CLAUDE_SONNET_5, const.CLAUDE_OPUS_5, const.CLAUDE_FABLE_5_1, const.CLAUDE_FABLE_5, const.CLAUDE_4_8_OPUS, const.CLAUDE_4_7_OPUS, const.CLAUDE_4_6_SONNET, const.CLAUDE_4_6_OPUS],
        "gemini":    [const.GEMINI_38_FLASH, const.GEMINI_37_FLASH, const.GEMINI_36_FLASH, const.GEMINI_35_FLASH, const.GEMINI_31_FLASH_LITE_PRE, const.GEMINI_31_PRO_PRE, const.GEMINI_3_FLASH_PRE],
        "qianfan":   [const.ERNIE_45_TURBO_VL],
        # glm-5.3-flash is natively multimodal and dispatched as-is; the
        # text-only chat models (glm-5.2, glm-5-turbo, etc.) fall back to the
        # dedicated glm-5v-turbo vision model (see
        # models/zhipuai/zhipuai_bot.py::call_vision).
        "zhipu":     [const.GLM_5_3_FLASH, const.GLM_5V_TURBO],
        # MiniMax-M3 natively accepts text, image, and video input. The M2.x
        # chat family remains text-only and is not offered for vision.
        "minimax":   [const.MINIMAX_M3],
        # MiMo 原生全模态模型：v2.5-pro / v2.5 支持图像/音频/视频输入
        "mimo":      [const.MIMO_V2_5_PRO, const.MIMO_V2_5],
        # LinkAI proxies the underlying vendor; surface a curated set of
        # multimodal models. Order: gpt-4.1-mini → gpt-5.4-mini as the
        # cross-vendor baselines, then each vendor's recommended default.
        "linkai":    [
            const.GPT_41_MINI,
            const.GPT_54_MINI,
            const.QWEN38_FLASH,
            const.QWEN37_PLUS,
            const.DOUBAO_SEED_2_1_PRO,
            const.KIMI_K2_6,
            const.CLAUDE_SONNET_5,
            const.CLAUDE_FABLE_5_1,
            const.CLAUDE_FABLE_5,
            const.GEMINI_31_FLASH_LITE_PRE,
        ],
        # Custom OpenAI-compatible providers have no preset list — model
        # names vary per vendor, so the user types the model id manually.
        "custom": [],
    }

    # Image-generation catalog. Source of truth: skills/image-generation/SKILL.md.
    # Listed verbatim (not via const.*) because these are skill-side names
    # the script forwards directly to the vendor's image endpoint.
    #
    # Two shapes are accepted per model entry:
    #   - bare string                           → the model id, no hint
    #   - {"value": ..., "hint": "..."}         → model id + dim secondary
    #                                             label rendered on the right
    #                                             of the dropdown row. Useful
    #                                             for surfacing brand names
    #                                             (e.g. "Nano Banana 2" next
    #                                             to gemini-3.1-flash-image-preview).
    # The skill itself maps either form to the real vendor endpoint, so the
    # hint is purely cosmetic.
    _IMAGE_PROVIDER_MODELS = {
        "openai":    ["gpt-image-2.5-flare", "gpt-image-2.5-sunburst", "gpt-image-2", "gpt-image-1"],
        "gemini": [
            {"value": "gemini-3.1-flash-image-preview", "hint": "Nano Banana 2"},
            {"value": "gemini-3-pro-image-preview",     "hint": "Nano Banana Pro"},
            {"value": "gemini-2.5-flash-image",         "hint": "Nano Banana"},
        ],
        "doubao":    ["seedream-5.0-lite", "seedream-4.5"],
        "dashscope": ["qwen-image-2.0-pro", "qwen-image-2.0"],
        "minimax":   ["image-01"],
        "linkai": [
            "gpt-image-2.5-flare",
            "gpt-image-2.5-sunburst",
            "gpt-image-2",
            {"value": "gemini-3.1-flash-image-preview", "hint": "Nano Banana 2"},
            {"value": "gemini-3-pro-image-preview",     "hint": "Nano Banana Pro"},
            "seedream-5.0-lite",
        ],
        "custom": [],
    }

    @staticmethod
    def _config_path() -> str:
        return os.path.join(get_data_root(), "config.json")

    @classmethod
    def _read_file_config(cls) -> dict:
        return _read_config_file_for_write()

    @classmethod
    def _write_file_config(cls, data: dict) -> None:
        _write_config_file_for_write(cls._config_path(), data)

    @classmethod
    def _custom_provider_cards(cls, local_config: dict) -> List[dict]:
        """Expand ``custom_providers`` into one card per provider.

        Each user-defined OpenAI-compatible provider becomes its own card with
        id ``custom:<id>`` so the frontend can render, edit, delete and
        activate them independently. The card carries ``is_custom=True`` and
        ``active`` flags that the UI uses to render the extra controls.

        Returns an empty list when no multi-providers are configured, in which
        case the caller keeps the single legacy ``custom`` card untouched —
        guaranteeing backward compatibility with the flat
        ``custom_api_key`` / ``custom_api_base`` config.
        """
        try:
            from models.custom_provider import get_custom_providers, parse_custom_bot_type
            providers = get_custom_providers()
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"[ModelsHandler] failed to load custom_providers: {e}")
            providers = []
        if not providers:
            return []

        # Determine the currently active provider id from bot_type.
        bot_type = local_config.get("bot_type") or ""
        _, active_id = parse_custom_bot_type(bot_type)

        meta = PROVIDER_MODELS.get("custom") or {}
        catalog_map = model_catalog.get_catalog_map()
        hidden_map = model_catalog.get_hidden_map()
        cards = []
        for p in providers:
            pid = p.get("id") or ""
            name = p.get("name") or pid
            raw_key = p.get("api_key") or ""
            raw_base = p.get("api_base") or ""
            # A custom (OpenAI-compatible) provider's API key is optional — some
            # self-hosted / gateway endpoints need no auth. Treat the provider
            # as configured once it has an api_base, so a keyless-but-valid
            # endpoint isn't shown as an unconfigured (greyed-out) vendor.
            configured = bool(raw_base) or is_real_key(raw_key)
            # A custom endpoint has no presets, so its overrides are its whole
            # list and there is nothing to tombstone.
            catalog = catalog_map.get(f"custom:{pid}") or []
            cards.append({
                "id": f"custom:{pid}",
                "label": {"zh": name, "en": name},
                "configured": configured,
                "is_custom": True,
                "custom_id": pid,
                "custom_name": name,
                "active": (pid == active_id),
                "model": p.get("model") or "",
                # Custom cards are edited via the dedicated set_custom_provider
                # action, not the field-based set_provider flow, so the field
                # names are intentionally null.
                "api_key_field": None,
                "api_base_field": None,
                "api_key_masked": mask_key(raw_key) if is_real_key(raw_key) else "",
                "api_base": raw_base,
                "api_base_default": "",
                "api_base_placeholder": meta.get("api_base_placeholder") or "",
                "catalog": catalog,
                "hidden": hidden_map.get(f"custom:{pid}") or [],
                "seed": [],
                "effective": catalog,
                "models": ([e["name"] for e in catalog] if catalog
                           else ([p.get("model")] if p.get("model") else [])),
            })
        return cards

    @classmethod
    def _provider_overview(cls) -> List[dict]:
        """All known providers (configured first, unconfigured after).
        Re-uses PROVIDER_MODELS for the canonical list.

        When the user has defined multiple custom (OpenAI-compatible)
        providers via ``custom_providers``, the single built-in ``custom``
        card is replaced by one card per provider (see
        ``_custom_provider_cards``). Otherwise the legacy single ``custom``
        card is shown unchanged.
        """
        local_config = conf()
        custom_cards = cls._custom_provider_cards(local_config)
        # Keep the legacy single "custom" card visible alongside the expanded
        # ones when the flat custom_api_key/base config is still active or
        # filled, so existing single-provider setups never disappear from the UI.
        keep_legacy_custom = legacy_custom_in_use(local_config)
        catalog_map = model_catalog.get_catalog_map()
        hidden_map = model_catalog.get_hidden_map()
        items = []
        for pid, p in PROVIDER_MODELS.items():
            if pid == "custom" and custom_cards:
                # Multi-provider mode: emit the expanded cards, plus the
                # legacy card when it is still in use.
                items.extend(custom_cards)
                if not keep_legacy_custom:
                    continue
            key_field = p.get("api_key_field")
            base_field = p.get("api_base_key")
            raw_key = local_config.get(key_field, "") if key_field else ""
            raw_base = local_config.get(base_field, "") if base_field else ""
            configured = is_real_key(raw_key)
            overrides = catalog_map.get(pid) or []
            hidden = hidden_map.get(pid) or []
            seed = [] if pid == "custom" else cls._preset_seed(pid)
            # The editor prefills from the effective list (presets minus
            # removals, plus overrides), so the user always edits the full
            # list — adding one model can no longer wipe the rest.
            effective = cls._merged_catalog(pid, seed, catalog_map, hidden_map)
            items.append({
                "id": pid,
                "label": p["label"],
                "configured": configured,
                "is_custom": (pid == "custom"),
                "api_key_field": key_field,
                "api_base_field": base_field,
                "api_key_masked": mask_key(raw_key) if configured else "",
                "api_base": raw_base or (p.get("api_base_default") or ""),
                "api_base_default": p.get("api_base_default") or "",
                "api_base_placeholder": p.get("api_base_placeholder") or "",
                # Raw stored overlay (overrides + tombstones), so the editor can
                # tell what the user actually changed from the presets.
                "catalog": overrides,
                "hidden": hidden,
                # Preset models pre-typed with their real capabilities: the base
                # the editor diffs against and the "restore presets" reset uses.
                "seed": seed,
                # The full effective list the editor loads as its rows.
                "effective": effective,
                "models": [e["name"] for e in effective] if effective
                          else list(p.get("models") or []),
            })

        def _sort_key(it):
            pid = it["id"]
            # Custom expanded cards share the sort weight of the base "custom"
            # entry so they cluster where the single custom card used to be.
            base_id = "custom" if it.get("is_custom") else pid
            try:
                order = list(PROVIDER_MODELS.keys()).index(base_id)
            except ValueError:
                order = len(PROVIDER_MODELS)
            return (0 if it["configured"] else 1, order)

        items.sort(key=_sort_key)
        return items

    # Map a chat `model` name to a provider id in PROVIDER_MODELS. Mirrors the
    # inference in bridge.py::Bridge.__init__ so that a config with an empty
    # `bot_type` (valid at runtime, since the bridge derives the provider from
    # `model`) is still recognized as "configured" by the models handler and
    # doesn't wrongly trigger the onboarding wizard. Prefix rules are ordered
    # most-specific first; the returned ids are the PROVIDER_MODELS keys.
    @staticmethod
    def _infer_provider_from_model(model: str) -> str:
        """Best-effort provider id from a model name. Returns "" when unknown.

        Kept deliberately tolerant: any unexpected input yields "" rather than
        raising, so callers can treat "no inference" and "bad input" the same.
        """
        try:
            if not model or not isinstance(model, str):
                return ""
            m = model.strip().lower()
            if not m:
                return ""
            # Exact matches first (models whose name isn't a clean prefix).
            exact = {
                "wenxin": "qianfan",
                "wenxin-4": "qianfan",
                "abab6.5": "minimax",
                "abab6.5-chat": "minimax",
            }
            if m in exact:
                return exact[m]
            # Prefix rules — order matters where prefixes could overlap.
            prefix_rules = (
                ("deepseek", "deepseek"),
                ("gemini", "gemini"),
                ("glm", "zhipu"),
                ("claude", "claudeAPI"),
                ("kimi", "moonshot"),
                ("moonshot", "moonshot"),
                ("doubao", "doubao"),
                ("mimo-", "mimo"),
                ("qwen", "dashscope"),
                ("qwq", "dashscope"),
                ("qvq", "dashscope"),
                ("ernie", "qianfan"),
                ("minimax", "minimax"),
                ("gpt", "openai"),
                ("o1", "openai"),
                ("o3", "openai"),
                ("o4", "openai"),
            )
            for prefix, pid in prefix_rules:
                if m.startswith(prefix):
                    return pid
            # `qianfan` is sometimes used directly as the model name.
            if m == "qianfan":
                return "qianfan"
            return ""
        except Exception:
            # Never let inference break the models endpoint / startup.
            return ""

    @classmethod
    def _chat_capability(cls, local_config: dict) -> dict:
        """Main chat model — drives the agent. bot_type maps to a provider id."""
        bot_type = local_config.get("bot_type") or ""
        provider_id = "openai" if bot_type == "chatGPT" else bot_type
        is_custom_id = provider_id.startswith("custom:")
        if (provider_id not in PROVIDER_MODELS and not is_custom_id
                and local_config.get("use_linkai")):
            provider_id = "linkai"
        # When `bot_type` doesn't resolve to a known provider (e.g. it was
        # left empty by a config edit, which the runtime bridge tolerates by
        # inferring from `model`), fall back to the same model-based inference
        # here. Otherwise the wizard would treat a working setup as unconfigured
        # and re-open on every launch. Guarded so a failure can't affect startup.
        if provider_id not in PROVIDER_MODELS and not is_custom_id:
            try:
                inferred = cls._infer_provider_from_model(local_config.get("model", ""))
                if inferred in PROVIDER_MODELS:
                    provider_id = inferred
            except Exception:
                pass
        # In multi-provider mode, replace the single "custom" entry with the
        # expanded "custom:<id>" ids so the chat dropdown matches the cards.
        # The legacy "custom" entry stays when its flat config is still used.
        provider_ids = []
        custom_cards = cls._custom_provider_cards(local_config)
        keep_legacy_custom = legacy_custom_in_use(local_config)
        for pid in PROVIDER_MODELS.keys():
            if pid == "custom" and custom_cards:
                provider_ids.extend(c["id"] for c in custom_cards)
                if keep_legacy_custom:
                    provider_ids.append(pid)
            else:
                provider_ids.append(pid)
        return {
            "editable": True,
            "current_provider": provider_id,
            "current_model": local_config.get("model", ""),
            "providers": provider_ids,
            # Chat has no preset model list (vendors' models[] drives the
            # dropdown); a catalog narrows it to text-tagged entries.
            "provider_models": cls._apply_catalog({}, "text", custom_cards),
            "use_linkai": bool(local_config.get("use_linkai", False)),
        }

    @staticmethod
    def _chat_preset_models() -> dict:
        """{provider_id: [model, ...]} for every chat-capable vendor.

        ``PROVIDER_MODELS`` carries per-vendor metadata
        (label, api_key_field, ...) around the model list; the console's model
        picker wants only the lists. Used as the base for the fallback card's
        model lists, so a vendor without a catalog still offers its presets
        while a catalogued one offers its catalog instead.
        """
        out = {}
        for pid, meta in PROVIDER_MODELS.items():
            models = (meta or {}).get("models")
            out[pid] = list(models) if isinstance(models, (list, tuple)) else []
        return out

    @classmethod
    def _chat_fallback_capability(cls, local_config: dict) -> dict:
        """The fallback chain, tried in order after the primary model fails.

        Deliberately separate from ``_chat_capability``: the primary model is
        the one that answers, while this is a safety net that stays idle until
        an outage. It is opt-in (``enabled`` defaults to false) and every link
        needs both a provider and a model — a half-filled link is dropped so a
        partially configured chain can never hijack a healthy setup.

        The chain is ordered and unbounded: the console renders one editable
        row per link and the runtime walks them front to back, so the number of
        links the user saves *is* the number of backups a turn gets.
        """
        cfg = local_config.get("chat_fallback") or {}
        if not isinstance(cfg, dict):
            cfg = {}
        raw_chain = cfg.get("chain")
        chain = []
        if isinstance(raw_chain, list):
            for item in raw_chain:
                if not isinstance(item, dict):
                    continue
                chain.append({
                    "provider": (item.get("provider") or "").strip(),
                    "model": (item.get("model") or "").strip(),
                })
        elif isinstance(cfg, dict) and (cfg.get("provider") or cfg.get("model")):
            # Pre-chain config: surface it as a one-link chain so the console
            # shows what is configured instead of an empty list.
            chain = [{
                "provider": (cfg.get("provider") or "").strip(),
                "model": (cfg.get("model") or "").strip(),
            }]
        # Same provider list as the primary chat card, so the dropdowns always
        # offer identical choices (including expanded custom:<id>).
        primary = cls._chat_capability(local_config)
        # Same model lists too: start from the vendors' presets and let a
        # catalog override them, which is what the primary card does. Building
        # this from the presets alone would leave the fallback on a free-form
        # model field for a vendor whose models the primary card can list.
        custom_cards = cls._custom_provider_cards(local_config)
        return {
            "editable": True,
            "enabled": bool(cfg.get("enabled", False)),
            "providers": primary.get("providers", []),
            # The model picker expects {provider_id: [models]}. PROVIDER_MODELS
            # is richer ({provider_id: {label, models, ...}}), so reduce it to
            # just the lists — handing over the raw dict makes the web console
            # call .slice() on a mapping and throw.
            "provider_models": cls._apply_catalog(
                cls._chat_preset_models(), "text", custom_cards),
            "chain": chain,
            # Kept for older clients that still read a single backup model:
            # link 1 of the chain, so a downgraded console does not show blank.
            "current_provider": chain[0]["provider"] if chain else "",
            "current_model": chain[0]["model"] if chain else "",
            # Shown in the UI so it's obvious the fallback is inactive.
            "primary_provider": primary.get("current_provider", ""),
            "primary_model": primary.get("current_model", ""),
        }

    # Auto-fallback order for vision when no explicit model is pinned.
    # Mirrors agent/tools/vision/vision.py::_resolve_providers — DeepSeek and
    # other text-only chat bots are intentionally absent, since they cannot
    # actually serve a vision request. Each entry is
    #   (provider_id, api_key_field, default_vision_model)
    # and lookups are case-insensitive on the api_key_field. LinkAI and
    # OpenAI are handled separately below so use_linkai can promote LinkAI
    # to the front of the chain.
    _VISION_AUTO_ORDER = [
        ("moonshot",  "moonshot_api_key",  const.KIMI_K2_6),
        ("doubao",    "ark_api_key",       const.DOUBAO_SEED_2_PRO),
        ("dashscope", "dashscope_api_key", const.QWEN37_PLUS),
        ("claudeAPI", "claude_api_key",    const.CLAUDE_SONNET_5),
        ("gemini",    "gemini_api_key",    const.GEMINI_38_FLASH),
        ("qianfan",   "qianfan_api_key",   const.ERNIE_45_TURBO_VL),
        ("zhipu",     "zhipu_ai_api_key",  const.GLM_5V_TURBO),
        ("minimax",   "minimax_api_key",   const.MINIMAX_M3),
        ("mimo",      "mimo_api_key",      const.MIMO_V2_5_PRO),
    ]

    @classmethod
    def _predict_vision_auto(cls, local_config: dict) -> dict:
        """Predict which provider vision.py will actually dispatch to when
        no tools.vision.model is set. Mirrors the fallback order in
        agent/tools/vision/vision.py::_resolve_providers so the UI hint
        matches reality."""
        chat = cls._chat_capability(local_config)
        main_provider = chat["current_provider"]
        main_model = chat["current_model"]
        use_linkai_flag = bool(local_config.get("use_linkai", False))
        linkai_configured = is_real_key(local_config.get("linkai_api_key", ""))

        def _try(pid: str, model_default: str):
            # Look up the api_key for this provider via the canonical
            # provider table so we don't hardcode field names here.
            meta = PROVIDER_MODELS.get(pid) or {}
            key_field = meta.get("api_key_field")
            if not key_field:
                return None
            if not is_real_key(local_config.get(key_field, "")):
                return None
            # Pick a model that the vision runtime can actually dispatch to
            # for this provider. Using `main_model` here is unsafe — for
            # vendors like Zhipu/MiniMax the bot hard-codes the vision model
            # name regardless of the chat-model name, so surfacing the chat
            # model name in the hint is misleading. Trust the curated
            # _VISION_PROVIDER_MODELS list: prefer the main model only if
            # it appears there; otherwise show the vendor's first vision-
            # capable model.
            allowed = cls._VISION_PROVIDER_MODELS.get(pid, [])
            if pid == main_provider and main_model and main_model in allowed:
                return {"provider": pid, "model": main_model}
            fallback = allowed[0] if allowed else model_default
            return {"provider": pid, "model": fallback}

        # 1. use_linkai → suppress the hint entirely. LinkAI is a proxy and
        #    we don't observe which underlying model it picks; surfacing
        #    "LinkAI" with no model would not tell the user anything useful.
        if use_linkai_flag and linkai_configured:
            return {"provider": "", "model": ""}

        # 2. Main bot — only when it natively supports vision. We approximate
        #    "natively supports" by membership in _VISION_PROVIDER_MODELS,
        #    which is the same set vision.py's _DISCOVERABLE_MODELS covers
        #    (the DeepSeek family is included since V4 Flash vision).
        if main_provider in cls._VISION_PROVIDER_MODELS:
            hit = _try(main_provider, main_model)
            if hit:
                return hit

        # 3. Other discoverable providers in declared order
        for pid, _key, default_model in cls._VISION_AUTO_ORDER:
            hit = _try(pid, default_model)
            if hit:
                return hit

        # 4. OpenAI raw HTTP
        if is_real_key(local_config.get("open_ai_api_key", "")):
            return {"provider": "openai", "model": const.GPT_55}

        # 5. LinkAI as last resort (only reached when use_linkai is off)
        if linkai_configured:
            return {"provider": "linkai", "model": const.GPT_41_MINI}

        return {"provider": "", "model": ""}

    @classmethod
    def _vision_capability(cls, local_config: dict) -> dict:
        """Vision model. tools.vision.model is the explicit override; otherwise
        the runtime fallback chain in agent/tools/vision/vision.py decides."""
        tools_conf = local_config.get("tools") or local_config.get("tool") or {}
        if not isinstance(tools_conf, dict):
            tools_conf = {}
        vision_conf = tools_conf.get("vision") or {}
        if not isinstance(vision_conf, dict):
            vision_conf = {}
        user_specified = (vision_conf.get("model") or "").strip()
        explicit_provider = (vision_conf.get("provider") or "").strip()

        # Build provider list: built-in providers + expanded custom:<id> entries.
        # Same pattern as _embedding_capability — each user-created custom
        # provider gets its own dropdown entry showing the user-chosen name.
        providers = []
        custom_cards = cls._custom_provider_cards(local_config)
        for pid in cls._VISION_PROVIDER_MODELS:
            if pid == "custom":
                if custom_cards:
                    providers.extend(c["id"] for c in custom_cards)
            else:
                providers.append(pid)

        # Provider resolution priority:
        #   1. Explicit `tools.vision.provider` (persisted via UI; supports
        #      custom model names that prefix-inference can't recognize).
        #   2. Scan per-provider model lists by model name.
        # Empty provider keeps the dropdown on "auto" when we can't tell.
        inferred_provider = ""
        if explicit_provider and explicit_provider in providers:
            inferred_provider = explicit_provider
        elif user_specified:
            for pid, models in cls._VISION_PROVIDER_MODELS.items():
                if user_specified in models:
                    # For "custom" key, map to the first custom card
                    inferred_provider = custom_cards[0]["id"] if pid == "custom" and custom_cards else pid
                    break

        # In auto mode the hint should reflect what vision.py will actually
        # dispatch to — surface that prediction via fallback_* so the UI
        # shows e.g. "openai / gpt-4.1-mini" instead of the chat-model name.
        predicted = cls._predict_vision_auto(local_config)

        return {
            "editable": True,
            "strategy": "specified" if user_specified else "auto",
            "user_specified_model": user_specified,
            "current_provider": inferred_provider,
            "current_model": user_specified,
            "fallback_provider": predicted["provider"],
            "fallback_model": predicted["model"],
            "providers": providers,
            "provider_models": cls._apply_catalog(
                cls._VISION_PROVIDER_MODELS, "vision", custom_cards
            ),
        }

    @classmethod
    def _asr_capability(cls, local_config: dict) -> dict:
        # "Pick or empty" — when voice_to_text is unset we don't show a
        # current selection. `suggested_provider` previews which vendor
        # the bridge auto-picker would land on (purely a UX hint, NOT
        # persisted). Once the user saves a vendor, we lock onto it.
        explicit = (local_config.get("voice_to_text") or "").strip().lower()
        suggested = ""
        if not explicit:
            for pid in cls._ASR_PROVIDERS:
                meta = PROVIDER_MODELS.get(pid) or {}
                key_field = meta.get("api_key_field")
                if key_field and is_real_key(local_config.get(key_field, "")):
                    suggested = pid
                    break
        # Custom (OpenAI-compatible) vendors are selectable too — same pattern
        # as _vision_capability: each expanded custom:<id> gets an entry.
        providers = list(cls._ASR_PROVIDERS)
        custom_cards = cls._custom_provider_cards(local_config)
        if custom_cards:
            providers.extend(c["id"] for c in custom_cards)
        return {
            "editable": True,
            "current_provider": explicit,
            "suggested_provider": suggested,
            "current_model": (local_config.get("voice_to_text_model") or "") if explicit else "",
            "providers": providers,
            "provider_models": cls._apply_catalog(cls._ASR_PROVIDER_MODELS, "asr", custom_cards),
        }

    @classmethod
    def _tts_capability(cls, local_config: dict) -> dict:
        explicit = (local_config.get("text_to_voice") or "").strip().lower()
        # Custom (OpenAI-compatible) vendors are selectable too; accept them
        # (expanded custom:<id> or legacy flat "custom") as the current
        # provider so the card shows the saved selection. Other providers
        # outside the white-list don't drive the picker, but their underlying
        # runtime config is preserved so bridge still routes them.
        is_custom_id = explicit.startswith("custom:") or explicit == "custom"
        ui_provider = explicit if (explicit in cls._TTS_PROVIDERS or is_custom_id) else ""
        suggested = ""
        if not ui_provider:
            for pid in cls._TTS_PROVIDERS:
                meta = PROVIDER_MODELS.get(pid) or {}
                key_field = meta.get("api_key_field")
                if key_field and is_real_key(local_config.get(key_field, "")):
                    suggested = pid
                    break
        providers = list(cls._TTS_PROVIDERS)
        custom_cards = cls._custom_provider_cards(local_config)
        if custom_cards:
            providers.extend(c["id"] for c in custom_cards)
        return {
            "editable": True,
            "current_provider": ui_provider,
            "suggested_provider": suggested,
            "current_model": (local_config.get("text_to_voice_model") or "") if ui_provider else "",
            "current_voice": (local_config.get("tts_voice_id") or "") if ui_provider else "",
            "providers": providers,
            "provider_models": cls._apply_catalog(cls._TTS_PROVIDER_MODELS, "tts", custom_cards),
            "provider_voices": cls._TTS_PROVIDER_VOICES,
            "reply_mode": cls._tts_reply_mode(local_config),
        }

    @staticmethod
    def _tts_reply_mode(local_config: dict) -> str:
        if local_config.get("always_reply_voice", False):
            return "always"
        if local_config.get("voice_reply_voice", False):
            return "voice_if_voice"
        return "off"

    @classmethod
    def _embedding_capability(cls, local_config: dict) -> dict:
        # Embedding is "pick or empty" — runtime's legacy openai/linkai
        # fallback is a safety net, not a UX-visible auto mode.
        # `suggested_provider` is a UI-only hint (NOT persisted) that
        # preselects the dropdown to whichever configured vendor we'd
        # recommend, so users don't have to expand the menu to find it.
        explicit = (local_config.get("embedding_provider") or "").strip().lower()
        suggested = ""
        if not explicit:
            for pid in cls._EMBEDDING_PROVIDERS:
                if pid == "custom":
                    continue
                meta = PROVIDER_MODELS.get(pid) or {}
                key_field = meta.get("api_key_field")
                if key_field and is_real_key(local_config.get(key_field, "")):
                    suggested = pid
                    break
            if not suggested:
                custom_cards = cls._custom_provider_cards(local_config)
                if custom_cards:
                    suggested = custom_cards[0]["id"]

        # Build provider list: built-in providers + expanded custom:<id> entries
        # Same pattern as _chat_capability — each user-created custom provider
        # gets its own dropdown entry showing the user-chosen name.
        providers = []
        custom_cards = cls._custom_provider_cards(local_config)
        for pid in cls._EMBEDDING_PROVIDERS:
            if pid == "custom":
                if custom_cards:
                    providers.extend(c["id"] for c in custom_cards)
                # No custom providers configured — skip the bare "custom" entry
                # since the runtime cannot resolve its credentials.
            else:
                providers.append(pid)

        return {
            "editable": True,
            "current_provider": explicit,
            "suggested_provider": suggested,
            "current_model": local_config.get("embedding_model", "") or "",
            "current_dim": int(local_config.get("embedding_dimensions") or 0) or None,
            "providers": providers,
            "provider_models": cls._apply_catalog(cls._EMBEDDING_PROVIDER_MODELS, "embedding", custom_cards),
        }

    # Auto-fallback order for image generation. Mirrors the global priority
    # used inside skills/image-generation/scripts/generate.py
    # (`_DEFAULT_PROVIDER_ORDER`): OpenAI → Gemini → Seedream(Ark/doubao) →
    # Qwen(dashscope) → MiniMax → LinkAI. Each entry maps the
    # provider-card id to the script's per-provider DEFAULT_MODEL so the
    # hint matches what the runtime would actually request.
    _IMAGE_AUTO_ORDER = [
        ("openai",    "gpt-image-2.5-flare"),
        ("gemini",    "gemini-3.1-flash-image-preview"),  # nano-banana-2
        ("doubao",    "seedream-5.0-lite"),
        ("dashscope", "qwen-image-2.0"),
        ("minimax",   "image-01"),
        ("linkai",    "gpt-image-2.5-flare"),
    ]

    @classmethod
    def _predict_image_auto(cls, local_config: dict) -> dict:
        """Predict which provider/model the image-generation skill will hit
        when no SKILL_IMAGE_GENERATION_MODEL override is set. Mirrors
        skills/image-generation/scripts/generate.py::_build_providers so
        the UI hint matches reality. Chat-only providers (DeepSeek etc.)
        are absent by design — image generation never falls back to a chat
        bot regardless of the main model.

        When use_linkai is enabled the hint is suppressed entirely — LinkAI
        proxies to whichever backend it deems appropriate and surfacing
        "LinkAI" alone tells the user nothing actionable."""
        use_linkai_flag = bool(local_config.get("use_linkai", False))
        linkai_configured = is_real_key(local_config.get("linkai_api_key", ""))
        if use_linkai_flag and linkai_configured:
            return {"provider": "", "model": ""}

        for pid, default_model in cls._IMAGE_AUTO_ORDER:
            meta = PROVIDER_MODELS.get(pid) or {}
            key_field = meta.get("api_key_field")
            if not key_field:
                continue
            if is_real_key(local_config.get(key_field, "")):
                return {"provider": pid, "model": default_model}
        return {"provider": "", "model": ""}

    @classmethod
    def _image_capability(cls, local_config: dict) -> dict:
        """Image generation. Source of truth: config["skills"]["image-generation"]["model"]
        (mirrors the per-skill config schema documented in skills/image-generation).
        The runtime resolver in skills/image-generation/scripts/generate.py
        reads this via the SKILL_IMAGE_GENERATION_MODEL env var that the
        agent_initializer syncs at startup; provider is inferred from the
        model name prefix, mirroring vision.py's design.

        ``skill`` (singular) is still tolerated as a legacy fallback —
        config.load_config() folds it into ``skills`` at startup.
        """
        skills_node = local_config.get("skills") or local_config.get("skill") or {}
        if not isinstance(skills_node, dict):
            skills_node = {}
        img_node = skills_node.get("image-generation") or {}
        if not isinstance(img_node, dict):
            img_node = {}
        explicit_model = (img_node.get("model") or "").strip()
        explicit_provider = (img_node.get("provider") or "").strip()

        providers = []
        custom_cards = cls._custom_provider_cards(local_config)
        for provider_id in cls._IMAGE_PROVIDER_MODELS:
            if provider_id == "custom":
                providers.extend(
                    card["id"] for card in custom_cards
                )
            else:
                providers.append(provider_id)

        # Provider resolution priority:
        #   1. Explicit `skills.image-generation.provider` (persisted via UI;
        #      supports custom model names that prefix-inference can't catch).
        #   2. Scan per-provider model catalog by model name.
        # Empty provider keeps the dropdown on "auto" when we can't tell.
        inferred_provider = ""
        if explicit_provider and explicit_provider in providers:
            inferred_provider = explicit_provider
        elif explicit_model:
            for pid, models in cls._IMAGE_PROVIDER_MODELS.items():
                for entry in models:
                    val = entry if isinstance(entry, str) else (entry.get("value") or "")
                    if val == explicit_model:
                        inferred_provider = pid
                        break
                if inferred_provider:
                    break

        # In auto mode the hint should reflect what generate.py will actually
        # dispatch to — surface that prediction via fallback_* so the UI
        # never claims a chat-only bot (e.g. minimax/MiniMax-M2.7) "would
        # generate the image", which is impossible.
        predicted = cls._predict_image_auto(local_config)

        return {
            "editable": True,
            "strategy": "specified" if explicit_model else "auto",
            "current_provider": inferred_provider,
            "current_model": explicit_model,
            "fallback_provider": predicted["provider"],
            "fallback_model": predicted["model"],
            "providers": providers,
            "provider_models": cls._apply_catalog(cls._IMAGE_PROVIDER_MODELS, "image", custom_cards),
            "runtime_active": True,
        }

    # Canonical search provider order. Mirrors PROVIDER_ORDER in
    # agent/tools/web_search/web_search.py — keep them in sync.
    _SEARCH_PROVIDERS = ("bocha", "qianfan", "zhipu", "linkai", "anysearch", "serply", "tavily", "searxng", "keenable")

    _SEARCH_PROVIDER_LABELS = {
        "bocha":   {"zh": "博查", "en": "Bocha"},
        "zhipu":   {"zh": "智谱", "en": "GLM"},
        "qianfan": {"zh": "百度", "en": "ERNIE"},
        "linkai":  {"zh": "LinkAI", "en": "LinkAI"},
        "anysearch": {"zh": "AnySearch", "en": "AnySearch"},
        "serply":  {"zh": "Serply", "en": "Serply"},
        "tavily":  {"zh": "Tavily", "en": "Tavily"},
        "searxng": {"zh": "SearXNG", "en": "SearXNG"},
        "keenable": {"zh": "Keenable", "en": "Keenable"},
    }

    @classmethod
    def _search_provider_key(cls, provider: str, local_config: dict) -> str:
        """Resolve the (raw) key for a given search provider."""
        if provider == "bocha":
            tools_cfg = local_config.get("tools") or {}
            block = tools_cfg.get("web_search") or {} if isinstance(tools_cfg, dict) else {}
            return (block.get("bocha_api_key") if isinstance(block, dict) else "") or os.environ.get("BOCHA_API_KEY", "")
        if provider == "zhipu":
            return local_config.get("zhipu_ai_api_key") or os.environ.get("ZHIPUAI_API_KEY", "")
        if provider == "qianfan":
            return local_config.get("qianfan_api_key") or os.environ.get("QIANFAN_API_KEY", "")
        if provider == "linkai":
            return local_config.get("linkai_api_key") or os.environ.get("LINKAI_API_KEY", "")
        if provider == "anysearch":
            tools_cfg = local_config.get("tools") or {}
            block = tools_cfg.get("web_search") or {} if isinstance(tools_cfg, dict) else {}
            return (block.get("anysearch_api_key") if isinstance(block, dict) else "") or os.environ.get(
                "ANYSEARCH_API_KEY", "")
        if provider == "serply":
            tools_cfg = local_config.get("tools") or {}
            block = tools_cfg.get("web_search") or {} if isinstance(tools_cfg, dict) else {}
            return (block.get("serply_api_key") if isinstance(block, dict) else "") or os.environ.get(
                "SERPLY_API_KEY", "")
        if provider == "tavily":
            tools_cfg = local_config.get("tools") or {}
            block = tools_cfg.get("web_search") or {} if isinstance(tools_cfg, dict) else {}
            return (block.get("tavily_api_key") if isinstance(block, dict) else "") or os.environ.get(
                "TAVILY_API_KEY", "")
        if provider == "keenable":
            tools_cfg = local_config.get("tools") or {}
            block = tools_cfg.get("web_search") or {} if isinstance(tools_cfg, dict) else {}
            return (block.get("keenable_api_key") if isinstance(block, dict) else "") or os.environ.get(
                "KEENABLE_API_KEY", "")
        # searxng uses an instance URL, not an API key — handled in _search_capability
        return ""

    @classmethod
    def _search_capability(cls, local_config: dict) -> dict:
        """Search is editable: pick auto (default) or pin a specific backend.
        Providers reuse model-vendor keys (zhipu/qianfan/linkai) so they show
        up as configured once the user adds those vendors; bocha keeps its
        own key under tools.web_search."""
        tools_cfg = local_config.get("tools") or {}
        ws_cfg = tools_cfg.get("web_search") or {} if isinstance(tools_cfg, dict) else {}
        if not isinstance(ws_cfg, dict):
            ws_cfg = {}

        anonymous_on = bool(ws_cfg.get("anysearch_anonymous"))
        keenable_anonymous_on = bool(ws_cfg.get("keenable_anonymous"))
        searxng_url = (ws_cfg.get("searxng_url") or "").strip() if isinstance(ws_cfg, dict) else ""
        providers = []
        configured_ids = []
        for pid in cls._SEARCH_PROVIDERS:
            raw_key = cls._search_provider_key(pid, local_config)
            if pid == "anysearch":
                # AnySearch: real key, or an explicit anonymous opt-in.
                ok = is_real_key(raw_key) or anonymous_on
            elif pid == "keenable":
                # Keenable: real key, or an explicit anonymous opt-in.
                ok = is_real_key(raw_key) or keenable_anonymous_on
            elif pid == "searxng":
                # SearXNG: self-hosted, no auth — available when instance URL is set.
                ok = bool(searxng_url)
            else:
                ok = is_real_key(raw_key)
            providers.append({
                "id": pid,
                "label": cls._SEARCH_PROVIDER_LABELS.get(pid, pid),
                "configured": ok,
                # bocha owns its key under tools.web_search; the other three
                # piggy-back on a model-vendor credential. Frontend uses
                # this hint to decide which credential editor to surface.
                # Lets the frontend badge "匿名/anonymous" only in anonymous mode.
                "anonymous": pid in ("anysearch", "keenable") and ok and not raw_key,
                "needs_dedicated_key": pid in ("bocha", "anysearch", "serply", "tavily", "keenable"),
                "needs_url": pid == "searxng",
                # SearXNG stores an instance URL (not a secret), so echo it back
                # verbatim to prefill/edit; other providers mask their key.
                "url_masked": searxng_url if pid == "searxng" else "",
                "api_key_masked": mask_key(raw_key) if raw_key else "",
            })
            if ok:
                configured_ids.append(pid)

        strategy = (ws_cfg.get("strategy") or "auto").strip().lower()
        if strategy not in ("auto", "fixed"):
            strategy = "auto"
        fixed_provider = (ws_cfg.get("provider") or "").strip().lower()
        if fixed_provider and fixed_provider not in configured_ids:
            fixed_provider = ""

        # current_provider drives the chip in the header — show the actually
        # active backend (pinned or first auto-picked).
        if strategy == "fixed" and fixed_provider:
            current = fixed_provider
        else:
            current = configured_ids[0] if configured_ids else ""

        return {
            "editable": True,
            "strategy": strategy,
            "providers": providers,
            "configured_providers": configured_ids,
            "current_provider": current,
            "fixed_provider": fixed_provider,
            "available": bool(current),
        }

    @classmethod
    def _capabilities(cls, local_config: dict) -> dict:
        return {
            "chat":      cls._chat_capability(local_config),
            "chat_fallback": cls._chat_fallback_capability(local_config),
            "vision":    cls._vision_capability(local_config),
            "asr":       cls._asr_capability(local_config),
            "tts":       cls._tts_capability(local_config),
            "embedding": cls._embedding_capability(local_config),
            "image":     cls._image_capability(local_config),
            "search":    cls._search_capability(local_config),
        }

    @classmethod
    def _apply_catalog(cls, presets: dict, capability, custom_cards=None) -> dict:
        """Layer per-provider catalog overlays onto a capability's model list.

        A provider without any overlay keeps its presets untouched. When the
        user has an overlay, the provider's effective list (preset base minus
        tombstones, plus overrides) is filtered to `capability` ("text" for the
        main chat model) so only models that can serve this role are offered."""
        merged = dict(presets)
        catalog_map = model_catalog.get_catalog_map()
        hidden_map = model_catalog.get_hidden_map()
        ids = [pid for pid in list(merged.keys()) + list(PROVIDER_MODELS.keys())
               if pid != "custom"]
        ids += [c["id"] for c in (custom_cards or [])]
        for pid in dict.fromkeys(ids):  # dedupe, keep order
            if not catalog_map.get(pid) and not hidden_map.get(pid):
                continue  # no overlay: presets stand as-is
            base_seed = [] if pid.startswith("custom:") else cls._preset_seed(pid)
            effective = cls._merged_catalog(pid, base_seed, catalog_map, hidden_map)
            merged[pid] = [
                {"value": e["name"]} for e in effective
                if capability is None or capability in (e.get("capabilities") or [])
            ]
        return merged

    # Researched specs (context window / max output) for built-in preset
    # models, from the vendors' official docs. Optional "capabilities" unions
    # extra tags the preset lists don't reflect yet (e.g. native-multimodal
    # models). Fields left off fall back to auto-detection.
    _PRESET_MODEL_META = {
        "deepseek-flash": {"capabilities": ["text", "vision"], "context_window": 1000000, "max_output_tokens": 393216},
        "deepseek-v4-flash": {"context_window": 1000000, "max_output_tokens": 393216},
        "deepseek-v4-pro": {"context_window": 1000000, "max_output_tokens": 393216},
        "glm-5.3-flash": {"context_window": 1000000, "max_output_tokens": 131072},
        "glm-5.3": {"context_window": 1000000, "max_output_tokens": 131072},
        "glm-5.2": {"context_window": 1000000, "max_output_tokens": 131072},
        "glm-5.1": {"context_window": 200000},
        "glm-5-turbo": {"context_window": 200000},
        "glm-5": {"context_window": 200000},
        "glm-4.7": {"context_window": 200000},
        "glm-5v-turbo": {"capabilities": ["text", "vision"]},
        "qwen3.8-flash": {"context_window": 1000000},
        "qwen3.8-max": {"context_window": 1000000},
        "qwen3.7-plus": {"context_window": 1000000},
        "qwen3.7-max": {"context_window": 1000000},
        "qwen3.6-plus": {"context_window": 128000},
        "kimi-k3": {"capabilities": ["text", "vision"], "context_window": 1048576},
        "kimi-k2.7-code": {"context_window": 262144},
        "kimi-k2.7-code-highspeed": {"context_window": 262144},
        "kimi-k2.6": {"context_window": 262144},
        "kimi-k2.5": {"context_window": 262144},
        "doubao-seed-2-1-pro-260628": {"context_window": 256000, "max_output_tokens": 32000},
        "doubao-seed-2-1-turbo-260628": {"context_window": 256000, "max_output_tokens": 32000},
        "doubao-seed-2-0-pro-260215": {"context_window": 256000},
        "doubao-seed-2-0-code-preview-260215": {"context_window": 256000},
        "ernie-5.1": {"context_window": 128000},
        "ernie-5.0": {"capabilities": ["text", "vision"], "context_window": 128000},
        "ernie-x1.1": {"context_window": 64000},
        "ernie-4.5-turbo-128k": {"context_window": 128000, "max_output_tokens": 16000},
        "ernie-4.5-turbo-32k": {"context_window": 32000, "max_output_tokens": 16000},
        "ernie-4.5-turbo-vl": {"capabilities": ["text", "vision"], "context_window": 128000, "max_output_tokens": 16000},
        "MiniMax-M3": {"capabilities": ["text", "vision", "video"], "context_window": 1000000, "max_output_tokens": 512000},
        "MiniMax-M2.7": {"context_window": 204800, "max_output_tokens": 196608},
        "MiniMax-M2.7-highspeed": {"context_window": 204800, "max_output_tokens": 196608},
        "MiniMax-Text-01": {"context_window": 1000000},
        "mimo-v2.5-pro": {"context_window": 1000000, "max_output_tokens": 131072},
        "mimo-v2.5": {"context_window": 1000000, "max_output_tokens": 131072},
        "gpt-5.6-luna": {"context_window": 1050000, "max_output_tokens": 128000},
        "gpt-5.6-terra": {"context_window": 1050000, "max_output_tokens": 128000},
        "gpt-5.6-sol": {"context_window": 1050000, "max_output_tokens": 128000},
        "gpt-5.5": {"context_window": 1050000, "max_output_tokens": 128000},
        "gpt-5.4": {"context_window": 1050000, "max_output_tokens": 128000},
        "gpt-5.4-mini": {"context_window": 1050000, "max_output_tokens": 128000},
        "gpt-5.4-nano": {"context_window": 1050000, "max_output_tokens": 128000},
        "gpt-5": {"context_window": 400000, "max_output_tokens": 128000},
        "gpt-4.1": {"context_window": 1047576, "max_output_tokens": 32768},
        "gpt-4.1-mini": {"context_window": 1047576, "max_output_tokens": 32768},
        "gpt-4o": {"context_window": 128000, "max_output_tokens": 16384},
        "claude-opus-5": {"context_window": 1000000, "max_output_tokens": 128000},
        "claude-sonnet-5": {"context_window": 1000000, "max_output_tokens": 128000},
        "claude-fable-5": {"context_window": 1000000, "max_output_tokens": 128000},
        "claude-opus-4-8": {"context_window": 200000, "max_output_tokens": 64000},
        "claude-opus-4-7": {"context_window": 200000, "max_output_tokens": 64000},
        "claude-sonnet-4-6": {"context_window": 200000, "max_output_tokens": 64000},
        "claude-opus-4-6": {"context_window": 200000, "max_output_tokens": 64000},
        "gemini-3.7-flash": {"context_window": 1048576, "max_output_tokens": 65536},
        "gemini-3.6-flash": {"context_window": 1048576, "max_output_tokens": 65536},
        "gemini-3.5-flash": {"context_window": 1048576, "max_output_tokens": 65536},
        "gemini-3.1-flash-lite-preview": {"context_window": 1048576, "max_output_tokens": 65536},
        "gemini-3.1-pro-preview": {"context_window": 1048576, "max_output_tokens": 65536},
        "gemini-3-flash-preview": {"context_window": 1048576, "max_output_tokens": 65536},
    }

    @classmethod
    def _preset_seed(cls, pid: str) -> List[dict]:
        """Type-tagged catalog entries for a built-in vendor's preset models.

        Membership in the per-capability preset lists IS the type: the chat
        list -> "text", the vision list -> "vision", etc. Tags merge across
        lists (gpt-4o -> text+vision, mimo-v2.5 -> text+vision+tts), so the
        catalog editor seeds each preset with its real capabilities."""
        merged: "OrderedDict[str, dict]" = OrderedDict()

        def add(name, cap):
            if not name:
                return
            entry = merged.setdefault(name, {"name": name, "capabilities": []})
            if cap not in entry["capabilities"]:
                entry["capabilities"].append(cap)

        for m in PROVIDER_MODELS.get(pid, {}).get("models") or []:
            add(m if isinstance(m, str) else m.get("value"), "text")
        tables = (
            ("vision", cls._VISION_PROVIDER_MODELS),
            ("asr", cls._ASR_PROVIDER_MODELS),
            ("tts", cls._TTS_PROVIDER_MODELS),
            ("embedding", cls._EMBEDDING_PROVIDER_MODELS),
            ("image", cls._IMAGE_PROVIDER_MODELS),
        )
        for cap, table in tables:
            for m in table.get(pid) or []:
                add(m if isinstance(m, str) else m.get("value"), cap)
        from agent.protocol.agent import resolve_family_spec
        for entry in merged.values():
            extra = cls._PRESET_MODEL_META.get(entry["name"]) or {}
            for cap in extra.get("capabilities", []):
                if cap not in entry["capabilities"]:
                    entry["capabilities"].append(cap)
            # Explicit researched specs win; otherwise fall back to the runtime
            # family table so the editor shows the same budget that actually
            # takes effect (e.g. gpt-6-astra -> 1M/128K) instead of a blank.
            fam_window, fam_output = resolve_family_spec(entry["name"])
            window = extra.get("context_window") or fam_window
            output = extra.get("max_output_tokens") or fam_output
            if window:
                entry["context_window"] = window
            if output:
                entry["max_output_tokens"] = output
        return list(merged.values())

    @classmethod
    def _merged_catalog(cls, pid, base_seed=None, catalog_map=None, hidden_map=None) -> List[dict]:
        """The provider's effective model list: preset base, minus removals,
        with user overrides layered on.

        The catalog is an overlay, not a replacement — a preset the user never
        touched stays on the list (and keeps following the code-side metadata),
        an overridden preset takes the user's values, a tombstoned preset drops
        out, and an override with a new name is appended.

        ``base_seed`` is the preset base; for a built-in vendor it defaults to
        ``_preset_seed(pid)``, and a custom provider passes ``[]`` (no presets,
        so its overrides are simply its whole list)."""
        if catalog_map is None:
            catalog_map = model_catalog.get_catalog_map()
        if hidden_map is None:
            hidden_map = model_catalog.get_hidden_map()
        overrides = catalog_map.get(pid) or []
        hidden = set(hidden_map.get(pid) or [])
        if base_seed is None:
            base_seed = [] if pid == "custom" else cls._preset_seed(pid)

        override_by_name = {e["name"]: e for e in overrides}
        merged: "OrderedDict[str, dict]" = OrderedDict()
        for entry in base_seed:
            name = entry.get("name")
            if not name or name in hidden:
                continue
            merged[name] = override_by_name.get(name, entry)
        # Appended models (overrides the presets don't carry), order preserved.
        for entry in overrides:
            name = entry.get("name")
            if name and name not in merged:
                merged[name] = entry
        return list(merged.values())

    def GET(self):
        _require_auth()
        web.header("Content-Type", "application/json; charset=utf-8")
        try:
            local_config = conf()
            return json.dumps({
                "status": "success",
                "providers": self._provider_overview(),
                "capabilities": self._capabilities(local_config),
            }, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[ModelsHandler] GET failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def POST(self):
        _require_auth()
        web.header("Content-Type", "application/json; charset=utf-8")
        try:
            data = json.loads(web.data() or b"{}")
            action = data.get("action") or ""
            if action == "set_provider":
                return self._handle_set_provider(data)
            if action == "delete_provider":
                return self._handle_delete_provider(data)
            if action == "set_custom_provider":
                return self._handle_set_custom_provider(data)
            if action == "delete_custom_provider":
                return self._handle_delete_custom_provider(data)
            if action == "set_active_custom_provider":
                return self._handle_set_active_custom_provider(data)
            if action == "set_capability":
                return self._handle_set_capability(data)
            if action == "save_catalog":
                return self._handle_save_catalog(data)
            if action == "set_voice_reply_mode":
                return self._handle_set_voice_reply_mode(data)
            if action == "set_search_credential":
                return self._handle_set_search_credential(data)
            return json.dumps({"status": "error", "message": f"unknown action: {action!r}"})
        except Exception as e:
            logger.error(f"[ModelsHandler] POST failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def _handle_set_provider(self, data: dict) -> str:
        provider_id = (data.get("provider_id") or "").strip()
        meta = PROVIDER_MODELS.get(provider_id)
        if not meta:
            return json.dumps({"status": "error", "message": f"unknown provider: {provider_id}"})

        # api_key absent / empty / null => leave the existing key untouched
        # (used by the "edit only base url" flow). To clear the key, callers
        # must use action=delete_provider explicitly.
        api_key_raw = data.get("api_key")
        api_key = api_key_raw.strip() if isinstance(api_key_raw, str) else ""

        # api_base presence is significant: an explicit "" means "reset to
        # default", whereas a missing key means "no change".
        api_base_present = "api_base" in data
        api_base = (data.get("api_base") or "").strip() if api_base_present else None

        applied = {}
        local_config = conf()
        file_cfg = self._read_file_config()

        key_field = meta.get("api_key_field")
        if key_field and api_key:
            local_config[key_field] = api_key
            file_cfg[key_field] = api_key
            applied[key_field] = True
        base_field = meta.get("api_base_key")
        if base_field and api_base_present:
            local_config[base_field] = api_base
            file_cfg[base_field] = api_base
            applied[base_field] = True

        if not applied:
            # Nothing actually changed (e.g. user opened the modal and hit
            # save without editing). Treat as a successful no-op so the
            # frontend can show "Saved" instead of surfacing an error.
            return json.dumps({"status": "success", "provider": provider_id, "noop": True})

        self._write_file_config(file_cfg)
        logger.info(f"[ModelsHandler] provider {provider_id} updated: {sorted(applied.keys())}")

        # Vendor credentials affect bot routing for any capability that uses
        # them; safest to reset Bridge so the next request rebuilds bots.
        self._reset_bridge()
        return json.dumps({"status": "success", "provider": provider_id})

    def _handle_delete_provider(self, data: dict) -> str:
        provider_id = (data.get("provider_id") or "").strip()
        meta = PROVIDER_MODELS.get(provider_id)
        if not meta:
            return json.dumps({"status": "error", "message": f"unknown provider: {provider_id}"})

        local_config = conf()
        file_cfg = self._read_file_config()

        cleared = []
        for field_name in (meta.get("api_key_field"), meta.get("api_base_key")):
            if not field_name:
                continue
            # Always write the key — even if it was absent before — so the
            # in-memory conf() reflects the cleared state without needing a
            # restart. (`in local_config` was too strict: provider keys that
            # were ever set then deleted manually wouldn't get reset.)
            local_config[field_name] = ""
            file_cfg[field_name] = ""
            cleared.append(field_name)

        self._write_file_config(file_cfg)
        logger.info(f"[ModelsHandler] provider {provider_id} cleared: {cleared}")
        self._reset_bridge()
        return json.dumps({"status": "success", "provider": provider_id, "cleared": cleared})

    # ------------------------------------------------------------------
    # Multiple custom (OpenAI-compatible) providers
    # ------------------------------------------------------------------
    # These actions manage the ``custom_providers`` list.  Activation is done
    # by setting ``bot_type`` to ``"custom:<id>"``.  There is no separate
    # ``custom_active_provider`` field — a single source of truth.

    @staticmethod
    def _normalize_custom_providers(raw) -> List[dict]:
        """Return a clean list of provider dicts (drops malformed entries)."""
        if not isinstance(raw, list):
            return []
        out = []
        for p in raw:
            if isinstance(p, dict) and (p.get("id") or "").strip():
                out.append(p)
        return out

    def _persist_custom_providers(self, providers: List[dict], bot_type=None) -> None:
        """Write the providers list to both in-memory conf and the on-disk
        config, then reset the bridge so bots rebuild.

        If ``bot_type`` is given, also update ``bot_type``.  When activating a
        provider (bot_type is ``custom:<id>``), also write the provider's
        ``model`` into the global ``model`` field so that all paths (chat,
        agent, vision) automatically use the correct model."""
        from models.custom_provider import parse_custom_bot_type

        local_config = conf()
        file_cfg = self._read_file_config()
        local_config["custom_providers"] = providers
        file_cfg["custom_providers"] = providers
        if bot_type is not None:
            local_config["bot_type"] = bot_type
            file_cfg["bot_type"] = bot_type
            # Sync the provider's model into the global model field.
            _, pid = parse_custom_bot_type(bot_type)
            if pid:
                provider = next((p for p in providers if p.get("id") == pid), None)
                if provider and provider.get("model"):
                    local_config["model"] = provider["model"]
                    file_cfg["model"] = provider["model"]

        skills = local_config.get("skills") or {}
        image_config = (
            skills.get("image-generation")
            if isinstance(skills, dict)
            else {}
        )
        image_provider = (
            image_config.get("provider", "")
            if isinstance(image_config, dict)
            else ""
        )
        if image_provider.startswith("custom:"):
            image_provider_id = image_provider[len("custom:"):]
            if not any(
                provider.get("id") == image_provider_id
                for provider in providers
            ):
                for target in (local_config, file_cfg):
                    self._set_nested_namespace_value(
                        target,
                        "skills",
                        "image-generation",
                        "provider",
                        "",
                    )
                    self._set_nested_namespace_value(
                        target,
                        "skills",
                        "image-generation",
                        "model",
                        "",
                    )
                os.environ.pop(
                    "SKILL_IMAGE_GENERATION_PROVIDER",
                    None,
                )
                os.environ.pop(
                    "SKILL_IMAGE_GENERATION_MODEL",
                    None,
                )
        sync_image_generation_custom_provider_env(
            local_config,
            overwrite=True,
        )
        self._write_file_config(file_cfg)
        self._reset_bridge()

    def _handle_set_custom_provider(self, data: dict) -> str:
        """Add a new custom provider or update an existing one.

        Payload::

            {
              "action": "set_custom_provider",
              "id": "3f2a9c1b",             # required for edit; omit for create
              "name": "my-provider",         # required, display label
              "api_base": "https://...",     # required when creating
              "api_key": "sk-...",           # optional on edit (keep existing)
              "model": "model-name",         # optional default model
              "make_active": true            # optional, also activate it
            }
        """
        from models.custom_provider import generate_provider_id

        name = (data.get("name") or "").strip()
        if not name:
            return json.dumps({"status": "error", "message": "name is required"})

        provider_id = (data.get("id") or "").strip()
        api_base = (data.get("api_base") or "").strip()
        # api_key omitted/empty on edit => keep the existing one.
        api_key_raw = data.get("api_key")
        api_key = api_key_raw.strip() if isinstance(api_key_raw, str) else ""
        model = (data.get("model") or "").strip()
        make_active = bool(data.get("make_active"))

        local_config = conf()
        providers = self._normalize_custom_providers(local_config.get("custom_providers"))

        existing = next((p for p in providers if p.get("id") == provider_id), None) if provider_id else None
        if existing is None:
            # Creating a new provider — api_base is mandatory.
            if not api_base:
                return json.dumps({"status": "error", "message": "api_base is required"})
            provider_id = generate_provider_id()
            entry = {"id": provider_id, "name": name, "api_key": api_key, "api_base": api_base}
            if model:
                entry["model"] = model
            providers.append(entry)
            created = True
        else:
            existing["name"] = name
            if api_base:
                existing["api_base"] = api_base
            # The API key is optional for custom providers. Distinguish "field
            # omitted => keep existing" from "explicit empty => clear it" by
            # presence of the key, mirroring the model handling below. A masked,
            # untouched value is omitted by the UI, so it never reaches here.
            if "api_key" in data:
                if api_key:
                    existing["api_key"] = api_key
                else:
                    existing.pop("api_key", None)
            # Only touch model when explicitly provided in the payload; an
            # explicit empty string clears it, a missing key keeps it (the
            # UI modal no longer sends model, so manual config survives edits).
            if "model" in data:
                if model:
                    existing["model"] = model
                else:
                    existing.pop("model", None)
            created = False

        # Decide bot_type — only switch when explicitly requested.
        new_bot_type = None
        if make_active:
            new_bot_type = f"custom:{provider_id}"

        self._persist_custom_providers(providers, new_bot_type)
        logger.info(
            f"[ModelsHandler] custom provider {name!r} (id={provider_id}) "
            f"{'created' if created else 'updated'}"
        )
        return json.dumps({
            "status": "success",
            "id": provider_id,
            "name": name,
            "created": created,
        })

    def _handle_delete_custom_provider(self, data: dict) -> str:
        """Remove a custom provider by id."""
        from models.custom_provider import parse_custom_bot_type

        provider_id = (data.get("id") or "").strip()
        if not provider_id:
            return json.dumps({"status": "error", "message": "id is required"})

        local_config = conf()
        providers = self._normalize_custom_providers(local_config.get("custom_providers"))
        remaining = [p for p in providers if p.get("id") != provider_id]
        if len(remaining) == len(providers):
            return json.dumps({"status": "error", "message": f"unknown custom provider id: {provider_id}"})

        # If the deleted provider was active, fall back to the first remaining.
        _, current_active_id = parse_custom_bot_type(local_config.get("bot_type") or "")
        new_bot_type = None
        if current_active_id == provider_id:
            if remaining:
                new_bot_type = f"custom:{remaining[0]['id']}"
            else:
                new_bot_type = "custom"  # revert to legacy

        self._persist_custom_providers(remaining, new_bot_type)
        model_catalog.remove_catalog(f"custom:{provider_id}")
        logger.info(f"[ModelsHandler] custom provider id={provider_id} deleted")
        return json.dumps({"status": "success", "id": provider_id})

    def _handle_set_active_custom_provider(self, data: dict) -> str:
        """Activate a custom provider by setting bot_type to 'custom:<id>'."""
        provider_id = (data.get("id") or "").strip()
        if not provider_id:
            return json.dumps({"status": "error", "message": "id is required"})

        local_config = conf()
        providers = self._normalize_custom_providers(local_config.get("custom_providers"))
        if not any(p.get("id") == provider_id for p in providers):
            return json.dumps({"status": "error", "message": f"unknown custom provider id: {provider_id}"})

        new_bot_type = f"custom:{provider_id}"
        self._persist_custom_providers(providers, new_bot_type)
        logger.info(f"[ModelsHandler] active custom provider set to id={provider_id}")
        return json.dumps({"status": "success", "active_id": provider_id})

    def _handle_save_catalog(self, data: dict) -> str:
        """Replace one provider's model catalog wholesale (empty list -> back
        to presets). Metadata-only: no bridge reset needed, the budget and
        max_output_tokens resolution read the catalog per call."""
        provider_id = (data.get("provider_id") or "").strip()
        if not provider_id:
            return json.dumps({"status": "error", "message": "provider_id is required"})
        if provider_id not in PROVIDER_MODELS and not provider_id.startswith("custom:"):
            return json.dumps({"status": "error", "message": f"unknown provider: {provider_id}"})
        try:
            entries = model_catalog.save_catalog(
                provider_id, data.get("models"), data.get("hidden"))
        except ValueError as e:
            return json.dumps({"status": "error", "message": str(e)})
        logger.info(f"[ModelsHandler] catalog saved: provider={provider_id} models={len(entries)}")
        return json.dumps({"status": "success", "provider_id": provider_id, "models": entries})

    def _handle_set_capability(self, data: dict) -> str:
        capability = (data.get("capability") or "").strip()
        provider_id = (data.get("provider_id") or "").strip()
        model = (data.get("model") or "").strip()

        if capability == "chat":
            return self._set_chat(provider_id, model)
        if capability == "chat_fallback":
            return self._set_chat_fallback(
                provider_id,
                model,
                bool(data.get("enabled")),
                chain=data.get("chain"),
            )
        if capability == "vision":
            return self._set_vision(provider_id, model)
        if capability == "asr":
            return self._set_asr(provider_id, model)
        if capability == "tts":
            return self._set_tts(provider_id, model, (data.get("voice") or "").strip())
        if capability == "embedding":
            return self._set_embedding(provider_id, model)
        if capability == "image":
            return self._set_image(provider_id, model)
        if capability == "search":
            return self._set_search(
                (data.get("strategy") or "").strip().lower(),
                (data.get("provider") or "").strip().lower(),
            )
        return json.dumps({"status": "error", "message": f"capability not editable: {capability}"})

    def _set_image(self, provider_id: str, model: str) -> str:
        # Source of truth: skills.image-generation.{provider, model}. The
        # provider field is persisted so users picking a custom model under
        # a specific vendor still get routed there — runtime falls back to
        # model-name prefix inference only when provider is empty.
        local_config = conf()
        if provider_id.startswith("custom:"):
            custom_id = provider_id[len("custom:"):]
            providers = self._normalize_custom_providers(
                local_config.get("custom_providers")
            )
            custom_provider = next(
                (
                    provider
                    for provider in providers
                    if provider.get("id") == custom_id
                ),
                None,
            )
            if custom_provider is None:
                return json.dumps({
                    "status": "error",
                    "message": (
                        "unknown custom provider id: {}".format(custom_id)
                    ),
                })
            if not model:
                model = custom_provider.get("model") or ""
        elif (
            provider_id
            and provider_id not in self._IMAGE_PROVIDER_MODELS
        ):
            return json.dumps({
                "status": "error",
                "message": "unknown image provider: {}".format(provider_id),
            })

        if provider_id and not model:
            return json.dumps({
                "status": "error",
                "message": (
                    "image model is required when a provider is selected"
                ),
            })

        file_cfg = self._read_file_config()

        self._set_nested_namespace_value(local_config, "skills", "image-generation", "model", model or "")
        self._set_nested_namespace_value(file_cfg, "skills", "image-generation", "model", model or "")
        self._set_nested_namespace_value(local_config, "skills", "image-generation", "provider", provider_id or "")
        self._set_nested_namespace_value(file_cfg, "skills", "image-generation", "provider", provider_id or "")
        self._drop_legacy_namespace(local_config, "skill", "skills", child="image-generation")
        self._drop_legacy_namespace(file_cfg, "skill", "skills", child="image-generation")

        self._write_file_config(file_cfg)

        # The skill subprocess reads SKILL_IMAGE_GENERATION_{MODEL,PROVIDER}
        # from env at startup; mirror the change so live edits apply without
        # restart.
        model_env = "SKILL_IMAGE_GENERATION_MODEL"
        provider_env = "SKILL_IMAGE_GENERATION_PROVIDER"
        if model:
            os.environ[model_env] = model
        else:
            os.environ.pop(model_env, None)
        if provider_id:
            os.environ[provider_env] = provider_id
        else:
            os.environ.pop(provider_env, None)
        sync_image_generation_custom_provider_env(
            local_config,
            overwrite=True,
        )

        logger.info(f"[ModelsHandler] image updated: provider={provider_id!r} model={model!r}")
        return json.dumps({
            "status": "success",
            "provider": provider_id,
            "model": model,
        })

    def _set_chat(self, provider_id: str, model: str) -> str:
        # Accept expanded custom provider ids ("custom:<id>") as well as the
        # built-in vendors, so the chat capability card and the custom
        # providers section behave consistently.
        custom_provider = None
        if provider_id.startswith("custom:"):
            from models.custom_provider import parse_custom_bot_type
            _, custom_id = parse_custom_bot_type(provider_id)
            providers = self._normalize_custom_providers(conf().get("custom_providers"))
            custom_provider = next((p for p in providers if p.get("id") == custom_id), None)
            if custom_provider is None:
                return json.dumps({"status": "error", "message": f"unknown custom provider id: {custom_id}"})
        elif provider_id and provider_id not in PROVIDER_MODELS:
            return json.dumps({"status": "error", "message": f"unknown provider: {provider_id}"})

        applied = {}
        local_config = conf()
        file_cfg = self._read_file_config()

        # Fall back to the custom provider's default model when none is given.
        if not model and custom_provider:
            model = custom_provider.get("model") or ""

        if provider_id:
            bot_type_value = "chatGPT" if provider_id == "openai" else provider_id
            local_config["bot_type"] = bot_type_value
            file_cfg["bot_type"] = bot_type_value
            applied["bot_type"] = bot_type_value
            use_linkai = (provider_id == "linkai")
            local_config["use_linkai"] = use_linkai
            file_cfg["use_linkai"] = use_linkai
            applied["use_linkai"] = use_linkai
        if model:
            local_config["model"] = model
            file_cfg["model"] = model
            applied["model"] = model

        if not applied:
            return json.dumps({"status": "success", "applied": {}, "noop": True})

        self._write_file_config(file_cfg)
        logger.info(f"[ModelsHandler] chat updated: {applied}")
        self._reset_bridge()
        return json.dumps({"status": "success", "applied": applied})

    def _normalized_custom_provider(self, provider_id: str):
        """Resolve a ``custom:<id>`` provider id, or None for a builtin one.

        Returns ``(provider_entry, error_json)``; exactly one is set. Kept
        separate so a chain can reuse it per link instead of duplicating the
        lookup.
        """
        if not provider_id:
            return None, None
        if provider_id.startswith("custom:"):
            from models.custom_provider import parse_custom_bot_type
            _, custom_id = parse_custom_bot_type(provider_id)
            providers = self._normalize_custom_providers(conf().get("custom_providers"))
            custom_provider = next((p for p in providers if p.get("id") == custom_id), None)
            if custom_provider is None:
                return None, json.dumps({"status": "error",
                                         "message": f"unknown custom provider id: {custom_id}"})
            return custom_provider, None
        if provider_id not in PROVIDER_MODELS:
            return None, json.dumps({"status": "error",
                                     "message": f"unknown provider: {provider_id}"})
        return None, None

    def _set_chat_fallback(self, provider_id: str, model: str, enabled: bool,
                           chain=None) -> str:
        """Persist the fallback chain under ``chat_fallback``.

        ``chain`` is an ordered list of ``{"provider", "model"}`` links, tried
        front to back after the primary model fails a turn for good. It is
        unbounded: however many links are saved is how many backups a turn
        gets, so there is no cap to configure.

        For callers still sending the single-model shape (``provider_id`` /
        ``model``), the pair is folded into a one-link chain, so an older
        client keeps working against the new config.

        Validation mirrors ``_set_chat`` (custom:<id> ids included), with two
        differences: the chain is opt-in via ``enabled``, and turning it on
        requires at least one fully specified link so a half-configured
        fallback can never hijack a healthy primary model. Individual links
        that are incomplete or repeat the primary model are dropped rather
        than rejected — one bad row should not block saving the good ones.
        """
        links = []
        if chain is not None:
            if not isinstance(chain, list):
                return json.dumps({"status": "error", "message": "chain must be a list"})
            raw_links = chain
        else:
            raw_links = [{"provider": provider_id or "", "model": model or ""}]

        for item in raw_links:
            if not isinstance(item, dict):
                continue
            link_provider = (item.get("provider") or "").strip()
            link_model = (item.get("model") or "").strip()
            if not link_provider and not link_model:
                continue  # an empty row the user never filled in
            custom_provider, err = self._normalized_custom_provider(link_provider)
            if err:
                return err
            # Fall back to the custom provider's default model when none given.
            if not link_model and custom_provider:
                link_model = custom_provider.get("model") or ""
            if not link_provider or not link_model:
                continue  # half a link routes nowhere
            links.append({"provider": link_provider, "model": link_model})

        # Enabling needs at least one usable link; disabling is always allowed
        # (it is the safe direction, and lets a user clear a broken entry).
        if enabled and not links:
            return json.dumps({
                "status": "error",
                "message": "at least one provider/model pair is required to enable the fallback",
            })

        local_config = conf()
        file_cfg = self._read_file_config()
        payload = {
            "enabled": bool(enabled),
            "chain": links,
        }
        # Written as a whole so a stale key from an older shape can't survive.
        local_config["chat_fallback"] = dict(payload)
        file_cfg["chat_fallback"] = dict(payload)
        self._write_file_config(file_cfg)

        # Turning the fallback off must take effect now, not on the next run
        # boundary. A model that had already switched to the backup keeps its
        # engaged fallback state on the long-lived AgentLLMModel, so clear it
        # across all live agents — otherwise disabling the fallback appears to
        # do nothing and the backup model keeps answering.
        if not enabled:
            try:
                from bridge.bridge import Bridge
                Bridge().get_agent_bridge().clear_all_model_fallbacks()
            except Exception as clear_err:
                logger.warning(
                    f"[ModelsHandler] failed to clear engaged fallbacks: {clear_err}"
                )

        logger.info(f"[ModelsHandler] chat fallback updated: {payload}")
        return json.dumps({"status": "success", "applied": payload})

    def _set_vision(self, provider_id: str, model: str) -> str:
        # Source of truth: tools.vision.{provider, model}. The provider field
        # is persisted so users picking a custom model under a specific vendor
        # still get routed there — runtime falls back to model-name prefix
        # inference only when provider is empty.
        # Validate provider_id — mirrors _set_chat / _set_embedding pattern.
        if provider_id.startswith("custom:"):
            from models.custom_provider import parse_custom_bot_type
            _, custom_id = parse_custom_bot_type(provider_id)
            providers = self._normalize_custom_providers(conf().get("custom_providers"))
            custom_provider = next((p for p in providers if p.get("id") == custom_id), None)
            if custom_provider is None:
                return json.dumps({"status": "error", "message": f"unknown custom provider id: {custom_id}"})
            if not model:
                model = custom_provider.get("model") or ""
        elif provider_id and provider_id not in {k for k in ModelsHandler._VISION_PROVIDER_MODELS if k != "custom"}:
            return json.dumps({"status": "error", "message": f"unknown provider: {provider_id}"})

        if provider_id and not model:
            return json.dumps({
                "status": "error",
                "message": "vision model is required when a provider is selected",
            })

        local_config = conf()
        file_cfg = self._read_file_config()
        self._set_nested_namespace_value(file_cfg, "tools", "vision", "model", model)
        self._set_nested_namespace_value(local_config, "tools", "vision", "model", model)
        self._set_nested_namespace_value(file_cfg, "tools", "vision", "provider", provider_id or "")
        self._set_nested_namespace_value(local_config, "tools", "vision", "provider", provider_id or "")
        self._drop_legacy_namespace(file_cfg, "tool", "tools", child="vision")
        self._drop_legacy_namespace(local_config, "tool", "tools", child="vision")

        self._write_file_config(file_cfg)
        logger.info(f"[ModelsHandler] vision updated: provider={provider_id!r} model={model!r}")
        return json.dumps({"status": "success", "provider": provider_id, "model": model})

    @staticmethod
    def _set_nested_namespace_value(cfg, top: str, name: str, key: str, value):
        """Set ``cfg[top][name][key] = value``, creating missing dicts."""
        bucket = cfg.get(top)
        if not isinstance(bucket, dict):
            bucket = {}
        node = bucket.get(name)
        if not isinstance(node, dict):
            node = {}
        node[key] = value
        bucket[name] = node
        cfg[top] = bucket

    @staticmethod
    def _drop_legacy_namespace(cfg, legacy: str, canonical: str, child: str) -> None:
        """Strip the deprecated singular key so config.json stays single-source."""
        legacy_section = cfg.get(legacy)
        if not isinstance(legacy_section, dict):
            return
        legacy_section.pop(child, None)
        if legacy_section:
            cfg[legacy] = legacy_section
        else:
            cfg.pop(legacy, None)

    def _handle_set_voice_reply_mode(self, data: dict) -> str:
        # UI picker (off / voice_if_voice / always) maps to the legacy
        # always_reply_voice + voice_reply_voice pair that chat_channel.py
        # reads, so all channels (web/feishu/wecom/...) share the routing.
        mode = (data.get("mode") or "").strip().lower()
        if mode not in ("off", "voice_if_voice", "always"):
            return json.dumps({"status": "error", "message": f"invalid mode: {mode!r}"})
        always = (mode == "always")
        if_voice = (mode == "voice_if_voice")
        local_config = conf()
        file_cfg = self._read_file_config()
        local_config["always_reply_voice"] = always
        local_config["voice_reply_voice"] = if_voice
        file_cfg["always_reply_voice"] = always
        file_cfg["voice_reply_voice"] = if_voice
        self._write_file_config(file_cfg)
        logger.info(
            f"[ModelsHandler] voice reply mode set: {mode!r} "
            f"(always_reply_voice={always}, voice_reply_voice={if_voice})"
        )
        return json.dumps({"status": "success", "mode": mode})

    def _set_simple(self, key: str, value: str) -> str:
        local_config = conf()
        file_cfg = self._read_file_config()
        local_config[key] = value
        file_cfg[key] = value
        self._write_file_config(file_cfg)
        logger.info(f"[ModelsHandler] {key} set: {value!r}")
        # Hot-swap the cached voice bot so the change takes effect immediately.
        if key in ("voice_to_text", "text_to_voice"):
            self._refresh_voice_routing()
        return json.dumps({"status": "success", key: value})

    def _set_asr(self, provider_id: str, model: str) -> str:
        local_config = conf()
        file_cfg = self._read_file_config()
        local_config["voice_to_text"] = provider_id
        file_cfg["voice_to_text"] = provider_id
        # Normally an empty model means "keep whatever is configured" so
        # switching provider from the console never wipes a user's hand-set
        # voice_to_text_model (runtime falls back to the engine default via
        # `or DEFAULT_ASR_MODEL` regardless). The exception is a provider that
        # exposes an explicit empty-value option (e.g. LinkAI's "默认 · 由网关
        # 自动选择引擎"): picking it is a deliberate "use the gateway default",
        # so clear the stored model instead of silently keeping the old one.
        offers_default = any(
            (m if isinstance(m, str) else m.get("value", "")) == ""
            for m in (self._ASR_PROVIDER_MODELS.get(provider_id) or [])
        )
        if model:
            local_config["voice_to_text_model"] = model
            file_cfg["voice_to_text_model"] = model
        elif offers_default:
            local_config["voice_to_text_model"] = ""
            file_cfg["voice_to_text_model"] = ""
        self._write_file_config(file_cfg)
        logger.info(
            f"[ModelsHandler] asr updated: provider={provider_id!r} "
            f"model={model!r}"
        )
        self._refresh_voice_routing()
        return json.dumps({
            "status": "success",
            "provider": provider_id,
            "model": local_config.get("voice_to_text_model", ""),
        })

    def _set_tts(self, provider_id: str, model: str, voice: str = "") -> str:
        local_config = conf()
        file_cfg = self._read_file_config()
        local_config["text_to_voice"] = provider_id
        file_cfg["text_to_voice"] = provider_id
        local_config["text_to_voice_model"] = model
        file_cfg["text_to_voice_model"] = model
        local_config["tts_voice_id"] = voice
        file_cfg["tts_voice_id"] = voice
        self._write_file_config(file_cfg)
        logger.info(
            f"[ModelsHandler] tts updated: provider={provider_id!r} "
            f"model={model!r} voice={voice!r}"
        )
        self._refresh_voice_routing()
        return json.dumps({
            "status": "success",
            "provider": provider_id, "model": model, "voice": voice,
        })

    @staticmethod
    def _refresh_voice_routing() -> None:
        try:
            from bridge.bridge import Bridge
            Bridge().refresh_voice()
        except Exception as e:
            logger.warning(f"[ModelsHandler] Bridge voice refresh failed: {e}")

    def _set_embedding(self, provider_id: str, model: str) -> str:
        # Validate provider_id — mirrors _set_chat's validation pattern.
        if provider_id.startswith("custom:"):
            from models.custom_provider import parse_custom_bot_type
            _, custom_id = parse_custom_bot_type(provider_id)
            providers = self._normalize_custom_providers(conf().get("custom_providers"))
            custom_provider = next((p for p in providers if p.get("id") == custom_id), None)
            if custom_provider is None:
                return json.dumps({"status": "error", "message": f"unknown custom provider id: {custom_id}"})
            # Fall back to the custom provider's default model when none is given.
            if not model:
                model = custom_provider.get("model") or ""
        elif provider_id and provider_id not in {p for p in ModelsHandler._EMBEDDING_PROVIDERS if p != "custom"}:
            return json.dumps({"status": "error", "message": f"unknown provider: {provider_id}"})

        # A provider without a model leaves the runtime in a broken half-state,
        # so reject that explicitly instead of silently writing it through.
        if provider_id and not model:
            return json.dumps({
                "status": "error",
                "message": "embedding model is required when a provider is selected",
            })
        local_config = conf()
        file_cfg = self._read_file_config()
        local_config["embedding_provider"] = provider_id
        file_cfg["embedding_provider"] = provider_id
        local_config["embedding_model"] = model
        file_cfg["embedding_model"] = model
        self._write_file_config(file_cfg)
        logger.info(f"[ModelsHandler] embedding updated: provider={provider_id!r} model={model!r}")
        # The next /memory rebuild-index command hot-swaps the provider onto
        # the running MemoryManager (see plugins/cow_cli). The dim may have
        # changed, so the frontend prompts the user to rebuild.
        return json.dumps({"status": "success", "provider": provider_id, "model": model})

    def _set_search(self, strategy: str, provider: str) -> str:
        """Persist search routing under tools.web_search.{strategy,provider}.

        strategy 'auto'  -> provider field is cleared (auto picks at call time)
        strategy 'fixed' -> provider must be in the canonical list; runtime
                            silently falls back to auto if its key is missing.
        """
        if strategy not in ("auto", "fixed"):
            return json.dumps({"status": "error", "message": f"invalid strategy: {strategy!r}"})
        if strategy == "fixed":
            if provider not in self._SEARCH_PROVIDERS:
                return json.dumps({"status": "error", "message": f"unknown provider: {provider!r}"})
        else:
            provider = ""

        local_config = conf()
        file_cfg = self._read_file_config()
        self._set_nested_namespace_value(local_config, "tools", "web_search", "strategy", strategy)
        self._set_nested_namespace_value(file_cfg,     "tools", "web_search", "strategy", strategy)
        self._set_nested_namespace_value(local_config, "tools", "web_search", "provider", provider)
        self._set_nested_namespace_value(file_cfg,     "tools", "web_search", "provider", provider)
        self._write_file_config(file_cfg)
        logger.info(f"[ModelsHandler] search updated: strategy={strategy!r} provider={provider!r}")
        return json.dumps({"status": "success", "strategy": strategy, "provider": provider})

    def _handle_set_search_credential(self, data: dict) -> str:
        """Persist a dedicated search-provider key under tools.web_search.

        bocha, anysearch, serply and keenable own their keys here; anysearch
        and keenable also take an ``anonymous`` flag that, with an empty key,
        turns on their keyless tier (``<provider>_anonymous``). zhipu/qianfan/
        linkai reuse model-vendor credentials and go through set_provider
        instead.
        """
        provider = (data.get("provider") or "bocha").strip().lower()
        if provider not in ("bocha", "anysearch", "serply", "tavily", "searxng", "keenable"):
            return json.dumps({"status": "error", "message": f"unsupported search provider: {provider!r}"})

        if provider in ("anysearch", "keenable"):
            anonymous = data.get("anonymous", False)

            api_key = (data.get("api_key") or "").strip() if isinstance(data.get("api_key"), str) else ""
            key_field = f"{provider}_api_key"
            anonymous_field = f"{provider}_anonymous"
            anonymous_on = bool(anonymous and not api_key)

            local_config = conf()
            file_cfg = self._read_file_config()

            self._set_nested_namespace_value(local_config, "tools", "web_search", key_field, api_key)
            self._set_nested_namespace_value(file_cfg, "tools", "web_search", key_field, api_key)

            self._set_nested_namespace_value(local_config, "tools", "web_search", anonymous_field, anonymous_on)
            self._set_nested_namespace_value(file_cfg, "tools", "web_search", anonymous_field, anonymous_on)

            self._write_file_config(file_cfg)
            logger.info(
                f"[ModelsHandler] search credential set: {key_field}={'***' if api_key else ''}, {anonymous_field}={anonymous_on}")
            return json.dumps({"status": "success", "provider": provider})
        if provider == "searxng":
            # SearXNG uses an instance URL, not an API key.
            instance_url = (data.get("url") or "").strip() if isinstance(data.get("url"), str) else ""
            local_config = conf()
            file_cfg = self._read_file_config()
            self._set_nested_namespace_value(local_config, "tools", "web_search", "searxng_url", instance_url)
            self._set_nested_namespace_value(file_cfg, "tools", "web_search", "searxng_url", instance_url)
            self._write_file_config(file_cfg)
            logger.info(f"[ModelsHandler] search credential set: searxng_url={'***' if instance_url else ''}")
            return json.dumps({"status": "success", "provider": provider})
        else:
            key_field = f"{provider}_api_key"
            api_key = (data.get("api_key") or "").strip() if isinstance(data.get("api_key"), str) else ""
            local_config = conf()
            file_cfg = self._read_file_config()
            self._set_nested_namespace_value(local_config, "tools", "web_search", key_field, api_key)
            self._set_nested_namespace_value(file_cfg, "tools", "web_search", key_field, api_key)
            self._write_file_config(file_cfg)
            logger.info(f"[ModelsHandler] search credential set: {key_field}={'***' if api_key else ''}")
            return json.dumps({"status": "success", "provider": provider})

    @staticmethod
    def _reset_bridge() -> None:
        try:
            from bridge.bridge import Bridge
            Bridge().reset_bot()
            logger.info("[ModelsHandler] Bridge bot routing reset")
        except Exception as e:
            logger.warning(f"[ModelsHandler] Bridge reset failed: {e}")
