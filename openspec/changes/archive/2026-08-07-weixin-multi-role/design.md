## 技术方案

### 架构概览

```
微信消息 → chat_channel.produce()
              │
              ├─ role_switch.handle_role_command() ── 命中 → 直接回复 → RETURN
              │       (在 route_context 之前执行，绑定停用角色时仍可自救)
              │
              └─ 未命中 → agent_bridge.route_context() → Agent pipeline (不变)
```

### 组件

| 组件 | 路径 | 职责 |
|------|------|------|
| RoleBindingStore | channel/role_switch.py | 线程安全的 JSON 持久化存储，原子写入 |
| 指令拦截 | channel/role_switch.py::handle_role_command() | 正则匹配 + 指令分发 + 回复生成 |
| 角色切换 | channel/role_switch.py::_cmd_switch_role() | 校验 + 持久化 + 配置同步 + 路由刷新 |
| 切回默认 | channel/role_switch.py::_cmd_switch_to_default() | 移除绑定并刷新路由 |
| 启动加载 | channel/role_switch.py::load_role_bindings_on_startup() | 合并持久化绑定到 conf()["agent_bindings"] |
| 绑定合并 | channel/role_switch.py::_merge_bindings() | 去重合并既有配置与角色绑定 |
| 路由刷新 | bridge/agent_bridge.py::refresh_router() | 重建 AgentRouter 使绑定立即生效 |
| 接入点 | channel/chat_channel.py::produce() | 在 route_context、/cancel、/steer 之前 |

### 数据流

1. 用户发送 `/角色 coach`
2. `produce()` 调用 `handle_role_command()` → 匹配 `/角色 <id>` 正则
3. 校验 `coach` 在 AgentRegistry 中存在且启用
4. `store.set_binding("weixin", user_id, "coach")` → 原子写入 JSON
5. `_sync_bindings_to_config()` → 合并到 `conf()["agent_bindings"]`
6. `_rebuild_router()` → 重建 AgentRouter
7. 回复 "已切换为【职业教练】..."
8. 下一条消息经 `route_context()` → AgentRouter 匹配 `(weixin, user_id)` → 路由到 `coach`

### 持久化格式 (与 agent_bindings 兼容)

```json
[
  {"channel_type": "weixin", "conversation_id": "wxid_abc123", "agent_id": "coach"}
]
```

默认路径: `~/.cow/role_bindings.json`，可通过 `role_bindings_path` 配置覆盖。

### 指令语法

| 指令 | 功能 |
|------|------|
| `/角色` 或 `/role` | 列出可用角色 (简要) |
| `/角色列表` 或 `/roles` 或 `/role list` | 列出可用角色 (详细含描述) |
| `/角色 <id>` 或 `/role <id>` | 切换到指定角色 (大小写不敏感) |
| `/回到大海` 或 `/default` 或 `/大海` | 切回默认 agent (清除绑定) |

### 教练角色 (coach)

- workspace 路径: `~/cow-roles/coach` (可通过 `role_workspace_root` 配置)
- AGENT.md: 职业教练人格提示词
- memory/: 独立记忆目录
- skills/: 独立技能目录
- knowledge/: 独立知识库目录

### 安全性

- RoleBindingStore 使用 `threading.Lock` 保护竞态
- 原子写入: 先写 `.tmp` 再 `os.replace`
- 不修改任何配置文件的 agent_bindings 段 (只运行时合并)
- 不处理 `/角色` 指令时行为完全不变

### 错误处理

| 场景 | 行为 |
|------|------|
| 角色 id 不存在或已禁用 | 回复提示可用角色列表，不修改绑定 |
| 角色 id 大小写不一致 | 忽略大小写匹配已启用角色 |
| 绑定到随后被停用的 agent | `/角色`、`/回到大海` 仍在路由前拦截，用户可自救 |
| 绑定文件损坏 | 跳过非法条目并告警；无法解析时降级为空绑定 |
| 存储写入失败 | 记录错误日志，回复通用失败文案 |
| 路由重建失败 | 记录错误日志，绑定已持久化但需重启生效 |
