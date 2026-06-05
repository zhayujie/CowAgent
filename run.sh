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

# ============================
# i18n: install-flow language
# ============================
# UI_LANG controls the language of install prompts/menus. Detected on first run
# (or chosen by the user), defaults to auto-detection. "zh" or "en".
UI_LANG=""

# A terminal we can read from. When the script runs via `curl | bash`, stdin is
# the script pipe (EOF on read), so interactive prompts must read from the tty.
TTY_DEV="/dev/tty"
HAS_TTY=false
if [ -r /dev/tty ] && [ -w /dev/tty ]; then
    HAS_TTY=true
fi

# Detect default UI language from environment (best-effort, mirrors common/i18n).
detect_ui_lang() {
    local loc=""
    # macOS: prefer AppleLocale, which reflects the real UI language
    if [ "$(uname)" = "Darwin" ] && command -v defaults &> /dev/null; then
        loc=$(defaults read -g AppleLocale 2>/dev/null || true)
    fi
    [ -z "$loc" ] && loc="${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}"
    case "$loc" in
        zh* | *zh_* | *_CN* | *_TW* | *_HK* | *Hans* | *Hant*) echo "zh" ;;
        *) echo "en" ;;
    esac
}

# Translation helper: t <zh_text> <en_text>
t() {
    if [ "$UI_LANG" = "en" ]; then
        printf '%s' "$2"
    else
        printf '%s' "$1"
    fi
}

# Read a line from the controlling terminal (works under `curl | bash`).
# Usage: tty_read VAR "prompt"
tty_read() {
    local __var=$1 __prompt=$2 __input=""
    if [ "$HAS_TTY" = true ]; then
        # Ensure the tty is in normal line mode. A preceding arrow-key menu
        # may have left it in cbreak/-echo mode; without this, `read` could
        # return immediately or not echo typed characters.
        stty sane < "$TTY_DEV" 2>/dev/null || true
        # Print the prompt explicitly (not via read -p, whose prompt can be
        # swallowed right after an arrow-key menu) and read from the tty.
        # `|| true` so a non-zero read (EOF) does NOT trip `set -e`.
        printf '%s' "$__prompt" > /dev/tty
        read -r __input < "$TTY_DEV" || true
    else
        read -r -p "$__prompt" __input || true
    fi
    printf -v "$__var" '%s' "$__input"
}

