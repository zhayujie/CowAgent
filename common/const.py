# 厂商类型
OPEN_AI = "openAI"
OPENAI = "openai"
CHATGPT = "chatGPT"  # legacy alias for OPENAI, kept for backward compatibility
BAIDU = "baidu"
QIANFAN = "qianfan"
XUNFEI = "xunfei"
CHATGPTONAZURE = "chatGPTOnAzure"
LINKAI = "linkai"
CLAUDEAPI= "claudeAPI"
QWEN = "qwen"  # 千问 (兼容旧配置，实际走 DashscopeBot)
QWEN_DASHSCOPE = "dashscope"  # 千问 DashScope 接入
GEMINI = "gemini" 
ZHIPU_AI = "zhipu"  
MOONSHOT = "moonshot"
MiniMax = "minimax"
DEEPSEEK = "deepseek"
CUSTOM = "custom"  # custom OpenAI-compatible API, bot_type won't auto-switch on model change
MODELSCOPE = "modelscope"

# 模型列表
# Claude (Anthropic)
CLAUDE3 = "claude-3-opus-20240229"
CLAUDE_3_OPUS = "claude-3-opus-latest"
CLAUDE_3_OPUS_0229 = "claude-3-opus-20240229"
CLAUDE_3_SONNET = "claude-3-sonnet-20240229"
CLAUDE_3_HAIKU = "claude-3-haiku-20240307"
CLAUDE_35_SONNET = "claude-3-5-sonnet-latest"  # 带 latest 标签的模型名称，会不断更新指向最新发布的模型
CLAUDE_35_SONNET_1022 = "claude-3-5-sonnet-20241022"  # 带具体日期的模型名称，会固定为该日期发布的模型
CLAUDE_35_SONNET_0620 = "claude-3-5-sonnet-20240620"
CLAUDE_4_OPUS = "claude-opus-4-0"
CLAUDE_4_7_OPUS = "claude-opus-4-7"      # Claude Opus 4.7
CLAUDE_4_6_OPUS = "claude-opus-4-6"      # Claude Opus 4.6 - Agent推荐模型
CLAUDE_4_SONNET = "claude-sonnet-4-0"    # Claude Sonnet 4.0
CLAUDE_4_5_SONNET = "claude-sonnet-4-5"  # Claude Sonnet 4.5 - Agent推荐模型
CLAUDE_4_6_SONNET = "claude-sonnet-4-6"  # Claude Sonnet 4.6 - Agent推荐模型

# Gemini (Google)
GEMINI_PRO = "gemini-1.0-pro"
GEMINI_15_flash = "gemini-1.5-flash"
GEMINI_15_PRO = "gemini-1.5-pro"
GEMINI_20_flash_exp = "gemini-2.0-flash-exp"  # exp结尾为实验模型，会逐步不再支持
GEMINI_20_FLASH = "gemini-2.0-flash"  # 正式版模型
GEMINI_25_FLASH_PRE = "gemini-2.5-flash-preview-05-20"
GEMINI_25_PRO_PRE = "gemini-2.5-pro-preview-05-06"
GEMINI_3_FLASH_PRE = "gemini-3-flash-preview"  # Gemini 3 Flash Preview - Agent推荐模型
GEMINI_3_PRO_PRE = "gemini-3-pro-preview"  # Gemini 3 Pro Preview
GEMINI_31_PRO_PRE = "gemini-3.1-pro-preview"  # Gemini 3.1 Pro Preview - Agent推荐模型
GEMINI_31_FLASH_LITE_PRE = "gemini-3.1-flash-lite-preview"  # Gemini 3.1 Flash Lite Preview - Agent推荐模型

