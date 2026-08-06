"""微信渠道角色切换指令拦截器。

在 chat_channel.py::produce() 消息链路最前端拦截 /角色 系列文本指令，
完成"指令解析 → 路由改写 → 持久化保存"三步操作后直接回复确认文本，
不进入后续 agent pipeline。

持久化通过 RoleBindingStore 实现，以 JSON 文件为载体，使用线程锁 +
原子写保证竞态安全。启动时加载并合并到 conf()["agent_bindings"]。
"""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

from common.log import logger
from common.i18n import t as _t


# ---- 指令正则 ---------------------------------------------------------------

# 匹配: /角色, /角色 <id>, /角色列表, /role, /role <id>
_ROLE_LIST_RE = re.compile(r"^/(?:角色列表|roles|role\s+list)\s*$", re.IGNORECASE)
_ROLE_SWITCH_RE = re.compile(
    r"^/(?:角色|role)\s+([A-Za-z0-9][A-Za-z0-9_-]{0,63})\s*$", re.IGNORECASE
)
_ROLE_SHOW_RE = re.compile(r"^/(?:角色|roles?)\s*$", re.IGNORECASE)

# 回到默认 agent（大海）
_ROLE_DEFAULT_RE = re.compile(r"^/(?:回到大海|default|大海)\s*$", re.IGNORECASE)


def _strip_at_mention(content: str, bot_name: str = "") -> str:
    """移除消息开头的 @bot 前缀，返回净文本。"""
    content = content.strip()
    if bot_name:
        pattern = rf"^@{re.escape(bot_name)}(\u2005|\u0020|\s)*"
        content = re.sub(pattern, "", content).strip()
    return content


# ---- RoleBindingStore -------------------------------------------------------


class RoleBindingStore:
    """线程安全的角色绑定持久化存储。

    使用 JSON 文件存储，格式与 agent_bindings 兼容：
        [{"channel_type": "weixin", "conversation_id": "<user_id>", "agent_id": "coach"}]

    写入使用写临时文件 + 原子重命名策略，避免读取方看到半截数据。
    """

    def __init__(self, file_path: str):
        self._file_path = os.path.expanduser(file_path)
        self._lock = threading.Lock()
        self._bindings: List[Dict[str, str]] = []
        self._load()

    # -- public API -----------------------------------------------------------

    def get_bindings(self) -> List[Dict[str, str]]:
        """返回当前所有绑定条目的快照。"""
        with self._lock:
            return list(self._bindings)

    def set_binding(
        self, channel_type: str, conversation_id: str, agent_id: Optional[str]
    ) -> None:
        """设置（添加或更新）一条 conversation 级别的角色绑定。

        同一 (channel_type, conversation_id) 只保留最近一次绑定。
        agent_id 为 None 时移除该绑定。
        """
        with self._lock:
            self._bindings = [
                b
                for b in self._bindings
                if not (
                    b.get("channel_type") == channel_type
                    and b.get("conversation_id") == conversation_id
                )
            ]
            if agent_id:
                self._bindings.append(
                    {
                        "channel_type": channel_type,
                        "conversation_id": conversation_id,
                        "agent_id": agent_id,
                    }
                )
            self._save()

    def get_binding(self, channel_type: str, conversation_id: str) -> Optional[str]:
        """查询某 conversation 的绑定 agent_id，无绑定时返回 None。"""
        with self._lock:
            for b in self._bindings:
                if (
                    b.get("channel_type") == channel_type
                    and b.get("conversation_id") == conversation_id
                ):
                    return b.get("agent_id")
            return None

    def remove_binding(self, channel_type: str, conversation_id: str) -> bool:
        """移除绑定，返回是否实际移除了条目。"""
        with self._lock:
            before = len(self._bindings)
            self._bindings = [
                b
                for b in self._bindings
                if not (
                    b.get("channel_type") == channel_type
                    and b.get("conversation_id") == conversation_id
                )
            ]
            if len(self._bindings) != before:
                self._save()
                return True
            return False

    # -- internal -------------------------------------------------------------

    def _load(self) -> None:
        try:
            if os.path.exists(self._file_path):
                with open(self._file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    valid = [b for b in data if self._is_valid_binding(b)]
                    if len(valid) != len(data):
                        logger.warning(
                            f"[role_switch] 已跳过 {len(data) - len(valid)} 条非法角色绑定"
                        )
                    self._bindings = valid
                    logger.info(
                        f"[role_switch] 已加载 {len(valid)} 条角色绑定: {self._file_path}"
                    )
        except Exception as e:
            logger.warning(f"[role_switch] 加载角色绑定失败: {e}")
            self._bindings = []

    @staticmethod
    def _is_valid_binding(b: Any) -> bool:
        """校验单条绑定结构：三字段均为非空字符串。"""
        if not isinstance(b, dict):
            return False
        for key in ("channel_type", "conversation_id", "agent_id"):
            value = b.get(key)
            if not isinstance(value, str) or not value.strip():
                return False
        return True

    def _save(self) -> None:
        """原子写入：先写临时文件，再重命名。"""
        tmp_path = self._file_path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self._file_path) or ".", exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._bindings, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._file_path)
            logger.debug(f"[role_switch] 已持久化 {len(self._bindings)} 条角色绑定")
        except Exception as e:
            logger.error(f"[role_switch] 持久化角色绑定失败: {e}")


