用于让Bot扮演指定角色的聊天插件，触发方法如下：

- `$角色/$role help/帮助` - 打印目前支持的角色列表。
- `$角色/$role <角色名>` - 让AI扮演该角色，角色名支持模糊匹配。
- `$角色类型 <类型>` - 按分类浏览角色（如 `$角色类型 写作`，`$角色类型 所有`）。
- `$设定扮演 <自定义设定>` - 直接输入自定义角色设定，无需预设角色。
- `$停止扮演` - 停止角色扮演。

## 添加自定义角色

在 `roles/` 目录下新建一个 `.json` 文件，参考模板 `Role_Schema/Role Schema.json`：

```
plugins/role/
├── Role_Schema/
│   └── Role Schema.json    ← 角色JSON模板（含字段说明）
├── roles/                   ← 自定义角色文件放这里
│   ├── writing_assistant.json
│   ├── cat_girl.json
│   └── ...
├── role_file_map.json       ← 自动生成的角色名→文件名映射表
└── tag.json                 ← 角色分类标签定义
```

模板 `Role_Schema/Role Schema.json` 内容如下：

```json5
{
    "title": "角色名",
    "description": "英文prompt（使用$role触发时）",
    "descn": "中文prompt（使用$角色触发时）",
    "wrapper": "内容包装格式，%s 为用户输入",
    "remark": "简短角色描述，在帮助文档中显示",
    "tags": [
        "favorite",
        "write"
    ]
}
```

字段说明：
- `title`: 角色名。
- `description`: 使用 `$role` 触发时，使用英语 prompt。
- `descn`: 使用 `$角色` 触发时，使用中文 prompt。
- `wrapper`: 用于包装用户消息，可起到强调作用，避免回复离题。
- `remark`: 简短描述该角色，在打印帮助文档时显示。
- `tags`: 角色分类标签，可选值见 `tag.json`（常用、写作、编程、生活百科 等）。

添加/删除角色文件后，重启插件即可自动同步 `role_file_map.json`，无需手动维护映射表。

(大部分 prompt 来自 https://github.com/rockbenben/ChatGPT-Shortcut/blob/main/src/data/users.tsx)
