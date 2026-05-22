# Agent插件

## 插件说明

基于 [AgentMesh](https://github.com/MinimalFuture/AgentMesh) 多智能体框架实现的Agent插件，可以让机器人快速获得Agent能力，通过自然语言对话来访问 **终端、浏览器、文件系统、搜索引擎** 等各类工具。
同时还支持通过 **多智能体协作** 来完成复杂任务，例如多智能体任务分发、多智能体问题讨论、协同处理等。

AgentMesh项目地址：https://github.com/MinimalFuture/AgentMesh

## 安装

1. 确保已安装依赖：

```bash
pip install agentmesh-sdk>=0.1.3
```

2. 如需使用浏览器工具，还需安装：

```bash
pip install browser-use>=0.1.40
playwright install
```

## 配置

插件配置文件是 `plugins/agent`目录下的 `config.yaml`，包含智能体团队的配置以及工具的配置，可以从模板文件 `config-template.yaml`中复制：

```bash
cp config-template.yaml config.yaml
```

说明：

 - `team`配置是默认选中的 agent team
 - `teams` 下是Agent团队配置，团队的model默认为`gpt-4.1-mini`，可根据需要进行修改，模型对应的 `api_key` 需要在项目根目录的 `config.json` 全局配置中进行配置。例如openai模型需要配置 `open_ai_api_key`
 - 支持为 `agents` 下面的每个agent添加model字段来设置不同的模型


## 使用方法

在对机器人发送的消息中使用 `$agent` 前缀来触发插件，支持以下命令：

- `$agent [task]`: 使用默认团队执行任务 (默认团队可通 config.yaml 中的team配置修改)
- `$agent teams`: 列出可用的团队
- `$agent use [team_name] [task]`: 使用指定的团队执行任务


### 示例

```bash
$agent 帮我查看当前目录下有哪些文件夹
$agent teams
$agent use software_team 帮我写一个产品预约体验的表单页面
```

## 工具支持

目前支持多种内置工具，包括但不限于：

- `calculator`: 数学计算工具
- `current_time`: 获取当前时间
- `browser`: 浏览器操作工具，注意需安装`browser-use`依赖
- `google_search`: 搜索引擎，注意需在`config.yaml`中配置 `api_key`
- `file_save`: 文件保存工具，开启后智能体输出的内容将保存在 `workspace` 目录下
- `terminal`: 终端命令执行工具
