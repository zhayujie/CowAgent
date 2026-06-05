<p align="center"><img src="https://github.com/user-attachments/assets/eca9a9ec-8534-4615-9e0f-96c5ac1d10a3" alt="CowAgent" width="420" /></p>

<p align="center">
  <a href="https://github.com/zhayujie/CowAgent/releases/latest"><img src="https://img.shields.io/github/v/release/zhayujie/CowAgent" alt="Latest release"></a>
  <a href="https://github.com/zhayujie/CowAgent/blob/master/LICENSE"><img src="https://img.shields.io/github/license/zhayujie/CowAgent" alt="License: MIT"></a>
  <a href="https://github.com/zhayujie/CowAgent"><img src="https://img.shields.io/github/stars/zhayujie/CowAgent?style=flat-square" alt="Stars"></a> <br/>
  [<a href="../../README.md">English</a>] | [<a href="../zh/README.md">中文</a>] | [日本語]
</p>

**CowAgent** は、自律的にタスクを計画し、コンピュータや外部リソースを操作し、Skill を作成・実行し、パーソナルナレッジベースと長期記憶でユーザーとともに成長するオープンソースのスーパー AI アシスタントです。エンドツーエンドの Agent Harness のリファレンス実装の一つでもあります。

CowAgent は軽量でデプロイしやすく、拡張性に優れています。主要な LLM プロバイダーをそのまま組み込み、Web や主要な IM プラットフォーム上で動作。個人 PC やサーバー上で 24 時間 365 日稼働できます。

<p align="center">
  <a href="https://cowagent.ai/">🌐 ウェブサイト</a> &nbsp;·&nbsp;
  <a href="https://docs.cowagent.ai/ja/intro/index">📖 ドキュメント</a> &nbsp;·&nbsp;
  <a href="https://docs.cowagent.ai/ja/guide/quick-start">🚀 クイックスタート</a> &nbsp;·&nbsp;
  <a href="https://skills.cowagent.ai/">🧩 Skill Hub</a> &nbsp;·&nbsp;
  <a href="https://link-ai.tech/cowagent/create">☁️ オンラインで試す</a>
</p>

<br/>

## 🌟 主な機能

