## 实现任务

### Task 1: 完善 channel/role_switch.py (保留现有草稿)
- [x] 审查现有草稿代码质量，确认无 P0 问题
- [x] 确认 `@bot` 前缀剥离逻辑与 chat_channel.py 兼容
- [x] 确认 `_cmd_list_roles` 中 `registry.list()` 调用正确
- [x] 确认 `_cmd_switch_role` 去重检查 (已相同角色)
- **变更范围**: `channel/role_switch.py` (修改)
- **依赖**: 无

### Task 2: 在 chat_channel.py::produce() 接入角色指令拦截
- [x] 在 produce() 中 `/cancel` 和 `/steer` 快速路径之前，加入角色指令处理
- [x] 角色指令通过 `handle_role_command()` 处理
- [x] 处理 `bot_name` 参数传入 (用于 @bot 剥离)
- [x] 命中后直接 `_send_reply` 返回，不进入队列
- **变更范围**: `channel/chat_channel.py` (修改 `produce()` 方法)
- **依赖**: Task 1

### Task 3: 在 config.py::load_config() 添加角色绑定启动加载
- [x] 在 AgentRegistry 初始化后调用 `load_role_bindings_on_startup()`
- **变更范围**: `config.py` (修改 `load_config()`)
- **依赖**: Task 1

### Task 4: 创建教练示例角色 workspace
- [x] 创建 `~/cow-roles/coach/` 目录结构
- [x] 编写 `AGENT.md` (职业教练人格)
- [x] 创建 `memory/`、`skills/`、`knowledge/` 空目录骨架
- [x] 在 config.json 的 agents 数组中注册 coach
- **变更范围**: `~/cow-roles/coach/` (新增), `config.json` (修改 agents 段)
- **依赖**: AgentRegistry 加载机制

### Task 5: 编写单元测试
- [x] `test_role_switch_commands.py`: 指令解析测试 (所有指令变体)
- [x] `test_role_binding_store.py`: 持久化 CRUD + 原子写 + 并发安全
- [x] `test_role_routing_integration.py`: 绑定后 AgentRouter 正确路由
- [x] `test_role_switch_recover.py`: 绑定停用角色后的自救行为
- [x] 运行 `pytest` 确认全部通过
- **变更范围**: `tests/` (新增测试文件)
- **依赖**: Task 1, Task 2, Task 3

### Task 6: 文档与配置登记
- [x] 在 config-template.json 中登记 `role_bindings_path` 配置键
- [x] 更新 tasks.md 任务状态与依赖关系
- **变更范围**: `config-template.json` (修改)
- **依赖**: Task 1
