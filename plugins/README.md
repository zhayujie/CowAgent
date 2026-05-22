**Table of Content**

- [插件化初衷](#插件化初衷)
- [插件安装方法](#插件安装方法)
- [插件化实现](#插件化实现)
- [插件编写示例](#插件编写示例)
- [插件设计建议](#插件设计建议)

## 插件化初衷

之前未插件化的代码耦合程度高，如果要定制一些个性化功能（如流量控制、接入`NovelAI`画图平台等），需要了解代码主体，避免影响到其他的功能。多个功能同时存在时，无法调整功能的优先级顺序，功能配置项也非常混乱。

此时插件化应声而出。

**插件化**: 在保证主体功能是ChatGPT的前提下，我们推荐将主体功能外的功能利用插件的方式实现。

- [x] 可根据功能需要，下载不同插件。
- [x] 插件开发成本低，仅需了解插件触发事件，并按照插件定义接口编写插件。
- [x] 插件化能够自由开关和调整优先级。
- [x] 每个插件可在插件文件夹内维护独立的配置文件，方便代码的测试和调试，可以在独立的仓库开发插件。

## 插件安装方法

在本仓库中预置了一些插件，如果要安装其他仓库的插件，有两种方法。

- 第一种方法是在将下载的插件文件都解压到"plugins"文件夹的一个单独的文件夹，最终插件的代码都位于"plugins/PLUGIN_NAME/*"中。启动程序后，如果插件的目录结构正确，插件会自动被扫描加载。除此以外，注意你还需要安装文件夹中`requirements.txt`中的依赖。

- 第二种方法是`Godcmd`插件，它是预置的管理员插件，能够让程序在运行时就能安装插件，它能够自动安装依赖。

    安装插件的命令是"#installp [仓库源](https://github.com/zhayujie/chatgpt-on-wechat/blob/master/plugins/source.json)记录的插件名/仓库地址"。这是管理员命令，认证方法在[这里](https://github.com/zhayujie/chatgpt-on-wechat/tree/master/plugins/godcmd)。

    - 安装[仓库源](https://github.com/zhayujie/chatgpt-on-wechat/blob/master/plugins/source.json)记录的插件：#installp sdwebui

    - 安装指定仓库的插件：#installp https://github.com/lanvent/plugin_sdwebui.git

    在安装之后，需要执行"#scanp"命令来扫描加载新安装的插件（或者重新启动程序）。

安装插件后需要注意有些插件有自己的配置模板，一般要去掉".template"新建一个配置文件。

## 插件化实现

插件化实现是在收到消息到发送回复的各个步骤之间插入触发事件实现的。

### 消息处理过程

在了解插件触发事件前，首先需要了解程序收到消息到发送回复的整个过程。

插件化版本中，消息处理过程可以分为4个步骤：
```
    1.收到消息 ---> 2.产生回复 ---> 3.包装回复 ---> 4.发送回复
```

以下是它们的默认处理逻辑(太长不看，可跳到[插件编写示例](#插件编写示例))：

**注意以下包含的代码是`v1.1.0`中的片段，已过时，只可用于理解事件，最新的默认代码逻辑请参考[chat_channel](https://github.com/zhayujie/chatgpt-on-wechat/blob/master/channel/chat_channel.py)**

#### 1. 收到消息

负责接收用户消息，根据用户的配置，判断本条消息是否触发机器人。如果触发，则会判断该消息的类型（声音、文本、画图命令等），将消息包装成如下的`Context`交付给下一个步骤。

```python
    class ContextType (Enum):
        TEXT = 1         # 文本消息
        VOICE = 2        # 音频消息
        IMAGE_CREATE = 3 # 创建图片命令
    class Context:
        def __init__(self, type : ContextType = None , content = None,  kwargs = dict()):
            self.type = type
            self.content = content
            self.kwargs = kwargs
        def __getitem__(self, key):
            return self.kwargs[key]
```

`Context`中除了存放消息类型和内容外,还存放了一些与会话相关的参数。

例如，当收到用户私聊消息时，会存放以下的会话参数。

```python
    context.kwargs = {'isgroup': False, 'msg': msg, 'receiver': other_user_id, 'session_id': other_user_id}
```

- `isgroup`: `Context`是否是群聊消息。
- `msg`: the original message object from the channel.
- `receiver`: 需要回复消息的对象ID。
- `session_id`: 会话ID(一般是发送触发bot消息的用户ID，如果在群聊中并且`conf`里设置了`group_chat_in_one_session`，那么此处便是群聊ID)

#### 2. 产生回复

处理消息并产生回复。目前默认处理逻辑是根据`Context`的类型交付给对应的bot，并产生回复`Reply`。 如果本步骤没有产生任何回复，那么会跳过之后的所有步骤。

```python
    if context.type == ContextType.TEXT or context.type == ContextType.IMAGE_CREATE:
        reply = super().build_reply_content(context.content, context) #文字跟画图交付给chatgpt
    elif context.type == ContextType.VOICE: # 声音先进行语音转文字后，修改Context类型为文字后，再交付给chatgpt
        cmsg = context['msg']
        cmsg.prepare()
        file_name = context.content
        reply = super().build_voice_to_text(file_name)
        if reply.type != ReplyType.ERROR and reply.type != ReplyType.INFO:
            context.content = reply.content # 语音转文字后，将文字内容作为新的context
            context.type = ContextType.TEXT
            reply = super().build_reply_content(context.content, context)
            if reply.type == ReplyType.TEXT:
                if conf().get('voice_reply_voice'):
                    reply = super().build_text_to_voice(reply.content)
```

回复`Reply`的定义如下所示，它允许Bot可以回复多类不同的消息。同时也加入了`INFO`和`ERROR`消息类型区分系统提示和系统错误。

```python
    class ReplyType(Enum):
        TEXT = 1        # 文本
        VOICE = 2       # 音频文件
        IMAGE = 3       # 图片文件
        IMAGE_URL = 4   # 图片URL

        INFO = 9
        ERROR = 10
    class Reply:
        def __init__(self, type : ReplyType = None , content = None):
            self.type = type
            self.content = content
```

#### 3. 装饰回复

根据`Context`和回复`Reply`的类型，对回复的内容进行装饰。目前的装饰有以下两种:

- `TEXT`文本回复:如果这次消息需要的回复是`VOICE`，进行文字转语音回复之后再次装饰。 否则根据是否在群聊中来决定是艾特接收方还是添加回复的前缀。

- `INFO`或`ERROR`类型，会在消息前添加对应的系统提示字样。

如下是默认逻辑的代码：

```python
    if reply.type == ReplyType.TEXT:
        reply_text = reply.content
        if context.get('desire_rtype') == ReplyType.VOICE:
            reply = super().build_text_to_voice(reply.content)
            return self._decorate_reply(context, reply)
        if context['isgroup']:
            reply_text = '@' +  context['msg'].actual_user_nickname + ' ' + reply_text.strip()
            reply_text = conf().get("group_chat_reply_prefix", "")+reply_text
        else:
            reply_text = conf().get("single_chat_reply_prefix", "")+reply_text
        reply.content = reply_text
    elif reply.type == ReplyType.ERROR or reply.type == ReplyType.INFO:
        reply.content = str(reply.type)+":\n" + reply.content
```

#### 4. 发送回复

根据`Reply`的类型，默认逻辑调用不同的发送函数发送回复给接收方`context["receiver"]`。

### 插件触发事件

主程序目前会在各个消息步骤间触发事件，监听相应事件的插件会按照优先级，顺序调用事件处理函数。

目前支持三类触发事件：
```
1.收到消息
---> `ON_HANDLE_CONTEXT`
2.产生回复
---> `ON_DECORATE_REPLY`
3.装饰回复
---> `ON_SEND_REPLY`
4.发送回复
```

触发事件会产生事件的上下文`EventContext`，它包含了以下信息:

`EventContext(Event事件类型, {'channel' : 消息channel, 'context': Context, 'reply': Reply})`

插件处理函数可通过修改`EventContext`中的`context`和`reply`来实现功能。

## 插件编写示例

以`plugins/hello`为例，其中编写了一个简单的`Hello`插件。

### 1. 创建插件

在`plugins`目录下创建一个插件文件夹`hello`。然后，在该文件夹中创建``__init__.py``文件，在``__init__.py``中将其他编写的模块文件导入。在程序启动时，插件管理器会读取``__init__.py``的所有内容。

```
plugins/
└── hello
    ├── __init__.py
    └── hello.py
```

``__init__.py``的内容：
```
from .hello import *
```

### 2. 编写插件类

在`hello.py`文件中，创建插件类，它继承自`Plugin`。

在类定义之前需要使用`@plugins.register`装饰器注册插件，并填写插件的相关信息，其中`desire_priority`表示插件默认的优先级，越大优先级越高。初次加载插件后可在`plugins/plugins.json`中修改插件优先级。

并在`__init__`中绑定你编写的事件处理函数。

`Hello`插件为事件`ON_HANDLE_CONTEXT`绑定了一个处理函数`on_handle_context`，它表示之后每次生成回复前，都会由`on_handle_context`先处理。

PS: `ON_HANDLE_CONTEXT`是最常用的事件，如果要根据不同的消息来生成回复，就用它。

```python
@plugins.register(name="Hello", desc="A simple plugin that says hello", version="0.1", author="lanvent", desire_priority= -1)
class Hello(Plugin):
    def __init__(self):
        super().__init__()
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        logger.info("[Hello] inited")
```

### 3. 编写事件处理函数

#### 修改事件上下文

事件处理函数接收一个`EventContext`对象`e_context`作为参数。`e_context`包含了事件相关信息，利用`e_context['key']`来访问这些信息。

`EventContext(Event事件类型, {'channel' : 消息channel, 'context': Context, 'reply': Reply})`

处理函数中通过修改`e_context`对象中的事件相关信息来实现所需功能，比如更改`e_context['reply']`中的内容可以修改回复。

#### 决定是否交付给下个插件或默认逻辑

在处理函数结束时，还需要设置`e_context`对象的`action`属性，它决定如何继续处理事件。目前有以下三种处理方式：

- `EventAction.CONTINUE`: 事件未结束，继续交给下个插件处理，如果没有下个插件，则交付给默认的事件处理逻辑。
- `EventAction.BREAK`: 事件结束，不再给下个插件处理，交付给默认的处理逻辑。
- `EventAction.BREAK_PASS`: 事件结束，不再给下个插件处理，跳过默认的处理逻辑。

#### 示例处理函数

`Hello`插件处理`Context`类型为`TEXT`的消息：

- 如果内容是`Hello`，就将回复设置为`Hello+用户昵称`，并跳过之后的插件和默认逻辑。
- 如果内容是`End`，就将`Context`的类型更改为`IMAGE_CREATE`，并让事件继续，如果最终交付到默认逻辑，会调用默认的画图Bot来画画。

```python
    def on_handle_context(self, e_context: EventContext):
        if e_context['context'].type != ContextType.TEXT:
            return
        content = e_context['context'].content
        if content == "Hello":
            reply = Reply()
            reply.type = ReplyType.TEXT
            msg:ChatMessage = e_context['context']['msg']
            if e_context['context']['isgroup']:
                reply.content = f"Hello, {msg.actual_user_nickname} from {msg.from_user_nickname}"
            else:
                reply.content = f"Hello, {msg.from_user_nickname}"
            e_context['reply'] = reply
            e_context.action = EventAction.BREAK_PASS # 事件结束，并跳过处理context的默认逻辑
        if content == "End":
            # 如果是文本消息"End"，将请求转换成"IMAGE_CREATE"，并将content设置为"The World"
            e_context['context'].type = ContextType.IMAGE_CREATE
            content = "The World"
            e_context.action = EventAction.CONTINUE  # 事件继续，交付给下个插件或默认逻辑
```

## 插件设计建议

- 尽情将你想要的个性化功能设计为插件。
- 一个插件目录建议只注册一个插件类。建议使用单独的仓库维护插件，便于更新。

  在测试调试好后提交`PR`，把自己的仓库加入到[仓库源](https://github.com/zhayujie/chatgpt-on-wechat/blob/master/plugins/source.json)中。

- 插件的config文件、使用说明`README.md`、`requirement.txt`等放置在插件目录中。
- 默认优先级不要超过管理员插件`Godcmd`的优先级(999)，`Godcmd`插件提供了配置管理、插件管理等功能。
