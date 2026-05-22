#!/bin/bash
set -e

# ============================
# CowAgent Management Script
# ============================

# ANSI colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Emojis
EMOJI_ROCKET="🚀"
EMOJI_COW="🐄"
EMOJI_CHECK="✅"
EMOJI_CROSS="❌"
EMOJI_WARN="⚠️"
EMOJI_STOP="🛑"
EMOJI_WRENCH="🔧"

# Check if using Bash
if [ -z "$BASH_VERSION" ]; then
    echo -e "${RED}❌ Please run this script with Bash.${NC}"
    exit 1
fi

# Cross-platform timeout: prefer GNU timeout/gtimeout, fallback to a pure-bash implementation
# that uses background process + sleep to enforce a hard time limit.
if command -v timeout &> /dev/null; then
    _timeout() { timeout "$@"; }
elif command -v gtimeout &> /dev/null; then
    _timeout() { gtimeout "$@"; }
else
    _timeout() {
        local secs=$1; shift
        "$@" &
        local cmd_pid=$!
        ( sleep "$secs"; kill $cmd_pid 2>/dev/null ) &
        local watcher_pid=$!
        wait $cmd_pid 2>/dev/null
        local exit_code=$?
        kill $watcher_pid 2>/dev/null
        wait $watcher_pid 2>/dev/null
        return $exit_code
    }
fi

# Get current script directory
export BASE_DIR=$(cd "$(dirname "$0")"; pwd)

# Detect if in project directory
IS_PROJECT_DIR=false
if [ -f "${BASE_DIR}/config-template.json" ] && [ -f "${BASE_DIR}/app.py" ]; then
    IS_PROJECT_DIR=true
fi

# Check and install tool
check_and_install_tool() {
    local tool_name=$1
    if ! command -v "$tool_name" &> /dev/null; then
        echo -e "${YELLOW}⚙️  $tool_name not found, installing...${NC}"
        if command -v yum &> /dev/null; then
            sudo yum install "$tool_name" -y
        elif command -v apt-get &> /dev/null; then
            sudo apt-get update && sudo apt-get install "$tool_name" -y
        elif command -v brew &> /dev/null; then
            brew install "$tool_name"
        else
            echo -e "${RED}❌ Unsupported package manager. Please install $tool_name manually.${NC}"
            return 1
        fi

        if ! command -v "$tool_name" &> /dev/null; then
            echo -e "${RED}❌ Failed to install $tool_name.${NC}"
            return 1
        else
            echo -e "${GREEN}✅ $tool_name installed successfully.${NC}"
            return 0
        fi
    else
        echo -e "${GREEN}✅ $tool_name is already installed.${NC}"
        return 0
    fi
}

# Detect and set Python command
detect_python_command() {
    FOUND_NEWER_VERSION=""
    
    # Try to find Python command in order of preference
    for cmd in python3 python python3.12 python3.11 python3.10 python3.9 python3.8 python3.7; do
        if command -v $cmd &> /dev/null; then
            # Check Python version
            major_version=$($cmd -c 'import sys; print(sys.version_info[0])' 2>/dev/null)
            minor_version=$($cmd -c 'import sys; print(sys.version_info[1])' 2>/dev/null)
            
            if [[ "$major_version" == "3" ]]; then
                # Check if version is in supported range (3.7 - 3.12)
                if (( minor_version >= 7 && minor_version <= 12 )); then
                    PYTHON_CMD=$cmd
                    PYTHON_VERSION="${major_version}.${minor_version}"
                    break
                elif (( minor_version >= 13 )); then
                    # Found Python 3.13+, but not compatible
                    if [ -z "$FOUND_NEWER_VERSION" ]; then
                        FOUND_NEWER_VERSION="${major_version}.${minor_version}"
                    fi
                fi
            fi
        fi
    done
    
    if [ -z "$PYTHON_CMD" ]; then
        echo -e "${YELLOW}Tried: python3, python, python3.12, python3.11, python3.10, python3.9, python3.8, python3.7${NC}"
        if [ -n "$FOUND_NEWER_VERSION" ]; then
            echo -e "${RED}❌ Found Python $FOUND_NEWER_VERSION, but this project requires Python 3.7-3.12${NC}"
            echo -e "${YELLOW}Python 3.13+ has compatibility issues with some dependencies (web.py, cgi module removed)${NC}"
            echo -e "${YELLOW}Please install Python 3.7-3.12 (recommend Python 3.12)${NC}"
        else
            echo -e "${RED}❌ No suitable Python found. Please install Python 3.7-3.12${NC}"
        fi
        exit 1
    fi
    
    # Export for global use
    export PYTHON_CMD
    export PYTHON_VERSION
    
    echo -e "${GREEN}✅ Found Python: $PYTHON_CMD (version $PYTHON_VERSION)${NC}"
}

# Check Python version (>= 3.7)
check_python_version() {
    detect_python_command
    
    # Verify pip is available
    if ! $PYTHON_CMD -m pip --version &> /dev/null; then
        echo -e "${RED}❌ pip not found for $PYTHON_CMD. Please install pip.${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✅ pip is available for $PYTHON_CMD${NC}"
}

