#Requires -Version 5.1
<#
.SYNOPSIS
    CowAgent installer & management script for Windows.
.DESCRIPTION
    One-liner install:
      irm https://cdn.link-ai.tech/code/cow/run.ps1 | iex
    Or from a local clone:
      .\scripts\run.ps1              # install / configure
      .\scripts\run.ps1 start        # start service  (delegates to cow CLI)
      .\scripts\run.ps1 stop|restart|status|logs|config|update|help
#>

param(
    [Parameter(Position = 0)]
    [string]$Command = ""
)

$ErrorActionPreference = "Stop"

# ── ensure UTF-8 everywhere on Windows ───────────────────────────
# Without this, Chinese text renders as mojibake (e.g. "éæ©") on Windows
# PowerShell 5.1, whose console defaults to the system ANSI code page (GBK on
# Chinese systems). Set the active code page AND the console encodings so both
# our output and any child process (git/python) speak UTF-8.
try { chcp 65001 | Out-Null } catch {}
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::InputEncoding  = [System.Text.Encoding]::UTF8
} catch {}
# $OutputEncoding controls how strings are piped to external programs.
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

# ── colours ──────────────────────────────────────────────────────
function Write-Cow   { param([string]$M) Write-Host $M -ForegroundColor Green  }
function Write-Warn  { param([string]$M) Write-Host $M -ForegroundColor Yellow }
function Write-Err   { param([string]$M) Write-Host $M -ForegroundColor Red    }
function Write-Info  { param([string]$M) Write-Host $M -ForegroundColor Cyan   }

# ── i18n: install-flow language ──────────────────────────────────
# $UiLang controls the language of install prompts/menus ("zh" or "en").
# Chosen by the user at the first step; defaults to environment detection
# for management commands (start/stop/...).
$script:UiLang = ""

# Detect default UI language from the OS culture (best-effort). Checks the
# display/UI culture first (closest to the user's chosen Windows language),
# then the regional format culture as a fallback. Any zh-* signal -> "zh".
function Get-DefaultUiLang {
    foreach ($getter in @({ (Get-UICulture).Name }, { (Get-Culture).Name })) {
        try {
            $name = & $getter
            if ($name -match '^zh') { return "zh" }
        } catch {}
    }
    return "en"
}

# Translation helper: T <zh> <en> -> string in the active UI language.
function T {
    param([string]$Zh, [string]$En)
    if ($script:UiLang -eq "en") { return $En } else { return $Zh }
}

# ── detect project directory ─────────────────────────────────────
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { $PWD.Path }
$BaseDir   = Split-Path $ScriptDir -Parent

$IsProjectDir = (Test-Path "$BaseDir\app.py") -and (Test-Path "$BaseDir\config-template.json")
if (-not $IsProjectDir) {
    $BaseDir = $PWD.Path
    $IsProjectDir = (Test-Path "$BaseDir\app.py") -and (Test-Path "$BaseDir\config-template.json")
}

# Initialize $UiLang for management commands: prefer cow_lang from an existing
# config.json, otherwise fall back to environment detection.
function Initialize-UiLang {
    if ($script:UiLang) { return }
    $cfgLang = ""
    if (Test-Path "$BaseDir\config.json") {
        try {
            $cfg = Get-Content "$BaseDir\config.json" -Raw | ConvertFrom-Json
            if ($cfg.cow_lang) { $cfgLang = "$($cfg.cow_lang)" }
        } catch {}
    }
    switch ($cfgLang) {
        "zh"    { $script:UiLang = "zh" }
        "en"    { $script:UiLang = "en" }
        default { $script:UiLang = Get-DefaultUiLang }
    }
}

