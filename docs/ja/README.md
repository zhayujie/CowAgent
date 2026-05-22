<p align="center"><img src="https://github.com/user-attachments/assets/eca9a9ec-8534-4615-9e0f-96c5ac1d10a3" alt="CowAgent" width="550" /></p>

<p align="center">
  <a href="https://github.com/zhayujie/CowAgent/releases/latest"><img src="https://img.shields.io/github/v/release/zhayujie/CowAgent" alt="Latest release"></a>
  <a href="https://github.com/zhayujie/CowAgent/blob/master/LICENSE"><img src="https://img.shields.io/github/license/zhayujie/CowAgent" alt="License: MIT"></a>
  <a href="https://github.com/zhayujie/CowAgent"><img src="https://img.shields.io/github/stars/zhayujie/CowAgent?style=flat-square" alt="Stars"></a> <br/>
  [<a href="https://github.com/zhayujie/CowAgent/blob/master/README.md">中文</a>] | [<a href="https://github.com/zhayujie/CowAgent/blob/master/docs/en/README.md">English</a>] | [日本語]
</p>

**CowAgent** はLLMを搭載したAIスーパーアシスタントです。自律的なタスク計画、コンピュータや外部リソースの操作、Skillの作成・実行、長期記憶とパーソナルナレッジベースによる継続的な成長が可能です。柔軟なモデル切り替えに対応し、テキスト・音声・画像・ファイルを処理でき、WeChat、Web、Feishu（飛書）、DingTalk（釘釘）、WeCom Bot（企業微信ボット）、WeComアプリ、WeChat公式アカウントに統合可能で、個人のPCやサーバー上で24時間365日稼働できます。

<p align="center">
  <a href="https://cowagent.ai/">🌐 ウェブサイト</a> &nbsp;·&nbsp;
  <a href="https://docs.cowagent.ai/en/intro/index">📖 ドキュメント</a> &nbsp;·&nbsp;
  <a href="https://docs.cowagent.ai/en/guide/quick-start">🚀 クイックスタート</a> &nbsp;·&nbsp;
  <a href="https://skills.cowagent.ai/">🧩 Skill Hub</a> &nbsp;·&nbsp;
  <a href="https://link-ai.tech/cowagent/create">☁️ オンラインで試す</a>
</p>

## はじめに

> CowAgentは、すぐに使えるAIスーパーアシスタントであると同時に、高い拡張性を持つAgentフレームワークでもあります。新しいモデルインターフェース、チャネル、組み込みツール、Skillシステムを拡張することで、さまざまなカスタマイズニーズに柔軟に対応できます。

