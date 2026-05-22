<p align="center"><img src= "https://github.com/user-attachments/assets/eca9a9ec-8534-4615-9e0f-96c5ac1d10a3" alt="CowAgent" width="550" /></p>

<p align="center">
  <a href="https://github.com/zhayujie/CowAgent/releases/latest"><img src="https://img.shields.io/github/v/release/zhayujie/CowAgent" alt="Latest release"></a>
  <a href="https://github.com/zhayujie/CowAgent/blob/master/LICENSE"><img src="https://img.shields.io/github/license/zhayujie/CowAgent" alt="License: MIT"></a>
  <a href="https://github.com/zhayujie/CowAgent"><img src="https://img.shields.io/github/stars/zhayujie/CowAgent?style=flat-square" alt="Stars"></a> <br/>
  [中文] | [<a href="docs/en/README.md">English</a>] | [<a href="docs/ja/README.md">日本語</a>]
</p>

**CowAgent** 是基于大模型的超级 AI 助理，能够主动思考和任务规划、操作计算机和外部资源、创造和执行 Skills、拥有长期记忆和知识库并不断成长，比 OpenClaw 更轻量和便捷。CowAgent 支持灵活切换多种模型，能处理文本、语音、图片、文件等多模态消息，可接入微信、飞书、钉钉、企微智能机器人、QQ、企微自建应用、微信公众号、网页中使用，7*24小时运行于你的个人电脑或服务器中。

<p align="center">
  <a href="https://cowagent.ai/">🌐 官网</a> &nbsp;·&nbsp;
  <a href="https://docs.cowagent.ai/">📖 文档中心</a> &nbsp;·&nbsp;
  <a href="https://docs.cowagent.ai/guide/quick-start">🚀 快速开始</a> &nbsp;·&nbsp;
  <a href="https://skills.cowagent.ai/">🧩 技能广场</a> &nbsp;·&nbsp;
  <a href="https://link-ai.tech/cowagent/create">☁️ 在线体验</a>
</p>


# 简介

> 该项目既是一个可以开箱即用的超级 AI 助理，也是一个支持高扩展的 Agent 框架，可以通过为项目扩展大模型接口、接入渠道、内置工具、Skills 系统来灵活实现各种定制需求。核心能力如下：