# ── arrow-key selectable menu with number fallback ───────────────
# Usage: $idx = Select-Menu -Title "..." -Options @("a","b") [-Default 1]
# Returns the selected 1-based index.
function Select-Menu {
    param(
        [string]$Title,
        [string[]]$Options,
        [int]$Default = 1
    )
    $count = $Options.Count
    $cur = [Math]::Max(0, [Math]::Min($Default - 1, $count - 1))

    # Fallback to numbered input when there is no interactive console
    # (e.g. piped input, redirected host).
    $interactive = $true
    try {
        if ([Console]::IsInputRedirected) { $interactive = $false }
    } catch { $interactive = $false }

    if (-not $interactive) {
        Write-Info $Title
        for ($i = 0; $i -lt $count; $i++) {
            Write-Host ("  {0}) {1}" -f ($i + 1), $Options[$i])
        }
        do {
            $sel = Read-Host (T "请输入序号" "Enter number") 
            if (-not $sel) { $sel = "$($cur + 1)" }
        } while ($sel -notmatch '^\d+$' -or [int]$sel -lt 1 -or [int]$sel -gt $count)
        return [int]$sel
    }

    Write-Info $Title
    Write-Host (T "↑/↓ 选择，Enter 确认" "Use ↑/↓ to move, Enter to select") -ForegroundColor Cyan

    [Console]::CursorVisible = $false
    $firstDraw = $true
    try {
        while ($true) {
            if (-not $firstDraw) {
                # Move cursor up to the top of the option block to redraw it.
                $top = [Console]::CursorTop - $count
                if ($top -lt 0) { $top = 0 }
                [Console]::SetCursorPosition(0, $top)
            }
            $firstDraw = $false

            for ($i = 0; $i -lt $count; $i++) {
                # Clear the line first to avoid leftover characters.
                Write-Host (" " * ([Console]::WindowWidth - 1)) -NoNewline
                [Console]::SetCursorPosition(0, [Console]::CursorTop)
                if ($i -eq $cur) {
                    Write-Host ("  > " + $Options[$i]) -ForegroundColor Green
                } else {
                    Write-Host ("    " + $Options[$i])
                }
            }

            $key = [Console]::ReadKey($true)
            switch ($key.Key) {
                "UpArrow"   { $cur = (($cur - 1 + $count) % $count) }
                "DownArrow" { $cur = (($cur + 1) % $count) }
                "Enter"     { return ($cur + 1) }
                default {
                    # Number shortcut (1-9) jumps to that option and confirms.
                    $ch = $key.KeyChar
                    if ($ch -match '^[1-9]$') {
                        $n = [int]"$ch"
                        if ($n -ge 1 -and $n -le $count) { return $n }
                    }
                }
            }
        }
    } finally {
        [Console]::CursorVisible = $true
    }
}

# ── language selection (first step of install) ───────────────────
function Select-Language {
    # Order is fixed (English first, Chinese second). The default highlight
    # follows detection, but conservatively: only a confident "zh" signal
    # (a zh-* system culture) preselects Chinese; everything else defaults to
    # English. The menu hint shows in the detected language for familiarity.
    $detected = Get-DefaultUiLang
    if ($detected -eq "zh") {
        $default = 2
        $script:UiLang = "zh"
    } else {
        $default = 1
        $script:UiLang = "en"
    }

    $idx = Select-Menu -Title "Select Language / 选择语言" -Options @("English", "中文 (Chinese)") -Default $default
    switch ($idx) {
        1 { $script:UiLang = "en" }
        2 { $script:UiLang = "zh" }
        default { $script:UiLang = "en" }
    }
    $script:InstallLang = $script:UiLang
}

# ── Python detection ─────────────────────────────────────────────
function Find-Python {
    foreach ($cmd in @("python3", "python")) {
        $bin = Get-Command $cmd -ErrorAction SilentlyContinue
        if (-not $bin) { continue }
        try {
            $ver = & $bin.Source -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')" 2>$null
            $parts = $ver -split '\.'
            $major = [int]$parts[0]; $minor = [int]$parts[1]
            if ($major -eq 3 -and $minor -ge 9 -and $minor -le 13) {
                return $bin.Source
            }
        } catch {}
    }
    return $null
}

$PythonCmd = Find-Python
function Assert-Python {
    if (-not $PythonCmd) {
        Write-Err (T "未找到 Python 3.9-3.13，请从 https://www.python.org/downloads/ 安装" "Python 3.9-3.13 not found. Please install from https://www.python.org/downloads/")
        Read-Host (T "按回车退出" "Press Enter to exit")
        exit 1
    }
    Write-Cow ((T "找到 Python" "Found Python") + ": $PythonCmd")
}

