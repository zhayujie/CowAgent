# 开发任务书：微信「一键切换多角色」

> 触发方：李大海（CowAgent 助手）
> 执行方：OpenAI Codex CLI
> 版本：v1.0 ｜ 日期：2026-08-06
> 状态：待执行

---

## 一、目标（Goal）

在微信渠道（`channel_type=weixin`）中，让用户通过**文本快捷指令**一键切换助手扮演不同角色（对应不同人格/记忆/技能），实现「深度人格」切换——每个角色是**独立的 agent workspace**，拥有自己的 `AGENT.md`（人格）、`MEMORY.md` 与 `memory/`（记忆）、`skills/`、`knowledge/`，互不串味。

## 二、已确认的架构事实（Codex 必须依赖，勿推翻）

实测确认（2026-08-06）：

1. **多 agent 基建已落地**，不是 spec：
   - `agent/registry.py` → `AgentRegistry`（from_config / upsert / set_enabled / set_default / remove / list）
   - `agent/routing.py` → `AgentRouter` + `agent_bindings`（按 channel/conversation 路由，`resolve_context()`）
   - 每个 agent = 独立 workspace（独立 AGENT.md / MEMORY / memory/ / skills/ / knowledge/）
2. **微信渠道**：`channel/weixin/`，腾讯官方 **ilink bot API**（HTTP 长轮询）。**仅支持文本/图片/文件/视频消息，无法注入 UI 按钮** → 切换必须用**文本指令**。
3. **消息入口**：`channel/chat_channel.py` 的 `handle()` 处理消息，核心调用流程见下；`check_prefix()` 已有前缀剥离机制（`single_chat_prefix`）。
4. **对话持久化**：按 session_id（= 微信用户 id）存 SQLite（ConversationStore），同一用户消息在同一会话上下文内流动。
5. **运行配置**：`config.json` 当前为单 agent（`agent=true`、`agent_workspace=~/cow`），`model=deepseek-v4-flash`。

## 三、方案（Design）

### 3.1 角色 = 独立 agent workspace

利用现有多 agent 机制。每个角色对应一个 agent profile + 独立 workspace：

```
<workspace>/AGENT.md          # 该角色的人格设定
<workspace>/USER.md
<workspace>/RULE.md
<workspace>/MEMORY.md + memory/   # 独立记忆
<workspace>/skills/  <workspace>/knowledge/
```

默认角色沿用现有 `~/cow`（李大海），新增角色目录建议放 `~/cow-roles/<role>/`（或项目约定位置，Codex 需可配置，默认聚焦 1 个试点角色，避免首页铺开）。

### 3.2 切换指令（微信文本）

定义一组文本指令，由消息链路**最靠前**的指令解析层拦截（推荐在 `chat_channel.py::handle()` 处理前，或新建一个 `channel/chat_role_switch.py` 拦截器）：

- `/角色` → 弹出可选角色列表（若存在多角色）
- `/角色 <role_id>` 或 `/role <id>` → 切换到指定角色
- `/回到大海`（`/default` / `/大海`）→ 切回默认 agent（~/cow）

切换后**提示语**：「🎭 已切换为 <角色名>，此后对话由该角色回应」。

### 3.3 路由与持久化（核心难点）

切换逻辑使当前 `conversation_id`（用户微信 id）绑定到目标 agent：

- 首选：把该 conversation 的绑定写入 `agent_bindings`（channel_type=weixin + conversation_id=<用户id> → agent_id=<role>），复用 `AgentRouter.resolve_context()` 完成后续路由。
- **跨会话记住**：用户切换后，即使 bot 重启，也要保持该用户绑定的角色（需把 binding 持久化，建议落 SQLite 或 config 运行时改写；Codex 需给出可靠、可查、不引入竞态的持久化方案）。
- **切换即隔离**：新角色会话开始时默认空上下文（避免上一角色对话污染），但保留角色自身 workspace 的历史。

### 3.4 试点范围（首版收敛）

- 只做 **1 个试点角色**（建议 `coach` 职业教练，或由用户指定），先打通「建 workspace → 切换指令 → 路由 → 回复」全链路。
- 不要在第一版就做「任意角色动态创建」的复杂管理 UI；指令管理先做最小可用（静态读取已配置 agents）。

## 四、Codex 需完成的代码清单

| # | 文件/模块 | 动作 | 说明 |
|---|-----------|------|------|
| 1 | `agent/registry.py` | 复用（必要时补 API） | 确认 upsert 可在运行时新增角色 profile |
| 2 | `agent/routing.py` | 复用 | 确认 conversation 级绑定正确注入 |
| 3 | 新建 `channel/role_switch.py` | **新建** | 文本指令解析 + 路由改写 + 持久化保存用户↔角色绑定 |
| 4 | `channel/chat_channel.py` | 改 | 在 `handle()` 消息链路最前接入 role_switch 拦截器 |
| 5 | `config.py` | 改 | 支持运行时读写 agent_bindings / 新增角色的持久化配置项 |
| 6 | 试点角色 workspace | 创建 | 1 个角色的 AGENT.md（人格）+ 空记忆结构。人格内容占位即可 |
| 7 | 测试 | 新增 | role_switch 单元测试 + AgentRouter conversation 绑定测试 |

> 禁止改动：`channel/weixin/` 协议层、大模型调用层、现有默认 agent 行为（除非任务要求）。

## 五、验收标准（Acceptance Criteria）

1. 微信私聊发送 `/角色` 能展示可用角色列表文本。
2. 发送 `/角色 coach` 后：大海回复「已切换」，且后续消息由 coach 人格回应（可用一句能体现人格差异的提问验证）。
3. 切换后角色**独立记忆**：coach 记忆不污染默认 agent 的记忆，反之亦然。
4. **跨重启保持**：重启 CowAgent 后，该用户仍是 coach 角色。
5. `/回到大海` 能切回默认 agent。
6. 现有单 agent 行为不受影响（默认用户不发指令时仍是李大海）。
7. 全部新代码有测试，`pytest` 通过；不得破坏既有测试。

## 六、技术约束与风险

- **微信无 UI 按钮**：全程文本指令，不要试图注入按钮。
- **首版收敛**：勿过度设计（不做动态角色市场、不做复杂配置 GUI）。
- **不破坏单 agent**：零配置场景（不发任何 `/角色` 指令）必须与现在完全一致。
- **持久化竞态**：绑定写入需考虑多线程/env 重载竞态，用锁或原子写。

## 七、Codex 自检清单（完成后逐条打勾）

- [ ] 切换指令在微信端可用
- [ ] 角色记忆隔离验证通过
- [ ] 跨重启保持通过
- [ ] 回到默认通过
- [ ] 单 agent 行为不回归
- [ ] 测试全绿
