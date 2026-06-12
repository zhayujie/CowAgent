# 微信客服（WeChat Customer Service）通道

> 与 `channel/wechatcom/`（企微自建应用）是两个**独立的 CoW 通道**：
>
> - 自建应用：**面向企业内部成员**（员工通过企业微信 App 与机器人对话）。
> - 微信客服：**面向外部微信用户**（普通微信用户通过链接/二维码进入对话）。
>
> 但底层都基于"企微自建应用"——本通道是**通过把一个企微自建应用绑定到微信客服账号**来实现 AI 接管对外咨询，详见 [LinkAI 微信客服接入文档](https://docs.link-ai.tech/platform/link-app/wechat-customer-service)。

## 一、接入流程概览

```
┌─────────────────────┐    ┌─────────────────────┐    ┌──────────────────┐
│ 1. 企业微信后台      │ →  │ 2. CoW 配置回调      │ →  │ 3. 绑定微信客服   │
│   创建一个自建应用   │    │   端口 9888          │    │   账号           │
└─────────────────────┘    └─────────────────────┘    └──────────────────┘
                                                              ↓
                                                   外部微信用户通过
                                                   链接/二维码 →
                                                   消息 → CoW Bot
```

> **重要**：建议**单独再创建一个企微自建应用**用于微信客服，**不要复用**已经接入员工内部使用的那个 `wechatcom_app` 应用，否则两个通道会争抢同一个回调地址。

## 二、企业微信后台配置

### 1. 创建企微自建应用

进入 企业微信管理后台 → **应用管理** → **创建应用**。

### 2. 收集字段

| 字段 | 来源 | 对应 CoW 配置项 |
|---|---|---|
| 企业ID（CorpId） | 「我的企业」最下方 | `wechat_kf_corp_id` |
| Secret | 进入应用详情 → 点击「查看」（会推送到管理员手机端，在手机上查看） | `wechat_kf_secret` |
| Token | 应用「接收消息 → 设置API接收」 | `wechat_kf_token` |
| EncodingAESKey | 应用「接收消息 → 设置API接收」 | `wechat_kf_aes_key` |

> AgentId 在本通道**不需要**（消息发送走的是 `cgi-bin/kf/send_msg`，不依赖 agent_id）。

### 3. 配置回调地址 + 可信 IP

在应用「**接收消息 → 设置API接收**」里填：

- URL：`http://<your-host>:9888/wxkf/`（公网必须可达）
- Token / EncodingAESKey：与下方 `config.json` 一致

回到应用详情页，把服务器公网 IP 填入「**企业可信IP**」。

### 4. 绑定微信客服账号

进入 企业微信后台 → **微信客服** → 创建客服账号 → **将该账号绑定到上一步创建的企微自建应用**。

绑定完成后，进入 **微信客服 → 微信客服账号详情** 页面，在「**接入链接**」一栏：

- 「复制链接」可拿到形如 `https://work.weixin.qq.com/kfid/kfcd83e5896b9ba07be` 的访问链接
- 「生成二维码」可拿到对应二维码

把链接或二维码推给微信客户使用即可。

## 三、CoW 配置（`config.json`）

```json
{
  "channel_type": "wechat_kf",

  "wechat_kf_corp_id": "ww1234567890abcdef",
  "wechat_kf_secret": "<企微应用的 Secret>",
  "wechat_kf_token": "<接收消息 Token>",
  "wechat_kf_aes_key": "<EncodingAESKey>",
  "wechat_kf_port": 9888
}
```

| 字段 | 说明 |
|---|---|
| `wechat_kf_corp_id` | 企业 ID |
| `wechat_kf_secret` | **绑定到微信客服**的那个企微自建应用的 Secret |
| `wechat_kf_token` | 该应用「接收消息」配置的 Token |
| `wechat_kf_aes_key` | 该应用「接收消息」配置的 EncodingAESKey |
| `wechat_kf_port` | 监听端口，默认 `9888` |

也支持环境变量：`WECHAT_KF_CORP_ID` / `WECHAT_KF_SECRET` / `WECHAT_KF_TOKEN` / `WECHAT_KF_AES_KEY`。

## 四、运行

```bash
python app.py
```

启动后日志里会看到：

```
[wechat_kf] WeCom customer-service channel started
[wechat_kf] Listening on http://0.0.0.0:9888/wxkf/
```

回到企微后台「设置API接收」点击保存——会触发 `GET /wxkf/?...&echostr=...`，CoW 通过 `crypto.check_signature` 校验后返回明文 `echostr`，验证成功。

## 五、支持的回复类型

| ReplyType | 是否支持 | 备注 |
|---|---|---|
| `TEXT` / `INFO` / `ERROR` | ✅ | 自动按 2048 字节切片分段发送 |
| `IMAGE`（本地） / `IMAGE_URL`（网络） | ✅ | 大图自动压缩到 10MB 以内 |
| `VOICE` | ✅ | 转 amr 后发送，>60s 自动切片 |
| `VIDEO_URL` | ✅ | 通过临时素材接口上传 |
| `FILE` | ✅ | |

## 六、参考文档

- [LinkAI 微信客服接入文档](https://docs.link-ai.tech/platform/link-app/wechat-customer-service)
- [企业微信开放接口 - 微信客服 - 接收消息](https://developer.work.weixin.qq.com/document/path/94670)
- [企业微信开放接口 - 微信客服 - 发送消息](https://developer.work.weixin.qq.com/document/path/95122)
