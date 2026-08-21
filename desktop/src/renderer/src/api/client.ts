import type {
  ConfigData,
  ChannelInfo,
  ChannelAction,
  SkillInfo,
  ToolInfo,
  MemoryItem,
  MemoryCategory,
  MemoryPage,
  SchedulerTask,
  Attachment,
  SessionsPage,
  SessionSettingsState,
  HistoryPage,
  ModelsData,
  ModelsAction,
  KnowledgeList,
  KnowledgeGraph,
  KnowledgeAction,
  KnowledgeImportPayload,
  WorkspaceEntry,
  WorkspaceTree,
  ProjectState,
} from '../types'
import { getLang } from '../i18n'

interface ApiResult {
  status: string
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

  private async request<T>(path: string, options?: RequestInit): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
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
    const url = `${this.baseUrl}${path}`
    // A plain `fetch` that never reaches the backend throws a bare
    // `TypeError: Failed to fetch`, which is useless in a bug report. The most
    // common cause here is a transient connection refusal (the local backend
    // still booting, or briefly restarting), so retry once after a short delay
    // and, on a persistent network failure, raise an actionable message that
    // names the target URL instead of the opaque browser error.
    let lastErr: unknown
    for (let attempt = 0; attempt < 2; attempt++) {
      if (attempt > 0) await new Promise((r) => setTimeout(r, 600))
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
    console.error(`[api] upload network failure to ${url}:`, lastErr)
    throw new Error(
      `无法连接到本地服务 (${url})，请确认客户端后台正在运行后重试`,
    )
  }

  // ---------------------------------------------------------
  // Chat / messages
  // ---------------------------------------------------------

