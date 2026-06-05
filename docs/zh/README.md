<p align="center"><img src= "https://github.com/user-attachments/assets/eca9a9ec-8534-4615-9e0f-96c5ac1d10a3" alt="CowAgent" width="420" /></p>

<p align="center">
  <a href="https://github.com/zhayujie/CowAgent/releases/latest"><img src="https://img.shields.io/github/v/release/zhayujie/CowAgent?cacheSeconds=3600" alt="Latest release"></a>
  <a href="https://github.com/zhayujie/CowAgent/blob/master/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT"></a>
  <a href="https://github.com/zhayujie/CowAgent"><img src="https://img.shields.io/github/stars/zhayujie/CowAgent?style=flat-square&cacheSeconds=3600" alt="Stars"></a>
  <a href="https://docs.cowagent.ai/zh"><img src="https://img.shields.io/badge/%E6%96%87%E6%A1%A3-cowagent.ai-blue?style=flat&logo=readthedocs&logoColor=white" alt="文档"></a>
</p>

<p align="center">
  <a href="https://trendshift.io/repositories/25763" target="_blank"><img src="https://trendshift.io/api/badge/repositories/25763" alt="zhayujie%2FCowAgent | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
</p>

<p align="center">
  [<a href="../../README.md">English</a>] | [中文] | [<a href="../ja/README.md">日本語</a>]
</p>

**CowAgent** 是一个开源的超级 AI 助理，能够主动思考和规划任务、操作计算机和外部资源、创造和执行 Skills、构建知识库与长期记忆，与你一同成长，是 Agent Harness 工程的最佳实践之一。

CowAgent 轻量、易部署、可扩展，自由接入主流大模型，覆盖微信、飞书、钉钉、企微、QQ、Telegram、Slack、网页等多渠道，7×24 运行于个人电脑或服务器中。

<p align="center">
  <a href="https://cowagent.ai/?lang=zh">🌐 官网</a> &nbsp;·&nbsp;
  <a href="https://docs.cowagent.ai/zh/">📖 文档中心</a> &nbsp;·&nbsp;
  <a href="https://docs.cowagent.ai/zh/guide/quick-start">🚀 快速开始</a> &nbsp;·&nbsp;
  <a href="https://skills.cowagent.ai/">🧩 技能广场</a> &nbsp;·&nbsp;
  <a href="https://link-ai.tech/cowagent/create">☁️ 在线体验</a>
</p>

<br/>

## 🌟 核心能力