# Arrow-key selectable menu with number fallback.
# Usage: select_menu OUT_VAR "Title" "opt1" "opt2" ...
# Result: OUT_VAR is set to the selected index (1-based).
select_menu() {
    # Interactive function: never let a non-zero command (read EOF, arithmetic
    # evaluating to 0, etc.) abort the caller under `set -e`.
    set +e
    local __out=$1; shift
    local title=$1; shift
    local options=("$@")
    local count=${#options[@]}
    # Initial highlight: MENU_DEFAULT (1-based) if set, else first option.
    local cur=0
    if [[ "${MENU_DEFAULT:-}" =~ ^[0-9]+$ ]] && (( MENU_DEFAULT >= 1 && MENU_DEFAULT <= count )); then
        cur=$((MENU_DEFAULT - 1))
    fi
    MENU_DEFAULT=""

    # Fallback to numbered input when no interactive terminal is available
    # (e.g. CI, non-tty pipe). Arrow-key rendering needs a real tty.
    if [ "$HAS_TTY" != true ] || [ ! -t 1 ]; then
        local def=$((cur + 1))
        echo -e "${CYAN}${BOLD}${title}${NC}"
        local i=1
        for opt in "${options[@]}"; do
            echo -e "  ${YELLOW}${i})${NC} ${opt}"
            i=$((i + 1))
        done
        local choice=""
        while true; do
            tty_read choice "$(t "请输入序号" "Enter number") [1-${count}, $(t "默认" "default") ${def}]: "
            choice=${choice:-$def}
            if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= count )); then
                break
            fi
            echo -e "${RED}$(t "无效选择，请输入" "Invalid choice, enter") 1-${count}${NC}"
        done
        printf -v "$__out" '%s' "$choice"
        return
    fi

    # Interactive arrow-key menu.
    # Use literal escape characters (via $'...') and printf instead of
    # `echo -e`, because `echo`'s backslash handling is not portable and
    # leaks raw "\e[K" text on some shells/terminals.
    local ESC=$'\033'
    local UP="${ESC}[A"          # move cursor up one line
    local CLR="${ESC}[K"         # clear to end of line

    # fd 3 is a long-lived (read) handle to the controlling terminal, opened
    # once by menu_session_begin() before the install flow. Reusing one fd
    # across all menus avoids the bash 3.2 bug where re-opening /dev/tty per
    # menu makes the second menu read EOF and auto-select the default.
    # Detect whether fd 3 is already open using a READ redirection (fd 3 is
    # read-only; testing with `>&3` would wrongly report it as closed).
    local _own_fd3=false
    if ! { : <&3; } 2>/dev/null; then
        exec 3<"$TTY_DEV"
        _own_fd3=true
    fi

    # Put the terminal into cbreak/raw input mode so single keystrokes arrive
    # immediately and are not echoed.
    #   -echo    : don't echo keystrokes (otherwise arrow keys leak as ^[[A)
    #   -icanon  : disable line buffering
    #   min 1 time 0 : read returns as soon as 1 byte is available
    local _restore="tput cnorm 2>/dev/null; stty echo icanon <${TTY_DEV} 2>/dev/null"
    trap "$_restore" EXIT INT TERM
    tput civis 2>/dev/null || true
    stty -echo -icanon min 1 time 0 <&3 2>/dev/null || true

    printf '%b\n' "${CYAN}${BOLD}${title}${NC}"
    printf '%b\n' "${CYAN}$(t "↑/↓ 选择，Enter 确认" "Use ↑/↓ to move, Enter to select")${NC}"

    local first_draw=true
    while true; do
        # Move cursor up to the top of the option block to redraw it.
        if [ "$first_draw" = false ]; then
            local i=0
            while [ $i -lt $count ]; do
                printf '%s' "$UP"
                i=$((i + 1))
            done
        fi
        first_draw=false

        local idx=0
        for opt in "${options[@]}"; do
            if [ $idx -eq $cur ]; then
                printf '%s%b\n' "$CLR" "  ${GREEN}${BOLD}❯ ${opt}${NC}"
            else
                printf '%s%b\n' "$CLR" "    ${opt}"
            fi
            idx=$((idx + 1))
        done

        # Read one key from the shared terminal fd 3.
        local key=""
        IFS= read -rsn1 key <&3
        local rc=$?
        if [ $rc -ne 0 ]; then
            # No usable terminal: restore and fall back to numbered input.
            eval "$_restore"; trap - EXIT INT TERM
            [ "${_own_fd3:-}" = true ] && exec 3<&- 2>/dev/null
            local choice=""
            while true; do
                tty_read choice "$(t "请输入序号" "Enter number") [1-${count}]: "
                choice=${choice:-$((cur + 1))}
                if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= count )); then
                    break
                fi
            done
            printf -v "$__out" '%s' "$choice"
            return
        fi

        # Empty key means Enter/Return (read -n1 strips the newline delimiter).
        if [ -z "$key" ]; then
            break
        fi

        case "$key" in
            "$ESC")
                # Arrow key: ESC [ A/B (or ESC O A/B). Read the two trailing
                # bytes one at a time, no timeout (bash 3.2 has no fractional
                # read -t; in cbreak mode the bytes are already buffered).
                local b2="" b3=""
                IFS= read -rsn1 b2 <&3 2>/dev/null || b2=""
                IFS= read -rsn1 b3 <&3 2>/dev/null || b3=""
                case "${b2}${b3}" in
                    "[A" | "OA") cur=$(( (cur - 1 + count) % count )) ;;  # up
                    "[B" | "OB") cur=$(( (cur + 1) % count )) ;;          # down
                esac
                ;;
            $'\n' | $'\r')
                break
                ;;
            [0-9])
                if (( key >= 1 && key <= count )); then
                    cur=$((key - 1))
                    break
                fi
                ;;
            $'\003')
                # Ctrl-C: restore and abort.
                eval "$_restore"; trap - EXIT INT TERM
                [ "${_own_fd3:-}" = true ] && exec 3<&- 2>/dev/null
                printf '\n%b\n' "${RED}$(t "已取消安装" "Installation cancelled")${NC}"
                exit 130
                ;;
        esac
    done

    eval "$_restore"
    trap - EXIT INT TERM
    [ "${_own_fd3:-}" = true ] && exec 3<&- 2>/dev/null
    printf -v "$__out" '%s' "$((cur + 1))"
}

# Open/close a long-lived terminal handle (fd 3) shared by all menus in an
# install/config session. Opening fd 3 once avoids per-menu re-open issues on
# bash 3.2 (second menu reading EOF). Safe no-ops when there is no tty.
menu_session_begin() {
    [ "$HAS_TTY" = true ] || return 0
    exec 3<"$TTY_DEV" 2>/dev/null || true
}
menu_session_end() {
    exec 3<&- 2>/dev/null || true
}

# Ask the user to choose the install/UI language (first step of install).
select_language() {
    # Order is fixed (English first, Chinese second). The default highlight
    # follows detection, but conservatively: only a confident "zh" signal
    # (macOS AppleLocale / Linux zh_* locale) preselects Chinese; everything
    # else (English, empty/C/POSIX locale, server images) defaults to English.
    local detected
    detected=$(detect_ui_lang)
    if [ "$detected" = "zh" ]; then
        MENU_DEFAULT=2
        UI_LANG="zh"
    else
        MENU_DEFAULT=1
        UI_LANG="en"
    fi

    local lang_choice
    select_menu lang_choice "Select Language / 选择语言" "English" "中文 (Chinese)"
    case "$lang_choice" in
        1) UI_LANG="en" ;;
        2) UI_LANG="zh" ;;
        *) UI_LANG="en" ;;
    esac
    # Remember for the rest of the flow (config write happens later)
    INSTALL_LANG="$UI_LANG"
}

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