# Clone project
clone_project() {
    echo -e "${GREEN}🔍 Cloning CowAgent project...${NC}"

    if [ -d "CowAgent" ]; then
        echo -e "${YELLOW}⚠️  Directory 'CowAgent' already exists.${NC}"
        read -p "Choose action: overwrite(o), backup(b), or quit(q)? [press Enter for default: b]: " choice
        choice=${choice:-b}
        case "$choice" in
            o|O)
                echo -e "${YELLOW}🗑️  Overwriting 'CowAgent' directory...${NC}"
                rm -rf CowAgent
                ;;
            b|B)
                backup_dir="CowAgent_backup_$(date +%s)"
                echo -e "${YELLOW}🔀 Backing up to '$backup_dir'...${NC}"
                mv CowAgent "$backup_dir"
                ;;
            q|Q)
                echo -e "${RED}❌ Installation cancelled.${NC}"
                exit 1
                ;;
            *)
                echo -e "${RED}❌ Invalid choice. Exiting.${NC}"
                exit 1
                ;;
        esac
    fi

    check_and_install_tool git

    if ! command -v git &> /dev/null; then
        echo -e "${YELLOW}⚠️  Git not available. Trying wget/curl...${NC}"
        local zip_url="https://gitee.com/zhayujie/CowAgent/repository/archive/master.zip"
        if command -v wget &> /dev/null; then
            wget "$zip_url" -O CowAgent.zip
        elif command -v curl &> /dev/null; then
            curl -L "$zip_url" -o CowAgent.zip
        else
            echo -e "${RED}❌ Cannot download project. Please install Git, wget, or curl.${NC}"
            exit 1
        fi
        unzip CowAgent.zip
        mv CowAgent-master CowAgent
        rm CowAgent.zip
    else
        local clone_ok=false
        # Detect and temporarily disable invalid git proxy settings
        local _git_proxy_unset=false
        local _http_proxy=$(git config --global http.proxy 2>/dev/null)
        local _https_proxy=$(git config --global https.proxy 2>/dev/null)
        if [ -n "$_http_proxy" ] && ! curl -s --connect-timeout 3 --max-time 5 --proxy "$_http_proxy" https://github.com > /dev/null 2>&1; then
            echo -e "${YELLOW}⚠️  Invalid git proxy detected: $_http_proxy, temporarily disabling...${NC}"
            git config --global --unset http.proxy
            [ -n "$_https_proxy" ] && git config --global --unset https.proxy
            _git_proxy_unset=true
        fi
        # Test GitHub connectivity before attempting clone
        if curl -sI --connect-timeout 5 --max-time 10 https://github.com > /dev/null 2>&1; then
            echo -e "${YELLOW}🌐 GitHub is reachable, cloning from GitHub...${NC}"
            _timeout 60 git clone --depth 10 --progress https://github.com/zhayujie/CowAgent.git && clone_ok=true
        fi
        if [ "$clone_ok" = false ]; then
            echo -e "${YELLOW}⚠️  GitHub clone failed or timed out, switching to Gitee mirror...${NC}"
            _timeout 30 git clone --depth 10 --progress https://gitee.com/zhayujie/CowAgent.git && clone_ok=true
        fi
        if [ "$clone_ok" = false ]; then
            echo -e "${RED}❌ Project clone failed. Please check network connection.${NC}"
            if git config --global http.proxy &> /dev/null || git config --global https.proxy &> /dev/null || [ -n "$http_proxy" ] || [ -n "$https_proxy" ] || [ -n "$HTTP_PROXY" ] || [ -n "$HTTPS_PROXY" ]; then
                echo -e "${YELLOW}💡 Detected proxy settings. If proxy is misconfigured, try removing it with:${NC}"
                echo -e "${YELLOW}   git config --global --unset http.proxy${NC}"
                echo -e "${YELLOW}   git config --global --unset https.proxy${NC}"
                echo -e "${YELLOW}   unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY${NC}"
            fi
            exit 1
        fi
    fi

    cd CowAgent || { echo -e "${RED}❌ Failed to enter project directory.${NC}"; exit 1; }
    export BASE_DIR=$(pwd)
    echo -e "${GREEN}✅ Project cloned successfully: $BASE_DIR${NC}"
    
    # Add execute permission to management script
    if [ -f "${BASE_DIR}/run.sh" ]; then
        chmod +x "${BASE_DIR}/run.sh" 2>/dev/null || true
        echo -e "${GREEN}✅ Execute permission added to run.sh${NC}"
    fi
    
    sleep 1
}