- ✅ **自律的タスク計画**: 複雑なタスクを理解し、自律的に実行計画を立て、目標達成までツールを呼び出しながら継続的に思考します。
- ✅ **長期記憶**: 会話の記憶をローカルファイルやデータベースに自動的に永続化します。コアメモリ、デイリーメモリ、Deep Dream 蒸留を含み、キーワード検索やベクトル検索に対応しています。
- ✅ **パーソナルナレッジベース**: 構造化された知識を自動整理し、相互参照によるナレッジグラフを構築。Web での可視化ブラウジングと対話による管理をサポートします。
- ✅ **Skillシステム**: Skillの作成・実行エンジンを実装。[Skill Hub](https://skills.cowagent.ai)、GitHubなどからSkillをインストールでき、会話を通じたカスタムSkill作成もサポートしています。
- ✅ **ツールシステム**: ファイル読み書き、ターミナル実行、ブラウザ操作、スケジュールタスク、メッセージ送信などの組み込みツールを提供。Agentが自律的に呼び出して複雑なタスクを完了します。
- ✅ **CLIシステム**: ターミナルコマンドとチャットコマンドを提供し、プロセス管理、Skillインストール、設定変更などの操作をサポートします。
- ✅ **マルチモーダルメッセージ**: テキスト、画像、音声、ファイルなど、さまざまなメッセージタイプの解析・処理・生成・送信に対応しています。
- ✅ **複数モデル対応**: DeepSeek、MiniMax、Claude、Gemini、OpenAI、GLM、Qwen、Doubao、Kimiなど、主要なモデルプロバイダーに対応しています。
- ✅ **マルチプラットフォームデプロイ**: ローカルPCやサーバー上で実行でき、WeChat、Web、Feishu、DingTalk、WeChat公式アカウント、WeComアプリケーションに統合可能です。

## 免責事項

1. 本プロジェクトは [MIT License](/LICENSE) に基づいており、技術研究・学習を目的としています。利用者は現地の法律、規制、ポリシー、企業の社則を遵守する必要があります。違法行為や権利侵害となる利用は禁止されています。
2. Agentモードは通常のチャットモードよりも多くのトークンを消費します。効果とコストに基づいてモデルを選択してください。AgentはホストOSにアクセスできるため、信頼できる環境にデプロイしてください。
3. CowAgentはオープンソース開発に注力しており、いかなる暗号通貨の発行・参加・承認も行っていません。

## デモ

オンラインで試す（デプロイ不要）: [CowAgent](https://link-ai.tech/cowagent/create)

## 更新履歴

> **2026.04.14:** [v2.0.6](https://github.com/zhayujie/CowAgent/releases/tag/2.0.6) — ナレッジベース、Deep Dream 記憶蒸留、スマートコンテキスト圧縮、Web コンソールアップグレード。

> **2026.04.01:** [v2.0.5](https://github.com/zhayujie/CowAgent/releases/tag/2.0.5) — Cow CLI、Skill Hubオープンソース化、ブラウザツール、WeCom Botスキャン作成など。

> **2026.02.27:** [v2.0.2](https://github.com/zhayujie/CowAgent/releases/tag/2.0.2) — Webコンソールの全面刷新（ストリーミングチャット、モデル/Skill/メモリ/チャネル/スケジューラ/ログ管理）、マルチチャネル同時実行、セッション永続化、Gemini 3.1 Pro / Claude 4.6 Sonnet / Qwen3.5 Plusなど新モデル追加。

> **2026.02.13:** [v2.0.1](https://github.com/zhayujie/CowAgent/releases/tag/2.0.1) — 組み込みWeb検索ツール、スマートコンテキストトリミング、ランタイム情報の動的更新、Windows互換性、スケジューラのメモリ喪失やFeishu接続問題などの修正。

> **2026.02.03:** [v2.0.0](https://github.com/zhayujie/CowAgent/releases/tag/2.0.0) — マルチステップタスク計画、長期記憶、組み込みツール、Skillフレームワーク、新モデル、チャネル最適化を備えたAIスーパーアシスタントへの全面アップグレード。

> **2025.05.23:** [v1.7.6](https://github.com/zhayujie/CowAgent/releases/tag/1.7.6) — Webチャネル最適化、AgentMeshマルチエージェントプラグイン、Baidu TTS、claude-4-sonnet/opus対応。

> **2025.04.11:** [v1.7.5](https://github.com/zhayujie/CowAgent/releases/tag/1.7.5) — wechatferryプロトコル、DeepSeekモデル、Tencent Cloud音声、ModelScope・Gitee-AI対応。

> **2024.12.13:** [v1.7.4](https://github.com/zhayujie/CowAgent/releases/tag/1.7.4) — Gemini 2.0モデル、Webチャネル、メモリリーク修正。

全更新履歴: [リリースノート](https://docs.cowagent.ai/en/releases/overview)

<br/>

## 🚀 クイックスタート

本プロジェクトは、インストール・設定・起動・管理をワンクリックで行えるスクリプトを提供しています：

**Linux / macOS:**
```bash
bash <(curl -fsSL https://cdn.link-ai.tech/code/cow/run.sh)
```

**Windows (PowerShell):**
```powershell
irm https://cdn.link-ai.tech/code/cow/run.ps1 | iex
```

実行後、デフォルトでWebサービスが起動します。`http://localhost:9899/chat` にアクセスしてチャットを開始できます。

スクリプトの使い方: [ワンクリックインストール](https://docs.cowagent.ai/ja/guide/quick-start)。インストール後は `cow start`、`cow stop` などの [CLI コマンド](https://docs.cowagent.ai/ja/cli/index)でサービスを管理できます。

### 手動インストール

**1. プロジェクトのクローン**

```bash
git clone https://github.com/zhayujie/CowAgent
cd CowAgent/
```

**2. 依存関係のインストール**

```bash
pip3 install -r requirements.txt
pip3 install -r requirements-optional.txt   # 任意ですが推奨
```

**3. Cow CLI のインストール（推奨）**

```bash
pip3 install -e .
```

インストール後、`cow` コマンドでサービス管理（起動、停止、更新など）やSkill管理ができます。[コマンドドキュメント](https://docs.cowagent.ai/ja/cli/index)を参照してください。

**4. ブラウザのインストール（任意）**

Agentにブラウザ操作（Webページへのアクセス、フォーム入力など）が必要な場合：

```bash
cow install-browser
```

`playwright` と Chromium を自動インストールします。[ブラウザツールドキュメント](https://docs.cowagent.ai/ja/tools/browser)を参照してください。

**5. 設定**

```bash
cp config-template.json config.json
```

`config.json` にモデルのAPIキーとチャネルタイプを記入してください。詳細は[設定ドキュメント](https://docs.cowagent.ai/en/guide/manual-install)を参照してください。

**6. 実行**

```bash
cow start              # 推奨、Cow CLI が必要
python3 app.py         # または直接実行
```

サーバーデプロイでは、`cow` コマンドでサービスを管理できます：

```bash
cow start              # バックグラウンドで起動
cow stop               # サービス停止
cow restart            # サービス再起動
cow status             # 実行状態を確認
cow logs               # ログを表示
cow update             # 最新コードを取得して再起動
```

または従来の方法で実行：

```bash
nohup python3 app.py & tail -f nohup.out
```

### Dockerデプロイ

```bash
curl -O https://cdn.link-ai.tech/code/cow/docker-compose.yml
# docker-compose.yml を編集して設定を記入
sudo docker compose up -d
sudo docker logs -f chatgpt-on-wechat
```

<br/>

## モデル

主要なモデルプロバイダーに対応しています。Agentモードの推奨モデル：

| プロバイダー | 推奨モデル |
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

各モデルの詳細設定については、[モデルドキュメント](https://docs.cowagent.ai/en/models/index)を参照してください。

### Coding Plan

Coding Planは各プロバイダーが提供する月額サブスクリプションパッケージで、高頻度のAgent利用に最適です。すべてのプロバイダーはOpenAI互換モードでアクセスできます：

```json
{
  "bot_type": "openai",
  "model": "MODEL_NAME",
  "open_ai_api_base": "PROVIDER_CODING_PLAN_API_BASE",
  "open_ai_api_key": "YOUR_API_KEY"
}
```

- `bot_type`: `openai` を指定
- `model`: プロバイダーがサポートするモデル名
- `open_ai_api_base`: プロバイダーのCoding Plan API Base（標準の従量課金とは異なります）
- `open_ai_api_key`: プロバイダーのCoding Plan APIキー

> 注意：Coding PlanのAPI BaseとAPIキーは、通常の従量課金のものとは別です。各プロバイダーのプラットフォームから取得してください。

対応プロバイダーには、Alibaba Cloud、MiniMax、Zhipu GLM、Kimi、Volcengineなどがあります。各プロバイダーの詳細設定については、[Coding Planドキュメント](https://docs.cowagent.ai/en/models/coding-plan)を参照してください。

<br/>

## チャネル

複数のプラットフォームに対応しています。`config.json` の `channel_type` を設定して切り替えます：

| チャネル | `channel_type` | ドキュメント |
| --- | --- | --- |
| WeChat | `weixin` | [WeChat設定](https://docs.cowagent.ai/ja/channels/weixin) |
| Web（デフォルト） | `web` | [Webチャネル](https://docs.cowagent.ai/en/channels/web) |
| Feishu（飛書） | `feishu` | [Feishu設定](https://docs.cowagent.ai/en/channels/feishu) |
| DingTalk（釘釘） | `dingtalk` | [DingTalk設定](https://docs.cowagent.ai/en/channels/dingtalk) |
| WeCom Bot | `wecom_bot` | [WeCom Bot設定](https://docs.cowagent.ai/en/channels/wecom-bot) |
| WeComアプリ | `wechatcom_app` | [WeCom設定](https://docs.cowagent.ai/en/channels/wecom) |
| WeChat公式アカウント | `wechatmp` / `wechatmp_service` | [WeChat公式アカウント設定](https://docs.cowagent.ai/en/channels/wechatmp) |
| ターミナル | `terminal` | — |

複数チャネルを同時に有効化できます。カンマ区切りで指定してください：`"channel_type": "feishu,dingtalk"`

<br/>

## エンタープライズサービス

<a href="https://link-ai.tech" target="_blank"><img width="720" src="https://cdn.link-ai.tech/image/link-ai-intro.jpg"></a>

> [LinkAI](https://link-ai.tech/) は、企業や開発者向けのワンストップAIエージェントプラットフォームです。マルチモーダルLLM、ナレッジベース、Agentプラグイン、ワークフローを統合しています。主要プラットフォームへのワンクリック統合、SaaSおよびプライベートデプロイに対応しています。

<br/>

## 🔗 関連プロジェクト

- [Cow Skill Hub](https://github.com/zhayujie/cow-skill-hub): AIエージェント向けのオープンSkillマーケットプレイス。CowAgent、OpenClaw、Claude Codeなどで利用可能なSkillの閲覧・検索・インストール・公開が可能。
- [bot-on-anything](https://github.com/zhayujie/bot-on-anything): 軽量で高い拡張性を持つLLMアプリケーションフレームワーク。Slack、Telegram、Discord、Gmailなどに対応。
- [AgentMesh](https://github.com/MinimalFuture/AgentMesh): エージェントチームの協調による複雑な問題解決のためのオープンソースのマルチエージェントフレームワーク。

## 🔎 よくある質問

FAQ: <https://github.com/zhayujie/CowAgent/wiki/FAQs>

## 🛠️ コントリビューション

新しいチャネルの追加を歓迎します。[Feishuチャネル](https://github.com/zhayujie/CowAgent/blob/master/channel/feishu/feishu_channel.py)を参考にしてください。また、新しいSkillのコントリビューションも歓迎します。[Skill作成ドキュメント](https://docs.cowagent.ai/ja/skills/create)を参照するか、[Skill Hub](https://skills.cowagent.ai/submit)に提出してください。

## ✉ お問い合わせ

PRやIssueの提出を歓迎します。🌟 Starでプロジェクトをサポートしてください。ご質問がある場合は、[FAQリスト](https://github.com/zhayujie/CowAgent/wiki/FAQs)を確認するか、[Issues](https://github.com/zhayujie/CowAgent/issues)を検索してください。

## 🌟 コントリビューター

![cow contributors](https://contrib.rocks/image?repo=zhayujie/CowAgent&max=1000)