# Get current script directory.
# When launched via process substitution (`bash <(curl ...)`) or a pipe,
# $0 points at /dev/fd/* or "bash", so dirname is meaningless. Fall back to
# the current working directory in that case (remote install will cd into
# the cloned project dir and reset BASE_DIR afterwards).
_script_src="$0"
case "$_script_src" in
    /dev/fd/* | /proc/self/fd/* | bash | sh | -* | "")
        export BASE_DIR="$(pwd)"
        ;;
    *)
        export BASE_DIR=$(cd "$(dirname "$_script_src")" 2>/dev/null && pwd || pwd)
        ;;
esac

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
        # An existing directory is automatically backed up (no prompt) so the
        # installer stays one-shot / hands-off.
        local backup_dir="CowAgent_backup_$(date +%s)"
        echo -e "${YELLOW}⚠️  $(t "目录 'CowAgent' 已存在，自动备份到" "Directory 'CowAgent' exists, backing up to") '$backup_dir'...${NC}"
        mv CowAgent "$backup_dir"
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
        # Unzip: prefer `unzip`, otherwise fall back to Python's zipfile (no
        # extra dependency) so minimal environments without unzip still work.
        if command -v unzip &> /dev/null; then
            unzip CowAgent.zip
        elif command -v python3 &> /dev/null; then
            python3 -m zipfile -e CowAgent.zip .
        elif command -v python &> /dev/null; then
            python -m zipfile -e CowAgent.zip .
        else
            echo -e "${RED}❌ Cannot extract archive. Please install 'unzip' or Python.${NC}"
            exit 1
        fi
        # Archive top-level dir name may vary (CowAgent-master, etc.); detect it.
        local _extracted="CowAgent-master"
        if [ ! -d "$_extracted" ]; then
            _extracted=$(ls -d CowAgent-*/ 2>/dev/null | head -1 | sed 's:/*$::')
        fi
        [ -n "$_extracted" ] && [ -d "$_extracted" ] && mv "$_extracted" CowAgent
        rm -f CowAgent.zip
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
    # Pick the pip index by install language, then fall back to the other if the
    # preferred one is unreachable:
    #   - zh users: Tsinghua mirror first (fast in China), official PyPI fallback
    #   - others : official PyPI first, Tsinghua mirror fallback
    local PIP_MIRROR=""
    local _tuna="https://pypi.tuna.tsinghua.edu.cn/simple"
    local _pypi="https://pypi.org/simple"
    if [ "$UI_LANG" = "zh" ]; then
        # Prefer Tsinghua; if it's down, fall back to official PyPI (pip default).
        if curl -s --connect-timeout 5 "${_tuna}/" > /dev/null 2>&1; then
            PIP_MIRROR="-i $_tuna"
        fi
    else
        # Prefer official PyPI; only use Tsinghua if PyPI is unreachable.
        if ! curl -s --connect-timeout 5 "${_pypi}/" > /dev/null 2>&1 \
           && curl -s --connect-timeout 5 "${_tuna}/" > /dev/null 2>&1; then
            PIP_MIRROR="-i $_tuna"
        fi
    fi
    if [ -n "$PIP_MIRROR" ]; then
        echo -e "${YELLOW}Using pip mirror: ${_tuna}${NC}"
    fi

    # Only pass --break-system-packages if this pip actually supports it
    # (pip >= 23.x). Older pip versions error out with "no such option",
    # which previously dumped a confusing usage message and failed the install.
    PIP_EXTRA_ARGS=""
    if $PYTHON_CMD -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null \
       && $PYTHON_CMD -m pip install --help 2>/dev/null | grep -q -- "--break-system-packages"; then
        PIP_EXTRA_ARGS="--break-system-packages"
        echo -e "${YELLOW}Python 3.11+ with break-system-packages support detected${NC}"
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
    local title sel
    title="$(t "选择 AI 模型" "Select AI Model")"
    # The 12th option is "skip" -> configure later in the web console.
    select_menu sel "$title" \
        "DeepSeek (deepseek-v4-flash, deepseek-v4-pro, etc.)" \
        "Claude (claude-opus-4-8, claude-opus-4-7, etc.)" \
        "Gemini (gemini-3.5-flash, gemini-3.1-pro-preview, etc.)" \
        "OpenAI (gpt-5.5, etc.)" \
        "MiniMax (MiniMax-M3, etc.)" \
        "GLM (glm-5.1, etc.)" \
        "Qwen (qwen3.7-plus, qwen3.7-max, etc.)" \
        "Doubao (doubao-seed-2.0, etc.)" \
        "Kimi (kimi-k2.6, etc.)" \
        "MiMo (mimo-v2.5-pro, etc.)" \
        "LinkAI ($(t "一个 Key 接入所有模型" "access all models via one API"))" \
        "$(t "⏭  跳过（稍后在 Web 控制台配置）" "⏭  Skip (configure later in the web console)")"
    model_choice="$sel"
}

# Read model config: provider, default_model, key_variable_name
read_model_config() {
    local provider=$1 default_model=$2 key_var=$3
    echo -e "${GREEN}$(t "正在配置" "Configuring") ${provider}...${NC}"
    # Only ask for the API key here; the model name and API base default to
    # sensible values and can be changed later in the web console.
    local _api_key
    tty_read _api_key "$(t "请输入" "Enter") ${provider} API Key ($(t "回车跳过，稍后在 Web 控制台填写" "press Enter to skip, set later in web console")): "
    MODEL_NAME="$default_model"
    # printf -v (not eval) so keys containing quotes/backticks/$() are safe.
    printf -v "${key_var}" '%s' "$_api_key"
}