# Install dependencies
install_dependencies() {
    echo -e "${GREEN}📦 Installing dependencies...${NC}"
    local PIP_MIRROR=""
    if curl -s --connect-timeout 5 https://pypi.tuna.tsinghua.edu.cn/simple/ > /dev/null 2>&1; then
        PIP_MIRROR="-i https://pypi.tuna.tsinghua.edu.cn/simple"
    fi

    PIP_EXTRA_ARGS=""
    if $PYTHON_CMD -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
        PIP_EXTRA_ARGS="--break-system-packages"
        echo -e "${YELLOW}Python 3.11+ detected, using --break-system-packages for pip installations${NC}"
    fi

    echo -e "${YELLOW}Upgrading pip and basic tools...${NC}"
    set +e
    $PYTHON_CMD -m pip install --upgrade pip setuptools wheel importlib_metadata --ignore-installed $PIP_EXTRA_ARGS $PIP_MIRROR > /tmp/pip_upgrade.log 2>&1
    [ $? -ne 0 ] && echo -e "${YELLOW}⚠️  Some tools failed to upgrade, but continuing...${NC}"
    set -e
    rm -f /tmp/pip_upgrade.log

    echo -e "${YELLOW}Installing project dependencies...${NC}"
    set +e
    $PYTHON_CMD -m pip install -r requirements.txt $PIP_EXTRA_ARGS $PIP_MIRROR > /tmp/pip_install.log 2>&1
    local exit_code=$?
    set -e
    cat /tmp/pip_install.log

    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}✅ Dependencies installed successfully.${NC}"
    elif grep -qE "distutils installed project|uninstall-no-record-file|installed by debian" /tmp/pip_install.log; then
        echo -e "${YELLOW}⚠️  Detected system package conflict, retrying with workaround...${NC}"
        local IGNORE_PACKAGES=""
        for pkg in PyYAML setuptools wheel certifi charset-normalizer; do
            IGNORE_PACKAGES="$IGNORE_PACKAGES --ignore-installed $pkg"
        done
        set +e
        $PYTHON_CMD -m pip install -r requirements.txt $IGNORE_PACKAGES $PIP_EXTRA_ARGS $PIP_MIRROR \
            && echo -e "${GREEN}✅ Dependencies installed successfully (workaround applied).${NC}" \
            || echo -e "${YELLOW}⚠️  Some dependencies may have issues, but continuing...${NC}"
        set -e
    elif grep -q "externally-managed-environment" /tmp/pip_install.log; then
        echo -e "${YELLOW}⚠️  Detected externally-managed environment, retrying with --break-system-packages...${NC}"
        set +e
        $PYTHON_CMD -m pip install -r requirements.txt --break-system-packages $PIP_MIRROR \
            && echo -e "${GREEN}✅ Dependencies installed successfully (system packages override applied).${NC}" \
            || echo -e "${YELLOW}⚠️  Some dependencies may have issues, but continuing...${NC}"
        set -e
    else
        echo -e "${YELLOW}⚠️  Installation had errors, but continuing...${NC}"
    fi

    rm -f /tmp/pip_install.log

    # Register `cow` CLI command via editable install
    echo -e "${YELLOW}Registering cow CLI...${NC}"
    set +e
    $PYTHON_CMD -m pip install -e . $PIP_EXTRA_ARGS $PIP_MIRROR > /dev/null 2>&1
    if command -v cow &> /dev/null; then
        echo -e "${GREEN}✅ cow CLI registered.${NC}"
    else
        echo -e "${YELLOW}⚠️  cow CLI not in PATH, you can still use: $PYTHON_CMD -m cli.cli${NC}"
    fi
    set -e
}

# Select model
select_model() {
    echo ""
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo -e "${CYAN}${BOLD}   Select AI Model${NC}"
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo -e "${YELLOW}1) DeepSeek (deepseek-v4-flash, deepseek-v4-pro, etc.)${NC}"
    echo -e "${YELLOW}2) MiniMax (MiniMax-M2.7, MiniMax-M2.5, etc.)${NC}"
    echo -e "${YELLOW}3) Claude (claude-sonnet-4-6, claude-opus-4-7, claude-opus-4-6, etc.)${NC}"
    echo -e "${YELLOW}4) Gemini (gemini-3.1-flash-lite-preview, gemini-3.1-pro-preview, etc.)${NC}"
    echo -e "${YELLOW}5) OpenAI GPT (gpt-5.4, gpt-5.2, gpt-4.1, etc.)${NC}"
    echo -e "${YELLOW}6) Zhipu AI (glm-5.1, glm-5-turbo, glm-5, etc.)${NC}"
    echo -e "${YELLOW}7) Qwen (qwen3.6-plus, qwen3.5-plus, qwen3-max, qwq-plus, etc.)${NC}"
    echo -e "${YELLOW}8) Doubao (doubao-seed-2-0-code-preview-260215, etc.)${NC}"
    echo -e "${YELLOW}9) Kimi (kimi-k2.6, kimi-k2.5, kimi-k2, etc.)${NC}"
    echo -e "${YELLOW}10) LinkAI (access multiple models via one API)${NC}"
    echo ""
    
    while true; do
        read -p "Enter your choice [press Enter for default: 1 - DeepSeek]: " model_choice
        model_choice=${model_choice:-1}
        case "$model_choice" in
            1|2|3|4|5|6|7|8|9|10)
                break
                ;;
            *)
                echo -e "${RED}Invalid choice. Please enter 1-10.${NC}"
                ;;
        esac
    done
}

# Read model config: provider, default_model, key_variable_name
read_model_config() {
    local provider=$1 default_model=$2 key_var=$3
    echo -e "${GREEN}Configuring ${provider}...${NC}"
    read -p "Enter ${provider} API Key: " _api_key
    read -p "Enter model name [press Enter for default: ${default_model}]: " model_name
    model_name=${model_name:-$default_model}
    MODEL_NAME="$model_name"
    eval "${key_var}=\"\$_api_key\""
}

