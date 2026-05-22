<p align="center"><img src="https://github.com/user-attachments/assets/eca9a9ec-8534-4615-9e0f-96c5ac1d10a3" alt="CowAgent" width="550" /></p>

<p align="center">
  <a href="https://github.com/zhayujie/CowAgent/releases/latest"><img src="https://img.shields.io/github/v/release/zhayujie/CowAgent" alt="Latest release"></a>
  <a href="https://github.com/zhayujie/CowAgent/blob/master/LICENSE"><img src="https://img.shields.io/github/license/zhayujie/CowAgent" alt="License: MIT"></a>
  <a href="https://github.com/zhayujie/CowAgent"><img src="https://img.shields.io/github/stars/zhayujie/CowAgent?style=flat-square" alt="Stars"></a> <br/>
  [<a href="https://github.com/zhayujie/CowAgent/blob/master/README.md">中文</a>] | [English] | [<a href="https://github.com/zhayujie/CowAgent/blob/master/docs/ja/README.md">日本語</a>]
</p>

**CowAgent** is an AI super assistant powered by LLMs, capable of autonomous task planning, operating computers and external resources, creating and executing Skills, and continuously growing with long-term memory and a personal knowledge base. It supports flexible model switching, handles text, voice, images, and files, and can be integrated into WeChat, Web, Feishu, DingTalk, WeCom Bot, WeCom App, and WeChat Official Account — running 7×24 hours on your personal computer or server.

<p align="center">
  <a href="https://cowagent.ai/">🌐 Website</a> &nbsp;·&nbsp;
  <a href="https://docs.cowagent.ai/en/intro/index">📖 Docs</a> &nbsp;·&nbsp;
  <a href="https://docs.cowagent.ai/en/guide/quick-start">🚀 Quick Start</a> &nbsp;·&nbsp;
  <a href="https://skills.cowagent.ai/">🧩 Skill Hub</a> &nbsp;·&nbsp;
  <a href="https://link-ai.tech/cowagent/create">☁️ Try Online</a>
</p>

## Introduction

> CowAgent is both an out-of-the-box AI super assistant and a highly extensible Agent framework. You can extend it with new model interfaces, channels, built-in tools, and the Skills system to flexibly implement various customization needs.