# Configure model. The "skip" choice leaves the model empty so the user can
# finish configuration in the web console after first start.
configure_model() {
    case "$model_choice" in
        1) read_model_config "DeepSeek" "deepseek-v4-flash" "DEEPSEEK_KEY" ;;
        2) read_model_config "Claude" "claude-opus-4-8" "CLAUDE_KEY" ;;
        3) read_model_config "Gemini" "gemini-3.1-pro-preview" "GEMINI_KEY" ;;
        4) read_model_config "OpenAI" "gpt-5.5" "OPENAI_KEY" ;;
        5) read_model_config "MiniMax" "MiniMax-M3" "MINIMAX_KEY" ;;
        6) read_model_config "GLM" "glm-5.1" "ZHIPU_KEY" ;;
        7) read_model_config "Qwen (DashScope)" "qwen3.7-plus" "DASHSCOPE_KEY" ;;
        8) read_model_config "Doubao (Volcengine Ark)" "doubao-seed-2-0-code-preview-260215" "ARK_KEY" ;;
        9) read_model_config "Kimi (Moonshot)" "kimi-k2.6" "MOONSHOT_KEY" ;;
        10) read_model_config "MiMo" "mimo-v2.5-pro" "MIMO_KEY" ;;
        11)
            # Show where to obtain a LinkAI key (zh users -> console page).
            echo -e "${CYAN}$(t "获取 LinkAI Key" "Get your LinkAI Key"): https://link-ai.tech/console/interface${NC}"
            read_model_config "LinkAI" "deepseek-v4-flash" "LINKAI_KEY"
            USE_LINKAI="true"
            ;;
        12)
            # Skip: leave model unset, will be configured in web console
            MODEL_SKIPPED="true"
            MODEL_NAME=""
            echo -e "${YELLOW}$(t "已跳过模型配置，稍后可在 Web 控制台填写" "Model configuration skipped, you can set it later in the web console")${NC}"
            ;;
    esac
}

# Channel label by stable key (independent of menu order).
channel_label() {
    case "$1" in
        web)           t "Web 网页控制台（推荐，开箱即用）" "Web Console (recommended, ready to use)" ;;
        weixin)        t "微信" "Wechat" ;;
        feishu)        t "飞书" "Feishu" ;;
        dingtalk)      t "钉钉" "DingTalk" ;;
        wecom_bot)     t "企微智能机器人" "WeCom Bot" ;;
        qq)            printf '%s' "QQ" ;;
        wechatcom_app) t "企微自建应用" "WeCom App" ;;
        telegram)      printf '%s' "Telegram" ;;
        slack)         printf '%s' "Slack" ;;
        discord)       printf '%s' "Discord" ;;
        skip)          t "⏭  跳过（稍后在 Web 控制台配置）" "⏭  Skip (configure later in the web console)" ;;
    esac
}

# Select channel. The display order depends on the install language:
#   - English: Web first, then the global IM channels (Telegram/Discord/Slack),
#     then the China-focused channels.
#   - Chinese: Web first, then China-focused channels, then global ones.
# A stable key list (CHANNEL_KEYS) decouples the menu order from the config
# logic, so reordering the menu never breaks configure_channel().
select_channel() {
    echo ""
    local title sel
    title="$(t "选择接入渠道" "Select Communication Channel")"
    if [ "$UI_LANG" = "en" ]; then
        CHANNEL_KEYS=(web telegram discord slack weixin feishu dingtalk wecom_bot qq wechatcom_app skip)
    else
        CHANNEL_KEYS=(web weixin feishu dingtalk wecom_bot qq wechatcom_app telegram slack discord skip)
    fi
    local labels=() k
    for k in "${CHANNEL_KEYS[@]}"; do
        labels+=("$(channel_label "$k")")
    done
    select_menu sel "$title" "${labels[@]}"
    # Map the 1-based menu position back to the stable channel key.
    channel_choice="${CHANNEL_KEYS[$((sel - 1))]}"
}

