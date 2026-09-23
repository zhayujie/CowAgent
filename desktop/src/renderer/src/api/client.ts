import type {
  ConfigData,
  ChannelInfo,
  ChannelAction,
  SkillInfo,
  SkillContent,
  ToolInfo,
  MemoryItem,
  MemoryCategory,
  MemoryPage,
  MemoryDoc,
  SchedulerTask,
  SchedulerRun,
  SchedulerRunDetail,
  TaskSchedule,
  TaskAction,
  SchedulerInstance,
  TaskRecipient,
  Attachment,
  SessionsPage,
  SessionSettingsState,
  HistoryPage,
  UserMessageIndex,
  ContextUsage,
  ModelsData,
  ModelsAction,
  KnowledgeList,
  KnowledgeGraph,
  KnowledgeAction,
  KnowledgeImportPayload,
  WorkspaceEntry,
  WorkspaceReadResult,
  WorkspaceTree,
  WorkspaceWriteResult,
  ProjectState,
  ChannelsResponse,
  RosterSnapshot,
  TeamGroup,
} from '../types'
import { getLang, t } from '../i18n'

export interface ApiResult {
  status: string
  message?: string
}

export interface UploadResult {
  status: string
  file_path: string
  file_name: string
  file_type: string
  preview_url: string
  message?: string
}

const AUTH_TOKEN_KEY = 'cow_auth_token'

class ApiClient {
  private baseUrl = 'http://127.0.0.1:9876'
  // Bearer token for web_password-protected backends. The desktop renderer
  // runs from a file:// origin, where cross-origin cookies to http://127.0.0.1
  // aren't sent reliably, so we authenticate via an Authorization header
  // instead. Persisted in localStorage so it survives reloads.
  private authToken: string | null =
    typeof localStorage !== 'undefined' ? localStorage.getItem(AUTH_TOKEN_KEY) : null

  setBaseUrl(url: string) {
    this.baseUrl = url
  }

  getBaseUrl() {
    return this.baseUrl
  }

  setAuthToken(token: string | null) {
    this.authToken = token
    try {
      if (token) localStorage.setItem(AUTH_TOKEN_KEY, token)
      else localStorage.removeItem(AUTH_TOKEN_KEY)
    } catch {
      // localStorage may be unavailable; in-memory token still works this session
    }
  }

  // The Agent whose workspace scoped endpoints (skills/knowledge/scheduler,
  // and new chat sessions) should target. Empty means "let the backend use its
  // default Agent" — exactly the legacy single-Agent behavior, so nothing is
  // sent and the old requests are byte-for-byte unchanged. Set by the agent
  // store only when the install is in multi-Agent mode.
  private activeAgentId = ''

  setActiveAgentId(id: string) {
    this.activeAgentId = (id || '').trim()
  }

  getActiveAgentId(): string {
    return this.activeAgentId
  }

  // Append agent_id to a query string. An explicit `override` wins (used by the
  // Knowledge/Memory pages, which scope to a chosen Agent independent of the
  // chat's active one); otherwise the active Agent is used. No-op in
  // single-Agent mode with no override, so legacy URLs are untouched.
  private scoped(path: string, override?: string): string {
    const id = (override ?? this.activeAgentId) || ''
    if (!id) return path
    const sep = path.includes('?') ? '&' : '?'
    return `${path}${sep}agent_id=${encodeURIComponent(id)}`
  }

  // Add agent_id to a JSON body when an active Agent is set, without clobbering
  // an explicit agent_id a caller already put there. No-op in single-Agent mode.
  private withAgent<T extends Record<string, unknown>>(body: T): T {
    if (!this.activeAgentId || 'agent_id' in body) return body
    return { ...body, agent_id: this.activeAgentId }
  }

  // Carry the active Agent through every request, the way the web console's
  // fetch wrapper does: sessions, history, projects, skills, knowledge and
  // uploads are all stored per Agent workspace, so a request that forgets the
  // id silently lands on the default Agent's data. Query string always; JSON
  // bodies too (handlers read either). An explicit agent_id — even an empty
  // one — always wins, so callers can still scope to another Agent or opt out
  // (e.g. the aggregated scheduler list). No-op in single-Agent mode, keeping
  // legacy requests byte-for-byte unchanged.
  private carryAgent(path: string, options?: RequestInit): { path: string; options?: RequestInit } {
    const id = this.activeAgentId
    if (!id) return { path, options }
    let url = path
    if (!/[?&]agent_id=/.test(url)) {
      url += `${url.includes('?') ? '&' : '?'}agent_id=${encodeURIComponent(id)}`
    }
    let opts = options
    if (options && typeof options.body === 'string') {
      try {
        const body = JSON.parse(options.body)
        if (body && typeof body === 'object' && !Array.isArray(body) && !('agent_id' in body)) {
          opts = { ...options, body: JSON.stringify({ ...body, agent_id: id }) }
        }
      } catch {
        /* not JSON; leave the body alone */
      }
    }
    return { path: url, options: opts }
  }

