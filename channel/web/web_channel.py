"""The console's URL table.

Every route the web console answers on, and the web.py application built
from it. The handlers themselves live in api/, one module per view, and the
plumbing they share lives in core/ -- see channel/web/README.md.

This module imports every handler because build_app() resolves the names in
URLS against this module's globals; see build_app at the bottom.
"""

import web

from channel.web.api.agents import (  # noqa: F401
    AgentAvatarHandler, AgentCoreFileHandler, AgentsHandler,
)
from channel.web.api.auth import (  # noqa: F401
    AuthCheckHandler, AuthLoginHandler, AuthLogoutHandler,
    McpOAuthCallbackHandler,
)
from channel.web.api.channels import (  # noqa: F401
    ChannelsHandler, FeishuRegisterHandler, WeixinQrHandler,
)
from channel.web.api.chat import (  # noqa: F401
    CancelHandler, MessageHandler, PollHandler, StreamHandler,
)
from channel.web.api.config import ConfigHandler  # noqa: F401
from channel.web.api.files import (  # noqa: F401
    FileServeHandler, PreviewHandler, UploadHandler, UploadsHandler,
    VoiceAsrHandler, VoiceTtsHandler,
)
from channel.web.api.knowledge import (  # noqa: F401
    KnowledgeActionHandler, KnowledgeGraphHandler, KnowledgeImportHandler,
    KnowledgeListHandler, KnowledgeReadHandler,
)
from channel.web.api.logs import LogsDownloadHandler, LogsHandler  # noqa: F401
from channel.web.api.memory import (  # noqa: F401
    MemoryContentHandler, MemoryHandler,
)
from channel.web.api.models import ModelsHandler  # noqa: F401
from channel.web.api.openai_compat import (  # noqa: F401
    OpenAIChatCompletionsHandler,
)
from channel.web.api.pages import (  # noqa: F401
    AssetsHandler, ChatHandler, HealthHandler, RootHandler,
)
from channel.web.api.scheduler import (  # noqa: F401
    SchedulerCreateHandler, SchedulerDeleteHandler, SchedulerHandler,
    SchedulerInstancesHandler, SchedulerRecipientsHandler,
    SchedulerRunDeleteHandler, SchedulerRunDetailHandler, SchedulerRunHandler,
    SchedulerRunsHandler, SchedulerToggleHandler, SchedulerUpdateHandler,
)
from channel.web.api.sessions import (  # noqa: F401
    HistoryHandler, MessageDeleteHandler, PromptOptimizeHandler,
    SessionClearContextHandler, SessionCompactContextHandler,
    SessionContextUsageHandler, SessionDetailHandler, SessionSettingsHandler,
    SessionTitleHandler, SessionsHandler, UserMessagesHandler,
)
from channel.web.api.skills import (  # noqa: F401
    SkillContentHandler, SkillsHandler, ToolsHandler,
)
from channel.web.api.team import TeamStateHandler  # noqa: F401
from channel.web.api.teams_store import (  # noqa: F401
    TeamGroupDetailHandler, TeamsStoreHandler,
)
from channel.web.api.update import (  # noqa: F401
    UpdateCheckHandler, UpdateStartHandler, UpdateStatusHandler, VersionHandler,
)
from channel.web.api.workspace import (  # noqa: F401
    ProjectBrowseHandler, ProjectCreateHandler, ProjectManageHandler,
    ProjectOrderHandler, ProjectSelectHandler, ProjectsHandler,
    WorkspaceMetaHandler, WorkspaceReadHandler, WorkspaceResolveHandler,
    WorkspaceSearchHandler, WorkspaceTreeHandler, WorkspaceWriteHandler,
)
# Re-exported, not used here. app.py waits on SERVING and channel_factory
# resolves "channel.web.web_channel.WebChannel" by name, so both have to stay
# reachable through this module; the tests reach for the rest.
from channel.web.core._common import (  # noqa: F401
    SERVING, SSEStreamState, WebMessage,
)
from channel.web.core.channel import WebChannel  # noqa: F401