# ── clone project ────────────────────────────────────────────────
function Install-Project {
    if (Test-Path "CowAgent") {
        # Auto-backup the existing directory without prompting.
        $backup = "CowAgent_backup_$(Get-Date -Format 'yyyyMMddHHmmss')"
        Rename-Item "CowAgent" $backup
        Write-Warn ((T "已存在 CowAgent 目录，已自动备份为" "Existing 'CowAgent' directory backed up to") + " '$backup'")
    }

    $gitBin = Get-Command git -ErrorAction SilentlyContinue
    if (-not $gitBin) {
        Write-Err (T "未找到 Git，请从 https://git-scm.com/download/win 安装" "Git not found. Please install from https://git-scm.com/download/win")
        Read-Host (T "按回车退出" "Press Enter to exit")
        exit 1
    }

    Write-Cow (T "正在克隆 CowAgent 项目..." "Cloning CowAgent project...")
    $cloneOk = $false

    # Test GitHub connectivity before attempting clone
    try {
        $null = Invoke-WebRequest -Uri "https://github.com" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        Write-Cow (T "GitHub 可达，正在从 GitHub 克隆..." "GitHub is reachable, cloning from GitHub...")
        $prevEAP = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        git clone --depth 10 --progress "https://github.com/zhayujie/CowAgent.git" 2>&1 | ForEach-Object { Write-Host $_ }
        if ($LASTEXITCODE -eq 0) { $cloneOk = $true }
        $ErrorActionPreference = $prevEAP
        if (-not $cloneOk) {
            if (Test-Path "CowAgent") { Remove-Item -Recurse -Force "CowAgent" }
        }
    } catch {}

    if (-not $cloneOk) {
        Write-Warn (T "GitHub 克隆失败或超时，切换到 Gitee 镜像..." "GitHub clone failed or timed out, switching to Gitee mirror...")
        $prevEAP = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        git clone --depth 10 --progress "https://gitee.com/zhayujie/CowAgent.git" 2>&1 | ForEach-Object { Write-Host $_ }
        if ($LASTEXITCODE -eq 0) { $cloneOk = $true }
        $ErrorActionPreference = $prevEAP
        if (-not $cloneOk) {
            if (Test-Path "CowAgent") { Remove-Item -Recurse -Force "CowAgent" }
        }
    }

    if (-not $cloneOk) {
        Write-Err (T "GitHub 和 Gitee 均克隆失败，请检查网络连接。" "Clone failed from both GitHub and Gitee. Please check your network connection.")
        Write-Err (T "你也可以手动克隆: git clone https://gitee.com/zhayujie/CowAgent.git" "You can also manually clone: git clone https://gitee.com/zhayujie/CowAgent.git")
        Read-Host (T "按回车退出" "Press Enter to exit")
        exit 1
    }

    Set-Location "CowAgent"
    $script:BaseDir = $PWD.Path
    $script:IsProjectDir = $true
    Write-Cow ((T "项目已克隆" "Project cloned") + ": $BaseDir")
}

# Test whether a URL is reachable within a short timeout. Uses a HEAD request
# and hides progress so it never blocks the UI for long. Any failure (DNS, TLS,
# timeout) just returns $false so the caller falls back gracefully.
function Test-UrlReachable {
    param([string]$Url, [int]$TimeoutSec = 4)
    $oldPP = $ProgressPreference; $ProgressPreference = "SilentlyContinue"
    try {
        $null = Invoke-WebRequest -Uri $Url -Method Head -UseBasicParsing -TimeoutSec $TimeoutSec -ErrorAction Stop
        return $true
    } catch {
        return $false
    } finally {
        $ProgressPreference = $oldPP
    }
}

# Pick the pip index by install language, with the other as fallback:
#   - zh users: Tsinghua mirror first, official PyPI fallback
#   - others : official PyPI first, Tsinghua mirror fallback
# Returns an args array to splat into pip (empty = pip default / official PyPI).
function Get-PipMirrorArgs {
    $tuna = "https://pypi.tuna.tsinghua.edu.cn/simple"
    $pypi = "https://pypi.org/simple"
    if ($script:UiLang -eq "zh") {
        if (Test-UrlReachable "$tuna/") {
            Write-Warn ((T "使用 pip 镜像" "Using pip mirror") + ": $tuna")
            return @("-i", $tuna)
        }
    } else {
        if ((-not (Test-UrlReachable "$pypi/")) -and (Test-UrlReachable "$tuna/")) {
            Write-Warn ((T "使用 pip 镜像" "Using pip mirror") + ": $tuna")
            return @("-i", $tuna)
        }
    }
    return @()
}

