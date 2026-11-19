## 插件描述
一个能让chatgpt联网，搜索，数字运算的插件，将赋予强大且丰富的扩展能力   
使用说明(默认trigger_prefix为$)：  
```text
#help tool: 查看tool帮助信息，可查看已加载工具列表  
$tool 工具名 命令: （pure模式）根据给出的{命令}使用指定 一个 可用工具尽力为你得到结果。
$tool 命令: （多工具模式）根据给出的{命令}使用 一些 可用工具尽力为你得到结果。  
$tool reset: 重置工具。  
```
### 本插件所有工具同步存放至专用仓库：[chatgpt-tool-hub](https://github.com/goldfishh/chatgpt-tool-hub)

2024.01.16更新
1. 新增工具pure模式，支持单个工具调用
2. 新增消息转发工具：email, sms, wechat, 可以根据规则向其他平台发送消息
3. 替换visual-dl（更名为visual）实现，目前识别图片链接效果较好。
4. 修复了0.4版本大部分工具返回结果不可靠问题

新版本工具名共19个，不一一列举，相应工具需要的环境参数见`tool.py`里的`_build_tool_kwargs`函数

## 使用说明
使用该插件后将默认使用4个工具, 无需额外配置长期生效：
### 1. python
###### python解释器，使用它来解释执行python指令，可以配合你想要chatgpt生成的代码输出结果或执行事务

### 2. 访问网页的工具汇总(默认url-get)

#### 2.1 url-get
###### 往往用来获取某个网站具体内容，结果可能会被反爬策略影响

#### 2.2 browser
###### 浏览器，功能与2.1类似，但能更好模拟，不会被识别为爬虫影响获取网站内容

> 注1：url-get默认配置、browser需额外配置，browser依赖google-chrome，你需要提前安装好

> 注2：（可通过`browser_use_summary`或 `url_get_use_summary`开关）当检测到长文本时会进入summary tool总结长文本，tokens可能会大量消耗！

这是debian端安装google-chrome教程，其他系统请自行查找
> https://www.linuxjournal.com/content/how-can-you-install-google-browser-debian

### 3. terminal
###### 在你运行的电脑里执行shell命令，可以配合你想要chatgpt生成的代码使用，给予自然语言控制手段

> terminal调优记录：https://github.com/zhayujie/CowAgent/issues/776#issue-1659347640

### 4. meteo
###### 回答你有关天气的询问, 需要获取时间、地点上下文信息，本工具使用了[meteo open api](https://open-meteo.com/)
注：该工具需要较高的对话技巧，不保证你问的任何问题均能得到满意的回复
注2：当前版本可只使用这个工具，返回结果较可控。

> meteo调优记录：https://github.com/zhayujie/CowAgent/issues/776#issuecomment-1500771334

## 使用本插件对话（prompt）技巧
### 1. 有指引的询问
#### 例如：
- 总结这个链接的内容 https://github.com/goldfishh/chatgpt-tool-hub
- 使用Terminal执行curl cip.cc
- 使用python查询今天日期

### 2. 使用搜索引擎工具
- 如果有搜索工具就能让chatgpt获取到你的未传达清楚的上下文信息，比如chatgpt不知道你的地理位置，现在时间等，所以无法查询到天气

## 其他工具

### 5. wikipedia
###### 可以回答你想要知道确切的人事物

### 6. news 新闻类工具集合

> news更新：0.4版本对新闻类工具做了整合，配置文件只要加入`news`一个工具名就会自动加载所有新闻类工具

#### 6.1. news-api *
###### 从全球 80,000 多个信息源中获取当前和历史新闻文章

#### 6.2. morning-news *
###### 每日60秒早报，每天凌晨一点更新，本工具使用了[alapi-每日60秒早报](https://alapi.cn/api/view/93)

> 该tool每天返回内容相同

#### 6.3. finance-news
###### 获取实时的金融财政新闻

> 该工具需要用到browser工具解决反爬问题


### 7. bing-search *
###### bing搜索引擎，从此你不用再烦恼搜索要用哪些关键词

### 8. wolfram-alpha *
###### 知识搜索引擎、科学问答系统，常用于专业学科计算

### 9. google-search *
###### google搜索引擎，申请流程较bing-search繁琐

### 10. arxiv
###### 用于查找论文

```text
可配置参数：
1. arxiv_summary: 是否使用总结工具，默认true, 当为false时会直接返回论文的标题、作者、发布时间、摘要、分类、备注、pdf链接等内容
```

> 0.4.2更新，例子：帮我找一篇吴恩达写的论文

### 11. summary
###### 总结工具，该工具可以支持输入url

> 该工具目前是和其他工具配合使用，暂未测试单独使用效果

### 12. visual
###### 将图片转换成文字，底层调用ali dashscope `qwen-vl-plus`模型

### 13. searxng-search *
###### 一个私有化的搜索引擎工具

> 安装教程：https://docs.searxng.org/admin/installation.html

### 14. email *
###### 发送邮件

### 15. sms *
###### 发送短信

### 16. stt *
###### speak to text 语音识别

### 17. tts *
###### text to speak 文生语音

### 18. wechat *
###### 向好友、群组发送微信

---

###### 注1：带*工具需要获取api-key才能使用(在config.json内的kwargs添加项)，部分工具需要外网支持  
## [工具的api申请方法](https://github.com/goldfishh/chatgpt-tool-hub/blob/master/docs/apply_optional_tool.md)

## config.json 配置说明
###### 默认工具无需配置，其它工具需手动配置，以增加morning-news和bing-search两个工具为例：
```json
{
  "tools": ["bing-search", "morning-news", "你想要添加的其他工具"],  // 填入你想用到的额外工具名，这里加入了工具"bing-search"和工具"morning-news"
  "kwargs": {
      "debug": true, // 当你遇到问题求助时，需要配置
      "request_timeout": 120,  // openai接口超时时间
      "no_default": false,  // 是否不使用默认的4个工具
      "bing_subscription_key": "4871f273a4804743",//带*工具需要申请api-key，这里填入了工具bing-search对应的api，api_name参考前述`工具的api申请方法`
      "morning_news_api_key": "5w1kjNh9VQlUc",// 这里填入了morning-news对应的api，
  }
}

```
注：config.json文件非必须，未创建仍可使用本tool；带*工具需在kwargs填入对应api-key键值对  
- `tools`：本插件初始化时加载的工具, 上述一级标题即是对应工具名称，带*工具必须在kwargs中配置相应api-key
- `kwargs`：工具执行时的配置，一般在这里存放**api-key**，或环境配置
  - `debug`: 输出chatgpt-tool-hub额外信息用于调试
  - `request_timeout`: 访问openai接口的超时时间，默认与wechat-on-chatgpt配置一致，可单独配置
  - `no_default`: 用于配置默认加载4个工具的行为，如果为true则仅使用tools列表工具，不加载默认工具
  - `model_name`: 用于控制tool插件底层使用的llm模型，目前暂未测试3.5以外的模型，一般保持默认

---

## 备注
- 强烈建议申请搜索工具搭配使用，推荐bing-search
- 虽然我会有意加入一些限制，但请不要使用本插件做危害他人的事情，请提前了解清楚某些内容是否会违反相关规定，建议提前做好过滤
- 如有本插件问题，请将debug设置为true无上下文重新问一遍，如仍有问题请访问[chatgpt-tool-hub](https://github.com/goldfishh/chatgpt-tool-hub)建个issue，将日志贴进去，我无法处理不能复现的问题
- 欢迎 star & 宣传，有能力请提pr