# Read optional API base URL
read_api_base() {
    local base_var=$1 default_url=$2
    read -p "Enter API Base URL [press Enter for default: ${default_url}]: " api_base
    api_base=${api_base:-$default_url}
    eval "${base_var}=\"\$api_base\""
}

# Configure model
configure_model() {
    case "$model_choice" in
        1) read_model_config "DeepSeek" "deepseek-v4-flash" "DEEPSEEK_KEY" ;;
        2) read_model_config "MiniMax" "MiniMax-M2.7" "MINIMAX_KEY" ;;
        3)
            read_model_config "Claude" "claude-sonnet-4-6" "CLAUDE_KEY"
            read_api_base "CLAUDE_BASE" "https://api.anthropic.com/v1"
            ;;
        4)
            read_model_config "Gemini" "gemini-3.1-pro-preview" "GEMINI_KEY"
            read_api_base "GEMINI_BASE" "https://generativelanguage.googleapis.com"
            ;;
        5)
            read_model_config "OpenAI GPT" "gpt-5.4" "OPENAI_KEY"
            read_api_base "OPENAI_BASE" "https://api.openai.com/v1"
            ;;
        6) read_model_config "Zhipu AI" "glm-5.1" "ZHIPU_KEY" ;;
        7) read_model_config "Qwen (DashScope)" "qwen3.6-plus" "DASHSCOPE_KEY" ;;
        8) read_model_config "Doubao (Volcengine Ark)" "doubao-seed-2-0-code-preview-260215" "ARK_KEY" ;;
        9) read_model_config "Kimi (Moonshot)" "kimi-k2.6" "MOONSHOT_KEY" ;;
        10)
            read_model_config "LinkAI" "deepseek-v4-flash" "LINKAI_KEY"
            USE_LINKAI="true"
            ;;
    esac
}

# Select channel
select_channel() {
    echo ""
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo -e "${CYAN}${BOLD}   Select Communication Channel${NC}"
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo -e "${YELLOW}1) Weixin (微信)${NC}"
    echo -e "${YELLOW}2) Feishu (飞书)${NC}"
    echo -e "${YELLOW}3) DingTalk (钉钉)${NC}"
    echo -e "${YELLOW}4) WeCom Bot (企微智能机器人)${NC}"
    echo -e "${YELLOW}5) QQ (QQ 机器人)${NC}"
    echo -e "${YELLOW}6) WeCom App (企微自建应用)${NC}"
    echo -e "${YELLOW}7) Web (网页)${NC}"
    echo ""
    
    while true; do
        read -p "Enter your choice [press Enter for default: 1 - Weixin]: " channel_choice
        channel_choice=${channel_choice:-1}
        case "$channel_choice" in
            1|2|3|4|5|6|7)
                break
                ;;
            *)
                echo -e "${RED}Invalid choice. Please enter 1-7.${NC}"
                ;;
        esac
    done
}

# Configure channel
configure_channel() {
    case "$channel_choice" in
        1)
            # Weixin
            CHANNEL_TYPE="weixin"
            ACCESS_INFO="Weixin channel configured. Scan QR code in terminal or web console to login."
            ;;
        2)
            # Feishu (WebSocket mode)
            CHANNEL_TYPE="feishu"
            echo -e "${GREEN}Configure Feishu (WebSocket mode)...${NC}"
            read -p "Enter Feishu App ID: " fs_app_id
            read -p "Enter Feishu App Secret: " fs_app_secret
            
            FEISHU_APP_ID="$fs_app_id"
            FEISHU_APP_SECRET="$fs_app_secret"
            FEISHU_EVENT_MODE="websocket"
            ACCESS_INFO="Feishu channel configured (WebSocket mode)"
            ;;
        3)
            # DingTalk
            CHANNEL_TYPE="dingtalk"
            echo -e "${GREEN}Configure DingTalk...${NC}"
            read -p "Enter DingTalk Client ID: " dt_client_id
            read -p "Enter DingTalk Client Secret: " dt_client_secret
            
            DT_CLIENT_ID="$dt_client_id"
            DT_CLIENT_SECRET="$dt_client_secret"
            ACCESS_INFO="DingTalk channel configured"
            ;;
        4)
            # WeCom Bot
            CHANNEL_TYPE="wecom_bot"
            echo -e "${GREEN}Configure WeCom Bot...${NC}"
            read -p "Enter WeCom Bot ID: " wecom_bot_id
            read -p "Enter WeCom Bot Secret: " wecom_bot_secret
            
            WECOM_BOT_ID="$wecom_bot_id"
            WECOM_BOT_SECRET="$wecom_bot_secret"
            ACCESS_INFO="WeCom Bot channel configured"
            ;;
        5)
            # QQ
            CHANNEL_TYPE="qq"
            echo -e "${GREEN}Configure QQ Bot...${NC}"
            read -p "Enter QQ App ID: " qq_app_id
            read -p "Enter QQ App Secret: " qq_app_secret
            
            QQ_APP_ID="$qq_app_id"
            QQ_APP_SECRET="$qq_app_secret"
            ACCESS_INFO="QQ Bot channel configured"
            ;;
        6)
            # WeCom App
            CHANNEL_TYPE="wechatcom_app"
            echo -e "${GREEN}Configure WeCom App...${NC}"
            read -p "Enter WeChat Corp ID: " corp_id
            read -p "Enter WeChat Com App Token: " com_token
            read -p "Enter WeChat Com App Secret: " com_secret
            read -p "Enter WeChat Com App Agent ID: " com_agent_id
            read -p "Enter WeChat Com App AES Key: " com_aes_key
            read -p "Enter WeChat Com App Port [press Enter for default: 9898]: " com_port
            com_port=${com_port:-9898}
            
            WECHATCOM_CORP_ID="$corp_id"
            WECHATCOM_TOKEN="$com_token"
            WECHATCOM_SECRET="$com_secret"
            WECHATCOM_AGENT_ID="$com_agent_id"
            WECHATCOM_AES_KEY="$com_aes_key"
            WECHATCOM_PORT="$com_port"
            ACCESS_INFO="WeCom App channel configured on port ${com_port}"
            ;;
        7)
            # Web
            CHANNEL_TYPE="web"
            read -p "Enter web port [press Enter for default: 9899]: " web_port
            web_port=${web_port:-9899}
            
            WEB_PORT="$web_port"
            ACCESS_INFO="Web interface will be available at: http://localhost:${web_port}/chat"
            ;;
    esac
}

