## Why

CowAgent 当前仅支持单一 Agent 与用户对话，缺乏"一键切换多个助手角色"的能力。用户在不同场景（如职业教练、编程助手、翻译等）需要手动修改配置才能使用不同的 agent workspace，切换成本高。

## What Changes

本变更实现"微信一键切换多角色"功能，核心改动：

1. **指令拦截器**: 在 `chat_channel.py::produce()` 消息链路最前端接入角色指令拦截，识别 `/角色`、`/角色 <id>`、`/回到大海` 等指令后直接回复确认文本，不进入 Agent pipeline

2. **角色绑定持久化**: `RoleBindingStore` (JSON + 线程锁 + 原子写) 存储用户角色绑定，启动时合并到 `conf()["agent_bindings"]`，重启后仍保持绑定

3. **动态路由重载**: 角色切换后重建 `AgentRouter`，使新绑定立即生效

4. **教练示例角色**: 创建 `~/cow-roles/coach` 独立 workspace (含 AGENT.md 人格、memory/skills/knowledge 骨架)

5. **单元测试**: `role_switch` 指令解析、绑定持久化、AgentRouter conversation 绑定

**边界（不改变）**:
- 不改动 `channel/weixin/` 协议层
- 不改动大模型调用层
- 用户不发送 `/角色` 系列指令时行为与现在完全一致

## 能力 (Capabilities)

- 微信消息中识别 `/角色`、`/角色 <id>`、`/回到大海` 等指令并即时回复
- 用户级角色绑定持久化，重启后保持
- 角色切换后路由立即生效（无需重启）
- 独立 coach workspace 提供职业教练人格

## 影响范围 (Impact)

- 修改：`channel/chat_channel.py::produce()`（接入指令拦截）
- 修改：`config.py::load_config()`（启动加载角色绑定）
- 新增：`channel/role_switch.py`（指令拦截器 + RoleBindingStore）
- 新增：`~/cow-roles/coach/`（示例角色 workspace）
- 新增：`tests/test_role_*.py`（单元测试）
- 修改：`config.json`（agents 数组注册 coach）