# OpenAI
GPT35 = "gpt-3.5-turbo"
GPT35_0125 = "gpt-3.5-turbo-0125"
GPT35_1106 = "gpt-3.5-turbo-1106"
GPT4 = "gpt-4"
GPT4_06_13 = "gpt-4-0613"
GPT4_32k = "gpt-4-32k"
GPT4_32k_06_13 = "gpt-4-32k-0613"
GPT4_TURBO = "gpt-4-turbo"
GPT4_TURBO_PREVIEW = "gpt-4-turbo-preview"
GPT4_TURBO_01_25 = "gpt-4-0125-preview"
GPT4_TURBO_11_06 = "gpt-4-1106-preview"
GPT4_TURBO_04_09 = "gpt-4-turbo-2024-04-09"
GPT4_VISION_PREVIEW = "gpt-4-vision-preview"
GPT_4o = "gpt-4o"
GPT_4O_0806 = "gpt-4o-2024-08-06"
GPT_4o_MINI = "gpt-4o-mini"
GPT_41 = "gpt-4.1"
GPT_41_MINI = "gpt-4.1-mini"
GPT_41_NANO = "gpt-4.1-nano"
GPT_5 = "gpt-5"
GPT_5_MINI = "gpt-5-mini"
GPT_5_NANO = "gpt-5-nano"
GPT_54 = "gpt-5.4"  # GPT-5.4 - Agent recommended model
GPT_54_MINI = "gpt-5.4-mini"
GPT_54_NANO = "gpt-5.4-nano"
O1 = "o1-preview"
O1_MINI = "o1-mini"
WHISPER_1 = "whisper-1"
TTS_1 = "tts-1"
TTS_1_HD = "tts-1-hd"

# DeepSeek
DEEPSEEK_CHAT = "deepseek-chat"  # DeepSeek-V3对话模型
DEEPSEEK_REASONER = "deepseek-reasoner"  # DeepSeek-R1模型
DEEPSEEK_V4_FLASH = "deepseek-v4-flash"  # DeepSeek V4 Flash - 默认推荐 (思考模式 + 工具调用)
DEEPSEEK_V4_PRO = "deepseek-v4-pro"  # DeepSeek V4 Pro - 复杂任务更强 (思考模式 + 工具调用)

# Baidu Qianfan / ERNIE
ERNIE_5_1 = "ernie-5.1"  # ERNIE 5.1 - default recommendation, latest flagship
ERNIE_5 = "ernie-5.0"  # ERNIE 5.0
ERNIE_X1_1 = "ernie-x1.1"  # ERNIE X1.1 - reasoning-focused, multimodal
ERNIE_45_TURBO_128K = "ernie-4.5-turbo-128k"
ERNIE_45_TURBO_32K = "ernie-4.5-turbo-32k"
ERNIE_4_TURBO_8K = "ERNIE-4.0-Turbo-8K"
ERNIE_45_TURBO_VL = "ernie-4.5-turbo-vl"
ERNIE_45_TURBO_VL_32K = "ernie-4.5-turbo-vl-32k"

# Qwen (通义千问 - 阿里云 DashScope)
QWEN_TURBO = "qwen-turbo"
QWEN_PLUS = "qwen-plus"
QWEN_MAX = "qwen-max"
QWEN_LONG = "qwen-long"
QWEN3_MAX = "qwen3-max"  # Qwen3 Max - Agent推荐模型
QWEN35_PLUS = "qwen3.5-plus"  # Qwen3.5 Plus - Omni model (MultiModalConversation)
QWEN36_PLUS = "qwen3.6-plus"  # Qwen3.6 Plus - Omni model (MultiModalConversation)
QWQ_PLUS = "qwq-plus"

# MiniMax
MINIMAX_M2_7 = "MiniMax-M2.7"  # MiniMax M2.7 - Latest
MINIMAX_M2_7_HIGHSPEED = "MiniMax-M2.7-highspeed"  # MiniMax M2.7 highspeed
MINIMAX_M2_5 = "MiniMax-M2.5"  # MiniMax M2.5
MINIMAX_M2_1 = "MiniMax-M2.1"  # MiniMax M2.1
MINIMAX_M2_1_LIGHTNING = "MiniMax-M2.1-lightning"  # MiniMax M2.1 极速版
MINIMAX_M2 = "MiniMax-M2"  # MiniMax M2
MINIMAX_ABAB6_5 = "abab6.5-chat"  # MiniMax abab6.5

# GLM (智谱AI)
GLM_5_1 = "glm-5.1"  # 智谱 GLM-5.1 - Agent recommended model (default)
GLM_5_TURBO = "glm-5-turbo"  # 智谱 GLM-5-Turbo
GLM_5 = "glm-5"  # 智谱 GLM-5
GLM_4 = "glm-4"
GLM_4_PLUS = "glm-4-plus"
GLM_4_flash = "glm-4-flash"
GLM_4_LONG = "glm-4-long"
GLM_4_ALLTOOLS = "glm-4-alltools"
GLM_4_0520 = "glm-4-0520"
GLM_4_AIR = "glm-4-air"
GLM_4_AIRX = "glm-4-airx"
GLM_4_7 = "glm-4.7"  # 智谱 GLM-4.7 - Agent推荐模型