# Configure channel, dispatched by stable channel key (not menu position).
configure_channel() {
    case "$channel_choice" in
        web|skip)
            # Web (also the default when skipped). Use the default port with
            # no prompt; it can be changed later in the web console / config.
            CHANNEL_TYPE="web"
            WEB_PORT="9899"
            ACCESS_INFO="$(t "Web 控制台地址" "Web console") : http://localhost:9899/chat"
            ;;
        weixin)
            # Weixin
            CHANNEL_TYPE="weixin"
            ACCESS_INFO="$(t "微信渠道已配置，请在终端或 Web 控制台扫码登录" "Weixin channel configured. Scan QR code in terminal or web console to login.")"
            ;;
        feishu)
            # Feishu (WebSocket mode)
            CHANNEL_TYPE="feishu"
            echo -e "${GREEN}$(t "配置飞书（WebSocket 模式）" "Configure Feishu (WebSocket mode)")...${NC}"
            local fs_app_id fs_app_secret
            tty_read fs_app_id "$(t "请输入飞书 App ID" "Enter Feishu App ID"): "
            tty_read fs_app_secret "$(t "请输入飞书 App Secret" "Enter Feishu App Secret"): "
            FEISHU_APP_ID="$fs_app_id"
            FEISHU_APP_SECRET="$fs_app_secret"
            FEISHU_EVENT_MODE="websocket"
            ACCESS_INFO="$(t "飞书渠道已配置（WebSocket 模式）" "Feishu channel configured (WebSocket mode)")"
            ;;
        dingtalk)
            # DingTalk
            CHANNEL_TYPE="dingtalk"
            echo -e "${GREEN}$(t "配置钉钉" "Configure DingTalk")...${NC}"
            local dt_client_id dt_client_secret
            tty_read dt_client_id "$(t "请输入钉钉 Client ID" "Enter DingTalk Client ID"): "
            tty_read dt_client_secret "$(t "请输入钉钉 Client Secret" "Enter DingTalk Client Secret"): "
            DT_CLIENT_ID="$dt_client_id"
            DT_CLIENT_SECRET="$dt_client_secret"
            ACCESS_INFO="$(t "钉钉渠道已配置" "DingTalk channel configured")"
            ;;
        wecom_bot)
            # WeCom Bot
            CHANNEL_TYPE="wecom_bot"
            echo -e "${GREEN}$(t "配置企微智能机器人" "Configure WeCom Bot")...${NC}"
            local wecom_bot_id wecom_bot_secret
            tty_read wecom_bot_id "$(t "请输入 WeCom Bot ID" "Enter WeCom Bot ID"): "
            tty_read wecom_bot_secret "$(t "请输入 WeCom Bot Secret" "Enter WeCom Bot Secret"): "
            WECOM_BOT_ID="$wecom_bot_id"
            WECOM_BOT_SECRET="$wecom_bot_secret"
            ACCESS_INFO="$(t "企微智能机器人渠道已配置" "WeCom Bot channel configured")"
            ;;
        qq)
            # QQ
            CHANNEL_TYPE="qq"
            echo -e "${GREEN}$(t "配置 QQ 机器人" "Configure QQ Bot")...${NC}"
            local qq_app_id qq_app_secret
            tty_read qq_app_id "$(t "请输入 QQ App ID" "Enter QQ App ID"): "
            tty_read qq_app_secret "$(t "请输入 QQ App Secret" "Enter QQ App Secret"): "
            QQ_APP_ID="$qq_app_id"
            QQ_APP_SECRET="$qq_app_secret"
            ACCESS_INFO="$(t "QQ 机器人渠道已配置" "QQ Bot channel configured")"
            ;;
        wechatcom_app)
            # WeCom App
            CHANNEL_TYPE="wechatcom_app"
            echo -e "${GREEN}$(t "配置企微自建应用" "Configure WeCom App")...${NC}"
            local corp_id com_token com_secret com_agent_id com_aes_key com_port
            tty_read corp_id "$(t "请输入企业 Corp ID" "Enter WeChat Corp ID"): "
            tty_read com_token "$(t "请输入应用 Token" "Enter WeChat Com App Token"): "
            tty_read com_secret "$(t "请输入应用 Secret" "Enter WeChat Com App Secret"): "
            tty_read com_agent_id "$(t "请输入应用 Agent ID" "Enter WeChat Com App Agent ID"): "
            tty_read com_aes_key "$(t "请输入应用 AES Key" "Enter WeChat Com App AES Key"): "
            tty_read com_port "$(t "请输入应用端口" "Enter WeChat Com App Port") [$(t "默认" "default"): 9898]: "
            com_port=${com_port:-9898}
            WECHATCOM_CORP_ID="$corp_id"
            WECHATCOM_TOKEN="$com_token"
            WECHATCOM_SECRET="$com_secret"
            WECHATCOM_AGENT_ID="$com_agent_id"
            WECHATCOM_AES_KEY="$com_aes_key"
            WECHATCOM_PORT="$com_port"
            ACCESS_INFO="$(t "企微自建应用渠道已配置，端口" "WeCom App channel configured on port") ${com_port}"
            ;;
        telegram)
            # Telegram
            CHANNEL_TYPE="telegram"
            echo -e "${GREEN}$(t "配置 Telegram" "Configure Telegram")...${NC}"
            local tg_token
            tty_read tg_token "$(t "请输入 Telegram Bot Token" "Enter Telegram Bot Token"): "
            TELEGRAM_TOKEN="$tg_token"
            ACCESS_INFO="$(t "Telegram 渠道已配置" "Telegram channel configured")"
            ;;
        slack)
            # Slack
            CHANNEL_TYPE="slack"
            echo -e "${GREEN}$(t "配置 Slack" "Configure Slack")...${NC}"
            local slack_bot slack_app
            tty_read slack_bot "$(t "请输入 Slack Bot Token" "Enter Slack Bot Token") (xoxb-...): "
            tty_read slack_app "$(t "请输入 Slack App Token" "Enter Slack App Token") (xapp-...): "
            SLACK_BOT_TOKEN="$slack_bot"
            SLACK_APP_TOKEN="$slack_app"
            ACCESS_INFO="$(t "Slack 渠道已配置" "Slack channel configured")"
            ;;
        discord)
            # Discord
            CHANNEL_TYPE="discord"
            echo -e "${GREEN}$(t "配置 Discord" "Configure Discord")...${NC}"
            local discord_token
            tty_read discord_token "$(t "请输入 Discord Bot Token" "Enter Discord Bot Token"): "
            DISCORD_TOKEN="$discord_token"
            ACCESS_INFO="$(t "Discord 渠道已配置" "Discord channel configured")"
            ;;
    esac
}

