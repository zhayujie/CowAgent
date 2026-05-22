# 微信公众号channel

微信公众号channel，提供稳定的服务。
目前支持订阅号和服务号两种类型的公众号，它们都支持文本交互，语音和图片输入。其中个人主体的微信订阅号由于无法通过微信认证，存在回复时间限制，每天的图片和声音回复次数也有限制。

## 使用方法（订阅号，服务号类似）

在开始部署前，你需要一个拥有公网IP的服务器，以提供微信服务器和我们自己服务器的连接。或者你需要进行内网穿透，否则微信服务器无法将消息发送给我们的服务器。

此外，需要在我们的服务器上安装python的web框架web.py和wechatpy。
以ubuntu为例(在ubuntu 22.04上测试):
```
pip3 install web.py
pip3 install wechatpy
```

然后在[微信公众平台](https://mp.weixin.qq.com)注册一个自己的公众号，类型选择订阅号，主体为个人即可。

然后根据[接入指南](https://developers.weixin.qq.com/doc/offiaccount/Basic_Information/Access_Overview.html)的说明，在[微信公众平台](https://mp.weixin.qq.com)的“设置与开发”-“基本配置”-“服务器配置”中填写服务器地址`URL`和令牌`Token`。`URL`填写格式为`http://url/wx`，可使用IP（成功几率看脸），`Token`是你自己编的一个特定的令牌。消息加解密方式如果选择了需要加密的模式，需要在配置中填写`wechatmp_aes_key`。

相关的服务器验证代码已经写好，你不需要再添加任何代码。你只需要在本项目根目录的`config.json`中添加
```
"channel_type": "wechatmp",     # 如果通过了微信认证，将"wechatmp"替换为"wechatmp_service"，可极大的优化使用体验
"wechatmp_token": "xxxx",       # 微信公众平台的Token
"wechatmp_port": 8080,          # 微信公众平台的端口,需要端口转发到80或443
"wechatmp_app_id": "xxxx",      # 微信公众平台的appID
"wechatmp_app_secret": "xxxx",  # 微信公众平台的appsecret
"wechatmp_aes_key": "",         # 微信公众平台的EncodingAESKey，加密模式需要
"single_chat_prefix": [""],     # 推荐设置，任意对话都可以触发回复，不添加前缀
"single_chat_reply_prefix": "", # 推荐设置，回复不设置前缀
"plugin_trigger_prefix": "&",   # 推荐设置，在手机微信客户端中，$%^等符号与中文连在一起时会自动显示一段较大的间隔，用户体验不好。请不要使用管理员指令前缀"#"，这会造成未知问题。
```
然后运行`python3 app.py`启动web服务器。这里会默认监听8080端口，但是微信公众号的服务器配置只支持80/443端口，有两种方法来解决这个问题。第一个是推荐的方法，使用端口转发命令将80端口转发到8080端口：
```
sudo iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8080
sudo iptables-save > /etc/iptables/rules.v4
```
第二个方法是让python程序直接监听80端口，在配置文件中设置`"wechatmp_port": 80` ，在linux上需要使用`sudo python3 app.py`启动程序。然而这会导致一系列环境和权限问题，因此不是推荐的方法。

443端口同理，注意需要支持SSL，也就是https的访问，在`wechatmp_channel.py`中需要修改相应的证书路径。

程序启动并监听端口后，在刚才的“服务器配置”中点击`提交`即可验证你的服务器。
随后在[微信公众平台](https://mp.weixin.qq.com)启用服务器，关闭手动填写规则的自动回复，即可实现ChatGPT的自动回复。

之后需要在公众号开发信息下将本机IP加入到IP白名单。

不然在启用后，发送语音、图片等消息可能会遇到如下报错：
```
'errcode': 40164, 'errmsg': 'invalid ip xx.xx.xx.xx not in whitelist rid
```


## 个人微信公众号的限制
由于人微信公众号不能通过微信认证，所以没有客服接口，因此公众号无法主动发出消息，只能被动回复。而微信官方对被动回复有5秒的时间限制，最多重试2次，因此最多只有15秒的自动回复时间窗口。因此如果问题比较复杂或者我们的服务器比较忙，ChatGPT的回答就没办法及时回复给用户。为了解决这个问题，这里做了回答缓存，它需要你在回复超时后，再次主动发送任意文字（例如1）来尝试拿到回答缓存。为了优化使用体验，目前设置了两分钟（120秒）的timeout，用户在至多两分钟后即可得到查询到回复或者错误原因。

另外，由于微信官方的限制，自动回复有长度限制。因此这里将ChatGPT的回答进行了拆分，以满足限制。

## 私有api_key
公共api有访问频率限制（免费账号每分钟最多3次ChatGPT的API调用），这在服务多人的时候会遇到问题。因此这里多加了一个设置私有api_key的功能。目前通过godcmd插件的命令来设置私有api_key。

## 语音输入
利用微信自带的语音识别功能，提供语音输入能力。需要在公众号管理页面的“设置与开发”->“接口权限”页面开启“接收语音识别结果”。

## 语音回复
请在配置文件中添加以下词条：
```
  "voice_reply_voice": true,
```
这样公众号将会用语音回复语音消息，实现语音对话。

默认的语音合成引擎是`google`，它是免费使用的。

如果要选择其他的语音合成引擎，请添加以下配置项：
```
"text_to_voice": "pytts"
```

pytts是本地的语音合成引擎。还支持baidu,azure，这些你需要自行配置相关的依赖和key。

如果使用pytts，在ubuntu上需要安装如下依赖：
```
sudo apt update
sudo apt install espeak
sudo apt install ffmpeg
python3 -m pip install pyttsx3
```
不是很建议开启pytts语音回复，因为它是离线本地计算，算的慢会拖垮服务器，且声音不好听。

## 图片回复
现在认证公众号和非认证公众号都可以实现的图片和语音回复。但是非认证公众号使用了永久素材接口，每天有1000次的调用上限（每个月有10次重置机会，程序中已设定遇到上限会自动重置），且永久素材库存也有上限。因此对于非认证公众号，我们会在回复图片或者语音消息后的10秒内从永久素材库存内删除该素材。

## 测试
目前在`RoboStyle`这个公众号上进行了测试（基于[wechatmp分支](https://github.com/JS00000/chatgpt-on-wechat/tree/wechatmp)），感兴趣的可以关注并体验。开启了godcmd, Banwords, role, dungeon, finish这五个插件，其他的插件还没有详尽测试。百度的接口暂未测试。[wechatmp-stable分支](https://github.com/JS00000/chatgpt-on-wechat/tree/wechatmp-stable)是较稳定的上个版本，但也缺少最新的功能支持。

## TODO
 - [x] 语音输入
 - [x] 图片输入
 - [x] 使用临时素材接口提供认证公众号的图片和语音回复
 - [x] 使用永久素材接口提供未认证公众号的图片和语音回复
 - [ ] 高并发支持