# ── install dependencies ─────────────────────────────────────────
function Install-Dependencies {
    Write-Cow (T "正在安装依赖..." "Installing dependencies...")

    # Probe the mirror first (with progress hidden so the slow IWR call doesn't
    # leave the screen blank for too long).
    $oldPP = $ProgressPreference; $ProgressPreference = "SilentlyContinue"
    $pipMirror = Get-PipMirrorArgs
    $ProgressPreference = $oldPP

    # Keep pip output VISIBLE (do not pipe to Out-Null): on slow networks the
    # download can take minutes, and a silent step looks like a hang.
    $prevEAP = $ErrorActionPreference; $ErrorActionPreference = "Continue"

    Write-Info (T "正在升级 pip 等基础工具..." "Upgrading pip and basic tools...")
    & $PythonCmd -m pip install --upgrade pip setuptools wheel @pipMirror

    Write-Info (T "正在安装项目依赖（可能需要几分钟）..." "Installing project dependencies (may take a few minutes)...")
    & $PythonCmd -m pip install -r "$BaseDir\requirements.txt" @pipMirror
    $pipExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEAP
    if ($pipExit -ne 0) {
        Write-Warn (T "部分依赖可能有问题，但继续安装..." "Some dependencies may have issues, but continuing...")
    }

    Write-Cow (T "正在注册 cow CLI..." "Registering cow CLI...")
    $prevEAP = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & $PythonCmd -m pip install -e $BaseDir @pipMirror 2>&1 | Out-Null
    $ErrorActionPreference = $prevEAP

    # Ensure Python Scripts dir is in PATH for this session
    $scriptsDir = & $PythonCmd -c "import sysconfig; print(sysconfig.get_path('scripts'))" 2>$null
    if ($scriptsDir -and (Test-Path $scriptsDir)) {
        if ($env:PATH -notlike "*$scriptsDir*") {
            $env:PATH = "$scriptsDir;$env:PATH"
        }
    }

    $cowBin = Get-Command cow -ErrorAction SilentlyContinue
    if ($cowBin) {
        Write-Cow ((T "cow CLI 注册成功" "cow CLI registered") + ": $($cowBin.Source)")
    } else {
        Write-Warn ((T "cow CLI 不在 PATH 中，你可以使用" "cow CLI not in PATH. You can use") + ": $PythonCmd -m cli.cli")
        Write-Warn (T "如需永久修复，请将 Python Scripts 目录加入系统 PATH。" "To fix permanently, add Python Scripts directory to your system PATH.")
    }
}

# ── model selection ──────────────────────────────────────────────
# Order mirrors run.sh: DeepSeek, Claude, Gemini, OpenAI, MiniMax, Zhipu,
# Qwen, Doubao, Kimi, LinkAI, then Skip (11th option).
# Each entry: Provider / default model name / config key field / optional base.
$ModelChoices = @{
    1  = @{ Provider = "DeepSeek";                Default = "deepseek-v4-flash";                   Field = "deepseek_api_key" }
    2  = @{ Provider = "Claude";                  Default = "claude-opus-4-8";                     Field = "claude_api_key";    BaseField = "claude_api_base" }
    3  = @{ Provider = "Gemini";                  Default = "gemini-3.1-pro-preview";              Field = "gemini_api_key";    BaseField = "gemini_api_base" }
    4  = @{ Provider = "OpenAI";                  Default = "gpt-5.5";                             Field = "open_ai_api_key";   BaseField = "open_ai_api_base" }
    5  = @{ Provider = "MiniMax";                 Default = "MiniMax-M3";                          Field = "minimax_api_key" }
    6  = @{ Provider = "GLM";                     Default = "glm-5.1";                             Field = "zhipu_ai_api_key" }
    7  = @{ Provider = "Qwen (DashScope)";        Default = "qwen3.7-plus";                        Field = "dashscope_api_key" }
    8  = @{ Provider = "Doubao (Volcengine Ark)"; Default = "doubao-seed-2-0-code-preview-260215"; Field = "ark_api_key" }
    9  = @{ Provider = "Kimi (Moonshot)";         Default = "kimi-k2.6";                           Field = "moonshot_api_key" }
    10 = @{ Provider = "MiMo";                    Default = "mimo-v2.5-pro";                       Field = "mimo_api_key" }
    11 = @{ Provider = "LinkAI";                  Default = "deepseek-v4-flash";                   Field = "linkai_api_key";    Linkai = $true }
}

function Select-Model {
    Write-Host ""
    $title = T "选择 AI 模型" "Select AI Model"
    $options = @(
        "DeepSeek (deepseek-v4-flash, deepseek-v4-pro, etc.)",
        "Claude (claude-opus-4-8, claude-opus-4-7, etc.)",
        "Gemini (gemini-3.5-flash, gemini-3.1-pro-preview, etc.)",
        "OpenAI (gpt-5.5, etc.)",
        "MiniMax (MiniMax-M3, etc.)",
        "GLM (glm-5.1, etc.)",
        "Qwen (qwen3.7-plus, qwen3.7-max, etc.)",
        "Doubao (doubao-seed-2.0, etc.)",
        "Kimi (kimi-k2.6, etc.)",
        "MiMo (mimo-v2.5-pro, etc.)",
        ("LinkAI (" + (T "一个 Key 接入所有模型" "access all models via one API") + ")"),
        (T "⏭  跳过（稍后在 Web 控制台配置）" "⏭  Skip (configure later in the web console)")
    )
    $script:ModelChoice = Select-Menu -Title $title -Options $options -Default 1
}