# Generate config file
create_config_file() {
    echo -e "${GREEN}📝 $(t "正在生成 config.json" "Generating config.json")...${NC}"

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
    MIMO_KEY="${MIMO_KEY:-}" \
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
    TELEGRAM_TOKEN="${TELEGRAM_TOKEN:-}" \
    SLACK_BOT_TOKEN="${SLACK_BOT_TOKEN:-}" \
    SLACK_APP_TOKEN="${SLACK_APP_TOKEN:-}" \
    DISCORD_TOKEN="${DISCORD_TOKEN:-}" \
    COW_LANG="${INSTALL_LANG:-auto}" \
    $PYTHON_CMD -c "
import json, os
e = os.environ.get
base = {
    'channel_type': e('CHANNEL_TYPE') or 'web',
    'model': e('MODEL_NAME') or '',
    'cow_lang': e('COW_LANG', 'auto'),
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
    'mimo_api_key': e('MIMO_KEY', ''),
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
    'telegram': {'telegram_token': 'TELEGRAM_TOKEN'},
    'slack': {'slack_bot_token': 'SLACK_BOT_TOKEN', 'slack_app_token': 'SLACK_APP_TOKEN'},
    'discord': {'discord_token': 'DISCORD_TOKEN'},
}
def _to_int(val, default):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default
ch = e('CHANNEL_TYPE') or 'web'
for key, spec in channel_map.get(ch, {}).items():
    if isinstance(spec, tuple):
        env_name, conv = spec
        # Guard int() against non-numeric input; fall back to a sane port.
        base[key] = _to_int(e(env_name), 9899 if key == 'web_port' else 9898) if conv is int else conv(e(env_name))
    else:
        base[key] = e(spec, '')
with open('config.json', 'w') as f:
    json.dump(base, f, indent=2, ensure_ascii=False)
"

    echo -e "${GREEN}✅ $(t "配置文件创建成功" "Configuration file created successfully").${NC}"
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
    echo -e "${GREEN}${EMOJI_CHECK} $(t "CowAgent 已在后台运行" "CowAgent is now running in background")!${NC}"
    echo -e "${GREEN}${EMOJI_CHECK} $(t "关闭终端后进程仍会继续运行" "Process will continue after closing terminal").${NC}"
    echo -e "${CYAN}$ACCESS_INFO${NC}"

    # If the model was skipped, guide the user to finish setup in the web console.
    if [ "${MODEL_SKIPPED:-}" = "true" ]; then
        local _port="${WEB_PORT:-9899}"
        echo ""
        echo -e "${YELLOW}${EMOJI_WARN} $(t "尚未配置模型，请在 Web 控制台完成配置" "Model not configured yet, please finish setup in the web console"):${NC}"
        echo -e "${CYAN}   http://localhost:${_port}/chat${NC}"
    fi
    echo ""
    echo -e "${CYAN}${BOLD}$(t "管理命令" "Management Commands"):${NC}"
    if $USE_COW; then
        echo -e "  ${GREEN}cow stop${NC}       $(t "停止服务" "Stop the service")"
        echo -e "  ${GREEN}cow restart${NC}    $(t "重启服务" "Restart the service")"
        echo -e "  ${GREEN}cow status${NC}     $(t "查看状态" "Check status")"
        echo -e "  ${GREEN}cow logs${NC}       $(t "查看日志" "View logs")"
        echo -e "  ${GREEN}cow update${NC}     $(t "更新并重启" "Update and restart")"
        echo -e "  ${GREEN}cow install-browser${NC}  $(t "安装浏览器工具" "Install browser tool")"
    else
        echo -e "  ${GREEN}./run.sh stop${NC}       $(t "停止服务" "Stop the service")"
        echo -e "  ${GREEN}./run.sh restart${NC}    $(t "重启服务" "Restart the service")"
        echo -e "  ${GREEN}./run.sh status${NC}     $(t "查看状态" "Check status")"
        echo -e "  ${GREEN}./run.sh logs${NC}       $(t "查看日志" "View logs")"
        echo -e "  ${GREEN}./run.sh update${NC}     $(t "更新并重启" "Update and restart")"
    fi
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo ""

    echo -e "${YELLOW}$(t "显示最近日志（Ctrl+C 退出，Agent 继续运行）" "Showing recent logs (Ctrl+C to exit, agent keeps running)"):${NC}"
    sleep 2
    tail -n 30 -f "${BASE_DIR}/nohup.out"
}