# Kimi (Moonshot)
MOONSHOT = "moonshot"
KIMI_K2 = "kimi-k2"
KIMI_K2_5 = "kimi-k2.5"
KIMI_K2_6 = "kimi-k2.6"  # Kimi K2.6 - Agent recommended model (default)

# Doubao (Volcengine Ark)
DOUBAO = "doubao"
DOUBAO_SEED_2_CODE = "doubao-seed-2-0-code-preview-260215"
DOUBAO_SEED_2_PRO = "doubao-seed-2-0-pro-260215"
DOUBAO_SEED_2_LITE = "doubao-seed-2-0-lite-260215"
DOUBAO_SEED_2_MINI = "doubao-seed-2-0-mini-260215"

# ModelScope(魔搭社区)
QWEN3_235B_A22B_INSTRUCT_2507 = "Qwen/Qwen3-235B-A22B-Instruct-2507"
QWEN3_5_27B = "Qwen/Qwen3.5-27B"

# 其他模型
WEN_XIN = "wenxin"
WEN_XIN_4 = "wenxin-4"
XUNFEI = "xunfei"
LINKAI_35 = "linkai-3.5"
LINKAI_4_TURBO = "linkai-4-turbo"
LINKAI_4o = "linkai-4o"
MODELSCOPE = "modelscope"

GITEE_AI_MODEL_LIST = ["Yi-34B-Chat", "InternVL2-8B", "deepseek-coder-33B-instruct", "InternVL2.5-26B", "Qwen2-VL-72B", "Qwen2.5-32B-Instruct", "glm-4-9b-chat", "codegeex4-all-9b", "Qwen2.5-Coder-32B-Instruct", "Qwen2.5-72B-Instruct", "Qwen2.5-7B-Instruct", "Qwen2-72B-Instruct", "Qwen2-7B-Instruct", "code-raccoon-v1", "Qwen2.5-14B-Instruct"]

MODELSCOPE_MODEL_LIST = ["deepseek-ai/DeepSeek-R1-0528", "deepseek-ai/DeepSeek-R1-Distill-Llama-70B", "deepseek-ai/DeepSeek-R1-Distill-Llama-8B", "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B", "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B", "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
                         "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B", "deepseek-ai/DeepSeek-V3.2", "LLM-Research/c4ai-command-r-plus-08-2024", "LLM-Research/Llama-4-Maverick-17B-128E-Instruct", "meituan-longcat/LongCat-Flash-Lite", "MiniMax/MiniMax-M1-80k", "MiniMax/MiniMax-M2.5", "mistralai/Ministral-8B-Instruct-2410",
                         "mistralai/Mistral-Large-Instruct-2407", "mistralai/Mistral-Small-Instruct-2409", "moonshotai/Kimi-K2.5", "MusePublic/Qwen-Image-Edit", "opencompass/CompassJudger-1-32B-Instruct", "OpenGVLab/InternVL3_5-241B-A28B",
                         "Qwen/QVQ-72B-Preview", "Qwen/Qwen-Image-Edit", "Qwen/Qwen3-0.6B", "Qwen/Qwen3-1.7B", "Qwen/Qwen3-14B", "Qwen/Qwen3-235B-A22B", "Qwen/Qwen3-235B-A22B-Instruct-2507", "Qwen/Qwen3-235B-A22B-Thinking-2507", "Qwen/Qwen3-30B-A3B", "Qwen/Qwen3-30B-A3B-Thinking-2507",
                         "Qwen/Qwen3-32B", "Qwen/Qwen3-4B", "Qwen/Qwen3-8B", "Qwen/Qwen3-Coder-30B-A3B-Instruct", "Qwen/Qwen3-Coder-480B-A35B-Instruct", "Qwen/Qwen3-Next-80B-A3B-Instruct", "Qwen/Qwen3-Next-80B-A3B-Thinking", "Qwen/Qwen3-VL-235B-A22B-Instruct", "Qwen/Qwen3-VL-8B-Instruct",
                         "Qwen/Qwen3-VL-8B-Thinking", "Qwen/Qwen3.5-122B-A10B", "Qwen/Qwen3.5-27B", "Qwen/Qwen3.5-35B-A3B", "Qwen/Qwen3.5-397B-A17B", "Qwen/QwQ-32B", "Qwen/QwQ-32B-Preview", "Shanghai_AI_Laboratory/Intern-S1", "Shanghai_AI_Laboratory/Intern-S1-mini",
                         "stepfun-ai/Step-3.5-Flash", "XiaomiMiMo/MiMo-V2-Flash", "ZhipuAI/GLM-4.7-Flash", "ZhipuAI/GLM-5"]