| 能力 | 说明 |
| :--- | :--- |
| [任务规划](https://docs.cowagent.ai/zh/intro/architecture) | 理解复杂任务并自主分解执行，循环调用工具直到完成目标 |
| [长期记忆](https://docs.cowagent.ai/zh/memory) | 三层记忆架构（上下文 → 天级 → 核心），梦境蒸馏自动整理，支持关键词与向量混合检索 |
| [知识库](https://docs.cowagent.ai/zh/knowledge) | 自动整理结构化知识为 Markdown Wiki，构建持续增长的知识图谱，可视化浏览 |
| [技能](https://docs.cowagent.ai/zh/skills) | 从 [Skill Hub](https://skills.cowagent.ai/)、GitHub、ClawHub 等一键安装；也可通过对话创造自定义技能 |
| [工具](https://docs.cowagent.ai/zh/tools) | 内置文件读写、终端、浏览器、定时任务、记忆检索、联网搜索等 10+ 工具，支持 MCP 协议 |
| [通道](https://docs.cowagent.ai/zh/channels) | 一个 Agent 同时接入 Web、微信、飞书、钉钉、企微、QQ、公众号、Telegram、Slack 等多个渠道 |
| 多模态 | 文本、图片、语音、文件全消息类型支持，覆盖识别、生成、收发 |
| [模型](https://docs.cowagent.ai/zh/models) | DeepSeek、Claude、Gemini、GPT、GLM、Qwen、Kimi、MiniMax、Doubao 等主流厂商，配置一行切换 |
| [部署](https://docs.cowagent.ai/zh/guide/quick-start) | 一键脚本安装，Web 控制台统一管理；本地、Docker、服务器多种部署方式 |

<br/>

## 🏗️ 架构总览

<img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/architecture/zh/architecture.jpg" alt="CowAgent Architecture" width="750"/>

CowAgent 是一个完整的 **Agent Harness**：消息从各类**通道**进入，**Agent Core** 结合记忆、知识库与可用工具/技能进行任务规划与决策，调用**模型**生成结果，再回传至原通道。各模块解耦清晰，按需扩展。

详见 [项目架构](https://docs.cowagent.ai/zh/intro/architecture)。

<br/>

## 🚀 快速开始

项目提供一键安装脚本，自动完成依赖安装、配置和启动：

**Linux / macOS：**

```bash
bash <(curl -fsSL https://cdn.link-ai.tech/code/cow/run.sh)
```

**Windows（PowerShell）：**

```powershell
irm https://cdn.link-ai.tech/code/cow/run.ps1 | iex
```

**Docker：**

```bash
curl -O https://cdn.link-ai.tech/code/cow/docker-compose.yml
docker compose up -d
```

启动成功后访问 `http://localhost:9899` 进入 **Web 控制台**，在控制台内即可完成模型配置、渠道接入、技能安装等全部操作。

> 服务器部署且需要公网访问控制台时，请在 `config.json` 中将 `web_host` 设为 `0.0.0.0`（同时强烈建议设置 `web_password` 启用鉴权），然后访问 `http://<server-ip>:9899`，并确保防火墙/安全组放行 `9899` 端口。

> 📖 详细安装指南：[快速开始](https://docs.cowagent.ai/zh/guide/quick-start) · [源码安装](https://docs.cowagent.ai/zh/guide/manual-install) · [升级](https://docs.cowagent.ai/zh/guide/upgrade)

安装后可使用 `cow` [CLI 命令](https://docs.cowagent.ai/zh/cli) 管理服务：

```bash
cow start | stop | restart        # 服务管理
cow status | logs                  # 状态和日志
cow update                         # 拉取最新代码并重启
cow skill install <名称>           # 安装技能
cow install-browser                # 安装浏览器工具
```

<br/>

## 🤖 模型支持

CowAgent 支持国内外主流厂商的大语言模型。**文本对话、图像理解、图像生成、语音识别/合成、向量** 等能力均可独立配置厂商。

| 厂商 | 代表模型 | 文本 | 图像理解 | 图像生成 | 语音识别 | 语音合成 | 向量 |
| --- | --- | :-: | :-: | :-: | :-: | :-: | :-: |
| [DeepSeek](https://docs.cowagent.ai/zh/models/deepseek) | deepseek-v4-flash / pro | ✅ | | | | | |
| [MiniMax](https://docs.cowagent.ai/zh/models/minimax) | MiniMax-M3 | ✅ | ✅ | ✅ | | ✅ | |
| [Claude](https://docs.cowagent.ai/zh/models/claude) | claude-opus-4-8 | ✅ | ✅ | | | | |
| [Gemini](https://docs.cowagent.ai/zh/models/gemini) | gemini-3.5-flash | ✅ | ✅ | ✅ | | | |
| [OpenAI](https://docs.cowagent.ai/zh/models/openai) | gpt-5.5、o 系列 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [智谱 GLM](https://docs.cowagent.ai/zh/models/glm) | glm-5.1、glm-5v-turbo | ✅ | ✅ | | ✅ | | ✅ |
| [通义千问](https://docs.cowagent.ai/zh/models/qwen) | qwen3.7-plus | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [豆包 Doubao](https://docs.cowagent.ai/zh/models/doubao) | doubao-seed-2.0 系列 | ✅ | ✅ | ✅ | | | ✅ |
| [Kimi](https://docs.cowagent.ai/zh/models/kimi) | kimi-k2.6 | ✅ | ✅ | | | | |
| [百度ERNIE](https://docs.cowagent.ai/zh/models/qianfan) | ernie-5.1 | ✅ | ✅ | | | | |
| [小米 MiMo](https://docs.cowagent.ai/zh/models/mimo) | mimo-v2.5-pro / v2.5 | ✅ | ✅ | | | ✅ | |
| [LinkAI](https://docs.cowagent.ai/zh/models/linkai) | 一个 Key 接入 100+ 模型 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [自定义](https://docs.cowagent.ai/zh/models/custom) | 本地模型 / 三方代理 | ✅ | | | | | |

> 推荐通过 Web 控制台在线配置，无需手动编辑文件。手动配置请参考各厂商文档，详见 [模型概览](https://docs.cowagent.ai/zh/models)。

<br/>

## 💬 通道接入

一个 Agent 实例可同时接入多个渠道，启动时通过 `channel_type` 切换或并行运行。

| 通道 | 文本 | 图片 | 文件 | 语音 | 群聊 |
| --- | :-: | :-: | :-: | :-: | :-: |
| [Web 控制台](https://docs.cowagent.ai/zh/channels/web)（默认） | ✅ | ✅ | ✅ | ✅ | |
| [微信](https://docs.cowagent.ai/zh/channels/weixin) | ✅ | ✅ | ✅ | ✅ | |
| [飞书](https://docs.cowagent.ai/zh/channels/feishu) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [钉钉](https://docs.cowagent.ai/zh/channels/dingtalk) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [企微智能机器人](https://docs.cowagent.ai/zh/channels/wecom-bot) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [QQ](https://docs.cowagent.ai/zh/channels/qq) | ✅ | ✅ | ✅ | | ✅ |
| [企业微信应用](https://docs.cowagent.ai/zh/channels/wecom) | ✅ | ✅ | ✅ | ✅ | |
| [微信客服](https://docs.cowagent.ai/zh/channels/wechat-kf) | ✅ | ✅ | ✅ | ✅ | |
| [微信公众号](https://docs.cowagent.ai/zh/channels/wechatmp) | ✅ | ✅ | | ✅ | |
| [Telegram](https://docs.cowagent.ai/zh/channels/telegram) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Slack](https://docs.cowagent.ai/zh/channels/slack) | ✅ | ✅ | ✅ | | ✅ |
| [Discord](https://docs.cowagent.ai/zh/channels/discord) | ✅ | ✅ | ✅ | | ✅ |

> 飞书、企微智能机器人支持在 Web 控制台内**扫码一键接入**，无需公网 IP。详见 [通道概览](https://docs.cowagent.ai/zh/channels)。

<img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/screenshots/zh/web-console-chat.png" alt="CowAgent Web 控制台" width="800"/>

*Web 控制台是默认通道，也是统一的 Agent 配置和管理入口*

<br/>

## 🧠 记忆与知识库

**长期记忆**采用三层架构：对话上下文（短期）→ 天级记忆（中期）→ MEMORY.md（长期）。每日自动执行**梦境蒸馏（Deep Dream）**，将分散记忆整合为精炼的长期记忆并生成叙事日记。详见 [长期记忆](https://docs.cowagent.ai/zh/memory) · [梦境蒸馏](https://docs.cowagent.ai/zh/memory/deep-dream)。

**个人知识库** 与按时间记录的记忆不同，以**主题为维度**组织结构化知识。Agent 在对话中自动整理有价值信息，维护交叉引用与索引，Web 控制台可可视化浏览知识图谱。详见 [个人知识库](https://docs.cowagent.ai/zh/knowledge)。

<table>
  <tr>
    <td width="50%">
      <img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/screenshots/zh/web-console-memory.png" alt="长期记忆" />
      <p align="center"><em>长期记忆 · 三层记忆 + 梦境蒸馏</em></p>
    </td>
    <td width="50%">
      <img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/screenshots/zh/web-console-knowledge.png" alt="个人知识库" />
      <p align="center"><em>个人知识库 · 自动整理的 Markdown Wiki</em></p>
    </td>
  </tr>
</table>

<br/>


## 🔧 工具与技能

**工具（Tools）** 是 Agent 操作系统资源的原子能力，**技能（Skills）** 是基于说明文件的高级工作流，可组合多个工具完成复杂任务。

### 工具系统

**内置工具** 涵盖文件读写（`read` / `write` / `edit` / `ls`）、终端（`bash`）、文件发送（`send`）、记忆检索（`memory`）、环境变量（`env_config`）、网页获取（`web_fetch`）、定时任务（`scheduler`）、联网搜索（`web_search`）、图像识别（`vision`）、浏览器自动化（`browser`）等常用能力。

**MCP 协议** 通过 [Model Context Protocol](https://modelcontextprotocol.io) 接入开放生态中的各种 MCP 服务，配置一次 `mcp.json` 即用即得，支持 stdio / SSE 协议、热更新、零代码接入。

详见 [工具概览](https://docs.cowagent.ai/zh/tools) · [MCP 集成](https://docs.cowagent.ai/zh/tools/mcp)。

### 技能系统

- **[Skill Hub](https://skills.cowagent.ai/)** — 开源的技能广场，浏览、搜索、一键安装
- **GitHub / ClawHub / URL 等** — 任意来源一键安装
- **对话创造** — 通过 `skill-creator` 用对话快速生成自定义技能，可将工作流程或第三方接口直接固化为技能

```bash
/skill list                   # 查看当前技能
/skill search <关键词>         # 在技能广场搜索
/skill install <名称>          # 一键安装
```

详见 [技能概览](https://docs.cowagent.ai/zh/skills) · [创建技能](https://docs.cowagent.ai/zh/skills/create)。

<br/>

## 🏷 更新日志

> **2026.06.01：** [v2.1.0](https://github.com/zhayujie/CowAgent/releases/tag/2.1.0) — 国际化支持、新增通道（Telegram、Discord、Slack、微信客服）、命令行交互升级、一键安装脚本优化、MCP Streamable HTTP 支持、新模型接入（claude-opus-4-8、MiMo）

> **2026.05.22：** [v2.0.9](https://github.com/zhayujie/CowAgent/releases/tag/2.0.9) — 模型管理、MCP 协议支持、浏览器登录态持久化、新模型接入（gpt-5.5、gemini-3.5-flash、qwen3.7-max）、部署安全加固

> **2026.05.06：** [v2.0.8](https://github.com/zhayujie/CowAgent/releases/tag/2.0.8) — 飞书渠道全面升级（语音、流式输出、扫码接入）、新模型支持（DeepSeek V4、百度千帆）、定时任务工具增强

> **2026.04.22：** [v2.0.7](https://github.com/zhayujie/CowAgent/releases/tag/2.0.7) — 图像生成内置技能（GPT Image 2、Nano Banana）、新模型支持（Kimi K2.6、Claude Opus 4.7、GLM 5.1）、知识库和记忆增强

> **2026.04.14：** [v2.0.6](https://github.com/zhayujie/CowAgent/releases/tag/2.0.6) — 知识库系统、梦境记忆模块、上下文智能压缩、Web 控制台多会话

> **2026.04.01：** [v2.0.5](https://github.com/zhayujie/CowAgent/releases/tag/2.0.5) — Cow CLI 命令系统、Skill Hub 开源、浏览器工具、企微扫码创建

> **2026.03.22：** [v2.0.4](https://github.com/zhayujie/CowAgent/releases/tag/2.0.4) — 新增个人微信通道，支持文本/图片/文件/语音消息

> **2026.02.03：** [v2.0.0](https://github.com/zhayujie/CowAgent/releases/tag/2.0.0) — 正式升级为超级 Agent 助理，支持多轮任务决策、长期记忆、Skills 框架

完整更新历史：[Release Notes](https://docs.cowagent.ai/zh/releases)

<br/>

## 🤝 社区与支持

扫码加入微信开源交流群：

<img width="130" src="https://img-1317903499.cos.ap-guangzhou.myqcloud.com/docs/open-community.png">

也可通过以下方式获取支持：

- 🐛 [提交 Issue](https://github.com/zhayujie/CowAgent/issues)
- 🤖 在线 AI 助手：[项目小助手](https://link-ai.tech/app/Kv2fXJcH)（基于项目知识库）

<br/>

## 🔗 相关项目

- **[Cow Skill Hub](https://github.com/zhayujie/cow-skill-hub)** — 开源的 AI Agent 技能广场，支持 CowAgent、OpenClaw、Claude Code 等多种 Agent
- **[bot-on-anything](https://github.com/zhayujie/bot-on-anything)** — 轻量大模型应用框架，支持 Slack、Telegram、Discord、Gmail 等海外平台
- **[AgentMesh](https://github.com/MinimalFuture/AgentMesh)** — 开源多智能体（Multi-Agent）框架，通过团队协同解决复杂问题

<br/>

## 🏢 企业服务

<a href="https://link-ai.tech" target="_blank"><img width="650" src="https://cdn.link-ai.tech/image/link-ai-intro.jpg"></a>

> [LinkAI](https://link-ai.tech/) 是面向企业和个人的一站式 AI 智能体平台，为 CowAgent 提供云端托管和企业级支持：
>
> - **🚀 免部署在线运行**：无需服务器即可创建 [CowAgent 在线助理](https://link-ai.tech/cowagent/create)，1 分钟拥有专属 Agent
> - **🧠 Agent 基础设施**：聚合主流大模型、知识库、数据库、技能、工作流，提供开箱即用的 Agent 能力扩展
> - **🏢 企业级协作**：提供团队协作、权限分级、审计日志、私有化部署等能力，让 Agent 安全落地企业场景

**产品咨询和企业服务** 可联系产品客服：

<img width="130" src="https://cdn.link-ai.tech/portal/linkai-customer-service.png">

<br/>

## 🛠️ 开发与贡献

欢迎各种形式的贡献：新功能、Bug 修复、性能优化、文档完善，或向 [Skill Hub](https://skills.cowagent.ai/submit) 分享你的技能。请先阅读 [CONTRIBUTING.md](/CONTRIBUTING.md) 了解如何开始，然后提交 Issue 讨论或直接发起 PR。

欢迎 ⭐ Star 支持项目，并通过 Watch → Custom → Releases 订阅新版本通知。也欢迎提交 PR、Issue 进行反馈。

## 🌟 贡献者

![cow contributors](https://contrib.rocks/image?repo=zhayujie/CowAgent&max=1000)

<br/>

## ⚠️ 声明

1. 本项目遵循 [MIT 开源协议](/LICENSE)，主要用于技术研究和学习。使用时请遵守所在地法律法规及相关政策，因使用本项目所产生的一切后果由使用者自行承担。
2. **成本与安全：** Agent 模式 Token 消耗显著高于普通对话，请根据效果与成本权衡选择模型；Agent 具备访问本地操作系统的能力，请谨慎选择部署环境。
3. CowAgent 项目专注于开源技术开发，不会参与、授权或发行任何加密货币。

<br/>

## 📌 项目更名说明

本项目原名 `chatgpt-on-wechat`，于 2026.04.13 正式更名为 **CowAgent**。原 GitHub 地址已自动重定向，老用户可选择执行 `git remote set-url origin https://github.com/zhayujie/CowAgent.git` 更新本地远程地址。