# Configure model. Only ask for the API key; model name and base default to
# sensible values and can be changed later in the web console.
function Configure-Model {
    # Reset model-related state
    $script:ModelName    = ""
    $script:ModelField   = ""
    $script:ApiKey       = ""
    $script:ApiBase      = ""
    $script:ApiBaseField = ""
    $script:UseLinkai    = $false

    if ($script:ModelChoice -eq 12) {
        # Skip: leave model unset, will be configured in the web console.
        Write-Warn (T "已跳过模型配置，稍后可在 Web 控制台填写" "Model configuration skipped, you can set it later in the web console")
        return
    }

    $m = $ModelChoices[$script:ModelChoice]
    Write-Cow ((T "正在配置" "Configuring") + " $($m.Provider)...")
    # Show where to obtain a LinkAI key.
    if ($m.Linkai) {
        Write-Info ((T "获取 LinkAI Key" "Get your LinkAI Key") + ": https://link-ai.tech/console/interface")
    }
    $hint = T "回车跳过，稍后在 Web 控制台填写" "press Enter to skip, set later in web console"
    $script:ApiKey     = Read-Host ((T "请输入" "Enter") + " $($m.Provider) API Key ($hint)")
    $script:ModelName  = $m.Default
    $script:ModelField = $m.Field
    if ($m.BaseField) { $script:ApiBaseField = $m.BaseField }
    if ($m.Linkai)    { $script:UseLinkai = $true }
}

# ── channel selection ────────────────────────────────────────────
# Channel label by stable key (independent of menu order).
function Get-ChannelLabel {
    param([string]$Key)
    switch ($Key) {
        "web"           { return (T "Web 网页控制台（推荐，开箱即用）" "Web Console (recommended, ready to use)") }
        "weixin"        { return (T "微信 Weixin" "Wechat") }
        "feishu"        { return (T "飞书 Feishu" "Feishu") }
        "dingtalk"      { return (T "钉钉 DingTalk" "DingTalk") }
        "wecom_bot"     { return (T "企微智能机器人 WeCom Bot" "WeCom Bot") }
        "qq"            { return "QQ" }
        "wechatcom_app" { return (T "企微自建应用 WeCom App" "WeCom App") }
        "telegram"      { return "Telegram" }
        "slack"         { return "Slack" }
        "discord"       { return "Discord" }
        "skip"          { return (T "⏭  跳过（稍后在 Web 控制台配置）" "⏭  Skip (configure later in the web console)") }
    }
}

# Select channel. The display order depends on the install language:
#   - English: Web first, then the global IM channels (Telegram/Discord/Slack),
#     then the China-focused channels.
#   - Chinese: Web first, then China-focused channels, then global ones.
# A stable key list decouples the menu order from the config logic.
function Select-Channel {
    Write-Host ""
    $title = T "选择接入渠道" "Select Communication Channel"
    if ($script:UiLang -eq "en") {
        $script:ChannelKeys = @("web", "telegram", "discord", "slack", "weixin", "feishu", "dingtalk", "wecom_bot", "qq", "wechatcom_app", "skip")
    } else {
        $script:ChannelKeys = @("web", "weixin", "feishu", "dingtalk", "wecom_bot", "qq", "wechatcom_app", "telegram", "slack", "discord", "skip")
    }
    $options = @($script:ChannelKeys | ForEach-Object { Get-ChannelLabel $_ })
    $idx = Select-Menu -Title $title -Options $options -Default 1
    # Map the 1-based menu position back to the stable channel key.
    $script:ChannelChoice = $script:ChannelKeys[$idx - 1]
}