# ---- 单例 + 启动加载 --------------------------------------------------------

_store_instance: Optional[RoleBindingStore] = None
_store_lock = threading.Lock()


def _default_bindings_path() -> str:
    """默认绑定文件路径，优先使用 config 中配置的值。"""
    try:
        from config import conf

        configured = conf().get("role_bindings_path", "")
        if configured:
            return configured
    except Exception:
        pass
    return os.path.expanduser("~/.cow/role_bindings.json")


def get_role_binding_store() -> RoleBindingStore:
    """获取 RoleBindingStore 单例。"""
    global _store_instance
    with _store_lock:
        if _store_instance is None:
            _store_instance = RoleBindingStore(_default_bindings_path())
        return _store_instance


def _merge_bindings(
    existing: List[Dict[str, Any]], store_bindings: List[Dict[str, str]]
) -> List[Dict[str, Any]]:
    """合并既有配置绑定与角色绑定，角色绑定优先。

    保留既有配置中不与角色绑定冲突的条目，再将角色绑定追加到末尾。
    """
    store_keys = {(b["channel_type"], b["conversation_id"]) for b in store_bindings}
    merged = [
        b
        for b in existing
        if (b.get("channel_type"), b.get("conversation_id")) not in store_keys
    ]
    merged.extend(store_bindings)
    return merged


def load_role_bindings_on_startup() -> None:
    """启动时调用：将持久化的角色绑定合并到 config["agent_bindings"]。

    角色绑定条目 vs 配置文件中的 agent_bindings：
    - 配置文件中的 agent_bindings 不会改写
    - 持久化的角色绑定追加到 agent_bindings 列表末尾
    - 重复的 (channel_type, conversation_id) 以角色绑定优先
    """
    try:
        store = get_role_binding_store()
        store_bindings = store.get_bindings()
        if not store_bindings:
            return

        from config import conf

        existing: List[Dict[str, Any]] = list(conf().get("agent_bindings") or [])
        conf()["agent_bindings"] = _merge_bindings(existing, store_bindings)
        logger.info(
            f"[role_switch] 已合并 {len(store_bindings)} 条角色绑定到 agent_bindings"
        )
    except Exception as e:
        logger.warning(f"[role_switch] 启动加载角色绑定失败: {e}")


# ---- 指令处理 ---------------------------------------------------------------


def _rebuild_router(agent_bridge) -> None:
    """角色切换后重建路由表，使新的 agent_bindings 立即生效。

    通过 AgentBridge 公开的 refresh_router() 刷新缓存路由，避免直接
    操作内部字段。
    """
    try:
        agent_bridge.refresh_router()
        logger.debug("[role_switch] 路由表已重建")
    except Exception as e:
        logger.error(f"[role_switch] 重建路由表失败: {e}")