MODEL_LIST = [
              # DeepSeek
              DEEPSEEK_V4_FLASH, DEEPSEEK_V4_PRO, DEEPSEEK_CHAT, DEEPSEEK_REASONER,

              # Baidu Qianfan / ERNIE
              QIANFAN, ERNIE_5_1, ERNIE_5, ERNIE_X1_1, ERNIE_45_TURBO_128K, ERNIE_45_TURBO_32K, ERNIE_4_TURBO_8K,
              ERNIE_45_TURBO_VL, ERNIE_45_TURBO_VL_32K,

              # MiniMax
              MiniMax, MINIMAX_M2_7, MINIMAX_M2_7_HIGHSPEED, MINIMAX_M2_5, MINIMAX_M2_1, MINIMAX_M2_1_LIGHTNING, MINIMAX_M2, MINIMAX_ABAB6_5,

              # Claude
              CLAUDE3, CLAUDE_4_6_SONNET, CLAUDE_4_7_OPUS, CLAUDE_4_6_OPUS, CLAUDE_4_OPUS, CLAUDE_4_5_SONNET, CLAUDE_4_SONNET, CLAUDE_3_OPUS, CLAUDE_3_OPUS_0229,
              CLAUDE_35_SONNET, CLAUDE_35_SONNET_1022, CLAUDE_35_SONNET_0620, CLAUDE_3_SONNET, CLAUDE_3_HAIKU,
              "claude", "claude-3-haiku", "claude-3-sonnet", "claude-3-opus", "claude-3.5-sonnet",

              # Gemini
              GEMINI_31_FLASH_LITE_PRE, GEMINI_31_PRO_PRE, GEMINI_3_PRO_PRE, GEMINI_3_FLASH_PRE, GEMINI_25_PRO_PRE, GEMINI_25_FLASH_PRE,
              GEMINI_20_FLASH, GEMINI_20_flash_exp, GEMINI_15_PRO, GEMINI_15_flash, GEMINI_PRO, GEMINI,

              # OpenAI
              GPT35, GPT35_0125, GPT35_1106, "gpt-3.5-turbo-16k",
              GPT4, GPT4_06_13, GPT4_32k, GPT4_32k_06_13,
              GPT4_TURBO, GPT4_TURBO_PREVIEW, GPT4_TURBO_01_25, GPT4_TURBO_11_06, GPT4_TURBO_04_09,
              GPT_4o, GPT_4O_0806, GPT_4o_MINI,
              GPT_41, GPT_41_MINI, GPT_41_NANO,
              GPT_5, GPT_5_MINI, GPT_5_NANO,
              GPT_54, GPT_54_MINI, GPT_54_NANO,
              O1, O1_MINI,

              # GLM (智谱AI)
              ZHIPU_AI, GLM_5_1, GLM_5_TURBO, GLM_5, GLM_4, GLM_4_PLUS, GLM_4_flash, GLM_4_LONG, GLM_4_ALLTOOLS,
              GLM_4_0520, GLM_4_AIR, GLM_4_AIRX, GLM_4_7,

              # Qwen (通义千问)
              QWEN36_PLUS, QWEN35_PLUS, QWEN3_MAX, QWEN_MAX, QWEN_PLUS, QWEN_TURBO, QWEN_LONG,

              # Doubao (豆包)
              DOUBAO, DOUBAO_SEED_2_CODE, DOUBAO_SEED_2_PRO, DOUBAO_SEED_2_LITE, DOUBAO_SEED_2_MINI,

              # Kimi (Moonshot)
              MOONSHOT, "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k",
              KIMI_K2_6, KIMI_K2_5, KIMI_K2,

              # ModelScope
              MODELSCOPE,

              # LinkAI
              LINKAI_35, LINKAI_4_TURBO, LINKAI_4o,

              # 其他模型
              WEN_XIN, WEN_XIN_4, XUNFEI,
            ]

MODEL_LIST = MODEL_LIST + GITEE_AI_MODEL_LIST + MODELSCOPE_MODEL_LIST
# channel
FEISHU = "feishu"
DINGTALK = "dingtalk"
WECOM_BOT = "wecom_bot"
QQ = "qq"
WEIXIN = "weixin"