-  ✅  **自主任务规划**：能够理解复杂任务并自主规划执行，持续思考和调用工具直到完成目标
-  ✅  **长期记忆：** 自动将对话记忆持久化至本地文件和数据库中，包括核心记忆、日级记忆和梦境蒸馏，支持关键词及向量检索
-  ✅  **个人知识库：** 自动整理结构化知识，通过交叉引用构建知识图谱，支持通过对话管理和可视化浏览知识库
-  ✅  **技能系统：** Skills 安装和运行的引擎，支持从 [Skill Hub](https://skills.cowagent.ai/)、GitHub 等一键安装技能，或通过对话创造 Skills
-  ✅  **工具系统：** 内置文件读写、终端执行、浏览器操作、定时任务等工具，支持 MCP 协议，通过 Agent 自主调用完成复杂任务
-  ✅  **CLI系统：** 提供终端命令和对话命令，支持进程管理、技能安装、配置修改等操作
-  ✅  **多模态消息：** 支持对文本、图片、语音、文件等多类型消息进行解析、处理、生成、发送等操作
-  ✅  **多模型支持：** 支持 DeepSeek、MiniMax、Claude、Gemini、OpenAI、GLM、Qwen、Doubao、Kimi 等国内外主流模型厂商
-  ✅  **多通道接入：** 支持运行在本地计算机或服务器，可集成到微信、飞书、钉钉、企业微信、QQ、微信公众号、网页中使用

## 声明

1. 本项目遵循 [MIT 开源协议](/LICENSE)，主要用于技术研究和学习，使用本项目时需遵守所在地法律法规、相关政策以及企业章程，禁止用于任何违法或侵犯他人权益的行为。任何个人、团队和企业，无论以何种方式使用该项目、对何对象提供服务，所产生的一切后果，本项目均不承担任何责任。
2. 成本与安全：Agent 模式下 Token 使用量高于普通对话模式，请根据效果及成本综合选择模型。Agent 具有访问所在操作系统的能力，请谨慎选择项目部署环境。同时项目也会持续升级安全机制、并降低模型消耗成本。
3. CowAgent 项目专注于开源技术开发，不会参与、授权或发行任何加密货币。

## 演示

- 使用说明( Agent 模式)：[CowAgent 介绍](https://docs.cowagent.ai/intro/features)

- 免部署在线体验：[CowAgent](https://link-ai.tech/cowagent/create)

- DEMO 视频(对话模式)：https://cdn.link-ai.tech/doc/cow_demo.mp4

## 社区

添加小助手微信加入开源项目交流群：

<img width="140" src="https://img-1317903499.cos.ap-guangzhou.myqcloud.com/docs/open-community.png">

<br/>

# 企业服务

<a href="https://link-ai.tech" target="_blank"><img width="650" src="https://cdn.link-ai.tech/image/link-ai-intro.jpg"></a>

> [LinkAI](https://link-ai.tech/) 是面向企业和个人的一站式 AI 智能体平台，聚合多模态大模型、知识库、技能、工作流等能力，支持一键接入主流平台并管理，支持 SaaS、私有化部署等多种模式，可免部署在线运行[CowAgent 助理](https://link-ai.tech/cowagent/create)。
>
> LinkAI 目前已在智能客服、私域运营、企业效率助手等场景积累了丰富的 AI 解决方案，在消费、健康、文教、科技制造等各行业沉淀了大模型落地应用的最佳实践，致力于帮助更多企业和开发者拥抱 AI 生产力。

**产品咨询和企业服务** 可联系产品客服：

<img width="150" src="https://cdn.link-ai.tech/portal/linkai-customer-service.png">

<br/>

# 🏷 更新日志

>**2026.05.06：** [2.0.8版本](https://github.com/zhayujie/CowAgent/releases/tag/2.0.8)，飞书渠道全面升级（语音、流式输出和Markdown、一键扫码接入）、新模型支持（DeepSeek V4、百度千帆）、定时任务工具增强等

>**2026.04.22：** [2.0.7版本](https://github.com/zhayujie/CowAgent/releases/tag/2.0.7)，图像生成内置技能（GPT Image 2、Nano Banana 等）、新模型支持（Kimi K2.6、Claude Opus 4.7、GLM 5.1）、知识库和记忆增强、Web 控制台优化

>**2026.04.14：** [2.0.6版本](https://github.com/zhayujie/CowAgent/releases/tag/2.0.6)，知识库系统、梦境记忆模块、上下文智能压缩、Web 控制台多会话及多项优化。

>**2026.04.01：** [2.0.5版本](https://github.com/zhayujie/CowAgent/releases/tag/2.0.5)，Cow CLI 命令系统、Skill Hub 开源、浏览器工具、企微扫码创建、多项优化和修复。

>**2026.03.22：** [2.0.4版本](https://github.com/zhayujie/CowAgent/releases/tag/2.0.4)，新增个人微信通道（微信扫码即用）、新增 MiniMax-M2.7 和 GLM-5-Turbo 模型、run.sh 脚本重构、日文文档及多项修复。

>**2026.03.18：** [2.0.3版本](https://github.com/zhayujie/CowAgent/releases/tag/2.0.3)，新增企微智能机器人和 QQ 通道、支持 Coding Plan、新增多个模型、Web 端文件处理、记忆系统升级。

>**2026.02.27：** [2.0.2版本](https://github.com/zhayujie/CowAgent/releases/tag/2.0.2)，Web 控制台全面升级（流式对话、模型/技能/记忆/通道/定时任务/日志管理）、支持多通道同时运行、会话持久化存储、新增多个模型。

>**2026.02.13：** [2.0.1版本](https://github.com/zhayujie/CowAgent/releases/tag/2.0.1)，内置 Web Search 工具、智能上下文裁剪策略、运行时信息动态更新、Windows 兼容性适配，修复定时任务记忆丢失、飞书连接等多项问题。

>**2026.02.03：** [2.0.0版本](https://github.com/zhayujie/CowAgent/releases/tag/2.0.0)，正式升级为超级 Agent 助理，支持多轮任务决策、具备长期记忆、实现多种系统工具、支持 Skills 框架，新增多种模型并优化了接入渠道。

更多更新历史请查看: [更新日志](https://docs.cowagent.ai/releases)

<br/>

# 🚀 快速开始

项目提供了一键安装、配置、启动、管理程序的脚本，推荐使用脚本快速运行，也可以根据下文中的详细指引一步步安装运行。

在终端执行以下命令：

**Linux / macOS：**
```bash
bash <(curl -fsSL https://cdn.link-ai.tech/code/cow/run.sh)
```

**Windows（PowerShell）：**
```powershell
irm https://cdn.link-ai.tech/code/cow/run.ps1 | iex
```

脚本使用说明：[一键运行脚本](https://docs.cowagent.ai/guide/quick-start)。安装后可使用 `cow start`、`cow stop` 等 [CLI 命令](https://docs.cowagent.ai/cli/index) 管理服务。


## 一、准备

### 1. 模型API

项目支持国内外主流厂商的模型接口，可选模型及配置说明参考：[模型说明](#模型说明)。

> 注：Agent 模式下推荐使用以下模型，可根据效果及成本综合选择：deepseek-v4-flash、MiniMax-M2.7、glm-5.1、kimi-k2.6、qwen3.5-plus、claude-sonnet-4-6、gemini-3.1-pro-preview、gpt-5.4、gpt-5.4-mini、ernie-5.1

同时支持使用 **LinkAI 平台** 接口，支持上述全部模型，并支持知识库、工作流、插件等 Agent 技能，参考 [接口文档](https://docs.link-ai.tech/platform/api)。

### 2.环境安装

支持 Linux、MacOS、Windows 操作系统，可在个人计算机及服务器上运行，需安装 `Python`，Python 版本需在 3.7 ~ 3.13 之间。

> 注意：Agent 模式推荐使用源码运行，若选择 Docker 部署则无需安装 python 环境和下载源码，可直接快进到下一节。

**(1) 克隆项目代码：**

```bash
git clone https://github.com/zhayujie/CowAgent
cd CowAgent/
```

若遇到网络问题可使用国内仓库地址：https://gitee.com/zhayujie/CowAgent

**(2) 安装核心依赖 (必选)：**

```bash
pip3 install -r requirements.txt
```

**(3) 拓展依赖 (可选，建议安装)：**

```bash
pip3 install -r requirements-optional.txt
```

> 国内网络可使用镜像源加速：`pip3 install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`

如果某项依赖安装失败可注释掉对应的行后重试。

**(4) 安装 Cow CLI (推荐)：**

```bash
pip3 install -e .
```

安装后可使用 `cow` 命令管理服务（启动、停止、更新等）和技能，详见 [命令文档](https://docs.cowagent.ai/cli/index)。

**(5) 安装浏览器工具 (可选)：**

如果需要 Agent 操作浏览器（如访问网页、填写表单等），需要额外安装浏览器依赖：

```bash
cow install-browser
```

该命令会自动安装 `playwright` 和 Chromium 浏览器，国内网络自动使用镜像加速。详见 [浏览器工具文档](https://docs.cowagent.ai/tools/browser)。

## 二、配置

配置文件的模板在根目录的 `config-template.json` 中，需复制该模板创建最终生效的 `config.json` 文件：

```bash
  cp config-template.json config.json
```

然后在 `config.json` 中填入配置，以下是对默认配置的说明，可根据需要进行自定义修改（注意实际使用时请去掉注释，保证 JSON 格式的规范）：

```bash
# config.json 文件内容示例
{
  "channel_type": "weixin",                                   # 接入渠道类型，默认为 weixin, 支持修改为 feishu,dingtalk,wecom_bot,qq,wechatcom_app,wechatmp_service,wechatmp,terminal
  "model": "deepseek-v4-flash",                                # 模型名称
  "deepseek_api_key": "",                                      # DeepSeek API Key
  "deepseek_api_base": "https://api.deepseek.com/v1",         # DeepSeek API 地址
  "minimax_api_key": "",                                      # MiniMax API Key
  "zhipu_ai_api_key": "",                                     # 智谱 GLM API Key
  "moonshot_api_key": "",                                     # Kimi/Moonshot API Key
  "ark_api_key": "",                                          # 豆包(火山方舟) API Key
  "dashscope_api_key": "",                                    # 百炼(通义千问) API Key
  "claude_api_key": "",                                       # Claude API Key
  "claude_api_base": "https://api.anthropic.com/v1",          # Claude API 地址，修改可接入三方代理平台
  "gemini_api_key": "",                                       # Gemini API Key
  "gemini_api_base": "https://generativelanguage.googleapis.com", # Gemini API 地址
  "open_ai_api_key": "",                                      # OpenAI API Key
  "open_ai_api_base": "https://api.openai.com/v1",            # OpenAI API 地址
  "linkai_api_key": "",                                       # LinkAI API Key
  "proxy": "",                                                # 代理客户端的 ip 和端口，国内环境需要开启代理的可填写该项，如 "127.0.0.1:7890"
  "speech_recognition": false,                                # 是否开启语音识别
  "group_speech_recognition": false,                          # 是否开启群组语音识别
  "voice_reply_voice": false,                                 # 是否使用语音回复语音
  "use_linkai": false,                                        # 是否使用 LinkAI 接口，默认关闭，设置为 true 后可对接 LinkAI 平台模型
  "web_password": "",                                         # Web 控制台访问密码，留空则不启用密码保护（监听 0.0.0.0 时务必设置）
  "agent": true,                                              # 是否启用 Agent 模式，启用后拥有多轮工具决策、长期记忆、Skills 能力等
  "agent_workspace": "~/cow",                                 # Agent 的工作空间路径，用于存储 memory、skills、系统设定等
  "agent_max_context_tokens": 50000,                          # Agent 模式下最大上下文 tokens，超出将自动智能压缩处理
  "agent_max_context_turns": 20,                              # Agent 模式下最大上下文记忆轮次，一问一答为一轮，超出后智能压缩处理
  "agent_max_steps": 20,                                      # Agent 模式下单次任务的最大决策步数，超出后将停止继续调用工具
  "enable_thinking": false                                    # 是否启用深度思考模式
}
```

**配置补充说明:** 

<details>
<summary>1. 语音配置</summary>

+ 添加 `"speech_recognition": true` 将开启语音识别，默认使用 openai 的 whisper 模型识别为文字，同时以文字回复，该参数仅支持私聊 (注意由于语音消息无法匹配前缀，一旦开启将对所有语音自动回复，支持语音触发画图)；
+ 添加 `"group_speech_recognition": true` 将开启群组语音识别，默认使用 openai 的 whisper 模型识别为文字，同时以文字回复，参数仅支持群聊 (会匹配 group_chat_prefix 和 group_chat_keyword, 支持语音触发画图)；
+ 添加 `"voice_reply_voice": true` 将开启语音回复语音（同时作用于私聊和群聊）
+ 使用 MiniMax TTS：设置 `"text_to_voice": "minimax"`，并配置 `minimax_api_key`；可通过 `"tts_voice_id"` 指定发音人（如 `English_Graceful_Lady`），`"text_to_voice_model"` 指定模型（如 `speech-2.8-hd`、`speech-2.8-turbo`）
</details>

<details>
<summary>2. 其他配置</summary>

+ `model`: 模型名称，Agent 模式下推荐使用 `deepseek-v4-flash`、`MiniMax-M2.7`、`glm-5.1`、`kimi-k2.6`、`qwen3.6-plus`、`claude-sonnet-4-6`、`gemini-3.1-pro-preview`，全部模型名称参考[common/const.py](https://github.com/zhayujie/CowAgent/blob/master/common/const.py)文件
+ `character_desc`：普通对话模式下的机器人系统提示词。在 Agent 模式下该配置不生效，由工作空间中的文件内容构成。
+ `subscribe_msg`：订阅消息，公众号和企业微信 channel 中请填写，当被订阅时会自动回复， 可使用特殊占位符。目前支持的占位符有{trigger_prefix}，在程序中它会自动替换成 bot 的触发词。
</details>

<details>
<summary>3. LinkAI 配置</summary>

+ `use_linkai`: 是否使用 LinkAI 接口，默认关闭，设置为 true 后可对接 LinkAI 平台，使用模型、知识库、工作流、插件等技能, 参考[接口文档](https://docs.link-ai.tech/platform/api/chat)
+ `linkai_api_key`: LinkAI Api Key，可在 [控制台](https://link-ai.tech/console/interface) 创建
</details>

注：全部配置项说明可在 [`config.py`](https://github.com/zhayujie/CowAgent/blob/master/config.py) 文件中查看。

## 三、运行

### 1.本地运行

如果是个人计算机 **本地运行**，直接在项目根目录下执行：

```bash
cow start              # 推荐，需先安装 Cow CLI
python3 app.py         # 或直接运行，windows 环境下该命令通常为 python app.py
```

运行后默认会启动 web 服务，可通过访问 `http://localhost:9899/chat` 在网页端对话。

如果需要接入其他应用通道只需修改 `config.json` 配置文件中的 `channel_type` 参数，详情参考：[通道说明](#通道说明)。


### 2.服务器部署

推荐使用 `cow` 命令管理服务：

```bash
cow start              # 后台启动
cow stop               # 停止服务
cow restart            # 重启服务
cow status             # 查看运行状态
cow logs               # 查看日志
cow update             # 拉取最新代码并重启
```

也可以使用传统方式后台运行：

```bash
nohup python3 app.py & tail -f nohup.out
```

此外，项目根目录下的 `run.sh` 脚本也支持一键管理服务，包括 `./run.sh start`、`./run.sh stop`、`./run.sh restart` 等命令，执行 `./run.sh help` 可查看全部用法。

> 如果需要通过浏览器访问 Web 控制台，请确保服务器的 `9899` 端口已在防火墙或安全组中放行，建议仅对指定 IP 开放以保证安全。

### 3.Docker部署

使用 docker 部署无需下载源码和安装依赖，只需要获取 `docker-compose.yml` 配置文件并启动容器即可。Agent 模式下更推荐使用源码进行部署，以获得更多系统访问能力。

> 前提是需要安装好 `docker` 及 `docker-compose`，安装成功后执行 `docker -v` 和 `docker-compose version` (或 `docker compose version`) 可查看到版本号。安装地址为 [docker官网](https://docs.docker.com/engine/install/) 。

**(1) 下载 docker-compose.yml 文件**

```bash
curl -O https://cdn.link-ai.tech/code/cow/docker-compose.yml
```

下载完成后打开 `docker-compose.yml` 填写所需配置，例如 `CHANNEL_TYPE`、`OPEN_AI_API_KEY` 和等配置。

**(2) 启动容器**

在 `docker-compose.yml` 所在目录下执行以下命令启动容器：

```bash
sudo docker compose up -d         # 若docker-compose为 1.X 版本，则执行 `sudo  docker-compose up -d`
```

运行命令后，会自动取 [docker hub](https://hub.docker.com/r/zhayujie/chatgpt-on-wechat) 拉取最新 release 版本的镜像。当执行 `sudo docker ps` 能查看到 NAMES 为 chatgpt-on-wechat 的容器即表示运行成功。最后执行以下命令可查看容器的运行日志：

```bash
sudo docker logs -f chatgpt-on-wechat
```

> 如果需要通过浏览器访问 Web 控制台，请确保服务器的 `9899` 端口已在防火墙或安全组中放行，建议仅对指定 IP 开放以保证安全。

## 模型说明

推荐通过 Web 控制台在线管理模型配置，无需手动编辑文件，详见 [模型文档](https://docs.cowagent.ai/models)。以下是手动修改 `config.json` 配置模型的说明：

<details>
<summary>DeepSeek</summary>

1. API Key 创建：在 [DeepSeek 平台](https://platform.deepseek.com/api_keys) 创建 API Key

2. 填写配置

方式一：官方接入（推荐）：

```json
{
    "model": "deepseek-v4-flash",
    "deepseek_api_key": "sk-xxxxxxxxxxx"
}
```

 - `model`: 推荐填写 `deepseek-v4-flash`、`deepseek-v4-pro`
 - `deepseek_api_key`: DeepSeek 平台的 API Key
 - `deepseek_api_base`: 可选，默认为 `https://api.deepseek.com/v1`，可修改为第三方代理地址

方式二：OpenAI 兼容方式接入：

```json
{
    "model": "deepseek-v4-flash",
    "bot_type": "openai",
    "open_ai_api_key": "sk-xxxxxxxxxxx",
    "open_ai_api_base": "https://api.deepseek.com/v1"
}
```

</details>

<details>
<summary>MiniMax</summary>

方式一：官方接入，配置如下(推荐)：

```json
{
    "model": "MiniMax-M2.7",
    "minimax_api_key": ""
}
```
 - `model`: 可填写 `MiniMax-M2.7、MiniMax-M2.7-highspeed、MiniMax-M2.5、MiniMax-M2.1、MiniMax-M2.1-lightning、MiniMax-M2、abab6.5-chat` 等
 - `minimax_api_key`：MiniMax 平台的 API-KEY，在 [控制台](https://platform.minimaxi.com/user-center/basic-information/interface-key) 创建

方式二：OpenAI 兼容方式接入，配置如下：
```json
{
  "bot_type": "openai",
  "model": "MiniMax-M2.7",
  "open_ai_api_base": "https://api.minimaxi.com/v1",
  "open_ai_api_key": ""
}
```
- `bot_type`: OpenAI 兼容方式
- `model`: 可填 `MiniMax-M2.7、MiniMax-M2.7-highspeed、MiniMax-M2.5、MiniMax-M2.1、MiniMax-M2.1-lightning、MiniMax-M2`，参考[API文档](https://platform.minimaxi.com/document/%E5%AF%B9%E8%AF%9D?key=66701d281d57f38758d581d0#QklxsNSbaf6kM4j6wjO5eEek)
- `open_ai_api_base`: MiniMax 平台 API 的 BASE URL
- `open_ai_api_key`: MiniMax 平台的 API-KEY
</details>

<details>
<summary>Claude</summary>

1. API Key 创建：在 [Claude控制台](https://console.anthropic.com/settings/keys) 创建 API Key

2. 填写配置

```json
{
    "model": "claude-sonnet-4-6",
    "claude_api_key": "YOUR_API_KEY"
}
```
 - `model`: 参考 [官方模型ID](https://docs.anthropic.com/en/docs/about-claude/models/overview#model-aliases) ，支持 `claude-sonnet-4-6、claude-opus-4-7、claude-opus-4-6、claude-sonnet-4-5、claude-sonnet-4-0、claude-opus-4-0、claude-3-5-sonnet-latest` 等
</details>

<details>
<summary>Gemini</summary>

API Key 创建：在 [控制台](https://aistudio.google.com/app/apikey?hl=zh-cn) 创建 API Key ，配置如下
```json
{
    "model": "gemini-3.1-flash-lite-preview",
    "gemini_api_key": ""
}
```
 - `model`: 参考[官方文档-模型列表](https://ai.google.dev/gemini-api/docs/models?hl=zh-cn)，支持 `gemini-3.1-flash-lite-preview、gemini-3.1-pro-preview、gemini-3-flash-preview、gemini-3-pro-preview` 等
</details>

<details>
<summary>OpenAI</summary>

1. API Key 创建：在 [OpenAI平台](https://platform.openai.com/api-keys) 创建 API Key

2. 填写配置

```json
{
    "model": "gpt-5.4",
    "open_ai_api_key": "YOUR_API_KEY",
    "open_ai_api_base": "https://api.openai.com/v1",
    "bot_type": "openai"
}
```

 - `model`: 与 OpenAI 接口的 [model参数](https://platform.openai.com/docs/models) 一致，支持包括 gpt-5.4、gpt-5.4-mini、gpt-5.4-nano、o 系列、gpt-4.1 等模型，Agent 模式推荐使用  `gpt-5.4`、`gpt-5.4-mini`
 - `open_ai_api_base`: 如果需要接入第三方代理接口，可通过修改该参数进行接入
 - `bot_type`: 使用 OpenAI 相关模型时无需填写。当使用第三方代理接口接入 Claude 等非 OpenAI 官方模型时，该参数设为 `openai`
</details>

<details>
<summary>智谱AI (GLM)</summary>

方式一：官方接入，配置如下(推荐)：

```json
{
  "model": "glm-5.1",
  "zhipu_ai_api_key": ""
}
```
 - `model`: 可填 `glm-5.1、glm-5-turbo、glm-5、glm-4.7、glm-4-plus、glm-4-flash、glm-4-air、glm-4-airx、glm-4-long` 等, 参考 [glm 系列模型编码](https://bigmodel.cn/dev/api/normal-model/glm-4)
 - `zhipu_ai_api_key`: 智谱AI 平台的 API KEY，在 [控制台](https://www.bigmodel.cn/usercenter/proj-mgmt/apikeys) 创建

方式二：OpenAI 兼容方式接入，配置如下：
```json
{
  "bot_type": "openai",
  "model": "glm-5.1",
  "open_ai_api_base": "https://open.bigmodel.cn/api/paas/v4",
  "open_ai_api_key": ""
}
```
- `bot_type`: OpenAI 兼容方式
- `model`: 可填 `glm-5.1、glm-5-turbo、glm-5、glm-4.7、glm-4-plus、glm-4-flash、glm-4-air、glm-4-airx、glm-4-long` 等
- `open_ai_api_base`: 智谱AI 平台的 BASE URL
- `open_ai_api_key`: 智谱AI 平台的 API KEY
</details>

<details>
<summary>通义千问 (Qwen)</summary>

方式一：官方 SDK 接入，配置如下(推荐)：

```json
{
    "model": "qwen3.6-plus",
    "dashscope_api_key": "sk-qVxxxxG"
}
```
 - `model`: 可填写 `qwen3.6-plus、qwen3.5-plus、qwen3-max、qwen-max、qwen-plus、qwen-turbo、qwen-long、qwq-plus` 等
 - `dashscope_api_key`: 通义千问的 API-KEY，参考 [官方文档](https://bailian.console.aliyun.com/?tab=api#/api) ，在 [百炼控制台](https://bailian.console.aliyun.com/?tab=model#/api-key) 创建

方式二：OpenAI 兼容方式接入，配置如下：
```json
{
  "bot_type": "openai",
  "model": "qwen3.6-plus",
  "open_ai_api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "open_ai_api_key": "sk-qVxxxxG"
}
```
- `bot_type`: OpenAI 兼容方式
- `model`: 支持官方所有模型，参考[模型列表](https://help.aliyun.com/zh/model-studio/models?spm=a2c4g.11186623.0.0.78d84823Kth5on#9f8890ce29g5u)
- `open_ai_api_base`: 通义千问 API 的 BASE URL
- `open_ai_api_key`: 通义千问的 API-KEY
</details>

<details>
<summary>豆包 (Doubao)</summary>

1. API Key 创建：在 [火山方舟控制台](https://console.volcengine.com/ark/region:ark+cn-beijing/apikey) 创建API Key

2. 填写配置

```json
{
    "model": "doubao-seed-2-0-code-preview-260215",
    "ark_api_key": "YOUR_API_KEY"
}
```
 - `model`: 可填写 `doubao-seed-2-0-code-preview-260215、doubao-seed-2-0-pro-260215、doubao-seed-2-0-lite-260215、doubao-seed-2-0-mini-260215` 等
 - `ark_api_key`: 火山方舟平台的 API Key，在 [控制台](https://console.volcengine.com/ark/region:ark+cn-beijing/apikey) 创建
 - `ark_base_url`: 可选，默认为 `https://ark.cn-beijing.volces.com/api/v3`
</details>

<details>
<summary>Kimi (Moonshot)</summary>

方式一：官方接入，配置如下：

```json
{
    "model": "kimi-k2.6",
    "moonshot_api_key": ""
}
```
 - `model`: 可填写 `kimi-k2.6、kimi-k2.5、kimi-k2、moonshot-v1-8k、moonshot-v1-32k、moonshot-v1-128k`
 - `moonshot_api_key`: Moonshot 的 API-KEY，在 [控制台](https://platform.moonshot.cn/console/api-keys) 创建

方式二：OpenAI 兼容方式接入，配置如下：
```json
{
  "bot_type": "openai",
  "model": "kimi-k2.6",
  "open_ai_api_base": "https://api.moonshot.cn/v1",
  "open_ai_api_key": ""
}
```
- `bot_type`: OpenAI 兼容方式
- `model`: 可填写 `kimi-k2.6、kimi-k2.5、kimi-k2、moonshot-v1-8k、moonshot-v1-32k、moonshot-v1-128k`
- `open_ai_api_base`: Moonshot 的 BASE URL
- `open_ai_api_key`: Moonshot 的 API-KEY
</details>

<details>
<summary>ModelScope</summary>

```json
{
  "bot_type": "modelscope",
  "model": "Qwen/QwQ-32B",
  "modelscope_api_key": "your_api_key",
  "modelscope_base_url": "https://api-inference.modelscope.cn/v1/chat/completions",
  "text_to_image": "MusePublic/489_ckpt_FLUX_1"
}
```

- `bot_type`: modelscope 接口格式
- `model`: 参考[模型列表](https://www.modelscope.cn/models?filter=inference_type&page=1)
- `modelscope_api_key`: 参考 [官方文档-访问令牌](https://modelscope.cn/docs/accounts/token) ，在 [控制台](https://modelscope.cn/my/myaccesstoken)
- `modelscope_base_url`: modelscope 平台的 BASE URL
- `text_to_image`: 图像生成模型，参考[模型列表](https://www.modelscope.cn/models?filter=inference_type&page=1)
</details>

<details>
<summary>LinkAI</summary>

1. API Key 创建：在 [LinkAI平台](https://link-ai.tech/console/interface) 创建 API Key

2. 填写配置

```json
{
    "model": "gpt-5.4-mini",
    "use_linkai": true,
    "linkai_api_key": "YOUR API KEY"
}
```

+ `use_linkai`: 是否使用 LinkAI 接口，默认关闭，设置为 true 后可对接 LinkAI 平台的模型，并使用知识库、工作流、数据库、插件等丰富的 Agent 技能
+ `linkai_api_key`: LinkAI 平台的 API Key，可在 [控制台](https://link-ai.tech/console/interface) 中创建
+ `model`: [模型列表](https://link-ai.tech/console/models)中的全部模型均可使用
</details>

<details>
<summary>Azure</summary>

1. API Key 创建：在 [Azure平台](https://oai.azure.com/) 创建 API Key 

2. 填写配置

```json
{
  "model": "",
  "use_azure_chatgpt": true,
  "open_ai_api_key": "",
  "open_ai_api_base": "",
  "azure_deployment_id": "",
  "azure_api_version": "2025-01-01-preview"
}
```

 - `model`: 留空即可
 - `use_azure_chatgpt`: 设为 true 
 - `open_ai_api_key`: Azure 平台的密钥
 - `open_ai_api_base`: Azure 平台的 BASE URL
 - `azure_deployment_id`: Azure 平台部署的模型名称
 - `azure_api_version`: api 版本以及以上参数可以在部署的 [模型配置](https://oai.azure.com/resource/deployments) 界面查看
</details>

<details>
<summary>百度千帆 / ERNIE</summary>

方式一：官方接入（推荐），配置如下：

```json
{
  "model": "ernie-5.1",
  "qianfan_api_key": "",
  "qianfan_api_base": "https://qianfan.baidubce.com/v2"
}
```

 - `model`: 默认推荐填写 `ernie-5.1`（多模态，可直接识图），也可填写 `ernie-5.0`、`ernie-x1.1`、`ernie-4.5-turbo-128k`、`ernie-4.5-turbo-32k`；当主模型为纯文本 ERNIE 时，Vision 工具会自动 fallback 到 `ernie-4.5-turbo-vl`
 - `qianfan_api_key`: 百度千帆 API Key，通常以 `bce-v3/` 开头，可在百度智能云控制台创建
 - `qianfan_api_base`: 可选，默认为 `https://qianfan.baidubce.com/v2`

方式二：OpenAI 兼容方式接入，配置如下：
```json
{
  "bot_type": "openai",
  "model": "ernie-5.1",
  "open_ai_api_base": "https://qianfan.baidubce.com/v2",
  "open_ai_api_key": ""
}
```
- `bot_type`: OpenAI 兼容方式
- `model`: 支持千帆平台上的 ERNIE 模型
- `open_ai_api_base`: 百度千帆 OpenAI 兼容 API 的 BASE URL
- `open_ai_api_key`: 百度千帆 API Key

</details>

<details>
<summary>讯飞星火</summary>

方式一：官方接入，配置如下：
参考 [官方文档-快速指引](https://www.xfyun.cn/doc/platform/quickguide.html#%E7%AC%AC%E4%BA%8C%E6%AD%A5-%E5%88%9B%E5%BB%BA%E6%82%A8%E7%9A%84%E7%AC%AC%E4%B8%80%E4%B8%AA%E5%BA%94%E7%94%A8-%E5%BC%80%E5%A7%8B%E4%BD%BF%E7%94%A8%E6%9C%8D%E5%8A%A1) 获取 `APPID、 APISecret、 APIKey` 三个参数

```json
{
  "model": "xunfei",
  "xunfei_app_id": "",
  "xunfei_api_key": "",
  "xunfei_api_secret": "",
  "xunfei_domain": "4.0Ultra",
  "xunfei_spark_url": "wss://spark-api.xf-yun.com/v4.0/chat"
}
```
 - `model`: 填 `xunfei`
 - `xunfei_domain`: 可填写 `4.0Ultra、generalv3.5、max-32k、generalv3、pro-128k、lite`
 - `xunfei_spark_url`: 填写参考 [官方文档-请求地址](https://www.xfyun.cn/doc/spark/Web.html#_1-1-%E8%AF%B7%E6%B1%82%E5%9C%B0%E5%9D%80) 的说明
 
方式二：OpenAI 兼容方式接入，配置如下：
```json
{
  "bot_type": "openai",
  "model": "4.0Ultra",
  "open_ai_api_base": "https://spark-api-open.xf-yun.com/v1",
  "open_ai_api_key": ""
}
```
- `bot_type`: OpenAI 兼容方式
- `model`: 可填写 `4.0Ultra、generalv3.5、max-32k、generalv3、pro-128k、lite`
- `open_ai_api_base`: 讯飞星火平台的 BASE URL
- `open_ai_api_key`: 讯飞星火平台的[APIPassword](https://console.xfyun.cn/services/bm3) ，因模型而已
</details>

<details>
<summary>Coding Plan</summary>

Coding Plan 是各厂商推出的编程包月套餐，所有厂商均可通过 OpenAI 兼容方式接入：

```json
{
  "bot_type": "openai",
  "model": "模型名称",
  "open_ai_api_base": "厂商 Coding Plan API Base",
  "open_ai_api_key": "YOUR_API_KEY"
}
```

目前支持阿里云、MiniMax、智谱 GLM、Kimi、火山引擎等厂商，各厂商详细配置请参考 [Coding Plan 文档](https://docs.cowagent.ai/models/coding-plan)。
</details>


## 通道说明

推荐通过 Web 控制台在线管理通道配置，无需手动编辑文件，详见 [通道文档](https://docs.cowagent.ai/channels/weixin)。以下为手动修改 `config.json` 配置通道的说明：

支持同时可接入多个通道，配置时可通过逗号进行分割，例如 `"channel_type": "feishu,dingtalk"`。

<details>
<summary>1. Weixin - 微信</summary>

接入个人微信，扫码登录即可使用，支持文本、图片、语音、文件等消息收发。

```json
{
    "channel_type": "weixin"
}
```

启动后终端会显示二维码，使用微信扫码授权即可，也可以在 Web 控制台的「通道」页面中扫码接入。登录凭证会自动保存至 `~/.weixin_cow_credentials.json`，下次启动无需重新扫码，如需重新登录删除该文件后重启即可。

详细步骤和参数说明参考 [微信接入](https://docs.cowagent.ai/channels/weixin)

</details>

<details>
<summary>2. Web</summary>

项目启动后会默认运行 Web 控制台，配置如下：

```json
{
    "channel_type": "web",
    "web_host": "0.0.0.0",
    "web_password": "YOUR PASSWORD",
    "web_port": 9899
}
```

- `web_host`: 监听地址，默认 `127.0.0.1`（仅本机），如需公网访问请改为 `0.0.0.0` 并设置密码
- `web_port`: 默认为 9899，可按需更改，需要服务器防火墙和安全组放行该端口
- `web_password`: 访问密码，留空则不启用密码保护。部署在公网环境时请务必设置
- 如本地运行，启动后请访问 `http://localhost:9899` ；如服务器运行，请访问 `http://YOUR_IP:9899`
> 注：请将上述 url 中的 ip 或者 port 替换为实际的值
</details>

<details>
<summary>3. Feishu - 飞书</summary>

飞书使用 WebSocket 长连接模式，无需公网 IP。详细步骤参考 [飞书接入](https://docs.cowagent.ai/channels/feishu)。

**方式一：扫码一键创建（推荐）**

启动 Cow 后打开 Web 控制台，**通道** → **接入通道** → 选择 **飞书** → 扫码创建。也支持 CLI 启动时在终端打印二维码。

**方式二：手动配置**

在飞书开放平台创建自建应用并配置权限后，将凭据填入 `config.json`：

```json
{
    "channel_type": "feishu",
    "feishu_app_id": "APP_ID",
    "feishu_app_secret": "APP_SECRET",
    "feishu_stream_reply": true
}
```

- `feishu_stream_reply`：是否开启流式打字机回复，默认开启（需 `cardkit:card:write` 权限 + 飞书客户端 ≥ 7.20）

</details>

<details>
<summary>4. DingTalk - 钉钉</summary>

钉钉需要在开放平台创建智能机器人应用，将以下配置填入 `config.json`：

```json
{
    "channel_type": "dingtalk",
    "dingtalk_client_id": "CLIENT_ID",
    "dingtalk_client_secret": "CLIENT_SECRET"
}
```
详细步骤和参数说明参考 [钉钉接入](https://docs.cowagent.ai/channels/dingtalk)
</details>

<details>
<summary>5. WeCom Bot - 企微智能机器人</summary>

企微智能机器人使用 WebSocket 长连接模式，无需公网 IP 和域名。详细步骤参考 [企微智能机器人接入](https://docs.cowagent.ai/channels/wecom-bot)。

**方式一：扫码一键创建（推荐）**

启动 Cow 后打开 Web 控制台，**通道** → **接入通道** → 选择 **企微智能机器人** → 使用企业微信扫码创建。

**方式二：手动配置**

在企业微信中创建智能机器人并选择**长连接模式**，记录 Bot ID 和 Secret 后填入 `config.json`：

```json
{
    "channel_type": "wecom_bot",
    "wecom_bot_id": "YOUR_BOT_ID",
    "wecom_bot_secret": "YOUR_SECRET"
}
```

</details>

<details>
<summary>6. QQ - QQ 机器人</summary>

QQ 机器人使用 WebSocket 长连接模式，无需公网 IP 和域名，支持 QQ 单聊、群聊和频道消息：

```json
{
    "channel_type": "qq",
    "qq_app_id": "YOUR_APP_ID",
    "qq_app_secret": "YOUR_APP_SECRET"
}
```
详细步骤和参数说明参考 [QQ 机器人接入](https://docs.cowagent.ai/channels/qq)

</details>

<details>
<summary>7. WeCom App - 企业微信应用</summary>

企业微信自建应用接入需在后台创建应用并启用消息回调，配置示例：

```json
{
    "channel_type": "wechatcom_app",
    "wechatcom_corp_id": "CORPID",
    "wechatcomapp_token": "TOKEN",
    "wechatcomapp_port": 9898,
    "wechatcomapp_secret": "SECRET",
    "wechatcomapp_agent_id": "AGENTID",
    "wechatcomapp_aes_key": "AESKEY"
}
```
详细步骤和参数说明参考 [企微自建应用接入](https://docs.cowagent.ai/channels/wecom)

</details>

<details>
<summary>8. WeChat MP - 微信公众号</summary>

本项目支持订阅号和服务号两种公众号，通过服务号（`wechatmp_service`）体验更佳。

**个人订阅号（wechatmp）**

```json
{
    "channel_type": "wechatmp",
    "wechatmp_token": "TOKEN",
    "wechatmp_port": 80,
    "wechatmp_app_id": "APPID",
    "wechatmp_app_secret": "APPSECRET",
    "wechatmp_aes_key": ""
}
```

**企业服务号（wechatmp_service）**

```json
{
    "channel_type": "wechatmp_service",
    "wechatmp_token": "TOKEN",
    "wechatmp_port": 80,
    "wechatmp_app_id": "APPID",
    "wechatmp_app_secret": "APPSECRET",
    "wechatmp_aes_key": ""
}
```

详细步骤和参数说明参考 [微信公众号接入](https://docs.cowagent.ai/channels/wechatmp)

</details>

<details>
<summary>9. Terminal - 终端</summary>

修改 `config.json` 中的 `channel_type` 字段：

```json
{
    "channel_type": "terminal"
}
```

运行后可在终端与机器人进行对话。

</details>

<br/>

# 🔗 相关项目

- [Cow Skill Hub](https://github.com/zhayujie/cow-skill-hub)：开源的 AI Agent 技能广场，浏览、搜索、安装和发布技能，支持 CowAgent、OpenClaw、Claude Code 等多种 Agent。
- [bot-on-anything](https://github.com/zhayujie/bot-on-anything)：轻量和高可扩展的大模型应用框架，支持接入 Slack, Telegram, Discord, Gmail 等海外平台，可作为本项目的补充使用。
- [AgentMesh](https://github.com/MinimalFuture/AgentMesh)：开源的多智能体( Multi-Agent )框架，可以通过多智能体团队的协同来解决复杂问题。




# 🔎 常见问题

FAQs： <https://github.com/zhayujie/CowAgent/wiki/FAQs>

或直接在线咨询 [项目小助手](https://link-ai.tech/app/Kv2fXJcH)  (知识库持续完善中，回复供参考)

# 🛠️ 开发

欢迎接入更多应用通道，参考 [飞书通道](https://github.com/zhayujie/CowAgent/blob/master/channel/feishu/feishu_channel.py) 新增自定义通道，实现接收和发送消息逻辑即可完成接入。同时欢迎贡献新的 Skills，向 [Skill Hub](https://skills.cowagent.ai/submit) 提交技能。

# ✉ 联系

欢迎提交PR、Issues进行反馈，以及通过 🌟Star 支持并关注项目更新。项目运行遇到问题可以查看 [常见问题列表](https://github.com/zhayujie/CowAgent/wiki/FAQs) ，以及前往 [Issues](https://github.com/zhayujie/CowAgent/issues) 中搜索。个人开发者可加入开源交流群参与更多讨论，企业用户可联系[产品客服](https://cdn.link-ai.tech/portal/linkai-customer-service.png)咨询。

# 🌟 贡献者

![cow contributors](https://contrib.rocks/image?repo=zhayujie/CowAgent&max=1000)

# 📌 项目更名说明

本项目原名 `chatgpt-on-wechat`（GitHub 原地址：https://github.com/zhayujie/chatgpt-on-wechat ），
于 2026.04.13 正式更名为 **CowAgent**。GitHub 已自动设置重定向，原有链接仍可正常访问。

如需更新本地仓库的远程地址（可选）：
```bash
git remote set-url origin https://github.com/zhayujie/CowAgent.git
```
