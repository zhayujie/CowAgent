<p align="center"><img src= "https://github.com/user-attachments/assets/eca9a9ec-8534-4615-9e0f-96c5ac1d10a3" alt="CowAgent" width="420" /></p>

<p align="center">
  <a href="https://github.com/zhayujie/CowAgent/releases/latest"><img src="https://img.shields.io/github/v/release/zhayujie/CowAgent?cacheSeconds=3600" alt="Latest release" /></a>
  <a href="https://github.com/zhayujie/CowAgent/blob/master/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT" /></a>
  <a href="https://github.com/zhayujie/CowAgent"><img src="https://img.shields.io/github/stars/zhayujie/CowAgent?style=flat-square&cacheSeconds=3600" alt="Stars" /></a>
  <a href="https://docs.cowagent.ai/zh"><img src="https://img.shields.io/badge/%E6%96%87%E6%A1%A3-cowagent.ai-blue?style=flat&logo=readthedocs&logoColor=white" alt="文件" /></a>
  <a href="https://cdn.link-ai.tech/code/cow/cowagent-wechat-group.png"><img src="https://img.shields.io/badge/%E5%BE%AE%E4%BF%A1-%E4%BA%A4%E6%B5%81%E7%BE%A4-07C160?style=flat&logo=wechat&logoColor=white" alt="微信交流群" /></a>
  <a href="https://discord.gg/9U8eA8v9TR"><img src="https://img.shields.io/badge/Discord-Join-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord" /></a>
</p>

<p align="center">
  <a href="https://trendshift.io/repositories/25763" target="_blank"><img src="https://trendshift.io/api/badge/repositories/25763" alt="zhayujie%2FCowAgent | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
</p>

<p align="center">
[<a href="../../README.md">English</a>] | [<a href="README.md">中文</a>] | [繁體中文] | [<a href="../ja/README.md">日本語</a>]
</p>

**CowAgent** 是一個開源的超級 AI 助理，能夠主動思考和規劃任務、操作電腦和外部資源、創造和執行 Skills、構建知識庫與長期記憶、透過自主進化與你一同成長，是 Agent Harness 工程的最佳實踐之一。

CowAgent 輕量、易部署、可擴充，自由接入主流大模型，覆蓋微信、飛書、釘釘、企微、QQ、Telegram、Slack、網頁等多渠道，7×24 執行於個人電腦或伺服器中。

<p align="center">
  <a href="https://cowagent.ai/?lang=zh">🌐 官網</a> &nbsp;·&nbsp;
  <a href="https://docs.cowagent.ai/zh/">📖 文件中心</a> &nbsp;·&nbsp;
  <a href="https://docs.cowagent.ai/zh/guide/quick-start">🚀 快速開始</a> &nbsp;·&nbsp;
  <a href="https://skills.cowagent.ai/">🧩 技能廣場</a> &nbsp;·&nbsp;
  <a href="https://cowagent.ai/zh/download/">💻 下載客戶端</a> &nbsp;·&nbsp;
  <a href="https://link-ai.tech/cowagent/create">☁️ 線上體驗</a>
</p>

<br/>

## 🎬 示範

<p align="center">
  <video src="https://github.com/user-attachments/assets/a2d8fb12-f294-42d6-a569-c4a6ceedab1d" controls muted playsinline width="720">
    你的瀏覽器無法播放該影片。
    <a href="https://cowagent.ai/?lang=zh">前往官網觀看示範 →</a>
  </video>
</p>

<br/>

## 🌟 核心能力

