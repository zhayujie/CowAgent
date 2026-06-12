"""
System Prompt Builder - 系统提示词构建器

实现模块化的系统提示词构建，支持工具、技能、记忆等多个子系统
"""

from __future__ import annotations
import os
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

from common.log import logger
from config import conf


@dataclass
class ContextFile:
    """A context file (path + content)."""
    path: str
    content: str


class PromptBuilder:
    """System prompt builder."""
    
    def __init__(self, workspace_dir: str, language: str = "zh"):
        """
        初始化提示词构建器
        
        Args:
            workspace_dir: 工作空间目录
            language: 语言 ("zh" 或 "en")
        """
        self.workspace_dir = workspace_dir
        self.language = language
    
    def build(
        self,
        base_persona: Optional[str] = None,
        user_identity: Optional[Dict[str, str]] = None,
        tools: Optional[List[Any]] = None,
        context_files: Optional[List[ContextFile]] = None,
        skill_manager: Any = None,
        memory_manager: Any = None,
        runtime_info: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """
        构建完整的系统提示词
        
        Args:
            base_persona: 基础人格描述（会被context_files中的AGENT.md覆盖）
            user_identity: 用户身份信息
            tools: 工具列表
            context_files: 上下文文件列表（AGENT.md, USER.md, RULE.md, BOOTSTRAP.md等）
            skill_manager: 技能管理器
            memory_manager: 记忆管理器
            runtime_info: 运行时信息
            **kwargs: 其他参数
            
        Returns:
            完整的系统提示词
        """
        return build_agent_system_prompt(
            workspace_dir=self.workspace_dir,
            language=self.language,
            base_persona=base_persona,
            user_identity=user_identity,
            tools=tools,
            context_files=context_files,
            skill_manager=skill_manager,
            memory_manager=memory_manager,
            runtime_info=runtime_info,
            **kwargs
        )


def build_agent_system_prompt(
    workspace_dir: str,
    language: str = "zh",
    base_persona: Optional[str] = None,
    user_identity: Optional[Dict[str, str]] = None,
    tools: Optional[List[Any]] = None,
    context_files: Optional[List[ContextFile]] = None,
    skill_manager: Any = None,
    memory_manager: Any = None,
    runtime_info: Optional[Dict[str, Any]] = None,
    **kwargs
) -> str:
    """
    Build the agent system prompt.

    Section order (by importance and logical flow):
    1. Tooling - core capabilities, introduced first
    2. Skills - right after tools, since skills are read via the read tool
    3. Memory - memory recall and writing guidance
    3.5 Knowledge - structured knowledge base (injects knowledge/index.md)
    4. Workspace - working environment description
    5. User identity - user info (optional)
    6. Project context - AGENT.md, USER.md, RULE.md, MEMORY.md, BOOTSTRAP.md
    7. Runtime info - meta info (time, model, etc.)

    Args:
        workspace_dir: workspace directory
        language: language ("zh" or "en")
        base_persona: base persona description (deprecated, defined by AGENT.md)
        user_identity: user identity info
        tools: tool list
        context_files: context file list
        skill_manager: skill manager
        memory_manager: memory manager
        runtime_info: runtime info
        **kwargs: extra args

    Returns:
        The full system prompt.
    """
    sections = []

    # 1. Tooling (most important, goes first)
    if tools:
        sections.extend(_build_tooling_section(tools, language))

    # 2. Skills (right after tools, since they need the read tool)
    if skill_manager:
        sections.extend(_build_skills_section(skill_manager, tools, language))

    # 3. Memory (standalone memory capability)
    if memory_manager:
        sections.extend(_build_memory_section(memory_manager, tools, language))

    # 3.5 Knowledge (structured knowledge base)
    if conf().get("knowledge", True):
        sections.extend(_build_knowledge_section(workspace_dir, language))

    # 4. Workspace (working environment description)
    sections.extend(_build_workspace_section(workspace_dir, language))

    # 5. User identity (if present)
    if user_identity:
        sections.extend(_build_user_identity_section(user_identity, language))

    # 6. Project context files (AGENT.md, USER.md, RULE.md - define the persona)
    if context_files:
        sections.extend(_build_context_files_section(context_files, language))

    # 7. Runtime info (meta info, goes last)
    if runtime_info:
        sections.extend(_build_runtime_section(runtime_info, language))

    # 8. Response language (always appended, independent of the skeleton language)
    sections.extend(_build_response_language_section(language))

    return "\n".join(sections)


def _build_response_language_section(language: str) -> List[str]:
    """Response-language rule, appended regardless of the prompt skeleton language.

    Keeps the agent's reply language aligned with the user's input by default,
    so a Chinese-built prompt still answers an English user in English.
    """
    if language == "en":
        return [
            "## 🌐 Response language",
            "",
            "By default, reply in the same language as the user's input, "
            "unless the user explicitly asks for another language.",
            "",
        ]
    return [
        "## 🌐 回复语言",
        "",
        "默认使用与用户输入相同的语言回复，除非用户明确要求使用其他语言。",
        "",
    ]


def _build_identity_section(base_persona: Optional[str], language: str) -> List[str]:
    """Base identity section - no longer needed, identity is defined by AGENT.md."""
    # Identity is fully defined by AGENT.md, so emit nothing here.
    return []


def _build_tooling_section(tools: List[Any], language: str) -> List[str]:
    """Build tooling section with concise tool list and call style guide."""
    is_en = language == "en"
    # One-line summaries for known tools (details are in the tool schema)
    if is_en:
        core_summaries = {
            "read": "read file content",
            "write": "create or overwrite a file",
            "edit": "make precise edits to a file",
            "ls": "list directory contents",
            "grep": "search file contents",
            "find": "find files by pattern",
            "bash": "run shell commands",
            "terminal": "manage background processes",
            "web_search": "web search",
            "web_fetch": "fetch URL content",
            "browser": "control the browser (screenshot key results or send to the user when help is needed)",
            "memory_search": "search memory",
            "memory_get": "read memory content",
            "env_config": "manage API keys and skill config",
            "scheduler": "manage scheduled tasks and reminders",
            "send": "send a local file to the user (local files only; put URLs directly in the reply text)",
            "vision": "analyze images (recognition, description, OCR, etc.)",
        }
    else:
        core_summaries = {
            "read": "读取文件内容",
            "write": "创建或覆盖文件",
            "edit": "精确编辑文件",
            "ls": "列出目录内容",
            "grep": "搜索文件内容",
            "find": "按模式查找文件",
            "bash": "执行shell命令",
            "terminal": "管理后台进程",
            "web_search": "网络搜索",
            "web_fetch": "获取URL内容",
            "browser": "控制浏览器（关键结果或需要协助可截图发送给用户）",
            "memory_search": "搜索记忆",
            "memory_get": "读取记忆内容",
            "env_config": "管理API密钥和技能配置",
            "scheduler": "管理定时任务和提醒",
            "send": "发送本地文件给用户（仅限本地文件，URL直接放在回复文本中）",
            "vision": "分析图片内容（识别、描述、OCR文字提取等）",
        }

    # Preferred display order
    tool_order = [
        "read", "write", "edit", "ls", "grep", "find",
        "bash", "terminal",
        "web_search", "web_fetch", "browser",
        "memory_search", "memory_get",
        "env_config", "scheduler", "send", "vision",
    ]

    # Build name -> summary mapping for available tools
    available = {}
    for tool in tools:
        name = tool.name if hasattr(tool, 'name') else str(tool)
        available[name] = core_summaries.get(name, "")

    # Generate tool lines: ordered tools first, then extras
    tool_lines = []
    for name in tool_order:
        if name in available:
            summary = available.pop(name)
            tool_lines.append(f"- {name}: {summary}" if summary else f"- {name}")
    for name in sorted(available):
        summary = available[name]
        tool_lines.append(f"- {name}: {summary}" if summary else f"- {name}")

    if is_en:
        lines = [
            "## 🔧 Tooling",
            "",
            "Available tools (names are case-sensitive, call exactly as listed):",
            "\n".join(tool_lines),
            "",
            "Tool-calling style:",
            "",
            "- For multi-step tasks, complex decisions or sensitive operations, briefly explain what you are doing and why, so the user follows key progress",
            "- Keep going until the task is done, then report the result to the user",
            "- Always redact secrets, tokens and other sensitive info in replies",
            "- Put URLs directly in the reply text; the system handles and renders them. Don't download and re-send them via the send tool",
            "",
        ]
    else:
        lines = [
            "## 🔧 工具系统",
            "",
            "可用工具（名称大小写敏感，严格按列表调用）:",
            "\n".join(tool_lines),
            "",
            "工具调用风格：",
            "",
            "- 多步骤任务、复杂决策、敏感操作时，应简要说明当前在做什么、为什么这样做，让用户了解关键进展",
            "- 持续推进直到任务完成，完成后向用户报告结果",
            "- 回复中涉及密钥、令牌等敏感信息必须脱敏",
            "- URL链接直接放在回复文本中即可，系统会自动处理和渲染。无需下载后使用send工具发送",
            "",
        ]

    return lines


def _build_skills_section(skill_manager: Any, tools: Optional[List[Any]], language: str) -> List[str]:
    """Build the skills section."""
    if not skill_manager:
        return []
    
    # Resolve the read tool name
    read_tool_name = "read"
    if tools:
        for tool in tools:
            tool_name = tool.name if hasattr(tool, 'name') else str(tool)
            if tool_name.lower() == "read":
                read_tool_name = tool_name
                break
    
    if language == "en":
        lines = [
            "## 🧩 Skills (mandatory)",
            "",
            "Before replying: scan the <description> of every skill in <available_skills> below.",
            "",
            f"- If a skill's description matches the user's need: use the `{read_tool_name}` tool to read the SKILL.md at its <location> path, then strictly follow the instructions in the file. "
            "Prefer using a skill when one matches.",
            "- If multiple skills apply, pick the best-matching one, then read and follow it.",
            "- If no skill clearly applies: do not read any SKILL.md, just use the general tools.",
            "",
            f"**Important**: skills are not tools and cannot be called directly. The only way to use a skill is to read its SKILL.md with `{read_tool_name}`, then act on the file's content. "
            "Never read multiple skills at once — only read one after selecting it.",
            "",
            "Available skills:"
        ]
    else:
        lines = [
            "## 🧩 技能系统（mandatory）",
            "",
            "在回复之前：扫描下方 <available_skills> 中每个技能的 <description>。",
            "",
            f"- 如果有技能的描述与用户需求匹配：使用 `{read_tool_name}` 工具读取其 <location> 路径的 SKILL.md 文件，然后严格遵循文件中的指令。"
            "当有匹配的技能时，应优先使用技能",
            "- 如果多个技能都适用则选择最匹配的一个，然后读取并遵循。",
            "- 如果没有技能明确适用：不要读取任何 SKILL.md，直接使用通用工具。",
            "",
            f"**重要**: 技能不是工具，不能直接调用。使用技能的唯一方式是用 `{read_tool_name}` 读取 SKILL.md 文件，然后按文件内容操作。"
            "永远不要一次性读取多个技能，只在选择后再读取。",
            "",
            "以下是可用技能："
        ]
    
    # Append the skills list (built by skill_manager)
    try:
        skills_prompt = skill_manager.build_skills_prompt()
        logger.debug(f"[PromptBuilder] Skills prompt length: {len(skills_prompt) if skills_prompt else 0}")
        if skills_prompt:
            lines.append(skills_prompt.strip())
            lines.append("")
        else:
            logger.warning("[PromptBuilder] No skills prompt generated - skills_prompt is empty")
    except Exception as e:
        logger.warning(f"Failed to build skills prompt: {e}")
        import traceback
        logger.debug(f"Skills prompt error traceback: {traceback.format_exc()}")
    
    return lines


def _build_memory_section(memory_manager: Any, tools: Optional[List[Any]], language: str) -> List[str]:
    """Build the memory section."""
    if not memory_manager:
        return []

    has_memory_tools = False
    if tools:
        tool_names = [tool.name if hasattr(tool, 'name') else str(tool) for tool in tools]
        has_memory_tools = any(name in ['memory_search', 'memory_get'] for name in tool_names)

    if not has_memory_tools:
        return []

    from datetime import datetime
    today_file = datetime.now().strftime("%Y-%m-%d") + ".md"

    if language == "en":
        lines = [
            "## 🧠 Memory",
            "",
            "### Memory Recall (mandatory)",
            "",
            "When the user asks about past events, references an earlier decision, mentions relationships, preferences or to-dos, or when you are unsure about something, **you must search memory before answering**.",
            "No need to re-search if the info is already in MEMORY.md. Full content and daily memory must be retrieved via tools.",
            "",
            "1. Location unknown → `memory_search` (keyword / semantic search)",
            "2. Location known → `memory_get` to read the exact lines",
            "3. Search returns nothing → `memory_get` to read the last two days of memory",
            "",
            "**Memory file structure**:",
            "- `MEMORY.md`: long-term memory index (already auto-loaded into context: core info, preferences, decisions, etc.)",
            f"- `memory/YYYY-MM-DD.md`: daily memory; today is `memory/{today_file}`",
            "- `knowledge/`: structured knowledge base (see the knowledge system below)",
            "",
            "### Writing memory",
            "",
            "In the following cases, **proactively** write info to memory files (no need to tell the user):",
            "",
            "- The user asks you to remember something, or uses words like \"remember\", \"from now on\", \"always\", \"never\", \"prefer\"",
            "- The user shares important personal preferences, habits or decisions",
            "- The conversation produces an important conclusion, plan or agreement",
            "- A complex task is completed and the key steps and results are worth recording",
            "",
            "**Storage rules**:",
            "- Long-term core info → `MEMORY.md`",
            f"- Today's events/progress → `memory/{today_file}`",
            "- Structured knowledge → `knowledge/` (see the knowledge system)",
            "- Append → `edit` tool with empty oldText",
            "- Modify → `edit` tool with oldText set to the text to replace",
            "- **Never write sensitive info** (API keys, tokens, etc.)",
            "",
            "**Principle**: use memory naturally, as if you simply knew it; don't bring it up unless asked.",
            "",
        ]
    else:
        lines = [
            "## 🧠 记忆系统",
            "",
            "### Memory Recall（mandatory）",
            "",
            "当用户询问过往事件、引用之前的决定、提到人物关系、偏好、待办、或你对某事不确定时，**必须先检索记忆再回答**。",
            "如果 MEMORY.md 中已有相关信息则无需重复检索。完整内容和每日记忆需要通过工具检索。",
            "",
            "1. 不确定位置 → `memory_search` 关键词/语义检索",
            "2. 已知位置 → `memory_get` 直接读取对应行",
            "3. search 无结果 → `memory_get` 读最近两天记忆",
            "",
            "**记忆文件结构**:",
            "- `MEMORY.md`: 长期记忆索引（已自动加载到上下文，核心信息、偏好、决策等）",
            f"- `memory/YYYY-MM-DD.md`: 每日记忆，今天是 `memory/{today_file}`",
            "- `knowledge/`: 结构化知识库（见下方知识系统）",
            "",
            "### 写入记忆",
            "",
            "遇到以下情况时，**主动**将信息写入记忆文件（无需告知用户）：",
            "",
            "- 用户要求记住某些信息，或使用了「记住」「以后」「总是」「不要」「偏好」等表达",
            "- 用户分享了重要的个人偏好、习惯、决策",
            "- 对话中产生了重要的结论、方案、约定",
            "- 完成了复杂任务，值得记录关键步骤和结果",
            "",
            "**存储规则**:",
            f"- 长期核心信息 → `MEMORY.md`",
            f"- 当天事件/进展 → `memory/{today_file}`",
            "- 结构化知识 → `knowledge/`（见知识系统）",
            "- 追加 → `edit` 工具，oldText 留空",
            "- 修改 → `edit` 工具，oldText 填写要替换的文本",
            "- **禁止写入敏感信息**（API密钥、令牌等）",
            "",
            "**使用原则**: 自然使用记忆，就像你本来就知道；不用刻意提起，除非用户问起。",
            "",
        ]

    return lines


def _build_knowledge_section(workspace_dir: str, language: str) -> List[str]:
    """Build knowledge wiki section. Injects knowledge/index.md when present."""
    index_path = os.path.join(workspace_dir, "knowledge", "index.md")
    if not os.path.exists(index_path):
        return []

    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            index_content = f.read().strip()
    except Exception:
        return []

    if language == "en":
        lines = [
            "## 📚 Knowledge",
            "",
            "You have a continuously growing personal knowledge base `knowledge/` — your long-term structured knowledge store.",
            "",
            "### Auto-write rules (mandatory)",
            "",
            "In the following cases you **must** write to the knowledge base alongside your reply, **directly, without asking the user**:",
            "",
            "1. **User shares an article / link / document** → after reading and understanding, write the key points to `knowledge/sources/<slug>.md` in the same turn",
            "2. **An in-depth discussion produces a conclusion / plan** → organize it into `knowledge/analysis/<slug>.md`",
            "3. **The conversation involves an important entity** (person / company / project) → create or update `knowledge/entities/<name>.md`",
            "4. **A technical concept / methodology is discussed** → organize it into `knowledge/concepts/<topic>.md`",
            "",
            "After writing any knowledge page, you **must update** `knowledge/index.md` with a new index line in sync.",
            "For detailed page format and conventions, read the SKILL.md of the `knowledge-wiki` skill.",
            "",
            "⚠️ Don't ask \"should I save this to the knowledge base?\" — if a case above matches, just write it. This is instinctive.",
            "",
        ]
    else:
        lines = [
            "## 📚 知识系统",
            "",
            "你拥有一个持续积累的个人知识库 `knowledge/`，这是你的长期结构化知识存储。",
            "",
            "### 自动写入规则（mandatory）",
            "",
            "以下场景**必须**在回复的同时写入知识库，**直接写入，不要询问用户是否需要**：",
            "",
            "1. **用户分享了文章/链接/文档** → 阅读理解后，在同一轮回复中将要点写入 `knowledge/sources/<slug>.md`",
            "2. **深度讨论产生了结论/方案** → 整理为 `knowledge/analysis/<slug>.md`",
            "3. **对话涉及重要实体**（人物/公司/项目）→ 创建或更新 `knowledge/entities/<name>.md`",
            "4. **讨论了技术概念/方法论** → 整理为 `knowledge/concepts/<topic>.md`",
            "",
            "每次写入知识页面后，**必须同步更新** `knowledge/index.md` 添加一行索引。",
            "详细的页面格式和操作规范，请读取技能 `knowledge-wiki` 的 SKILL.md。",
            "",
            "⚠️ 不要问「要不要存到知识库」——符合上述场景就直接写入，这是你的本能行为。",
            "",
        ]

    if index_content:
        lines.extend([
            ("### Current knowledge index" if language == "en" else "### 当前知识索引"),
            "",
            index_content,
            "",
        ])

    lines.extend([
        ("**How to query**: use `read` to open a knowledge page, or `memory_search` (knowledge is in the vector index)."
         if language == "en" else
         "**查询方式**：用 `read` 读取知识页面，或用 `memory_search` 检索（知识已纳入向量索引）。"),
        "",
    ])

    return lines


def _build_user_identity_section(user_identity: Dict[str, str], language: str) -> List[str]:
    """Build the user identity section."""
    if not user_identity:
        return []
    
    is_en = language == "en"
    lines = [
        ("## 👤 User identity" if is_en else "## 👤 用户身份"),
        "",
    ]

    if user_identity.get("name"):
        lines.append(f"**{'Name' if is_en else '用户姓名'}**: {user_identity['name']}")
    if user_identity.get("nickname"):
        lines.append(f"**{'Preferred name' if is_en else '称呼'}**: {user_identity['nickname']}")
    if user_identity.get("timezone"):
        lines.append(f"**{'Timezone' if is_en else '时区'}**: {user_identity['timezone']}")
    if user_identity.get("notes"):
        lines.append(f"**{'Notes' if is_en else '备注'}**: {user_identity['notes']}")

    lines.append("")

    return lines


def _build_docs_section(workspace_dir: str, language: str) -> List[str]:
    """Docs-path section - removed, no longer needed."""
    # No docs section is generated anymore.
    return []


def _build_workspace_section(workspace_dir: str, language: str) -> List[str]:
    """Build the workspace section."""
    if language == "en":
        lines = [
            "## 📂 Workspace",
            "",
            f"Your working directory is: `{workspace_dir}`",
            "",
            "**Path rules** (very important):",
            "",
            f"1. **Base directory for relative paths**: all relative paths are relative to `{workspace_dir}`",
            "   - ✅ Correct: use relative paths for files inside the workspace, e.g. `AGENT.md`",
            f"   - ❌ Wrong: using a relative path for files in other directories (if not inside `{workspace_dir}`)",
            "",
            "2. **Accessing other directories**: to reach directories outside the workspace (project code, system files), **you must use absolute paths**",
            "   - ✅ Correct: e.g. `~/chatgpt-on-wechat`, `/usr/local/`",
            "   - ❌ Wrong: assuming a relative path points to another directory",
            "",
            "3. **Path resolution examples**:",
            f"   - relative `memory/` → actual `{workspace_dir}/memory/`",
            "   - absolute `~/chatgpt-on-wechat/docs/` → actual `~/chatgpt-on-wechat/docs/`",
            "",
            "4. **When unsure**: run `bash pwd` to confirm the current directory, or `ls .` to see where you are",
            "",
            "**Important - files already auto-loaded**:",
            "",
            "The following files are **already auto-loaded** into the system prompt at session start, so you **don't need to read them again with the read tool**:",
            "",
            "- ✅ `AGENT.md`: loaded - your persona and soul; follow it strictly. When your name, personality or style changes, proactively `edit` this file",
            "- ✅ `USER.md`: loaded - the user's identity info. When the user changes how they're addressed, their name, etc., `edit` this file",
            "- ✅ `RULE.md`: loaded - workspace guide and rules; follow them strictly",
            "- ✅ `MEMORY.md`: loaded - long-term memory index",
            "",
            "**💬 Communication norms**:",
            "",
            "- No need to expose file names for memory operations; use natural language. Say \"I'll remember that\" rather than \"updated MEMORY.md\"",
            "- Tell the user about key decisions and steps during a task, so they know what you're doing and why",
            "- Be genuinely helpful rather than performatively polite; solve the problem as much as you can",
            "- Keep replies well-structured and focused. Use **bold**, lists and sections to make info clear at a glance",
            "- Use emoji to make expression lively 🎯, but don't overdo it",
            "",
        ]
    else:
        lines = [
            "## 📂 工作空间",
            "",
            f"你的工作目录是: `{workspace_dir}`",
            "",
            "**路径使用规则** (非常重要):",
            "",
            f"1. **相对路径的基准目录**: 所有相对路径都是相对于 `{workspace_dir}` 而言的",
            f"   - ✅ 正确: 访问工作空间内的文件用相对路径，如 `AGENT.md`",
            f"   - ❌ 错误: 用相对路径访问其他目录的文件 (如果它不在 `{workspace_dir}` 内)",
            "",
            "2. **访问其他目录**: 如果要访问工作空间之外的目录（如项目代码、系统文件），**必须使用绝对路径**",
            f"   - ✅ 正确: 例如 `~/chatgpt-on-wechat`、`/usr/local/`",
            f"   - ❌ 错误: 假设相对路径会指向其他目录",
            "",
            "3. **路径解析示例**:",
            f"   - 相对路径 `memory/` → 实际路径 `{workspace_dir}/memory/`",
            f"   - 绝对路径 `~/chatgpt-on-wechat/docs/` → 实际路径 `~/chatgpt-on-wechat/docs/`",
            "",
            "4. **不确定时**: 先用 `bash pwd` 确认当前目录，或用 `ls .` 查看当前位置",
            "",
            "**重要说明 - 文件已自动加载**:",
            "",
            "以下文件在会话启动时**已经自动加载**到系统提示词中，你**无需再用 read 工具读取**：",
            "",
            "- ✅ `AGENT.md`: 已加载 - 你的人格和灵魂设定，请严格遵循。当你的名字、性格或交流风格发生变化时，主动用 `edit` 更新此文件",
            "- ✅ `USER.md`: 已加载 - 用户的身份信息。当用户修改称呼、姓名等身份信息时，用 `edit` 更新此文件",
            "- ✅ `RULE.md`: 已加载 - 工作空间使用指南和规则，请严格遵循",
            "- ✅ `MEMORY.md`: 已加载 - 长期记忆索引",
            "",
            "**💬 交流规范**:",
            "",
            "- 记忆相关操作无需暴露文件名，用自然语言表达即可。例如说「我已记住」而非「已更新 MEMORY.md」",
            "- 任务执行过程中的关键决策和步骤应该告知用户，让用户了解你在做什么、为什么这么做",
            "- 做真正有帮助的助手，而不是表演式的客套，尽可能帮忙解决问题",
            "- 回复应结构清晰、重点突出。善用 **加粗**、列表、分段等格式让信息一目了然",
            "- 适当使用 emoji 让表达更生动自然 🎯，但不要过度堆砌",
            "",
        ]

    # Cloud deployment: inject websites directory info and access URL
    cloud_website_lines = _build_cloud_website_section(workspace_dir)
    if cloud_website_lines:
        lines.extend(cloud_website_lines)
    
    return lines


def _build_cloud_website_section(workspace_dir: str) -> List[str]:
    """Build cloud website access prompt when cloud deployment is configured."""
    try:
        from common.cloud_client import build_website_prompt
        return build_website_prompt(workspace_dir)
    except Exception:
        return []


def _build_context_files_section(context_files: List[ContextFile], language: str) -> List[str]:
    """Build the project context files section."""
    if not context_files:
        return []
    
    # Check whether AGENT.md is present
    has_agent = any(
        f.path.lower().endswith('agent.md') or 'agent.md' in f.path.lower()
        for f in context_files
    )
    
    is_en = language == "en"
    if is_en:
        lines = [
            "# 📋 Project context",
            "",
            "The following project context files have been loaded:",
            "",
        ]
    else:
        lines = [
            "# 📋 项目上下文",
            "",
            "以下项目上下文文件已被加载：",
            "",
        ]

    if has_agent:
        if is_en:
            lines.append("**`AGENT.md` is your soul file** 🪞: strictly follow the persona, tone and settings it defines. Be your real self, avoid stiff, template-like replies.")
            lines.append("When the user reveals new expectations about your personality, style, responsibilities or capability boundaries, proactively `edit` AGENT.md to reflect that evolution.")
        else:
            lines.append("**`AGENT.md` 是你的灵魂文件** 🪞：严格遵循其中定义的人格、语气和设定，做真实的自己，避免僵硬、模板化的回复。")
            lines.append("当用户通过对话透露了对你性格、风格、职责、能力边界的新期望，你应该主动用 `edit` 更新 AGENT.md 以反映这些演变。")
        lines.append("")
    
    # Append the content of each file
    for file in context_files:
        lines.append(f"## {file.path}")
        lines.append("")
        lines.append(file.content)
        lines.append("")
    
    return lines


def _build_runtime_section(runtime_info: Dict[str, Any], language: str) -> List[str]:
    """Build the runtime info section - supports dynamic time."""
    if not runtime_info:
        return []
    
    is_en = language == "en"
    time_label = "Current time" if is_en else "当前时间"
    lines = [
        ("## ⚙️ Runtime info" if is_en else "## ⚙️ 运行时信息"),
        "",
    ]

    # Add current time if available
    # Support dynamic time via callable function
    if callable(runtime_info.get("_get_current_time")):
        try:
            time_info = runtime_info["_get_current_time"]()
            time_line = f"{time_label}: {time_info['time']} {time_info['weekday']} ({time_info['timezone']})"
            lines.append(time_line)
            lines.append("")
        except Exception as e:
            logger.warning(f"[PromptBuilder] Failed to get dynamic time: {e}")
    elif runtime_info.get("current_time"):
        # Fallback to static time for backward compatibility
        time_str = runtime_info["current_time"]
        weekday = runtime_info.get("weekday", "")
        timezone = runtime_info.get("timezone", "")

        time_line = f"{time_label}: {time_str}"
        if weekday:
            time_line += f" {weekday}"
        if timezone:
            time_line += f" ({timezone})"

        lines.append(time_line)
        lines.append("")

    # Add other runtime info
    model_label = "model" if is_en else "模型"
    workspace_label = "workspace" if is_en else "工作空间"
    channel_label = "channel" if is_en else "渠道"
    runtime_parts = []
    # Support dynamic model via callable, fallback to static value
    if callable(runtime_info.get("_get_model")):
        try:
            runtime_parts.append(f"{model_label}={runtime_info['_get_model']()}")
        except Exception:
            if runtime_info.get("model"):
                runtime_parts.append(f"{model_label}={runtime_info['model']}")
    elif runtime_info.get("model"):
        runtime_parts.append(f"{model_label}={runtime_info['model']}")
    if runtime_info.get("workspace"):
        runtime_parts.append(f"{workspace_label}={runtime_info['workspace']}")
    # Only add channel if it's not the default "web"
    if runtime_info.get("channel") and runtime_info.get("channel") != "web":
        runtime_parts.append(f"{channel_label}={runtime_info['channel']}")

    if runtime_parts:
        lines.append(("Runtime: " if is_en else "运行时: ") + " | ".join(runtime_parts))
        lines.append("")

    return lines
