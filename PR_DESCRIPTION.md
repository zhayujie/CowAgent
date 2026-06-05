# feat(web): 消息管理与代码块增强

## 📋 功能概述

本次更新为 Web Console 新增了完整的消息管理功能和代码块增强，提升用户交互体验。

## ✨ 新增功能

### 1. 消息操作（编辑/删除/重新生成）

**用户消息操作：**
- ✏️ **编辑消息**：点击编辑按钮，提取消息内容到输入框，级联删除当前消息及后续所有消息
- 🗑️ **删除消息**：删除用户消息及其对应的助手回复
- 悬停显示操作按钮，界面更简洁

**助手回复操作：**
- 🔄 **重新生成**：删除旧回复，重新发送用户消息获取新回复
- 🗑️ **删除回复**：单独删除助手回复，保留用户消息

**技术实现：**
- 前端：添加操作按钮和事件处理，调用后端 API 同步数据库
- 后端：新增 `POST /api/messages/delete` 接口
  - `delete_user`: 是否删除用户消息（默认 true）
  - `cascade`: 是否级联删除后续所有消息（默认 false）
- 数据库：`ConversationStore.delete_message_pair()` 方法
  - 正确识别 tool_result 消息边界（使用 `_is_visible_user_message()` 过滤）
  - 使用 RLock 避免死锁
  - 删除后同步更新 agent 内存上下文

### 2. 代码块增强

- 🏷️ **语言标签**：在代码块顶部显示编程语言名称
- 📋 **一键复制**：添加复制按钮，点击后复制代码内容
- 🎨 **样式优化**：代码块包裹在带边框的容器中，支持亮色/暗色主题
- 通过 DOM 操作动态添加，避免 innerHTML 注入风险

### 3. 拖拽上传增强

- 📂 **全屏拖拽**：从输入框区域扩展到整个聊天视图
- 🎯 **视觉反馈**：拖拽时显示全屏覆盖层和提示动画
- 🛡️ **防误触**：使用 `dragCounter` 正确处理嵌套元素的 dragenter/dragleave 事件

### 4. 剪贴板兼容性

- 添加 `copyToClipboard()` 辅助函数
- 支持 HTTP 环境（使用 `document.execCommand('copy')` fallback）
- 统一所有复制操作的实现

## 🐛 Bug 修复

1. **tool_result 边界识别错误**：修复 `delete_message_pair` 错误将 tool_result 当作可见用户消息的问题
2. **regenerateResponse 数据不一致**：修复只删 DOM 不删数据库导致刷新后旧回复重现的问题
3. **editUserMessage 数据不一致**：修复编辑消息后数据库残留旧消息的问题
4. **单独删 bot 回复无效**：修复只删 DOM 不删数据库的问题
5. **Lock 死锁风险**：将 `threading.Lock` 改为 `threading.RLock`，允许 `delete_message_pair` 内部调用 `load_messages`

## 📊 改动统计

```
 agent/memory/conversation_store.py | 106 ++++++++-
 channel/web/static/css/console.css | 168 ++++++++++++++
 channel/web/static/js/console.js   | 434 +++++++++++++++++++++++++++++++++++-
 channel/web/web_channel.py         |  51 +++++
 4 files changed, 748 insertions(+), 11 deletions(-)
```

## 🧪 测试场景

### 消息操作
- [x] 删除整条对话（user + bot reply）
- [x] 重新生成回复（删除旧回复，重新请求）
- [x] 编辑用户消息（级联删除后续消息）
- [x] 单独删除 bot 回复
- [x] 删除包含 tool_result 的消息（正确跳过 tool_result）

### 代码块
- [x] 代码块显示语言标签
- [x] 点击复制按钮复制代码
- [x] 亮色/暗色主题切换正常

### 拖拽上传
- [x] 拖拽文件到聊天视图任意位置
- [x] 显示拖拽覆盖层和提示
- [x] 释放文件后正常上传

### 数据一致性
- [x] 删除消息后刷新页面，数据库和 DOM 保持一致
- [x] 重新生成后刷新页面，只显示新回复
- [x] 编辑消息后刷新页面，旧消息已删除

## 🔧 API 文档

### POST /api/messages/delete

删除指定消息及其助手回复。

**请求参数：**
```json
{
  "session_id": "session_xxx",
  "user_seq": 5,
  "delete_user": true,
  "cascade": false
}
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| session_id | string | ✅ | - | 会话 ID |
| user_seq | int | ✅ | - | 用户消息的 seq 编号 |
| delete_user | bool | ❌ | true | 是否删除用户消息 |
| cascade | bool | ❌ | false | 是否级联删除后续所有消息 |

**响应：**
```json
{
  "status": "success",
  "deleted": 2
}
```

**使用场景：**

| 场景 | delete_user | cascade | 效果 |
|------|:-----------:|:-------:|------|
| 删除整条对话 | `true` | `false` | 删 user + bot reply |
| 重新生成 | `true` | `false` | 删 user + bot reply，然后重新发送 |
| 编辑消息 | `true` | `true` | 删 user + bot reply + 所有后续消息 |
| 单独删 bot 回复 | `false` | `false` | 只删 bot reply |

## 📝 注意事项

1. **异步操作**：前端使用 `await` 确保数据库删除完成后再更新 DOM，避免竞态条件
2. **内存同步**：删除消息后自动重建 agent 的内存上下文，确保后续对话基于最新历史
3. **国际化**：所有新增文本支持中英文切换
4. **主题适配**：所有新增样式支持亮色/暗色主题

## 🎯 后续优化建议

1. 添加删除确认对话框的"不再提示"选项
2. 支持批量删除消息
3. 添加撤销删除功能（软删除 + 定时清理）
4. 代码块支持折叠/展开长代码