def handle_role_command(
    content: str,
    channel_type: str,
    session_id: str,
    agent_bridge,
    bot_name: str = "",
) -> Tuple[bool, Optional[str]]:
    """解析并处理角色切换指令。

    Args:
        content: 净文本内容（已剥离 chat prefix）
        channel_type: 渠道类型
        session_id: 用户标识（微信用户 id）
        agent_bridge: AgentBridge 实例
        bot_name: bot 名称，用于剥除 @bot

    Returns:
        (handled, reply_text)
        - handled=False: 不是角色指令，继续正常流程
        - handled=True, reply_text 不为空: 已处理，回复此文本
    """
    stripped = _strip_at_mention(content, bot_name)

    # -- /角色列表 或 /roles 或 /role list -----------------------------------
    if _ROLE_LIST_RE.match(stripped):
        return _cmd_list_roles(agent_bridge)

    # -- /角色（无参数）或 /roles —— 显示简要列表 ----------------------------
    if _ROLE_SHOW_RE.match(stripped):
        return _cmd_list_roles(agent_bridge, brief=True)

    # -- /角色 <id> 或 /role <id> -------------------------------------------
    m = _ROLE_SWITCH_RE.match(stripped)
    if m:
        role_id = m.group(1)
        return _cmd_switch_role(channel_type, session_id, role_id, agent_bridge)

    # -- /回到大海 或 /default 或 /大海 -------------------------------------
    if _ROLE_DEFAULT_RE.match(stripped):
        return _cmd_switch_to_default(channel_type, session_id, agent_bridge)

    return False, None


def _cmd_list_roles(agent_bridge, brief: bool = False) -> Tuple[bool, Optional[str]]:
    """生成可用角色列表文本。"""
    try:
        registry = agent_bridge.agent_registry
        profiles = registry.list(include_disabled=False)
        if len(profiles) <= 1:
            return True, _t(
                "当前仅有一个助手角色，无需切换。",
                "There is only one assistant role, no switch needed.",
            )

        default_id = registry.default_agent_id
        lines = [_t("可用角色：", "Available roles:")]
        for p in profiles:
            marker = _t("（默认）", " (default)") if p.id == default_id else ""
            if brief:
                lines.append(f"  /角色 {p.id} {marker}")
            else:
                lines.append(f"  {p.id} — {p.name} {marker}")
        lines.append("")
        lines.append(
            _t(
                '发送 "/角色 <id>" 切换，发送 "/回到大海" 切回默认。',
                'Send "/角色 <id>" to switch, "/回到大海" to go back to default.',
            )
        )
        return True, "\n".join(lines)
    except Exception as e:
        logger.error(f"[role_switch] 列出角色失败: {e}")
        return True, _t(
            "获取角色列表失败，请稍后重试。",
            "Failed to list roles, please try again later.",
        )


def _resolve_role_id(registry, role_id: str) -> Optional[str]:
    """大小写不敏感地解析角色 id。

    优先精确匹配；否则在已启用角色中忽略大小写查找，避免用户输入
    大小写与配置不一致时无法切换（agent id 本身大小写敏感）。
    """
    try:
        registry.get(role_id, require_enabled=True)
        return role_id
    except Exception:
        pass
    lowered = role_id.lower()
    for profile in registry.list(include_disabled=False):
        if profile.id.lower() == lowered:
            return profile.id
    return None


