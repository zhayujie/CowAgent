# 飞书Channel使用说明

飞书Channel支持两种事件接收模式，可以根据部署环境灵活选择。

## 模式对比

| 模式 | 适用场景 | 优点 | 缺点 |
|------|---------|------|------|
| **webhook** | 生产环境 | 稳定可靠，官方推荐 | 需要公网IP或域名 |
| **websocket** | 本地开发 | 无需公网IP，开发便捷 | 需要额外依赖 |

## 配置说明

### 基础配置

在 `config.json` 中添加以下配置:

```json
{
  "channel_type": "feishu",
  "feishu_app_id": "cli_xxxxx",
  "feishu_app_secret": "your_app_secret",
  "feishu_token": "your_verification_token",
  "feishu_bot_name": "你的机器人名称",
  "feishu_event_mode": "webhook",
  "feishu_port": 9891
}
```

### 配置项说明

- `feishu_app_id`: 飞书应用的App ID
- `feishu_app_secret`: 飞书应用的App Secret
- `feishu_token`: 事件订阅的Verification Token
- `feishu_bot_name`: 机器人名称(用于群聊@判断)
- `feishu_event_mode`: 事件接收模式，可选值:
  - `"websocket"`: 长连接模式(默认)
  - `"webhook"`: HTTP服务器模式
- `feishu_port`: webhook模式下的HTTP服务端口(默认9891)

## 模式一: Webhook模式(推荐生产环境)

### 1. 配置

```json
{
  "feishu_event_mode": "webhook",
  "feishu_port": 9891
}
```

### 2. 启动服务

```bash
python3 app.py
```

服务将在 `http://0.0.0.0:9891` 启动。

### 3. 配置飞书应用

1. 登录[飞书开放平台](https://open.feishu.cn/)
2. 进入应用详情 -> 事件订阅
3. 选择 **将事件发送至开发者服务器**
4. 填写请求地址: `http://your-domain:9891/`
5. 添加事件: `im.message.receive_v1` (接收消息v2.0)
6. 保存配置

### 4. 注意事项

- 需要有公网IP或域名
- 确保防火墙开放对应端口
- 建议使用HTTPS(需要配置反向代理)

## 模式二: WebSocket模式(推荐本地开发)

### 1. 安装依赖

```bash
pip install lark-oapi
```

### 2. 配置

```json
{
  "feishu_event_mode": "websocket"
}
```

### 3. 启动服务

```bash
python3 app.py
```

程序将自动建立与飞书开放平台的长连接。

### 4. 配置飞书应用

1. 登录[飞书开放平台](https://open.feishu.cn/)
2. 进入应用详情 -> 事件订阅
3. 选择 **使用长连接接收事件**
4. 添加事件: `im.message.receive_v1` (接收消息v2.0)
5. 保存配置

### 5. 注意事项

- 无需公网IP
- 需要能访问公网(建立WebSocket连接)
- 每个应用最多50个连接
- 集群模式下消息随机分发到一个客户端

## 平滑迁移

从webhook模式切换到websocket模式(或反向切换):

1. 修改 `config.json` 中的 `feishu_event_mode`
2. 如果切换到websocket模式，安装 `lark-oapi` 依赖
3. 重启服务
4. 在飞书开放平台修改事件订阅方式

**重要**: 同一时间只能使用一种模式，否则会导致消息重复接收。

## 消息去重机制

两种模式都使用相同的消息去重机制:

- 使用 `ExpiredDict` 存储已处理的消息ID
- 过期时间: 7.1小时
- 确保消息不会重复处理

## 故障排查

### WebSocket模式连接失败

```
[FeiShu] lark_oapi not installed
```

**解决**: 安装依赖 `pip install lark-oapi`

### SSL证书验证失败

```
[Lark][ERROR] connect failed, err:[SSL:CERTIFICATE_VERIFY_FAILED] certificate verify failed: self signed certificate in certificate chain
```

**原因**: 网络环境中存在自签名证书或SSL中间人代理(如企业代理、VPN等)

**解决**: 程序会自动检测SSL证书验证失败，并自动重试禁用证书验证的连接。无需手动配置。

当遇到证书错误时，日志会显示：
```
[FeiShu] SSL certificate verification disabled due to certificate error. This may happen when using corporate proxy or self-signed certificates.
```

这是正常现象，程序会自动处理并继续运行。

### Webhook模式端口被占用

```
Address already in use
```

**解决**: 修改 `feishu_port` 配置或关闭占用端口的进程

### 收不到消息

1. 检查飞书应用的事件订阅配置
2. 确认已添加 `im.message.receive_v1` 事件
3. 检查应用权限: 需要 `im:message` 权限
4. 查看日志中的错误信息

## 开发建议

- **本地开发**: 使用websocket模式，快速迭代
- **测试环境**: 可以使用webhook模式 + 内网穿透工具(如ngrok)
- **生产环境**: 使用webhook模式，配置正式域名和HTTPS

## 参考文档

- [飞书开放平台 - 事件订阅](https://open.feishu.cn/document/ukTMukTMukTM/uUTNz4SN1MjL1UzM)
- [飞书SDK - Python](https://github.com/larksuite/oapi-sdk-python)