# Generate config file
create_config_file() {
    echo -e "${GREEN}📝 Generating config.json...${NC}"

    CHANNEL_TYPE="$CHANNEL_TYPE" \
    MODEL_NAME="$MODEL_NAME" \
    OPENAI_KEY="${OPENAI_KEY:-}" \
    OPENAI_BASE="${OPENAI_BASE:-https://api.openai.com/v1}" \
    CLAUDE_KEY="${CLAUDE_KEY:-}" \
    CLAUDE_BASE="${CLAUDE_BASE:-https://api.anthropic.com/v1}" \
    GEMINI_KEY="${GEMINI_KEY:-}" \
    GEMINI_BASE="${GEMINI_BASE:-https://generativelanguage.googleapis.com}" \
    ZHIPU_KEY="${ZHIPU_KEY:-}" \
    MOONSHOT_KEY="${MOONSHOT_KEY:-}" \
    ARK_KEY="${ARK_KEY:-}" \
    DASHSCOPE_KEY="${DASHSCOPE_KEY:-}" \
    MINIMAX_KEY="${MINIMAX_KEY:-}" \
    DEEPSEEK_KEY="${DEEPSEEK_KEY:-}" \
    DEEPSEEK_BASE="${DEEPSEEK_BASE:-https://api.deepseek.com/v1}" \
    USE_LINKAI="${USE_LINKAI:-false}" \
    LINKAI_KEY="${LINKAI_KEY:-}" \
    FEISHU_APP_ID="${FEISHU_APP_ID:-}" \
    FEISHU_APP_SECRET="${FEISHU_APP_SECRET:-}" \
    WEB_PORT="${WEB_PORT:-}" \
    DT_CLIENT_ID="${DT_CLIENT_ID:-}" \
    DT_CLIENT_SECRET="${DT_CLIENT_SECRET:-}" \
    WECOM_BOT_ID="${WECOM_BOT_ID:-}" \
    WECOM_BOT_SECRET="${WECOM_BOT_SECRET:-}" \
    QQ_APP_ID="${QQ_APP_ID:-}" \
    QQ_APP_SECRET="${QQ_APP_SECRET:-}" \
    WECHATCOM_CORP_ID="${WECHATCOM_CORP_ID:-}" \
    WECHATCOM_TOKEN="${WECHATCOM_TOKEN:-}" \
    WECHATCOM_SECRET="${WECHATCOM_SECRET:-}" \
    WECHATCOM_AGENT_ID="${WECHATCOM_AGENT_ID:-}" \
    WECHATCOM_AES_KEY="${WECHATCOM_AES_KEY:-}" \
    WECHATCOM_PORT="${WECHATCOM_PORT:-}" \
    $PYTHON_CMD -c "
import json, os
e = os.environ.get
base = {
    'channel_type': e('CHANNEL_TYPE'),
    'model': e('MODEL_NAME'),
    'open_ai_api_key': e('OPENAI_KEY', ''),
    'open_ai_api_base': e('OPENAI_BASE'),
    'claude_api_key': e('CLAUDE_KEY', ''),
    'claude_api_base': e('CLAUDE_BASE'),
    'gemini_api_key': e('GEMINI_KEY', ''),
    'gemini_api_base': e('GEMINI_BASE'),
    'zhipu_ai_api_key': e('ZHIPU_KEY', ''),
    'moonshot_api_key': e('MOONSHOT_KEY', ''),
    'ark_api_key': e('ARK_KEY', ''),
    'dashscope_api_key': e('DASHSCOPE_KEY', ''),
    'minimax_api_key': e('MINIMAX_KEY', ''),
    'deepseek_api_key': e('DEEPSEEK_KEY', ''),
    'deepseek_api_base': e('DEEPSEEK_BASE'),
    'voice_to_text': 'openai',
    'text_to_voice': 'openai',
    'voice_reply_voice': False,
    'speech_recognition': True,
    'group_speech_recognition': False,
    'use_linkai': e('USE_LINKAI') == 'true',
    'linkai_api_key': e('LINKAI_KEY', ''),
    'linkai_app_code': '',
    'agent': True,
    'agent_max_context_tokens': 40000,
    'agent_max_context_turns': 30,
    'agent_max_steps': 15,
}
channel_map = {
    'feishu': {'feishu_app_id': 'FEISHU_APP_ID', 'feishu_app_secret': 'FEISHU_APP_SECRET'},
    'web': {'web_port': ('WEB_PORT', int)},
    'dingtalk': {'dingtalk_client_id': 'DT_CLIENT_ID', 'dingtalk_client_secret': 'DT_CLIENT_SECRET'},
    'wecom_bot': {'wecom_bot_id': 'WECOM_BOT_ID', 'wecom_bot_secret': 'WECOM_BOT_SECRET'},
    'qq': {'qq_app_id': 'QQ_APP_ID', 'qq_app_secret': 'QQ_APP_SECRET'},
    'wechatcom_app': {'wechatcom_corp_id': 'WECHATCOM_CORP_ID', 'wechatcomapp_token': 'WECHATCOM_TOKEN', 'wechatcomapp_secret': 'WECHATCOM_SECRET', 'wechatcomapp_agent_id': 'WECHATCOM_AGENT_ID', 'wechatcomapp_aes_key': 'WECHATCOM_AES_KEY', 'wechatcomapp_port': ('WECHATCOM_PORT', int)},
}
ch = e('CHANNEL_TYPE')
for key, spec in channel_map.get(ch, {}).items():
    if isinstance(spec, tuple):
        env_name, conv = spec
        base[key] = conv(e(env_name))
    else:
        base[key] = e(spec, '')
with open('config.json', 'w') as f:
    json.dump(base, f, indent=2, ensure_ascii=False)
"

    echo -e "${GREEN}✅ Configuration file created successfully.${NC}"
}