# Configure channel, dispatched by stable channel key (not menu position).
function Configure-Channel {
    $script:ChannelExtra = @{}
    $script:AccessInfo = ""

    switch ($script:ChannelChoice) {
        { $_ -eq "web" -or $_ -eq "skip" } {
            # Web (also the default when skipped). Default port, no prompt.
            $script:ChannelType = "web"
            $script:ChannelExtra["web_port"] = 9899
            $script:AccessInfo = (T "Web 控制台地址" "Web console") + " : http://localhost:9899/chat"
        }
        "weixin" {
            $script:ChannelType = "weixin"
            $script:AccessInfo = T "微信渠道已配置，请在终端或 Web 控制台扫码登录" "Weixin channel configured. Scan QR code in terminal or web console to login."
        }
        "feishu" {
            $script:ChannelType = "feishu"
            Write-Cow (T "配置飞书（WebSocket 模式）..." "Configure Feishu (WebSocket mode)...")
            $script:ChannelExtra["feishu_app_id"]     = Read-Host (T "请输入飞书 App ID" "Enter Feishu App ID")
            $script:ChannelExtra["feishu_app_secret"] = Read-Host (T "请输入飞书 App Secret" "Enter Feishu App Secret")
            $script:ChannelExtra["feishu_event_mode"] = "websocket"
            $script:AccessInfo = T "飞书渠道已配置（WebSocket 模式）" "Feishu channel configured (WebSocket mode)"
        }
        "dingtalk" {
            $script:ChannelType = "dingtalk"
            Write-Cow (T "配置钉钉..." "Configure DingTalk...")
            $script:ChannelExtra["dingtalk_client_id"]     = Read-Host (T "请输入钉钉 Client ID" "Enter DingTalk Client ID")
            $script:ChannelExtra["dingtalk_client_secret"] = Read-Host (T "请输入钉钉 Client Secret" "Enter DingTalk Client Secret")
            $script:AccessInfo = T "钉钉渠道已配置" "DingTalk channel configured"
        }
        "wecom_bot" {
            $script:ChannelType = "wecom_bot"
            Write-Cow (T "配置企微智能机器人..." "Configure WeCom Bot...")
            $script:ChannelExtra["wecom_bot_id"]     = Read-Host (T "请输入 WeCom Bot ID" "Enter WeCom Bot ID")
            $script:ChannelExtra["wecom_bot_secret"] = Read-Host (T "请输入 WeCom Bot Secret" "Enter WeCom Bot Secret")
            $script:AccessInfo = T "企微智能机器人渠道已配置" "WeCom Bot channel configured"
        }
        "qq" {
            $script:ChannelType = "qq"
            Write-Cow (T "配置 QQ 机器人..." "Configure QQ Bot...")
            $script:ChannelExtra["qq_app_id"]     = Read-Host (T "请输入 QQ App ID" "Enter QQ App ID")
            $script:ChannelExtra["qq_app_secret"] = Read-Host (T "请输入 QQ App Secret" "Enter QQ App Secret")
            $script:AccessInfo = T "QQ 机器人渠道已配置" "QQ Bot channel configured"
        }
        "wechatcom_app" {
            $script:ChannelType = "wechatcom_app"
            Write-Cow (T "配置企微自建应用..." "Configure WeCom App...")
            $script:ChannelExtra["wechatcom_corp_id"]     = Read-Host (T "请输入企业 Corp ID" "Enter WeChat Corp ID")
            $script:ChannelExtra["wechatcomapp_token"]    = Read-Host (T "请输入应用 Token" "Enter WeChat Com App Token")
            $script:ChannelExtra["wechatcomapp_secret"]   = Read-Host (T "请输入应用 Secret" "Enter WeChat Com App Secret")
            $script:ChannelExtra["wechatcomapp_agent_id"] = Read-Host (T "请输入应用 Agent ID" "Enter WeChat Com App Agent ID")
            $script:ChannelExtra["wechatcomapp_aes_key"]  = Read-Host (T "请输入应用 AES Key" "Enter WeChat Com App AES Key")
            $port = Read-Host ((T "请输入应用端口" "Enter port") + " [" + (T "默认" "default") + ": 9898]")
            if (-not ($port -match '^\d+$')) { $port = "9898" }
            $script:ChannelExtra["wechatcomapp_port"] = [int]$port
            $script:AccessInfo = (T "企微自建应用渠道已配置，端口" "WeCom App channel configured on port") + " $port"
        }
        "telegram" {
            $script:ChannelType = "telegram"
            Write-Cow (T "配置 Telegram..." "Configure Telegram...")
            $script:ChannelExtra["telegram_token"] = Read-Host (T "请输入 Telegram Bot Token" "Enter Telegram Bot Token")
            $script:AccessInfo = T "Telegram 渠道已配置" "Telegram channel configured"
        }
        "slack" {
            $script:ChannelType = "slack"
            Write-Cow (T "配置 Slack..." "Configure Slack...")
            $script:ChannelExtra["slack_bot_token"] = Read-Host ((T "请输入 Slack Bot Token" "Enter Slack Bot Token") + " (xoxb-...)")
            $script:ChannelExtra["slack_app_token"] = Read-Host ((T "请输入 Slack App Token" "Enter Slack App Token") + " (xapp-...)")
            $script:AccessInfo = T "Slack 渠道已配置" "Slack channel configured"
        }
        "discord" {
            $script:ChannelType = "discord"
            Write-Cow (T "配置 Discord..." "Configure Discord...")
            $script:ChannelExtra["discord_token"] = Read-Host (T "请输入 Discord Bot Token" "Enter Discord Bot Token")
            $script:AccessInfo = T "Discord 渠道已配置" "Discord channel configured"
        }
    }
}