URLS = (
    '/', 'ChatHandler',
    '/chat', 'RootHandler',
    '/api/health', 'HealthHandler',
    '/auth/login', 'AuthLoginHandler',
    '/auth/check', 'AuthCheckHandler',
    '/auth/logout', 'AuthLogoutHandler',
    '/message', 'MessageHandler',
    '/upload', 'UploadHandler',
    '/uploads/(.*)', 'UploadsHandler',
    '/api/file', 'FileServeHandler',
    '/preview/(.+)', 'PreviewHandler',
    '/api/workspace/tree', 'WorkspaceTreeHandler',
    '/api/workspace/search', 'WorkspaceSearchHandler',
    '/api/workspace/resolve', 'WorkspaceResolveHandler',
    '/api/workspace/meta', 'WorkspaceMetaHandler',
    '/api/workspace/read', 'WorkspaceReadHandler',
    '/api/workspace/write', 'WorkspaceWriteHandler',
    '/api/projects', 'ProjectsHandler',
    '/api/projects/select', 'ProjectSelectHandler',
    '/api/projects/create', 'ProjectCreateHandler',
    '/api/projects/browse', 'ProjectBrowseHandler',
    '/api/projects/order', 'ProjectOrderHandler',
    '/api/projects/manage', 'ProjectManageHandler',
    '/api/voice/asr', 'VoiceAsrHandler',
    '/api/voice/tts', 'VoiceTtsHandler',
    '/poll', 'PollHandler',
    '/stream', 'StreamHandler',
    '/cancel', 'CancelHandler',
    '/v1/chat/completions', 'OpenAIChatCompletionsHandler',
    '/config', 'ConfigHandler',
    '/api/models', 'ModelsHandler',
    '/api/channels', 'ChannelsHandler',
    '/api/weixin/qrlogin', 'WeixinQrHandler',
    '/api/feishu/register', 'FeishuRegisterHandler',
    '/api/tools', 'ToolsHandler',
    '/api/skills', 'SkillsHandler',
    '/api/skills/content', 'SkillContentHandler',
    '/api/memory', 'MemoryHandler',
    '/api/memory/content', 'MemoryContentHandler',
    '/api/knowledge/list', 'KnowledgeListHandler',
    '/api/knowledge/read', 'KnowledgeReadHandler',
    '/api/knowledge/graph', 'KnowledgeGraphHandler',
    '/api/knowledge/action', 'KnowledgeActionHandler',
    '/api/knowledge/import', 'KnowledgeImportHandler',
    '/api/scheduler', 'SchedulerHandler',
    '/api/scheduler/runs/detail', 'SchedulerRunDetailHandler',
    '/api/scheduler/runs/delete', 'SchedulerRunDeleteHandler',
    '/api/scheduler/runs', 'SchedulerRunsHandler',
    '/api/scheduler/run', 'SchedulerRunHandler',
    '/api/scheduler/toggle', 'SchedulerToggleHandler',
    '/api/scheduler/update', 'SchedulerUpdateHandler',
    '/api/scheduler/delete', 'SchedulerDeleteHandler',
    '/api/scheduler/create', 'SchedulerCreateHandler',
    '/api/scheduler/recipients', 'SchedulerRecipientsHandler',
    '/api/scheduler/instances', 'SchedulerInstancesHandler',
    '/api/agents', 'AgentsHandler',
    '/api/agents/([^/]+)/avatar', 'AgentAvatarHandler',
    '/api/agents/([^/]+)/files/([^/]+)', 'AgentCoreFileHandler',
    '/api/sessions', 'SessionsHandler',
    '/api/sessions/(.*)/generate_title', 'SessionTitleHandler',
    '/api/prompt/optimize', 'PromptOptimizeHandler',
    '/api/sessions/(.*)/clear_context', 'SessionClearContextHandler',
    '/api/sessions/(.*)/context_usage', 'SessionContextUsageHandler',
    '/api/sessions/(.*)/compact_context', 'SessionCompactContextHandler',
    '/api/sessions/(.*)/settings', 'SessionSettingsHandler',
    '/api/sessions/(.*)', 'SessionDetailHandler',
    '/api/history/user_messages', 'UserMessagesHandler',
    '/api/team-groups', 'TeamsStoreHandler',
    '/api/team-groups/(.*)', 'TeamGroupDetailHandler',
    '/api/teams/(.*)', 'TeamStateHandler',
    '/api/history', 'HistoryHandler',
    '/api/messages/delete', 'MessageDeleteHandler',
    '/api/logs/download', 'LogsDownloadHandler',
    '/api/logs', 'LogsHandler',
    '/api/version', 'VersionHandler',
    '/api/update/check', 'UpdateCheckHandler',
    '/api/update/start', 'UpdateStartHandler',
    '/api/update/status', 'UpdateStatusHandler',
    '/mcp/oauth/callback', 'McpOAuthCallbackHandler',
    '/assets/(.*)', 'AssetsHandler',
    # Views inside the single-page console. Each serves the same shell;
    # the frontend router reads the path and opens the view it names,
    # so a reload or a shared link lands where it says. Last in the
    # table on purpose: web.py takes the first match, so no view name
    # can ever shadow an API route above -- which is also why the
    # settings view is /settings and not /config, a path the config
    # API already owns.
    '/(?:agents|settings|skills|memory|knowledge|channels|scheduler|logs)'
    '(?:/[a-z]+)?/?', 'ChatHandler',
)


def build_app():
    """The web.py application, built against this module's namespace.

    web.py resolves the handler names in URLS by looking them up in a
    namespace dict, so the application has to be built where those names are
    in scope. That is here -- this module imports every handler -- and it is
    why WebChannel, which only runs the server, asks for the app instead of
    assembling one.
    """
    return web.application(URLS, globals(), autoreload=False)
