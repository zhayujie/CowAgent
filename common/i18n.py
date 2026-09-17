# encoding:utf-8

"""Lightweight global language detection and resolution.

This module is the single source of truth for the runtime UI language used
across the CLI, startup logs, error messages, agent prompts and channel
replies. It must NOT import project config (to avoid circular imports) and
must stay dependency-free so it can run at the earliest startup phase.

Supported language codes (BCP 47 compliant):
  - "zh" (Simplified Chinese)
  - "zh-Hant" (Traditional Chinese, script-based tag per Unicode CLDR)
  - "en" (English)

Resolution priority (highest first):
  1. Explicit `cow_lang` from config.json — also covers Docker/CI, since any
     config key is overridable via its uppercase env var (e.g. COW_LANG=zh),
     handled by config.load_config() before resolution. COW_LANG is a private
     name to avoid clashing with the gettext-standard LANGUAGE variable.
  2. macOS `defaults read -g AppleLocale` (system-level preference; a Chinese
     system locale is a strong signal that beats a shell-default LANG)
  3. Standard locale env vars: LC_ALL > LC_MESSAGES > LANG
  4. Python locale module
  5. Default -> English

A value of "auto" (the default) triggers detection (steps 2-5). Explicitly
setting "zh", "zh-Hant", or "en" locks the language and skips detection.

Note: For backwards compatibility, zh-tw, zh-hk, and other regional variants
are automatically normalized to zh-Hant during detection.
"""

import os
import subprocess
import sys

# Supported language codes
ZH = "zh"
ZH_HANT = "zh-Hant"
EN = "en"
SUPPORTED = (ZH, ZH_HANT, EN)
DEFAULT_LANG = EN

# Mapped Simplified to Traditional characters in this codebase
_SIMPLIFIED = "与专业东丢两严个丰临为举么义乐乔习书乱于云产亲仅从仓们价众优伙会伟传体余侧倾储儿关兴兽内册写冲决况准减几凭凯击划则刚创删别剥办务动区华协单占厂历压参双发变叙台号后吗听启员响嚣团国图场坏块声处备复够头夹妩姗娇娱婶学宝实宠审宽对导将尝尽层属币师带帧帮幂干并广庆库应开异弃张弹强归当录彦彻征径忆态总悦惯戏战户执扩扫抛抢护报拟拥拦择换据数断无旧时昵显晓暂术机杂权条来杰极构枪标树样档桦梦检欢残毕气汇汉汤没泄泼洁测浏润涩淀渊温游湾湿滞满滤灵灿炀点炼烦热爱爷状独猪环现瑶电画监盖盘着睁码础确离种积称稳竞笔签简类粤紧纠红约级纪纯纳线组细织终绍经结绘给络绝统继绪续维综缀缓编缩网罗羁职联聪脑脚脱腾舰艺节苍苏范荐获萝蔼虑补装见观规视览觉触计订认讨让训议讯记讲许论设访证识诉诊词译试诚话询该详语误说请读谁调谢谨谱贝负责贤败账货质费资赋赖赘轩转轮软轻载较辑输边达过运还这进远违连迟适选递逻遥邮邻采释里鉴针钉钟钥钮钱铁链销锁错锤键镜长闭问闲间闺闻闽阅队阳际陆陕险随隐难静韩页项顺须顾预领频题额风飞饭饰馆馈馏马驻驿验骤鱼鸡麦齐"
_TRADITIONAL = "與專業東丟兩嚴個豐臨為舉麼義樂喬習書亂於雲產親僅從倉們價眾優夥會偉傳體餘側傾儲兒關興獸內冊寫沖決況準減幾憑凱擊劃則剛創刪別剝辦務動區華協單佔廠歷壓參雙發變敘臺號後嗎聽啟員響囂團國圖場壞塊聲處備復夠頭夾嫵姍嬌娛嬸學寶實寵審寬對導將嘗盡層屬幣師帶幀幫冪幹並廣慶庫應開異棄張彈強歸當錄彥徹徵徑憶態總悅慣戲戰戶執擴掃拋搶護報擬擁攔擇換據數斷無舊時暱顯曉暫術機雜權條來傑極構槍標樹樣檔樺夢檢歡殘畢氣匯漢湯沒洩潑潔測瀏潤澀澱淵溫遊灣溼滯滿濾靈燦煬點煉煩熱愛爺狀獨豬環現瑤電畫監蓋盤著睜碼礎確離種積稱穩競筆籤簡類粵緊糾紅約級紀純納線組細織終紹經結繪給絡絕統繼緒續維綜綴緩編縮網羅羈職聯聰腦腳脫騰艦藝節蒼蘇範薦獲蘿藹慮補裝見觀規視覽覺觸計訂認討讓訓議訊記講許論設訪證識訴診詞譯試誠話詢該詳語誤說請讀誰調謝謹譜貝負責賢敗帳貨質費資檔案影片圖片連結資料資訊支援排程執行帳號密碼憑證埠服務啟用管道終端機控制台"
_CHAR_MAP = None

_PHRASE_MAP = {
    "默认": "預設",
    "内存": "記憶體",
    "配置": "設定",
    "进程": "處理程序",
    "目录": "目錄",
    "文件夹": "資料夾",
    "文件": "檔案",
    "视频": "影片",
    "图片": "圖片",
    "影象": "影像",
    "图像": "影像",
    "链接": "連結",
    "数据": "資料",
    "信息": "資訊",
    "支持": "支援",
    "定时": "排程",
    "运行": "執行",
    "账号": "帳號",
    "密码": "密碼",
    "凭据": "憑證",
    "端口": "埠",
    "服务": "服務",
    "激活": "啟用",
    "通道": "管道",
    "终端": "終端機",
    "主控台": "控制台",
    "创建": "建立",
    "计算机": "電腦",
}