# Start project
start_project() {
    echo ""
    echo -e "${GREEN}${EMOJI_ROCKET} Starting CowAgent...${NC}"
    sleep 1

    local USE_COW=false
    if command -v cow &> /dev/null; then
        USE_COW=true
    fi

    if $USE_COW; then
        cd "${BASE_DIR}"
        cow start --no-logs
    else
        if [ ! -f "${BASE_DIR}/nohup.out" ]; then
            touch "${BASE_DIR}/nohup.out"
        fi

        OS_TYPE=$(uname)

        if [[ "$OS_TYPE" == "Linux" ]]; then
            nohup setsid $PYTHON_CMD "${BASE_DIR}/app.py" > "${BASE_DIR}/nohup.out" 2>&1 &
            echo -e "${GREEN}${EMOJI_COW} CowAgent started on Linux (using $PYTHON_CMD)${NC}"
        elif [[ "$OS_TYPE" == "Darwin" ]]; then
            nohup $PYTHON_CMD "${BASE_DIR}/app.py" > "${BASE_DIR}/nohup.out" 2>&1 &
            echo -e "${GREEN}${EMOJI_COW} CowAgent started on macOS (using $PYTHON_CMD)${NC}"
        else
            echo -e "${RED}❌ Unsupported OS: ${OS_TYPE}${NC}"
            exit 1
        fi
    fi

    sleep 2
    echo ""
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo -e "${GREEN}${EMOJI_CHECK} CowAgent is now running in background!${NC}"
    echo -e "${GREEN}${EMOJI_CHECK} Process will continue after closing terminal.${NC}"
    echo -e "${CYAN}$ACCESS_INFO${NC}"
    echo ""
    echo -e "${CYAN}${BOLD}Management Commands:${NC}"
    if $USE_COW; then
        echo -e "  ${GREEN}cow stop${NC}       Stop the service"
        echo -e "  ${GREEN}cow restart${NC}    Restart the service"
        echo -e "  ${GREEN}cow status${NC}     Check status"
        echo -e "  ${GREEN}cow logs${NC}       View logs"
        echo -e "  ${GREEN}cow update${NC}     Update and restart"
        echo -e "  ${GREEN}cow install-browser${NC}  Install browser tool"
    else
        echo -e "  ${GREEN}./run.sh stop${NC}       Stop the service"
        echo -e "  ${GREEN}./run.sh restart${NC}    Restart the service"
        echo -e "  ${GREEN}./run.sh status${NC}     Check status"
        echo -e "  ${GREEN}./run.sh logs${NC}       View logs"
        echo -e "  ${GREEN}./run.sh update${NC}     Update and restart"
    fi
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo ""

    echo -e "${YELLOW}Showing recent logs (Ctrl+C to exit, agent keeps running):${NC}"
    sleep 2
    tail -n 30 -f "${BASE_DIR}/nohup.out"
}