# Show usage
show_usage() {
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo -e "${CYAN}${BOLD}   ${EMOJI_COW} CowAgent Management Script${NC}"
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo ""
    echo -e "${YELLOW}$(t "用法" "Usage"):${NC}"
    echo -e "  ${GREEN}./run.sh${NC}               ${CYAN}# $(t "安装/配置项目" "Install/Configure project")${NC}"
    echo -e "  ${GREEN}./run.sh <command>${NC}     ${CYAN}# $(t "执行管理命令" "Execute management command")${NC}"
    echo ""
    echo -e "${YELLOW}$(t "命令" "Commands"):${NC}"
    echo -e "  ${GREEN}start${NC}      $(t "启动服务" "Start the service")"
    echo -e "  ${GREEN}stop${NC}       $(t "停止服务" "Stop the service")"
    echo -e "  ${GREEN}restart${NC}    $(t "重启服务" "Restart the service")"
    echo -e "  ${GREEN}status${NC}     $(t "查看服务状态" "Check service status")"
    echo -e "  ${GREEN}logs${NC}       $(t "查看日志 (tail -f)" "View logs (tail -f)")"
    echo -e "  ${GREEN}config${NC}     $(t "重新配置项目" "Reconfigure project")"
    echo -e "  ${GREEN}update${NC}     $(t "更新并重启" "Update and restart")"
    echo ""
    echo -e "${YELLOW}$(t "示例" "Examples"):${NC}"
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
        echo -e "${RED}${EMOJI_CROSS} $(t "未找到 config.json" "config.json not found")${NC}"
        echo -e "${YELLOW}$(t "请先运行 './run.sh' 进行配置" "Please run './run.sh' to configure first")${NC}"
        exit 1
    fi

    if has_cow; then
        cd "${BASE_DIR}"
        cow start
    else
        if is_running; then
            echo -e "${YELLOW}${EMOJI_WARN} $(t "CowAgent 已在运行中" "CowAgent is already running") (PID: $(get_pid))${NC}"
            echo -e "${YELLOW}$(t "使用 './run.sh restart' 重启" "Use './run.sh restart' to restart")${NC}"
            return
        fi
        check_python_version
        start_project
    fi
}

# Stop service
cmd_stop() {
    # Don't let kill/return non-zero (e.g. process already gone) abort the
    # caller (cmd_restart) under `set -e`.
    set +e
    if has_cow; then
        cd "${BASE_DIR}"
        cow stop
    else
        echo -e "${GREEN}${EMOJI_STOP} $(t "正在停止 CowAgent" "Stopping CowAgent")...${NC}"

        if ! is_running; then
            echo -e "${YELLOW}${EMOJI_WARN} $(t "CowAgent 未在运行" "CowAgent is not running")${NC}"
            return 0
        fi

        pid=$(get_pid)
        if [ -z "$pid" ] || ! echo "$pid" | grep -qE '^[0-9]+$'; then
            echo -e "${RED}❌ $(t "获取有效 PID 失败" "Failed to get valid PID") (${pid})${NC}"
            return 0
        fi

        echo -e "${GREEN}$(t "找到运行中的进程" "Found running process") (PID: ${pid})${NC}"

        kill ${pid} 2>/dev/null || true
        sleep 3

        if ps -p ${pid} > /dev/null 2>&1; then
            echo -e "${YELLOW}⚠️  $(t "进程未停止，强制终止" "Process not stopped, forcing termination")...${NC}"
            kill -9 ${pid} 2>/dev/null || true
        fi

        echo -e "${GREEN}${EMOJI_CHECK} $(t "CowAgent 已停止" "CowAgent stopped")${NC}"
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
            echo -e "${GREEN}$(t "状态" "Status"):${NC} ✅ $(t "运行中" "Running")"
            echo -e "${GREEN}PID:${NC}    ${pid}"
            if [ -f "${BASE_DIR}/nohup.out" ]; then
                echo -e "${GREEN}$(t "日志" "Logs"):${NC}   ${BASE_DIR}/nohup.out"
            fi
        else
            echo -e "${YELLOW}$(t "状态" "Status"):${NC} ⭐ $(t "已停止" "Stopped")"
        fi

        if [ -f "${BASE_DIR}/config.json" ]; then
            # `|| true`: grep returns 1 when the key is absent (set -e safe).
            model=$(grep -o '"model"[[:space:]]*:[[:space:]]*"[^"]*"' "${BASE_DIR}/config.json" 2>/dev/null | cut -d'"' -f4 || true)
            channel=$(grep -o '"channel_type"[[:space:]]*:[[:space:]]*"[^"]*"' "${BASE_DIR}/config.json" 2>/dev/null | cut -d'"' -f4 || true)
            echo -e "${GREEN}$(t "模型" "Model"):${NC}  ${model:-$(t "（未配置）" "(not set)")}"
            echo -e "${GREEN}$(t "渠道" "Channel"):${NC} ${channel:-$(t "（未配置）" "(not set)")}"
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
            echo -e "${YELLOW}$(t "查看日志（Ctrl+C 退出）" "Viewing logs (Ctrl+C to exit)"):${NC}"
            tail -f "${BASE_DIR}/nohup.out"
        else
            echo -e "${RED}❌ $(t "日志文件未找到" "Log file not found"): ${BASE_DIR}/nohup.out${NC}"
        fi
    fi
}