| 能力 | 說明 |
| :--- | :--- |
| [任務規劃](https://docs.cowagent.ai/zh/intro/architecture) | 理解複雜任務並自主分解執行，迴圈呼叫工具直到完成目標 |
| [長期記憶](https://docs.cowagent.ai/zh/memory) | 三層記憶架構（上下文 → 天級 → 核心），夢境蒸餾自動整理，支援關鍵詞與向量混合檢索 |
| [知識庫](https://docs.cowagent.ai/zh/knowledge) | 自動整理結構化知識為 Markdown Wiki，構建持續增長的知識圖譜，視覺化瀏覽 |
| [自主進化](https://docs.cowagent.ai/zh/memory/self-evolution) | 自動覆盤對話，最佳化技能、處理未完成事項、沉澱記憶與知識，在使用中持續成長 |
| [技能](https://docs.cowagent.ai/zh/skills) | 從 [Skill Hub](https://skills.cowagent.ai/)、GitHub、ClawHub 等一鍵安裝；也可透過對話創造自定義技能 |
| [工具](https://docs.cowagent.ai/zh/tools) | 內建檔案讀寫、終端、瀏覽器、定時任務、記憶檢索、聯網搜尋等 10+ 工具，支援 MCP 協議 |
| [通道](https://docs.cowagent.ai/zh/channels) | 一個 Agent 同時接入 Web、微信、飛書、釘釘、企微、QQ、公眾號、Telegram、Slack 等多個渠道 |
| 多模態 | 文字、圖片、語音、檔案全訊息型別支援，覆蓋識別、生成、收發 |
| [模型](https://docs.cowagent.ai/zh/models) | DeepSeek、Claude、Gemini、GPT、GLM、Qwen、Kimi、MiniMax、Doubao 等主流廠商，設定一行切換 |
| [部署](https://docs.cowagent.ai/zh/guide/quick-start) | 一鍵指令碼安裝，Web 控制台統一管理；本地、Docker、伺服器多種部署方式 |

<br/>

## 🏗️ 架構總覽

<img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/architecture/zh/architecture.jpg" alt="CowAgent Architecture" width="750"/>

CowAgent 是一個完整的 **Agent Harness**：訊息從各類**通道**進入，**Agent Core** 結合記憶、知識庫與可用工具/技能進行任務規劃與決策，呼叫**模型**生成結果，再回傳至原通道。各模組解耦清晰，按需擴充。

詳見 [專案架構](https://docs.cowagent.ai/zh/intro/architecture)。

<br/>

## 🚀 快速開始

專案提供一鍵安裝指令碼，自動完成依賴安裝、設定和啟動：

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

啟動成功後開啟 `http://localhost:9899` 進入 **Web 控制台**，在控制台內即可完成模型設定、渠道接入、技能安裝等全部操作。

> 伺服器部署且需要從外部網路存取控制台時，請在 `config.json` 中將 `web_host` 設為 `0.0.0.0`（同時強烈建議設定 `web_password` 啟用身分驗證），然後訪問 `http://<server-ip>:9899`，並確保防火牆/安全組放行 `9899` 埠。

> 📖 詳細安裝指南：[快速開始](https://docs.cowagent.ai/zh/guide/quick-start) · [原始碼安裝](https://docs.cowagent.ai/zh/guide/manual-install) · [升級](https://docs.cowagent.ai/zh/guide/upgrade)

安裝後可使用 `cow` [CLI 命令](https://docs.cowagent.ai/zh/cli) 管理服務：

```bash
cow start | stop | restart        # 服務管理
cow status | logs                  # 狀態和日誌
cow update                         # 拉取最新程式碼並重啟
cow skill install <名稱>           # 安裝技能
cow install-browser                # 安裝瀏覽器工具
```

> 💻 桌面客戶端：前往 **[下載 CowAgent 桌面客戶端](https://cowagent.ai/zh/download/)**（macOS / Windows），內建 Agent 執行環境，開箱即用。

<br/>

## 🤖 模型支援

CowAgent 支援國內外主流廠商的大語言模型。**文字對話、影像理解、影像生成、語音識別/合成、向量** 等能力均可獨立設定廠商。

| 廠商 | 代表模型 | 文字 | 影像理解 | 影像生成 | 語音識別 | 語音合成 | 向量 |
| --- | --- | :-: | :-: | :-: | :-: | :-: | :-: |
| [DeepSeek](https://docs.cowagent.ai/zh/models/deepseek) | deepseek-v4-flash / pro | ✅ | | | | | |
| [Claude](https://docs.cowagent.ai/zh/models/claude) | claude-opus-5 / sonnet-5 | ✅ | ✅ | | | | |
| [OpenAI](https://docs.cowagent.ai/zh/models/openai) | gpt-5.6 系列 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Gemini](https://docs.cowagent.ai/zh/models/gemini) | gemini-3.7-flash | ✅ | ✅ | ✅ | | | |
| [MiniMax](https://docs.cowagent.ai/zh/models/minimax) | MiniMax-M3 | ✅ | ✅ | ✅ | | ✅ | |
| [智譜 GLM](https://docs.cowagent.ai/zh/models/glm) | glm-5.3-flash、glm-5v-turbo | ✅ | ✅ | | ✅ | | ✅ |
| [通義千問](https://docs.cowagent.ai/zh/models/qwen) | qwen3.8-flash | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Kimi](https://docs.cowagent.ai/zh/models/kimi) | kimi-k3 | ✅ | ✅ | | | | |
| [豆包 Doubao](https://docs.cowagent.ai/zh/models/doubao) | doubao-seed-2.1 系列 | ✅ | ✅ | ✅ | | | ✅ |
| [百度ERNIE](https://docs.cowagent.ai/zh/models/qianfan) | ernie-5.1 | ✅ | ✅ | | | | |
| [小米 MiMo](https://docs.cowagent.ai/zh/models/mimo) | mimo-v2.5-pro / v2.5 | ✅ | ✅ | | | ✅ | |
| [LinkAI](https://docs.cowagent.ai/zh/models/linkai) | 一個 Key 接入 100+ 模型 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [自定義](https://docs.cowagent.ai/zh/models/custom) | 本地模型 / 三方代理 | ✅ | | | | | |

> 推薦透過 Web 控制台線上設定，無需手動編輯檔案。手動設定請參考各廠商文件，詳見 [模型概覽](https://docs.cowagent.ai/zh/models)。

<br/>

## 💬 通道接入

一個 Agent 例項可同時接入多個渠道，啟動時透過 `channel_type` 切換或並行執行。

| 通道 | 文字 | 圖片 | 檔案 | 語音 | 群聊 |
| --- | :-: | :-: | :-: | :-: | :-: |
| [Web 控制台](https://docs.cowagent.ai/zh/channels/web)（預設） | ✅ | ✅ | ✅ | ✅ | |
| [微信](https://docs.cowagent.ai/zh/channels/weixin) | ✅ | ✅ | ✅ | ✅ | |
| [飛書](https://docs.cowagent.ai/zh/channels/feishu) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [釘釘](https://docs.cowagent.ai/zh/channels/dingtalk) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [企微智慧機器人](https://docs.cowagent.ai/zh/channels/wecom-bot) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [QQ](https://docs.cowagent.ai/zh/channels/qq) | ✅ | ✅ | ✅ | | ✅ |
| [企業微信應用](https://docs.cowagent.ai/zh/channels/wecom) | ✅ | ✅ | ✅ | ✅ | |
| [微信客服](https://docs.cowagent.ai/zh/channels/wechat-kf) | ✅ | ✅ | ✅ | ✅ | |
| [微信公眾號](https://docs.cowagent.ai/zh/channels/wechatmp) | ✅ | ✅ | | ✅ | |
| [Telegram](https://docs.cowagent.ai/zh/channels/telegram) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Slack](https://docs.cowagent.ai/zh/channels/slack) | ✅ | ✅ | ✅ | | ✅ |
| [Discord](https://docs.cowagent.ai/zh/channels/discord) | ✅ | ✅ | ✅ | | ✅ |

> 飛書、企微智慧機器人支援在 Web 控制台內**掃碼一鍵接入**，無需公有 IP。詳見 [通道概覽](https://docs.cowagent.ai/zh/channels)。

<img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/screenshots/zh/web-console-chat.png" alt="CowAgent Web 控制台" width="800"/>

*Web 控制台是預設通道，也是統一的 Agent 設定和管理入口*

<br/>

## 🧠 記憶與知識庫

**長期記憶**採用三層架構：對話上下文（短期）→ 天級記憶（中期）→ MEMORY.md（長期）。每日自動執行**夢境蒸餾（Deep Dream）**，將分散記憶整合為精煉的長期記憶並生成敘事日記。詳見 [長期記憶](https://docs.cowagent.ai/zh/memory) · [夢境蒸餾](https://docs.cowagent.ai/zh/memory/deep-dream)。

**個人知識庫** 與按時間記錄的記憶不同，以**主題為維度**組織結構化知識。Agent 在對話中自動整理有價值資訊，維護交叉引用與索引，Web 控制台可視覺化瀏覽知識圖譜。詳見 [個人知識庫](https://docs.cowagent.ai/zh/knowledge)。

<table>
  <tr>
    <td width="50%">
      <img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/screenshots/zh/web-console-memory.png" alt="長期記憶" />
      <p align="center"><em>長期記憶 · 三層記憶 + 夢境蒸餾</em></p>
    </td>
    <td width="50%">
      <img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/screenshots/zh/web-console-knowledge.png" alt="個人知識庫" />
      <p align="center"><em>個人知識庫 · 自動整理的 Markdown Wiki</em></p>
    </td>
  </tr>
</table>

<br/>


## 🔧 工具與技能

**工具（Tools）** 是 Agent 作業系統資源的原子能力，**技能（Skills）** 是基於說明檔案的高階工作流，可組合多個工具完成複雜任務。

### 工具系統

**內建工具** 涵蓋檔案讀寫（`read` / `write` / `edit` / `ls`）、終端（`bash`）、檔案傳送（`send`）、記憶檢索（`memory`）、環境變數（`env_config`）、網頁獲取（`web_fetch`）、定時任務（`scheduler`）、聯網搜尋（`web_search`）、影像識別（`vision`）、瀏覽器自動化（`browser`）等常用能力。

**MCP 協議** 透過 [Model Context Protocol](https://modelcontextprotocol.io) 接入開放生態中的各種 MCP 服務，設定一次 `mcp.json` 即用即得，支援 stdio / SSE 協議、熱更新、零程式碼接入。

詳見 [工具概覽](https://docs.cowagent.ai/zh/tools) · [MCP 整合](https://docs.cowagent.ai/zh/tools/mcp)。

### 技能系統

- **[Skill Hub](https://skills.cowagent.ai/)** — 開源的技能廣場，瀏覽、搜尋、一鍵安裝
- **GitHub / ClawHub / URL 等** — 任意來源一鍵安裝
- **對話創造** — 透過 `skill-creator` 用對話快速生成自定義技能，可將工作流程或第三方介面直接固化為技能

```bash
/skill list                   # 檢視當前技能
/skill search <關鍵詞>         # 在技能廣場搜尋
/skill install <名稱>          # 一鍵安裝
```

詳見 [技能概覽](https://docs.cowagent.ai/zh/skills) · [建立技能](https://docs.cowagent.ai/zh/skills/create)。

<br/>

## 🏷 更新日誌

> **2026.08.20：** [v2.1.7](https://github.com/zhayujie/CowAgent/releases/tag/2.1.7) — 多工作空間與會話隔離、會話級權限模式、任務通知、桌面端最佳化、新模型接入

> **2026.08.12：** [v2.1.6](https://github.com/zhayujie/CowAgent/releases/tag/2.1.6) — 子 Agent 並行任務分配、推理強度設定、記憶向量庫可插拔、體驗與安全最佳化

> **2026.07.29：** [v2.1.5](https://github.com/zhayujie/CowAgent/releases/tag/2.1.5) — 工作空間與檔案預覽、基礎工具最佳化（檔案搜尋、寫入校驗、命令背景執行）、上下文壓縮（`/compact`）、提示詞一鍵最佳化、安全強化

> **2026.07.20：** [v2.1.4](https://github.com/zhayujie/CowAgent/releases/tag/2.1.4) — 桌面客戶端體驗最佳化、MCP 支援 OAuth 授權、飛書通道能力增強、定時任務與資料備份、新模型接入

> **2026.07.08：** [v2.1.3](https://github.com/zhayujie/CowAgent/releases/tag/2.1.3) — [桌面客戶端](https://cowagent.ai/zh/download/)正式發布（macOS / Windows）、知識庫文件管理增強、MCP 工具智能檢索、繁體中文支援、新模型接入

> **2026.06.18：** [v2.1.2](https://github.com/zhayujie/CowAgent/releases/tag/2.1.2) — Web 控制台升級（定時任務管理、知識庫分類、多模型自定義廠商）、自主進化最佳化、新模型接入（kimi-k2.7-code、glm-5.2）、安全加固和體驗最佳化

> **2026.06.09：** [v2.1.1](https://github.com/zhayujie/CowAgent/releases/tag/2.1.1) — 自進化能力、Web 控制台升級（訊息管理、多會話並行）、新模型接入（MiniMax-M3、qwen3.7-plus）、Python 3.13 支援

> **2026.06.01：** [v2.1.0](https://github.com/zhayujie/CowAgent/releases/tag/2.1.0) — 國際化支援、新增通道（Telegram、Discord、Slack、微信客服）、命令列互動升級、一鍵安裝指令碼最佳化、MCP Streamable HTTP 支援、新模型接入（claude-opus-4-8、MiMo）

完整更新歷史：[Release Notes](https://docs.cowagent.ai/zh/releases)

<br/>

## 🤝 社群與支援

加入 [**Discord 伺服器**](https://discord.gg/9U8eA8v9TR) 提問、分享技能、追蹤開發進度：

<a href="https://discord.gg/9U8eA8v9TR"><img src="https://img.shields.io/badge/Discord-加入社群-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="加入 Discord" /></a>

也歡迎在 GitHub [提交 Issue](https://github.com/zhayujie/CowAgent/issues)，或掃碼加入微信開源交流群：

<img width="130" src="https://img-1317903499.cos.ap-guangzhou.myqcloud.com/docs/open-community.png" />

也可透過以下方式獲取支援：

- 🐛 [提交 Issue](https://github.com/zhayujie/CowAgent/issues)
- 🤖 線上 AI 助手：[專案小助手](https://link-ai.tech/app/Kv2fXJcH)（基於專案知識庫）

<br/>

## 🔗 相關專案

- **[Cow Skill Hub](https://github.com/zhayujie/cow-skill-hub)** — 開源的 AI Agent 技能廣場，支援 CowAgent、OpenClaw、Claude Code 等多種 Agent
- **[bot-on-anything](https://github.com/zhayujie/bot-on-anything)** — 輕量大模型應用框架，支援 Slack、Telegram、Discord、Gmail 等海外平臺
- **[AgentMesh](https://github.com/MinimalFuture/AgentMesh)** — 開源多智慧體（Multi-Agent）框架，透過團隊協同解決複雜問題

<br/>

## 🏢 企業服務

<a href="https://link-ai.tech" target="_blank"><img width="650" src="https://cdn.link-ai.tech/image/link-ai-intro.jpg" /></a>

> [LinkAI](https://link-ai.tech/) 是面向企業和個人的一站式 AI 智慧體平臺，為 CowAgent 提供雲端託管和企業級支援：
>
> - **🚀 免部署線上執行**：無需伺服器即可建立 [CowAgent 線上助理](https://link-ai.tech/cowagent/create)，1 分鐘擁有專屬 Agent
> - **🧠 Agent 基礎設施**：聚合主流大模型、知識庫、資料庫、技能、工作流，提供開箱即用的 Agent 能力擴充
> - **🏢 企業級協作**：提供團隊協作、許可權分級、審計日誌、私有化部署等能力，讓 Agent 安全落地企業場景

**產品諮詢和企業服務** 可聯絡產品客服：

<img width="130" src="https://cdn.link-ai.tech/portal/linkai-customer-service.png" />

<br/>

## 🛠️ 開發與貢獻

歡迎各種形式的貢獻：新功能、Bug 修復、效能最佳化、文件完善，或向 [Skill Hub](https://skills.cowagent.ai/submit) 分享你的技能。請先閱讀 [CONTRIBUTING.md](/CONTRIBUTING.md) 瞭解如何開始，然後提交 Issue 討論或直接發起 PR。

歡迎 ⭐ Star 支援專案，並透過 Watch → Custom → Releases 訂閱新版本通知。也歡迎提交 PR、Issue 進行反饋。

## 🌟 貢獻者

![cow contributors](https://contrib.rocks/image?repo=zhayujie/CowAgent&max=1000)

<br/>

## ⚠️ 宣告

1. 本專案遵循 [MIT 開源協議](/LICENSE)，主要用於技術研究和學習。使用時請遵守所在地法律法規及相關政策，因使用本專案所產生的一切後果由使用者自行承擔。
2. **成本與安全：** Agent 模式 Token 消耗顯著高於普通對話，請根據效果與成本權衡選擇模型；Agent 具備訪問本地作業系統的能力，請謹慎選擇部署環境。
3. CowAgent 專案專注於開源技術開發，不會參與、授權或發行任何加密貨幣。

<br/>

## 📌 專案更名說明

本專案原名 `chatgpt-on-wechat`，於 2026.04.13 正式更名為 **CowAgent**。原 GitHub 地址已自動重定向，老使用者可選擇執行 `git remote set-url origin https://github.com/zhayujie/CowAgent.git` 更新本地遠端地址。