| 機能 | 説明 |
| :--- | :--- |
| [タスク計画](https://docs.cowagent.ai/ja/intro/architecture) | 複雑なタスクを分解し、目標達成までツールを繰り返し呼び出して段階的に実行 |
| [長期記憶](https://docs.cowagent.ai/ja/memory/index) | 三層構造（コンテキスト → デイリー → コア）、Deep Dream による自動蒸留、キーワードとベクトルのハイブリッド検索 |
| [ナレッジベース](https://docs.cowagent.ai/ja/knowledge/index) | 構造化された知識を Markdown Wiki として自動整理し、進化し続けるナレッジグラフを可視化ブラウジング |
| [Skill](https://docs.cowagent.ai/ja/skills/index) | [Skill Hub](https://skills.cowagent.ai/)、GitHub、ClawHub からワンクリックでインストール；対話によるカスタム Skill 作成にも対応 |
| [ツール](https://docs.cowagent.ai/ja/tools/index) | ファイル I/O、ターミナル、ブラウザ、スケジューラ、記憶検索、Web 検索など 10+ の組み込みツール — MCP プロトコルに完全対応 |
| [チャネル](https://docs.cowagent.ai/ja/channels/index) | 一つの Agent で Web、WeChat、Feishu、DingTalk、WeCom、QQ、公式アカウント、Telegram、Slack を同時にサポート |
| マルチモーダル | テキスト・画像・音声・ファイルをフルサポート — 認識・生成・双方向送受信 |
| [モデル](https://docs.cowagent.ai/ja/models/index) | Claude、GPT、Gemini、DeepSeek、GLM、Qwen、Kimi、MiniMax、Doubao など、設定 1 行で切り替え可能 |
| [デプロイ](https://docs.cowagent.ai/ja/guide/quick-start) | ワンラインインストーラー、統合された Web コンソール、複数のデプロイモード（ローカル / Docker / サーバー） |

<br/>

## 🏗️ アーキテクチャ

<img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/architecture/en/architecture.jpg" alt="CowAgent Architecture" width="750"/>

CowAgent は完全な **Agent Harness** です：メッセージは各種**チャネル**から流入し、**Agent Core** が記憶・知識・利用可能なツール／Skill を組み合わせてタスクを計画・判断、**モデル**が応答を生成し、結果は元のチャネルに返されます。各レイヤーは疎結合で、独立して拡張可能です。

詳細は [アーキテクチャ](https://docs.cowagent.ai/ja/intro/architecture) を参照してください。

<br/>

## 🚀 クイックスタート

依存関係のインストール、設定、起動を自動で行うワンラインインストーラーを提供しています：

**Linux / macOS:**

```bash
bash <(curl -fsSL https://cdn.link-ai.tech/code/cow/run.sh)
```

**Windows (PowerShell):**

```powershell
irm https://cdn.link-ai.tech/code/cow/run.ps1 | iex
```

**Docker:**

```bash
curl -O https://cdn.link-ai.tech/code/cow/docker-compose.yml
docker compose up -d
```

起動後、`http://localhost:9899` にアクセスして **Web コンソール**を開くと、モデル設定・チャネル接続・Skill インストールがすべてここで完結します。

> サーバーデプロイでコンソールに公開アクセスする場合は、`config.json` の `web_host` を `0.0.0.0` に設定してください（あわせて `web_password` の設定も強く推奨）。その後 `http://<server-ip>:9899` にアクセスし、ファイアウォール／セキュリティグループで `9899` ポートを開放することも忘れずに。

> 📖 詳細ガイド: [クイックスタート](https://docs.cowagent.ai/ja/guide/quick-start) · [ソースからインストール](https://docs.cowagent.ai/ja/guide/manual-install) · [アップグレード](https://docs.cowagent.ai/ja/guide/upgrade)

インストール後は、[`cow` CLI](https://docs.cowagent.ai/ja/cli/index) でサービスを管理できます：

```bash
cow start | stop | restart        # サービス制御
cow status | logs                  # ステータスとログ
cow update                         # 最新コード取得後に再起動
cow skill install <名前>           # Skill のインストール
cow install-browser                # ブラウザツールのインストール
```

<br/>

## 🤖 モデル

CowAgent は主要な LLM プロバイダーすべてに対応しています。**チャット、画像認識、画像生成、ASR/TTS、埋め込み（Embedding）** の各機能はそれぞれ別のベンダーで設定可能です。

| プロバイダー | 代表的なモデル | チャット | 画像認識 | 画像生成 | ASR | TTS | Embedding |
| --- | --- | :-: | :-: | :-: | :-: | :-: | :-: |
| [Claude](https://docs.cowagent.ai/ja/models/claude) | claude-opus-4-8 | ✅ | ✅ | | | | |
| [OpenAI](https://docs.cowagent.ai/ja/models/openai) | gpt-5.5、o シリーズ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Gemini](https://docs.cowagent.ai/ja/models/gemini) | gemini-3.5-flash | ✅ | ✅ | ✅ | | | |
| [DeepSeek](https://docs.cowagent.ai/ja/models/deepseek) | deepseek-v4-flash / pro | ✅ | | | | | |
| [Qwen](https://docs.cowagent.ai/ja/models/qwen) | qwen3.7-max | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [GLM](https://docs.cowagent.ai/ja/models/glm) | glm-5.1、glm-5v-turbo | ✅ | ✅ | | ✅ | | ✅ |
| [Doubao](https://docs.cowagent.ai/ja/models/doubao) | doubao-seed-2.0 シリーズ | ✅ | ✅ | ✅ | | | ✅ |
| [Kimi](https://docs.cowagent.ai/ja/models/kimi) | kimi-k2.6 | ✅ | ✅ | | | | |
| [MiniMax](https://docs.cowagent.ai/ja/models/minimax) | MiniMax-M2.7 | ✅ | ✅ | ✅ | | ✅ | |
| [ERNIE](https://docs.cowagent.ai/ja/models/qianfan) | ernie-5.1 | ✅ | ✅ | | | | |
| [MiMo](https://docs.cowagent.ai/ja/models/mimo) | mimo-v2.5-pro / v2.5 | ✅ | ✅ | | | ✅ | |
| [LinkAI](https://docs.cowagent.ai/ja/models/linkai) | 1 つの Key で 100+ モデルに接続 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [カスタム](https://docs.cowagent.ai/ja/models/custom) | ローカルモデル / サードパーティプロキシ | ✅ | | | | | |

> Web コンソールでの設定が推奨されており、ファイルを手動編集する必要はありません。手動設定については各プロバイダーのドキュメントおよび [モデル概要](https://docs.cowagent.ai/ja/models/index) を参照してください。

<br/>

## 💬 チャネル

一つの Agent インスタンスで複数のチャネルを同時に提供できます。`channel_type` 設定で切り替えるか、複数のチャネルを並列実行できます。

| チャネル | テキスト | 画像 | ファイル | 音声 | グループ |
| --- | :-: | :-: | :-: | :-: | :-: |
| [Web コンソール](https://docs.cowagent.ai/ja/channels/web)（デフォルト） | ✅ | ✅ | ✅ | ✅ | |
| [WeChat](https://docs.cowagent.ai/ja/channels/weixin) | ✅ | ✅ | ✅ | ✅ | |
| [Feishu / Lark](https://docs.cowagent.ai/ja/channels/feishu) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [DingTalk](https://docs.cowagent.ai/ja/channels/dingtalk) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [WeCom Bot](https://docs.cowagent.ai/ja/channels/wecom-bot) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [QQ](https://docs.cowagent.ai/ja/channels/qq) | ✅ | ✅ | ✅ | | ✅ |
| [WeCom App](https://docs.cowagent.ai/ja/channels/wecom) | ✅ | ✅ | ✅ | ✅ | |
| [WeChat カスタマーサービス](https://docs.cowagent.ai/ja/channels/wechat-kf) | ✅ | ✅ | ✅ | ✅ | |
| [WeChat 公式アカウント](https://docs.cowagent.ai/ja/channels/wechatmp) | ✅ | ✅ | | ✅ | |
| [Telegram](https://docs.cowagent.ai/ja/channels/telegram) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Slack](https://docs.cowagent.ai/ja/channels/slack) | ✅ | ✅ | ✅ | | ✅ |
| [Discord](https://docs.cowagent.ai/ja/channels/discord) | ✅ | ✅ | ✅ | | ✅ |

> Feishu と WeCom Bot は **Web コンソール内で QR コードをスキャンするだけで接続**できます — パブリック IP は不要です。詳細は [チャネル概要](https://docs.cowagent.ai/ja/channels/index) を参照してください。

<img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/screenshots/en/web-console-chat.png" alt="CowAgent Web Console" width="800"/>

*Web コンソールはデフォルトのチャネルであると同時に、Agent の設定・管理を統一的に行う場でもあります。*

<br/>

## 🧠 記憶とナレッジベース

**長期記憶**は三層構造：会話コンテキスト（短期）→ デイリー記憶（中期）→ MEMORY.md（長期）。毎晩の **Deep Dream** が散在する記憶を洗練された長期記憶とナラティブな日記に蒸留します。詳細は [長期記憶](https://docs.cowagent.ai/ja/memory/index) · [Deep Dream](https://docs.cowagent.ai/ja/memory/deep-dream) を参照してください。

**パーソナルナレッジベース**は時系列の記憶とは異なり、構造化された知識を**トピック単位**で整理します。Agent が会話中に有用な情報を自動でキュレーションし、相互参照とインデックスを維持し、Web コンソールでナレッジグラフを可視化できます。詳細は [パーソナルナレッジベース](https://docs.cowagent.ai/ja/knowledge/index) を参照してください。

<table>
  <tr>
    <td width="50%">
      <img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/screenshots/en/web-console-memory.png" alt="長期記憶" />
      <p align="center"><em>長期記憶 · 三層構造 + Deep Dream</em></p>
    </td>
    <td width="50%">
      <img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/screenshots/en/web-console-knowledge.png" alt="パーソナルナレッジベース" />
      <p align="center"><em>ナレッジベース · 自動キュレーションされた Markdown Wiki</em></p>
    </td>
  </tr>
</table>

<br/>

## 🔧 ツールと Skill

**ツール（Tools）** は Agent がシステムリソースを操作するためのアトミックな機能です。**Skill（Skills）** はマニフェストファイルで定義される高レベルのワークフローで、複数のツールを組み合わせて複雑なタスクを完了します。

### ツールシステム

**組み込みツール**には、ファイル I/O（`read` / `write` / `edit` / `ls`）、ターミナル（`bash`）、ファイル送信（`send`）、記憶検索（`memory`）、環境変数（`env_config`）、Web フェッチ（`web_fetch`）、スケジューラ（`scheduler`）、Web 検索（`web_search`）、画像認識（`vision`）、ブラウザ自動化（`browser`）などが含まれます。

**MCP プロトコル**は [Model Context Protocol](https://modelcontextprotocol.io) のオープンエコシステムを統合します。`mcp.json` を一度設定すれば即利用可能で、stdio / SSE トランスポート、ホットリロード、ノーコード統合をサポートします。

詳細: [ツール概要](https://docs.cowagent.ai/ja/tools/index) · [MCP 統合](https://docs.cowagent.ai/ja/tools/mcp)。

### Skill システム

- **[Skill Hub](https://skills.cowagent.ai/)** — オープン Skill マーケットプレイス：閲覧、検索、ワンクリックインストール
- **GitHub / ClawHub / URL など** — 任意のソースからワンクリックでインストール
- **対話による作成** — `skill-creator` を使って対話でカスタム Skill を生成；ワークフローやサードパーティ API を再利用可能な Skill に変換

```bash
/skill list                   # インストール済み Skill の一覧
/skill search <キーワード>     # マーケットプレイスで検索
/skill install <名前>          # ワンクリックインストール
```

詳細: [Skill 概要](https://docs.cowagent.ai/ja/skills/index) · [Skill 作成](https://docs.cowagent.ai/ja/skills/create)。

<br/>

## 🏷 更新履歴

> **2026.05.22:** [v2.0.9](https://github.com/zhayujie/CowAgent/releases/tag/2.0.9) — モデル管理、MCP プロトコル対応、ブラウザセッション永続化、新モデル（gpt-5.5、gemini-3.5-flash、qwen3.7-max）、デプロイのセキュリティ強化。

> **2026.05.06:** [v2.0.8](https://github.com/zhayujie/CowAgent/releases/tag/2.0.8) — Feishu チャネル全面アップグレード（音声、ストリーミング、QR 接続）、DeepSeek V4 と Baidu Qianfan 対応、スケジューラツール強化。

> **2026.04.22:** [v2.0.7](https://github.com/zhayujie/CowAgent/releases/tag/2.0.7) — 組み込み画像生成（GPT Image 2、Nano Banana）、新モデル（Kimi K2.6、Claude Opus 4.7、GLM 5.1）、ナレッジベースと記憶の強化。

> **2026.04.14:** [v2.0.6](https://github.com/zhayujie/CowAgent/releases/tag/2.0.6) — ナレッジベース、Deep Dream 記憶蒸留、スマートコンテキスト圧縮、マルチセッション Web コンソール。

> **2026.04.01:** [v2.0.5](https://github.com/zhayujie/CowAgent/releases/tag/2.0.5) — Cow CLI、Skill Hub オープンソース化、ブラウザツール、WeCom Bot QR 接続。

> **2026.02.03:** [v2.0.0](https://github.com/zhayujie/CowAgent/releases/tag/2.0.0) — マルチステップタスク計画、長期記憶、Skill フレームワークを備えたスーパー Agent アシスタントへの全面アップグレード。

完全な履歴: [リリースノート](https://docs.cowagent.ai/ja/releases/overview)

<br/>

## 🤝 コミュニティとサポート

GitHub で [Issue を報告](https://github.com/zhayujie/CowAgent/issues) するか、下記 QR コードをスキャンして WeChat コミュニティに参加してください：

<img width="130" src="https://img-1317903499.cos.ap-guangzhou.myqcloud.com/docs/open-community.png">

<br/>

## 🔗 関連プロジェクト

- **[Cow Skill Hub](https://github.com/zhayujie/cow-skill-hub)** — AI エージェント向けのオープン Skill マーケットプレイス；CowAgent、OpenClaw、Claude Code などに対応
- **[bot-on-anything](https://github.com/zhayujie/bot-on-anything)** — 軽量な LLM アプリケーションフレームワーク；Slack、Telegram、Discord、Gmail などに対応
- **[AgentMesh](https://github.com/MinimalFuture/AgentMesh)** — チーム協調による複雑な問題解決のためのオープンソースのマルチエージェントフレームワーク

<br/>

## 🏢 エンタープライズサービス

[**LinkAI**](https://link-ai.tech/) は企業や開発者向けのワンストップ AI Agent プラットフォームで、CowAgent にマネージドホスティングとエンタープライズグレードのサポートを提供します：

- **🚀 デプロイ不要のホスト型ランタイム** — [CowAgent オンラインアシスタント](https://link-ai.tech/cowagent/create) を 1 分以内に起動、サーバー不要
- **🧠 Agent インフラ** — 主要 LLM・ナレッジベース・データベース・Skill・ワークフローへの統一アクセス。CowAgent の機能を拡張する、すぐに使えるビルディングブロック
- **🏢 チーム & エンタープライズ機能** — ワークスペース、ロールベースのアクセス制御、監査ログ、本番運用向けプライベートデプロイ

エンタープライズに関するお問い合わせ：**sales@simple-future.tech** または [QR コードをスキャン](https://cdn.link-ai.tech/consultant.jpg) して WeChat でお問い合わせください。

<br/>

## 🛠️ 開発とコントリビューション

新しいチャネルの追加を歓迎します — [Feishu チャネル](https://github.com/zhayujie/CowAgent/blob/master/channel/feishu/feishu_channel.py) を参考にカスタムチャネルを実装できます。新しい Skill のコントリビューションも [Skill Hub](https://skills.cowagent.ai/submit) で受け付けています。

⭐ Star でプロジェクトの更新をフォローしてください。PR や Issue の提出も歓迎します。

## 🌟 コントリビューター

![cow contributors](https://contrib.rocks/image?repo=zhayujie/CowAgent&max=1000)

<br/>

## ⚠️ 免責事項

1. 本プロジェクトは [MIT License](/LICENSE) に基づき、技術研究と学習を目的としています。利用者は所在地の法令・規制を遵守する必要があり、本プロジェクトの利用に起因するいかなる結果についてもメンテナーは責任を負いません。
2. **コストと安全性：** Agent モードは通常のチャットよりトークン消費が大幅に多いため、品質とコストのバランスを考慮してモデルを選択してください。Agent はローカル OS にアクセスできるため、信頼できる環境にのみデプロイしてください。
3. CowAgent は純粋なオープンソースプロジェクトであり、暗号通貨の発行・参加・承認は一切行いません。

<br/>

## 📌 プロジェクト改名のお知らせ

本プロジェクトは旧名 `chatgpt-on-wechat` から、2026.04.13 に **CowAgent** へ正式に改名されました。元の GitHub URL は自動的にリダイレクトされます。既存ユーザーは `git remote set-url origin https://github.com/zhayujie/CowAgent.git` でローカルのリモートを更新できます。