# Reconfigure
cmd_config() {
    # Interactive flow: disable `set -e` (see install_mode for rationale).
    set +e
    # One shared terminal handle for all menus in this session.
    menu_session_begin

    # Choose language first so the rest of the flow is localized.
    select_language
    echo ""
    echo -e "${YELLOW}${EMOJI_WRENCH} $(t "正在重新配置 CowAgent" "Reconfiguring CowAgent")...${NC}"
    
    if [ -f "${BASE_DIR}/config.json" ]; then
        backup_file="${BASE_DIR}/config.json.backup.$(date +%s)"
        cp "${BASE_DIR}/config.json" "${backup_file}"
        echo -e "${GREEN}✅ $(t "已备份配置到" "Backed up config to"): ${backup_file}${NC}"
    fi
    
    check_python_version
    install_dependencies
    select_model
    configure_model
    select_channel
    configure_channel
    menu_session_end
    create_config_file
    
    echo ""
    local restart_now
    tty_read restart_now "$(t "现在重启服务" "Restart service now")? [Y/n]: "
    if [[ ! $restart_now == [Nn]* ]]; then
        cmd_restart
    fi
}

# Update project
cmd_update() {
    echo -e "${GREEN}${EMOJI_WRENCH} $(t "正在更新 CowAgent" "Updating CowAgent")...${NC}"
    cd "${BASE_DIR}"
    
    # Pull latest code first (service still running)
    local pull_ok=false
    if [ -d .git ]; then
        echo -e "${GREEN}🔄 $(t "正在拉取最新代码" "Pulling latest code")...${NC}"
        if git pull; then
            pull_ok=true
        else
            echo -e "${YELLOW}⚠️  $(t "git pull 失败，尝试 Gitee 镜像" "git pull failed, trying Gitee mirror")...${NC}"
            git remote set-url origin https://gitee.com/zhayujie/CowAgent.git
            if git pull; then
                pull_ok=true
            else
                echo -e "${RED}❌ $(t "拉取代码失败，更新已中止" "Failed to pull code. Update aborted").${NC}"
                exit 1
            fi
        fi
    else
        echo -e "${YELLOW}⚠️  $(t "非 git 仓库，跳过代码更新" "Not a git repository, skipping code update")${NC}"
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
    # Interactive flow: disable `set -e` so a single non-zero command (e.g. an
    # arithmetic `(( ))` evaluating to 0, a `read` hitting EOF, or an optional
    # step failing) does not silently abort the whole installer.
    set +e
    clear
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo -e "${CYAN}${BOLD}   ${EMOJI_COW} CowAgent Installation${NC}"
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo ""

    # Open one shared terminal handle for ALL menus in this session (language,
    # model, channel). One long-lived fd 3 avoids per-menu re-open issues on
    # bash 3.2. Closed on early return and before config generation.
    menu_session_begin

    # Step 0: choose the install/UI language. Everything after this is localized.
    select_language
    echo ""
    sleep 1

    if [ "$IS_PROJECT_DIR" = true ]; then
        echo -e "${GREEN}✅ $(t "检测到已有项目目录" "Detected existing project directory").${NC}"
        
        if [ -f "${BASE_DIR}/config.json" ]; then
            menu_session_end
            echo -e "${GREEN}✅ $(t "项目已配置" "Project already configured")${NC}"
            echo ""
            show_usage
            return
        fi
        
        echo -e "${YELLOW}📝 $(t "未找到 config.json，开始配置项目" "No config.json found. Let's configure your project")!${NC}"
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
    menu_session_end
    create_config_file
    
    # Auto-start after configuration for a true out-of-the-box experience.
    echo ""
    start_project
}

# Require running inside the project directory
require_project_dir() {
    if [ "$IS_PROJECT_DIR" = false ]; then
        echo -e "${RED}${EMOJI_CROSS} $(t "必须在项目目录下运行" "Must run in project directory")${NC}"
        exit 1
    fi
}

# Initialize UI_LANG for management commands: prefer cow_lang from an existing
# config.json, otherwise fall back to environment detection. The install flow
# overrides this later via select_language().
init_ui_lang() {
    [ -n "$UI_LANG" ] && return
    local cfg_lang=""
    if [ -f "${BASE_DIR}/config.json" ]; then
        # `|| true`: grep returns 1 when cow_lang is absent, which would abort
        # the whole script under `set -e` at the very first management command.
        cfg_lang=$(grep -o '"cow_lang"[[:space:]]*:[[:space:]]*"[^"]*"' "${BASE_DIR}/config.json" 2>/dev/null | cut -d'"' -f4 || true)
    fi
    case "$cfg_lang" in
        zh) UI_LANG="zh" ;;
        en) UI_LANG="en" ;;
        *) UI_LANG=$(detect_ui_lang) ;;
    esac
}

# Main function
main() {
    init_ui_lang

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
            echo -e "${RED}${EMOJI_CROSS} $(t "未知命令" "Unknown command"): $1${NC}"
            echo ""
            show_usage
            exit 1
            ;;
    esac
}

# Execute main function
main "$@"