# ── generate config.json ─────────────────────────────────────────
function New-ConfigFile {
    Write-Cow (T "正在生成 config.json..." "Generating config.json...")

    $config = [ordered]@{
        channel_type              = if ($script:ChannelType) { $script:ChannelType } else { "web" }
        model                     = if ($script:ModelName)  { $script:ModelName }  else { "" }
        cow_lang                  = if ($script:InstallLang) { $script:InstallLang } else { "auto" }
        open_ai_api_key           = ""
        open_ai_api_base          = "https://api.openai.com/v1"
        claude_api_key            = ""
        claude_api_base           = "https://api.anthropic.com/v1"
        gemini_api_key            = ""
        gemini_api_base           = "https://generativelanguage.googleapis.com"
        zhipu_ai_api_key          = ""
        moonshot_api_key          = ""
        ark_api_key               = ""
        dashscope_api_key         = ""
        minimax_api_key           = ""
        mimo_api_key              = ""
        deepseek_api_key          = ""
        deepseek_api_base         = "https://api.deepseek.com/v1"
        voice_to_text             = "openai"
        text_to_voice             = "openai"
        voice_reply_voice         = $false
        speech_recognition        = $true
        group_speech_recognition  = $false
        use_linkai                = [bool]$script:UseLinkai
        linkai_api_key            = ""
        linkai_app_code           = ""
        agent                     = $true
        agent_max_context_tokens  = 40000
        agent_max_context_turns   = 30
        agent_max_steps           = 15
    }

    # Set the API key into the right field (skipped models leave it empty).
    if ($script:ModelField -and $config.Contains($script:ModelField)) {
        $config[$script:ModelField] = $script:ApiKey
    }
    # Set API base if the model has a configurable base and the user changed it.
    if ($script:ApiBase -and $script:ApiBaseField -and $config.Contains($script:ApiBaseField)) {
        $config[$script:ApiBaseField] = $script:ApiBase
    }

    # Merge channel-specific fields
    foreach ($k in $script:ChannelExtra.Keys) {
        $config[$k] = $script:ChannelExtra[$k]
    }

    $jsonText = $config | ConvertTo-Json -Depth 5
    [System.IO.File]::WriteAllText("$BaseDir\config.json", $jsonText, (New-Object System.Text.UTF8Encoding $false))
    Write-Cow (T "配置文件创建成功。" "Configuration file created.")
}

# ── start via cow CLI ─────────────────────────────────────────────
function Start-CowAgent {
    Write-Cow (T "正在启动 CowAgent..." "Starting CowAgent...")
    $cowBin = Get-Command cow -ErrorAction SilentlyContinue
    if ($cowBin) {
        & cow start
    } else {
        Write-Warn (T "未找到 cow CLI，直接启动..." "cow CLI not found, starting directly...")
        & $PythonCmd "$BaseDir\app.py"
    }
}

# ── delegate management commands to cow CLI ──────────────────────
function Invoke-CowCommand {
    param([string]$Cmd)
    $cowBin = Get-Command cow -ErrorAction SilentlyContinue
    if ($cowBin) {
        & cow $Cmd
    } else {
        Write-Err (T "未找到 cow CLI，请先不带参数运行本脚本进行安装。" "cow CLI not found. Run this script without arguments first to install.")
        exit 1
    }
}