  async sendMessage(
    sessionId: string,
    message: string,
    opts?: { stream?: boolean; attachments?: Attachment[]; isVoice?: boolean; lang?: string }
  ): Promise<{ status: string; request_id: string; stream: boolean; inline_reply?: string }> {
    return this.request('/message', {
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        message,
        stream: opts?.stream ?? true,
        attachments: opts?.attachments,
        is_voice: opts?.isVoice ?? false,
        lang: opts?.lang,
      }),
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
  }): Promise<{ status: string; deleted: number }> {
    return this.request('/api/messages/delete', {
      method: 'POST',
      body: JSON.stringify({
        session_id: opts.sessionId,
        user_seq: opts.userSeq,
        delete_user: opts.deleteUser ?? true,
        cascade: opts.cascade ?? false,
      }),
    })
  }

  // ---------------------------------------------------------
  // Upload / files
  // ---------------------------------------------------------

  async uploadFile(file: File, sessionId?: string): Promise<{
    status: string
    file_path: string
    file_name: string
    file_type: string
    preview_url: string
    message?: string
  }> {
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

  async getSessions(page = 1, pageSize = 50): Promise<SessionsPage> {
    return this.request<{ status: string } & SessionsPage>(`/api/sessions?page=${page}&page_size=${pageSize}`)
  }

  async deleteSession(sessionId: string): Promise<ApiResult> {
    return this.request(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
  }

  async renameSession(sessionId: string, title: string): Promise<ApiResult> {
    return this.request(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'PUT',
      body: JSON.stringify({ title }),
    })
  }

  /** Pin or unpin a session; pinned sessions sort to the top of their group. */
  async setSessionPinned(sessionId: string, pinned: boolean): Promise<ApiResult> {
    return this.request(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'PUT',
      body: JSON.stringify({ pinned }),
    })
  }

  /** This session's effective model + permission, with the catalog to switch. */
  async getSessionSettings(sessionId: string): Promise<{ status: string } & SessionSettingsState> {
    return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/settings`)
  }

  /** Set or clear this session's model / permission override. Pass null to a
   *  field to drop the override and follow the global default. */
  async updateSessionSettings(
    sessionId: string,
    body: { provider?: string | null; model?: string | null; permission?: string | null }
  ): Promise<{ status: string } & Partial<SessionSettingsState> & { message?: string }> {
    return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/settings`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }

  async generateSessionTitle(sessionId: string, userMessage: string, assistantReply?: string): Promise<{ status: string; title: string }> {
    return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/generate_title`, {
      method: 'POST',
      body: JSON.stringify({ user_message: userMessage, assistant_reply: assistantReply }),
    })
  }

  async clearContext(sessionId: string): Promise<{ status: string; context_start_seq: number }> {
    return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/clear_context`, { method: 'POST' })
  }

  async getHistory(sessionId: string, page = 1, pageSize = 20): Promise<HistoryPage> {
    return this.request<{ status: string } & HistoryPage>(
      `/api/history?session_id=${encodeURIComponent(sessionId)}&page=${page}&page_size=${pageSize}`
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

  async channelAction(
    action: ChannelAction,
    channel: string,
    config?: Record<string, unknown>
  ): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/channels', {
      method: 'POST',
      body: JSON.stringify({ action, channel, config }),
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

  async getSkills(): Promise<SkillInfo[]> {
    const data = await this.request<{ status: string; skills: SkillInfo[] }>('/api/skills')
    return data.skills
  }

  async toggleSkill(name: string, action: 'open' | 'close'): Promise<ApiResult> {
    return this.request('/api/skills', {
      method: 'POST',
      body: JSON.stringify({ action, name }),
    })
  }

  // ---------------------------------------------------------
  // Memory
  // ---------------------------------------------------------

  async getMemoryList(page = 1, pageSize = 20, category: MemoryCategory = 'memory'): Promise<MemoryPage> {
    return this.request<{ status: string } & MemoryPage>(
      `/api/memory?page=${page}&page_size=${pageSize}&category=${category}`
    )
  }

  async getMemoryContent(filename: string, category: MemoryCategory = 'memory'): Promise<string> {
    const data = await this.request<{ status: string; content: string }>(
      `/api/memory/content?filename=${encodeURIComponent(filename)}&category=${category}`
    )
    return data.content
  }

  // ---------------------------------------------------------
  // Knowledge
  // ---------------------------------------------------------

  async getKnowledgeList(): Promise<KnowledgeList> {
    return this.request<{ status: string } & KnowledgeList>('/api/knowledge/list')
  }

  async readKnowledge(path: string): Promise<{ status: string; content: string; path: string; dir?: string }> {
    return this.request(`/api/knowledge/read?path=${encodeURIComponent(path)}`)
  }

  async getKnowledgeGraph(): Promise<KnowledgeGraph> {
    return this.request<KnowledgeGraph>('/api/knowledge/graph')
  }

  async knowledgeAction(req: KnowledgeAction): Promise<Record<string, unknown> & { status: string }> {
    return this.request('/api/knowledge/action', {
      method: 'POST',
      body: JSON.stringify(req),
    })
  }

  // Bulk import: upload .md/.txt files into a target category (multipart).
  async importKnowledge(
    files: File[],
    targetCategory: string
  ): Promise<{ status: string; message?: string; payload?: KnowledgeImportPayload }> {
    const formData = new FormData()
    formData.append('target_category', targetCategory)
    formData.append('conflict_strategy', 'rename')
    files.forEach((file) => formData.append('files', file, file.name))
    return this.postFormData('/api/knowledge/import', formData)
  }

  // ---------------------------------------------------------
  // Scheduler
  // ---------------------------------------------------------

  async getSchedulerTasks(): Promise<SchedulerTask[]> {
    const data = await this.request<{ status: string; tasks: SchedulerTask[] }>('/api/scheduler')
    return data.tasks
  }

  async runTask(taskId: string): Promise<ApiResult> {
    return this.request('/api/scheduler/run', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId }),
    })
  }

  async toggleTask(taskId: string, enabled: boolean): Promise<{ status: string; task: SchedulerTask }> {
    return this.request('/api/scheduler/toggle', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, enabled }),
    })
  }

  async updateTask(taskId: string, updates: Partial<Pick<SchedulerTask, 'name' | 'enabled' | 'schedule' | 'action'>>): Promise<{ status: string; task: SchedulerTask }> {
    return this.request('/api/scheduler/update', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, ...updates }),
    })
  }

  async deleteTask(taskId: string): Promise<ApiResult> {
    return this.request('/api/scheduler/delete', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId }),
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