def _cmd_switch_role(
    channel_type: str,
    session_id: str,
    role_id: str,
    agent_bridge,
) -> Tuple[bool, Optional[str]]:
    """切换到指定角色。"""
    try:
        registry = agent_bridge.agent_registry

        # 大小写不敏感解析：优先精确匹配，其次忽略大小写匹配已启用角色。
        resolved_role = _resolve_role_id(registry, role_id)
        if resolved_role is None:
            available = [p.id for p in registry.list(include_disabled=False)]
            hint = "、".join(available)
            return True, _t(
                f"角色「{role_id}」不存在或已禁用。可用角色：{hint}",
                f"Role '{role_id}' does not exist or is disabled. Available: {hint}",
            )

        # 已是当前角色则提示
        existing_binding = get_role_binding_store().get_binding(
            channel_type, session_id
        )
        if existing_binding == resolved_role:
            profile = registry.get(resolved_role, require_enabled=False)
            return True, _t(
                f"当前已是「{profile.name}」角色，无需重复切换。",
                f"You are already in the '{profile.name}' role.",
            )

        # 如果切到默认角色，等同切回大海
        if resolved_role == registry.default_agent_id:
            return _cmd_switch_to_default(channel_type, session_id, agent_bridge)

        # 校验目标角色存在且启用
        try:
            profile = registry.get(resolved_role, require_enabled=True)
        except Exception:
            return True, _t(
                f"角色「{role_id}」不存在或已禁用。",
                f"Role '{role_id}' does not exist or is disabled.",
            )

        # 更新持久化存储
        store = get_role_binding_store()
        store.set_binding(channel_type, session_id, resolved_role)

        # 更新 conf()["agent_bindings"] 并重建路由
        _sync_bindings_to_config(store)
        _rebuild_router(agent_bridge)

        logger.info(
            f"[role_switch] 用户 {session_id} 切换到角色 {resolved_role} ({profile.name})"
        )
        default_name = registry.get(registry.default_agent_id).name
        return True, _t(
            f"已切换为「{profile.name}」，此后对话由该角色回应。\n"
            f'发送 "/回到大海" 可切回「{default_name}」。',
            f"Switched to '{profile.name}'. This role will answer your future "
            f"messages. Send '/回到大海' to go back to '{default_name}'.",
        )
    except Exception as e:
        logger.error(f"[role_switch] 切换角色失败: {e}")
        return True, _t(
            "角色切换失败，请稍后重试。", "Role switch failed, please try again later."
        )


def _cmd_switch_to_default(
    channel_type: str,
    session_id: str,
    agent_bridge,
) -> Tuple[bool, Optional[str]]:
    """切回默认 agent。"""
    try:
        registry = agent_bridge.agent_registry
        default_id = registry.default_agent_id
        default_profile = registry.get(default_id)

        # 移除持久化绑定
        store = get_role_binding_store()
        removed = store.remove_binding(channel_type, session_id)

        # 更新 conf()["agent_bindings"] 并重建路由
        if removed:
            _sync_bindings_to_config(store, exclude={(channel_type, session_id)})
            _rebuild_router(agent_bridge)

        if not removed:
            return True, _t(
                f"当前已是默认角色「{default_profile.name}」。",
                f"You are already in the default role '{default_profile.name}'.",
            )

        logger.info(f"[role_switch] 用户 {session_id} 切回默认角色")
        return True, _t(
            f"已切回「{default_profile.name}」，此后对话由默认角色回应。",
            f"Switched back to '{default_profile.name}'. Your future messages "
            f"will be answered by the default role.",
        )
    except Exception as e:
        logger.error(f"[role_switch] 切回默认角色失败: {e}")
        return True, _t(
            "角色切换失败，请稍后重试。", "Role switch failed, please try again later."
        )


def _sync_bindings_to_config(
    store: RoleBindingStore,
    exclude: Optional[Set[Tuple[str, str]]] = None,
) -> None:
    """将持久化存储中的绑定同步到 conf()["agent_bindings"].

    exclude: 需从 conf 中剔除的 (channel_type, conversation_id) 集合，
    用于角色被移除（如切回默认）后清理此前合并进 conf 的残留条目。
    """
    try:
        from config import conf

        existing: List[Dict[str, Any]] = list(conf().get("agent_bindings") or [])
        keys = {
            (channel_type, conversation_id)
            for (channel_type, conversation_id) in exclude or set()
        }
        if keys:
            existing = [
                b
                for b in existing
                if (b.get("channel_type"), b.get("conversation_id")) not in keys
            ]
        conf()["agent_bindings"] = _merge_bindings(existing, store.get_bindings())
    except Exception as e:
        logger.error(f"[role_switch] 同步绑定到 config 失败: {e}")