def to_traditional(text):
    """Convert Simplified Chinese text to Traditional Chinese.

    Uses a two-tier approach:
    1. Phrase-level mapping for project-specific terms (e.g., "配置" → "設定")
    2. OpenCC library (opencc-python-reimplemented) if available for high-quality
       context-aware conversion, with fallback to built-in character mapping

    This function is designed to work without external dependencies. If OpenCC
    is not installed, it falls back to a curated 450-character mapping table
    plus 30+ technical term mappings that cover common project vocabulary.

    For production use with zh-Hant language, installing OpenCC is recommended:
        pip install opencc-python-reimplemented
    """
    if not text:
        return text

    # Replace phrases first
    for s, t_phrase in _PHRASE_MAP.items():
        text = text.replace(s, t_phrase)

    try:
        from opencc import OpenCC
        cc = OpenCC('s2twp')
        return cc.convert(text)
    except Exception:
        pass

    global _CHAR_MAP
    if _CHAR_MAP is None:
        _CHAR_MAP = dict(zip(_SIMPLIFIED, _TRADITIONAL))

    # Replace characters
    return "".join(_CHAR_MAP.get(c, c) for c in text)


# Resolved language cache; None until first resolution.
_resolved_lang = None


def _normalize(raw):
    """Map an arbitrary locale-ish string to a supported code, or None.

    Only Chinese is detected explicitly; everything else (including unknown
    or empty values) yields None so the caller can fall through to the next
    detection source.
    """
    if not raw:
        return None
    value = str(raw).strip().lower().replace("_", "-")
    if value in ("auto", ""):
        return None
    # Traditional Chinese variants: zh-tw, zh-hk, zh-hant, zh-hant-tw, zh-hant-hk...
    if value.startswith("zh-tw") or value.startswith("zh-hk") or "hant" in value:
        return ZH_HANT
    # General or Simplified Chinese variants: zh, zh-cn, zh-hans...
    if value.startswith("zh") or value.startswith("chinese"):
        return ZH
    if value.startswith("en") or value.startswith("english"):
        return EN
    return None


def _detect_from_env():
    """Detect language from standard locale environment variables.

    Note: on macOS, `LANG` is often a shell default (e.g. en_US.UTF-8 set by
    .zshrc) that does not reflect the user's real preference, so AppleLocale
    is checked first (see detect_language). On Linux these vars are the
    primary signal.

    The cow_lang env override (COW_LANG=zh) is intentionally NOT read here:
    it sets config["cow_lang"] and is handled via the explicit config path,
    not auto-detection.
    """
    for key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        lang = _normalize(os.environ.get(key))
        if lang:
            return lang
    return None


def _detect_from_macos():
    """macOS fallback: read the system-wide AppleLocale preference.

    On macOS the terminal often does NOT export LANG, yet the system locale
    is still meaningful (e.g. a Chinese Mac reports zh_CN). This recovers
    that signal so Chinese users are not misdetected as English.
    """
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(
            ["defaults", "read", "-g", "AppleLocale"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0:
            return _normalize(out.stdout)
    except Exception:
        pass
    return None


def _detect_from_python_locale():
    """Last-resort detection via Python's locale module."""
    try:
        import locale

        for value in locale.getlocale():
            lang = _normalize(value)
            if lang:
                return lang
    except Exception:
        pass
    return None


def detect_language():
    """Run full auto-detection and return a supported language code.

    Order (auto-detection only; explicit config["cow_lang"] is resolved
    before this is reached):
      1. macOS AppleLocale (system-level preference; a Chinese system locale
         is a strong, low-false-positive signal that beats a shell-default
         LANG like en_US.UTF-8)
      2. locale env vars LC_ALL / LC_MESSAGES / LANG (primary signal on Linux)
      3. Python locale module
      4. default English
    """
    if os.environ.get("CLOUD_DEPLOYMENT_ID"):
        return ZH
    return (
        _detect_from_macos()
        or _detect_from_env()
        or _detect_from_python_locale()
        or DEFAULT_LANG
    )


def resolve_language(configured=None):
    """Resolve the effective language from a configured value.

    `configured` is the raw `cow_lang` value from config.json (may be None,
    "auto", "zh" or "en"). An explicit "zh"/"en" locks the result; "auto"
    or empty triggers detection. The result is cached globally.
    """
    global _resolved_lang
    explicit = _normalize(configured)
    if explicit:
        _resolved_lang = explicit
    else:
        _resolved_lang = detect_language()
    return _resolved_lang


def set_language(lang):
    """Force the resolved language (used by tests or per-request overrides)."""
    global _resolved_lang
    normalized = _normalize(lang)
    _resolved_lang = normalized or DEFAULT_LANG
    return _resolved_lang


def get_language():
    """Return the currently resolved language, detecting lazily if needed."""
    global _resolved_lang
    if _resolved_lang is None:
        _resolved_lang = detect_language()
    return _resolved_lang


def is_zh():
    return get_language() in (ZH, ZH_HANT)


def t(zh_text, en_text):
    """Pick a string by the current language. Tiny inline-translation helper.

    Intended for one-off strings where a full message catalog is overkill:
        t("已中止", "Cancelled")
    """
    lang = get_language()
    if lang == ZH_HANT:
        return to_traditional(zh_text)
    return zh_text if lang == ZH else en_text
