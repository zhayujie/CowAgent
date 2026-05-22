# 企业微信应用号channel

企业微信官方提供了客服、应用等API，本channel使用的是企业微信的自建应用API的能力。

因为未来可能还会开发客服能力，所以本channel的类型名叫作`wechatcom_app`。

`wechatcom_app` channel支持插件系统和图片声音交互等能力，除了无法加入群聊，作为个人使用的私人助理已绰绰有余。

## 开始之前

- 在企业中确认自己拥有在企业内自建应用的权限。
- 如果没有权限或者是个人用户，也可创建未认证的企业。操作方式：登录手机企业微信，选择`创建/加入企业`来创建企业，类型请选择企业，企业名称可随意填写。
    未认证的企业有100人的服务人数上限，其他功能与认证企业没有差异。

本channel需安装的依赖与公众号一致，需要安装`wechatpy`和`web.py`，它们包含在`requirements-optional.txt`中。

此外，如果你是`Linux`系统，除了`ffmpeg`还需要安装`amr`编码器，否则会出现找不到编码器的错误，无法正常使用语音功能。

- Ubuntu/Debian

```bash
apt-get install libavcodec-extra
```

- Alpine

需自行编译`ffmpeg`，在编译参数里加入`amr`编码器的支持

## 使用方法

1.查看企业ID

- 扫码登陆[企业微信后台](https://work.weixin.qq.com)
- 选择`我的企业`，点击`企业信息`，记住该`企业ID`

2.创建自建应用

- 选择应用管理, 在自建区选创建应用来创建企业自建应用
- 上传应用logo，填写应用名称等项
- 创建应用后进入应用详情页面，记住`AgentId`和`Secert`

3.配置应用

- 在详情页点击`企业可信IP`的配置(没看到可以不管)，填入你服务器的公网IP，如果不知道可以先不填
- 点击`接收消息`下的启用API接收消息
- `URL`填写格式为`http://url:port/wxcomapp`，`port`是程序监听的端口，默认是9898
    如果是未认证的企业，url可直接使用服务器的IP。如果是认证企业，需要使用备案的域名，可使用二级域名。
- `Token`可随意填写，停留在这个页面
- 在程序根目录`config.json`中增加配置（**去掉注释**），`wechatcomapp_aes_key`是当前页面的`wechatcomapp_aes_key`

```python
    "channel_type": "wechatcom_app",
    "wechatcom_corp_id": "",  # 企业微信公司的corpID
    "wechatcomapp_token": "",  # 企业微信app的token
    "wechatcomapp_port": 9898,  # 企业微信app的服务端口, 不需要端口转发
    "wechatcomapp_secret": "",  # 企业微信app的secret
    "wechatcomapp_agent_id": "",  # 企业微信app的agent_id
    "wechatcomapp_aes_key": "",  # 企业微信app的aes_key
```

- 运行程序，在页面中点击保存，保存成功说明验证成功

4.连接个人微信

选择`我的企业`，点击`微信插件`，下面有个邀请关注的二维码。微信扫码后，即可在微信中看到对应企业，在这里你便可以和机器人沟通。

向机器人发送消息，如果日志里出现报错:

```bash
Error code: 60020, message: "not allow to access from your ip, ...from ip: xx.xx.xx.xx"
```

意思是IP不可信，需要参考上一步的`企业可信IP`配置，把这里的IP加进去。

~~### Railway部署方式~~（2023-06-08已失效）

~~公众号不能在`Railway`上部署，但企业微信应用[可以](https://railway.app/template/-FHS--?referralCode=RC3znh)!~~

~~填写配置后，将部署完成后的网址```**.railway.app/wxcomapp```，填写在上一步的URL中。发送信息后观察日志，把报错的IP加入到可信IP。（每次重启后都需要加入可信IP）~~

~~## 测试体验~~

~~AIGC开放社区中已经部署了多个可免费使用的Bot，扫描下方的二维码会自动邀请你来体验。~~

~~<img width="200" src="../../docs/images/aigcopen.png">~~