- ✅ **Autonomous Task Planning**: Understands complex tasks and autonomously plans execution, continuously thinking and invoking tools until goals are achieved.
- ✅ **Long-term Memory**: Automatically persists conversation memory to local files and databases, including core memory, daily memory, and Deep Dream distillation, with keyword and vector retrieval support.
- ✅ **Personal Knowledge Base**: Automatically organizes structured knowledge with cross-references to build a knowledge graph, with web-based visualization and conversational management.
- ✅ **Skills System**: Implements a Skills creation and execution engine, supports installing skills from [Skill Hub](https://skills.cowagent.ai), GitHub, etc., or creating custom Skills through conversation.
- ✅ **Tool System**: Built-in tools for file I/O, terminal execution, browser automation, scheduled tasks, messaging, and more — autonomously invoked by the Agent.
- ✅ **CLI System**: Provides terminal commands and in-chat commands for process management, skill installation, configuration, and more.
- ✅ **Multimodal Messages**: Supports parsing, processing, generating, and sending text, images, voice, files, and other message types.
- ✅ **Multiple Model Support**: Supports DeepSeek, MiniMax, Claude, Gemini, OpenAI, GLM, Qwen, Doubao, Kimi, and other mainstream model providers.
- ✅ **Multi-platform Deployment**: Runs on local computers or servers, integrable into WeChat, Web, Feishu, DingTalk, WeChat Official Account, and WeCom applications.

## Disclaimer

1. This project follows the [MIT License](/LICENSE) and is intended for technical research and learning. Users must comply with local laws, regulations, policies, and corporate bylaws. Any illegal or rights-infringing use is prohibited.
2. Agent mode consumes more tokens than normal chat mode. Choose models based on effectiveness and cost. Agent has access to the host OS — please deploy in trusted environments.
3. CowAgent focuses on open-source development and does not participate in, authorize, or issue any cryptocurrency.

## Demo

Try online (no deployment needed): [CowAgent](https://link-ai.tech/cowagent/create)

## Changelog

> **2026.04.14:** [v2.0.6](https://github.com/zhayujie/CowAgent/releases/tag/2.0.6) — Knowledge Base, Deep Dream Memory Distillation, Smart Context Compression, Web Console upgrades.

> **2026.04.01:** [v2.0.5](https://github.com/zhayujie/CowAgent/releases/tag/2.0.5) — Cow CLI, Skill Hub open source, Browser tool, WeCom Bot QR scan, and more.

> **2026.02.27:** [v2.0.2](https://github.com/zhayujie/CowAgent/releases/tag/2.0.2) — Web console overhaul (streaming chat, model/skill/memory/channel/scheduler/log management), multi-channel concurrent running, session persistence, new models including Gemini 3.1 Pro / Claude 4.6 Sonnet / Qwen3.5 Plus.

> **2026.02.13:** [v2.0.1](https://github.com/zhayujie/CowAgent/releases/tag/2.0.1) — Built-in Web Search tool, smart context trimming, runtime info dynamic update, Windows compatibility, fixes for scheduler memory loss, Feishu connection issues, and more.

> **2026.02.03:** [v2.0.0](https://github.com/zhayujie/CowAgent/releases/tag/2.0.0) — Full upgrade to AI super assistant with multi-step task planning, long-term memory, built-in tools, Skills framework, new models, and optimized channels.

> **2025.05.23:** [v1.7.6](https://github.com/zhayujie/CowAgent/releases/tag/1.7.6) — Web channel optimization, AgentMesh multi-agent plugin, Baidu TTS, claude-4-sonnet/opus support.

> **2025.04.11:** [v1.7.5](https://github.com/zhayujie/CowAgent/releases/tag/1.7.5) — wechatferry protocol, DeepSeek model, Tencent Cloud voice, ModelScope and Gitee-AI support.

> **2024.12.13:** [v1.7.4](https://github.com/zhayujie/CowAgent/releases/tag/1.7.4) — Gemini 2.0 model, Web channel, memory leak fix.

Full changelog: [Release Notes](https://docs.cowagent.ai/en/releases/overview)

<br/>

## 🚀 Quick Start

The project provides a one-click script for installation, configuration, startup, and management:

**Linux / macOS:**
```bash
bash <(curl -fsSL https://cdn.link-ai.tech/code/cow/run.sh)
```

**Windows (PowerShell):**
```powershell
irm https://cdn.link-ai.tech/code/cow/run.ps1 | iex
```

After running, the Web service starts by default. Access `http://localhost:9899/chat` to chat.

Script usage: [One-click Install](https://docs.cowagent.ai/en/guide/quick-start). After installation, you can also use `cow start`, `cow stop`, and other [CLI commands](https://docs.cowagent.ai/en/cli/index) to manage the service.

### Manual Installation

**1. Clone the project**

```bash
git clone https://github.com/zhayujie/CowAgent
cd CowAgent/
```

**2. Install dependencies**

```bash
pip3 install -r requirements.txt
pip3 install -r requirements-optional.txt   # optional but recommended
```

**3. Install Cow CLI (recommended)**

```bash
pip3 install -e .
```

After installation, use `cow` commands to manage the service (start, stop, update, etc.) and skills. See [Command Docs](https://docs.cowagent.ai/en/cli/index).

**4. Install browser (optional)**

If you need the Agent to operate a browser (visit web pages, fill forms, etc.):

```bash
cow install-browser
```

This auto-installs `playwright` and Chromium. See [Browser Tool Docs](https://docs.cowagent.ai/en/tools/browser).

**5. Configure**

```bash
cp config-template.json config.json
```

Fill in your model API key and channel type in `config.json`. See the [configuration docs](https://docs.cowagent.ai/en/guide/manual-install) for details.

**6. Run**

```bash
cow start              # recommended, requires Cow CLI
python3 app.py         # or run directly
```

For server deployment, use `cow` commands to manage the service:

```bash
cow start              # start in background
cow stop               # stop service
cow restart            # restart service
cow status             # check running status
cow logs               # view logs
cow update             # pull latest code and restart
```

Or use the traditional way:

```bash
nohup python3 app.py & tail -f nohup.out
```

### Docker Deployment

```bash
curl -O https://cdn.link-ai.tech/code/cow/docker-compose.yml
# Edit docker-compose.yml with your config
sudo docker compose up -d
sudo docker logs -f chatgpt-on-wechat
```

<br/>

## Models

Supports mainstream model providers. Recommended models for Agent mode:

| Provider | Recommended Model |
| --- | --- |
| DeepSeek | `deepseek-v4-flash` |
| MiniMax | `MiniMax-M2.7` |
| Claude | `claude-sonnet-4-6` |
| Gemini | `gemini-3.1-pro-preview` |
| OpenAI | `gpt-5.4` |
| GLM | `glm-5.1` |
| Qwen | `qwen3.6-plus` |
| Doubao | `doubao-seed-2-0-code-preview-260215` |
| Kimi | `kimi-k2.6` |

For detailed configuration of each model, see the [Models documentation](https://docs.cowagent.ai/en/models/index).

### Coding Plan

Coding Plan is a monthly subscription package offered by various providers, ideal for high-frequency Agent usage. All providers can be accessed via OpenAI-compatible mode:

```json
{
  "bot_type": "openai",
  "model": "MODEL_NAME",
  "open_ai_api_base": "PROVIDER_CODING_PLAN_API_BASE",
  "open_ai_api_key": "YOUR_API_KEY"
}
```

- `bot_type`: Must be `openai`
- `model`: Model name supported by the provider
- `open_ai_api_base`: Provider's Coding Plan API Base (different from standard pay-as-you-go)
- `open_ai_api_key`: Provider's Coding Plan API Key

> Note: Coding Plan API Base and API Key are usually separate from standard pay-as-you-go ones. Please obtain them from each provider's platform.

Supported providers include Alibaba Cloud, MiniMax, Zhipu GLM, Kimi, Volcengine, and more. For detailed configuration of each provider, see the [Coding Plan documentation](https://docs.cowagent.ai/en/models/coding-plan).

<br/>

## Channels

Supports multiple platforms. Set `channel_type` in `config.json` to switch:

| Channel | `channel_type` | Docs |
| --- | --- | --- |
| WeChat | `weixin` | [WeChat Setup](https://docs.cowagent.ai/en/channels/weixin) |
| Web (default) | `web` | [Web Channel](https://docs.cowagent.ai/en/channels/web) |
| Feishu | `feishu` | [Feishu Setup](https://docs.cowagent.ai/en/channels/feishu) |
| DingTalk | `dingtalk` | [DingTalk Setup](https://docs.cowagent.ai/en/channels/dingtalk) |
| WeCom Bot | `wecom_bot` | [WeCom Bot Setup](https://docs.cowagent.ai/en/channels/wecom-bot) |
| WeCom App | `wechatcom_app` | [WeCom Setup](https://docs.cowagent.ai/en/channels/wecom) |
| WeChat MP | `wechatmp` / `wechatmp_service` | [WeChat MP Setup](https://docs.cowagent.ai/en/channels/wechatmp) |
| Terminal | `terminal` | — |

Multiple channels can be enabled simultaneously, separated by commas: `"channel_type": "feishu,dingtalk"`.

<br/>

## Enterprise Services

<a href="https://link-ai.tech" target="_blank"><img width="720" src="https://cdn.link-ai.tech/image/link-ai-intro.jpg"></a>

> [LinkAI](https://link-ai.tech/) is a one-stop AI agent platform for enterprises and developers, integrating multimodal LLMs, knowledge bases, Agent plugins, and workflows. Supports one-click integration with mainstream platforms, SaaS and private deployment.

<br/>

## 🔗 Related Projects

- [Cow Skill Hub](https://github.com/zhayujie/cow-skill-hub): Open skill marketplace for AI Agents — browse, search, install, and publish skills for CowAgent, OpenClaw, Claude Code, and more.
- [bot-on-anything](https://github.com/zhayujie/bot-on-anything): Lightweight and highly extensible LLM application framework supporting Slack, Telegram, Discord, Gmail, and more.
- [AgentMesh](https://github.com/MinimalFuture/AgentMesh): Open-source Multi-Agent framework for complex problem solving through agent team collaboration.

## 🔎 FAQ

FAQs: <https://github.com/zhayujie/CowAgent/wiki/FAQs>

## 🛠️ Contributing

Welcome to add new channels, referring to the [Feishu channel](https://github.com/zhayujie/CowAgent/blob/master/channel/feishu/feishu_channel.py) as an example. Also welcome to contribute new Skills, see the [Skill Creation docs](https://docs.cowagent.ai/en/skills/create), or submit to [Skill Hub](https://skills.cowagent.ai/submit).

## ✉ Contact

Welcome to submit PRs and Issues, and support the project with a 🌟 Star. For questions, check the [FAQ list](https://github.com/zhayujie/CowAgent/wiki/FAQs) or search [Issues](https://github.com/zhayujie/CowAgent/issues).

## 🌟 Contributors

![cow contributors](https://contrib.rocks/image?repo=zhayujie/CowAgent&max=1000)
