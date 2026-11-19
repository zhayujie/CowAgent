## 插件说明

可以根据需求设置入群欢迎、群聊拍一拍、退群等消息的自定义提示词，也支持为每个群设置对应的固定欢迎语。

该插件也是用户根据需求开发自定义插件的示例插件，参考[插件开发说明](https://github.com/zhayujie/CowAgent/tree/master/plugins)

## 插件配置

将 `plugins/hello` 目录下的 `config.json.template` 配置模板复制为最终生效的 `config.json`。 (如果未配置则会默认使用`config.json.template`模板中配置)。

以下是插件配置项说明：

```bash
{
    "group_welc_fixed_msg": {                   ## 这里可以为特定群里配置特定的固定欢迎语
      "群聊1": "群聊1的固定欢迎语",
      "群聊2": "群聊2的固定欢迎语"
    },

  "group_welc_prompt": "请你随机使用一种风格说一句问候语来欢迎新用户\"{nickname}\"加入群聊。",  ## 群聊随机欢迎语的提示词

  "group_exit_prompt": "请你随机使用一种风格跟其他群用户说他违反规则\"{nickname}\"退出群聊。",  ## 移出群聊的提示词

  "patpat_prompt": "请你随机使用一种风格介绍你自己，并告诉用户输入#help可以查看帮助信息。",  ## 群内拍一拍的提示词
 
  "use_character_desc": false     ## 是否在Hello插件中使用LinkAI应用的系统设定
}
```


注意：

 - 设置全局的用户进群固定欢迎语，可以在***项目根目录下***的`config.json`文件里，可以添加参数`"group_welcome_msg": "" `，参考 [#1482](https://github.com/zhayujie/CowAgent/pull/1482)
 - 为每个群设置固定的欢迎语，可以在`"group_welc_fixed_msg": {}`配置群聊名和对应的固定欢迎语，优先级高于全局固定欢迎语
 - 如果没有配置以上两个参数，则使用随机欢迎语，如需设定风格，语言等，修改`"group_welc_prompt": `即可
 - 如果使用LinkAI的服务，想在随机欢迎中结合LinkAI应用的设定，配置`"use_character_desc": true `
 - 实际 `config.json` 配置中应保证json格式，不应携带 '#' 及后面的注释
 - 如果是`docker`部署，可通过映射 `plugins/config.json` 到容器中来完成插件配置，参考[文档](https://github.com/zhayujie/CowAgent#3-%E6%8F%92%E4%BB%B6%E4%BD%BF%E7%94%A8)



