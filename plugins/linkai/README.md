## 插件说明

基于 LinkAI 提供的知识库、Midjourney绘画、文档对话等能力对机器人的功能进行增强。平台地址: https://link-ai.tech/console

## 插件配置

将 `plugins/linkai` 目录下的 `config.json.template` 配置模板复制为最终生效的 `config.json`。 (如果未配置则会默认使用`config.json.template`模板中配置，但功能默认关闭，需要可通过指令进行开启)。

以下是插件配置项说明：

```bash
{
    "group_app_map": {               # 群聊 和 应用编码 的映射关系
        "测试群名称1": "default",      # 表示在名称为 "测试群名称1" 的群聊中将使用app_code 为 default 的应用
        "测试群名称2": "Kv2fXJcH"
    },
    "midjourney": {
        "enabled": true,          # midjourney 绘画开关
        "auto_translate": true,   # 是否自动将提示词翻译为英文
        "img_proxy": true,        # 是否对生成的图片使用代理，如果你是国外服务器，将这一项设置为false会获得更快的生成速度
        "max_tasks": 3,           # 支持同时提交的总任务个数
        "max_tasks_per_user": 1,  # 支持单个用户同时提交的任务个数
        "use_image_create_prefix": true   # 是否使用全局的绘画触发词，如果开启将同时支持由`config.json`中的 image_create_prefix 配置触发
    },
    "summary": {
        "enabled": true,              # 文档总结和对话功能开关
        "group_enabled": true,        # 是否支持群聊开启
        "max_file_size": 5000,        # 文件的大小限制，单位KB，默认为5M，超过该大小直接忽略
        "type": ["FILE", "SHARING", "IMAGE"]  # 支持总结的类型，分别表示 文件、分享链接、图片，其中文件和链接默认打开，图片默认关闭
    }
}
```

根目录 `config.json` 中配置，`API_KEY` 在 [控制台](https://link-ai.tech/console/interface) 中创建并复制过来:

```bash
"linkai_api_key": "Link_xxxxxxxxx"
```

注意：

 - 配置项中 `group_app_map` 部分是用于映射群聊与LinkAI平台上的应用， `midjourney` 部分是 mj 画图的配置，`summary` 部分是文档总结及对话功能的配置。三部分的配置相互独立，可按需开启
 - 实际 `config.json` 配置中应保证json格式，不应携带 '#' 及后面的注释
 - 如果是`docker`部署，可通过映射 `plugins/config.json` 到容器中来完成插件配置，参考[文档](https://github.com/zhayujie/chatgpt-on-wechat#3-%E6%8F%92%E4%BB%B6%E4%BD%BF%E7%94%A8)

## 插件使用

> 使用插件中的知识库管理功能需要首先开启`linkai`对话，依赖全局 `config.json` 中的 `use_linkai` 和 `linkai_api_key` 配置；而midjourney绘画 和 summary文档总结对话功能则只需填写 `linkai_api_key` 配置，`use_linkai` 无论是否关闭均可使用。具体可参考 [详细文档](https://link-ai.tech/platform/link-app/wechat)。

完成配置后运行项目，会自动运行插件，输入 `#help linkai` 可查看插件功能。

### 1.知识库管理功能

提供在不同群聊使用不同应用的功能。可以在上述 `group_app_map` 配置中固定映射关系，也可以通过指令在群中快速完成切换。

应用切换指令需要首先完成管理员 (`godcmd`) 插件的认证，然后按以下格式输入：

`$linkai app {app_code}`

例如输入 `$linkai app Kv2fXJcH`，即将当前群聊与 app_code为 Kv2fXJcH 的应用绑定。

另外，还可以通过 `$linkai close` 来一键关闭linkai对话，此时就会使用默认的openai接口；同理，发送 `$linkai open` 可以再次开启。

### 2.Midjourney绘画功能

若未配置 `plugins/linkai/config.json`，默认会关闭画图功能，直接使用 `$mj open` 可基于默认配置直接使用mj画图。

指令格式：

```
 - 图片生成: $mj 描述词1, 描述词2..
 - 图片放大: $mju 图片ID 图片序号
 - 图片变换: $mjv 图片ID 图片序号
 - 重置: $mjr 图片ID
```

例如：

```
"$mj a little cat, white --ar 9:16"
"$mju 1105592717188272288 2"
"$mjv 11055927171882 2"
"$mjr 11055927171882"
```

注意事项：
1. 使用 `$mj open` 和 `$mj close` 指令可以快速打开和关闭绘图功能
2. 海外环境部署请将 `img_proxy` 设置为 `false`
3. 开启 `use_image_create_prefix` 配置后可直接复用全局画图触发词，以"画"开头便可以生成图片。
4. 提示词内容中包含敏感词或者参数格式错误可能导致绘画失败，生成失败不消耗积分
5. 若未收到图片可能有两种可能，一种是收到了图片但微信发送失败，可以在后台日志查看有没有获取到图片url，一般原因是受到了wx限制，可以稍后重试或更换账号尝试；另一种情况是图片提示词存在疑似违规，mj不会直接提示错误但会在画图后删掉原图导致程序无法获取，这种情况不消耗积分。

### 3.文档总结对话功能

#### 配置

该功能依赖 LinkAI的知识库及对话功能，需要在项目根目录的config.json中设置 `linkai_api_key`， 同时根据上述插件配置说明，在插件config.json添加 `summary` 部分的配置，设置 `enabled` 为 true。

如果不想创建 `plugins/linkai/config.json` 配置，可以直接通过 `$linkai sum open` 指令开启该功能。

也可以通过私聊(全局 `config.json` 中的 `linkai_app_code`)或者群聊绑定(通过`group_app_map`参数配置)的应用来开启该功能：在LinkAI平台 [应用配置](https://link-ai.tech/console/factory) 里添加并开启**内容总结**插件。

#### 使用

功能开启后，向机器人发送 **文件**、 **分享链接卡片**、**图片** 即可生成摘要，进一步可以与文件或链接的内容进行多轮对话。如果需要关闭某种类型的内容总结，设置 `summary`配置中的type字段即可。

#### 限制

 1. 文件目前 支持 `txt`, `docx`, `pdf`, `md`, `csv`格式，文件大小由 `max_file_size` 限制，最大不超过15M，文件字数最多可支持百万字的文件。但不建议上传字数过多的文件，一是token消耗过大，二是摘要很难覆盖到全部内容，只能通过多轮对话来了解细节。
 2. 分享链接 目前仅支持 公众号文章，后续会支持更多文章类型及视频链接等
 3. 总结及对话的 费用与 LinkAI 3.5-4K 模型的计费方式相同，按文档内容的tokens进行计算