  private async request<T>(path: string, rawOptions?: RequestInit): Promise<T> {
    const { path: url, options } = this.carryAgent(path, rawOptions)
    const res = await fetch(`${this.baseUrl}${url}`, {
      ...options,
      // Cookies still work for browser access; the desktop app relies on the
      // Authorization header below.
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(this.authToken ? { Authorization: `Bearer ${this.authToken}` } : {}),
        ...options?.headers,
      },
    })
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`)
    }
    return res.json()
  }

  /** POST multipart form data.
   *
   * `request()` can't be reused: it forces a JSON content type, while FormData
   * must set its own multipart boundary. The auth header still has to be wired
   * up by hand — the desktop app renders from file://, so it authenticates via
   * the header, never the cookie.
   */
  private async postFormData<T>(path: string, formData: FormData): Promise<T> {
    // Multipart bodies must NOT get a copy of agent_id when the query already
    // carries it: web.py merges query + form fields and a duplicate collapses
    // into a list, which breaks handlers expecting a string. So scope via the
    // query only, and only when the form doesn't already name an Agent.
    const scopedPath = formData.has('agent_id') ? path : this.carryAgent(path).path
    const url = `${this.baseUrl}${scopedPath}`
    // A plain `fetch` throws a bare `TypeError: Failed to fetch` for any
    // network-level failure. In Electron this is almost never "the backend is
    // down" — the backend is a local child process that either answers with a
    // JSON error or a real HTTP status. It's a transient connection reset:
    // the WSGI thread pool is momentarily busy (an SSE stream holding threads,
    // a concurrent request), or the socket got dropped mid-body. It's
    // intermittent and unrelated to the file's type, which is why some uploads
    // go through and others don't. So retry a few times with backoff before
    // giving up, and never surface the internal "local service / backend"
    // wording to the user — just tell them the upload was interrupted.
    const maxAttempts = 4
    let lastErr: unknown
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      if (attempt > 0) await new Promise((r) => setTimeout(r, 400 * attempt))
      try {
        const res = await fetch(url, {
          method: 'POST',
          body: formData,
          credentials: 'include',
          headers: this.authToken ? { Authorization: `Bearer ${this.authToken}` } : undefined,
        })
        if (!res.ok) {
          // The backend returns JSON errors even on failure; surface its message
          // when present so the user sees the real reason (e.g. file too large).
          let detail = res.statusText
          try {
            const body = await res.clone().json()
            if (body?.message) detail = body.message
          } catch {
            /* non-JSON error body */
          }
          throw new Error(`HTTP ${res.status}: ${detail}`)
        }
        return res.json()
      } catch (e) {
        lastErr = e
        // Only retry the network-level failure; a real HTTP error is final.
        const isNetwork = e instanceof TypeError
        if (!isNetwork) throw e
      }
    }
    // Keep the technical detail (the target URL and raw error) in the console
    // for bug reports, but hand the user a plain, non-alarming message.
    console.error(`[api] upload network failure to ${url}:`, lastErr)
    throw new Error(t('upload_network_error'))
  }

  // ---------------------------------------------------------
  // Chat / messages
  // ---------------------------------------------------------

  async sendMessage(
    sessionId: string,
    message: string,
    opts?: {
      stream?: boolean
      attachments?: Attachment[]
      isVoice?: boolean
      lang?: string
      /** The conversation's owner Agent; defaults to the active one. */
      agentId?: string
      /** A teammate addressed for this turn (group chat); the owner still owns
       *  the conversation, this only changes who answers. */
      speakerAgentId?: string
    }
  ): Promise<{ status: string; request_id: string; stream: boolean; inline_reply?: string; speaker?: string }> {
    // Route to a specific Agent when asked, else the active one. Empty (legacy
    // single-Agent) omits agent_id entirely, so the backend uses its default.
    const agentId = opts?.agentId || this.activeAgentId
    const body: Record<string, unknown> = {
      session_id: sessionId,
      message,
      stream: opts?.stream ?? true,
      attachments: opts?.attachments,
      is_voice: opts?.isVoice ?? false,
      lang: opts?.lang,
    }
    if (agentId) body.agent_id = agentId
    if (opts?.speakerAgentId) body.speaker_agent_id = opts.speakerAgentId
    return this.request('/message', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async poll(sessionId: string): Promise<{
    status: string
    has_content: boolean
    content?: string
    request_id?: string
    timestamp?: number
  }> {
    return this.request('/poll', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    })
  }

  async cancel(opts: { requestId?: string; sessionId?: string; lang?: string }): Promise<{ status: string; cancelled: number }> {
    return this.request('/cancel', {
      method: 'POST',
      body: JSON.stringify({ request_id: opts.requestId, session_id: opts.sessionId, lang: opts.lang }),
    })
  }

  // EventSource can't set an Authorization header, so append the auth token as
  // a query param for SSE endpoints (the backend accepts it there).
  private withToken(url: string): string {
    if (!this.authToken) return url
    const sep = url.includes('?') ? '&' : '?'
    return `${url}${sep}token=${encodeURIComponent(this.authToken)}`
  }

  createSSEStream(requestId: string): EventSource {
    return new EventSource(this.withToken(`${this.baseUrl}/stream?request_id=${requestId}`))
  }

  async deleteMessage(opts: {
    sessionId: string
    userSeq: number
    deleteUser?: boolean
    cascade?: boolean
    /** Owner of the session; defaults to the active Agent. */
    agentId?: string
  }): Promise<{ status: string; deleted: number }> {
    const body: Record<string, unknown> = {
      session_id: opts.sessionId,
      user_seq: opts.userSeq,
      delete_user: opts.deleteUser ?? true,
      cascade: opts.cascade ?? false,
    }
    if (opts.agentId) body.agent_id = opts.agentId
    return this.request('/api/messages/delete', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  // ---------------------------------------------------------
  // Upload / files
  // ---------------------------------------------------------

  // Whether the backend runs on this machine. Only then does a local file path
  // mean anything to it; a remote backend must receive the bytes.
  private isLoopbackBackend(): boolean {
    try {
      const host = new URL(this.baseUrl).hostname
      return host === '127.0.0.1' || host === 'localhost' || host === '[::1]' || host === '::1'
    } catch {
      return false
    }
  }

  private desktopTokenPromise: Promise<string> | null = null

  private getDesktopToken(): Promise<string> {
    if (!this.desktopTokenPromise) {
      const api = typeof window !== 'undefined' ? window.electronAPI : undefined
      this.desktopTokenPromise = api?.getDesktopToken
        ? api.getDesktopToken().catch(() => '')
        : Promise.resolve('')
    }
    return this.desktopTokenPromise
  }

  /**
   * Hand the local backend the file's path and let it copy the file itself.
   *
   * Resolves to null when this route doesn't apply (no path, remote backend,
   * not running under the desktop shell) or the backend declines, so the
   * caller falls back to a regular multipart upload. Never throws.
   */
  private async importLocalFile(
    file: File,
    sessionId?: string
  ): Promise<UploadResult | null> {
    const api = typeof window !== 'undefined' ? window.electronAPI : undefined
    if (!api?.getPathForFile || !this.isLoopbackBackend()) return null
    const localPath = api.getPathForFile(file)
    if (!localPath) return null
    const token = await this.getDesktopToken()
    if (!token) return null
    try {
      const body: Record<string, unknown> = { local_path: localPath }
      if (sessionId) body.session_id = sessionId
      const res = await this.request<UploadResult>('/upload', {
        method: 'POST',
        body: JSON.stringify(body),
        headers: { 'X-Cow-Desktop-Token': token },
      })
      if (res?.status === 'success') return res
      console.warn('[api] import by path declined, falling back to upload:', res?.message)
      return null
    } catch (e) {
      console.warn('[api] import by path failed, falling back to upload:', e)
      return null
    }
  }

  async uploadFile(file: File, sessionId?: string): Promise<UploadResult> {
    // Same machine, same disk: skip the HTTP body entirely when we can. The
    // multipart route below stays as the fallback for pasted images (no path),
    // remote backends and plain browsers.
    const imported = await this.importLocalFile(file, sessionId)
    if (imported) return imported

    const formData = new FormData()
    // Read the file into memory (a Blob) instead of appending the File directly.
    // In Electron, `fetch` streaming a File straight from disk intermittently
    // rejects with a bare "Failed to fetch" (net::ERR while reading the backing
    // file — moved/locked path, sandbox, special chars in the name), even for
    // small files. Materializing the bytes first sidesteps that disk-streaming
    // path; the original name is preserved so the backend keeps the extension.
    try {
      const buf = await file.arrayBuffer()
      formData.append('file', new Blob([buf], { type: file.type }), file.name)
    } catch {
      // Reading failed (rare): fall back to the raw File so behavior degrades
      // gracefully rather than blocking the upload entirely.
      formData.append('file', file)
    }
    if (sessionId) formData.append('session_id', sessionId)
    return this.postFormData('/upload', formData)
  }

  getFileUrl(previewUrl: string): string {
    if (/^https?:\/\//.test(previewUrl)) return previewUrl
    // Served via <img src>, which can't set headers — carry the token in the
    // query so protected file endpoints load under web_password.
    return this.withToken(`${this.baseUrl}${previewUrl}`)
  }

  getServeFileUrl(absPath: string): string {
    return this.withToken(`${this.baseUrl}/api/file?path=${encodeURIComponent(absPath)}`)
  }

  // ---------------------------------------------------------
  // Workspace browsing / preview
  // ---------------------------------------------------------

  // Workspace endpoints accept an optional session so they resolve against the
  // session's project dir (when one is open) instead of always ~/cow.
  private sessionQuery(session?: string): string {
    return session ? `&session=${encodeURIComponent(session)}` : ''
  }

  async workspaceTree(path = '', session?: string): Promise<WorkspaceTree & ApiResult> {
    return this.request(`/api/workspace/tree?path=${encodeURIComponent(path)}${this.sessionQuery(session)}`)
  }

  async workspaceSearch(query: string, limit = 30, session?: string): Promise<{ results: WorkspaceEntry[] } & ApiResult> {
    return this.request(`/api/workspace/search?q=${encodeURIComponent(query)}&limit=${limit}${this.sessionQuery(session)}`)
  }

  async workspaceResolve(path: string, session?: string): Promise<{ file: WorkspaceEntry } & ApiResult> {
    return this.request(`/api/workspace/resolve?path=${encodeURIComponent(path)}${this.sessionQuery(session)}`)
  }

  /**
   * Text content of one workspace file, for the preview panel's editor.
   *
   * Unlike the preview URL used for rendering, this reports the `mtime` to pass
   * back on save and whether the file is editable at all.
   */
  async workspaceRead(path: string, session?: string): Promise<WorkspaceReadResult & ApiResult> {
    return this.request(`/api/workspace/read?path=${encodeURIComponent(path)}${this.sessionQuery(session)}`)
  }

  /**
   * Save edited text back to a workspace file.
   *
   * The backend answers 200 even when it refuses, so the caller must check
   * `status`: `code === 'conflict'` means the file changed since
   * `expectedMtime` and the user has to choose between reloading and
   * overwriting. Pass `expectedMtime: null` to force the overwrite.
   */
  async workspaceWrite(args: {
    path: string
    content: string
    session?: string
    expectedMtime?: number | null
  }): Promise<WorkspaceWriteResult & ApiResult> {
    return this.request('/api/workspace/write', {
      method: 'POST',
      body: JSON.stringify({
        path: args.path,
        content: args.content,
        session: args.session || '',
        expected_mtime: args.expectedMtime ?? null,
      }),
    })
  }

  // ---------------------------------------------------------
  // Project workspace (per-session working directory)
  // ---------------------------------------------------------

  async getProjects(session: string): Promise<ProjectState & ApiResult> {
    return this.request(`/api/projects?session=${encodeURIComponent(session)}`)
  }

  /** Bind the session to a project dir, or clear it (projectDir=null → ~/cow). */
  async selectProject(session: string, projectDir: string | null): Promise<ProjectState & ApiResult> {
    return this.request('/api/projects/select', {
      method: 'POST',
      body: JSON.stringify({ session, project_dir: projectDir }),
    })
  }

  /** Create a new project folder under the projects root and select it. */
  async createProject(session: string, name: string): Promise<ProjectState & ApiResult & { path?: string }> {
    return this.request('/api/projects/create', {
      method: 'POST',
      body: JSON.stringify({ session, name }),
    })
  }

  /** Persist the user-defined order of project spaces in the sidebar. */
  async setProjectsOrder(order: string[]): Promise<ApiResult> {
    return this.request('/api/projects/order', {
      method: 'POST',
      body: JSON.stringify({ order }),
    })
  }

  /** Rename a project's display label (record only; files on disk untouched). */
  async renameProject(path: string, name: string): Promise<ApiResult & { name?: string }> {
    return this.request('/api/projects/manage', {
      method: 'PUT',
      body: JSON.stringify({ path, name }),
    })
  }

  /** Forget a project record and unbind its sessions (files on disk kept). */
  async deleteProject(path: string): Promise<ApiResult & { unbound?: number }> {
    return this.request('/api/projects/manage', {
      method: 'DELETE',
      body: JSON.stringify({ path }),
    })
  }

  /** Absolute URL for a `/preview/...` path. The signed token in the path is
   *  what authorizes it, so no auth token is appended. */
  getPreviewUrl(previewPath: string): string {
    if (/^https?:\/\//.test(previewPath)) return previewPath
    return `${this.baseUrl}${previewPath}`
  }

  // ---------------------------------------------------------
  // Sessions
  // ---------------------------------------------------------

  // Conversations live in their owner Agent's store. Every session call below
  // takes the owner (`agentId`) explicitly so the list can act on any row, not
  // just the active Agent's; when omitted, the active Agent (the owner of the
  // open conversation) is carried automatically. Single-Agent installs pass
  // nothing and get the legacy requests.

  /** All Agents' web sessions merged into one recency-ordered list. A
   *  single-Agent backend returns exactly its own list (with an `agent` badge);
   *  a legacy backend ignores the unknown `scope` parameter. */
  async getSessions(page = 1, pageSize = 50): Promise<SessionsPage> {
    return this.request<{ status: string } & SessionsPage>(
      `/api/sessions?page=${page}&page_size=${pageSize}&scope=all`
    )
  }

  async deleteSession(sessionId: string, agentId?: string): Promise<ApiResult> {
    return this.request(this.scoped(`/api/sessions/${encodeURIComponent(sessionId)}`, agentId), {
      method: 'DELETE',
    })
  }

  async renameSession(sessionId: string, title: string, agentId?: string): Promise<ApiResult> {
    return this.request(this.scoped(`/api/sessions/${encodeURIComponent(sessionId)}`, agentId), {
      method: 'PUT',
      body: JSON.stringify(agentId ? { title, agent_id: agentId } : { title }),
    })
  }

  /** Pin or unpin a session; pinned sessions sort to the top of their group. */
  async setSessionPinned(sessionId: string, pinned: boolean, agentId?: string): Promise<ApiResult> {
    return this.request(this.scoped(`/api/sessions/${encodeURIComponent(sessionId)}`, agentId), {
      method: 'PUT',
      body: JSON.stringify(agentId ? { pinned, agent_id: agentId } : { pinned }),
    })
  }

  /** This session's effective model + permission (and team), with the catalog to switch. */
  async getSessionSettings(sessionId: string, agentId?: string): Promise<{ status: string } & SessionSettingsState> {
    return this.request(this.scoped(`/api/sessions/${encodeURIComponent(sessionId)}/settings`, agentId))
  }

  /** Set or clear this session's model / permission override, or its team
   *  members. Pass null to a field to drop the override and follow the global
   *  default (null members = nobody invited). */
  async updateSessionSettings(
    sessionId: string,
    body: { provider?: string | null; model?: string | null; permission?: string | null; members?: string[] | null },
    agentId?: string
  ): Promise<{ status: string } & Partial<SessionSettingsState> & { message?: string }> {
    return this.request(this.scoped(`/api/sessions/${encodeURIComponent(sessionId)}/settings`, agentId), {
      method: 'POST',
      body: JSON.stringify(agentId ? { ...body, agent_id: agentId } : body),
    })
  }

  async generateSessionTitle(
    sessionId: string,
    userMessage: string,
    assistantReply?: string,
    agentId?: string
  ): Promise<{ status: string; title: string }> {
    const body: Record<string, unknown> = { user_message: userMessage, assistant_reply: assistantReply }
    if (agentId) body.agent_id = agentId
    return this.request(this.scoped(`/api/sessions/${encodeURIComponent(sessionId)}/generate_title`, agentId), {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async clearContext(sessionId: string, agentId?: string): Promise<{ status: string; context_start_seq: number }> {
    return this.request(this.scoped(`/api/sessions/${encodeURIComponent(sessionId)}/clear_context`, agentId), {
      method: 'POST',
      body: JSON.stringify(agentId ? { agent_id: agentId } : {}),
    })
  }

  async getContextUsage(sessionId: string, agentId?: string): Promise<{ status: string } & ContextUsage> {
    return this.request(this.scoped(`/api/sessions/${encodeURIComponent(sessionId)}/context_usage`, agentId))
  }

  // Synchronous manual compaction (same logic as the /compact command). Returns
  // the refreshed usage so the caller can redraw the chart without a refetch.
  async compactContext(
    sessionId: string,
    agentId?: string,
  ): Promise<{
    status: string
    ok?: boolean
    available?: boolean
    compacted_turns?: number
    before?: number
    after?: number
    usage?: ContextUsage | null
  }> {
    return this.request(this.scoped(`/api/sessions/${encodeURIComponent(sessionId)}/compact_context`, agentId), {
      method: 'POST',
      body: JSON.stringify(agentId ? { agent_id: agentId } : {}),
    })
  }

  async getHistory(
    sessionId: string,
    page = 1,
    pageSize = 20,
    agentId?: string,
    untilSeq?: number
  ): Promise<HistoryPage> {
    const until = untilSeq != null ? `&until_seq=${untilSeq}` : ''
    return this.request<{ status: string } & HistoryPage>(
      this.scoped(
        `/api/history?session_id=${encodeURIComponent(sessionId)}&page=${page}&page_size=${pageSize}${until}`,
        agentId
      )
    )
  }

  // Lightweight index of a session's user messages for the navigation timeline.
  // Returns the whole conversation's user turns at once (no pagination): the
  // payload is small since it only carries {seq, preview, created_at}.
  async getUserMessages(sessionId: string, agentId?: string): Promise<UserMessageIndex> {
    return this.request<{ status: string } & UserMessageIndex>(
      this.scoped(`/api/history/user_messages?session_id=${encodeURIComponent(sessionId)}`, agentId)
    )
  }

  // ---------------------------------------------------------
  // Config
  // ---------------------------------------------------------

  async getConfig(): Promise<ConfigData> {
    return this.request<{ status: string } & ConfigData>('/config')
  }

  async updateConfig(updates: Record<string, unknown>): Promise<{ status: string; applied: Record<string, unknown> }> {
    return this.request('/config', {
      method: 'POST',
      body: JSON.stringify({ updates }),
    })
  }

  // ---------------------------------------------------------
  // Models console
  // ---------------------------------------------------------

  async getModels(): Promise<ModelsData> {
    return this.request<{ status: string } & ModelsData>('/api/models')
  }

  async modelsAction(action: ModelsAction): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/models', {
      method: 'POST',
      body: JSON.stringify(action),
    })
  }

  // ---------------------------------------------------------
  // Agents / team roster (multi-Agent mode)
  //
  // A legacy single-Agent backend still answers GET /api/agents with a
  // one-entry roster (the synthesized default Agent), so these are safe to call
  // everywhere; the UI decides whether to surface multi-Agent affordances based
  // on the roster size, never by assuming the endpoint is absent.
  // ---------------------------------------------------------

  async getAgents(): Promise<RosterSnapshot> {
    return this.request<RosterSnapshot>('/api/agents')
  }

  async agentAction(
    body: Record<string, unknown>
  ): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/agents', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  // A cache-busting URL for an Agent's uploaded avatar. `version` should change
  // whenever the image is replaced so the <img> refetches (the roster revision
  // works well as the token). Carries the auth token for password-protected
  // backends, like the other file endpoints.
  agentAvatarUrl(agentId: string, version: string): string {
    return this.withToken(
      `${this.baseUrl}/api/agents/${encodeURIComponent(agentId)}/avatar?v=${encodeURIComponent(version)}`
    )
  }

  async uploadAgentAvatar(agentId: string, file: File): Promise<{ status: string; message?: string; revision?: string }> {
    const formData = new FormData()
    formData.append('avatar', file)
    return this.postFormData(`/api/agents/${encodeURIComponent(agentId)}/avatar`, formData)
  }

  // An Agent's editable core files (AGENT.md / USER.md / RULE.md / MEMORY.md).
  // The read returns the current content plus a revision used for optimistic
  // concurrency on write.
  async getAgentCoreFile(
    agentId: string,
    filename: string
  ): Promise<{ status: string; content?: string; revision?: string; message?: string }> {
    return this.request(
      `/api/agents/${encodeURIComponent(agentId)}/files/${encodeURIComponent(filename)}`
    )
  }

  async saveAgentCoreFile(
    agentId: string,
    filename: string,
    content: string,
    revision?: string
  ): Promise<{ status: string; revision?: string; message?: string }> {
    return this.request(
      `/api/agents/${encodeURIComponent(agentId)}/files/${encodeURIComponent(filename)}`,
      {
        method: 'PUT',
        body: JSON.stringify({ content, revision }),
      }
    )
  }

  // ---------------------------------------------------------
  // Channels
  // ---------------------------------------------------------

  async getChannels(): Promise<ChannelInfo[]> {
    // The list is ordered per language, and this window's language is kept
    // locally, so it may differ from the backend's global setting.
    const data = await this.request<{ status: string; channels: ChannelInfo[] }>(
      `/api/channels?lang=${getLang()}`
    )
    return data.channels
  }

  // Full channels response including the multi-Agent fields. A legacy backend
  // simply omits `multi_agent`/`instances`, so callers see them as undefined
  // and fall back to the single-instance path — no behavior change.
  async getChannelsFull(): Promise<ChannelsResponse> {
    return this.request<ChannelsResponse>(`/api/channels?lang=${getLang()}`)
  }

  async channelAction(
    action: ChannelAction,
    channel: string,
    config?: Record<string, unknown>,
    instanceId?: string
  ): Promise<Record<string, unknown> & { status: string }> {
    // instance_id is only meaningful in multi-Agent mode (multi-instance
    // channels). Sending an empty string is what "create a new instance" means
    // to the backend; omitting it entirely keeps the legacy per-type path.
    const body: Record<string, unknown> = { action, channel, config }
    if (instanceId !== undefined) body.instance_id = instanceId
    return this.request('/api/channels', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  // Weixin QR login
  async getWeixinQr(): Promise<{ status: string; qrcode_url?: string; qr_image?: string; source?: string; message?: string }> {
    return this.request('/api/weixin/qrlogin')
  }

  async weixinQrAction(action: 'poll' | 'refresh'): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/weixin/qrlogin', {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
  }

  // Feishu one-click register
  async getFeishuRegister(): Promise<{ status: string; register_status?: string; qrcode_url?: string; qr_image?: string; expire_in?: number; message?: string }> {
    return this.request('/api/feishu/register')
  }

  async feishuRegisterPoll(): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/feishu/register', {
      method: 'POST',
      body: JSON.stringify({ action: 'poll' }),
    })
  }

  // ---------------------------------------------------------
  // Tools & skills
  // ---------------------------------------------------------

  async getTools(): Promise<ToolInfo[]> {
    const data = await this.request<{ status: string; tools: ToolInfo[] }>('/api/tools')
    return data.tools
  }

  // The global Skills page stays global (no agent scope), matching the web
  // console: it manages the shared skill library. Per-Agent skill *selection*
  // is a separate concern handled on the Agents page, which passes an explicit
  // agentId to read/write that Agent's subset.
  async getSkills(agentId?: string): Promise<SkillInfo[]> {
    const path = agentId ? `/api/skills?agent_id=${encodeURIComponent(agentId)}` : '/api/skills'
    const data = await this.request<{ status: string; skills: SkillInfo[] }>(path)
    return data.skills
  }

  async toggleSkill(name: string, action: 'open' | 'close'): Promise<ApiResult> {
    return this.request('/api/skills', {
      method: 'POST',
      body: JSON.stringify({ action, name }),
    })
  }

  /**
   * Read a skill's definition file.
   *
   * Addressed by name rather than by path: which file a name resolves to is the
   * loader's business, and a builtin skill's file sits outside the workspace.
   */
  async readSkill(name: string): Promise<SkillContent & ApiResult> {
    return this.request(`/api/skills/content?name=${encodeURIComponent(name)}`)
  }

  /**
   * Save a skill's definition file.
   *
   * Refuses a skill that ships with the installation, and answers
   * `code === 'conflict'` when the file changed since `expectedMtime` - both
   * with status 200, so the caller has to look.
   */
  async writeSkill(args: {
    name: string
    content: string
    expectedMtime?: number | null
  }): Promise<WorkspaceWriteResult & ApiResult> {
    return this.request('/api/skills/content', {
      method: 'POST',
      body: JSON.stringify({
        name: args.name,
        content: args.content,
        expected_mtime: args.expectedMtime ?? null,
      }),
    })
  }

  // ---------------------------------------------------------
  // Memory
  // ---------------------------------------------------------

  async getMemoryList(
    page = 1,
    pageSize = 20,
    category: MemoryCategory = 'memory',
    agentId?: string
  ): Promise<MemoryPage> {
    return this.request<{ status: string } & MemoryPage>(
      this.scoped(`/api/memory?page=${page}&page_size=${pageSize}&category=${category}`, agentId)
    )
  }

  /**
   * Read a memory file.
   *
   * `rel_path` is what an edit needs: memory files are addressed by name and
   * category here, but the read and write endpoints take a path. `agentId`
   * scopes the read to the right agent's workspace in a multi-agent setup.
   */
  async getMemoryDoc(
    filename: string,
    category: MemoryCategory = 'memory',
    agentId?: string
  ): Promise<MemoryDoc & ApiResult> {
    return this.request(
      this.scoped(
        `/api/memory/content?filename=${encodeURIComponent(filename)}&category=${category}`,
        agentId
      )
    )
  }

  // ---------------------------------------------------------
  // Knowledge
  // ---------------------------------------------------------

  async getKnowledgeList(agentId?: string): Promise<KnowledgeList> {
    return this.request<{ status: string } & KnowledgeList>(this.scoped('/api/knowledge/list', agentId))
  }

  async readKnowledge(
    path: string,
    agentId?: string
  ): Promise<{ status: string; content: string; path: string; dir?: string }> {
    return this.request(this.scoped(`/api/knowledge/read?path=${encodeURIComponent(path)}`, agentId))
  }

  async getKnowledgeGraph(agentId?: string): Promise<KnowledgeGraph> {
    return this.request<KnowledgeGraph>(this.scoped('/api/knowledge/graph', agentId))
  }

  async knowledgeAction(req: KnowledgeAction): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/knowledge/action', {
      method: 'POST',
      body: JSON.stringify(this.withAgent(req as unknown as Record<string, unknown>)),
    })
  }

  // Bulk import: upload .md/.txt files into a target category (multipart).
  async importKnowledge(
    files: File[],
    targetCategory: string,
    agentId?: string
  ): Promise<{ status: string; message?: string; payload?: KnowledgeImportPayload }> {
    const formData = new FormData()
    formData.append('target_category', targetCategory)
    formData.append('conflict_strategy', 'rename')
    const scope = (agentId ?? this.activeAgentId) || ''
    if (scope) formData.append('agent_id', scope)
    files.forEach((file) => formData.append('files', file, file.name))
    return this.postFormData('/api/knowledge/import', formData)
  }

  // ---------------------------------------------------------
  // Scheduler
  // ---------------------------------------------------------

  // In multi-Agent mode we ask for the aggregate list across every Agent by
  // sending an explicit empty agent_id (the backend treats that as "all"),
  // mirroring the web console. Single-Agent mode omits the param entirely so
  // the legacy request is unchanged.
  async getSchedulerTasks(): Promise<SchedulerTask[]> {
    const path = this.activeAgentId ? '/api/scheduler?agent_id=' : '/api/scheduler'
    const data = await this.request<{ status: string; tasks: SchedulerTask[] }>(path)
    return data.tasks
  }

  // Execution history for scheduled tasks, newest first. In multi-Agent mode we
  // send an explicit empty agent_id so the backend returns the whole team's
  // history (mirroring the task list); single-Agent mode omits the param.
  // Pass a taskId to narrow to one task's runs.
  async getSchedulerRuns(taskId = '', limit = 100, offset = 0): Promise<SchedulerRun[]> {
    const qs = new URLSearchParams()
    if (this.activeAgentId) qs.set('agent_id', '')
    if (taskId) qs.set('task_id', taskId)
    if (limit) qs.set('limit', String(limit))
    if (offset) qs.set('offset', String(offset))
    const query = qs.toString()
    const path = query ? `/api/scheduler/runs?${query}` : '/api/scheduler/runs'
    const data = await this.request<{ status: string; runs: SchedulerRun[] }>(path)
    return data.runs || []
  }

  // Delete a single execution-history record from the runs ledger. Removes only
  // the list item; the delivered message in the session history is untouched.
  async deleteSchedulerRun(runId: string): Promise<void> {
    await this.request<{ status: string }>('/api/scheduler/runs/delete', {
      method: 'POST',
      body: JSON.stringify({ run_id: runId }),
    })
  }

  // Runs across ALL Agents that started after `since` (epoch seconds). Powers
  // the cross-session scheduler notification poll: a scheduled task can fire
  // into a session (any Agent) the user isn't viewing, so this is deliberately
  // NOT scoped to the active Agent — the notifier decides what to surface.
  async getSchedulerRunsSince(since: number, limit = 20): Promise<SchedulerRun[]> {
    const qs = new URLSearchParams()
    qs.set('since', String(Math.floor(since)))
    if (limit) qs.set('limit', String(limit))
    const data = await this.request<{ status: string; runs: SchedulerRun[] }>(
      `/api/scheduler/runs?${qs.toString()}`
    )
    return data.runs || []
  }

  // Full detail for one run: the complete delivered body recovered from the
  // receiver's session, or null (fall back to preview). Opened on demand when a
  // history record is clicked, so the list stays a light index.
  async getSchedulerRunDetail(runId: string): Promise<SchedulerRunDetail | null> {
    const data = await this.request<{ status: string; run?: SchedulerRunDetail }>(
      `/api/scheduler/runs/detail?run_id=${encodeURIComponent(runId)}`
    )
    return data.run || null
  }

  // Task mutations route to the owning Agent's store via its agent_id. Passing
  // an empty string (or omitting in single-Agent mode) keeps the legacy path.
  async runTask(taskId: string, agentId = ''): Promise<ApiResult> {
    return this.request('/api/scheduler/run', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, agent_id: agentId }),
    })
  }

  async toggleTask(taskId: string, enabled: boolean, agentId = ''): Promise<{ status: string; task: SchedulerTask }> {
    return this.request('/api/scheduler/toggle', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, enabled, agent_id: agentId }),
    })
  }

  async updateTask(
    taskId: string,
    updates: Partial<Pick<SchedulerTask, 'name' | 'enabled' | 'schedule' | 'action'>>,
    agentId = ''
  ): Promise<{ status: string; task: SchedulerTask }> {
    return this.request('/api/scheduler/update', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, agent_id: agentId, ...updates }),
    })
  }

  async deleteTask(taskId: string, agentId = ''): Promise<ApiResult> {
    return this.request('/api/scheduler/delete', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, agent_id: agentId }),
    })
  }

  // Create a cross-channel task for a trusted recipient. The backend derives the
  // owning Agent from the recipient's channel instance and rejects any receiver
  // not already in the trusted directory, so the client only names the target.
  async createTask(payload: {
    name: string
    enabled: boolean
    schedule: TaskSchedule
    action: TaskAction
  }): Promise<{ status: string; task?: SchedulerTask; message?: string }> {
    return this.request('/api/scheduler/create', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  }

  // Step 1 of the create/edit picker: channel instances a task can deliver
  // through (web/unknown excluded). Each carries a friendly name, its bound
  // Agent, and how many trusted recipients it has.
  async getSchedulerInstances(): Promise<SchedulerInstance[]> {
    const data = await this.request<{ status: string; instances: SchedulerInstance[] }>(
      '/api/scheduler/instances'
    )
    return data.instances || []
  }

  // Step 2 of the picker: every trusted recipient learned from inbound messages,
  // shared across Agents. The UI scopes them to the chosen instance client-side.
  async getSchedulerRecipients(): Promise<TaskRecipient[]> {
    const data = await this.request<{ status: string; recipients: TaskRecipient[] }>(
      '/api/scheduler/recipients'
    )
    return data.recipients || []
  }

  // Set a channel instance's friendly display name. Goes through the shared
  // /api/channels endpoint with the 'rename' action; does not touch credentials
  // or the live connection, so renaming never interrupts a running channel.
  async renameChannelInstance(
    channel: string,
    instanceId: string,
    name: string
  ): Promise<{ status: string; instance_id?: string; name?: string; message?: string }> {
    return this.request('/api/channels', {
      method: 'POST',
      body: JSON.stringify({ action: 'rename', channel, instance_id: instanceId, name }),
    })
  }

  // ---------------------------------------------------------
  // Voice
  // ---------------------------------------------------------

  async voiceAsr(audio: File | Blob): Promise<{ status: string; text?: string; audio_url?: string; message?: string }> {
    const formData = new FormData()
    // Match the file suffix to the actual container so the backend picks the
    // right extension (mirrors the web console's mic upload).
    const extByMime: Record<string, string> = {
      'audio/webm': 'webm',
      'audio/ogg': 'ogg',
      'audio/mp4': 'm4a',
      'audio/mpeg': 'mp3',
    }
    const mime = (audio.type || '').split(';')[0]
    const name =
      audio instanceof File && audio.name ? audio.name : `recording.${extByMime[mime] || 'webm'}`
    formData.append('file', audio, name)
    return this.postFormData('/api/voice/asr', formData)
  }

  async voiceTts(text: string, sessionId?: string): Promise<{ status: string; audio_url?: string; message?: string }> {
    return this.request('/api/voice/tts', {
      method: 'POST',
      body: JSON.stringify({ text, session_id: sessionId }),
    })
  }

  // ---------------------------------------------------------
  // Named teams (sidebar "Teams"; shared with the web console)
  // ---------------------------------------------------------

  // Saved, leader-led Agent groups (agent/teams_store.py). A team is opened
  // as — or reattached to — a group conversation; the rosters themselves are
  // persisted by the backend, so the two consoles see the same list. The list
  // read is best-effort, exactly like the web console's loadTeams(): a
  // missing endpoint (older backend) just leaves the section empty.

  async listTeamGroups(): Promise<TeamGroup[]> {
    try {
      const data = await this.request<{ status: string; teams?: TeamGroup[] }>('/api/team-groups')
      return data.status === 'success' ? data.teams || [] : []
    } catch {
      return []
    }
  }

  async getTeamGroup(teamId: string): Promise<TeamGroup | null> {
    try {
      const data = await this.request<{ status: string; team?: TeamGroup }>(
        `/api/team-groups/${encodeURIComponent(teamId)}`
      )
      return data.status === 'success' ? data.team || null : null
    } catch {
      return null
    }
  }

  async createTeamGroup(name: string, leader: string, members: string[]): Promise<TeamGroup> {
    const data = await this.request<{ status: string; message?: string; team?: TeamGroup }>(
      '/api/team-groups',
      {
        method: 'POST',
        body: JSON.stringify({ name, leader, members }),
      }
    )
    // The backend answers 200 even on validation failures, so the status
    // field decides — surfacing its message keeps "name already taken" etc.
    // readable, like the web console does.
    if (data.status !== 'success' || !data.team) {
      throw new Error(data.message || 'Could not create the team')
    }
    return data.team
  }

  async deleteTeamGroup(teamId: string): Promise<ApiResult> {
    return this.request(`/api/team-groups/${encodeURIComponent(teamId)}`, {
      method: 'DELETE',
    })
  }

  // ---------------------------------------------------------
  // Logs / version
  // ---------------------------------------------------------

  createLogStream(): EventSource {
    return new EventSource(this.withToken(`${this.baseUrl}/api/logs`))
  }

  // Full run.log as a downloadable attachment. Carries the token in the query
  // string like the other file endpoints so it works under web_password.
  getLogDownloadUrl(): string {
    return this.withToken(`${this.baseUrl}/api/logs/download`)
  }

  async getVersion(): Promise<string> {
    const data = await this.request<{ version: string }>('/api/version')
    return data.version
  }

  // ---------------------------------------------------------
  // Auth (web_password) — placeholder for future use
  // ---------------------------------------------------------

  async authCheck(): Promise<{ status: string; auth_required: boolean; authenticated?: boolean }> {
    return this.request('/auth/check')
  }

  async authLogin(password: string): Promise<ApiResult & { token?: string }> {
    const res = await this.request<ApiResult & { token?: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    })
    if (res.status === 'success' && res.token) {
      this.setAuthToken(res.token)
    }
    return res
  }

  async authLogout(): Promise<ApiResult> {
    this.setAuthToken(null)
    return this.request('/auth/logout', { method: 'POST' })
  }
}

export const apiClient = new ApiClient()
export default apiClient