# Show usage
show_usage() {
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo -e "${CYAN}${BOLD}   ${EMOJI_COW} CowAgent Management Script${NC}"
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo ""
    echo -e "${YELLOW}Usage:${NC}"
    echo -e "  ${GREEN}./run.sh${NC}               ${CYAN}# Install/Configure project${NC}"
    echo -e "  ${GREEN}./run.sh <command>${NC}     ${CYAN}# Execute management command${NC}"
    echo ""
    echo -e "${YELLOW}Commands:${NC}"
    echo -e "  ${GREEN}start${NC}      Start the service"
    echo -e "  ${GREEN}stop${NC}       Stop the service"
    echo -e "  ${GREEN}restart${NC}    Restart the service"
    echo -e "  ${GREEN}status${NC}     Check service status"
    echo -e "  ${GREEN}logs${NC}       View logs (tail -f)"
    echo -e "  ${GREEN}config${NC}     Reconfigure project"
    echo -e "  ${GREEN}update${NC}     Update and restart"
    echo ""
    echo -e "${YELLOW}Examples:${NC}"
    echo -e "  ${GREEN}./run.sh start${NC}"
    echo -e "  ${GREEN}./run.sh logs${NC}"
    echo -e "  ${GREEN}./run.sh status${NC}"
    echo -e "${CYAN}${BOLD}=========================================${NC}"
}

# Ensure PYTHON_CMD is set
ensure_python_cmd() {
    if [ -z "$PYTHON_CMD" ]; then
        detect_python_command > /dev/null 2>&1 || PYTHON_CMD="python3"
    fi
}

# Get service PID (empty string if not running)
get_pid() {
    ensure_python_cmd > /dev/null 2>&1
    ps ax | grep -i app.py | grep "${BASE_DIR}" | grep "$PYTHON_CMD" | grep -v grep | awk '{print $1}' | grep -E '^[0-9]+$' | head -1
}

# Check if service is running
is_running() {
    [ -n "$(get_pid)" ]
}

# Check if cow CLI is available
has_cow() {
    command -v cow &> /dev/null
}

# Start service
cmd_start() {
    if [ ! -f "${BASE_DIR}/config.json" ]; then
        echo -e "${RED}${EMOJI_CROSS} config.json not found${NC}"
        echo -e "${YELLOW}Please run './run.sh' to configure first${NC}"
        exit 1
    fi

    if has_cow; then
        cd "${BASE_DIR}"
        cow start
    else
        if is_running; then
            echo -e "${YELLOW}${EMOJI_WARN} CowAgent is already running (PID: $(get_pid))${NC}"
            echo -e "${YELLOW}Use './run.sh restart' to restart${NC}"
            return
        fi
        check_python_version
        start_project
    fi
}

# Stop service
cmd_stop() {
    if has_cow; then
        cd "${BASE_DIR}"
        cow stop
    else
        echo -e "${GREEN}${EMOJI_STOP} Stopping CowAgent...${NC}"

        if ! is_running; then
            echo -e "${YELLOW}${EMOJI_WARN} CowAgent is not running${NC}"
            return
        fi

        pid=$(get_pid)
        if [ -z "$pid" ] || ! echo "$pid" | grep -qE '^[0-9]+$'; then
            echo -e "${RED}❌ Failed to get valid PID (got: ${pid})${NC}"
            return 1
        fi

        echo -e "${GREEN}Found running process (PID: ${pid})${NC}"

        kill ${pid}
        sleep 3

        if ps -p ${pid} > /dev/null 2>&1; then
            echo -e "${YELLOW}⚠️  Process not stopped, forcing termination...${NC}"
            kill -9 ${pid}
        fi

        echo -e "${GREEN}${EMOJI_CHECK} CowAgent stopped${NC}"
    fi
}

# Restart service
cmd_restart() {
    if has_cow; then
        cd "${BASE_DIR}"
        cow restart
    else
        cmd_stop
        sleep 1
        cmd_start
    fi
}

# Check status
cmd_status() {
    if has_cow; then
        cd "${BASE_DIR}"
        cow status
    else
        echo -e "${CYAN}${BOLD}=========================================${NC}"
        echo -e "${CYAN}${BOLD}   ${EMOJI_COW} CowAgent Status${NC}"
        echo -e "${CYAN}${BOLD}=========================================${NC}"

        if is_running; then
            pid=$(get_pid)
            echo -e "${GREEN}Status:${NC} ✅ Running"
            echo -e "${GREEN}PID:${NC}    ${pid}"
            if [ -f "${BASE_DIR}/nohup.out" ]; then
                echo -e "${GREEN}Logs:${NC}   ${BASE_DIR}/nohup.out"
            fi
        else
            echo -e "${YELLOW}Status:${NC} ⭐ Stopped"
        fi

        if [ -f "${BASE_DIR}/config.json" ]; then
            model=$(grep -o '"model"[[:space:]]*:[[:space:]]*"[^"]*"' "${BASE_DIR}/config.json" | cut -d'"' -f4)
            channel=$(grep -o '"channel_type"[[:space:]]*:[[:space:]]*"[^"]*"' "${BASE_DIR}/config.json" | cut -d'"' -f4)
            echo -e "${GREEN}Model:${NC}  ${model}"
            echo -e "${GREEN}Channel:${NC} ${channel}"
        fi

        echo -e "${CYAN}${BOLD}=========================================${NC}"
    fi
}