# ── usage ─────────────────────────────────────────────────────────
function Show-Usage {
    Write-Info "========================================="
    Write-Info "   CowAgent Management Script (Windows)"
    Write-Info "========================================="
    Write-Host ""
    Write-Host (T "用法:" "Usage:")
    Write-Host ("  .\run.ps1               # " + (T "安装 / 配置" "Install / Configure"))
    Write-Host ("  .\run.ps1 <command>     # " + (T "管理命令" "Management command"))
    Write-Host ""
    Write-Host (T "命令:" "Commands:")
    Write-Host ("  start      " + (T "启动服务" "Start the service"))
    Write-Host ("  stop       " + (T "停止服务" "Stop the service"))
    Write-Host ("  restart    " + (T "重启服务" "Restart the service"))
    Write-Host ("  status     " + (T "查看状态" "Check service status"))
    Write-Host ("  logs       " + (T "查看日志" "View logs"))
    Write-Host ("  config     " + (T "重新配置项目" "Reconfigure project"))
    Write-Host ("  update     " + (T "更新并重启" "Update and restart"))
    Write-Host ("  help       " + (T "显示本帮助" "Show this message"))
    Write-Host ""
}

# ── install mode ──────────────────────────────────────────────────
function Install-Mode {
    Clear-Host
    Write-Info "========================================="
    Write-Info "   CowAgent Installation (Windows)"
    Write-Info "========================================="
    Write-Host ""

    # Step 0: choose the install/UI language. Everything after this is localized.
    Select-Language
    Write-Host ""

    if ($IsProjectDir) {
        Write-Cow (T "检测到已有项目目录。" "Detected existing project directory.")
        if (Test-Path "$BaseDir\config.json") {
            Write-Cow (T "项目已配置。" "Project already configured.")
            Write-Host ""
            Show-Usage
            return
        }
        Write-Warn (T "未找到 config.json，开始配置项目！" "No config.json found. Let's configure your project!")
        Write-Host ""
        Assert-Python
    } else {
        Assert-Python
        Install-Project
    }

    Install-Dependencies
    Select-Model
    Configure-Model
    Select-Channel
    Configure-Channel
    New-ConfigFile

    # Auto-start after configuration for a true out-of-the-box experience.
    Write-Host ""
    if ($script:AccessInfo) { Write-Cow $script:AccessInfo }
    Start-CowAgent
}

# ── update ────────────────────────────────────────────────────────
function Update-Project {
    Write-Cow (T "正在更新 CowAgent..." "Updating CowAgent...")
    Set-Location $BaseDir

    # Stop if running
    $cowBin = Get-Command cow -ErrorAction SilentlyContinue
    if ($cowBin) {
        $prevEAP = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        & cow stop 2>&1 | Out-Null
        $ErrorActionPreference = $prevEAP
    }

    if (Test-Path "$BaseDir\.git") {
        Write-Cow (T "正在拉取最新代码..." "Pulling latest code...")
        $prevEAP = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        git pull 2>&1 | Out-Null
        $pullExit = $LASTEXITCODE
        $ErrorActionPreference = $prevEAP
        if ($pullExit -ne 0) {
            Write-Warn (T "GitHub 拉取失败，尝试 Gitee..." "GitHub failed, trying Gitee...")
            $ErrorActionPreference = "Continue"
            git remote set-url origin https://gitee.com/zhayujie/CowAgent.git 2>&1 | Out-Null
            git pull 2>&1 | Out-Null
            $ErrorActionPreference = $prevEAP
        }
    } else {
        Write-Warn (T "非 git 仓库，跳过代码更新。" "Not a git repository, skipping code update.")
    }

    Assert-Python
    Install-Dependencies

    # Start via python -m cli.cli instead of cow.exe, because the exe may
    # still be cached/locked from the previous installation on Windows.
    Write-Cow (T "正在启动 CowAgent..." "Starting CowAgent...")
    & $PythonCmd -m cli.cli start
}

# ── main ──────────────────────────────────────────────────────────
Initialize-UiLang

switch ($Command.ToLower()) {
    ""        { Install-Mode }
    "start"   { Invoke-CowCommand "start" }
    "stop"    { Invoke-CowCommand "stop" }
    "restart" { Invoke-CowCommand "restart" }
    "status"  { Invoke-CowCommand "status" }
    "logs"    { Invoke-CowCommand "logs" }
    "config"  {
        Assert-Python
        Install-Dependencies
        Select-Model
        Configure-Model
        Select-Channel
        Configure-Channel
        New-ConfigFile
        $r = Read-Host (T "现在重启服务吗？[Y/n]" "Restart service now? [Y/n]")
        if ($r -ne "n" -and $r -ne "N") { Invoke-CowCommand "restart" }
    }
    "update"  { Update-Project }
    "help"    { Show-Usage }
    default   {
        Write-Err ((T "未知命令" "Unknown command") + ": $Command")
        Show-Usage
        exit 1
    }
}