# View logs
cmd_logs() {
    if has_cow; then
        cd "${BASE_DIR}"
        cow logs -f
    else
        if [ -f "${BASE_DIR}/nohup.out" ]; then
            echo -e "${YELLOW}Viewing logs (Ctrl+C to exit):${NC}"
            tail -f "${BASE_DIR}/nohup.out"
        else
            echo -e "${RED}❌ Log file not found: ${BASE_DIR}/nohup.out${NC}"
        fi
    fi
}

# Reconfigure
cmd_config() {
    echo -e "${YELLOW}${EMOJI_WRENCH} Reconfiguring CowAgent...${NC}"
    
    if [ -f "${BASE_DIR}/config.json" ]; then
        backup_file="${BASE_DIR}/config.json.backup.$(date +%s)"
        cp "${BASE_DIR}/config.json" "${backup_file}"
        echo -e "${GREEN}✅ Backed up config to: ${backup_file}${NC}"
    fi
    
    check_python_version
    install_dependencies
    select_model
    configure_model
    select_channel
    configure_channel
    create_config_file
    
    echo ""
    read -p "Restart service now? [Y/n]: " restart_now
    if [[ ! $restart_now == [Nn]* ]]; then
        cmd_restart
    fi
}

# Update project
cmd_update() {
    echo -e "${GREEN}${EMOJI_WRENCH} Updating CowAgent...${NC}"
    cd "${BASE_DIR}"
    
    # Pull latest code first (service still running)
    local pull_ok=false
    if [ -d .git ]; then
        echo -e "${GREEN}🔄 Pulling latest code...${NC}"
        if git pull; then
            pull_ok=true
        else
            echo -e "${YELLOW}⚠️  git pull failed, trying Gitee mirror...${NC}"
            git remote set-url origin https://gitee.com/zhayujie/CowAgent.git
            if git pull; then
                pull_ok=true
            else
                echo -e "${RED}❌ Failed to pull code. Update aborted.${NC}"
                exit 1
            fi
        fi
    else
        echo -e "${YELLOW}⚠️  Not a git repository, skipping code update${NC}"
    fi
    
    # Re-exec with the updated run.sh to pick up new logic
    exec "$0" _post_update
}

# Post-update: called by cmd_update after git pull to run with new code
cmd_post_update() {
    cd "${BASE_DIR}"

    # Stop service
    if is_running; then
        cmd_stop
    fi

    # Reinstall dependencies
    check_python_version
    install_dependencies

    # Restart service
    cmd_start
}

# Installation mode
install_mode() {
    clear
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo -e "${CYAN}${BOLD}   ${EMOJI_COW} CowAgent Installation${NC}"
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo ""
    sleep 1

    if [ "$IS_PROJECT_DIR" = true ]; then
        echo -e "${GREEN}✅ Detected existing project directory.${NC}"
        
        if [ -f "${BASE_DIR}/config.json" ]; then
            echo -e "${GREEN}✅ Project already configured${NC}"
            echo ""
            show_usage
            return
        fi
        
        echo -e "${YELLOW}📝 No config.json found. Let's configure your project!${NC}"
        echo ""
        
        # Project directory already exists, skip clone
        check_python_version
    else
        # Remote install mode, need to clone project
        check_python_version
        clone_project
    fi
    
    # Install dependencies and configure
    install_dependencies
    select_model
    configure_model
    select_channel
    configure_channel
    create_config_file
    
    echo ""
    read -p "Start CowAgent now? [Y/n]: " start_now
    if [[ ! $start_now == [Nn]* ]]; then
        start_project
    else
        echo -e "${GREEN}✅ Installation complete!${NC}"
        echo ""
        echo -e "${CYAN}${BOLD}To start manually:${NC}"
        echo -e "${YELLOW}  cd ${BASE_DIR}${NC}"
        echo -e "${YELLOW}  ./run.sh start${NC}"
        echo ""
        echo -e "${CYAN}Or use nohup directly:${NC}"
        echo -e "${YELLOW}  nohup $PYTHON_CMD app.py > nohup.out 2>&1 & tail -f nohup.out${NC}"
    fi
}

# Require running inside the project directory
require_project_dir() {
    if [ "$IS_PROJECT_DIR" = false ]; then
        echo -e "${RED}${EMOJI_CROSS} Must run in project directory${NC}"
        exit 1
    fi
}

# Main function
main() {
    case "$1" in
        start|stop|restart|status|logs|config|update|_post_update)
            require_project_dir
            ;;
    esac

    case "$1" in
        start)   cmd_start ;;
        stop)    cmd_stop ;;
        restart) cmd_restart ;;
        status)  cmd_status ;;
        logs)    cmd_logs ;;
        config)  cmd_config ;;
        update)  cmd_update ;;
        _post_update) cmd_post_update ;;
        help|--help|-h)
            show_usage
            ;;
        "")
            install_mode
            ;;
        *)
            echo -e "${RED}${EMOJI_CROSS} Unknown command: $1${NC}"
            echo ""
            show_usage
            exit 1
            ;;
    esac
}

# Execute main function
main "$@"
